import json
from test_corpus import client,exam,start_study,finalize_study
from mathlet.db import connect,init_db


def test_exact_condition_target_and_original_questions_are_registered(client,monkeypatch):
    fixed,doc,blocks=exam(client,monkeypatch)
    catalog=client.get('/api/corpus/catalog').json()
    assert len({q['question_id'] for q in catalog['questions']})==2
    for q in catalog['questions']:
        detail=client.get('/api/research/questions/'+q['question_id']);assert detail.status_code==200,detail.text
        assert detail.json()['payload']['statement']==q['statement']
    bank=client.get('/api/corpus/bank').json();assert len(bank)==2
    assert all(q['status']=='question_confirmed' and not q['reusable'] for q in bank)
    assert client.get('/api/research/questions/does-not-exist').status_code==404


def test_reviewed_research_enters_structured_bank_and_exports_without_unchecked_answers(client,monkeypatch):
    run,q,doc,blocks=start_study(client,monkeypatch)
    before=client.get('/api/corpus/bank').json();assert all(not x['reusable'] for x in before)
    final=finalize_study(client,run)
    bank=client.get('/api/corpus/bank').json();record=next(x for x in bank if x['id']==q['question_id'])
    assert record['status']=='research_reviewed' and record['current_analysis_ids']==[final['id']]
    assert record['problem_types'] and record['knowledge_names']==['等式与数量关系']
    detail=client.get('/api/corpus/bank/'+record['id']).json()
    assert detail['research_versions'][0]['analysis']==final['snapshot']['analysis']
    assert detail['research_versions'][0]['independent_verification']
    assert detail['sources'][0]['category']=='mock'
    assert detail['origins'][0]['filename'].endswith('-V1.json')
    assert 'text' not in detail['sources'][0]
    exported=client.get('/api/corpus/bank/'+record['id']+'/download')
    assert exported.status_code==200 and exported.json()['format']=='mathlet-question-bank'
    assert exported.json()['question']['reference_answer']==''
    url='/api/research/versions/analysis/'+final['id']+'/download';old=client.get(url).content
    revision=client.post('/api/research-editor/versions/'+final['id']+'/revise').json()
    assert revision['status']=='completed'
    assert client.get(url).content==old
    assert len(client.get('/api/corpus/bank/'+record['id']).json()['research_versions'])==1
    fixed=finalize_study(client,revision)
    assert len(client.get('/api/corpus/bank/'+record['id']).json()['research_versions'])==2
    assert len(client.get('/api/corpus/bank').json())==2


def test_existing_finals_backfill_once_and_source_changes_invalidate_reuse(client,monkeypatch):
    run,q,doc,blocks=start_study(client,monkeypatch);final=finalize_study(client,run)
    original=client.get('/api/research/versions/analysis/'+final['id']+'/download').content
    with connect() as c:
        c.execute('DELETE FROM question_bank_studies');c.execute('DELETE FROM question_bank_questions');c.execute('DELETE FROM schema_migrations WHERE version=14')
    init_db();init_db()
    record=client.get('/api/corpus/bank/'+q['question_id']).json()
    assert len(record['research_versions'])==1 and record['reusable']
    with connect() as c:c.execute('UPDATE blocks SET text=? WHERE id=?',('原文改变',blocks[1]['id']))
    record=client.get('/api/corpus/bank/'+q['question_id']).json()
    assert record['stale'] and not record['reusable'] and not record['research_versions'][0]['current']
    assert client.get('/api/research/versions/analysis/'+final['id']+'/download').content==original


def test_confirmed_mapping_is_structured_by_role_and_only_carries_linked_knowledge(client,monkeypatch):
    from test_research import context
    from mathlet import knowledge_worker as worker
    run,q,doc,blocks=start_study(client,monkeypatch);f=finalize_study(client,run)
    _,base,kv=context(client,monkeypatch);ref=kv['id']+':'+kv['snapshot']['items'][0]['knowledge_id']
    monkeypatch.setattr(worker,'generate',lambda *_:(json.dumps({'links':[{'ref':ref,'role':'method','reason':'用于转译条件','evidence':'明确已知与目标'}],'gaps':[],'summary':'方法关联'}),None))
    request=client.post('/api/corpus/mappings',json={'analysis_version_ids':[f['id']],'version_ids':[kv['id']]}).json();worker.run_one_knowledge()
    m=client.get('/api/corpus/mappings').json()[0]
    assert client.get('/api/corpus/bank/'+q['question_id']).json()['mapping_versions']==[]
    result=client.post('/api/corpus/mappings/'+m['id']+'/finalize',json={'revision':m['revision'],'confirmed':True});assert result.status_code==201,result.text
    bank=client.get('/api/corpus/bank/'+q['question_id']).json()
    assert bank['mapping_versions'][0]['snapshot']['mapping']['links'][0]['role']=='method'
    assert len(bank['mapping_versions'][0]['snapshot']['knowledge'])==1
    assert bank['knowledge_units']==[kv['snapshot']['unit']['title']]
