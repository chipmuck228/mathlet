import copy
import json
import pytest
from test_planning import client,upload,edit,confirm
from test_planning_ai import configured,start,model,complete
from mathlet import knowledge_worker as worker
from mathlet.db import connect


def spec_for(plan):
    return {'objectives':[{'id':'goal-1','text':'能够依据条件说明图象的变化','requirement_ids':[plan['payload']['requirements'][0]['id']]}],
            'required_content':['概念与成立条件','图象的表示'], 'boundary_notes':'区分全体实数与受限范围',
            'extension_candidates':['含参区间问题，待教师决定'], 'prerequisites':['坐标系'],
            'connections':[{'topic':'方程','reason':'通过交点联系实根'}], 'difficulties':['忽略自变量范围'],
            'presentation_hints':['用正反例比较条件'],
            'evidence':[{'source_id':plan['payload']['requirements'][0]['source_id'],'quote':'能画图和读图'}],
            'notes':'学习目标是教研拆解建议，并非官方原文'}


def spec_start(client,plan,**changes):
    return client.post('/api/topic-specs/runs',json={'plan_id':plan['id'],'unit_id':plan['payload']['units'][0]['id'],'plan_revision':plan['revision'],**changes})


def tasks(client,plan):
    return client.get('/api/topic-specs/runs',params={'plan_id':plan['id'],'unit_id':plan['payload']['units'][0]['id']}).json()


def test_joint_planning_retains_both_sources_and_secondary_edits_make_it_stale(client,monkeypatch):
    configured(client)
    primary=upload(client,['函数 二次函数 能画图和读图'],'standard')
    secondary=upload(client,['第二十六章 二次函数的概念与性质'],'textbook')
    blocks=[*client.get('/api/documents/'+primary+'/blocks').json(),*client.get('/api/documents/'+secondary+'/blocks').json()]
    def joint(config,system,payload,max_tokens):
        assert {s['category'] for s in payload['sources']}=={'standard','textbook'}
        assert '教材目录' in system
        raw,usage=model(config,system,payload,max_tokens)
        value=json.loads(raw);value['domains'][0]['topics'][0].update(source_id=blocks[1]['id'],quote='二次函数的概念与性质')
        return json.dumps(value),usage
    monkeypatch.setattr(worker,'generate',joint)
    response=start(client,primary,additional_document_ids=[secondary],source_revisions={b['id']:b['revision'] for b in blocks})
    assert response.status_code==201,response.text
    worker.run_one_knowledge();task=client.get('/api/planning-ai/runs/'+response.json()['id']).json()
    assert task['status']=='completed',task
    plan=client.get('/api/plans').json()[0]
    assert plan['payload']['document_ids']==[primary,secondary]
    assert {x['category'] for x in plan['payload']['source_documents']}=={'standard','textbook'}
    assert plan['source_locations'][blocks[1]['id']]['document_id']==secondary
    saved=edit(client,plan);assert saved.status_code==200,saved.text
    confirmed=confirm(client,saved.json()).json();assert confirmed['confirmed']
    b=blocks[1]
    client.put('/api/blocks/'+b['id'],json={'revision':b['revision'],'text':b['text']+' 新增要求','verified':False})
    stale=client.get('/api/plans').json()[0]
    assert not stale['confirmed'] and b['id'] in stale['stale_sources']
    assert spec_start(client,stale).status_code==409
    assert client.get('/api/planning-ai/runs/'+task['id']).json()['stale']


def test_topic_spec_proposal_is_not_applied_until_teacher_saves_and_confirms(client,monkeypatch):
    _,_,plan=complete(client,monkeypatch);plan=confirm(client,plan).json();before=copy.deepcopy(plan)
    proposal=spec_for(plan)
    def generate(config,system,payload,max_tokens):
        assert payload['unit']['id']==plan['payload']['units'][0]['id']
        assert '不能将目录标题当作学习程度要求' in system
        return json.dumps(proposal),{'total_tokens':50}
    monkeypatch.setattr(worker,'generate',generate)
    task=spec_start(client,plan);assert task.status_code==201,task.text
    worker.run_one_knowledge();result=tasks(client,plan)[0]
    assert result['status']=='completed' and result['proposal']==proposal
    assert client.get('/api/plans').json()[0]==before
    assert client.get('/api/knowledge/units').json()==[]
    units=copy.deepcopy(plan['payload']['units']);units[0]['topic_spec']=proposal
    saved=edit(client,plan,units=units);assert saved.status_code==200,saved.text
    saved=saved.json();assert not saved['confirmed']
    assert edit(client,plan,units=units).status_code==409
    assert confirm(client,plan).status_code==409
    assert tasks(client,plan)[0]['stale']
    final=confirm(client,saved).json();assert final['confirmed']
    knowledge=client.post('/api/knowledge/units/from-plan',json={'plan_id':final['id'],'unit_id':units[0]['id'],'plan_revision':final['revision']}).json()
    assert knowledge['origin_info']['topic_spec']==proposal
    assert knowledge['origin_info']['topic_spec_review']['basis']=='teacher_confirmed_plan'
    assert not knowledge['origin_info']['topic_spec_review']['official_coverage_verified']
    revised=copy.deepcopy(units);revised[0]['topic_spec']['boundary_notes']='新的教师判断'
    next_plan=edit(client,final,units=revised).json();assert not next_plan['confirmed']
    old_unit=next(u for u in client.get('/api/knowledge/units').json() if u['id']==knowledge['id'])
    assert old_unit['stale'] and old_unit['origin_info']['topic_spec']==proposal


@pytest.mark.parametrize('kind',['quote','foreign_source','foreign_requirement','duplicate_goal'])
def test_invalid_spec_evidence_or_objective_mapping_cannot_be_saved(client,monkeypatch,kind):
    _,_,plan=complete(client,monkeypatch);proposal=spec_for(plan)
    if kind=='quote':proposal['evidence'][0]['quote']='不存在的官方原文'
    if kind=='foreign_source':proposal['evidence'][0]['source_id']='foreign'
    if kind=='foreign_requirement':proposal['objectives'][0]['requirement_ids']=['foreign']
    if kind=='duplicate_goal':proposal['objectives'].append(proposal['objectives'][0])
    units=copy.deepcopy(plan['payload']['units']);units[0]['topic_spec']=proposal
    assert edit(client,plan,units=units).status_code==422
    assert client.get('/api/plans').json()[0]==plan
    monkeypatch.setattr(worker,'generate',lambda *_:(json.dumps(proposal),None))
    assert spec_start(client,plan).status_code==201
    worker.run_one_knowledge();assert tasks(client,plan)[0]['status']=='failed'
    assert not tasks(client,plan)[0]['proposal']


def test_concurrent_plan_change_discards_ai_result_and_stale_retry(client,monkeypatch):
    _,_,plan=complete(client,monkeypatch)
    proposal=spec_for(plan);assert spec_start(client,plan).status_code==201
    def concurrent(*_):
        changed=edit(client,plan,notes='教师已经修订当前规划');assert changed.status_code==200
        return json.dumps(proposal),None
    monkeypatch.setattr(worker,'generate',concurrent);worker.run_one_knowledge()
    t=tasks(client,plan)[0]
    assert t['status']=='failed' and t['stale'] and not t['proposal']
    assert client.post('/api/topic-specs/runs/'+t['id']+'/retry',json={'revision':t['revision']}).status_code==409
    assert client.get('/api/plans').json()[0]['payload']['notes']=='教师已经修订当前规划'


def test_failed_spec_explicit_retry_and_whitespace_cleanup(client,monkeypatch):
    _,_,plan=complete(client,monkeypatch)
    monkeypatch.setattr(worker,'generate',lambda *_:('{bad',None))
    assert spec_start(client,plan).status_code==201;worker.run_one_knowledge();t=tasks(client,plan)[0]
    assert t['status']=='failed'
    assert client.post('/api/topic-specs/runs/'+t['id']+'/retry',json={'revision':t['revision']-1}).status_code==409
    proposal=spec_for(plan);proposal['required_content']+=[' ','']
    monkeypatch.setattr(worker,'generate',lambda *_:(json.dumps(proposal),None))
    assert client.post('/api/topic-specs/runs/'+t['id']+'/retry',json={'revision':t['revision']}).status_code==200
    worker.run_one_knowledge();t=tasks(client,plan)[0]
    assert t['status']=='completed' and t['proposal']['required_content']==['概念与成立条件','图象的表示']
    assert 'topic_spec' not in client.get('/api/plans').json()[0]['payload']['units'][0]


def test_joint_input_preview_revisions_and_duplicate_documents_are_checked(client):
    configured(client);a=upload(client,['函数'],'standard');b=upload(client,['函数目录'])
    assert start(client,a,additional_document_ids=[a]).status_code==422
    assert start(client,a,additional_document_ids=[b]).status_code==409


def test_spec_revision_invalidates_linked_work_but_preserves_old_knowledge_delivery(client,monkeypatch):
    from test_knowledge import complete as complete_knowledge
    _,_,plan=complete(client,monkeypatch)
    units=copy.deepcopy(plan['payload']['units']);units[0]['topic_spec']=spec_for(plan)
    plan=confirm(client,edit(client,plan,units=units).json()).json()
    ku=client.post('/api/knowledge/units/from-plan',json={'plan_id':plan['id'],'unit_id':units[0]['id'],'plan_revision':plan['revision']}).json()
    run=client.post('/api/knowledge/units/'+ku['id']+'/runs',json={'unit_revision':ku['revision'],'consent':True}).json()
    current=complete_knowledge(client,run,monkeypatch)
    selected=[{'id':i['id'],'revision':i['revision']} for i in current['items']]
    current=client.post('/api/knowledge/runs/'+run['id']+'/scope',json={'revision':current['revision'],'items':selected,'scope':'core'}).json()
    selected=[{'id':i['id'],'revision':i['revision']} for i in current['items']]
    reviewed=client.post('/api/knowledge/runs/'+run['id']+'/review',json={'revision':current['revision'],'items':selected,'reviewer':'教师','confirmed':True})
    assert reviewed.status_code==200,reviewed.text
    final=client.post('/api/knowledge/runs/'+run['id']+'/versions',json={'revision':reviewed.json()['revision']})
    assert final.status_code==201,final.text
    url='/api/knowledge/versions/'+final.json()['id']+'/download';before=client.get(url).content
    revised=copy.deepcopy(plan['payload']['units']);revised[0]['topic_spec']['boundary_notes']='已修订边界'
    changed=edit(client,plan,units=revised);assert changed.status_code==200
    assert client.get('/api/knowledge/runs/'+run['id']).json()['stale']
    assert client.get(url).content==before
