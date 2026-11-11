import json
import pytest
from test_knowledge import client,setup,complete
from test_knowledge_actions import approve_all
from test_planning import upload
from mathlet import knowledge_worker as worker
from mathlet.db import connect,init_db


def context(client,monkeypatch):
    _,run=setup(client);base=approve_all(client,complete(client,run,monkeypatch))
    version=client.post(f"/api/knowledge/runs/{base['id']}/versions",json={'revision':base['revision']}).json()
    response=client.post('/api/research/contexts',json={'title':'已审核知识研究','version_ids':[version['id']]})
    assert response.status_code==201,response.text
    return response.json(),base,version


def question(client,answer_status='absent',reference_answer=''):
    doc=upload(client,['反比例函数 y=k/x 的图象经过点(2,3)，求k。'],'exam')
    block=client.get(f'/api/documents/{doc}/blocks').json()[0]
    body={'title':'反比例函数求系数','question_block_ids':[block['id']],'statement':block['text'],'answer_status':answer_status,'reference_answer':reference_answer,'figure_status':'not_needed'}
    response=client.post('/api/research/questions',json=body);assert response.status_code==201,response.text
    value=response.json()
    confirmed=client.post(f"/api/research/questions/{value['id']}/confirm",json={'revision':value['revision'],'reviewer':'数学老师','note':'已对照原文核对题干及答案状态','confirmed':True})
    assert confirmed.status_code==200,confirmed.text
    return confirmed.json(),body,block


def analysis(ref):
    return {'problem_types':['已知点求反比例函数系数'],'classification_reason':'点在函数图象上提供数量关系',
        'assessed_points':[{'name':'点的坐标满足函数表达式','knowledge_refs':[ref],'evidence':'图象经过(2,3)'}],
        'knowledge_breakdown':[{'ref':ref,'role':'建立方程','conditions':'x不为零'}],
        'approaches':[{'id':'substitute','title':'代入点坐标','trigger':'已知点在图象上','steps':[{'action':'将x=2,y=3代入，得到3=k/2','reason':'图象上点的坐标满足表达式','knowledge_refs':[ref]}],'conclusion':'k=6','checks':'检验3=6/2且k不为零','limitations':'适用于给出非零横坐标的点'}],
        'recognition_cues':['已知图象上一点'],'common_mistakes':['交换横纵坐标'],'variation_prompts':['改变已知点坐标，检查条件是否仍成立'],'scope_notes':[],'missing_information':[]}


def model(config,system,payload,max_tokens):
    if 'candidates' in payload:return json.dumps({'issues':[]}),{'total_tokens':20}
    refs=[x['ref'] for x in payload['knowledge']['items']]
    if 'question' in payload:return json.dumps(analysis(refs[0])),{'total_tokens':200}
    return json.dumps({'relations':[{'source_ref':refs[0],'target_ref':refs[1],'relation_type':'contrast','reason':'区分概念与变形依据','conditions':'分别明确概念和适用条件','example':'判断方程和解释变形依据'}]}),{'total_tokens':100}


def start(client,ctx,monkeypatch,kind='connections',q=None,graph=None):
    monkeypatch.setattr(worker,'generate',model)
    response=client.post('/api/research/runs',json={'kind':kind,'context_id':ctx['id'],'context_revision':ctx['revision'],'question_version_id':q['version_id'] if q else None,'graph_version_id':graph,'consent':True,'limit':2})
    assert response.status_code==201,response.text
    worker.run_one_knowledge();result=client.get('/api/research/runs/'+response.json()['id']).json()
    assert result['status']=='completed',result.get('error')
    return result


def review(client,task,**extra):
    return client.post(f"/api/research/runs/{task['id']}/review",json={'run_revision':task['revision'],'items':[{'id':x['id'],'revision':x['revision']} for x in task['outputs']],'reviewer':'数学老师','note':'已逐项检查内容与适用条件','confirmed':True,**extra})


def test_version_bound_connections_question_research_and_immutable_delivery(client,monkeypatch):
    ctx,base,version=context(client,monkeypatch)
    task=start(client,ctx,monkeypatch)
    assert len(task['calls'])==2 and task['outputs'][0]['state']=='pending'
    assert review(client,task).status_code==200
    ctx=client.get('/api/research/contexts').json()[0]
    assert ctx['revision']==2
    graph=client.post(f"/api/research/contexts/{ctx['id']}/graph-versions",json={'revision':ctx['revision']}).json()
    assert len(graph['snapshot']['reviewed_relations'])==1
    q,body,block=question(client)
    assert not block['verified'] and q['confirmed']
    task=start(client,ctx,monkeypatch,'analysis',q,graph['id'])
    assert task['outputs'][0]['body']['approaches'][0]['conclusion']=='k=6'
    assert review(client,task).status_code==200
    task=client.get('/api/research/runs/'+task['id']).json();out=task['outputs'][0]
    frozen=client.post(f"/api/research/outputs/{out['id']}/versions",json={'revision':out['revision']})
    assert frozen.status_code==201,frozen.text
    version_id=frozen.json()['id'];saved=client.get(f'/api/research/versions/analysis/{version_id}/download').content
    assert json.loads(saved)['input']['question_version_id']==q['version_id']
    changed=client.put(f"/api/research/questions/{q['id']}",json={**body,'revision':q['revision'],'statement':body['statement']+'请说明理由。'})
    assert changed.status_code==200 and not changed.json()['confirmed']
    assert client.get('/api/research/runs/'+task['id']).json()['stale']
    assert client.post(f"/api/research/outputs/{out['id']}/versions",json={'revision':out['revision']}).status_code==409
    init_db();assert client.get(f'/api/research/versions/analysis/{version_id}/download').content==saved
    # Original approved knowledge remains unchanged by all research operations.
    assert client.get(f"/api/knowledge/runs/{base['id']}").json()['items']==base['items']


def test_unchecked_answer_and_image_bytes_are_not_sent_to_model(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client,'unchecked','UNREVIEWED-SECRET-ANSWER')
    sent=[]
    def capture(config,system,payload,max_tokens):sent.append(payload);return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',capture)
    response=client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'],'consent':True})
    worker.run_one_knowledge();task=client.get('/api/research/runs/'+response.json()['id']).json()
    assert task['status']=='completed',task.get('error')
    assert 'UNREVIEWED-SECRET-ANSWER' not in json.dumps(sent)
    assert 'reference_answer' not in sent[0]['question']
    assert 'data:image' not in json.dumps(sent)
    artifacts=client.get(f"/api/knowledge/runs/{task['id']}/artifacts").json()
    assert 'UNREVIEWED-SECRET-ANSWER' not in json.dumps(artifacts)


def test_source_and_knowledge_changes_invalidate_pending_research(client,monkeypatch):
    ctx,base,_=context(client,monkeypatch);q,body,block=question(client)
    task=start(client,ctx,monkeypatch,'analysis',q)
    client.put(f"/api/blocks/{block['id']}",json={'revision':block['revision'],'text':block['text']+'来源改动','verified':False})
    assert review(client,task).status_code==409
    assert client.get('/api/research/questions').json()[0]['stale']
    item=base['items'][0]
    client.put(f"/api/knowledge/candidates/{item['id']}",json={'revision':item['revision'],'body':item['body'],'scope':'core'})
    assert client.get('/api/research/contexts').json()[0]['stale']
    assert client.get('/api/research/knowledge-versions').json()[0]['stale']
    assert client.post('/api/research/runs',json={'kind':'connections','context_id':ctx['id'],'context_revision':1,'consent':True}).status_code==409


def test_analysis_requires_complete_confirmed_question_and_explicit_consent(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch)
    assert client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'consent':True}).status_code==422
    assert client.post('/api/research/runs',json={'kind':'connections','context_id':ctx['id'],'context_revision':1,'consent':False}).status_code==422
    q,body,_=question(client)
    pending=client.put(f"/api/research/questions/{q['id']}",json={**body,'revision':q['revision'],'figure_status':'pending'}).json()
    assert client.post(f"/api/research/questions/{q['id']}/confirm",json={'revision':pending['revision'],'reviewer':'老师','note':'待核对','confirmed':True}).status_code==422
    assert client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'],'consent':True}).status_code==409


@pytest.mark.parametrize('kind',['connections','analysis'])
def test_unknown_knowledge_references_reject_entire_model_output(client,monkeypatch,kind):
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client)
    def invalid(config,system,payload,max_tokens):
        raw,usage=model(config,system,payload,max_tokens);value=json.loads(raw)
        if 'knowledge' in payload:
            if 'relations' in value:value['relations'][0]['target_ref']='foreign'
            else:value['knowledge_breakdown'][0]['ref']='foreign'
        return json.dumps(value),usage
    monkeypatch.setattr(worker,'generate',invalid)
    response=client.post('/api/research/runs',json={'kind':kind,'context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'] if kind=='analysis' else None,'consent':True})
    worker.run_one_knowledge();task=client.get('/api/research/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and not task['outputs']


def test_critic_failure_reuses_draft_checkpoint_and_teacher_edits_preserve_original(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client)
    def fail(config,system,payload,max_tokens):
        if 'candidates' in payload:raise ValueError('复核暂时失败')
        return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',fail)
    response=client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'],'consent':True})
    worker.run_one_knowledge();task=client.get('/api/research/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and not task['outputs']
    assert client.post('/api/research/runs/'+task['id']+'/retry',json={'revision':task['revision']}).status_code==200
    calls=[]
    def retry(config,system,payload,max_tokens):calls.append(payload);return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',retry);worker.run_one_knowledge()
    task=client.get('/api/research/runs/'+task['id']).json();assert task['status']=='completed' and len(calls)==1 and len(task['calls'])==3
    out=task['outputs'][0];edited=out['body']|{'scope_notes':['教师补充范围说明']}
    response=client.put('/api/research/outputs/'+out['id'],json={'revision':out['revision'],'body':edited})
    assert response.status_code==200,response.text
    latest=response.json();assert latest['outputs'][0]['original_body']==out['original_body']
    assert client.put('/api/research/outputs/'+out['id'],json={'revision':out['revision'],'body':edited}).status_code==409
    assert client.get('/api/research/outputs/'+out['id']+'/history').json()


def test_missing_information_blocks_approval_until_teacher_resolves_it(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client)
    task=start(client,ctx,monkeypatch,'analysis',q);out=task['outputs'][0]
    changed=out['body']|{'missing_information':['尚需明确条件']}
    updated=client.put('/api/research/outputs/'+out['id'],json={'revision':out['revision'],'body':changed}).json()
    assert review(client,updated).status_code==422
    assert review(client,updated,decision='return').status_code==200


def test_withdrawn_relation_invalidates_graph_dependency_not_archived_graph_bytes(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);task=start(client,ctx,monkeypatch)
    assert review(client,task).status_code==200;ctx=client.get('/api/research/contexts').json()[0]
    graph=client.post(f"/api/research/contexts/{ctx['id']}/graph-versions",json={'revision':ctx['revision']}).json()
    saved=client.get(f"/api/research/versions/graph/{graph['id']}/download").content
    relation=client.get(f"/api/research/contexts/{ctx['id']}/relations").json()[0]
    q,_,_=question(client);analysis_task=start(client,ctx,monkeypatch,'analysis',q,graph['id'])
    response=client.post(f"/api/research/relations/{relation['id']}/withdraw",json={'revision':relation['revision'],'context_revision':ctx['revision'],'reviewer':'老师','note':'方向需重审','confirmed':True})
    assert response.status_code==200,response.text
    assert review(client,analysis_task).status_code==409
    assert client.get(f"/api/research/versions/graph/{graph['id']}/download").content==saved


def test_two_knowledge_versions_preserve_separate_identities_and_cross_unit_refs(client,monkeypatch):
    _,_,a=context(client,monkeypatch);_,_,b=context(client,monkeypatch)
    response=client.post('/api/research/contexts',json={'title':'跨单元知识','version_ids':[a['id'],b['id']]})
    assert response.status_code==201,response.text
    ctx=response.json();items=ctx['snapshot']['items']
    assert len(items)==4 and len({x['ref'] for x in items})==4
    assert len({x['title'] for x in items})==2  # Same labels never imply automatic identity merging.
    assert client.post('/api/research/contexts',json={'title':'重复版本','version_ids':[a['id'],a['id']]}).status_code==422


def test_diagram_confirmation_and_archived_image_bytes_are_preserved_not_sent(client,monkeypatch):
    from mathlet.db import data_dir
    from PIL import Image
    ctx,_,_=context(client,monkeypatch);q,body,block=question(client)
    path=data_dir()/'documents'/block['document_id']/'assets'/'test-figure.png';path.parent.mkdir(exist_ok=True)
    Image.new('RGB',(10,10),'white').save(path)
    with connect() as c:c.execute('UPDATE blocks SET assets=? WHERE id=?',(json.dumps(['test-figure.png']),block['id']))
    edited=client.put(f"/api/research/questions/{q['id']}",json={**body,'revision':q['revision']}).json()
    check={'revision':edited['revision'],'reviewer':'老师','note':'核对完整题干及配图','confirmed':True}
    assert client.post(f"/api/research/questions/{q['id']}/confirm",json=check).status_code==422
    edited=client.put(f"/api/research/questions/{q['id']}",json={**body,'revision':edited['revision'],'figure_status':'described','diagram_description':'坐标系中点(2,3)位于图象上'}).json()
    check['revision']=edited['revision'];q=client.post(f"/api/research/questions/{q['id']}/confirm",json=check).json()
    saved=client.get(f"/api/research/versions/question/{q['version_id']}/download").content
    assert 'data:image/png;base64,' in saved.decode()
    payloads=[]
    def capture(config,system,payload,max_tokens):payloads.append(payload);return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',capture)
    response=client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'],'consent':True})
    worker.run_one_knowledge();assert client.get('/api/research/runs/'+response.json()['id']).json()['status']=='completed'
    assert 'data:image' not in json.dumps(payloads)
    Image.new('RGB',(10,10),'black').save(path)
    assert client.get('/api/research/questions').json()[0]['stale']
    assert client.get(f"/api/research/versions/question/{q['version_id']}/download").content==saved


def test_unverified_reference_answer_blocks_cannot_be_marked_verified(client,monkeypatch):
    _,body,block=question(client)
    response=client.post('/api/research/questions',json={**body,'answer_block_ids':[block['id']],'answer_status':'verified','reference_answer':'k=6'})
    assert response.status_code==422


def test_research_source_change_during_model_call_discards_result(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);q,_,block=question(client)
    def concurrent(config,system,payload,max_tokens):
        value=model(config,system,payload,max_tokens)
        if 'knowledge' in payload:
            with connect() as c:c.execute('UPDATE blocks SET text=text||? WHERE id=?',('原题已修改',block['id']))
        return value
    monkeypatch.setattr(worker,'generate',concurrent)
    response=client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'],'consent':True})
    worker.run_one_knowledge();task=client.get('/api/research/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and not task['outputs']
    assert client.post('/api/research/runs/'+task['id']+'/retry',json={'revision':task['revision']}).status_code==409


def test_teacher_verified_transcription_is_sent_with_its_true_basis(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client,'verified','k=6')
    sent=[]
    def capture(config,system,payload,max_tokens):sent.append(payload);return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',capture)
    response=client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'],'consent':True})
    worker.run_one_knowledge()
    assert client.get('/api/research/runs/'+response.json()['id']).json()['status']=='completed'
    assert sent[0]['question']['reference_answer']=='k=6'
    assert sent[0]['question']['reference_answer_basis']=='teacher_transcription'


def test_analysis_edit_revokes_approval_and_retains_old_download(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client)
    task=start(client,ctx,monkeypatch,'analysis',q);assert review(client,task).status_code==200
    task=client.get('/api/research/runs/'+task['id']).json();out=task['outputs'][0]
    frozen=client.post('/api/research/outputs/'+out['id']+'/versions',json={'revision':out['revision']}).json()
    url='/api/research/versions/analysis/'+frozen['id']+'/download';saved=client.get(url).content
    changed=client.put('/api/research/outputs/'+out['id'],json={'revision':out['revision'],'body':out['body']|{'scope_notes':['教师修订范围说明']}})
    assert changed.status_code==200,changed.text
    fresh=changed.json()['outputs'][0]
    assert fresh['state']=='pending' and not fresh['reviewer']
    assert client.post('/api/research/outputs/'+out['id']+'/versions',json={'revision':fresh['revision']}).status_code==409
    assert client.get(url).content==saved


def test_independent_critic_cannot_reference_nonexistent_approach(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);q,_,_=question(client)
    def critic(config,system,payload,max_tokens):
        if 'candidates' in payload:return json.dumps({'issues':[{'approach_id':'not-a-path','category':'correctness','message':'不应引用不存在的解法'}]}),None
        return model(config,system,payload,max_tokens)
    monkeypatch.setattr(worker,'generate',critic)
    response=client.post('/api/research/runs',json={'kind':'analysis','context_id':ctx['id'],'context_revision':1,'question_version_id':q['version_id'],'consent':True})
    worker.run_one_knowledge();task=client.get('/api/research/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and not task['outputs']


def test_revoking_answer_source_confirmation_invalidates_question_research(client,monkeypatch):
    ctx,_,_=context(client,monkeypatch);_,body,block=question(client)
    verified=client.put('/api/blocks/'+block['id'],json={'revision':block['revision'],'text':block['text'],'verified':True}).json()
    response=client.post('/api/research/questions',json={**body,'answer_block_ids':[block['id']],'answer_status':'verified','reference_answer':'k=6'})
    q=response.json();q=client.post(f"/api/research/questions/{q['id']}/confirm",json={'revision':1,'reviewer':'老师','note':'已核对题干与参考答案','confirmed':True}).json()
    task=start(client,ctx,monkeypatch,'analysis',q)
    client.put('/api/blocks/'+block['id'],json={'revision':verified['revision'],'text':verified['text'],'verified':False})
    assert review(client,task).status_code==409
    assert next(x for x in client.get('/api/research/questions').json() if x['id']==q['id'])['stale']
