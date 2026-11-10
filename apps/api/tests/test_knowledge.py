import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from mathlet.main import app
from mathlet.db import connect, init_db
from mathlet import knowledge_worker as worker
from mathlet.model_provider import load_provider, config_path

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('MATHLET_DATA_DIR',str(tmp_path))
    monkeypatch.delenv('MATHLET_MODEL_API_KEY',raising=False)
    monkeypatch.delenv('MATHLET_MODEL_NAME',raising=False)
    with TestClient(app) as client: yield client

def setup(client,limit=2):
    cfg=client.put('/api/knowledge/provider',json={'model':'test-model','api_key':'test-secret-DO-NOT-RETURN'})
    assert cfg.status_code==200,cfg.text
    assert 'test-secret' not in cfg.text and cfg.json()['ready']
    unit=client.post('/api/knowledge/units',json={'title':'一元一次方程','chapters':['一元一次方程'],'notes':'不含参考答案'}).json()
    run=client.post(f"/api/knowledge/units/{unit['id']}/runs",json={'unit_revision':1,'consent':True,'max_items':limit})
    assert run.status_code==201,run.text
    return unit,run.json()

def body(name='一元一次方程',kind='concept'):
    return {'name':name,'kind':kind,'statement':'只含一个未知数且未知数的次数为1的整式方程。',
        'conditions':'一般式 ax+b=0 中 a≠0。','formula':r'ax+b=0,\quad a\ne 0',
        'positive_example':'2x+1=3','misconception':'a=0 时 ax+b=0 不是一元一次方程。',
        'mastery':'能识别整式条件和非零系数，并解释反例。','method_steps':'','uncertainty':''}

def model(config,system,payload,max_tokens):
    if '先不要展开' in system:
        return json.dumps({'items':[{'name':'一元一次方程','kind':'concept','reason':'复习定义与条件'},{'name':'等式性质','kind':'property','reason':'方程变形依据'}]},ensure_ascii=False),{'total_tokens':101}
    if '展开指定清单' in system:
        return json.dumps({'items':[{'knowledge_id':item['id'],'body':body(item['name'],item['kind'])} for item in payload['items']]},ensure_ascii=False),{'total_tokens':202}
    return json.dumps({'issues':[]}),{'total_tokens':33}

def complete(client,run,monkeypatch):
    monkeypatch.setattr(worker,'generate',model)
    assert worker.run_one_knowledge()
    current=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert current['status']=='awaiting_selection',current
    selected=[i['id'] for i in current['catalog']]
    response=client.post(f"/api/knowledge/runs/{run['id']}/expand",json={'revision':current['revision'],'selected_ids':selected})
    assert response.status_code==200,response.text
    assert worker.run_one_knowledge()
    current=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert current['status']=='completed',current
    return current

def test_generation_review_snapshots_and_regeneration_preserve_teacher_work(client,monkeypatch):
    unit,run=setup(client);current=complete(client,run,monkeypatch)
    assert len(current['calls'])==3
    assert all(i['review_state']=='pending' and i['scope']=='pending' for i in current['items'])
    assert client.post(f"/api/knowledge/runs/{run['id']}/versions",json={'revision':current['revision']}).status_code==422
    selected=[{'id':i['id'],'revision':i['revision']} for i in current['items']]
    assert client.post(f"/api/knowledge/runs/{run['id']}/review",json={'revision':current['revision'],'items':selected,'reviewer':'老师','confirmed':True}).status_code==422
    scoped=client.post(f"/api/knowledge/runs/{run['id']}/scope",json={'revision':current['revision'],'items':selected,'scope':'core'})
    assert scoped.status_code==200,scoped.text
    current=scoped.json();selected=[{'id':i['id'],'revision':i['revision']} for i in current['items']]
    reviewed=client.post(f"/api/knowledge/runs/{run['id']}/review",json={'revision':current['revision'],'items':selected,'reviewer':'数学老师','confirmed':True})
    assert reviewed.status_code==200,reviewed.text
    current=reviewed.json()
    version=client.post(f"/api/knowledge/runs/{run['id']}/versions",json={'revision':current['revision']})
    assert version.status_code==201,version.text
    version_id=version.json()['id'];snapshot=client.get(f'/api/knowledge/versions/{version_id}/download').content
    assert not version.json()['snapshot']['official_coverage_verified']
    assert client.post(f"/api/knowledge/runs/{run['id']}/versions",json={'revision':current['revision']}).json()['id']==version_id
    old=current['items'][0];changed=old['body']|{'statement':'教师修正后的严谨表述'}
    edited=client.put(f"/api/knowledge/candidates/{old['id']}",json={'revision':old['revision'],'body':changed,'scope':'core','review_note':'人工修正'})
    assert edited.status_code==200,edited.text
    assert edited.json()['review_state']=='pending'
    assert edited.json()['original_body']==old['body']
    assert client.put(f"/api/knowledge/candidates/{old['id']}",json={'revision':old['revision'],'body':changed,'scope':'core'}).status_code==409
    assert client.get(f"/api/knowledge/candidates/{old['id']}/history").json()
    regenerated=client.post(f"/api/knowledge/units/{unit['id']}/runs",json={'unit_revision':1,'consent':True,'base_run_id':run['id']}).json()
    assert regenerated['id']!=run['id'] and regenerated['status']=='awaiting_selection'
    assert regenerated['catalog']==current['catalog']
    assert client.get(f'/api/knowledge/versions/{version_id}/download').content==snapshot
    assert client.get(f"/api/knowledge/runs/{run['id']}").json()['items'][0]['body']==changed
    assert 'test-secret' not in client.get(f"/api/knowledge/runs/{run['id']}/artifacts").text
    init_db();assert client.get('/api/knowledge/units').json()[0]['id']==unit['id']

def test_no_credentials_no_consent_no_fabricated_run(client):
    unit=client.post('/api/knowledge/units',json={'title':'函数','chapters':['函数']}).json()
    assert client.post(f"/api/knowledge/units/{unit['id']}/runs",json={'unit_revision':1,'consent':True}).status_code==422
    client.put('/api/knowledge/provider',json={'model':'test','api_key':'secret'})
    assert client.post(f"/api/knowledge/units/{unit['id']}/runs",json={'unit_revision':1,'consent':False}).status_code==422
    assert client.get(f"/api/knowledge/units/{unit['id']}/runs").json()==[]
    assert client.put('/api/knowledge/provider',json={'base_url':'http://public.example/v1'}).status_code==422
    assert client.put('/api/knowledge/provider',json={'base_url':'https://user:password@example.com/v1'}).status_code==422
    assert config_path().stat().st_mode&0o077==0
    client.put('/api/knowledge/provider',json={'model':'test','clear_key':True})
    assert not load_provider().api_key

def test_partial_failure_checkpoints_budget_and_worker_recovery(client,monkeypatch):
    unit,run=setup(client)
    calls=[]
    def failing(config,system,payload,max_tokens):
        calls.append(system)
        if '单独一轮' in system: raise ValueError('transient test-secret-DO-NOT-RETURN')
        return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',failing)
    worker.run_one_knowledge();current=client.get(f"/api/knowledge/runs/{run['id']}").json()
    client.post(f"/api/knowledge/runs/{run['id']}/expand",json={'revision':current['revision'],'selected_ids':[i['id'] for i in current['catalog']]})
    worker.run_one_knowledge();current=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert current['status']=='failed' and len(current['items'])==2
    assert 'test-secret' not in current['error']
    monkeypatch.setattr(worker,'generate',model)
    client.post(f"/api/knowledge/runs/{run['id']}/retry",json={'revision':current['revision']})
    worker.run_one_knowledge();current=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert current['status']=='completed'
    assert len([c for c in current['calls'] if c['step']=='details:0'])==1
    # A running paid request is not automatically re-sent after a restart.
    with connect() as c: c.execute("UPDATE knowledge_runs SET status='running' WHERE id=?",(run['id'],))
    worker.recover_knowledge()
    assert client.get(f"/api/knowledge/runs/{run['id']}").json()['status']=='interrupted'
    assert not worker.run_one_knowledge()

def test_unit_changes_make_old_results_stale_and_group_conflicts_atomic(client,monkeypatch):
    unit,run=setup(client);current=complete(client,run,monkeypatch)
    items=[{'id':i['id'],'revision':i['revision']} for i in current['items']]
    items[-1]['revision']=999
    response=client.post(f"/api/knowledge/runs/{run['id']}/scope",json={'revision':current['revision'],'items':items,'scope':'core'})
    assert response.status_code==409
    assert all(i['scope']=='pending' for i in client.get(f"/api/knowledge/runs/{run['id']}").json()['items'])
    changed=client.put(f"/api/knowledge/units/{unit['id']}",json={'revision':1,'title':unit['title'],'chapters':['新范围'],'target':unit['target'],'notes':''})
    assert changed.status_code==200
    assert client.get(f"/api/knowledge/runs/{run['id']}").json()['stale']
    assert client.post(f"/api/knowledge/runs/{run['id']}/versions",json={'revision':current['revision']}).status_code==409
    candidate=current['items'][0]
    assert client.put(f"/api/knowledge/candidates/{candidate['id']}",json={'revision':candidate['revision'],'body':candidate['body'],'scope':'core'}).status_code==409

def test_manual_addition_exclusion_is_not_a_math_error_and_critic_requires_note(client,monkeypatch):
    unit,run=setup(client)
    def critic(config,system,payload,max_tokens):
        if '单独一轮' in system:return json.dumps({'issues':[{'knowledge_id':payload['candidates'][0]['knowledge_id'],'message':'请核对整式条件'}]}),None
        return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',critic)
    worker.run_one_knowledge();current=client.get(f"/api/knowledge/runs/{run['id']}").json()
    client.post(f"/api/knowledge/runs/{run['id']}/expand",json={'revision':current['revision'],'selected_ids':[i['id'] for i in current['catalog']]})
    worker.run_one_knowledge();current=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert current['checks']
    added=client.post(f"/api/knowledge/runs/{run['id']}/items",json={'revision':current['revision'],'body':body('教师补充'),'scope':'excluded'})
    assert added.status_code==201,added.text
    assert added.json()['origin']=='teacher_authored'
    current=client.get(f"/api/knowledge/runs/{run['id']}").json();item=current['items'][-1]
    reviewed=client.post(f"/api/knowledge/runs/{run['id']}/review",json={'revision':current['revision'],'items':[{'id':item['id'],'revision':item['revision']}],'reviewer':'老师','confirmed':True})
    assert reviewed.status_code==200 and reviewed.json()['items'][-1]['scope']=='excluded'
    assert client.post(f"/api/knowledge/runs/{run['id']}/versions",json={'revision':reviewed.json()['revision']}).status_code==422


def test_migration_preserves_existing_sources_and_releases(client):
    from test_workflow import imported,verified
    document,source=imported(client);source=verified(client,source)
    draft=client.post('/api/drafts',json={'title':'旧草稿','source_ids':[source['id']]}).json()
    client.post(f"/api/drafts/{draft['id']}/approve",json={'revision':1,'reviewer':'教师','confirmed':True})
    release=client.post(f"/api/drafts/{draft['id']}/releases",json={'revision':1}).json()['id']
    saved=client.get(f'/api/releases/{release}/download').content
    init_db();init_db()
    assert client.get(f'/api/releases/{release}/download').content==saved
    assert client.get(f'/api/documents/{document}/blocks').json()[0]['id']==source['id']

def test_returned_items_remain_candidates_and_validation_never_echoes_key(client,monkeypatch):
    unit,run=setup(client);current=complete(client,run,monkeypatch)
    item=current['items'][0]
    response=client.post(f"/api/knowledge/runs/{run['id']}/review",json={'revision':current['revision'],'items':[{'id':item['id'],'revision':item['revision']}],'reviewer':'老师','confirmed':True,'decision':'return','note':'请补充成立条件'})
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['review_state']=='returned'
    assert response.json()['items'][1]['review_state']=='pending'
    bad=client.put('/api/knowledge/provider',json={'model':'m','api_key':'private\nsecret'})
    assert bad.status_code==422 and 'private' not in bad.text and 'secret' not in bad.text


def test_critic_issues_need_teacher_disposition(client,monkeypatch):
    unit,run=setup(client);current=complete(client,run,monkeypatch)
    item=current['items'][0]
    with connect() as c:
        c.execute('UPDATE knowledge_runs SET checks=? WHERE id=?',(json.dumps([{'knowledge_id':item['knowledge_id'],'message':'检查系数条件'}]),run['id']))
    scoped=client.post(f"/api/knowledge/runs/{run['id']}/scope",json={'revision':current['revision'],'items':[{'id':item['id'],'revision':item['revision']}],'scope':'core'}).json()
    item=scoped['items'][0]
    checked={'revision':scoped['revision'],'items':[{'id':item['id'],'revision':item['revision']}],'reviewer':'教师','confirmed':True}
    assert client.post(f"/api/knowledge/runs/{run['id']}/review",json=checked).status_code==422
    edited=client.put(f"/api/knowledge/candidates/{item['id']}",json={'revision':item['revision'],'body':item['body'],'scope':'core','review_note':'已核实 a≠0 条件正确'}).json()
    updated=client.get(f"/api/knowledge/runs/{run['id']}").json()
    checked.update(revision=updated['revision'],items=[{'id':edited['id'],'revision':edited['revision']}])
    assert client.post(f"/api/knowledge/runs/{run['id']}/review",json=checked).status_code==200


def test_budget_exhaustion_and_malformed_outputs_are_not_success(client,monkeypatch):
    unit,run=setup(client)
    monkeypatch.setattr(worker,'generate',lambda *_:('{broken JSON',None))
    worker.run_one_knowledge()
    result=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert result['status']=='failed' and not result['catalog']
    with connect() as c:
        frozen=json.loads(c.execute('SELECT model_json FROM knowledge_runs WHERE id=?',(run['id'],)).fetchone()[0])
        frozen['max_calls']=1
        c.execute('UPDATE knowledge_runs SET model_json=? WHERE id=?',(json.dumps(frozen),run['id']))
    client.post(f"/api/knowledge/runs/{run['id']}/retry",json={'revision':result['revision']})
    worker.run_one_knowledge()
    after=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert after['status']=='failed' and '预算' in after['error'] and len(after['calls'])==1


def test_confirmed_plan_unit_can_be_used_without_textbook_body_and_stales_on_plan_edit(client):
    from test_planning import import_plan,edit,confirm
    plan=import_plan(client)
    node=next(n for n in plan['payload']['nodes'] if n['kind']=='chapter')
    item={'id':'unit1','title':'二次函数复习','kind':'基础复习','volume':'函数','goals':'条件完整','node_ids':[node['id']]}
    item['kind']='foundation'
    changed=edit(client,plan,units=[item])
    assert changed.status_code==200,changed.text
    plan=changed.json();assert confirm(client,plan).status_code==200
    result=client.post('/api/knowledge/units/from-plan',json={'plan_id':plan['id'],'unit_id':'unit1','plan_revision':plan['revision']})
    assert result.status_code==201,result.text
    assert result.json()['notes']=='条件完整'
    assert node['title'] in result.json()['chapters']
    assert not result.json()['stale']
    assert edit(client,plan,notes='新规划修订').status_code==200
    assert client.get('/api/knowledge/units').json()[0]['stale']

def test_main_worker_dispatches_knowledge_when_file_queue_is_empty(client,monkeypatch):
    from mathlet.worker import run_one
    unit,run=setup(client)
    monkeypatch.setattr(worker,'generate',model)
    assert run_one()
    assert client.get(f"/api/knowledge/runs/{run['id']}").json()['status']=='awaiting_selection'

def test_legacy_invalid_key_can_be_replaced_without_returning_its_value(client):
    from mathlet.model_provider import config_path
    config_path().write_text(json.dumps({'base_url':'https://api.deepseek.com','model':'deepseek-flash','api_key':'sk-secret中文注释'}))
    result=client.get('/api/knowledge/provider')
    assert result.status_code==200 and not result.json()['ready']
    assert result.json()['credential_error'] and 'sk-secret' not in result.text
    repaired=client.put('/api/knowledge/provider',json={'base_url':'https://api.deepseek.com','model':'deepseek-flash','api_key':'valid-test-key'})
    assert repaired.status_code==200 and repaired.json()['ready']
    assert repaired.json()['thinking_mode']=='auto' and not repaired.json()['credential_error']


def test_failed_empty_response_preserves_usage_in_run_artifacts(client,monkeypatch):
    from mathlet.model_provider import ModelOutputError
    unit,run=setup(client)
    def empty(*_):raise ModelOutputError('空正文 finish_reason=length','',{'completion_tokens':1800})
    monkeypatch.setattr(worker,'generate',empty)
    worker.run_one_knowledge()
    result=client.get(f"/api/knowledge/runs/{run['id']}").json()
    assert result['status']=='failed'
    assert result['calls'][0]['usage']=={'completion_tokens':1800}
    artifacts=client.get(f"/api/knowledge/runs/{run['id']}/artifacts").json()
    request=json.loads(artifacts['calls'][0]['request_json'])
    assert request['transport_version']=='chat-v2'
