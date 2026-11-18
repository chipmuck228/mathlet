import copy
import json
import pytest
from test_planning import client,edit,confirm
from test_planning_ai import complete as complete_plan
from test_topic_specs import spec_for
from test_knowledge import body
from mathlet import knowledge_worker as worker
from mathlet.db import connect


def prepare(client,monkeypatch):
    _,_,plan=complete_plan(client,monkeypatch)
    units=copy.deepcopy(plan['payload']['units']);units[0]['topic_spec']=spec_for(plan)
    units[0]['topic_spec']['objectives'].append({'id':'goal-2','text':'能比较受限区间的函数值','requirement_ids':[]})
    plan=confirm(client,edit(client,plan,units=units).json()).json()
    unit=client.post('/api/knowledge/units/from-plan',json={'plan_id':plan['id'],'unit_id':units[0]['id'],'plan_revision':plan['revision']}).json()
    run=client.post('/api/knowledge/units/'+unit['id']+'/runs',json={'unit_revision':unit['revision'],'consent':True}).json()
    return plan,unit,run


def report_for(ctx,status='partial'):
    item=ctx['items'][0]['knowledge_id']
    return {'rows':[{'target_id':t['id'],'status':status,'links':[] if status=='missing' else [{'knowledge_id':item,'fields':['statement','positive_example'],'explanation':'正文中已有说明和具体例子，但仍需补充范围讨论'}],
        'gap':'' if status=='covered' else '尚缺受限范围的讨论','guidance':'' if status=='covered' else '补充端点与顶点值比较的说明和反例'} for t in ctx['targets']],
        'issues':[{'kind':'boundary','knowledge_ids':[item],'message':'需要区分全体实数与有限范围','guidance':'在成立条件和例子中明确范围'}],'teacher_note':''}


def model(config,system,payload,max_tokens):
    if '先不要展开' in system:
        assert payload['topic_spec']['required_content'] and 'boundary_notes' in payload['topic_spec']
        assert 'objective_ids' in system and 'extension_candidates' in system
        return json.dumps({'items':[{'name':'二次函数定义','kind':'concept','reason':'说明定义与条件','objective_ids':['goal-1'],'required_content_indices':[0]},
                                    {'name':'二次函数图象','kind':'property','reason':'图象的表示','objective_ids':['goal-1','goal-2'],'required_content_indices':[1]}]}),None
    if '展开指定清单' in system:
        assert 'topic_spec' in payload['unit'] and payload['items'][0]['objective_ids']
        assert '不要只写名词' in system
        return json.dumps({'items':[{'knowledge_id':i['id'],'body':body(i['name'],i['kind'])} for i in payload['items']]}),None
    if '检查当前知识正文' in system:return json.dumps(report_for(payload)),None
    return json.dumps({'issues':[]}),None


def get(client,r):return client.get('/api/editor/runs/'+r['id']).json()
def coverage(client,r):return client.get('/api/knowledge-coverage/runs/'+r['id']).json()
def check(client,r):return client.post('/api/knowledge-coverage/runs/'+r['id']+'/check',json={'revision':r['revision']})
def complete(client,monkeypatch):
    p,u,r=prepare(client,monkeypatch);monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    response=client.post('/api/knowledge/runs/'+r['id']+'/expand',json={'revision':r['revision'],'selected_ids':[v['id'] for v in r['catalog']]});assert response.status_code==200,response.text
    worker.run_one_knowledge();r=get(client,r);assert r['status']=='completed',r['error'];return p,u,r


def test_spec_drives_catalog_body_and_automatic_non_veto_coverage(client,monkeypatch):
    _,_,r=complete(client,monkeypatch);c=coverage(client,r)
    assert r['catalog'][0]['objective_ids']==['goal-1']
    assert c['state']=='current' and len(c['targets'])==4
    assert c['result']['report']['rows'][0]['status']=='partial'
    assert c['result']['report']['issues'] and not r['final_blockers']
    assert any(call['step']=='coverage:objectives' for call in r['calls'])
    final=client.post('/api/editor/runs/'+r['id']+'/finalize',json={'revision':r['revision'],'confirmed':True})
    assert final.status_code==201,final.text
    f=final.json();assert f['snapshot']['topic_coverage']['state']=='current'
    assert f['snapshot']['topic_catalog_bindings'][0]['objective_ids']==['goal-1']
    old=client.get('/api/knowledge/versions/'+f['id']+'/download').content
    assert check(client,get(client,r)).status_code==409
    fork=client.post('/api/editor/versions/'+f['id']+'/revise').json()
    assert fork['catalog'][0]['objective_ids']==['goal-1']
    assert fork['topic_coverage']['state']=='not_checked'
    assert client.get('/api/knowledge/versions/'+f['id']+'/download').content==old


def test_direct_teacher_edit_and_stale_report_protection(client,monkeypatch):
    _,_,r=complete(client,monkeypatch);c=coverage(client,r);report=copy.deepcopy(c['result']['report']);report['teacher_note']='教师保留当前安排，区间最值另节展开'
    request={'revision':r['revision'],'source_hash':c['source_hash'],'result_id':c['result_id'],'report':report}
    saved=client.put('/api/knowledge-coverage/runs/'+r['id'],json=request);assert saved.status_code==200,saved.text
    assert saved.json()['result']['origin']=='teacher' and saved.json()['result']['report']['teacher_note']
    assert client.put('/api/knowledge-coverage/runs/'+r['id'],json=request).status_code==409
    updated=get(client,r);item=updated['items'][0]
    modified=client.put('/api/editor/runs/'+r['id']+'/items/'+item['id'],json={'revision':updated['revision'],'item_revision':item['revision'],'body':item['body']|{'positive_example':'教师补充的例子'},'review_note':''})
    assert modified.status_code==200,modified.text
    assert coverage(client,r)['state']=='stale'
    assert client.put('/api/knowledge-coverage/runs/'+r['id'],json=request|{'revision':modified.json()['revision']}).status_code==409
    assert client.post('/api/editor/runs/'+r['id']+'/finalize',json={'revision':modified.json()['revision'],'confirmed':True}).status_code==201


@pytest.mark.parametrize('mutation',['foreign_goal','foreign_knowledge','empty_field','omission','missing_guidance'])
def test_invalid_coverage_mappings_are_rejected_without_changing_body(client,monkeypatch,mutation):
    _,_,r=complete(client,monkeypatch);c=coverage(client,r);report=copy.deepcopy(c['result']['report'])
    if mutation=='foreign_goal':report['rows'][0]['target_id']='foreign'
    if mutation=='foreign_knowledge':report['rows'][0]['links'][0]['knowledge_id']='foreign'
    if mutation=='empty_field':report['rows'][0]['links'][0]['fields']=['method_steps']
    if mutation=='omission':report['rows'].pop()
    if mutation=='missing_guidance':report['rows'][0]['guidance']=''
    response=client.put('/api/knowledge-coverage/runs/'+r['id'],json={'revision':r['revision'],'source_hash':c['source_hash'],'result_id':c['result_id'],'report':report})
    assert response.status_code==422,response.text
    assert get(client,r)['revision']==r['revision'] and coverage(client,r)['result_id']==c['result_id']


def test_budget_or_model_failure_does_not_fail_knowledge_or_block_final(client,monkeypatch):
    _,_,r=prepare(client,monkeypatch)
    # Budget applies to this run's frozen provider; three calls suffice for knowledge.
    with connect() as conn:
        config=json.loads(conn.execute('SELECT model_json FROM knowledge_runs WHERE id=?',(r['id'],)).fetchone()[0]);config['max_calls']=3
        conn.execute('UPDATE knowledge_runs SET model_json=? WHERE id=?',(json.dumps(config),r['id']))
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    client.post('/api/knowledge/runs/'+r['id']+'/expand',json={'revision':r['revision'],'selected_ids':[v['id'] for v in r['catalog']]});worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed' and not r['error']
    c=coverage(client,r);assert c['state']=='failed' and '预算' in c['result']['error']
    assert client.post('/api/editor/runs/'+r['id']+'/finalize',json={'revision':r['revision'],'confirmed':True}).status_code==201


def test_queued_recheck_deduplicates_and_cannot_overwrite_concurrent_teacher_edit(client,monkeypatch):
    _,_,r=complete(client,monkeypatch);c=coverage(client,r)
    t=check(client,r);assert t.status_code==201,t.text
    assert check(client,r).json()['id']==t.json()['id']
    def concurrent(config,system,payload,max_tokens):
        changed=copy.deepcopy(c['result']['report']);changed['teacher_note']='教师已经处理'
        response=client.put('/api/knowledge-coverage/runs/'+r['id'],json={'revision':r['revision'],'source_hash':c['source_hash'],'result_id':c['result_id'],'report':changed})
        assert response.status_code==200,response.text
        return json.dumps(report_for(payload)),None
    monkeypatch.setattr(worker,'generate',concurrent);worker.run_one_knowledge()
    view=coverage(client,r);assert view['tasks'][0]['status']=='failed' and view['tasks'][0]['stale']
    assert view['result']['origin']=='teacher' and view['result']['report']['teacher_note']=='教师已经处理'


def test_successful_recheck_rejects_save_of_previous_report_even_when_body_unchanged(client,monkeypatch):
    _,_,r=complete(client,monkeypatch);old=coverage(client,r)
    assert check(client,r).status_code==201;worker.run_one_knowledge();fresh=coverage(client,r)
    assert fresh['result_id']!=old['result_id'] and fresh['state']=='current'
    response=client.put('/api/knowledge-coverage/runs/'+r['id'],json={'revision':r['revision'],'source_hash':old['source_hash'],'result_id':old['result_id'],'report':old['result']['report']})
    assert response.status_code==409
    item=r['items'][0];removed=client.post('/api/editor/runs/'+r['id']+'/arrange',json={'revision':r['revision'],'item_id':item['id'],'action':'remove'})
    assert removed.status_code==200 and coverage(client,r)['state']=='stale'


def test_changed_planning_source_stops_pending_check_before_model_call(client,monkeypatch):
    plan,_,r=complete(client,monkeypatch);assert check(client,r).status_code==201
    assert edit(client,plan,notes='重新考虑范围').status_code==200
    monkeypatch.setattr(worker,'generate',lambda *_:pytest.fail('stale check must not call model'))
    worker.run_one_knowledge();view=coverage(client,r)
    assert view['state']=='stale' and view['tasks'][0]['status']=='failed'


def test_teacher_can_save_coverage_without_any_configured_model(client,monkeypatch):
    _,_,r=complete(client,monkeypatch);c=coverage(client,r)
    response=client.put('/api/knowledge/provider',json={'model':'test-model','clear_key':True});assert response.status_code==200
    report=copy.deepcopy(c['result']['report']);report['teacher_note']='人工核对，无需AI'
    saved=client.put('/api/knowledge-coverage/runs/'+r['id'],json={'revision':r['revision'],'source_hash':c['source_hash'],'result_id':c['result_id'],'report':report})
    assert saved.status_code==200,saved.text
    assert saved.json()['result']['origin']=='teacher'


@pytest.mark.parametrize('kind',['objective','required_content'])
def test_catalog_cannot_bind_foreign_topic_targets(client,monkeypatch,kind):
    _,_,r=prepare(client,monkeypatch)
    def invalid(config,system,payload,max_tokens):
        raw,usage=model(config,system,payload,max_tokens);value=json.loads(raw)
        if kind=='objective':value['items'][0]['objective_ids']=['foreign-goal']
        else:value['items'][0]['required_content_indices']=[99]
        return json.dumps(value),usage
    monkeypatch.setattr(worker,'generate',invalid);worker.run_one_knowledge()
    result=get(client,r);assert result['status']=='failed' and not result['catalog']


def test_pending_ai_check_cannot_write_after_teacher_finalizes(client,monkeypatch):
    _,_,r=complete(client,monkeypatch);previous=coverage(client,r)['result_id'];assert check(client,r).status_code==201
    frozen={}
    def finalizing(config,system,payload,max_tokens):
        response=client.post('/api/editor/runs/'+r['id']+'/finalize',json={'revision':r['revision'],'confirmed':True})
        assert response.status_code==201,response.text
        frozen['id']=response.json()['id'];frozen['bytes']=client.get('/api/knowledge/versions/'+frozen['id']+'/download').content
        return json.dumps(report_for(payload,'covered')),None
    monkeypatch.setattr(worker,'generate',finalizing);worker.run_one_knowledge()
    view=coverage(client,r);assert view['tasks'][0]['status']=='failed'
    assert view['result_id']==previous
    assert client.get('/api/knowledge/versions/'+frozen['id']+'/download').content==frozen['bytes']
