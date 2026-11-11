"""Strict JSON with bounded, auditable normalization of mathematical escapes.

No quote/bracket guessing, literal evaluation, trailing-comma repair or truncation
recovery. Standard JSON escapes stay standard unless they occur inside explicitly
marked math or a formula field. Ambiguous bare mathematical escapes are rejected.
"""
import json
import re
from .formula_support import COMMANDS

PARSER_VERSION='math-json-v1'
JSON_GUIDANCE='''JSON中的LaTeX反斜杠必须正确转义。使用JSON序列化规则，不要直接把单反斜杠公式粘入JSON字符串；换行写为合法JSON转义。示例：'''+json.dumps({'formula':r'\frac{k}{x}','statement':r'当 \(x\ne 0\) 时，讨论 \(y=\frac{k}{x}\)。'},ensure_ascii=False)+'。不要为了修复格式改动公式、知识ID或字段。'
STRING=re.compile(r'"(?:\\[\s\S]|[^"\\])*"')

class ModelJSONError(ValueError): pass


def parse_model_json(text):
    stripped=text.strip()
    if stripped.startswith('```'):
        match=re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```',stripped)
        if match: stripped=match[1]
    result=[];notes=[];at=0;key=None
    for token in STRING.finditer(stripped):
        result.append(stripped[at:token.start()]);raw=token[0]
        is_key=bool(re.match(r'\s*:',stripped[token.end():]))
        field=None if is_key else key
        inner=raw[1:-1];out=[];i=0;math_end=None
        while i<len(inner):
            char=inner[i]
            if char=='$':
                mark='$$' if inner.startswith('$$',i) else '$'
                math_end=None if math_end==mark else mark
                out.append(mark);i+=len(mark);continue
            if char!='\\' or i+1>=len(inner):out.append(char);i+=1;continue
            next_char=inner[i+1]
            if next_char=='\\':
                # Already escaped JSON: preserve it verbatim and track math markers.
                if i+2<len(inner):
                    following=inner[i+2]
                    if following in '([':math_end=')' if following=='(' else ']'
                    elif following==math_end:math_end=None
                out.append(inner[i:i+2]);i+=2;continue
            if next_char in '"/':out.append(inner[i:i+2]);i+=2;continue
            if next_char=='u' and re.match(r'u[0-9a-fA-F]{4}',inner[i+1:]):
                out.append(inner[i:i+6]);i+=6;continue
            if next_char in '([':
                math_end=')' if next_char=='(' else ']'
                out.append('\\\\'+next_char);notes.append({'position':token.start()+1+i,'kind':'math_delimiter'});i+=2;continue
            if next_char in ')]':
                if next_char==math_end:math_end=None
                out.append('\\\\'+next_char);notes.append({'position':token.start()+1+i,'kind':'math_delimiter'});i+=2;continue
            command=re.match(r'[A-Za-z]+',inner[i+1:])
            name=command[0] if command else ''
            known=name in COMMANDS
            # Brace-taking commands are unambiguous even outside formula delimiters.
            brace_argument=known and inner[i+1+len(name):].startswith('{')
            if known and (next_char not in 'bfnrt' or math_end or field=='formula' or brace_argument):
                out.append('\\\\'+name);notes.append({'position':token.start()+1+i,'kind':'math_command','command':name});i+=1+len(name);continue
            if known and next_char in 'bfnrt' and len(name)>1:
                raise ModelJSONError('[MODEL_JSON_ESCAPE] 模型在未标记公式的正文中使用了有歧义的单反斜杠命令；请让公式使用明确的定界符并遵守JSON转义。原始返回已保留，未猜测修改。')
            if next_char in ',;:!{}|_%# ':
                out.append('\\\\'+next_char);notes.append({'position':token.start()+1+i,'kind':'math_symbol'});i+=2;continue
            # Preserve newline/tab/control/Unicode escapes. Anything else will fail strict JSON.
            out.append(inner[i:i+2]);i+=2
        normalized='"'+''.join(out)+'"';result.append(normalized);at=token.end()
        if is_key:
            try:key=json.loads(normalized)
            except json.JSONDecodeError:key=None
        else:key=None
    result.append(stripped[at:]);normalized=''.join(result)
    def unique_object(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ModelJSONError('[MODEL_JSON_FORMAT] 模型JSON含重复字段，不能判断应保留哪个值；原始返回已保留。')
            result[key]=value
        return result
    try:value=json.loads(normalized,object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        raise ModelJSONError(f'[MODEL_JSON_FORMAT] 模型JSON格式无效（第{exc.lineno}行，第{exc.colno}列）。仅兼容可明确识别的数学反斜杠；不补猜引号、括号或截断内容。原始返回已保留，请人工重试。') from None
    if not isinstance(value,dict):raise ModelJSONError('模型必须返回JSON对象')
    def check_controls(node):
        if isinstance(node,str) and re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',node):
            raise ModelJSONError('[MODEL_JSON_ESCAPE] 模型JSON含不适合数学正文的控制字符，可能是公式反斜杠未转义；原始返回已保留，未静默丢弃。')
        if isinstance(node,dict):
            for key,item in node.items(): check_controls(key);check_controls(item)
        elif isinstance(node,list):
            for item in node:check_controls(item)
    check_controls(value)
    return value,notes
