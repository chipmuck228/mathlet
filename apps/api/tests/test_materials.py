"""Explicit categories, file deletion and source invalidation without altering releases."""
from test_knowledge import client
from test_workflow import docx_bytes
from mathlet.db import connect,data_dir
from mathlet.worker import run_one


def upload(client):
    r=client.post('/api/documents?category=mock',files={'file':('delete-test.docx',docx_bytes())});assert r.status_code==201,r.text;return r.json()


def test_upload_requires_recognized_category_before_creating_any_files(client):
    for query in ['', '?category=unknown','?category=','?category=invalid']:
        response=client.post('/api/documents'+query,files={'file':('sample.docx',docx_bytes())});assert response.status_code==422,response.text
    assert client.get('/api/documents').json()==[]
    for category in ['standard','textbook','exam','mock','term']:
        assert client.post('/api/documents?category='+category,files={'file':('sample.docx',docx_bytes())}).status_code==201


def test_delete_queued_original_cancels_jobs_and_removes_bytes_but_keeps_identity(client):
    r=upload(client);folder=data_dir()/'documents'/r['id'];assert folder.is_dir()
    deleted=client.delete('/api/documents/'+r['id']);assert deleted.status_code==200,deleted.text
    assert not folder.exists() and not client.get('/api/documents').json() and not client.get('/api/jobs').json()
    assert client.get('/api/documents/'+r['id']+'/original').status_code==410
    assert client.get('/api/documents/'+r['id']+'/original-view').status_code==410
    assert client.post('/api/jobs/'+r['job_id']+'/retry').status_code==410
    assert not run_one()
    assert client.delete('/api/documents/'+r['id']).status_code==200
    with connect() as c:assert c.execute('SELECT status FROM documents WHERE id=?',(r['id'],)).fetchone()[0]=='deleted'


def test_running_extraction_cannot_race_file_deletion_and_unknown_category_can_be_classified(client):
    r=upload(client)
    with connect() as c:
        c.execute("UPDATE jobs SET status='running' WHERE id=?",(r['job_id'],))
        c.execute("UPDATE documents SET category='unknown' WHERE id=?",(r['id'],))
    assert client.delete('/api/documents/'+r['id']).status_code==409
    assert (data_dir()/'documents'/r['id']).exists()
    updated=client.put('/api/documents/'+r['id']+'/category',json={'category':'standard'});assert updated.status_code==200,updated.text
    assert updated.json()['category']=='standard'
    assert client.put('/api/documents/'+r['id']+'/category',json={'category':'exam'}).status_code==409


def test_deleting_reviewed_original_invalidates_live_research_and_preserves_reader(client,monkeypatch):
    from test_review_units import complete,finish,get
    r,_,_,blocks=complete(client,monkeypatch);f=finish(client,r);assert f.status_code==201,f.text
    url='/api/review-units/versions/'+f.json()['id']+'/download';original=client.get(url).content
    with connect() as c:document=c.execute('SELECT document_id FROM blocks WHERE id=?',(blocks[0]['id'],)).fetchone()[0]
    result=client.delete('/api/documents/'+document);assert result.status_code==200,result.text
    assert get(client,r)['stale']
    assert client.get(url).content==original
    assert client.get('/api/documents/'+document+'/blocks').status_code==410
    b=blocks[0];assert client.put('/api/blocks/'+b['id'],json={'revision':3,'text':b['text'],'verified':True}).status_code==410
    assert client.get('/api/review-units/catalog').json()['studies']==[]


def test_deleting_plan_source_invalidates_confirmed_curriculum(client):
    from test_planning import import_plan
    plan=import_plan(client)
    confirmed=client.post('/api/plans/'+plan['id']+'/confirm',json={'revision':plan['revision'],'reviewer':'测试教师','acknowledged':True})
    assert confirmed.status_code==200 and confirmed.json()['confirmed']
    doc=plan['payload']['document_id'];response=client.delete('/api/documents/'+doc);assert response.status_code==200,response.text
    state=client.get('/api/plans').json()[0]
    assert state['stale_sources'] and not state['confirmed']
