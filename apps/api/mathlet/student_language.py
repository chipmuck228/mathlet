"""Separate learner prose from editorial reports; retain original evidence in the workbench."""
import re

ROLE=re.compile(r'(?<![A-Za-z0-9_])(core|optional|support|primary|uncertain|excluded|pending)(?![A-Za-z0-9_])',re.I)
REPORT=re.compile(r'知识映射|未(?:单独)?成卡|教师.{0,14}(?:核对|核查|审核|决定|判断)|(?:需|待|请).{0,8}教师|(?:研究|知识|单元)?终稿|工作稿|待审核|未经.{0,6}核验|AI.{0,6}(?:生成|复核)|不构成.{0,12}标准答案')
OPAQUE=re.compile(r'(?<![A-Za-z0-9])[a-f0-9]{12,64}(?![A-Za-z0-9])',re.I)
ROLE_NAMES={'core':'主要用到本节知识','optional':'还可以用到的知识','support':'辅助知识','primary':'主要知识','uncertain':'需要进一步判断','excluded':'本节不使用','pending':'尚未分类'}

def aliases(body,know,sources=()):
    refs={k['ref']:k['title'] for k in know['items']}
    ids=list(dict.fromkeys(body.get('selected_analysis_ids',[])+[s['id'] for s in sources]))
    names={key:('例题 '+str(i+1) if key in body.get('selected_analysis_ids',[]) else '参考题 '+str(i+1)) for i,key in enumerate(ids)}
    result=refs|names
    for n in range(4,13):
        prefixes={}
        for key,label in names.items():
            if len(key)>=n:prefixes.setdefault(key[:n],[]).append(label)
        result.update({key:values[0] for key,values in prefixes.items() if len(set(values))==1})
    return result

def outside_math(text,convert):
    # Formula delimiters and their contents are protected; do not rename mathematical symbols.
    result=[];at=0
    for match in re.finditer(r'\\\(.*?\\\)',text,re.S):
        result.extend([convert(text[at:match.start()]),match.group()]);at=match.end()
    result.append(convert(text[at:]))
    return ''.join(result)

def public_text(value,names):
    keys=sorted(names,key=len,reverse=True)
    pattern=re.compile(r'(?<![A-Za-z0-9_])(?:'+ '|'.join(re.escape(k) for k in keys)+r')(?![A-Za-z0-9_])') if keys else None
    def convert(s):
        if pattern:s=pattern.sub(lambda m:names[m.group()],s)
        s=re.sub(r'`((?:例题|参考题) [0-9]+)`',lambda match:match.group(1),s)
        return ROLE.sub(lambda m:ROLE_NAMES[m.group().lower()],s)
    return outside_math(value,convert)

def problems(value,names):
    found=[]
    if ROLE.search(value):found.append('内部分类标签')
    if re.search(r'(?:知识|条目)\s*[0-9]{1,3}(?![0-9])',value):found.append('引用占位名')
    if REPORT.search(value):found.append('教师审核或教研说明')
    if any(any(c.isalpha() for c in m.group()) for m in OPAQUE.finditer(value)):found.append('内部编号')
    for key in names:
        if len(key)>=4 and any(c.isdigit() for c in key) and re.search(r'(?<![A-Za-z0-9_])'+re.escape(key)+r'(?![A-Za-z0-9_])',value):
            found.append('内部引用编号');break
    return list(dict.fromkeys(found))

def prose_fields(p):
    values=[('导读',p['introduction']),('思路导读',p.get('summary',''))]
    values.extend(('目标',x) for x in p['goals'])
    for k in p['knowledge']:
        values.extend(('知识讲解',k[key]) for key in ['plain_explanation','memory_hint','self_check'])
    values.extend(('思路导语',x['student_lead']) for x in p['cards'])
    values.extend(('训练导语',x['student_lead']) for x in p['training'])
    return values

def copy_issues(p,body,know):
    names=aliases(body,know)
    return [label+'含'+ '／'.join(issues) for label,text in prose_fields(p) if (issues:=problems(text,names))]
