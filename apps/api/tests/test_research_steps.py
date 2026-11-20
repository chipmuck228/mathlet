"""Long synthetic solutions retain every step; no real exam or paid calls."""
import json
import pytest
from pydantic import Field,ValidationError
from test_corpus import client,exam,solution,independent_model,finalize_study
from mathlet import knowledge_worker as worker,corpus_worker
from mathlet.research_models import Approach,MAX_APPROACH_STEPS
from mathlet.corpus_models import IndependentAnalysis


def long_solution(question,count):
    body=solution(question)
    body['approaches'][0]['steps']=[{'action':f'第{i+1}步：按条件计算并检查分支','reason':f'依据第{i+1}项等式关系','knowledge_refs':[]} for i in range(count)]
    return body


@pytest.mark.parametrize('count',[12,40,MAX_APPROACH_STEPS])
def test_long_schema_preserves_all_steps(count):
    body=long_solution({'statement':'合成题'},count)
    assert IndependentAnalysis.model_validate(body).model_dump()==body
    assert IndependentAnalysis.model_json_schema()['$defs']['Approach']['properties']['steps']['maxItems']==MAX_APPROACH_STEPS


def test_step_capacity_does_not_truncate_or_accept_invalid_steps():
    body=long_solution({'statement':'合成题'},MAX_APPROACH_STEPS+1)
    with pytest.raises(ValidationError):IndependentAnalysis.model_validate(body)
    body=long_solution({'statement':'合成题'},12);body['approaches'][0]['steps'][-1]['reason']=''
    with pytest.raises(ValidationError):IndependentAnalysis.model_validate(body)


@pytest.mark.parametrize('failed_step',['independent:solve','independent:blind-solve'])
def test_retry_revalidates_old_ten_step_failure_without_repaying_and_keeps_final(client,monkeypatch,failed_step):
    fixed,doc,blocks=exam(client,monkeypatch)
    q=client.get('/api/corpus/catalog').json()['questions'][0]
    run_id=client.post('/api/corpus/studies',json={'question_ids':[q['id']]}).json()['results'][0]['run_id']
    calls=[]
    def model(config,system,payload,tokens):
        if 'first' in payload:
            assert len(payload['first']['approaches'][0]['steps'])==12
            assert len(payload['second']['approaches'][0]['steps'])==12
            return independent_model(config,system,payload,tokens)
        assert '最多60步' in system
        calls.append(payload)
        return json.dumps(long_solution(payload['question'],12)),None
    monkeypatch.setattr(worker,'generate',model)
    original=corpus_worker.IndependentAnalysis
    class LegacyApproach(Approach):
        steps:list=Field(min_length=1,max_length=10)
    class LegacyAnalysis(IndependentAnalysis):
        approaches:list[LegacyApproach]=Field(min_length=1,max_length=3)
    # For blind-solve failure only, allow solve and then emulate the old validator.
    if failed_step=='independent:solve':monkeypatch.setattr(corpus_worker,'IndependentAnalysis',LegacyAnalysis)
    else:
        def switch(config,system,payload,tokens):
            result=model(config,system,payload,tokens)
            if len(calls)==2:monkeypatch.setattr(corpus_worker,'IndependentAnalysis',LegacyAnalysis)
            return result
        monkeypatch.setattr(worker,'generate',switch)
    worker.run_one_knowledge()
    run=client.get('/api/research-editor/runs/'+run_id).json()
    assert run['status']=='failed' and 'approaches.0.steps' in run['error'] and not run['outputs']
    before=len(calls);monkeypatch.setattr(corpus_worker,'IndependentAnalysis',original);monkeypatch.setattr(worker,'generate',model)
    assert client.post('/api/research/runs/'+run_id+'/retry',json={'revision':run['revision']}).status_code==200
    worker.run_one_knowledge();run=client.get('/api/research-editor/runs/'+run_id).json()
    assert run['status']=='completed',run['error']
    assert len(calls)==2  # two independent solutions total, including recovered response
    if failed_step=='independent:blind-solve':assert len(calls)==before
    records=[c for c in run['calls'] if c['step']==failed_step]
    assert len(records)==1 and records[0]['status']=='revalidated'
    assert len(run['outputs'][0]['body']['approaches'][0]['steps'])==12
    final=finalize_study(client,run);url='/api/research/versions/analysis/'+final['id']+'/download';old=client.get(url).content
    assert len(json.loads(old)['analysis']['approaches'][0]['steps'])==12
    fork=client.post('/api/research-editor/versions/'+final['id']+'/revise');assert fork.status_code==201
    assert len(fork.json()['outputs'][0]['body']['approaches'][0]['steps'])==12
    assert client.get(url).content==old


def test_downstream_mapping_can_reference_later_steps():
    from mathlet.teaching_models import Application
    mapping={'id':'m','quote':'题干依据','knowledge_ref':'k','why':'使用这个条件','operation':'检验','conditions':'原题条件','approach_id':'p1','step_index':MAX_APPROACH_STEPS-1}
    assert Application.model_validate(mapping).step_index==59
    with pytest.raises(ValidationError):Application.model_validate(mapping|{'step_index':MAX_APPROACH_STEPS})
