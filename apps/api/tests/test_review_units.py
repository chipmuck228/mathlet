"""Synthetic source-bound workflow: no real user papers or paid model calls."""
import json
from test_knowledge import client
from test_teaching import ready,case_for
from mathlet import knowledge_worker as worker
from mathlet.db import connect,init_db

def prepare(client,monkeypatch):
    v,qs,blocks,_=ready(client,monkeypatch)
    def research_model(config,system,payload,tokens):
        if 'candidates' in payload:return json.dumps({'issues':[]}),None
        q=next(q for q in qs if q['payload']['statement']==payload['question']['statement'])
        return json.dumps(case_for(payload|{'question_version_id':q['version_id']})['analysis']),None
    monkeypatch.setattr(worker,'generate',research_model)
    finals=[]
    for i,q in enumerate(qs):
        r=client.post('/api/research-editor/runs',json={'version_ids':[v['id']],'question_version_id':q['version_id'],'request_key':'unit-test-research-'+str(i)});assert r.status_code==201,r.text
        worker.run_one_knowledge();r=client.get('/api/research-editor/runs/'+r.json()['id']).json();assert r['status']=='completed',r['error']
        o=r['outputs'][0];f=client.post('/api/research-editor/runs/'+r['id']+'/outputs/'+o['id']+'/finalize',json={'revision':o['revision'],'run_revision':r['revision'],'confirmed':True});assert f.status_code==201,f.text;finals.append(f.json()['id'])
    return v,finals,blocks

def ev(s):return {'analysis_id':s['id'],'approach_id':s['analysis']['approaches'][0]['id'],'step_index':0,'quote':s['analysis']['approaches'][0]['steps'][0]['action']}
def model(config,system,payload,tokens):
    encoded=json.dumps(payload)
    assert 'UNREVIEWED-ANSWER-DO-NOT-SEND' not in encoded and 'data:image' not in encoded
    if '逐一判断' in system:
        ref=payload['knowledge']['items'][5]['ref']
        return json.dumps({'mappings':[{'analysis_id':s['id'],'relevance':'core','reason':'加减消元用于求解','links':[ev(s)|{'knowledge_ref':ref,'role':'core','explanation':'两式相加消去y','conditions':'两个方程的y系数互为相反数'}],'gaps':['教师可判断是否补充实际应用。']} for s in payload['reviewed_studies']]}),None
    if '比较不同代表题' in system:
        return json.dumps({'cards':[{'title':'观察系数，选择消元','cues':['系数互为相反数'],'structure':'同时满足两个方程','steps':['比较系数','相加消元','代回检验'],'conditions':['同一组未知数同时满足两式'],'alternatives':['代入消元'],'mistakes':['漏加常数项'],'knowledge_refs':[payload['knowledge']['items'][5]['ref']],'evidence':[ev(s) for s in payload['reviewed_studies']],'doubts':['提示梯度请教师判断']}],'summary':'两题支持同一种思路，不代表所有方程组都应直接相加。'}),None
    if '把知识终稿' in system:
        return json.dumps({'title':'二元一次方程组 · 合成试读单元','introduction':'先理解，再建立思路。','goals':['能解释何时选择加减消元。'],'training':[{'phase':phase,'kind':'original','title':title,'source_analysis_ids':[payload['reviewed_studies'][0]['id']],'knowledge_refs':[payload['knowledge']['items'][5]['ref']],'prompt':prompt,'hints':['观察同一未知数的系数。'],'answer':'x=3，y=2','reasoning':'两式相加求x，代回求y。','checkpoints':['代回两个方程均成立。']} for phase,title,prompt in [('basic','唤起等式性质','为什么可以把两个等式相加？'),('thinking','比较方法','代入法与加减法哪个更方便？'),('solve','独立求解','不看提示完成这道题。')]]}),None
    if '复核新归纳' in system:return json.dumps({'issues':[{'section':'training','message':'第一层提示是否过早给出方法？','guidance':'可编辑提示，或由教师判断现有提示合适。'}]}),None
    return json.dumps({'reply':'可以先让学生比较系数，再决定消元方法。'}),None

def start(client,v,key='unit-generation-request'):
    r=client.post('/api/review-units/runs',json={'knowledge_version_id':v['id'],'request_key':key});assert r.status_code==201,r.text;return r.json()
def get(client,r):return client.get('/api/review-units/runs/'+r['id']).json()
def finish(client,r,**extra):return client.post('/api/review-units/runs/'+r['id']+'/finalize',json={'revision':r['revision'],'run_revision':r['run_revision'],'confirmed':True,**extra})
def save(client,r,b):return client.put('/api/review-units/runs/'+r['id'],json={'revision':r['revision'],'run_revision':r['run_revision'],'body':b})
def complete(client,monkeypatch):
    v,finals,blocks=prepare(client,monkeypatch);r=start(client,v);monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r);assert r['status']=='completed',r['error'];return r,v,finals,blocks

def test_automatic_whole_bank_to_knowledge_maps_cards_training_and_one_teacher_final(client,monkeypatch):
    r,v,finals,blocks=complete(client,monkeypatch)
    assert len(r['body']['mappings'])==2 and len(r['knowledge']['items'])==10
    assert len(r['body']['cards'])==1 and len(r['body']['training'])==3
    assert r['body']['cards'][0]['doubts'] and r['advice']
    assert len(r['calls'])==4 and all(x['status']=='succeeded' for x in r['calls'])
    preview=client.get('/api/review-units/runs/'+r['id']+'/preview');assert preview.status_code==200,preview.text
    assert '未审定草案' in preview.text and '分层训练' in preview.text
    f=finish(client,r,note='教师认可现有提示；保留AI意见作为参考。');assert f.status_code==201,f.text
    fid=f.json()['id'];url='/api/review-units/versions/'+fid+'/download';original=client.get(url).content
    snapshot=client.get('/api/review-units/versions/'+fid+'/json').json()
    assert snapshot['teacher_review']['confirmed'] and '教师认可' in snapshot['teacher_review']['note'] and snapshot['checks']
    assert len(snapshot['sources'])==2 and snapshot['body']['mappings'][0]['gaps']
    assert '教师审定复习单元' in original.decode() and 'UNREVIEWED-ANSWER' not in original.decode()
    assert save(client,get(client,r),r['body']).status_code==409
    fork=client.post('/api/review-units/versions/'+fid+'/revise');assert fork.status_code==201,fork.text
    fork=fork.json();assert not fork['read_only'] and fork['parent_version']==fid
    new=fork['body'];new['title']='教师修订版';new['introduction']='<script>alert(1)</script>'
    revised=save(client,fork,new);assert revised.status_code==200,revised.text
    assert save(client,fork,new).status_code==409
    f2=finish(client,revised.json());assert f2.status_code==201,f2.text
    html=client.get('/api/review-units/versions/'+f2.json()['id']+'/download').text
    assert '<script>' not in html and '&lt;script&gt;' in html
    init_db();assert client.get(url).content==original
    b=blocks[0];client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text']+'改变条件','verified':True})
    assert get(client,revised.json())['stale'] and finish(client,revised.json()).status_code==409
    assert client.get(url).content==original

def test_quotes_steps_refs_and_training_coverage_are_technical_constraints_not_ai_veto(client,monkeypatch):
    r,_,_,_=complete(client,monkeypatch)
    for key,value in [('quote','虚构的步骤'),('knowledge_ref','foreign'),('step_index',99),('analysis_id','foreign')]:
        b=json.loads(json.dumps(r['body']));b['mappings'][0]['links'][0][key]=value
        result=save(client,r,b);assert result.status_code==422,result.text
    b=json.loads(json.dumps(r['body']));b['cards'][0]['evidence']=[b['cards'][0]['evidence'][0]]*2
    assert save(client,r,b).status_code==422
    b=json.loads(json.dumps(r['body']));b['training'][0]['source_analysis_ids']=['foreign'];assert save(client,r,b).status_code==422
    b=json.loads(json.dumps(r['body']));b['training']=b['training'][:1];assert save(client,r,b).status_code==422
    assert finish(client,r).status_code==201

def test_idempotent_generation_checkpoint_retry_and_no_overwrite_from_discussion(client,monkeypatch):
    v,_,_=prepare(client,monkeypatch);r=start(client,v);assert start(client,v)['id']==r['id'];calls=[];fail=True
    def interrupted(*args):
        nonlocal fail
        calls.append(args[1])
        if '把知识终稿' in args[1] and fail:fail=False;raise ValueError('模拟训练步骤中断')
        return model(*args)
    monkeypatch.setattr(worker,'generate',interrupted);worker.run_one_knowledge();r=get(client,r);assert r['status']=='failed' and r['body'] is None
    retry=client.post('/api/review-units/runs/'+r['id']+'/retry',json={'revision':r['revision'],'run_revision':r['run_revision']});assert retry.status_code==200,retry.text
    worker.run_one_knowledge();r=get(client,r);assert r['status']=='completed',r['error']
    assert sum('逐一判断' in s for s in calls)==1 and sum('比较不同代表题' in s for s in calls)==1
    chat_body=json.loads(json.dumps(r['body']));chat_body['introduction']='未保存的教师修改'
    data={'revision':r['revision'],'run_revision':r['run_revision'],'body':chat_body,'section':'introduction','instruction':'怎样改善导读？','request_key':'unit-discussion-idempotent'}
    d=client.post('/api/review-units/runs/'+r['id']+'/discussions',json=data);assert d.status_code==201,d.text
    assert client.post('/api/review-units/runs/'+r['id']+'/discussions',json=data).json()['id']==d.json()['id']
    worker.run_one_knowledge();chats=client.get('/api/review-units/runs/'+r['id']+'/discussions').json()
    assert chats[0]['status']=='completed' and chats[0]['reply'] and chats[0]['revision']==r['revision']
    assert get(client,r)['body']==r['body'] and get(client,r)['revision']==r['revision']
    with connect() as c:
        payload=json.loads(c.execute('SELECT payload FROM review_unit_discussions').fetchone()[0]);assert payload['uses_unsaved_body'] and payload['current_section']=='未保存的教师修改'

def test_source_mutation_during_generation_stops_pipeline(client,monkeypatch):
    v,_,blocks=prepare(client,monkeypatch);r=start(client,v)
    def mutate(*args):
        value=model(*args);b=blocks[0];client.put('/api/blocks/'+b['id'],json={'revision':2,'text':b['text']+'变更','verified':True});return value
    monkeypatch.setattr(worker,'generate',mutate);worker.run_one_knowledge();r=get(client,r)
    assert r['stale'] and r['status']=='failed' and r['body'] is None and len(r['calls'])==1


def test_no_match_is_explicit_does_not_force_cards_or_training(client,monkeypatch):
    v,_,_=prepare(client,monkeypatch);r=start(client,v)
    def no_match(config,system,payload,tokens):
        if '逐一判断' in system:return json.dumps({'mappings':[{'analysis_id':s['id'],'relevance':'none','reason':'没有足够关联','links':[],'gaps':[]} for s in payload['reviewed_studies']]}),None
        return model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',no_match);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert not r['body']['selected_analysis_ids'] and not r['body']['training'] and not r['body']['cards']
    assert any('尚未形成' in a['message'] for a in r['advice'])
    assert finish(client,r).status_code==201


def test_generation_repairs_retyped_quotes_and_keeps_teacher_visible_diagnostics(client,monkeypatch):
    v,_,_=prepare(client,monkeypatch);r=start(client,v)
    def paraphrased(config,system,payload,tokens):
        raw,usage=model(config,system,payload,tokens);value=json.loads(raw)
        if '逐一判断' in system:
            for m in value['mappings']:m['links'][0]['quote']='把两个方程相加消去未知数（AI概括）'
        if '比较不同代表题' in system:
            for e in value['cards'][0]['evidence']:e['quote']='相加消元的概述'
        return json.dumps(value),usage
    monkeypatch.setattr(worker,'generate',paraphrased);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert len(r['body']['selected_analysis_ids'])==2 and r['body']['cards']
    for m in r['body']['mappings']:
        s=next(s for s in r['studies'] if s['id']==m['analysis_id'])
        assert m['links'][0]['quote']==s['analysis']['approaches'][0]['steps'][0]['action']
        assert any('AI概括' in text and '不代表知识关联已验证' in text for text in m['gaps'])
    assert any('引文定位核对' in a['message'] for a in r['advice'])
    assert finish(client,r).status_code==201


def test_unlocatable_one_question_does_not_stop_other_questions(client,monkeypatch):
    v,_,_=prepare(client,monkeypatch);r=start(client,v)
    def unlocatable(config,system,payload,tokens):
        raw,usage=model(config,system,payload,tokens);value=json.loads(raw)
        if '逐一判断' in system:value['mappings'][0]['links'][0].update(approach_id='nonexistent',step_index=99,quote='没有这样的原文')
        return json.dumps(value),usage
    monkeypatch.setattr(worker,'generate',unlocatable);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    first=r['body']['mappings'][0];assert first['relevance']=='uncertain' and not first['links']
    assert len(r['body']['selected_analysis_ids'])==1 and r['body']['training']
    assert any('证据待定位' in text for text in first['gaps'])


def test_retry_revalidates_saved_quote_failure_without_repaying_mapping_call(client,monkeypatch):
    from mathlet.review_units import validate_mappings
    v,_,_=prepare(client,monkeypatch);r=start(client,v)
    def paraphrased(config,system,payload,tokens):
        raw,usage=model(config,system,payload,tokens);value=json.loads(raw)
        if '逐一判断' in system:
            for m in value['mappings']:m['links'][0]['quote']='曾经导致旧校验失败的概括'
        return json.dumps(value),usage
    import mathlet.review_unit_worker as unit_worker
    actual=unit_worker.bind_mappings
    monkeypatch.setattr(worker,'generate',paraphrased)
    # Reproduce a historical failure using the original strict generation validator.
    monkeypatch.setattr(unit_worker,'bind_mappings',lambda value,know,studies:validate_mappings(value,know,studies))
    worker.run_one_knowledge();r=get(client,r);assert r['status']=='failed' and '逐字引用' in r['error']
    monkeypatch.setattr(unit_worker,'bind_mappings',actual)
    def remaining(config,system,payload,tokens):
        assert '逐一判断' not in system,'Mapping must be recovered from the existing response'
        return model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',remaining)
    retry=client.post('/api/review-units/runs/'+r['id']+'/retry',json={'revision':r['revision'],'run_revision':r['run_revision']});assert retry.status_code==200,retry.text
    worker.run_one_knowledge();r=get(client,r);assert r['status']=='completed',r['error']
    assert r['calls'][0]['status']=='revalidated' and len([x for x in r['calls'] if x['step']=='unit:mapping:1'])==1


def test_unique_quote_relocates_wrong_step_but_does_not_guess_ambiguous_locations():
    from mathlet.review_unit_evidence import bind
    source={'id':'a','question':{'title':'定位测试'},'analysis':{'approaches':[{'id':'path','steps':[{'action':'唯一原文','reason':'依据'}]}]}}
    e={'analysis_id':'a','approach_id':'wrong','step_index':9,'quote':'唯一原文'}
    fixed,note=bind(e,{'a':source});assert fixed['approach_id']=='path' and fixed['step_index']==0 and '唯一逐字引文' in note
    source['analysis']['approaches'][0]['steps'].append({'action':'唯一原文','reason':'依据'})
    fixed,note=bind(e,{'a':source});assert fixed is None and '无法唯一定位' in note
