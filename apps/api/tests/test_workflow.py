import io
import json
from zipfile import ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from mathlet.db import connect, init_db
from mathlet.main import app
from mathlet.worker import run_one


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATHLET_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def docx_bytes():
    stream = io.BytesIO()
    with ZipFile(stream, "w") as z:
        z.writestr(ZipInfo("word/document.xml", date_time=(2000, 1, 1, 0, 0, 0)), '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p><w:r><w:t>1. 点在函数图像上：</w:t></w:r><m:oMath><m:f><m:num><m:r><m:t>k</m:t></m:r></m:num><m:den><m:r><m:t>x</m:t></m:r></m:den></m:f></m:oMath></w:p></w:body></w:document>''')
    return stream.getvalue()


def imported(client):
    result = client.post("/api/documents?category=mock", files={"file": ("样例.docx", docx_bytes())})
    assert result.status_code == 201, result.text
    document = result.json()["id"]
    assert run_one()
    blocks = client.get(f"/api/documents/{document}/blocks").json()
    assert len(blocks) == 1
    assert "<mfrac>" in blocks[0]["preview"]
    return document, blocks[0]


def verified(client, block):
    response = client.put(f"/api/blocks/{block['id']}", json={"text": "点满足 y=k/x，x≠0。", "verified": True, "revision": block["revision"]})
    assert response.status_code == 200
    return response.json()


def test_real_workflow_release_immutability_and_review_invalidation(client):
    document, block = imported(client)
    blocked = client.post("/api/drafts", json={"title": "函数连接", "source_ids": [block["id"]]})
    assert blocked.status_code == 409
    block = verified(client, block)
    draft = client.post("/api/drafts", json={"title": "函数连接", "source_ids": [block["id"]]}).json()
    path = f"/api/drafts/{draft['id']}"
    assert client.post(path + "/releases", json={"revision": 1}).status_code == 409
    draft = client.put(path, json={"title": "函数连接", "content": "同一个点满足表达式；检查自变量范围。", "revision": 1}).json()
    assert draft["revision"] == 2
    assert client.put(path, json={"title": "过期", "content": "不能覆盖", "revision": 1}).status_code == 409
    assert client.post(path + "/comments", json={"revision": 2, "author": "教师A", "body": "请核对定义范围"}).status_code == 201
    assert len(client.get(path + "/comments").json()) == 1
    assert client.post(path + "/approve", json={"revision": 2, "reviewer": "教师A", "confirmed": False}).status_code == 422
    approved = client.post(path + "/approve", json={"revision": 2, "reviewer": "教师A", "confirmed": True}).json()
    assert approved["approved"]
    result = client.post(path + "/releases", json={"revision": 2})
    assert result.status_code == 201, result.text
    release = result.json()["id"]
    download = f"/api/releases/{release}/download"
    snapshot = client.get(download).text
    assert "教师A" in snapshot
    verified(client, block)  # Source revision changes: approval must be invalidated.
    current = client.get("/api/drafts").json()[0]
    assert current["revision"] == 3 and not current["approved"]
    assert client.post(path + "/approve", json={"revision": 2, "reviewer": "教师A", "confirmed": True}).status_code == 409
    assert client.post(path + "/releases", json={"revision": 3}).status_code == 409
    assert client.get(download).text == snapshot
    assert client.get(f"/api/documents/{document}/original").content == docx_bytes()


def test_persistence_and_escaped_export(client):
    _, block = imported(client)
    verified(client, block)
    draft = client.post("/api/drafts", json={"title": "<script>bad</script>", "source_ids": [block["id"]]}).json()
    path = f"/api/drafts/{draft['id']}"
    client.put(path, json={"revision": 1, "title": "数学", "content": "<img src=x onerror=alert(1)>"})
    init_db()  # Reinitializing does not erase persisted records.
    assert len(client.get("/api/drafts").json()) == 1
    page = client.get(path + "/preview").text
    assert "&lt;img" in page and "<img src=x" not in page


def test_bad_file_is_failed_job_and_can_retry(client):
    r = client.post("/api/documents", files={"file": ("broken.docx", b"not zip")})
    assert r.status_code == 201
    assert run_one()
    jobs = client.get("/api/jobs").json()
    assert jobs[0]["status"] == "failed"
    assert client.post(f"/api/jobs/{r.json()['job_id']}/retry").status_code == 200
    assert client.post(f"/api/jobs/{r.json()['job_id']}/retry").status_code == 409


def test_local_origin_and_file_validation(client):
    assert client.post("/api/documents", files={"file": ("x.exe", b"x")}).status_code == 415
    assert client.post("/api/documents", files={"file": ("empty.pdf", b"")}).status_code == 400
    assert client.post("/api/documents", headers={"Origin": "https://unrelated.example"}, files={"file": ("x.docx", docx_bytes())}).status_code == 403
    assert client.get("/api/documents/../../assets/a.png").status_code == 404


def test_pdf_page_render_and_scan_warning(client):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO(); writer.write(buf)
    r = client.post("/api/documents", files={"file": ("scan.pdf", buf.getvalue())})
    assert run_one()
    blocks = client.get(f"/api/documents/{r.json()['id']}/blocks").json()
    assert len(blocks) == 1
    assert any("OCR" in w for w in blocks[0]["warnings"])
    image = client.get(f"/api/documents/{r.json()['id']}/assets/{blocks[0]['assets'][0]}")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")


def test_source_edit_optimistic_lock(client):
    _, block = imported(client)
    verified(client, block)
    stale = client.put(f"/api/blocks/{block['id']}", json={"text": "覆盖", "verified": True, "revision": 1})
    assert stale.status_code == 409
