"""Synthetic native tables and full transcription/research preservation."""
import copy
import io
import json
from zipfile import ZipFile
import pytest
from test_knowledge import client
from test_exam_extraction import complete as plain_exam,start,get,save,final
from mathlet import knowledge_worker as worker
from mathlet.worker import run_one
from mathlet.db import connect,data_dir
from mathlet.data_tables import DataTable,docx_tables,table_html,tabular_text
from mathlet.exam_extraction import digest
from mathlet.research_editor import safe_question
from mathlet.corpus import fingerprint


def native_file():
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main';m='http://schemas.openxmlformats.org/officeDocument/2006/math'
    def p(s):return '<w:p><w:r><w:t>'+s+'</w:t></w:r></w:p>'
    def cell(s):return '<w:tc>'+p(s)+'</w:tc>'
    formula='<w:tc><w:p><m:oMath><m:f><m:num><m:r><m:t>1</m:t></m:r></m:num><m:den><m:r><m:t>x</m:t></m:r></m:den></m:f></m:oMath></w:p></w:tc>'
    xml=f'<w:document xmlns:w="{w}" xmlns:m="{m}"><w:body>'+p('合成统计试卷')+p('1. 根据下表，回答问题。')+'<w:tbl><w:tr>'+cell('成绩范围')+cell('人数')+'</w:tr><w:tr>'+cell('60≤x＜70')+cell('08')+'</w:tr><w:tr>'+cell('70≤x＜80')+formula+'</w:tr><w:tr>'+cell('80≤x≤100')+cell('')+'</w:tr></w:tbl>'+p('（1）说出表格中的已知数据。')+'</w:body></w:document>'
    out=io.BytesIO()
    with ZipFile(out,'w') as z:z.writestr('word/document.xml',xml)
    return out.getvalue()


def native_exam(client,monkeypatch):
    client.put('/api/knowledge/provider',json={'model':'table-test','api_key':'table-test-secret'})
    upload=client.post('/api/documents?category=exam',files={'file':('native-table.docx',native_file())});assert upload.status_code==201
    doc=upload.json()['id'];run_one();r=start(client,doc)
    def extract(config,system,payload,tokens):
        assert payload['blocks'][2]['native_table']['rows'][1][1]=='08'
        return json.dumps({'title':'合成统计试卷','questions':[{'number':'1','question_spans':[{'block_id':b['id']} for b in payload['blocks'][1:]]}],'notes':[]}),None
    monkeypatch.setattr(worker,'generate',extract);worker.run_one_knowledge();r=get(client,r)
    assert r['status']=='completed',r['error'];return r,doc


def test_native_table_formula_blank_and_leading_zero_survive_extraction_final_and_research(client,monkeypatch):
    r,doc=native_exam(client,monkeypatch);q=r['payload']['questions'][0]
    assert len(q['tables'])==1 and '人数' not in q['question_text']
    t=q['tables'][0];assert t['rows'][1][1]=='08' and t['rows'][3][1]==''
    assert t['rows'][2][1]==r'\(\frac{1}{x}\)'
    original=copy.deepcopy(r['source']);strip=[{k:v for k,v in b.items() if k!='native_table'} for b in original['blocks']]
    assert original['fingerprint']==digest({'document_id':doc,'original_hash':original['original_hash'],'blocks':strip})
    b=copy.deepcopy(r['payload']);b['questions'][0]['tables'][0]['rows'][1][1]='09'
    revised=save(client,r,b);assert revised.status_code==200,revised.text
    fixed=final(client,revised.json());assert fixed.status_code==201,fixed.text
    v=fixed.json()['versions'][0];f=client.get('/api/exam-extraction-versions/'+v['id']).json()['snapshot']
    assert f['questions'][0]['tables'][0]['rows'][1][1]=='09'
    qid=f['questions'][0]['research_question_id']
    # Research question detail is exposed by the collection.
    question=next(x for x in client.get('/api/research/questions').json() if x['id']==qid)
    assert question['payload']['tables'][0]['rows'][3][1]==''
    packet=safe_question(question['payload']);assert packet['tables'][0]['rows'][1][1]=='09'
    assert 'reference_answer' not in packet and 'table-test-secret' not in json.dumps(packet)
    assert client.get('/api/corpus/bank/'+qid).json()['question']['tables']==packet['tables']
    url='/api/exam-extraction-versions/'+v['id']+'/download';saved=client.get(url).content
    fork=client.post('/api/exam-extraction-versions/'+v['id']+'/revise').json()
    body=copy.deepcopy(fork['payload']);body['questions'][0]['tables'][0]['rows'][1][1]='10'
    changed=save(client,fork,body);assert changed.status_code==200
    assert save(client,fork,body).status_code==409
    assert final(client,changed.json()).status_code==201
    assert client.get(url).content==saved
    latest=next(x for x in client.get('/api/research/questions').json() if x['id']==qid)
    assert latest['revision']>question['revision'] and latest['payload']['tables'][0]['rows'][1][1]=='10'


def test_table_html_is_real_safe_math_and_duplicate_detection_uses_data():
    t=DataTable(key='t',caption='<script>caption</script>',rows=[['范围','人数'],[r'\(\frac{1}{x}\)',''],['<img src=x onerror=alert(1)>','08']]).model_dump()
    output=table_html([t]);assert '<table' in output and '<thead>' in output and '<mfrac>' in output
    assert '<script>' not in output and '<img src=x' not in output and '&lt;img' in output
    q={'statement':'根据表回答。','tables':[t]};changed=copy.deepcopy(q);changed['tables'][0]['rows'][2][1]='09'
    assert fingerprint(q)!=fingerprint(changed)
    renamed=copy.deepcopy(q);renamed['tables'][0]['key']='another'
    assert fingerprint(q)==fingerprint(renamed)


@pytest.mark.parametrize('table',[{'key':'t','rows':[['1','2'],['3']]},{'key':'t','header_rows':3,'rows':[['1','2']]},{'key':'t','rows':[['1']*21]}])
def test_invalid_rectangles_are_rejected_without_guessing(table):
    with pytest.raises(ValueError):DataTable.model_validate(table)


def test_tab_rows_preserve_empty_cells_and_do_not_guess_spaced_columns():
    text='1. 根据表回答\n组别\t人数\n甲\t\n乙\t08\n求总数。'
    remaining,tables=tabular_text(text)
    assert tables[0]['rows']==[['组别','人数'],['甲',''],['乙','08']]
    assert remaining=='1. 根据表回答\n求总数。'
    spaced='1. 根据表回答\n组别  人数\n甲  8\n乙  9'
    assert tabular_text(spaced)==(spaced,[])


def suggestion(client,r,text=None,tables=None):
    q=r['payload']['questions'][0]
    return client.post('/api/exam-extractions/'+r['id']+'/table-suggestions',json={'revision':r['revision'],'question_key':q['key'],'text':text or q['question_text'],'tables':tables or q.get('tables',[])})


def test_ai_suggestion_preserves_parent_until_adoption_and_rejects_stale_task(client,monkeypatch):
    r,_,_=plain_exam(client,monkeypatch,False);text='根据下表回答。\n类别\t人数\n甲\t8\n乙\t\n求已知人数。'
    parent_before=get(client,r)
    def table_model(config,system,payload,tokens):
        assert payload['current_text']==text and payload['limitations'] and '不补0' in system
        return json.dumps({'tables':[{'key':'t','rows':[['类别','人数'],['甲','8'],['乙','']]}],'remove_fragments':['类别\t人数\n甲\t8\n乙\t\n'],'uncertainties':['乙组人数原文为空，未计算']}),None
    monkeypatch.setattr(worker,'generate',table_model)
    task=suggestion(client,r,text);assert task.status_code==201,task.text
    assert suggestion(client,r,text).json()['id']==task.json()['id']
    worker.run_one_knowledge();result=client.get('/api/exam-table-suggestions/'+task.json()['id']).json()
    assert result['status']=='completed' and result['result']['tables'][0]['rows'][2][1]==''
    assert result['result']['suggested_text']=='根据下表回答。\n求已知人数。'
    assert get(client,r)['payload']==parent_before['payload']
    body=copy.deepcopy(r['payload']);body['questions'][0].update(question_text=result['result']['suggested_text'],tables=result['result']['tables'])
    changed=save(client,r,body);assert changed.status_code==200,changed.text
    assert client.get('/api/exam-table-suggestions/'+task.json()['id']).json()['stale']
    assert final(client,changed.json()).status_code==201


def test_research_question_only_table_edit_revokes_confirmation(client,monkeypatch):
    r,_=native_exam(client,monkeypatch);fixed=final(client,r).json();f=client.get('/api/exam-extraction-versions/'+fixed['versions'][0]['id']).json()['snapshot'];qid=f['questions'][0]['research_question_id']
    current=next(q for q in client.get('/api/research/questions').json() if q['id']==qid)
    from mathlet.research_models import QuestionBody
    b={k:current['payload'][k] for k in QuestionBody.model_fields if k in current['payload']};b['tables'][0]['rows'][1][1]='11'
    changed=client.put('/api/research/questions/'+qid,json={**b,'revision':current['revision']})
    assert changed.status_code==200,changed.text
    assert not changed.json()['confirmed']
    assert changed.json()['payload']['tables'][0]['rows'][1][1]=='11'


def test_import_remaps_table_sources_to_reuploaded_original(client,monkeypatch):
    r,_=native_exam(client,monkeypatch);fixed=final(client,r).json();vid=fixed['versions'][0]['id']
    snapshot=client.get('/api/exam-extraction-versions/'+vid).json()['snapshot']
    # Simulate a portable file from another workbench, without a colliding local version.
    snapshot['version_id']='external-table-version'
    upload=client.post('/api/documents?category=exam',files={'file':('copy.docx',native_file())});run_one();doc=upload.json()['id']
    imported=client.post('/api/documents/'+doc+'/exam-extractions/import',json={'payload':snapshot})
    assert imported.status_code==201,imported.text
    result=imported.json()['extraction'];t=result['payload']['questions'][0]['tables'][0]
    assert t['rows']==snapshot['questions'][0]['tables'][0]['rows']
    assert set(t['source_block_ids'])<=set(b['id'] for b in result['source']['blocks'])
    assert t['source_block_ids']!=snapshot['questions'][0]['tables'][0]['source_block_ids']


def test_parent_save_during_ai_table_generation_rejects_result(client,monkeypatch):
    r,_,_=plain_exam(client,monkeypatch,False)
    def generate(config,system,payload,tokens):
        body=copy.deepcopy(r['payload']);body['questions'][0]['question_text']+=' 教师修订。'
        assert save(client,r,body).status_code==200
        return json.dumps({'tables':[],'remove_fragments':[],'uncertainties':[]}),None
    monkeypatch.setattr(worker,'generate',generate);task=suggestion(client,r).json();worker.run_one_knowledge()
    result=client.get('/api/exam-table-suggestions/'+task['id']).json()
    assert result['stale'] and result['status']=='failed' and result['result'] is None
    assert get(client,r)['payload']['questions'][0]['question_text'].endswith('教师修订。')
