import json
from test_exam_extraction import client,complete,final,get,save
from mathlet import knowledge_worker as worker
from mathlet.db import connect


def request(client,r,text='已知x2=4，求x。'):
    return client.post('/api/exam-extractions/'+r['id']+'/formula-suggestions',json={'revision':r['revision'],'question_key':r['payload']['questions'][0]['key'],'text':text})

def generate(config,system,payload,tokens):
    assert payload['current_text']=='已知x2=4，求x。'
    assert payload['native_docx'] and '不解题' in system
    assert all('解答：' not in b['text'] for b in payload['blocks'])
    return json.dumps({'changes':[{'before':'x2','after':r'\(x^2\)','reason':'恢复平方结构','evidence':'对应原文公式x^2'}],'uncertainties':['仍需核对原题数字']}),None


def test_formula_proposal_preserves_manuscript_and_logs_call(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,False)
    before=client.get('/api/exam-extractions/'+r['id']).content
    task=request(client,r);assert task.status_code==201,task.text
    task=task.json();assert request(client,r).json()['id']==task['id']
    monkeypatch.setattr(worker,'generate',generate);assert worker.run_one_knowledge()
    result=client.get('/api/exam-formula-suggestions/'+task['id']).json()
    assert result['status']=='completed',result['error']
    assert result['result']['suggested_text']==r'已知\(x^2\)=4，求x。'
    assert not result['stale']
    assert client.get('/api/exam-extractions/'+r['id']).content==before
    with connect() as c:
        assert c.execute('SELECT status FROM knowledge_calls WHERE run_id=?',(task['id'],)).fetchone()[0]=='succeeded'
    body=r['payload'];body['questions'][0]['question_text']='教师新修订'
    assert save(client,r,body).status_code==200
    assert client.get('/api/exam-formula-suggestions/'+task['id']).json()['stale']
    assert request(client,r).status_code==409


def test_formula_stale_during_call_and_final_immutable(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,False);task=request(client,r).json()
    fixed=final(client,r).json();version=fixed['versions'][0]['id']
    url='/api/exam-extraction-versions/'+version+'/download';old=client.get(url).content
    assert request(client,r).status_code==409
    monkeypatch.setattr(worker,'generate',generate);worker.run_one_knowledge()
    result=client.get('/api/exam-formula-suggestions/'+task['id']).json()
    assert result['status']=='failed' and result['stale']
    assert client.get(url).content==old


def test_formula_invalid_replacement_and_no_evidence_fallback(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,False);task=request(client,r).json()
    monkeypatch.setattr(worker,'generate',lambda *args:(json.dumps({'changes':[{'before':'不存在','after':'x','reason':'test','evidence':'test'}],'uncertainties':[]}),None))
    worker.run_one_knowledge();result=client.get('/api/exam-formula-suggestions/'+task['id']).json()
    assert result['status']=='failed' and '唯一定位' in result['error']
    task=request(client,r).json()
    monkeypatch.setattr(worker,'generate',lambda *args:(json.dumps({'changes':[],'uncertainties':['无法确认x2的原始含义']}),None))
    worker.run_one_knowledge();result=client.get('/api/exam-formula-suggestions/'+task['id']).json()
    assert result['status']=='completed' and result['result']['suggested_text']==result['original_text']


def test_source_change_during_paid_call_keeps_proposal_unapplied(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,False);task=request(client,r).json()
    def changing(*args):
        with connect() as c:c.execute('UPDATE blocks SET text=? WHERE id=?',('changed source',blocks[1]['id']))
        return generate(*args)
    monkeypatch.setattr(worker,'generate',changing);worker.run_one_knowledge()
    result=client.get('/api/exam-formula-suggestions/'+task['id']).json()
    assert result['status']=='failed' and result['stale']
    assert get(client,r)['payload']==r['payload']


def test_native_omml_evidence_and_pdf_limitations(tmp_path,monkeypatch):
    from zipfile import ZipFile
    from mathlet import exam_formulas as formulas
    monkeypatch.setattr(formulas,'data_dir',lambda:tmp_path)
    folder=tmp_path/'documents'/'doc';folder.mkdir(parents=True)
    xml='''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p><m:oMath><m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup></m:oMath></w:p></w:body></w:document>'''
    with ZipFile(folder/'original.docx','w') as z:z.writestr('word/document.xml',xml)
    evidence,note=formulas.native_evidence({'kind':'docx','document_id':'doc'},[{'id':'b','ordinal':0}])
    assert evidence[0]['formula_parts'][0]['type']=='math'
    assert evidence[0]['formula_parts'][0]['latex']=='{x}^{2}'
    evidence,note=formulas.native_evidence({'kind':'pdf'},[])
    assert not evidence and '未读取PDF原页' in note


def test_unsaved_text_whitespace_is_preserved(client,monkeypatch):
    r,doc,blocks=complete(client,monkeypatch,False)
    text='  x2=4\n'
    task=request(client,r,text).json()
    monkeypatch.setattr(worker,'generate',lambda *args:(json.dumps({'changes':[],'uncertainties':['无法确认公式结构']}),None))
    worker.run_one_knowledge()
    result=client.get('/api/exam-formula-suggestions/'+task['id']).json()
    assert result['status']=='completed',result['error']
    assert result['original_text']==text==result['result']['suggested_text']
