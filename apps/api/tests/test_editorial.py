import json
import pytest
from test_knowledge import client, setup, complete, body
from mathlet import editorial
from mathlet.db import connect


def prepared(client,monkeypatch):
    unit,run=setup(client);run=complete(client,run,monkeypatch)
    run=client.post(f"/api/knowledge/runs/{run['id']}/scope",json={'revision':run['revision'],'items':[{'id':x['id'],'revision':x['revision']} for x in run['items']],'scope':'core'}).json()
    client.get('/api/editor/profiles')
    return unit,client.get(f"/api/editor/runs/{run['id']}").json()


def save(client,run,item=None,**changes):
    item=item or run['items'][0]
    return client.put(f"/api/editor/runs/{run['id']}/items/{item['id']}",json={'revision':run['revision'],'item_revision':item['revision'],'body':changes.get('body',item['body']),'scope':changes.get('scope',item['scope']),'review_note':changes.get('review_note','')})


def send(client,run,action='chat',**changes):
    request={'revision':run['revision'],'request_key':'request-unique-1','action':action,'candidate_id':run['items'][0]['id'] if action=='chat' else None,'body':None,'instruction':'请解释成立条件','profile_id':'openai'}|changes
    return client.post(f"/api/editor/runs/{run['id']}/messages",json=request)


def test_five_profiles_isolate_secrets_and_migrate_existing_configuration(client):
    client.put('/api/knowledge/provider',json={'model':'old-model','api_key':'old-private-key'})
    response=client.get('/api/editor/profiles');assert response.status_code==200
    data=response.json();assert len(data['profiles'])==5 and data['active']=='openai'
    assert 'old-private-key' not in response.text
    gemini={'base_url':'https://generativelanguage.googleapis.com/v1beta/openai','model':'test-gemini','api_key':'gemini-private-key'}
    assert client.put('/api/editor/profiles/gemini',json=gemini).status_code==200
    assert client.post('/api/editor/profiles/gemini/activate').status_code==200
    assert editorial.load_provider().api_key=='gemini-private-key'
    assert client.post('/api/editor/profiles/openai/activate').status_code==200
    assert editorial.load_provider().api_key=='old-private-key'
    assert client.post('/api/editor/profiles/other/activate').status_code==200
    assert editorial.load_provider().api_key==''  # never inherit an unrelated key
    assert client.put('/api/editor/profiles/sixth',json=gemini).status_code==404
    invalid=client.put('/api/editor/profiles/gemini',json=gemini|{'api_key':'SECRET 中文'})
    assert invalid.status_code==422 and 'SECRET' not in invalid.text
    assert client.put('/api/editor/profiles/gemini',json=gemini|{'api_key':'','clear_key':True}).status_code==200
    assert not next(x for x in client.get('/api/editor/profiles').json()['profiles'] if x['id']=='gemini')['api_key_configured']


def test_whole_manuscript_finalize_ignores_ai_veto_preserves_versions_and_forks(client,monkeypatch):
    unit,run=prepared(client,monkeypatch)
    run=save(client,run,body=run['items'][0]['body']|{'uncertainty':'AI认为可能需要拓展，教师判断属于教学取舍'}).json()
    assert run['final_blockers']==[]
    assert client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':False}).status_code==422
    final=client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True})
    assert final.status_code==201,final.text
    version=final.json();assert len(version['snapshot']['items'])==2 and version['snapshot']['relations']==[]
    original=client.get(f"/api/knowledge/versions/{version['id']}/download").content
    run=client.get(f"/api/editor/runs/{run['id']}").json()
    assert run['final_version']['id']==version['id']
    assert save(client,run).status_code==409
    assert client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True}).json()['id']==version['id']
    fork=client.post(f"/api/editor/versions/{version['id']}/revise").json()
    assert fork['id']!=run['id'] and fork['parent_version']==version['id'] and not fork['calls']
    assert fork['items'][0]['review_state']=='pending'
    modified=save(client,fork,body=fork['items'][0]['body']|{'positive_example':'3x=6'}).json()
    assert save(client,fork).status_code==409  # stale local revision rejected
    next_version=client.post(f"/api/editor/runs/{modified['id']}/finalize",json={'revision':modified['revision'],'confirmed':True}).json()
    assert next_version['id']!=version['id']
    assert next_version['snapshot']['editorial']['parent_version']==version['id']
    assert client.get(f"/api/knowledge/versions/{version['id']}/download").content==original
    assert len(client.get(f"/api/knowledge/units/{unit['id']}/versions").json())==2


def test_structure_range_remove_restore_and_order_are_revision_bound(client,monkeypatch):
    _,run=prepared(client,monkeypatch);first,second=run['items']
    assert client.post(f"/api/editor/runs/{run['id']}/arrange",json={'revision':run['revision'],'item_id':'wrong','action':'remove'}).status_code==422
    url=f"/api/editor/runs/{run['id']}/arrange"
    run=client.post(url,json={'revision':run['revision'],'item_id':second['id'],'action':'up'}).json()
    assert run['items'][0]['id']==second['id']
    run=client.post(url,json={'revision':run['revision'],'item_id':first['id'],'action':'remove'}).json()
    assert first['id'] in run['removed']
    run=client.post(url,json={'revision':run['revision'],'item_id':first['id'],'action':'restore'}).json()
    assert first['id'] not in run['removed']
    run=save(client,run,body=run['items'][0]['body']|{'positive_example':''},scope='pending').json()
    assert any('正例' in x for x in run['final_blockers']) and any('适用范围' in x for x in run['final_blockers'])
    assert client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True}).status_code==422
    run=client.post(url,json={'revision':run['revision'],'item_id':run['items'][0]['id'],'action':'remove'}).json()
    final=client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True})
    assert final.status_code==201 and len(final.json()['snapshot']['items'])==1


def test_chat_carries_unsaved_context_and_history_without_mutating_manuscript(client,monkeypatch):
    _,run=prepared(client,monkeypatch);seen=[]
    def model(config,system,payload,max_tokens):
        seen.append((config,system,payload));return '请补充 $x\\ne0$ 的条件。',{'total_tokens':20}
    monkeypatch.setattr(editorial,'generate',model)
    unsaved=run['items'][0]['body']|{'statement':'教师尚未保存的表述'}
    response=send(client,run,body=unsaved)
    assert response.status_code==201,response.text
    assert response.json()['status']=='completed'
    assert seen[0][2]['current_item']==unsaved and seen[0][2]['uses_unsaved_body']
    assert seen[0][0].json_mode is False
    assert send(client,run,body=unsaved).json()['id']==response.json()['id']
    assert len(seen)==1  # duplicate submit never repeats paid call
    assert send(client,run,request_key='request-unique-2',instruction='再举一个例子').json()['status']=='completed'
    assert seen[1][2]['history'][0]['reply'].startswith('请补充')
    current=client.get(f"/api/editor/runs/{run['id']}").json()
    assert current['revision']==run['revision'] and current['items'][0]['body']!=unsaved
    assert len(client.get(f"/api/editor/runs/{run['id']}/messages").json())==2


def test_supplement_acceptance_is_atomic_and_refuses_outdated_proposals(client,monkeypatch):
    _,run=prepared(client,monkeypatch)
    monkeypatch.setattr(editorial,'generate',lambda *_:(json.dumps({'items':[body('补充知识')]}),None))
    msg=send(client,run,'supplement').json();assert msg['status']=='completed'
    accept=f"/api/editor/runs/{run['id']}/supplements"
    assert client.post(accept,json={'revision':run['revision'],'selections':[{'message_id':msg['id'],'index':2}]}).status_code==422
    assert len(client.get(f"/api/editor/runs/{run['id']}").json()['items'])==2
    response=client.post(accept,json={'revision':run['revision'],'selections':[{'message_id':msg['id'],'index':0}]})
    assert response.status_code==200,response.text
    next_run=response.json();assert len(next_run['items'])==3 and next_run['items'][-1]['scope']=='pending'
    assert next_run['items'][-1]['origin']=='model_prior'
    assert client.post(accept,json={'revision':next_run['revision'],'selections':[{'message_id':msg['id'],'index':0}]}).status_code==409
    assert client.get(f"/api/editor/runs/{run['id']}/messages").json()[0]['adopted']==[0]


def test_ai_relations_are_unverified_validate_endpoints_and_do_not_enter_final(client,monkeypatch):
    _,run=prepared(client,monkeypatch)
    edge={'source_id':run['items'][0]['knowledge_id'],'target_id':run['items'][1]['knowledge_id'],'relation_type':'uses','reason':'使用等式性质','conditions':'等式变形满足条件','example':'两边同加一个数'}
    monkeypatch.setattr(editorial,'generate',lambda *_:(json.dumps({'relations':[edge]}),None))
    response=send(client,run,'relations');assert response.json()['status']=='completed',response.text
    assert response.json()['result']['teacher_verified'] is False
    assert response.json()['result']['context_revision']==run['revision']
    monkeypatch.setattr(editorial,'generate',lambda *_:(json.dumps({'relations':[edge|{'target_id':'not-real'}]}),None))
    bad=send(client,run,'relations',request_key='bad-relation-request').json()
    assert bad['status']=='failed' and bad['result'] is None
    final=client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True}).json()
    assert final['snapshot']['relations']==[]


def test_failed_chat_is_preserved_and_not_retried_automatically(client,monkeypatch):
    _,run=prepared(client,monkeypatch);calls=[]
    def fail(*_):calls.append(1);raise ValueError('test-secret-DO-NOT-RETURN 超时')
    monkeypatch.setattr(editorial,'generate',fail)
    response=send(client,run).json();assert response['status']=='failed' and 'test-secret' not in response['error']
    assert send(client,run).json()['id']==response['id'] and len(calls)==1
    assert client.get(f"/api/editor/runs/{run['id']}").json()['revision']==run['revision']


def test_source_changes_reject_finalize_save_and_version_fork(client,monkeypatch):
    unit,run=prepared(client,monkeypatch)
    final=client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True}).json()
    response=client.put(f"/api/knowledge/units/{unit['id']}",json={'revision':unit['revision'],'title':unit['title'],'chapters':unit['chapters'],'target':unit['target'],'notes':'范围已经调整'})
    assert response.status_code==200
    assert client.post(f"/api/editor/versions/{final['id']}/revise").status_code==409
    current=client.get(f"/api/editor/runs/{run['id']}").json()
    assert current['stale'] and save(client,current).status_code==409


def test_frozen_context_remains_exact_after_original_working_run_is_changed(client,monkeypatch):
    _,run=prepared(client,monkeypatch)
    final=client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True}).json()
    snapshot=final['snapshot'];item=snapshot['items'][0]
    # Old compatibility editing APIs can create a later live revision; frozen context must not follow it.
    assert client.put(f"/api/knowledge/candidates/{item['id']}",json={'revision':item['revision'],'body':item['body']|{'statement':'较新的工作内容'},'scope':'core','review_note':''}).status_code==200
    seen=[]
    def model(config,system,payload,max_tokens):seen.append(payload);return '基于终稿的讨论',None
    monkeypatch.setattr(editorial,'generate',model)
    response=send(client,run,revision=snapshot['run_revision'],version_id=final['id'],candidate_id=item['id'])
    assert response.status_code==201 and response.json()['status']=='completed',response.text
    assert seen[0]['current_item']['statement']==item['body']['statement']
    assert seen[0]['source_version']==final['id']
    assert client.get(f"/api/editor/versions/{final['id']}").json()['snapshot']==snapshot


def test_switching_active_profile_does_not_reassign_queued_generation(client):
    _,run=setup(client)
    client.get('/api/editor/profiles')
    response=client.post('/api/editor/profiles/gemini/activate')
    assert response.status_code==409
    assert editorial.load_provider().model=='test-model'


def test_cross_unit_edits_and_foreign_proposals_are_rejected(client,monkeypatch):
    _,first=prepared(client,monkeypatch);_,second=prepared(client,monkeypatch)
    assert save(client,first,item=second['items'][0]).status_code==422
    monkeypatch.setattr(editorial,'generate',lambda *_:(json.dumps({'items':[body('额外条目')]}),None))
    proposal=send(client,first,'supplement').json()
    response=client.post(f"/api/editor/runs/{second['id']}/supplements",json={'revision':second['revision'],'selections':[{'message_id':proposal['id'],'index':0}]})
    assert response.status_code==422
    assert len(client.get(f"/api/editor/runs/{second['id']}").json()['items'])==2


def section_relations(client,monkeypatch,run,key='section-relations-test'):
    ids=[x['knowledge_id'] for x in run['items']]
    edge={'source_id':ids[0],'target_id':ids[1],'relation_type':'uses','reason':'原始AI建议','conditions':'满足相应成立条件','example':'解释等式变形'}
    monkeypatch.setattr(editorial,'generate',lambda *_:(json.dumps({'relations':[edge]}),None))
    r=send(client,run,'relations',request_key=key);assert r.status_code==201,r.text
    assert r.json()['status']=='completed',r.text
    return r.json(),edge


def test_section_final_freezes_teacher_edited_relations_and_preserves_original_suggestions(client,monkeypatch):
    unit,run=prepared(client,monkeypatch);m,edge=section_relations(client,monkeypatch,run)
    edited=edge|{'reason':'教师已核查：方法的使用必须满足性质条件'}
    r=client.post(f"/api/editor/runs/{run['id']}/finalize",json={'revision':run['revision'],'confirmed':True,'relation_message_id':m['id'],'relations':[edited]})
    assert r.status_code==201,r.text
    f=r.json();assert f['snapshot']['editorial']['relations_teacher_confirmed']
    assert f['snapshot']['relations'][0]['body']==edited and f['snapshot']['relations'][0]['teacher_verified']
    messages=client.get(f"/api/editor/runs/{run['id']}/messages").json()
    assert messages[-1]['result']['relations'][0]==edge
    url=f"/api/knowledge/versions/{f['id']}/download";original=client.get(url).content
    ctx=client.post('/api/research/contexts',json={'title':'小节终稿依据','version_ids':[f['id']]})
    assert ctx.status_code==201,ctx.text
    assert ctx.json()['snapshot']['inherited_relations'][0]['reason']==edited['reason']
    fork=client.post(f"/api/editor/versions/{f['id']}/revise").json()
    save(client,fork,body=fork['items'][0]['body']|{'positive_example':'教师修改了例子'})
    assert client.get(url).content==original


def test_section_final_rejects_stale_relation_context_and_bad_endpoints(client,monkeypatch):
    _,run=prepared(client,monkeypatch);m,edge=section_relations(client,monkeypatch,run)
    url=f"/api/editor/runs/{run['id']}/finalize";base={'revision':run['revision'],'confirmed':True,'relation_message_id':m['id']}
    assert client.post(url,json=base).status_code==422
    for edges in [[edge|{'target_id':'foreign'}],[edge|{'target_id':edge['source_id']}],[edge,edge]]:
        r=client.post(url,json=base|{'relations':edges});assert r.status_code==422,r.text
    changed=save(client,run,body=run['items'][0]['body']|{'positive_example':'换个例子'}).json()
    response=client.post(url,json=base|{'revision':changed['revision'],'relations':[edge]})
    assert response.status_code==409 and '关系依据已变化' in response.text
    assert client.get(f"/api/knowledge/units/{run['unit_id']}/versions").json()==[]
    m2,e2=section_relations(client,monkeypatch,changed,'section-new-relations')
    # An empty AI list can be explicitly confirmed; absence of edges does not prove completeness.
    response=client.post(url,json={'revision':changed['revision'],'confirmed':True,'relation_message_id':m2['id'],'relations':[]})
    assert response.status_code==201,response.text
    assert response.json()['snapshot']['relations']==[] and response.json()['snapshot']['editorial']['relations_teacher_confirmed']
