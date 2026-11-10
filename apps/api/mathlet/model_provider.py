"""Local configuration and a bounded OpenAI-compatible Chat Completions transport."""
import json
import os
from pathlib import Path
from typing import Literal
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator
from .db import data_dir

def validate_api_key(value):
    value=value.strip()
    if value and (value[0] in '"\'' or value[-1] in '"\'' or not value.isascii() or any(ord(c)<33 or ord(c)>126 for c in value)):
        raise ValueError('API Key 含非ASCII字符、内部空格或控制字符。请只粘贴密钥本身，不含中文备注、引号或 Bearer 前缀')
    return value


class Provider(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str = 'https://api.openai.com/v1'
    model: str = Field(default='', max_length=160)
    api_key: str = Field(default='', max_length=2000)
    clear_key: bool = False
    json_mode: bool = True
    token_parameter: Literal['auto','max_tokens','max_completion_tokens'] = 'auto'
    thinking_mode: Literal['auto','disabled','enabled'] = 'auto'
    _credential_error: str = PrivateAttr(default='')
    timeout: int = Field(default=90, ge=10, le=180)
    max_calls: int = Field(default=16, ge=3, le=40)
    output_token_budget: int = Field(default=30000, ge=6000, le=100000)
    @field_validator('base_url')
    @classmethod
    def validate_url(cls, value):
        if not value.strip().isascii() or any(c.isspace() for c in value.strip()):
            raise ValueError('服务地址不能包含中文备注或空格，请填写完整英文URL')
        p = urlsplit(value.strip())
        if not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('服务地址不能包含账号、查询参数或片段')
        if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in {'127.0.0.1','localhost','::1'}):
            raise ValueError('外部模型服务必须使用 HTTPS；本机服务可用 HTTP')
        return value.strip().rstrip('/')
    @field_validator('api_key')
    @classmethod
    def key(cls, value): return validate_api_key(value)

    @field_validator('model')
    @classmethod
    def clean(cls, value):
        if '\r' in value or '\n' in value: raise ValueError('不能包含换行')
        return value.strip()


def config_path(): return data_dir() / 'knowledge-provider.json'


def load_provider():
    path = config_path()
    stored = json.loads(path.read_text()) if path.is_file() else {}
    stored.setdefault('base_url', os.environ.get('MATHLET_MODEL_BASE_URL', 'https://api.openai.com/v1'))
    stored.setdefault('model', os.environ.get('MATHLET_MODEL_NAME', ''))
    if 'api_key' not in stored: stored['api_key'] = os.environ.get('MATHLET_MODEL_API_KEY','')
    try:
        return Provider.model_validate(stored)
    except ValidationError as exc:
        if all(e['loc']==('api_key',) for e in exc.errors()):
            stored['api_key']=''
            config=Provider.model_validate(stored)
            config._credential_error='原保存密钥包含非法字符，请重新粘贴纯API Key并保存；密钥不会显示'
            return config
        raise ValueError('本机模型配置无效，请检查配置文件或重新保存设置') from None


def public_provider(config=None):
    config = config or load_provider()
    data = config.model_dump(exclude={'api_key','clear_key'})
    return data | {'api_key_configured': bool(config.api_key), 'ready': bool(config.api_key and config.model), 'credential_error':config._credential_error}


def save_provider(body):
    old = load_provider()
    if not body.api_key and not body.clear_key: body.api_key = old.api_key
    if body.clear_key: body.api_key = ''
    data = body.model_dump(exclude={'clear_key'})
    # Atomic write, local-only file; key is never returned by an endpoint.
    with tempfile.NamedTemporaryFile(mode='w', dir=data_dir(), delete=False, encoding='utf-8') as f:
        temp = Path(f.name); os.chmod(temp, 0o600)
        json.dump(data, f, ensure_ascii=False)
    temp.replace(config_path())
    return public_provider(body)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class ModelOutputError(ValueError):
    def __init__(self,message,content,usage):
        super().__init__(message)
        self.raw_response=content if isinstance(content,str) else ''
        self.usage=usage


def effective_options(config: Provider, max_tokens: int):
    token_field=config.token_parameter
    if token_field=='auto': token_field='max_completion_tokens' if config.model.startswith(('gpt-5','o1','o3','o4')) else 'max_tokens'
    options={'model':config.model,token_field:max_tokens}
    if config.json_mode: options['response_format']={'type':'json_object'}
    host=urlsplit(config.base_url).hostname
    if host=='api.deepseek.com':
        # Knowledge authoring needs final JSON; default DeepSeek thinking can consume
        # the whole small output allowance before content is produced.
        options['thinking']={'type':'disabled' if config.thinking_mode=='auto' else config.thinking_mode}
    elif config.thinking_mode!='auto':
        raise ValueError('此思考模式开关当前仅用于官方DeepSeek接口，其他服务请选择自动')
    return options


def generate(config: Provider, system: str, payload: dict, max_tokens: int):
    validate_api_key(config.api_key)
    request_body = effective_options(config,max_tokens) | {'messages': [
        {'role':'system','content':system},
        {'role':'user','content':json.dumps(payload, ensure_ascii=False)}]}
    req = Request(config.base_url + '/chat/completions', data=json.dumps(request_body).encode(),
                  headers={'Content-Type':'application/json','Authorization':'Bearer '+config.api_key}, method='POST')
    try:
        with build_opener(NoRedirect()).open(req, timeout=config.timeout) as response:
            raw = response.read(2_000_001)
        if len(raw)>2_000_000: raise ValueError('模型响应超过2MB限制')
        result=json.loads(raw)
        choice=result['choices'][0]
        text=choice['message']['content']
        finish=choice.get('finish_reason','unknown')
        reasoning=bool(choice['message'].get('reasoning_content'))
        if finish=='length':
            raise ModelOutputError(f'模型达到输出长度上限（finish_reason=length；含思考信息={reasoning}），没有完整JSON。DeepSeek知识草案请关闭思考模式后创建新候选',text,result.get('usage'))
        if not isinstance(text,str) or not text.strip():
            raise ModelOutputError(f'模型返回空正文（finish_reason={finish}；含思考信息={reasoning}）。未将思考信息当成知识结果，请检查模式后人工重试',text,result.get('usage'))
        return text, result.get('usage')
    except HTTPError as e:
        raise ValueError(f'模型服务返回 HTTP {e.code}；请检查服务地址、模型、密钥或额度。未自动重试计费调用。') from None
    except UnicodeEncodeError:
        raise ValueError('请求头或服务地址存在不支持的字符，请重新保存纯API Key和英文服务地址') from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('模型服务连接失败或超时；服务端可能已产生用量，重试需人工触发') from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError('模型服务未返回兼容的 Chat Completions 响应') from None
