import json
import re
from datetime import datetime,timedelta,timezone
from test_review_range import client,document,change
from mathlet import source_review
from mathlet.db import data_dir,connect,init_db


def save(client,doc,review,changes=()):
    return client.put(f'/api/documents/{doc}/source-review',json={'review_revision':review['revision'] if review else None,'changes':list(changes)})


def test_one_stable_file_preserves_review_states_and_reconfirmation_is_not_a_content_change(client,monkeypatch):
    doc,blocks=document(client);moment=datetime(2026,11,13,21,22,23,456789,tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(source_review,'review_time',lambda:moment)
    response=save(client,doc,None,[change(blocks[0],text=r'\(x^{2} 未转换提示【未转换公式】',verified=True)])
    assert response.status_code==200,response.text
    data=response.json();name=data['review']['filename']
    assert name=='2026-11-13_21-22-23-456789.json' and data['file_saved']
    path=data_dir()/'source-reviews'/name;assert path.is_file()
    stored=json.loads(path.read_text());assert stored['blocks'][0]['verified'] and stored['blocks'][0]['text']==data['blocks'][0]['text']
    assert [b['verified'] for b in data['blocks']]==[True,False,False]
    original_revision=data['blocks'][0]['revision'];first_created=data['review']['created_at']
    monkeypatch.setattr(source_review,'review_time',lambda:moment+timedelta(days=1))
    result=save(client,doc,data['review'],[change(data['blocks'][0],verified=True)]).json()
    assert result['review']['filename']==name and result['review']['created_at']==first_created
    assert result['review']['updated_at']!=data['review']['updated_at']
    assert result['blocks'][0]['revision']==original_revision
    assert len(list((data_dir()/'source-reviews').glob('*.json')))==1
    assert json.loads(path.read_text())['review']['revision']==result['review']['revision']
    init_db();assert client.get(f'/api/documents/{doc}/source-review').json()['blocks']==result['blocks']
    listed=client.get('/api/source-reviews').json();assert listed[0]['filename']==name and listed[0]['document_id']==doc


def test_file_download_and_open_restore_content_and_marks_keep_the_original_and_filename(client):
    doc,blocks=document(client);original=(data_dir()/'documents'/doc/'original.docx').read_bytes()
    first=save(client,doc,None,[change(blocks[0],text='教师第一次修订',verified=True)]).json()
    exported=client.get(f'/api/documents/{doc}/source-review/download')
    payload=exported.json();assert first['review']['filename'] in exported.headers['content-disposition']
    second=save(client,doc,first['review'],[change(first['blocks'][0],text='教师第二次修订',verified=False)]).json()
    opened=client.post(f'/api/documents/{doc}/source-review/open',json={'review_revision':second['review']['revision'],'payload':payload})
    assert opened.status_code==200,opened.text
    data=opened.json();assert data['blocks'][0]['text']=='教师第一次修订' and data['blocks'][0]['verified']
    assert data['review']['filename']==first['review']['filename']
    assert (data_dir()/'documents'/doc/'original.docx').read_bytes()==original
    assert data['blocks'][0]['original_text']==blocks[0]['original_text']
    with connect() as c:assert c.execute('SELECT count(*) FROM source_review_history WHERE document_id=?',(doc,)).fetchone()[0]>=2


def test_stale_record_and_last_block_conflicts_do_not_partially_overwrite(client):
    doc,blocks=document(client);first=save(client,doc,None).json();path=data_dir()/'source-reviews'/first['review']['filename'];before=path.read_bytes()
    stale=change(blocks[1],text='过时');stale['revision']=0
    response=save(client,doc,first['review'],[change(blocks[0],text='不应写入'),stale])
    assert response.status_code==409
    assert client.get(f'/api/documents/{doc}/source-review').json()['blocks']==blocks and path.read_bytes()==before
    good=save(client,doc,first['review'],[change(blocks[0],text='新版本',verified=True)]).json()
    assert save(client,doc,first['review'],[change(blocks[2],text='旧窗口内容')]).status_code==409
    assert client.get(f'/api/documents/{doc}/source-review').json()['blocks']==good['blocks']


def test_import_rejects_wrong_original_or_incomplete_mapping_without_math_checks(client):
    doc,blocks=document(client);saved=save(client,doc,None).json();payload=client.get(f'/api/documents/{doc}/source-review/download').json()
    payload['document']['source_sha256']='wrong'
    assert client.post(f'/api/documents/{doc}/source-review/open',json={'review_revision':saved['review']['revision'],'payload':payload}).status_code==422
    payload=client.get(f'/api/documents/{doc}/source-review/download').json();payload['blocks'].pop()
    assert client.post(f'/api/documents/{doc}/source-review/open',json={'review_revision':saved['review']['revision'],'payload':payload}).status_code==422
    assert client.get(f'/api/documents/{doc}/blocks').json()==blocks


def test_cache_write_failure_reports_saved_database_and_can_be_recovered(client,monkeypatch):
    doc,blocks=document(client)
    original=source_review.materialize
    def fail(_):raise OSError('磁盘不可写')
    monkeypatch.setattr(source_review,'materialize',fail)
    response=save(client,doc,None,[change(blocks[0],text='应保留的正文',verified=True)])
    assert response.status_code==200,response.text
    data=response.json();assert data['file_saved'] is False and data['file_error']
    assert client.get(f'/api/documents/{doc}/source-review/download').json()['blocks'][0]['text']=='应保留的正文'
    monkeypatch.setattr(source_review,'materialize',original)
    recovered=client.get(f'/api/documents/{doc}/source-review').json()
    assert recovered['file_saved'] and (data_dir()/'source-reviews'/data['review']['filename']).is_file()


def test_timestamp_collisions_are_distinct_and_import_filename_cannot_escape_folder(client,monkeypatch):
    moment=datetime(2026,11,13,0,0,0,tzinfo=timezone(timedelta(hours=8)));monkeypatch.setattr(source_review,'review_time',lambda:moment)
    first,_=document(client);second,_=document(client)
    a=save(client,first,None).json();b=save(client,second,None).json()
    assert a['review']['filename']!=b['review']['filename']
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}\.json',b['review']['filename'])
    third,blocks=document(client)
    with connect() as c:doc=dict(c.execute('SELECT * FROM documents WHERE id=?',(third,)).fetchone())
    payload={'schema_version':1,'review':{'filename':'../../escape.json','created_at':moment.isoformat()},'document':doc|{'source_sha256':source_review.source_identity(doc)},'blocks':blocks}
    response=client.post(f'/api/documents/{third}/source-review/open',json={'payload':payload,'review_revision':None})
    assert response.status_code==422 and client.get(f'/api/documents/{third}/source-review').json()['review'] is None


def test_upgrade_backfills_existing_reviewed_text_without_changing_its_revision(client):
    doc,blocks=document(client)
    with connect() as c:c.execute('UPDATE blocks SET verified=1 WHERE id=?',(blocks[0]['id'],))
    init_db();opened=client.get(f'/api/documents/{doc}/source-review').json()
    assert opened['review'] and opened['blocks'][0]['verified']
    assert opened['blocks'][0]['revision']==blocks[0]['revision']
    exported=client.get(f'/api/documents/{doc}/source-review/download').json()
    assert exported['blocks'][0]['checked_at'] is None
