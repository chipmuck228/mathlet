import json
from test_knowledge import client
from test_research import context,question,model,analysis
from mathlet import knowledge_worker as worker,editorial,research_editor
from mathlet.db import connect,init_db


def authoring_model(config,system,payload,max_tokens):
    raw,usage=model(config,system,payload,max_tokens)
    if 'question' in payload and 'candidates' not in payload:
        value=json.loads(raw);value.update(given_conditions=['图象经过点(2,3)'],goals=['求k'],thinking_operations=['代入与检验']);raw=json.dumps(value)
    return raw,usage


def start(client,monkeypatch,unchecked=False):
    _,base,version=context(client,monkeypatch)
    q,body,block=question(client,'unchecked' if unchecked else 'absent','DO-NOT-SEND-ANSWER' if unchecked else '')
    monkeypatch.setattr(worker,'generate',authoring_model)
    response=client.post('/api/research-editor/runs',json={'version_ids':[version['id']],'question_version_id':q['version_id'],'request_key':'single-question-request','limit':2})
    assert response.status_code==201,response.text
    assert worker.run_one_knowledge()
    result=client.get('/api/research-editor/runs/'+response.json()['id']).json()
    assert result['status']=='completed',result.get('error')
    return result,version,q,body,block


def save(client,task,body=None):
    out=task['outputs'][0]
    return client.put(f"/api/research-editor/runs/{task['id']}/outputs/{out['id']}",json={'run_revision':task['revision'],'revision':out['revision'],'body':body or out['body']})


def finalize(client,task,confirmed=True):
    out=task['outputs'][0]
    return client.post(f"/api/research-editor/runs/{task['id']}/outputs/{out['id']}/finalize",json={'run_revision':task['revision'],'revision':out['revision'],'confirmed':confirmed})


def chat(client,task,**changes):
    out=task['outputs'][0]
    request={'output_id':out['id'],'revision':out['revision'],'run_revision':task['revision'],'body':out['body'],'instruction':'请说明成立条件','profile_id':'openai','request_key':'discussion-unique-request'}|changes
    return client.post(f"/api/research-editor/runs/{task['id']}/discussions",json=request)


def test_new_generation_is_version_bound_idempotent_and_old_manuscripts_open_without_calls(client,monkeypatch):
    task,v,q,_,_=start(client,monkeypatch)
    assert task['task']['workflow']=='manuscript-v1'
    assert len(task['calls'])==2 and 'given_conditions' in task['outputs'][0]['body']
    repeat=client.post('/api/research-editor/runs',json={'version_ids':[v['id']],'question_version_id':q['version_id'],'request_key':'single-question-request','limit':2})
    assert repeat.status_code==201 and repeat.json()['id']==task['id']
    assert not worker.run_one_knowledge()
    summaries=client.get('/api/research-editor/runs').json()
    assert summaries[0]['id']==task['id'] and 'knowledge' not in summaries[0] and 'question' not in summaries[0]
    assert 'body' not in summaries[0]['outputs'][0]
    assert client.get('/api/research-editor/runs/'+task['id']).json()['outputs']==task['outputs']


def test_advisory_relations_match_exact_knowledge_final_and_remain_unverified(client,monkeypatch):
    _,base,v=context(client,monkeypatch);client.get('/api/editor/profiles')
    ids=[x['knowledge_id'] for x in v['snapshot']['items']]
    edge={'source_id':ids[0],'target_id':ids[1],'relation_type':'contrast','reason':'区分定义与变形依据','conditions':'等式变形满足相应条件','example':'判断方程并解释变形'}
    monkeypatch.setattr(editorial,'generate',lambda *_:(json.dumps({'relations':[edge]}),None))
    message=client.post(f"/api/editor/runs/{base['id']}/messages",json={'revision':base['revision'],'request_key':'advisory-relation-request','action':'relations','version_id':v['id'],'instruction':'生成关系','profile_id':'openai'}).json()
    assert message['status']=='completed',message
    listed=client.get('/api/research-editor/relation-references',params={'version_ids':v['id']}).json()
    assert listed[0]['id']==message['id'] and listed[0]['teacher_verified'] is False
    q,_,_=question(client)
    monkeypatch.setattr(worker,'generate',authoring_model)
    response=client.post('/api/research-editor/runs',json={'version_ids':[v['id']],'question_version_id':q['version_id'],'relation_message_ids':[message['id']],'request_key':'with-advisory-request'})
    assert response.status_code==201,response.text
    received=[]
    def capture(config,system,payload,max_tokens):received.append((system,payload));return authoring_model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',capture);worker.run_one_knowledge()
    task=client.get('/api/research-editor/runs/'+response.json()['id']).json()
    assert task['status']=='completed',task.get('error')
    assert received[0][1]['knowledge']['advisory_relations'][0]['teacher_verified'] is False
    assert '不能当作证明' in received[0][0]
    final=finalize(client,task).json()
    assert final['snapshot']['editorial']['advisory_relations_teacher_verified'] is False
    assert final['snapshot']['knowledge']['advisory_relations'][0]['basis']=='ai_suggestion'
    # A relationship generated for a different final cannot be injected into this one.
    bad=client.post('/api/research-editor/runs',json={'version_ids':[v['id']],'question_version_id':q['version_id'],'relation_message_ids':['foreign-message'],'request_key':'foreign-reference-request'})
    assert bad.status_code==409


def test_inline_save_whole_final_and_revision_fork_keep_old_file_immutable(client,monkeypatch):
    task,_,_,_,_=start(client,monkeypatch)
    out=task['outputs'][0];updated=out['body']|{'given_conditions':['图象经过点(2,3)'],'goals':['求系数k'],'thinking_operations':['代入','检验非零条件']}
    task=save(client,task,updated).json()
    assert task['outputs'][0]['state']=='pending' and task['outputs'][0]['final_version'] is None
    assert client.get('/api/research/analysis-versions').json()==[]
    assert finalize(client,task,False).status_code==422
    final=finalize(client,task);assert final.status_code==201,final.text
    frozen=final.json();original=client.get(f"/api/research/versions/analysis/{frozen['id']}/download").content
    task=client.get('/api/research-editor/runs/'+task['id']).json()
    assert task['outputs'][0]['final_version']['id']==frozen['id']
    assert save(client,task).status_code==409
    fork=client.post(f"/api/research-editor/versions/{frozen['id']}/revise").json()
    assert fork['id']!=task['id'] and fork['parent_version']==frozen['id'] and fork['calls']==[]
    body=fork['outputs'][0]['body']|{'common_mistakes':['漏掉非零条件']}
    next_task=save(client,fork,body).json()
    assert save(client,fork,body).status_code==409
    next_version=finalize(client,next_task).json()
    assert next_version['snapshot']['editorial']['parent_version']==frozen['id']
    init_db();assert client.get(f"/api/research/versions/analysis/{frozen['id']}/download").content==original
    assert client.get(f"/api/research-editor/versions/{frozen['id']}").json()['snapshot']['analysis']==updated


def test_ai_opinion_not_veto_but_missing_information_and_bad_refs_still_block(client,monkeypatch):
    task,_,_,_,_=start(client,monkeypatch);out=task['outputs'][0]
    with connect() as c:c.execute('UPDATE research_outputs SET checks=? WHERE id=?',(json.dumps([{'approach_id':'','category':'teaching','message':'是否增加迁移训练，请教师判断'}]),out['id']))
    missing=save(client,task,out['body']|{'missing_information':['需要补充必要条件']}).json()
    assert missing['outputs'][0]['final_blockers'] and finalize(client,missing).status_code==422
    valid=missing['outputs'][0]['body']|{'missing_information':[]}
    valid['knowledge_breakdown']=[{'ref':'foreign-reference','role':'错误引用','conditions':'未知'}]
    assert save(client,missing,valid).status_code==422
    corrected=save(client,missing,missing['outputs'][0]['body']|{'missing_information':[]}).json()
    assert finalize(client,corrected).status_code==201


def test_chat_carries_unsaved_research_not_unchecked_answer_or_images_and_does_not_edit(client,monkeypatch):
    task,_,_,_,_=start(client,monkeypatch,True);client.get('/api/editor/profiles');seen=[]
    def model_chat(config,system,payload,max_tokens):seen.append(payload);assert config.json_mode is False;return '建议在消元前检查非零条件。',{'total_tokens':10}
    monkeypatch.setattr(research_editor,'generate',model_chat)
    draft=task['outputs'][0]['body']|{'classification_reason':'尚未保存的教师修订'}
    response=chat(client,task,body=draft);assert response.status_code==201,response.text
    assert response.json()['status']=='completed' and response.json()['payload']['uses_unsaved_body']
    assert seen[0]['analysis']['classification_reason']=='尚未保存的教师修订'
    assert 'DO-NOT-SEND-ANSWER' not in json.dumps(seen) and 'data:image' not in json.dumps(seen)
    assert chat(client,task,body=draft).json()['id']==response.json()['id'] and len(seen)==1
    assert chat(client,task,body=draft,instruction='再给一个反例',request_key='next-discussion-request').json()['status']=='completed'
    assert seen[1]['history'][0]['reply'].startswith('建议')
    live=client.get('/api/research-editor/runs/'+task['id']).json()
    assert live['revision']==task['revision'] and live['outputs'][0]['body']==task['outputs'][0]['body']


def test_chat_supports_incomplete_edit_and_failure_preserves_evidence_without_retry(client,monkeypatch):
    task,_,_,_,_=start(client,monkeypatch);client.get('/api/editor/profiles');calls=[]
    def fail(*_):calls.append(1);raise ValueError('test-secret-DO-NOT-RETURN 连接超时')
    monkeypatch.setattr(research_editor,'generate',fail)
    draft=task['outputs'][0]['body']|{'approaches':[]}
    result=chat(client,task,body=draft).json()
    assert result['status']=='failed' and 'test-secret' not in result['error']
    assert chat(client,task,body=draft).json()['id']==result['id'] and len(calls)==1
    assert len(client.get(f"/api/research-editor/runs/{task['id']}/discussions").json())==1


def test_source_change_rejects_save_final_and_fork_but_old_final_stays_readable(client,monkeypatch):
    task,_,q,body,_=start(client,monkeypatch)
    final=finalize(client,task).json()
    fork=client.post(f"/api/research-editor/versions/{final['id']}/revise").json()
    changed=client.put(f"/api/research/questions/{q['id']}",json=body|{'revision':q['revision'],'statement':body['statement']+'请说明理由。'})
    assert changed.status_code==200
    assert client.get('/api/research-editor/runs/'+fork['id']).json()['stale']
    assert save(client,fork).status_code==409 and finalize(client,fork).status_code==409
    assert client.post(f"/api/research-editor/versions/{final['id']}/revise").status_code==409
    assert client.get(f"/api/research-editor/versions/{final['id']}").status_code==200


def test_legacy_question_research_and_legacy_finals_open_in_new_workspace(client,monkeypatch):
    from test_research import start as old_start,review
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client)
    task=old_start(client,ctx,monkeypatch,'analysis',q)
    assert client.get('/api/research-editor/runs/'+task['id']).json()['title']==q['payload']['title']
    assert review(client,task).status_code==200
    task=client.get('/api/research/runs/'+task['id']).json();out=task['outputs'][0]
    final=client.post(f"/api/research/outputs/{out['id']}/versions",json={'revision':out['revision']}).json()
    opened=client.get(f"/api/research-editor/versions/{final['id']}").json()
    assert opened['snapshot']['analysis']==out['body']
    assert client.post(f"/api/research-editor/versions/{final['id']}/revise").status_code==201


def test_frozen_discussion_uses_snapshot_and_foreign_output_is_rejected(client,monkeypatch):
    task,_,_,_,_=start(client,monkeypatch);client.get('/api/editor/profiles')
    final=finalize(client,task).json();version=client.get(f"/api/research-editor/versions/{final['id']}").json()
    # The compatibility API may create a newer working revision. Frozen discussion must stay on its exact snapshot.
    current=client.get('/api/research-editor/runs/'+task['id']).json();out=current['outputs'][0]
    assert client.put(f"/api/research/outputs/{out['id']}",json={'revision':out['revision'],'body':out['body']|{'classification_reason':'较新工作稿'}}).status_code==200
    seen=[]
    def model_chat(config,system,payload,max_tokens):seen.append(payload);return '基于旧终稿讨论',None
    monkeypatch.setattr(research_editor,'generate',model_chat)
    result=chat(client,task,version_id=final['id'],revision=version['revision'],body=version['snapshot']['analysis'])
    assert result.status_code==201 and result.json()['status']=='completed',result.text
    assert seen[0]['analysis']['classification_reason']==version['snapshot']['analysis']['classification_reason']
    assert seen[0]['source_version']==final['id']
    foreign=client.post(f"/api/research-editor/runs/{task['id']}/discussions",json={'output_id':'nonexistent','revision':1,'run_revision':1,'body':{},'instruction':'test','profile_id':'openai','request_key':'foreign-discussion-key'})
    assert foreign.status_code==404


def test_formula_and_incomplete_question_guards_remain_after_simplification(client,monkeypatch):
    task,v,q,body,_=start(client,monkeypatch)
    bad=task['outputs'][0]['body']|{'classification_reason':r'$\unknowncommand{x}$'}
    saved=save(client,task,bad).json()
    assert saved['outputs'][0]['final_blockers'] and finalize(client,saved).status_code==422
    assert client.put(f"/api/research/questions/{q['id']}",json=body|{'revision':q['revision'],'figure_status':'pending'}).status_code==200
    refused=client.post('/api/research-editor/runs',json={'version_ids':[v['id']],'question_version_id':q['version_id'],'request_key':'incomplete-question-key'})
    assert refused.status_code==409
