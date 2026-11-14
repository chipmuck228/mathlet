import json
from test_exam_extraction import client,ready,start,get,final
from mathlet import knowledge_worker as worker
from mathlet.db import connect,uid
from mathlet.exam_batches import batches,original_span,coalesce
from mathlet.paper_models import Span
from mathlet.paper_research import resolve


def test_large_exam_batches_cover_full_source_and_finalize(client,monkeypatch):
    doc,blocks=ready(client,False)
    # More than both previous arbitrary cutoffs, with questions at opposite ends.
    with connect() as c:
        c.execute('UPDATE blocks SET text=? WHERE id=?',('1.第一题。',blocks[1]['id']))
        for i in range(600):
            c.execute('INSERT INTO blocks(id,document_id,ordinal,locator,text,preview,assets,warnings) VALUES(?,?,?,?,?,?,?,?)',(uid(),doc,10+i,'测试段落','资料说明'*40,'','[]','[]'))
        c.execute('UPDATE blocks SET text=?,ordinal=1000 WHERE id=?',('2.最后一题。',blocks[2]['id']))
    r=start(client,doc);assert r['batch_count']>3
    seen=[]
    def model(config,system,payload,tokens):
        seen.extend(b['id'] for b in payload['blocks']);items=[]
        for b in payload['blocks']:
            if b['text'] in ['1.第一题。','2.最后一题。']:
                items.append({'number':b['text'][0],'question_spans':[{'block_id':b['id']}],'continues_previous':False})
        return json.dumps({'title':'测试试卷' if payload['batch_number']==1 else '', 'questions':items,'notes':[]}),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert len(seen)==len(set(seen))==603
    assert [q['question_text'] for q in r['payload']['questions']]==['1.第一题。','2.最后一题。']
    fixed=final(client,r);assert fixed.status_code==201,fixed.text
    assert fixed.json()['versions'][0]['filename'].endswith('-V1.json')


def test_split_block_offsets_repeated_anchors_and_continuation(client,monkeypatch):
    from mathlet import exam_batches
    monkeypatch.setattr(exam_batches,'BATCH_CHARS',12)
    doc,blocks=ready(client,False)
    text='1.abcdefghij'+'klmnopqrstuv'
    with connect() as c:
        c.execute('UPDATE blocks SET text=? WHERE id=?',(text,blocks[1]['id']))
        c.execute('UPDATE blocks SET text=? WHERE id IN (?,?)',('',blocks[0]['id'],blocks[2]['id']))
    r=start(client,doc);assert r['batch_count']==2
    def model(config,system,payload,tokens):
        return json.dumps({'title':'跨批测试','questions':[{'number':'1','continues_previous':payload['batch_number']>1,'question_spans':[{'block_id':payload['blocks'][0]['id']}]}]}),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert len(r['payload']['questions'])==1
    assert r['payload']['questions'][0]['question_text']==text
    assert len(r['payload']['questions'][0]['question_spans'])==1
    original={'id':'b','locator':'测试','text':'abcabcabcabc','assets':[]}
    piece=original|{'text':'abcabc','source_offset':6}
    mapped=original_span(Span(block_id='b',start_anchor='abc',end_anchor='abc',end_occurrence=1),piece,original)
    assert mapped['start_occurrence']==2
    value=resolve({'source':json.dumps({'blocks':[original|{'verified':True}]})},{'question_spans':[mapped],'answer_spans':[],'asset_ids':[]})
    assert value['statement']=='abcabc'


def test_batch_retry_reuses_completed_calls(client,monkeypatch):
    from mathlet import exam_batches
    monkeypatch.setattr(exam_batches,'BATCH_CHARS',12)
    doc,blocks=ready(client,False)
    with connect() as c:
        c.execute('UPDATE blocks SET text=? WHERE id=?',('1.abcdefghij'+'klmnopqrstuv',blocks[1]['id']))
        c.execute('UPDATE blocks SET text=? WHERE id IN (?,?)',('',blocks[0]['id'],blocks[2]['id']))
    r=start(client,doc);seen=[];fail=True
    def model(config,system,payload,tokens):
        nonlocal fail
        n=payload['batch_number'];seen.append(n)
        if n==2 and fail:fail=False;raise ValueError('测试模拟网络中断')
        return json.dumps({'title':'断点测试','questions':[{'number':'1','continues_previous':n>1,'question_spans':[{'block_id':payload['blocks'][0]['id']}]}]}),None
    monkeypatch.setattr(worker,'generate',model);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='failed' and not r['payload']
    retried=client.post('/api/exam-extractions/'+r['id']+'/retry',json={'revision':r['run_revision']})
    assert retried.status_code==200,retried.text
    worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert seen==[1,2,2]
    assert r['payload']['questions'][0]['question_text']=='1.abcdefghijklmnopqrstuv'
