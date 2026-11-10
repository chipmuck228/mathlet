import json
from urllib.error import HTTPError
import pytest
from mathlet import model_provider as provider

def test_transport_sends_real_compatible_request_with_key_only_in_header(monkeypatch):
    captured={}
    class Opener:
        def open(self,req,timeout):
            captured['request']=req;captured['timeout']=timeout
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,n):return json.dumps({'choices':[{'message':{'content':'{"items":[]}'},'finish_reason':'stop'}],'usage':{'completion_tokens':10}}).encode()
            return Response()
    monkeypatch.setattr(provider,'build_opener',lambda *_:Opener())
    config=provider.Provider(model='gpt-5-test',api_key='private-test-key')
    text,usage=provider.generate(config,'return JSON',{'title':'数学'},1200)
    req=captured['request'];body=json.loads(req.data)
    assert req.full_url=='https://api.openai.com/v1/chat/completions'
    assert req.get_header('Authorization')=='Bearer private-test-key'
    assert 'private-test-key' not in req.data.decode()
    assert body['max_completion_tokens']==1200 and body['response_format']=={'type':'json_object'}
    assert json.loads(text)=={'items':[]} and usage['completion_tokens']==10

def test_transport_reports_http_failure_without_credentials(monkeypatch):
    class Opener:
        def open(self,*_args,**_kwargs):raise HTTPError('https://example.com',401,'private-test-key',{},None)
    monkeypatch.setattr(provider,'build_opener',lambda *_:Opener())
    with pytest.raises(ValueError,match='HTTP 401') as error:
        provider.generate(provider.Provider(model='m',api_key='private-test-key'),'JSON',{},1000)
    assert 'private-test-key' not in str(error.value)
