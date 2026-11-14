import json
import pytest
from test_exam_extraction import client,ready,start,get,final,save
from mathlet import knowledge_worker as worker
from mathlet.db import connect
from mathlet.exam_batches import original_span,AnchorError
from mathlet.paper_models import Span
from mathlet.paper_research import resolve


def test_unique_end_after_start_recovers_wrong_occurrence():
    original={'id':'b','text':'前题结束。2.第二题结束。','locator':'测试','assets':[],'verified':True}
    piece=original|{'source_offset':0}
    mapped=original_span(Span(block_id='b',start_anchor='2.',end_anchor='结束。'),piece,original)
    resolved=resolve({'source':json.dumps({'blocks':[original]})},{'question_spans':[mapped],'answer_spans':[],'asset_ids':[]})
    assert resolved['statement']=='2.第二题结束。'
    ambiguous=original|{'text':'前题结束。2.题干结束。小问结束。'}
    with pytest.raises(AnchorError):original_span(Span(block_id='b',start_anchor='2.',end_anchor='结束。'),ambiguous|{'source_offset':0},ambiguous)


def proposal(block,invalid=True):
    return {'title':'合成试卷','questions':[{'number':'1','question_spans':[{'block_id':block,'start_anchor':'1.','end_anchor':'第一题。'}]}, {'number':'2','question_spans':[{'block_id':block,'start_anchor':'第二题','end_anchor':'第一题。' if invalid else '最后。'}]}],'notes':[]}

def prepare(client):
    doc,blocks=ready(client,False)
    with connect() as c:c.execute('UPDATE blocks SET text=? WHERE id=?',('1.第一题。2.第二题，最后。',blocks[1]['id']))
    return start(client,doc),blocks[1]['id']


def test_ai_relocates_one_invalid_question_without_reextracting_paper(client,monkeypatch):
    r,block=prepare(client);calls=[]
    def model(config,system,payload,tokens):
        calls.append(payload)
        if 'location_errors' in payload:
            assert len(payload['location_errors'])==1 and payload['location_errors'][0]['number']=='2'
        return json.dumps(proposal(block,invalid='location_errors' not in payload)),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert len(calls)==2
    assert [q['question_text'] for q in r['payload']['questions']]==['1.第一题。','第二题，最后。']
    assert final(client,r).status_code==201


def test_unresolved_location_becomes_editable_empty_question_and_other_questions_survive(client,monkeypatch):
    r,block=prepare(client);calls=[]
    def model(*args):calls.append(1);return json.dumps(proposal(block)),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert len(calls)==2
    questions=r['payload']['questions'];assert questions[0]['question_text']=='1.第一题。'
    assert questions[1]['question_text']=='' and questions[1]['notes'].startswith('提取待核对：')
    assert final(client,r).status_code==422
    questions[1]['question_text']='2.第二题，最后。'
    changed=save(client,r,r['payload']);assert changed.status_code==200
    assert final(client,changed.json()).status_code==201


def test_no_stale_draft_written_during_location_repair(client,monkeypatch):
    r,block=prepare(client)
    def model(config,system,payload,tokens):
        if 'location_errors' in payload:
            with connect() as c:c.execute('UPDATE blocks SET text=? WHERE id=?',('原文已变化',block))
        return json.dumps(proposal(block,invalid='location_errors' not in payload)),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='failed' and r['payload'] is None and r['stale']


def test_malformed_repair_does_not_discard_good_questions(client,monkeypatch):
    r,block=prepare(client);calls=[]
    def model(config,system,payload,tokens):
        calls.append(1)
        return json.dumps({'title':'测试','questions':[],'notes':[]} if 'location_errors' in payload else proposal(block)),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert len(calls)==2
    assert r['payload']['questions'][0]['question_text']=='1.第一题。'
    assert r['payload']['questions'][1]['question_text']==''
    assert final(client,r).status_code==422


def test_retry_after_repair_network_failure_reuses_initial_extraction(client,monkeypatch):
    r,block=prepare(client);calls=[];failed=False
    def model(config,system,payload,tokens):
        nonlocal failed
        repair='location_errors' in payload;calls.append(repair)
        if repair and not failed:failed=True;raise ValueError('测试网络中断')
        return json.dumps(proposal(block,invalid=not repair)),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='failed' and not r['payload']
    assert client.post('/api/exam-extractions/'+r['id']+'/retry',json={'revision':r['run_revision']}).status_code==200
    worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert calls==[False,True,True]


def test_existing_failed_location_response_can_be_reused_for_repair(client,monkeypatch):
    from mathlet.db import uid,now
    r,block=prepare(client)
    with connect() as c:
        c.execute('INSERT INTO knowledge_calls(id,run_id,step,status,request_json,raw_response,reserved_tokens,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),r['id'],'exam:structure','failed','{}',json.dumps(proposal(block)),10000,'题目定位终点必须在起点之后',now(),now()))
    calls=[]
    def model(config,system,payload,tokens):
        calls.append(1);assert 'location_errors' in payload
        return json.dumps(proposal(block,False)),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert len(calls)==1
    assert r['calls'][0]['status']=='revalidated'


def test_cross_block_end_anchor_is_repaired_into_two_spans(client,monkeypatch):
    doc,blocks=ready(client,False)
    with connect() as c:
        c.execute('UPDATE blocks SET text=? WHERE id=?',('1.跨段题干开始',blocks[1]['id']))
        c.execute('UPDATE blocks SET text=? WHERE id=?',('续文结束。',blocks[2]['id']))
    r=start(client,doc)
    def model(config,system,payload,tokens):
        spans=[{'block_id':blocks[1]['id'],'start_anchor':'1.','end_anchor':'结束。'}]
        if 'location_errors' in payload:spans=[{'block_id':blocks[1]['id'],'start_anchor':'1.'},{'block_id':blocks[2]['id'],'end_anchor':'结束。'}]
        return json.dumps({'title':'跨段测试','questions':[{'number':'1','question_spans':spans}]}),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert r['payload']['questions'][0]['question_text']=='1.跨段题干开始\n\n续文结束。'
