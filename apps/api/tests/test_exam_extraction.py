"""Whole-exam review uses synthetic originals, never real user exam data or paid calls."""
import json
from pathlib import Path
from PIL import Image
from test_knowledge import client
from test_planning import upload
from mathlet import knowledge_worker as worker
from mathlet.db import connect,data_dir,init_db

TITLE='合成学校2026届九年级模拟试卷（测试，非真题）'
TEXT=r'1. 已知x=2，求\(x^2\)。 A.2 B.4 C.6 D.8'+'\n'+r'2. 解方程组 x+y=5，x-y=1。'

def ready(client,images=True):
    client.put('/api/knowledge/provider',json={'model':'synthetic-model','api_key':'test-only-key'})
    doc=upload(client,[TITLE,TEXT,'解答：1. 4。'],'mock')
    blocks=client.get('/api/documents/'+doc+'/blocks').json()
    if images:
        folder=data_dir()/'documents'/doc/'assets';folder.mkdir(exist_ok=True)
        for name,color in [('first.png','red'),('second.png','blue')]:Image.new('RGB',(10,10),color).save(folder/name)
        with connect() as c:c.execute('UPDATE blocks SET assets=? WHERE id=?',(json.dumps(['first.png','second.png']),blocks[1]['id']))
    assert not any(b['verified'] for b in blocks)
    return doc,blocks

def model(config,system,payload,tokens):
    assert 'blocks' in payload and len(payload['blocks'])==3
    b=payload['blocks'][1];a=payload['blocks'][2];images=b['assets']
    value={'title':TITLE,'questions':[{'title':'第一题','number':'1','question_spans':[{'block_id':b['id'],'start_anchor':'1.','end_anchor':'D.8'}],'answer_spans':[{'block_id':a['id'],'start_anchor':'1.','end_anchor':'4。'}]}, {'title':'第二题','number':'2','question_spans':[{'block_id':b['id'],'start_anchor':'2.'}],'asset_ids':[images[0]['id']] if images else [],'answer_spans':[]}],'notes':['第二题原文没有解答，未补写。']}
    return json.dumps(value),None

def start(client,doc):
    r=client.post('/api/exam-extractions',json={'document_id':doc});assert r.status_code==201,r.text
    return r.json()
def get(client,r):return client.get('/api/exam-extractions/'+r['id']).json()
def save(client,r,body):return client.put('/api/exam-extractions/'+r['id'],json={'revision':r['revision'],'body':body})
def final(client,r):return client.post('/api/exam-extractions/'+r['id']+'/finalize',json={'revision':r['revision'],'confirmed':True})
def complete(client,monkeypatch,images=True,legacy=False):
    doc,blocks=ready(client,images);r=start(client,doc);monkeypatch.setattr(worker,'generate',model);assert worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    if legacy:
        # Simulate a pre-upgrade saved manuscript; historical answer data must remain intact.
        body=r['payload'];body.pop('content_mode',None);body['questions'][0]['answer_text']='1. 4。'
        body['questions'][0]['answer_spans']=[{'block_id':blocks[2]['id'],'start_anchor':'1.','end_anchor':'4。','start_occurrence':0,'end_occurrence':0}]
        with connect() as c:c.execute('UPDATE exam_extractions SET payload=? WHERE id=?',(json.dumps(body,ensure_ascii=False),r['id']))
        r=get(client,r)
    return r,doc,blocks


def test_whole_exam_extract_edit_images_finalize_and_readonly_without_block_reviews(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch)
    assert r['payload']['title']==TITLE
    assert r['payload']['questions'][0]['question_text']==TEXT.split('\n')[0]
    assert r['payload']['questions'][0]['answer_text']==''
    assert r['payload']['content_mode']=='questions_only'
    assert not r['payload']['questions'][1]['answer_text']
    assert client.get('/api/research/questions').json()==[]
    assert client.get('/api/source-reviews').json()==[]
    assert not any(b['verified'] for b in client.get('/api/documents/'+doc+'/blocks').json())
    body=r['payload'];body['questions'][0]['question_text']+=' 请写出过程。'
    assets=r['source']['blocks'][1]['assets'];body['questions'][1]['image_ids']=[assets[1]['id']]
    changed=save(client,r,body);assert changed.status_code==200,changed.text
    changed=changed.json();assert changed['filename']==r['filename']
    assert save(client,r,body).status_code==409
    fixed=final(client,changed);assert fixed.status_code==201,fixed.text
    fixed=fixed.json();assert fixed['read_only'] and fixed['file_saved']
    version=fixed['versions'][0];url='/api/exam-extraction-versions/'+version['id']+'/download';original=client.get(url).content
    f=json.loads(original);assert f['teacher_confirmed_transcription'] and not f['answer_math_verified']
    assert f['questions'][0]['question_text'].endswith('请写出过程。')
    assert f['questions'][1]['image_ids']==[assets[1]['id']] and not f['questions'][1]['research_ready']
    assert f['questions'][0]['research_ready'] and f['questions'][0]['question_version_id']
    assert 'answer_text' not in f['questions'][0] and 'answer_spans' not in f['questions'][0]
    assert f['content_mode']=='questions_only'
    assert len(f['assets'])==1 and all(a['data_url'].startswith('data:image/png;base64,') for a in f['assets'])
    assert (data_dir()/'exam-extractions'/version['filename']).read_bytes()==original
    assert save(client,fixed,body).status_code==409
    assert final(client,fixed).json()['versions'][0]['id']==version['id']
    questions=client.get('/api/research/questions').json();assert len(questions)==2
    assert questions[0]['payload']['answer_status'] in {'absent','unchecked'}
    with connect() as c:
        old=json.loads(c.execute('SELECT original_payload FROM exam_extractions WHERE id=?',(r['id'],)).fetchone()[0]);assert not old['questions'][0]['question_text'].endswith('请写出过程。')
    # Whole-question finals can enter batch research without block review or another split.
    opened=client.post('/api/exam-extraction-versions/'+version['id']+'/paper');assert opened.status_code==201,opened.text
    p=opened.json();assert len(p['items'])==2 and p['items'][0]['resolved']['statement']==f['questions'][0]['question_text']
    assert not p['items'][0]['resolved']['errors'] and not p['coverage']['unchecked_blocks']
    assert client.post('/api/exam-extraction-versions/'+version['id']+'/paper').json()['id']==p['id']
    revised=client.post('/api/exam-extractions/'+r['id']+'/revise',json={'revision':fixed['revision']});assert revised.status_code==200,revised.text
    revised=revised.json();body=revised['payload'];body['questions'][1]['diagram_description']='图中所需数量关系均已写在题干中。'
    revised=save(client,revised,body).json();nextfinal=final(client,revised);assert nextfinal.status_code==201,nextfinal.text
    assert nextfinal.json()['versions'][0]['version_number']==2
    assert client.get('/api/papers/'+p['id']).json()['stale']
    init_db();assert client.get(url).content==original
    # Raw extraction blocks were never silently marked as human checked.
    assert not any(b['verified'] for b in client.get('/api/documents/'+doc+'/blocks').json())


def test_transcription_final_does_not_gate_on_formula_commands_or_claim_math_answer_verification(client,monkeypatch):
    r,doc,_=complete(client,monkeypatch,False);b=r['payload'];b['questions'][0]['question_text']=r'原文公式\(\customUnknown{x}\)（教师确认忠实转录）'
    r=save(client,r,b).json();f=final(client,r);assert f.status_code==201,f.text
    frozen=client.get('/api/exam-extraction-versions/'+f.json()['versions'][0]['id']).json()['snapshot']
    assert '\\customUnknown' in frozen['questions'][0]['question_text'] and not frozen['answer_math_verified']
    questions=client.get('/api/research/questions').json();assert all(q['payload']['answer_status']!='verified' for q in questions)


def test_import_exact_file_is_readonly_but_external_changes_become_new_draft(client,monkeypatch):
    r,doc,_=complete(client,monkeypatch,False,legacy=True);r=final(client,r).json();vid=r['versions'][0]['id'];f=client.get('/api/exam-extraction-versions/'+vid).json()['snapshot']
    opened=client.post('/api/documents/'+doc+'/exam-extractions/import',json={'payload':f});assert opened.status_code==201,opened.text
    assert opened.json()['view_version_id']==vid and opened.json()['extraction']['read_only']
    f['questions'][0]['answer_text']='外部修改，必须重新核对'
    copied=client.post('/api/documents/'+doc+'/exam-extractions/import',json={'payload':f});assert copied.status_code==201,copied.text
    assert not copied.json()['extraction']['read_only'] and not copied.json()['view_version_id']
    assert copied.json()['extraction']['id']!=r['id']
    assert client.get('/api/exam-extraction-versions/'+vid).json()['snapshot']['questions'][0]['answer_text']=='1. 4。'
    fork=client.post('/api/exam-extraction-versions/'+vid+'/revise');assert fork.status_code==201,fork.text
    assert fork.json()['parent_version']==vid and fork.json()['payload']['questions'][0]['answer_text']=='1. 4。'


def test_source_changes_reject_overwrite_and_keep_old_final_files(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,False);f=final(client,r).json();vid=f['versions'][0]['id'];url='/api/exam-extraction-versions/'+vid+'/download';original=client.get(url).content
    b=blocks[1];client.put('/api/blocks/'+b['id'],json={'revision':b['revision'],'text':b['text']+'来源变化','verified':False})
    assert get(client,r)['stale'] and final(client,get(client,r)).status_code==409
    assert client.post('/api/exam-extraction-versions/'+vid+'/paper').status_code==409
    assert client.get(url).content==original


def test_repeated_start_reuses_pending_task_and_stale_paid_response_is_not_applied(client,monkeypatch):
    doc,blocks=ready(client,False);r=start(client,doc);assert start(client,doc)['id']==r['id']
    def mutate(*args):
        result=model(*args);b=blocks[1];client.put('/api/blocks/'+b['id'],json={'revision':b['revision'],'text':b['text']+'变动','verified':False});return result
    monkeypatch.setattr(worker,'generate',mutate);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='failed' and r['stale'] and not r['payload']
    assert r['calls'] and client.post('/api/exam-extractions/'+r['id']+'/retry',json={'revision':r['run_revision']}).status_code==409


def test_oversized_answer_kept_in_extraction_not_silently_truncated_for_research(client,monkeypatch):
    r,_,_=complete(client,monkeypatch,False,legacy=True);body=r['payload'];body['questions'][0]['answer_text']='原文解答'*2300
    r=save(client,r,body).json();f=final(client,r);assert f.status_code==201,f.text
    frozen=client.get('/api/exam-extraction-versions/'+f.json()['versions'][0]['id']).json()['snapshot']
    assert len(frozen['questions'][0]['answer_text'])==9200 and not frozen['questions'][0]['research_ready']
    assert not frozen['questions'][0]['research_question_id']


def test_fixed_image_bytes_survive_source_image_change_and_review_flags_are_not_content_changes(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch);r=final(client,r).json();vid=r['versions'][0]['id'];url='/api/exam-extraction-versions/'+vid+'/download';before=client.get(url).content
    b=blocks[0];client.put('/api/blocks/'+b['id'],json={'revision':b['revision'],'text':b['text'],'verified':True})
    assert not get(client,r)['stale']
    Image.new('RGB',(10,10),'green').save(data_dir()/'documents'/doc/'assets'/'first.png')
    assert get(client,r)['stale'] and client.get('/api/exam-extraction-versions/'+vid).json()['stale']
    assert client.get(url).content==before
    f=json.loads(before);assert f['assets'][0]['data_url'].startswith('data:image/png;base64,')
    malformed=f|{'source':{'original_hash':f['source']['original_hash'],'blocks':[{'ordinal':0,'assets':[]}]}}
    assert client.post('/api/documents/'+doc+'/exam-extractions/import',json={'payload':malformed}).status_code==422


def test_question_title_is_not_requested_and_long_legacy_title_never_truncates_original_question(client,monkeypatch):
    from mathlet.exam_models import ExamPlan
    assert 'title' not in ExamPlan.model_json_schema()['$defs']['ExamHint']['properties']
    doc,_=ready(client,False);r=start(client,doc)
    def long_title(*args):
        raw,usage=model(*args);value=json.loads(raw)
        for q in value['questions']:q['title']='这是一段被模型误当作标题的长题干'+r'\(x^2+\frac{1}{x}\)'*100
        return json.dumps(value),usage
    monkeypatch.setattr(worker,'generate',long_title);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert r['payload']['questions'][0]['question_text']==TEXT.split('\n')[0]
    assert r['payload']['questions'][0]['answer_text']==''
    assert r['payload']['content_mode']=='questions_only'


def test_retry_recovers_historical_title_error_without_another_paid_call_even_at_budget_limit(client,monkeypatch):
    from pydantic import create_model,Field
    from mathlet.paper_models import SplitItem
    from mathlet.research_models import Strict
    from mathlet import exam_worker
    OldHint=create_model('OldHint',__base__=SplitItem,answer_asset_ids=(list[str],Field(default_factory=list)))
    OldPlan=create_model('ExamPlan',__base__=Strict,title=(str,...),questions=(list[OldHint],...),notes=(list[str],Field(default_factory=list)))
    doc,_=ready(client,False);r=start(client,doc)
    def response(*args):
        raw,usage=model(*args);v=json.loads(raw);v['questions'][0]['title']='长题干'*200
        return json.dumps(v),usage
    with monkeypatch.context() as old:
        old.setattr(exam_worker,'ExamPlan',OldPlan);old.setattr(worker,'generate',response);worker.run_one_knowledge()
    r=get(client,r);assert r['status']=='failed' and 'questions.0.title' in r['error']
    with connect() as c:
        call=dict(c.execute('SELECT * FROM knowledge_calls WHERE run_id=?',(r['id'],)).fetchone())
        frozen=json.loads(c.execute('SELECT model_json FROM knowledge_runs WHERE id=?',(r['id'],)).fetchone()[0]);frozen.update(max_calls=1,output_token_budget=10000)
        c.execute('UPDATE knowledge_runs SET model_json=? WHERE id=?',(json.dumps(frozen),r['id']))
    def forbidden(*_):raise AssertionError('历史响应可恢复，不应再次调用模型')
    monkeypatch.setattr(worker,'generate',forbidden)
    retry=client.post('/api/exam-extractions/'+r['id']+'/retry',json={'revision':r['run_revision']});assert retry.status_code==200,retry.text
    worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error']
    assert r['payload']['questions'][0]['question_text']==TEXT.split('\n')[0]
    with connect() as c:
        calls=c.execute('SELECT * FROM knowledge_calls WHERE run_id=?',(r['id'],)).fetchall()
        assert len(calls)==1 and calls[0]['status']=='revalidated' and calls[0]['raw_response']==call['raw_response']


def test_legacy_title_compatibility_does_not_accept_foreign_source_ids(client,monkeypatch):
    doc,_=ready(client,False);r=start(client,doc)
    def invalid(*args):
        raw,usage=model(*args);v=json.loads(raw);v['questions'][0]['title']='长标题'*200;v['questions'][0]['question_spans'][0]['block_id']='foreign'
        return json.dumps(v),usage
    monkeypatch.setattr(worker,'generate',invalid);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='failed' and not r['payload'] and '原文之外' in r['error']
