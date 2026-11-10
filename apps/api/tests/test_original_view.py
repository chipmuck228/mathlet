import io
import subprocess
from pathlib import Path
from pypdf import PdfWriter
import pytest
from fastapi.testclient import TestClient
from mathlet.main import app
from mathlet.worker import run_one
from mathlet.db import connect, init_db
from mathlet import original_view
from test_workflow import docx_bytes

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('MATHLET_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        yield client

def upload(client):
    doc = client.post('/api/documents', files={'file': ('test.docx', docx_bytes())}).json()['id']
    assert run_one()
    return doc

def test_view_jobs_fail_independently_and_retry_without_changing_sources(client, monkeypatch):
    doc = upload(client)
    original_bytes = client.get(f'/api/documents/{doc}/original').content
    before = client.get(f'/api/documents/{doc}/blocks').json()
    monkeypatch.setattr(original_view, 'converter', lambda: None)
    assert run_one()
    view = client.get(f'/api/documents/{doc}/original-view').json()
    assert view['status'] == 'failed' and 'LibreOffice' in view['message']
    assert client.get('/api/documents').json()[0]['status'] == 'ready'
    assert client.get(f'/api/documents/{doc}/blocks').json() == before
    with connect() as c:
        failed_job = c.execute("SELECT id FROM jobs WHERE kind='original_view' AND status='failed'").fetchone()[0]
    assert client.post(f'/api/jobs/{failed_job}/retry').status_code == 200
    assert client.get('/api/documents').json()[0]['status'] == 'ready'
    assert client.post(f'/api/documents/{doc}/original-view').status_code == 202
    client.post(f'/api/documents/{doc}/original-view')
    with connect() as c:
        assert c.execute("SELECT count(*) FROM jobs WHERE kind='original_view' AND status='queued'").fetchone()[0] == 1
    monkeypatch.setattr(original_view, 'converter', lambda: '/fake/soffice')
    def convert(args, **kwargs):
        out = Path(args[args.index('--outdir') + 1]) / 'original.pdf'
        writer = PdfWriter(); writer.add_blank_page(width=300, height=400)
        with out.open('wb') as f: writer.write(f)
        assert kwargs['timeout'] == 120
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(original_view.subprocess, 'run', convert)
    assert run_one()
    assert client.get(f'/api/documents/{doc}/original-view').json()['pages'] == 1
    response = client.get(f'/api/documents/{doc}/original-view.pdf')
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['content-disposition'] == 'inline'
    assert response.content.startswith(b'%PDF')
    assert client.get(f'/api/documents/{doc}/original').content == original_bytes
    block = before[0]
    assert block['original_text'] == block['text']
    edited = client.put(f"/api/blocks/{block['id']}", json={'text': '修正正文', 'revision': 1, 'verified': False}).json()
    assert edited['original_text'] == block['text']
    assert client.get(f'/api/documents/{doc}/original-view.pdf').content == response.content
    old_view = client.get(f'/api/documents/{doc}/original-view').json()
    assert client.post(f'/api/documents/{doc}/original-view').json()['status'] == 'ready'
    for _ in range(2):
        queued = client.post(f'/api/documents/{doc}/original-view?regenerate=true').json()
        assert queued['status'] == 'queued' and queued['available']
    with connect() as c:
        assert c.execute("SELECT count(*) FROM jobs WHERE kind='original_view' AND status='queued'").fetchone()[0] == 1
    assert run_one()
    new_view = client.get(f'/api/documents/{doc}/original-view').json()
    assert new_view['status'] == 'ready' and new_view['version'] != old_view['version']
    saved_bytes = client.get(f'/api/documents/{doc}/original-view.pdf').content
    monkeypatch.setattr(original_view, 'converter', lambda: None)
    client.post(f'/api/documents/{doc}/original-view?regenerate=true')
    assert run_one()
    failed = client.get(f'/api/documents/{doc}/original-view').json()
    assert failed['status'] == 'failed' and failed['available']
    assert failed['version'] == new_view['version']
    assert client.get(f'/api/documents/{doc}/original-view.pdf').content == saved_bytes
    assert client.get(f'/api/documents/{doc}/blocks').json()[0] == edited
    assert client.get(f'/api/documents/{doc}/original').content == original_bytes

def test_pdf_is_served_unchanged_and_unknown_doc_rejected(client):
    stream=io.BytesIO(); writer=PdfWriter(); writer.add_blank_page(width=300,height=400); writer.write(stream)
    raw=stream.getvalue()
    doc=client.post('/api/documents',files={'file':('test.pdf',raw)}).json()['id']
    status = client.get(f'/api/documents/{doc}/original-view').json()
    assert status['status'] == 'ready' and status['pages'] == 1 and not status['converted']
    assert client.get(f'/api/documents/{doc}/original-view.pdf').content == raw
    assert client.get('/api/documents/missing/original-view').status_code == 404
    assert client.post('/api/documents/missing/original-view').status_code == 404

def test_migration_does_not_invent_initial_text(client):
    doc=upload(client)
    with connect() as c:
        c.execute('ALTER TABLE blocks DROP COLUMN original_text')
        c.execute("UPDATE blocks SET text='旧人工修订'")
    init_db(); init_db()
    block=client.get(f'/api/documents/{doc}/blocks').json()[0]
    assert block['text']=='旧人工修订' and block['original_text'] is None
