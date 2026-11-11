import json
import pytest
from test_planning import client,upload,edit,confirm,import_plan
from mathlet import knowledge_worker as worker
from mathlet.db import init_db,connect


def configured(client):
    response=client.put('/api/knowledge/provider',json={'model':'test-model','api_key':'test-key-not-for-prompts'})
    assert response.status_code==200


def model(config,system,payload,max_tokens):
    assert '只依据所给资料' in system
    source=payload['sources'][0]
    return json.dumps({'domains':[{'title':'函数','source_id':source['id'],'quote':'函数','requirements':[{'key':'r1','source_id':source['id'],'quote':'能画图和读图'}],
        'topics':[{'title':'二次函数','source_id':source['id'],'quote':'二次函数','requirement_keys':['r1'],'learning_goals':'画二次函数图象并分析变化规律'}]}], 'notes':'目标对应须教师核对'}),{'total_tokens':100}


def start(client,doc,**extra):
    return client.post('/api/planning-ai/runs',json={'document_id':doc,'source_revisions':{x['id']:x['revision'] for x in client.get(f'/api/documents/{doc}/blocks').json()},'title':'初中数学规划','consent':True,**extra})


def complete(client,monkeypatch):
    configured(client);doc=upload(client,['函数\t一次函数、二次函数\t能画图和读图'],'standard')
    monkeypatch.setattr(worker,'generate',model)
    response=start(client,doc);assert response.status_code==201,response.text
    worker.run_one_knowledge()
    task=client.get('/api/planning-ai/runs/'+response.json()['id']).json()
    assert task['status']=='completed',task
    plan=next(p for p in client.get('/api/plans').json() if p['id']==task['plan_id'])
    return doc,task,plan


def test_ai_proposal_edit_confirm_and_generation_share_topic_and_source_requirements(client,monkeypatch):
    doc,task,plan=complete(client,monkeypatch)
    assert not plan['confirmed'] and not plan['stale_sources']
    assert [n['kind'] for n in plan['payload']['nodes']]==['domain','topic']
    unit=plan['payload']['units'][0];requirement=plan['payload']['requirements'][0]
    assert requirement['origin']=='source_excerpt' and requirement['text']=='能画图和读图'
    assert requirement['unit_ids']==[unit['id']]
    assert client.get('/api/knowledge/units').json()==[]
    assert client.post('/api/knowledge/units/from-plan',json={'plan_id':plan['id'],'unit_id':unit['id'],'plan_revision':1}).status_code==409
    # Source summary may be structurally confirmed without claiming the source itself verified.
    assert not client.get(f'/api/documents/{doc}/blocks').json()[0]['verified']
    edited_payload=plan['payload'];edited_payload['nodes'][1]['title']='二次函数复习';edited_payload['units'][0]['goals']='理解图象变化'
    response=edit(client,plan,**{k:edited_payload[k] for k in ['nodes','units','requirements']});assert response.status_code==200,response.text
    updated=response.json();assert updated['payload']['units'][0]['title']=='二次函数复习'
    confirmed=confirm(client,updated);assert confirmed.status_code==200,confirmed.text
    unit_args={'plan_id':plan['id'],'unit_id':unit['id'],'plan_revision':updated['revision']}
    knowledge=client.post('/api/knowledge/units/from-plan',json=unit_args).json()
    assert knowledge['title']=='二次函数复习' and knowledge['notes']=='理解图象变化'
    assert knowledge['origin_info']['learning_requirements'][0]['text']=='能画图和读图'
    assert client.post('/api/knowledge/units/from-plan',json=unit_args).json()['id']==knowledge['id']
    run=client.post(f"/api/knowledge/units/{knowledge['id']}/runs",json={'unit_revision':1,'consent':True}).json()
    assert run['input_json']['learning_requirements'][0]['text']=='能画图和读图'
    assert not run['input_json']['official_coverage_verified']
    # Planning edit invalidates the linked knowledge, never replaces its contents.
    latest=confirmed.json();changed=edit(client,latest,notes='范围调整').json()
    linked=next(x for x in client.get('/api/knowledge/units').json() if x['id']==knowledge['id'])
    assert linked['stale'] and linked['notes']=='理解图象变化'
    assert client.get('/api/knowledge/runs/'+run['id']).json()['stale']
    init_db();assert len(client.get('/api/plans').json())==1


@pytest.mark.parametrize('mutation',['quote','source','requirement','duplicate','too_many'])
def test_invalid_model_planning_evidence_never_creates_plan(client,monkeypatch,mutation):
    configured(client);doc=upload(client,['函数、二次函数，能画图和读图'])
    def invalid(config,system,payload,max_tokens):
        raw,usage=model(config,system,payload,max_tokens);value=json.loads(raw);d=value['domains'][0]
        if mutation=='quote': d['topics'][0]['quote']='来源中不存在的原文'
        if mutation=='source': d['source_id']='foreign'
        if mutation=='requirement': d['topics'][0]['requirement_keys']=['foreign']
        if mutation=='duplicate': d['topics'].append(d['topics'][0])
        if mutation=='too_many': d['topics'].append(d['topics'][0]|{'title':'另一个主题'})
        return json.dumps(value),usage
    monkeypatch.setattr(worker,'generate',invalid)
    response=start(client,doc,max_topics=1 if mutation=='too_many' else 80)
    worker.run_one_knowledge();task=client.get('/api/planning-ai/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and not task['plan_id'] and not client.get('/api/plans').json()
    artifacts=client.get('/api/knowledge/runs/'+task['id']+'/artifacts').json()
    assert artifacts['calls'][0]['raw_response']
    assert artifacts['calls'][0]['usage']
    assert 'test-key-not-for-prompts' not in json.dumps(artifacts)


def test_source_edits_before_and_during_generation_refuse_stale_results(client,monkeypatch):
    configured(client);doc=upload(client,['函数 二次函数 能画图和读图'])
    response=start(client,doc);block=client.get(f'/api/documents/{doc}/blocks').json()[0]
    client.put('/api/blocks/'+block['id'],json={'revision':block['revision'],'text':block['text']+'（补充）','verified':False})
    monkeypatch.setattr(worker,'generate',lambda *_:pytest.fail('stale source must not call model'))
    worker.run_one_knowledge();task=client.get('/api/planning-ai/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and task['stale']
    assert client.post('/api/planning-ai/runs/'+task['id']+'/retry',json={'revision':task['revision']}).status_code==409
    response=start(client,doc)
    def concurrent(config,system,payload,max_tokens):
        result=model(config,system,payload,max_tokens)
        with connect() as c:c.execute('UPDATE blocks SET text=text||? WHERE id=?',('再次修改',block['id']))
        return result
    monkeypatch.setattr(worker,'generate',concurrent);worker.run_one_knowledge()
    task=client.get('/api/planning-ai/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and not client.get('/api/plans').json()


def test_rebuild_keeps_existing_plan_and_invalid_hierarchy_quotes_are_rejected(client,monkeypatch):
    doc,task,plan=complete(client,monkeypatch)
    before=confirm(client,plan).json()
    second=start(client,doc);worker.run_one_knowledge()
    assert client.get('/api/planning-ai/runs/'+second.json()['id']).json()['plan_id']!=plan['id']
    original=next(p for p in client.get('/api/plans').json() if p['id']==plan['id'])
    assert original==before
    nodes=[dict(n) for n in original['payload']['nodes']];nodes[1]['parent_id']=None
    assert edit(client,original,nodes=nodes).status_code==422
    nodes=[dict(n) for n in original['payload']['nodes']];nodes[1]['source_excerpt']='伪造引文'
    assert edit(client,original,nodes=nodes).status_code==422
    nodes=[dict(n) for n in original['payload']['nodes']];nodes[0]['included']=False
    excluded=edit(client,original,nodes=nodes)
    assert excluded.status_code==200,excluded.text
    assert confirm(client,excluded.json()).status_code==422


def test_consent_empty_source_and_budget_fail_without_paid_calls(client):
    configured(client);doc=upload(client,['函数'])
    assert start(client,doc,consent=False).status_code==422
    client.put('/api/knowledge/provider',json={'model':'test-model','output_token_budget':6000})
    assert start(client,doc).status_code==422
    assert client.get('/api/planning-ai/runs').json()==[]


def test_docx_table_text_keeps_cells_for_model_and_source_preview_revision_is_bound(client,monkeypatch):
    import io
    from zipfile import ZipFile
    from mathlet.worker import run_one
    configured(client);buf=io.BytesIO()
    with ZipFile(buf,'w') as z:
        rows=[['领域','学生需要学习的主要内容','要达到的主要程度'],['函数','一次函数、二次函数','能画图和读图']]
        xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl>'
        for row in rows:xml+='<w:tr>'+''.join('<w:tc><w:p><w:r><w:t>'+v+'</w:t></w:r></w:p></w:tc>' for v in row)+'</w:tr>'
        z.writestr('word/document.xml',xml+'</w:tbl></w:body></w:document>')
    response=client.post('/api/documents?category=standard',files={'file':('summary.docx',buf.getvalue())})
    doc=response.json()['id'];run_one()
    block=client.get(f'/api/documents/{doc}/blocks').json()[0]
    assert '\t' in block['text'] and '学生需要学习的主要内容' in block['text']
    assert start(client,doc,source_revisions={block['id']:block['revision']+1}).status_code==409
    monkeypatch.setattr(worker,'generate',model);task=start(client,doc);worker.run_one_knowledge()
    assert client.get('/api/planning-ai/runs/'+task.json()['id']).json()['status']=='completed'


def test_failed_planning_can_retry_explicitly_without_overwriting_existing_plan(client,monkeypatch):
    configured(client);doc=upload(client,['函数 二次函数 能画图和读图'])
    monkeypatch.setattr(worker,'generate',lambda *_:('{broken',None))
    response=start(client,doc);worker.run_one_knowledge()
    task=client.get('/api/planning-ai/runs/'+response.json()['id']).json()
    assert task['status']=='failed' and len(task['calls'])==1
    assert client.post('/api/planning-ai/runs/'+task['id']+'/retry',json={'revision':task['revision']-1}).status_code==409
    monkeypatch.setattr(worker,'generate',model)
    assert client.post('/api/planning-ai/runs/'+task['id']+'/retry',json={'revision':task['revision']}).status_code==200
    worker.run_one_knowledge();task=client.get('/api/planning-ai/runs/'+task['id']).json()
    assert task['status']=='completed' and len(task['calls'])==2
    assert len(client.get('/api/plans').json())==1
