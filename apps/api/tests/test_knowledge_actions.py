import json
import pytest
from test_knowledge import client,setup,complete,body,model
from mathlet import knowledge_worker as worker
from mathlet.db import connect,init_db


def action_model(config,system,payload,max_tokens):
    if 'action' not in payload:
        if '候选编号' in system: return json.dumps({'issues':[]}),{'total_tokens':20}
        return model(config,system,payload,max_tokens)
    action=payload['action']
    if action in {'revise','supplement','split'}:
        count=2 if action=='split' else 1
        return json.dumps({'items':[{'body':body('修订名称' if action=='revise' else f'新增知识{i}'),'reason':'明确知识边界'} for i in range(count)]}),{'total_tokens':200}
    if action=='coverage':
        return json.dumps({'summary':'仅基于现有候选检查，不代表课标覆盖','suggestions':[{'name':'闭区间最值','kind':'method','category':'missing','action':'supplement','related_ids':[payload['sources'][0]['knowledge_id']],'reason':'已有条目未讨论给定区间'}]}),None
    return json.dumps({'relations':[{'source_id':payload['sources'][0]['knowledge_id'],'target_id':payload['sources'][1]['knowledge_id'],'relation_type':'prerequisite','reason':'前置依据','conditions':'满足一次方程定义','example':'由等式性质解方程'}]}),None


def prepare(client,monkeypatch):
    _,run=setup(client)
    base=complete(client,run,monkeypatch)
    monkeypatch.setattr(worker,'generate',action_model)
    return base


def start(client,base,action='supplement',**extra):
    response=client.post(f"/api/knowledge/runs/{base['id']}/actions",json={'revision':base['revision'],'action':action,'instruction':'根据意见补充','consent':True,**extra})
    assert response.status_code==201,response.text
    worker.run_one_knowledge()
    task=client.get(f"/api/knowledge/runs/{response.json()['id']}").json()
    assert task['status']=='completed',task
    return task


def apply(client,base,task,outputs=None,**extra):
    return client.post(f"/api/knowledge/runs/{task['id']}/apply",json={'revision':task['revision'],'parent_revision':base['revision'],
        'outputs':outputs or [{'id':x['id'],'revision':x['revision']} for x in task['outputs']],
        'reviewer':'教师','note':'已检查候选与原稿，采纳为待审核内容','confirmed':True,**extra})


def test_supplement_and_revision_proposals_do_not_overwrite_before_adoption(client,monkeypatch):
    base=prepare(client,monkeypatch)
    task=start(client,base)
    assert client.get(f"/api/knowledge/runs/{base['id']}").json()['items']==base['items']
    result=apply(client,base,task)
    assert result.status_code==200,result.text
    updated=result.json()
    assert len(updated['items'])==3
    assert updated['items'][-1]['review_state']=='pending' and updated['items'][-1]['scope']=='pending'
    assert updated['items'][:2]==base['items']
    assert apply(client,updated,task).status_code==409
    original=updated['items'][0]
    task=start(client,updated,'revise',candidate_id=original['id'])
    assert task['input_json']['action_task']['sources'][0]['body']==original['body']
    assert client.get(f"/api/knowledge/runs/{base['id']}").json()['items'][0]['body']==original['body']
    response=apply(client,updated,task);assert response.status_code==200,response.text
    changed=response.json()['items'][0]
    assert changed['id']==original['id'] and changed['knowledge_id']==original['knowledge_id']
    assert changed['body']['name']=='修订名称' and changed['review_state']=='pending'
    assert changed['revision']==original['revision']+1
    assert client.get(f"/api/knowledge/candidates/{original['id']}/history").json()


def test_split_requires_whole_adoption_retains_original_and_atomic_rollback(client,monkeypatch):
    base=prepare(client,monkeypatch);source=base['items'][0]
    task=start(client,base,'split',candidate_id=source['id'])
    assert apply(client,base,task,outputs=[{'id':task['outputs'][0]['id'],'revision':1}]).status_code==422
    assert client.get(f"/api/knowledge/runs/{base['id']}").json()['revision']==base['revision']
    result=apply(client,base,task);assert result.status_code==200,result.text
    changed=result.json();assert len(changed['items'])==4
    assert changed['items'][0]['body']==source['body']
    assert changed['items'][0]['scope']=='excluded' and changed['items'][0]['review_state']=='pending'
    assert all(x['scope']=='pending' and x['review_state']=='pending' for x in changed['items'][2:])


def test_scope_uncertainty_can_be_classified_without_rewriting_math(client,monkeypatch):
    base=prepare(client,monkeypatch);item=base['items'][0]
    edited=client.put(f"/api/knowledge/candidates/{item['id']}",json={'revision':item['revision'],'body':item['body']|{'uncertainty':'是否纳入动区间问题由教师决定'},'scope':'core','review_note':'仅纳入基础范围'}).json()
    current=client.get(f"/api/knowledge/runs/{base['id']}").json()
    def approve(current,item):return client.post(f"/api/knowledge/runs/{base['id']}/review",json={'revision':current['revision'],'items':[{'id':item['id'],'revision':item['revision']}],'reviewer':'教师','confirmed':True})
    assert approve(current,edited).status_code==422
    check=next(x for x in current['checks'] if x.get('origin')=='uncertainty')
    classified=client.post(f"/api/knowledge/runs/{base['id']}/classify",json={'revision':current['revision'],'issue_id':check['id'],'category':'scope','note':'这是范围决策，基础册暂不纳入动区间'}).json()
    assert approve(classified,classified['items'][0]).status_code==200
    # A different unresolved mathematical question must not inherit that classification.
    latest=client.get(f"/api/knowledge/runs/{base['id']}").json();item=latest['items'][0]
    client.put(f"/api/knowledge/candidates/{item['id']}",json={'revision':item['revision'],'body':item['body']|{'uncertainty':'条件a不确定'},'scope':'core','review_note':'尚未核实'})
    latest=client.get(f"/api/knowledge/runs/{base['id']}").json()
    assert len([x for x in latest['checks'] if x.get('origin')=='uncertainty'])==1
    assert approve(latest,latest['items'][0]).status_code==422
    item=latest['items'][0]
    client.put(f"/api/knowledge/candidates/{item['id']}",json={'revision':item['revision'],'body':item['body']|{'uncertainty':''},'scope':'core','review_note':'已核实条件'})
    latest=client.get(f"/api/knowledge/runs/{base['id']}").json()
    assert not any(x.get('origin')=='uncertainty' for x in latest['checks'])
    assert latest['items'][0]['review_blockers']==[]
    approved=approve(latest,latest['items'][0])
    assert approved.status_code==200,approved.text
    assert approved.json()['items'][0]['review_state']=='approved'
    history=client.get(f"/api/knowledge/candidates/{item['id']}/history").json()
    assert '条件a不确定' in json.dumps(history,ensure_ascii=False)


def test_coverage_selected_suggestion_drives_bounded_generation(client,monkeypatch):
    base=prepare(client,monkeypatch)
    task=start(client,base,'coverage')
    assert len(task['outputs'])==1 and '覆盖' in task['checks'][0]['message']
    assert apply(client,base,task).status_code==422
    proposal=start(client,base,'supplement',suggestion_run_id=task['id'],suggestion_ids=[task['outputs'][0]['id']],instruction='')
    assert proposal['input_json']['action_task']['suggestions'][0]['name']=='闭区间最值'
    assert apply(client,base,proposal).status_code==200
    stale=client.post(f"/api/knowledge/runs/{base['id']}/actions",json={'revision':base['revision']+1,'action':'supplement','instruction':'补充','consent':True,'suggestion_run_id':task['id'],'suggestion_ids':[task['outputs'][0]['id']]})
    assert stale.status_code==409


def approve_all(client,base):
    scoped=client.post(f"/api/knowledge/runs/{base['id']}/scope",json={'revision':base['revision'],'items':[{'id':x['id'],'revision':x['revision']} for x in base['items']],'scope':'core'}).json()
    result=client.post(f"/api/knowledge/runs/{base['id']}/review",json={'revision':scoped['revision'],'items':[{'id':x['id'],'revision':x['revision']} for x in scoped['items']],'reviewer':'教师','confirmed':True})
    assert result.status_code==200,result.text
    return result.json()


def test_relations_are_reviewed_endpoint_bound_and_frozen_versions_immutable(client,monkeypatch):
    base=approve_all(client,prepare(client,monkeypatch));task=start(client,base,'relations')
    response=apply(client,base,task);assert response.status_code==200,response.text
    base=response.json();assert base['relations'][0]['usable']
    frozen=client.post(f"/api/knowledge/runs/{base['id']}/versions",json={'revision':base['revision']}).json()
    assert len(frozen['snapshot']['relations'])==1
    original=client.get(f"/api/knowledge/versions/{frozen['id']}/download").content
    item=base['items'][0]
    client.put(f"/api/knowledge/candidates/{item['id']}",json={'revision':item['revision'],'body':item['body']|{'statement':'新修订'},'scope':'core'})
    current=client.get(f"/api/knowledge/runs/{base['id']}").json()
    assert current['relations'][0]['stale'] and not current['relations'][0]['usable']
    version=client.post(f"/api/knowledge/runs/{base['id']}/versions",json={'revision':current['revision']}).json()
    assert version['snapshot']['relations']==[]
    init_db();assert client.get(f"/api/knowledge/versions/{frozen['id']}/download").content==original


@pytest.mark.parametrize('change',['candidate','unit'])
def test_stale_sources_reject_generation_and_adoption(client,monkeypatch,change):
    base=prepare(client,monkeypatch);task=start(client,base)
    if change=='candidate':
        x=base['items'][0];client.put(f"/api/knowledge/candidates/{x['id']}",json={'revision':x['revision'],'body':x['body'],'scope':'core'})
    else:
        unit=client.get('/api/knowledge/units').json()[0]
        client.put(f"/api/knowledge/units/{unit['id']}",json={'revision':unit['revision'],'title':unit['title'],'chapters':['新范围'],'target':unit['target'],'notes':''})
    fresh=client.get(f"/api/knowledge/runs/{base['id']}").json()
    assert apply(client,fresh,task).status_code==409
    assert client.get(f"/api/knowledge/runs/{task['id']}").json()['stale']


def test_cross_batch_and_invalid_model_references_fail_without_partial_output(client,monkeypatch):
    base=prepare(client,monkeypatch)
    request={'revision':base['revision'],'action':'revise','instruction':'修正','candidate_id':'foreign','consent':True}
    assert client.post(f"/api/knowledge/runs/{base['id']}/actions",json=request).status_code==422
    request.update(action='supplement',candidate_id=None,consent=False)
    assert client.post(f"/api/knowledge/runs/{base['id']}/actions",json=request).status_code==422
    def invalid(config,system,payload,max_tokens):
        raw,usage=action_model(config,system,payload,max_tokens)
        if payload.get('action')=='relations':
            value=json.loads(raw);value['relations'][0]['target_id']='not-in-source';raw=json.dumps(value)
        return raw,usage
    monkeypatch.setattr(worker,'generate',invalid)
    response=client.post(f"/api/knowledge/runs/{base['id']}/actions",json={'revision':base['revision'],'action':'relations','consent':True})
    worker.run_one_knowledge();task=client.get(f"/api/knowledge/runs/{response.json()['id']}").json()
    assert task['status']=='failed' and not task['outputs']


def test_action_retry_reuses_generation_checkpoint_and_proposal_edits_preserve_original(client,monkeypatch):
    base=prepare(client,monkeypatch);calls=[]
    def fail_critic(config,system,payload,max_tokens):
        calls.append(payload.get('action','critic'))
        if '候选编号' in system: raise ValueError('模拟复核中断')
        return action_model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',fail_critic)
    response=client.post(f"/api/knowledge/runs/{base['id']}/actions",json={'revision':base['revision'],'action':'supplement','instruction':'补充最值','consent':True})
    worker.run_one_knowledge();task=client.get(f"/api/knowledge/runs/{response.json()['id']}").json()
    assert task['status']=='failed' and not task['outputs']
    monkeypatch.setattr(worker,'generate',action_model)
    client.post(f"/api/knowledge/runs/{task['id']}/retry",json={'revision':task['revision']});worker.run_one_knowledge()
    task=client.get(f"/api/knowledge/runs/{task['id']}").json()
    assert task['status']=='completed' and len(task['calls'])==3
    output=task['outputs'][0]
    proposed=output['body']|{'body':output['body']['body']|{'name':'教师修正的候选'}}
    assert client.put(f"/api/knowledge/outputs/{output['id']}",json={'revision':output['revision'],'body':proposed}).status_code==200
    assert client.put(f"/api/knowledge/outputs/{output['id']}",json={'revision':output['revision'],'body':proposed}).status_code==409
    current=client.get(f"/api/knowledge/runs/{task['id']}").json()
    assert current['outputs'][0]['original_body']==output['original_body']
    assert current['outputs'][0]['body']['body']['name']=='教师修正的候选'
    assert apply(client,base,current).status_code==200


def test_source_change_during_paid_call_discards_output_and_requires_new_task(client,monkeypatch):
    base=prepare(client,monkeypatch)
    def concurrent_edit(config,system,payload,max_tokens):
        result=action_model(config,system,payload,max_tokens)
        if payload.get('action'):
            with connect() as c:c.execute('UPDATE knowledge_runs SET revision=revision+1 WHERE id=?',(base['id'],))
        return result
    monkeypatch.setattr(worker,'generate',concurrent_edit)
    response=client.post(f"/api/knowledge/runs/{base['id']}/actions",json={'revision':base['revision'],'action':'coverage','consent':True})
    worker.run_one_knowledge()
    task=client.get(f"/api/knowledge/runs/{response.json()['id']}").json()
    assert task['status']=='failed' and task['stale'] and task['outputs']==[]
    assert client.post(f"/api/knowledge/runs/{task['id']}/retry",json={'revision':task['revision']}).status_code==409


def test_reject_preserves_parent_and_relation_edit_rejects_foreign_endpoints(client,monkeypatch):
    base=prepare(client,monkeypatch);task=start(client,base,'relations')
    output=task['outputs'][0]
    response=client.put(f"/api/knowledge/outputs/{output['id']}",json={'revision':output['revision'],'body':output['body']|{'target_id':'foreign'}})
    assert response.status_code==422
    rejected=apply(client,base,task,decision='reject');assert rejected.status_code==200,rejected.text
    assert rejected.json()['revision']==base['revision'] and rejected.json()['items']==base['items']
    assert not rejected.json()['relations']
    assert client.get(f"/api/knowledge/runs/{task['id']}").json()['outputs'][0]['state']=='rejected'


def test_action_budget_and_scope_checks_do_not_call_model(client,monkeypatch):
    base=prepare(client,monkeypatch)
    client.put('/api/knowledge/provider',json={'model':'test-model','output_token_budget':6000})
    response=client.post(f"/api/knowledge/runs/{base['id']}/actions",json={'revision':base['revision'],'action':'supplement','instruction':'新增','consent':True})
    assert response.status_code==422
    response=client.post(f"/api/knowledge/runs/{base['id']}/actions",json={'revision':base['revision'],'action':'revise','candidate_id':base['items'][0]['id'],'instruction':'修订','issue_ids':['foreign-check'],'consent':True})
    assert response.status_code==422
    assert client.get(f"/api/knowledge/runs/{base['id']}").json()['tasks']==[]


def test_supplement_can_expand_existing_unselected_catalog_identity(client,monkeypatch):
    _,run=setup(client);monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge()
    base=client.get(f"/api/knowledge/runs/{run['id']}").json();first,remaining=base['catalog']
    client.post(f"/api/knowledge/runs/{base['id']}/expand",json={'revision':base['revision'],'selected_ids':[first['id']]});worker.run_one_knowledge()
    base=client.get(f"/api/knowledge/runs/{base['id']}").json()
    def expand_remaining(config,system,payload,max_tokens):
        if payload.get('action')=='supplement':
            assert len(payload['catalog'])==2 and len(payload['sources'])==1
            return json.dumps({'items':[{'body':body(remaining['name'],remaining['kind']),'reason':'展开已有清单'}]}),None
        return action_model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',expand_remaining)
    task=start(client,base);result=apply(client,base,task)
    assert result.status_code==200,result.text
    assert len(result.json()['catalog'])==2
    assert result.json()['items'][-1]['knowledge_id']==remaining['id']


def test_teacher_can_withdraw_relation_without_changing_knowledge_or_old_version(client,monkeypatch):
    base=approve_all(client,prepare(client,monkeypatch));task=start(client,base,'relations')
    base=apply(client,base,task).json();edge=base['relations'][0]
    frozen=client.post(f"/api/knowledge/runs/{base['id']}/versions",json={'revision':base['revision']}).json()
    saved=client.get(f"/api/knowledge/versions/{frozen['id']}/download").content
    payload={'revision':base['revision'],'reviewer':'教师','note':'关系方向需要重新审阅','confirmed':True}
    response=client.post(f"/api/knowledge/runs/{base['id']}/relations/{edge['id']}/retire",json=payload)
    assert response.status_code==200,response.text
    current=response.json();assert current['items']==base['items']
    assert current['relations'][0]['retired'] and not current['relations'][0]['usable']
    assert client.post(f"/api/knowledge/runs/{base['id']}/relations/{edge['id']}/retire",json=payload).status_code==409
    assert client.get(f"/api/knowledge/versions/{frozen['id']}/download").content==saved
    init_db();assert client.get(f"/api/knowledge/runs/{base['id']}").json()['relations'][0]['retired']
