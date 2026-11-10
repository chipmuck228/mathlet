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

@pytest.mark.parametrize('key',['sk-test中文备注','sk-test\u200b','Bearer sk-test','sk-test note','"sk-test"'])
def test_key_validation_rejects_header_poison_without_exposing_value(key):
    with pytest.raises(ValueError) as error:
        provider.validate_api_key(key)
    assert key not in str(error.value)


def test_deepseek_auto_disables_thinking_but_other_endpoints_do_not_receive_vendor_fields():
    config=provider.Provider(base_url='https://api.deepseek.com',model='deepseek-flash',api_key='test-key')
    assert provider.effective_options(config,1800)['thinking']=={'type':'disabled'}
    assert provider.effective_options(config.model_copy(update={'thinking_mode':'enabled'}),1800)['thinking']=={'type':'enabled'}
    assert 'thinking' not in provider.effective_options(provider.Provider(model='other',api_key='test'),1800)


@pytest.mark.parametrize('finish,text,reasoning,expected',[('length','',True,'输出长度上限'),('stop','   ',False,'空正文')])
def test_failed_model_output_keeps_actual_usage_and_final_text(monkeypatch,finish,text,reasoning,expected):
    class Opener:
        def open(self,req,timeout):
            assert json.loads(req.data)['thinking']=={'type':'disabled'}
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,n):return json.dumps({'choices':[{'message':{'content':text,'reasoning_content':'private reasoning' if reasoning else ''},'finish_reason':finish}],'usage':{'completion_tokens':1800}}).encode()
            return Response()
    monkeypatch.setattr(provider,'build_opener',lambda *_:Opener())
    with pytest.raises(provider.ModelOutputError,match=expected) as error:
        provider.generate(provider.Provider(base_url='https://api.deepseek.com',model='deepseek-flash',api_key='test-key'),'JSON',{},1800)
    assert error.value.raw_response==text
    assert error.value.usage=={'completion_tokens':1800}
    assert 'private reasoning' not in str(error.value)
