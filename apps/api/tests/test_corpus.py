"""Synthetic model fixtures test lifecycle and evidence isolation, not mathematical proof."""
import json
from test_exam_extraction import client,complete,final
from test_research import context
from mathlet import knowledge_worker as worker
from mathlet.db import connect

def solution(question):
    return {'given_conditions':[question['statement']],'goals':['求解并检验'],'thinking_operations':['识别条件，建立关系，计算后检验'],
      'problem_types':['条件转译与计算'],'classification_reason':'依据已知关系求目标',
      'assessed_points':[{'name':'根据已知条件建立数量关系','knowledge_refs':[],'evidence':question['statement']}],
      'knowledge_breakdown':[],'identified_knowledge':[{'name':'等式与数量关系','role':'primary','reason':'从已知到所求','conditions':'保持等式关系'}],
      'approaches':[{'id':'p1','title':'代入与消元','trigger':'已知关系','steps':[{'action':'由已知关系代入求解','reason':'等式性质','knowledge_refs':[]}],'conclusion':'按原题计算所得结果','checks':'代回题目已知关系检验','limitations':'需要完整条件'}],
      'recognition_cues':['明确已知与目标'],'common_mistakes':['漏检验'],'variation_prompts':['改变一个已知量'],'scope_notes':[],'missing_information':[]}

def independent_model(config,system,payload,tokens):
    if 'first' in payload:return json.dumps({'verdict':'consistent','summary':'两次结果一致，仍需教师核验','issues':[]}),None
    assert set(payload)=={'question','teacher_instruction'}
    assert 'knowledge' not in payload and 'reference_answer' not in payload['question']
    assert 'assets' not in payload['question'] and 'sources' not in payload['question']
    return json.dumps(solution(payload['question'])),None

def exam(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,False)
    fixed=final(client,r);assert fixed.status_code==201,fixed.text
    return fixed.json(),doc,blocks

def start_study(client,monkeypatch,index=0):
    fixed,doc,blocks=exam(client,monkeypatch)
    catalog=client.get('/api/corpus/catalog').json();q=catalog['questions'][index]
    response=client.post('/api/corpus/studies',json={'question_ids':[q['id']]});assert response.status_code==201,response.text
    run_id=response.json()['results'][0]['run_id'];monkeypatch.setattr(worker,'generate',independent_model)
    assert worker.run_one_knowledge()
    run=client.get('/api/research-editor/runs/'+run_id).json();assert run['status']=='completed',run['error']
    return run,q,doc,blocks

def finalize_study(client,run):
    out=run['outputs'][0];response=client.post(f"/api/research-editor/runs/{run['id']}/outputs/{out['id']}/finalize",json={'revision':out['revision'],'run_revision':run['revision'],'confirmed':True})
    assert response.status_code==201,response.text
    return response.json()

def test_independent_study_does_not_require_knowledge_and_is_idempotent(client,monkeypatch):
    run,q,doc,blocks=start_study(client,monkeypatch)
    assert run['knowledge']['items']==[] and len(run['calls'])==3
    assert run['independent_verification']['comparison']['verdict']=='consistent'
    assert run['outputs'][0]['final_version'] is None
    again=client.post('/api/corpus/studies',json={'question_ids':[q['id']]}).json()
    assert again['results'][0]['run_id']==run['id']
    assert not worker.run_one_knowledge()
    with connect() as c:
        payloads=[json.loads(r['request_json'])['payload'] for r in c.execute('SELECT request_json FROM knowledge_calls WHERE run_id=? ORDER BY rowid',(run['id'],))]
    assert payloads[0]==payloads[1] and 'first' not in payloads[1]
    final_doc=finalize_study(client,run)
    assert final_doc['snapshot']['independent_verification']['comparison']['verdict']=='consistent'
    catalog=client.get('/api/corpus/catalog').json()
    assert catalog['questions'][0]['runs'][0]['finals'][0]['id']==final_doc['id']
    revise=client.post('/api/research-editor/versions/'+final_doc['id']+'/revise').json()
    assert revise['independent_verification'] and revise['parent_version']==final_doc['id']
    assert client.get('/api/research-editor/versions/'+final_doc['id']).json()['snapshot']==final_doc['snapshot']

def test_knowledge_matching_reuses_final_analysis_and_versions_independently(client,monkeypatch):
    run,q,doc,blocks=start_study(client,monkeypatch);f=finalize_study(client,run)
    original=client.get('/api/research/versions/analysis/'+f['id']+'/download').content
    _,base,kv=context(client,monkeypatch);ref=kv['id']+':'+kv['snapshot']['items'][0]['knowledge_id']
    def match_model(config,system,payload,tokens):
        assert 'reviewed_analysis' in payload and 'knowledge_catalog' in payload
        return json.dumps({'links':[{'ref':ref,'role':'support','reason':'支撑等式转译','evidence':'明确已知与目标'}],'gaps':['还需核对其他相关知识'],'summary':'按实际作用匹配'}),None
    monkeypatch.setattr(worker,'generate',match_model)
    response=client.post('/api/corpus/mappings',json={'analysis_version_ids':[f['id']],'version_ids':[kv['id']]});assert response.status_code==201,response.text
    key=response.json()['results'][0]['id'];worker.run_one_knowledge()
    m=client.get('/api/corpus/mappings').json()[0];assert m['status']=='completed',m['error']
    assert m['payload']['links'][0]['role']=='support'
    assert not worker.run_one_knowledge()
    again=client.post('/api/corpus/mappings',json={'analysis_version_ids':[f['id']],'version_ids':[kv['id']]}).json();assert again['results'][0]['id']==key
    body=m['payload'];body['links'][0]['role']='primary'
    saved=client.put('/api/corpus/mappings/'+key,json={'revision':m['revision'],'body':body});assert saved.status_code==200,saved.text
    m=saved.json();fixed=client.post('/api/corpus/mappings/'+key+'/finalize',json={'revision':m['revision'],'confirmed':True});assert fixed.status_code==201,fixed.text
    v=fixed.json()['finals'][0];download='/api/corpus/mapping-versions/'+v['id']+'/download';old=client.get(download).content
    assert client.put('/api/corpus/mappings/'+key,json={'revision':m['revision'],'body':body}).status_code==409
    new=client.post('/api/corpus/mappings/'+key+'/revise',json={'revision':m['revision'],'confirmed':True}).json()
    assert not new['read_only'] and client.get(download).content==old
    with connect() as c:c.execute('UPDATE knowledge_runs SET revision=revision+1 WHERE id=?',(base['id'],))
    assert client.get('/api/corpus/mappings').json()[0]['stale']
    assert not client.get('/api/research-editor/runs/'+run['id']).json()['stale']
    assert client.get('/api/research/versions/analysis/'+f['id']+'/download').content==original

def test_source_change_during_research_does_not_write_stale_output(client,monkeypatch):
    fixed,doc,blocks=exam(client,monkeypatch);q=client.get('/api/corpus/catalog').json()['questions'][0]
    r=client.post('/api/corpus/studies',json={'question_ids':[q['id']]}).json()['results'][0]
    def changing(*args):
        raw=independent_model(*args)
        with connect() as c:c.execute('UPDATE blocks SET text=? WHERE id=?',('changed',blocks[1]['id']))
        return raw
    monkeypatch.setattr(worker,'generate',changing);worker.run_one_knowledge()
    run=client.get('/api/research-editor/runs/'+r['run_id']).json()
    assert run['status']=='failed' and not run['outputs'] and run['stale']

def test_pending_figures_are_listed_but_not_sent_to_text_model(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,True);assert final(client,r).status_code==201
    catalog=client.get('/api/corpus/catalog').json();pending=catalog['questions'][1]
    assert pending['blockers']
    response=client.post('/api/corpus/studies',json={'question_ids':[pending['id']]}).json()
    assert 'error' in response['results'][0]


def test_disagreement_is_visible_without_claiming_approval(client,monkeypatch):
    fixed,doc,blocks=exam(client,monkeypatch);q=client.get('/api/corpus/catalog').json()['questions'][0]
    r=client.post('/api/corpus/studies',json={'question_ids':[q['id']]}).json()['results'][0]
    def model(config,system,payload,tokens):
        if 'first' in payload:return json.dumps({'verdict':'disagrees','summary':'两份结论不同，请教师核对','issues':[]}),None
        return independent_model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge()
    run=client.get('/api/research-editor/runs/'+r['run_id']).json()
    assert run['status']=='completed' and run['outputs'][0]['checks'][0]['category']=='correctness'
    assert run['outputs'][0]['final_version'] is None


def test_cross_exam_cards_and_immutable_card_final(client,monkeypatch):
    from test_paper_research import card_body
    exam(client,monkeypatch);exam(client,monkeypatch)
    catalog=client.get('/api/corpus/catalog').json();exams=catalog['exams']
    selected=[next(q for q in catalog['questions'] if q['exam_id']==exams[0]['id'] and q['number']=='1'),next(q for q in catalog['questions'] if q['exam_id']==exams[1]['id'] and q['number']=='2')]
    assert all(q['duplicate_count']==2 for q in selected)
    r=client.post('/api/corpus/studies',json={'question_ids':[q['id'] for q in selected]}).json()
    monkeypatch.setattr(worker,'generate',independent_model)
    finals=[]
    for result in r['results']:
        worker.run_one_knowledge();run=client.get('/api/research-editor/runs/'+result['run_id']).json();assert run['status']=='completed',run['error']
        finals.append(finalize_study(client,run)['id'])
    def model(config,system,payload,tokens):
        if 'cards' in payload:return json.dumps({'issues':[]}),None
        assert {f['id'] for f in payload['reviewed_research']}==set(finals)
        return json.dumps({'cards':[card_body(finals)],'summary':'仅根据当前两道研究归纳'}),None
    monkeypatch.setattr(worker,'generate',model)
    response=client.post('/api/corpus/cards',json={'analysis_version_ids':finals});assert response.status_code==201,response.text
    worker.run_one_knowledge();task=client.get('/api/corpus/tasks').json()[0]
    assert task['status']=='completed',task['error']
    card=task['cards'][0];assert len(card['sources'])==2
    url=f"/api/papers/{card['project_id']}/cards/{card['id']}/finalize"
    f=client.post(url,json={'revision':card['revision'],'confirmed':True});assert f.status_code==201,f.text
    download='/api/papers/card-versions/'+f.json()['id']+'/download';old=client.get(download).content
    assert json.loads(old)['body']['transfer_training'][0]['kind']=='designed'
    revised=client.post('/api/papers/card-versions/'+f.json()['id']+'/revise');assert revised.status_code==201,revised.text
    assert client.get(download).content==old


def test_blind_solve_failure_retries_only_unfinished_steps(client,monkeypatch):
    fixed,doc,blocks=exam(client,monkeypatch);q=client.get('/api/corpus/catalog').json()['questions'][0]
    r=client.post('/api/corpus/studies',json={'question_ids':[q['id']]}).json()['results'][0];calls=[]
    def failing(config,system,payload,tokens):
        calls.append(1)
        if len(calls)==2:raise ValueError('测试网络中断')
        return independent_model(config,system,payload,tokens)
    monkeypatch.setattr(worker,'generate',failing);worker.run_one_knowledge()
    run=client.get('/api/research-editor/runs/'+r['run_id']).json();assert run['status']=='failed'
    assert client.post('/api/research/runs/'+run['id']+'/retry',json={'revision':run['revision']}).status_code==200
    worker.run_one_knowledge();run=client.get('/api/research-editor/runs/'+run['id']).json();assert run['status']=='completed',run['error']
    assert len(calls)==4
    assert [c['status'] for c in run['calls']]==['succeeded','failed','succeeded','succeeded']


def test_mapping_rejects_unknown_knowledge_and_stale_final_during_call(client,monkeypatch):
    run,q,doc,blocks=start_study(client,monkeypatch);f=finalize_study(client,run)
    _,base,kv=context(client,monkeypatch)
    response=client.post('/api/corpus/mappings',json={'analysis_version_ids':[f['id']],'version_ids':[kv['id']]});key=response.json()['results'][0]['id']
    monkeypatch.setattr(worker,'generate',lambda *_:(json.dumps({'links':[{'ref':'fake','role':'primary','reason':'test','evidence':'明确已知与目标'}],'gaps':[],'summary':'test'}),None))
    worker.run_one_knowledge();m=client.get('/api/corpus/mappings').json()[0]
    assert m['status']=='failed' and not m['payload']
    assert client.post('/api/corpus/tasks/'+key+'/retry',json={'revision':m['run_revision'],'confirmed':True}).status_code==200
    def changing(*_):
        with connect() as c:c.execute('UPDATE knowledge_runs SET revision=revision+1 WHERE id=?',(base['id'],))
        return json.dumps({'links':[],'gaps':['没有适用条目'],'summary':'有知识缺口'}),None
    monkeypatch.setattr(worker,'generate',changing);worker.run_one_knowledge();m=client.get('/api/corpus/mappings').json()[0]
    assert m['status']=='failed' and m['stale'] and not m['payload']


def test_default_mapping_uses_available_finals_and_batches_large_catalog(client,monkeypatch):
    run,q,doc,blocks=start_study(client,monkeypatch);f=finalize_study(client,run)
    _,base,kv=context(client,monkeypatch)
    from mathlet import corpus_worker
    # Two small deterministic catalog chunks simulate a large library without huge fixtures.
    monkeypatch.setattr(corpus_worker,'knowledge_batches',lambda items:[[x] for x in items])
    def match_model(config,system,payload,tokens):
        if 'batch_candidates' in payload:return json.dumps({'links':[],'gaps':['缺口需教师判断'],'summary':'汇总全部匹配批次'}),None
        assert len(payload['knowledge_catalog'])==1
        return json.dumps({'links':[],'gaps':['缺口需教师判断'],'summary':'本批无匹配'}),None
    monkeypatch.setattr(worker,'generate',match_model)
    r=client.post('/api/corpus/mappings',json={'analysis_version_ids':[f['id']]});assert r.status_code==201,r.text
    worker.run_one_knowledge();m=client.get('/api/corpus/mappings').json()[0]
    assert m['status']=='completed',m['error']
    assert m['payload']['summary']=='汇总全部匹配批次'
    assert len(m['calls'])==len(kv['snapshot']['items'])+1


def test_human_confirmed_figure_conditions_can_join_without_redoing_exam(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,True);fixed=final(client,r).json()
    q=client.get('/api/research/questions').json()[1]
    # Locate the figure question explicitly; ordering is creation-time descending.
    q=next(x for x in client.get('/api/research/questions').json() if x['payload']['figure_status']=='pending')
    from mathlet.research_models import QuestionBody
    body=QuestionBody.model_validate({k:v for k,v in q['payload'].items() if k in QuestionBody.model_fields}).model_dump()
    body.update(figure_status='described',diagram_description='图形条件已逐字核对，不额外假设')
    changed=client.put('/api/research/questions/'+q['id'],json=body|{'revision':q['revision']});assert changed.status_code==200,changed.text
    changed=changed.json();confirmed=client.post('/api/research/questions/'+q['id']+'/confirm',json={'revision':changed['revision'],'reviewer':'测试教师','note':'核对完整图形条件','confirmed':True});assert confirmed.status_code==200,confirmed.text
    catalog=client.get('/api/corpus/catalog').json();target=next(x for x in catalog['questions'] if x['number']=='2')
    assert not target['blockers'],target['blockers']
    assert target['question_version_id']==confirmed.json()['version_id']


def test_duplicate_exam_questions_cannot_be_counted_as_two_card_sources(client,monkeypatch):
    exam(client,monkeypatch);exam(client,monkeypatch)
    questions=[q for q in client.get('/api/corpus/catalog').json()['questions'] if q['number']=='1']
    result=client.post('/api/corpus/studies',json={'question_ids':[q['id'] for q in questions]}).json()
    monkeypatch.setattr(worker,'generate',independent_model);finals=[]
    for entry in result['results']:
        worker.run_one_knowledge();run=client.get('/api/research-editor/runs/'+entry['run_id']).json();finals.append(finalize_study(client,run)['id'])
    response=client.post('/api/corpus/cards',json={'analysis_version_ids':finals})
    assert response.status_code==422 and '重复' in response.text


def test_migration_is_idempotent_and_does_not_change_question_finals(client,monkeypatch):
    from mathlet.db import init_db
    fixed,doc,blocks=exam(client,monkeypatch);v=fixed['versions'][0]['id']
    url='/api/exam-extraction-versions/'+v+'/download';old=client.get(url).content
    init_db();init_db()
    assert client.get(url).content==old
    with connect() as c:assert c.execute('SELECT count(*) FROM schema_migrations WHERE version=13').fetchone()[0]==1
