"""Synthetic documents and mocked models only; no paid calls or original exam data."""
import json
import pytest
from test_knowledge import client
from test_research import context
from test_planning import upload
from test_research_editor import authoring_model,finalize
from mathlet import knowledge_worker as worker
from mathlet.db import connect,init_db


def get(client,p):return client.get('/api/papers/'+p['id']).json()
def post(client,p,action,**extra):return client.post('/api/papers/'+p['id']+'/'+action,json={'revision':p['revision'],**extra})
def save(client,p,item,**changes):return client.put(f"/api/papers/{p['id']}/items/{item['id']}",json={'revision':p['revision'],'item_revision':item['revision'],'body':item['payload']|changes})
def ready(client,monkeypatch):
    _,base,version=context(client,monkeypatch)
    doc=upload(client,['合成测试试卷','1. 图象经过(2,3)，求k。 A. 1 B. 6\n2. 图象经过(3,2)，求k。','答案：1. SECRET-ANSWER 2. k=6','未核对内容不得发送'],'exam')
    blocks=client.get(f'/api/documents/{doc}/blocks').json()
    for b in blocks[:-1]:
        r=client.put('/api/blocks/'+b['id'],json={'revision':b['revision'],'text':b['text'],'verified':True});assert r.status_code==200,r.text
    res=client.post('/api/papers',json={'document_id':doc});assert res.status_code==201,res.text
    return res.json(),blocks,version,base

def split_model(config,system,payload,tokens):
    blocks=payload['blocks'];assert all(b['verified'] for b in blocks)
    assert '未核对内容不得发送' not in json.dumps(payload,ensure_ascii=False)
    b=blocks[1];a=blocks[2]
    return json.dumps({'questions':[{'title':'第一题','number':'1','question_spans':[{'block_id':b['id'],'start_anchor':'1.','end_anchor':'B. 6'}],'answer_spans':[{'block_id':a['id'],'start_anchor':'1.','end_anchor':'SECRET-ANSWER'}]}, {'title':'第二题','number':'2','question_spans':[{'block_id':b['id'],'start_anchor':'2.','end_anchor':'求k。','end_occurrence':1}],'answer_spans':[{'block_id':a['id'],'start_anchor':'2.'}]}],'notes':['页眉未分题']}),None

def split(client,monkeypatch,p,model=split_model):
    monkeypatch.setattr(worker,'generate',model)
    response=post(client,p,'split');assert response.status_code==201,response.text
    worker.run_one_knowledge();p=get(client,p)
    assert p['tasks'][0]['status']=='completed',p['tasks'][0]
    return p

def confirm(client,p,item):
    r=post(client,p,'items/'+item['id']+'/confirm',item_revision=item['revision'],confirmed=True)
    assert r.status_code==200,r.text
    return r.json()

def recommend_model(config,system,payload,tokens):
    assert 'SECRET-ANSWER' not in json.dumps(payload)
    ref=payload['knowledge_catalog'][0]['ref']
    return json.dumps({'matches':[{'item_id':q['id'],'recommendations':[{'ref':ref,'reason':'图象上点用于代入','evidence':'图象经过'}],'gaps':['检查是否缺少函数知识']} for q in payload['questions']]}),None

def recommend(client,monkeypatch,p):
    monkeypatch.setattr(worker,'generate',recommend_model)
    r=post(client,p,'recommend',item_ids=[i['id'] for i in p['items']]);assert r.status_code==201,r.text
    worker.run_one_knowledge();p=get(client,p)
    assert p['tasks'][0]['status']=='completed',p['tasks'][0]
    return p

def research_finals(client,monkeypatch):
    p,blocks,v,base=ready(client,monkeypatch);p=split(client,monkeypatch,p);p=recommend(client,monkeypatch,p)
    for id in [x['id'] for x in p['items']]:p=confirm(client,p,next(x for x in p['items'] if x['id']==id))
    ids=[x['id'] for x in p['items']]
    r=post(client,p,'analyses',item_ids=ids);assert r.status_code==201,r.text
    result=r.json()['results'];assert all('run_id' in x for x in result),result
    repeat=post(client,p,'analyses',item_ids=ids)
    assert [x['run_id'] for x in repeat.json()['results']]==[x['run_id'] for x in result]
    sent=[]
    def capture(config,system,payload,tokens):sent.append(payload);return authoring_model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',capture)
    for _ in result:assert worker.run_one_knowledge()
    assert not worker.run_one_knowledge()
    assert 'SECRET-ANSWER' not in json.dumps(sent)
    for x in sent:
        if 'knowledge' in x:assert len(x['knowledge']['items'])==1
    finals=[]
    for r in result:
        task=client.get('/api/research-editor/runs/'+r['run_id']).json();assert task['status']=='completed',task['error']
        f=finalize(client,task);assert f.status_code==201,f.text
        finals.append(f.json()['id'])
    return get(client,p),finals,blocks,v,base

def card_body(ids):
    return {'title':'由图象上的点建立数量关系','recognition_cues':['已知图象经过点'],'common_structure':'点的坐标满足函数表达式','strategy_steps':[{'action':'代入点坐标','reason':'函数图象定义','conditions':'表达式有意义','analysis_ids':ids}], 'alternative_paths':[],'boundaries':['不能缺少函数表达式或坐标条件'],'common_mistakes':['忽略自变量取值范围'],'examples':[{'analysis_id':i,'reason':'同样使用坐标满足关系'} for i in ids],'transfer_training':[{'kind':'designed','prompt':'若反比例函数图象经过(1,2)，求其表达式。','skill_goal':'代入与检验','hints':['先看横坐标是否为零'],'checkpoints':['k=2且k不为零'],'analysis_ids':ids}],'unresolved':[]}
def cards_model(config,system,payload,tokens):
    if 'research_finals' in payload and 'cards' in payload:return json.dumps({'issues':[{'card_index':0,'message':'教师检查训练条件'}]}),None
    return json.dumps({'cards':[card_body([x['id'] for x in payload['research_finals']])],'summary':'两题的共同线索有待教师核验'}),None


def test_split_preserves_exact_sources_and_missing_coverage_then_research_and_cards(client,monkeypatch):
    p,finals,blocks,v,base=research_finals(client,monkeypatch)
    assert len(p['items'])==2
    assert p['items'][0]['resolved']['statement']=='1. 图象经过(2,3)，求k。 A. 1 B. 6'
    assert p['items'][1]['resolved']['statement']=='2. 图象经过(3,2)，求k。'
    assert p['coverage']['unchecked_blocks']==[blocks[-1]['id']]
    assert any(x['text']=='合成测试试卷' for x in p['coverage']['unassigned'])
    assert all(i['payload']['answer_status']=='unchecked' for i in p['items'])
    assert all(i['runs'][0]['finals'] for i in p['items'])
    monkeypatch.setattr(worker,'generate',cards_model)
    r=post(client,p,'cards',analysis_version_ids=finals);assert r.status_code==201,r.text
    worker.run_one_knowledge();p=get(client,p);assert p['tasks'][0]['status']=='completed',p['tasks'][0]
    c=p['cards'][0];assert not c['read_only'] and not c['blockers'] and c['checks']
    response=client.post(f"/api/papers/{p['id']}/cards/{c['id']}/finalize",json={'revision':c['revision'],'confirmed':True});assert response.status_code==201,response.text
    version=response.json()['id'];url='/api/papers/card-versions/'+version+'/download';original=client.get(url).content
    assert json.loads(original)['body']['transfer_training'][0]['kind']=='designed'
    assert client.put(f"/api/papers/{p['id']}/cards/{c['id']}",json={'revision':c['revision'],'body':c['payload']}).status_code==409
    revised=client.post('/api/papers/card-versions/'+version+'/revise').json();assert revised['parent_version']==version
    updated=client.put(f"/api/papers/{p['id']}/cards/{revised['id']}",json={'revision':revised['revision'],'body':revised['payload']|{'title':'新卡片标题'}});assert updated.status_code==200,updated.text
    init_db();assert client.get(url).content==original
    b=blocks[1]
    client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text']+'来源改变','verified':True})
    assert get(client,p)['stale']
    assert client.get(url).content==original
    assert client.post(f"/api/papers/{p['id']}/cards/{revised['id']}/finalize",json={'revision':updated.json()['revision'],'confirmed':True}).status_code==409
    assert client.get(f"/api/knowledge/runs/{base['id']}").json()['items']==base['items']


def test_bad_anchors_are_editable_not_silently_guessed_and_archive_restore(client,monkeypatch):
    p,blocks,_,_=ready(client,monkeypatch)
    def broken(*args):
        raw,u=split_model(*args);v=json.loads(raw);v['questions'][0]['question_spans'][0]['start_anchor']='不存在的片段';return json.dumps(v),u
    p=split(client,monkeypatch,p,broken);i=p['items'][0]
    assert i['resolved']['errors']
    assert post(client,p,'items/'+i['id']+'/confirm',item_revision=i['revision'],confirmed=True).status_code==422
    body=i['payload'];body['question_spans'][0]['start_anchor']='1.'
    r=save(client,p,i,question_spans=body['question_spans']);assert r.status_code==200,r.text
    p=r.json();assert not p['items'][0]['resolved']['errors']
    assert save(client,p,i).status_code==409
    p=confirm(client,p,p['items'][0]);i=p['items'][0]
    r=post(client,p,'items/'+i['id']+'/archive',item_revision=i['revision'],excluded=True);assert r.status_code==200,r.text
    p=r.json();assert len(p['items'])==1 and len(p['archived'])==1
    a=p['archived'][0]
    p=post(client,p,'items/'+a['id']+'/archive',item_revision=a['revision'],excluded=False).json();assert len(p['items'])==2 and not p['items'][0]['question']['confirmed']
    assert post(client,p,'items').status_code==201


def test_source_recheck_unchanged_does_not_invalidate_but_real_changes_do(client,monkeypatch):
    p,blocks,_,_=ready(client,monkeypatch);b=blocks[1]
    client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text'],'verified':True})
    assert not get(client,p)['stale']
    client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text'],'verified':False})
    assert get(client,p)['stale']
    assert post(client,p,'split').status_code==409


def test_failed_match_checkpoint_retry_and_no_teacher_overwrite(client,monkeypatch):
    p,blocks,_,_=ready(client,monkeypatch);p=split(client,monkeypatch,p)
    def broken(config,system,payload,tokens):
        raw,u=recommend_model(config,system,payload,tokens);v=json.loads(raw);v['matches'][0]['recommendations'][0]['ref']='unknown';return json.dumps(v),u
    monkeypatch.setattr(worker,'generate',broken)
    r=post(client,p,'recommend',item_ids=[x['id'] for x in p['items']]);assert r.status_code==201,r.text
    assert save(client,get(client,p),p['items'][0],title='不允许覆盖').status_code==409
    worker.run_one_knowledge();p=get(client,p);t=p['tasks'][0]
    assert t['status']=='failed' and not p['items'][0]['payload']['recommendations']
    monkeypatch.setattr(worker,'generate',recommend_model)
    r=client.post('/api/papers/tasks/'+t['id']+'/retry',json={'revision':t['revision']});assert r.status_code==200,r.text
    worker.run_one_knowledge();p=get(client,p);assert p['tasks'][0]['status']=='completed'
    # Change original during paid generation: retain raw call, never apply obsolete boundaries.
    p2=client.post('/api/papers',json={'document_id':p['source']['document_id']}).json()
    def during(*args):
        out=split_model(*args);b=blocks[1]
        client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text']+'改变','verified':True});return out
    monkeypatch.setattr(worker,'generate',during);post(client,p2,'split');worker.run_one_knowledge();p2=get(client,p2)
    assert p2['stale'] and not p2['items'] and p2['tasks'][0]['status']=='failed'


def test_boundary_changes_revoke_question_approval_but_mapping_changes_do_not(client,monkeypatch):
    p,_,_,_=ready(client,monkeypatch);p=split(client,monkeypatch,p);p=recommend(client,monkeypatch,p);p=confirm(client,p,p['items'][0]);i=p['items'][0]
    p=save(client,p,i,knowledge_refs=[]).json();assert p['items'][0]['question']['confirmed']
    i=p['items'][0];p=save(client,p,i,title='修改题干归属').json()
    assert not p['items'][0]['question']['confirmed'] and p['items'][0]['question_version_id'] is None
    r=post(client,p,'analyses',item_ids=[p['items'][0]['id']]);assert r.status_code==201 and r.json()['results'][0]['error']


def test_cards_reject_duplicate_question_versions_and_invalid_citations(client,monkeypatch):
    p,finals,_,_,_=research_finals(client,monkeypatch)
    revised=client.post('/api/research-editor/versions/'+finals[0]+'/revise').json()
    assert any(r['id']==revised['id'] for i in get(client,p)['items'] for r in i['runs'])
    new=finalize(client,revised).json()['id'];p=get(client,p)
    assert post(client,p,'cards',analysis_version_ids=[finals[0],new]).status_code==422
    def bad(*args):
        raw,u=cards_model(*args);v=json.loads(raw)
        if 'cards' in v:v['cards'][0]['strategy_steps'][0]['analysis_ids']=['fake']
        return json.dumps(v),u
    monkeypatch.setattr(worker,'generate',bad);r=post(client,p,'cards',analysis_version_ids=finals);assert r.status_code==201,r.text
    worker.run_one_knowledge();p=get(client,p);assert p['tasks'][0]['status']=='failed' and not p['cards']


def test_figures_are_explicitly_assigned_and_necessary_conditions_required(client,monkeypatch):
    from PIL import Image
    from mathlet.db import data_dir
    from mathlet.source_review import snapshot_review
    p,blocks,v,_=ready(client,monkeypatch)
    doc=p['source']['document_id'];path=data_dir()/'documents'/doc/'assets';path.mkdir(exist_ok=True)
    Image.new('RGB',(8,8),'white').save(path/'shared.png')
    with connect() as c:
        c.execute('UPDATE blocks SET assets=? WHERE id=?',(json.dumps(['shared.png']),blocks[1]['id']));snapshot_review(c,doc)
    p=client.post('/api/papers',json={'document_id':doc}).json()
    def figures(*args):
        raw,u=split_model(*args);value=json.loads(raw);value['questions'][0]['asset_ids']=[blocks[1]['id']+'/shared.png'];return json.dumps(value),u
    p=split(client,monkeypatch,p,figures);i=p['items'][0];assert i['payload']['figure_status']=='pending'
    r=post(client,p,'items/'+i['id']+'/confirm',item_revision=i['revision'],confirmed=True);assert r.status_code==422
    p=save(client,p,i,figure_status='described',diagram_description='图中点的坐标已完整包含在题干中。').json();p=confirm(client,p,p['items'][0]);p=confirm(client,p,p['items'][1])
    q1=p['items'][0]['question']['payload'];q2=p['items'][1]['question']['payload']
    assert len(q1['assets'])==1 and not q2['assets']
    assert q1['source_ranges'][0]['start']==0 and q1['source_ranges'][0]['end']==len(p['items'][0]['resolved']['statement'])
    frozen=client.get('/api/research/questions').json();assert len(frozen)==2


def test_empty_cross_question_summary_is_not_a_fabricated_card(client,monkeypatch):
    p,finals,_,_,_=research_finals(client,monkeypatch)
    def no_common(config,system,payload,tokens):
        if 'cards' in payload:return json.dumps({'issues':[]}),None
        return json.dumps({'cards':[],'summary':'目前没有足够共同结构，建议另选题目。'}),None
    monkeypatch.setattr(worker,'generate',no_common);r=post(client,p,'cards',analysis_version_ids=finals);assert r.status_code==201,r.text
    worker.run_one_knowledge();p=get(client,p)
    assert p['tasks'][0]['status']=='completed' and not p['cards'] and '目前没有足够共同结构' in p['notes'][-1]


def test_partial_batch_reports_errors_and_does_not_invent_question_approval(client,monkeypatch):
    p,_,_,_=ready(client,monkeypatch);p=split(client,monkeypatch,p);p=recommend(client,monkeypatch,p);p=confirm(client,p,p['items'][0])
    response=post(client,p,'analyses',item_ids=[x['id'] for x in p['items']]);assert response.status_code==201,response.text
    results=response.json()['results'];assert 'run_id' in results[0] and 'error' in results[1]
    assert not get(client,p)['items'][1]['question']


def test_recommendation_retry_reuses_successful_group_checkpoint(client,monkeypatch):
    p,_,_,_=ready(client,monkeypatch);p=split(client,monkeypatch,p)
    for _ in range(4):p=post(client,p,'items').json()
    calls=[];fail=True
    def groups(config,system,payload,tokens):
        nonlocal fail
        ids=tuple(q['id'] for q in payload['questions']);calls.append(ids)
        if len(ids)==1 and fail:
            fail=False;raise ValueError('模拟第二组中断')
        raw,usage=recommend_model(config,system,payload,tokens);v=json.loads(raw)
        for m in v['matches']:
            text=next(q['statement'] for q in payload['questions'] if q['id']==m['item_id'])
            m['recommendations'][0]['evidence']=text[:8]
        return json.dumps(v),usage
    monkeypatch.setattr(worker,'generate',groups)
    post(client,p,'recommend',item_ids=[i['id'] for i in p['items']]);worker.run_one_knowledge();p=get(client,p);t=p['tasks'][0]
    assert t['status']=='failed' and all(not i['payload']['recommendations'] for i in p['items'])
    response=client.post('/api/papers/tasks/'+t['id']+'/retry',json={'revision':t['revision']});assert response.status_code==200,response.text
    worker.run_one_knowledge();p=get(client,p)
    assert p['tasks'][0]['status']=='completed' and len(calls)==3,p['tasks'][0]
    assert len(calls[0])==5 and calls[1]==calls[2] and len(calls[1])==1
    assert all(i['payload']['recommendations'] for i in p['items'])
