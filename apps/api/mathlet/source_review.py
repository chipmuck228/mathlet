"""Human transcription review with one stable, reloadable result file per original."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from filelock import FileLock
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from .db import connect, data_dir, block_json, now, uid

router=APIRouter(prefix='/api',tags=['source review files'])


def init_source_review(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS source_reviews (
      document_id TEXT PRIMARY KEY REFERENCES documents(id), filename TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL,
      checked_at TEXT NOT NULL DEFAULT '{}', snapshot TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS source_review_history (
      id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
      revision INTEGER NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL
    );
    ''')
    # Preserve existing human-reviewed blocks when upgrading; do not invent past check timestamps.
    for document in c.execute("SELECT id FROM documents WHERE status='ready' AND EXISTS(SELECT 1 FROM blocks WHERE document_id=documents.id AND verified=1) AND NOT EXISTS(SELECT 1 FROM source_reviews WHERE document_id=documents.id)").fetchall():
        snapshot_review(c,document['id'])


def review_time():return datetime.now(timezone(timedelta(hours=8)))
def filename_at(value):return value.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d_%H-%M-%S-%f.json')


def source_identity(document):
    path=data_dir()/'documents'/document['id']/('original.'+document['kind'])
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def record_json(value):
    if value is None:return None
    value=dict(value)
    return {k:value[k] for k in ['document_id','filename','created_at','updated_at','revision']}


def snapshot_review(c,document_id,changes=(),imported=None):
    """Called in the same transaction as text/status edits. No mathematical validation."""
    document=c.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
    if not document:raise HTTPException(404,'原始资料不存在')
    old=c.execute('SELECT * FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
    stamp=review_time()
    checked=json.loads(old['checked_at']) if old else {}
    if old:
        filename=old['filename'];created=old['created_at'];rev=old['revision']+1
        c.execute('INSERT INTO source_review_history VALUES(?,?,?,?,?)',(uid(),document_id,old['revision'],old['snapshot'],now()))
    else:
        if imported:
            try:stamp_created=datetime.fromisoformat(imported['created_at'])
            except ValueError:raise HTTPException(422,'核对文件的创建时间格式无效') from None
            if stamp_created.tzinfo is None or imported['filename']!=filename_at(stamp_created):raise HTTPException(422,'核对文件名称与首次创建时间不匹配')
        else:stamp_created=stamp
        filename=filename_at(stamp_created)
        if imported and c.execute('SELECT 1 FROM source_reviews WHERE filename=?',(filename,)).fetchone():raise HTTPException(409,'此文件名已被其他原始资料使用')
        while c.execute('SELECT 1 FROM source_reviews WHERE filename=?',(filename,)).fetchone():
            stamp_created+=timedelta(microseconds=1);filename=filename_at(stamp_created)
        created=stamp_created.isoformat();rev=1
    for key,body in changes:
        if body.verified:checked[key]=stamp.isoformat()
        else:checked.pop(key,None)
    blocks=[dict(r) for r in c.execute('SELECT * FROM blocks WHERE document_id=? ORDER BY ordinal',(document_id,))]
    snapshot={'schema_version':1,'review':{'filename':filename,'created_at':created,'updated_at':stamp.isoformat(),'revision':rev},
              'document':{k:document[k] for k in ['id','name','kind','category']}|{'source_sha256':source_identity(document)},
              'blocks':[{'id':b['id'],'ordinal':b['ordinal'],'locator':b['locator'],'text':b['text'],'verified':bool(b['verified']),'revision':b['revision'],'assets':json.loads(b['assets']),'checked_at':checked.get(b['id'])} for b in blocks]}
    c.execute('INSERT INTO source_reviews(document_id,filename,created_at,updated_at,revision,checked_at,snapshot) VALUES(?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET updated_at=excluded.updated_at,revision=excluded.revision,checked_at=excluded.checked_at,snapshot=excluded.snapshot',
              (document_id,filename,created,stamp.isoformat(),rev,json.dumps(checked,ensure_ascii=False),json.dumps(snapshot,ensure_ascii=False)))
    return snapshot


def materialize(document_id):
    """DB snapshot is authoritative; atomically refresh the same named local JSON cache."""
    with FileLock(str(data_dir()/'source-review-files.lock')):
        with connect() as c:value=c.execute('SELECT * FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
        if not value:return
        folder=data_dir()/'source-reviews';folder.mkdir(exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',dir=folder,delete=False,encoding='utf-8') as f:
                temporary=Path(f.name);os.chmod(f.name,0o600)
                json.dump(json.loads(value['snapshot']),f,ensure_ascii=False,indent=2);f.write('\n')
            temporary.replace(folder/value['filename'])
        finally:
            if temporary:temporary.unlink(missing_ok=True)


def result(document_id):
    with connect() as c:
        document=c.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if not document:raise HTTPException(404,'原始资料不存在')
        record=c.execute('SELECT * FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
        value={'review':record_json(record),'blocks':[block_json(r) for r in c.execute('SELECT * FROM blocks WHERE document_id=? ORDER BY ordinal',(document_id,))]}
    if record:
        try:materialize(document_id);value['file_saved']=True
        except OSError:value.update(file_saved=False,file_error='核对结果已保存在数据库，本地JSON文件暂未写入。可重新保存或下载核对文件。')
    return value


@router.get('/source-reviews')
def saved_reviews():
    with connect() as c:
        return [record_json(x)|{'document_name':x['document_name']} for x in c.execute('SELECT source_reviews.*,documents.name AS document_name FROM source_reviews JOIN documents ON documents.id=source_reviews.document_id ORDER BY source_reviews.created_at DESC')]

@router.get('/documents/{document_id}/source-review')
def load(document_id:str):return result(document_id)

class Change(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str
    revision:int
    text:str=Field(max_length=150000)
    verified:StrictBool
class Save(BaseModel):
    review_revision:int|None=None
    changes:list[Change]=Field(default_factory=list,max_length=2000)


def check_revision(c,document_id,expected):
    old=c.execute('SELECT revision FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
    if (old['revision'] if old else None)!=expected:raise HTTPException(409,'核对记录已由其他页面更新；当前输入保留，请重新打开记录后再保存')

@router.put('/documents/{document_id}/source-review')
def save(document_id:str,body:Save):
    from .main import apply_block_edits
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');document=c.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if not document:raise HTTPException(404,'原始资料不存在')
        if document['status']!='ready':raise HTTPException(409,'资料尚未读取完成')
        check_revision(c,document_id,body.review_revision)
        if len({x.id for x in body.changes})!=len(body.changes):raise HTTPException(422,'内容块重复')
        for item in body.changes:
            block=c.execute('SELECT document_id FROM blocks WHERE id=?',(item.id,)).fetchone()
            if not block or block['document_id']!=document_id:raise HTTPException(422,'内容块不属于当前原始资料')
        if body.changes:apply_block_edits(c,[(x.id,x) for x in body.changes])
        else:snapshot_review(c,document_id)
    return result(document_id)


@router.get('/documents/{document_id}/source-review/download')
def download(document_id:str):
    with connect() as c:record=c.execute('SELECT * FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
    if not record:raise HTTPException(404,'尚未保存核对文件')
    return Response(json.dumps(json.loads(record['snapshot']),ensure_ascii=False,indent=2)+'\n',media_type='application/json',headers={'Content-Disposition':f'attachment; filename="{record["filename"]}"'})

class ImportedBlock(BaseModel):
    id:str
    text:str=Field(max_length=150000)
    verified:StrictBool
    checked_at:str|None=None
class ImportRecord(BaseModel):
    schema_version:Literal[1]
    review:dict
    document:dict
    blocks:list[ImportedBlock]=Field(min_length=1,max_length=2000)
class OpenFile(BaseModel):
    review_revision:int|None=None
    payload:ImportRecord

@router.post('/documents/{document_id}/source-review/open')
def open_file(document_id:str,body:OpenFile):
    from .main import apply_block_edits
    payload=body.payload
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');document=c.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if not document:raise HTTPException(404,'请先恢复此核对文件对应的原始资料')
        if document['status']!='ready':raise HTTPException(409,'原始资料尚未读取完成')
        check_revision(c,document_id,body.review_revision)
        if payload.document.get('id')!=document_id or payload.document.get('kind')!=document['kind'] or not payload.document.get('source_sha256') or payload.document['source_sha256']!=source_identity(document):raise HTTPException(422,'核对文件与所选原始资料不对应，请选择对应原件')
        blocks={r['id']:r for r in c.execute('SELECT * FROM blocks WHERE document_id=?',(document_id,))}
        if len({x.id for x in payload.blocks})!=len(payload.blocks) or {x.id for x in payload.blocks}!=blocks.keys():raise HTTPException(422,'核对文件的内容块与本地原件不对应')
        old=c.execute('SELECT * FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
        if not old:
            if not isinstance(payload.review.get('created_at'),str) or not isinstance(payload.review.get('filename'),str):raise HTTPException(422,'核对文件缺少首次创建时间和名称')
            # Validate/establish imported first-created identity before applying changes; all one transaction.
            snapshot_review(c,document_id,imported=payload.review)
        changes=[(x.id,Change(id=x.id,revision=blocks[x.id]['revision'],text=x.text,verified=x.verified)) for x in payload.blocks]
        apply_block_edits(c,changes)
        record=c.execute('SELECT snapshot FROM source_reviews WHERE document_id=?',(document_id,)).fetchone()
        snapshot=json.loads(record['snapshot']);checks={x.id:x.checked_at for x in payload.blocks if x.verified and x.checked_at}
        for block in snapshot['blocks']:block['checked_at']=checks.get(block['id'])
        c.execute('UPDATE source_reviews SET checked_at=?,snapshot=? WHERE document_id=?',(json.dumps(checks,ensure_ascii=False),json.dumps(snapshot,ensure_ascii=False),document_id))
    return result(document_id)
