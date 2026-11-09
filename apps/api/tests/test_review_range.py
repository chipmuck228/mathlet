import io
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from mathlet.main import app
from mathlet.worker import run_one


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATHLET_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def document(client):
    data = io.BytesIO()
    with ZipFile(data, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
                   ''.join(f'<w:p><w:r><w:t>{s}</w:t></w:r></w:p>' for s in ['题目一', '题目二', '题目三']) + '</w:body></w:document>')
    result = client.post('/api/documents', files={'file': ('paper.docx', data.getvalue())}).json()
    assert run_one()
    blocks = client.get(f"/api/documents/{result['id']}/blocks").json()
    return result['id'], blocks


def change(block, text=None, verified=False):
    return {"id": block['id'], "revision": block['revision'], "text": text or block['text'], "verified": verified}


def test_range_save_is_atomic_on_last_block_conflict(client):
    doc, blocks = document(client)
    endpoint = f'/api/documents/{doc}/blocks/review'
    stale = change(blocks[1]); stale['revision'] = 0
    r = client.put(endpoint, json={'changes': [change(blocks[0], '修正一'), stale]})
    assert r.status_code == 409
    assert client.get(f'/api/documents/{doc}/blocks').json() == blocks
    assert client.put(endpoint, json={'changes': [change(blocks[0]), change(blocks[0])]}).status_code == 422
    other, other_blocks = document(client)
    assert client.put(endpoint, json={'changes': [change(blocks[0]), change(other_blocks[0])]}).status_code == 422
    assert client.get(f'/api/documents/{doc}/blocks').json() == blocks


def test_only_selected_range_confirmed_and_saved_edits_remain_unverified(client):
    doc, blocks = document(client)
    endpoint = f'/api/documents/{doc}/blocks/review'
    confirmed = client.put(endpoint, json={'changes': [change(blocks[0], verified=True), change(blocks[1], verified=True)]})
    assert confirmed.status_code == 200
    saved = client.get(f'/api/documents/{doc}/blocks').json()
    assert [b['verified'] for b in saved] == [True, True, False]
    r = client.put(endpoint, json={'changes': [change(saved[0], '再次修正')]})
    assert r.status_code == 200
    saved = client.get(f'/api/documents/{doc}/blocks').json()
    assert [b['verified'] for b in saved] == [False, True, False]
    assert saved[1]['revision'] == 2 and saved[2]['revision'] == 1


def test_range_invalidates_dependent_draft_once_and_preserves_release(client):
    doc, blocks = document(client)
    endpoint = f'/api/documents/{doc}/blocks/review'
    client.put(endpoint, json={'changes': [change(b, verified=True) for b in blocks]})
    draft = client.post('/api/drafts', json={'title': '练习', 'source_ids': [b['id'] for b in blocks]}).json()
    path = '/api/drafts/' + draft['id']
    client.post(path + '/approve', json={'revision': 1, 'reviewer': '教师', 'confirmed': True})
    release = client.post(path + '/releases', json={'revision': 1}).json()
    download = '/api/releases/' + release['id'] + '/download'
    snapshot = client.get(download).text
    current = client.get(f'/api/documents/{doc}/blocks').json()
    r = client.put(endpoint, json={'changes': [change(current[0], '新一'), change(current[1], '新二')]})
    assert r.status_code == 200
    changed = client.get('/api/drafts').json()[0]
    assert changed['revision'] == 2 and not changed['approved']
    assert client.get(download).text == snapshot
