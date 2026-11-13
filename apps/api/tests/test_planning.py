import io
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from mathlet.db import connect, init_db
from mathlet.main import app
from mathlet.worker import run_one


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATHLET_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def upload(client, lines, category="textbook"):
    from xml.sax.saxutils import escape
    buf = io.BytesIO()
    with ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
                   "".join('<w:p><w:r><w:t>' + escape(line) + '</w:t></w:r></w:p>' for line in lines) + '</w:body></w:document>')
    r = client.post(f"/api/documents?category={category}", files={"file": ("catalog.docx", buf.getvalue())})
    assert r.status_code == 201
    assert run_one()
    return r.json()["id"]


def import_plan(client):
    doc = upload(client, ["九年级上册", "第二十六章 二次函数", "26.1 二次函数的概念", "26.1.1 定义",
                          "第二十七章 反比例函数", "九年级下册", "第二十六章 反比例函数", "26.1 反比例函数"])
    r = client.post("/api/plans", json={"document_id": doc, "title": "初中数学"})
    assert r.status_code == 201, r.text
    return r.json()


def edit(client, plan, **updates):
    body = dict(plan["payload"], title=plan["title"], revision=plan["revision"])
    body.update(updates)
    return client.put("/api/plans/" + plan["id"], json=body)


def confirm(client, plan):
    return client.post(f"/api/plans/{plan['id']}/confirm", json={"revision": plan["revision"], "reviewer": "编辑", "acknowledged": True})


def test_tree_hierarchy_duplicate_and_no_false_coverage(client):
    plan = import_plan(client)
    nodes = plan["payload"]["nodes"]
    assert len(nodes) == 8
    assert nodes[2]["parent_id"] == nodes[1]["id"]
    assert nodes[3]["parent_id"] == nodes[2]["id"]
    assert nodes[6]["parent_id"] == nodes[5]["id"]
    assert any("重复" in w for w in plan["warnings"])
    assert plan["payload"]["requirements"] == [] and not plan["confirmed"]
    assert confirm(client, plan).json()["confirmed"]
    changed = edit(client, plan, notes="九下与九上编号不衔接，待核对")
    assert changed.status_code == 200
    assert not changed.json()["confirmed"]
    assert edit(client, plan).status_code == 409


def test_cycles_forged_source_and_unchecked_standards_rejected(client):
    plan = import_plan(client)
    nodes = plan["payload"]["nodes"]
    nodes[0]["parent_id"] = nodes[3]["id"]
    assert edit(client, plan).status_code == 422
    nodes[0]["parent_id"] = None
    nodes[0]["source_id"] = nodes[1]["source_id"]
    assert edit(client, plan).status_code == 422
    plan = client.get("/api/plans").json()[0]
    doc = upload(client, ["理解函数的概念。"], "standard")
    source = client.get(f"/api/documents/{doc}/blocks").json()[0]
    req = {"id": "r1", "source_id": source["id"], "text": source["text"], "unit_ids": []}
    assert edit(client, plan, requirements=[req]).status_code == 422
    r = client.put(f"/api/blocks/{source['id']}", json={"revision": source["revision"], "text": source["text"], "verified": True})
    assert r.status_code == 200
    result = edit(client, plan, requirements=[req])
    assert result.status_code == 200, result.text
    req["text"] = "不存在的课标要求"
    assert edit(client, result.json(), requirements=[req]).status_code == 422


def test_unit_draft_source_checks_idempotency_and_invalidation(client):
    plan = import_plan(client)
    node = plan["payload"]["nodes"][2]
    unit = {"id": "unit-1", "title": "函数与几何", "kind": "connection", "volume": "函数与图像", "goals": "说明连接依据", "node_ids": [node["id"]]}
    plan = edit(client, plan, units=[unit]).json()
    url = f"/api/plans/{plan['id']}/units/unit-1/draft"
    assert client.post(url, json={"revision": plan["revision"]}).status_code == 409
    plan = confirm(client, plan).json()
    assert client.post(url, json={"revision": plan["revision"]}).status_code == 409
    source = client.get(f"/api/documents/{plan['payload']['document_id']}/blocks").json()[2]
    assert client.put(f"/api/blocks/{source['id']}", json={"revision": source["revision"], "text": source["text"], "verified": True}).status_code == 200
    # A verification-only change must not make a structurally confirmed plan stale.
    assert client.get("/api/plans").json()[0]["confirmed"]
    draft = client.post(url, json={"revision": plan["revision"]}).json()
    assert "说明连接依据" in draft["content"]
    assert client.post(url, json={"revision": plan["revision"]}).json()["id"] == draft["id"]
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={"revision": 1, "reviewer": "教师", "confirmed": True}).json()["approved"]
    r = edit(client, plan, notes="调整说明")
    assert r.status_code == 200
    assert not client.get("/api/drafts").json()[0]["approved"]
    latest = r.json()
    block = client.get(f"/api/documents/{plan['payload']['document_id']}/blocks").json()[2]
    client.put(f"/api/blocks/{block['id']}", json={"revision": block["revision"], "text": block["text"] + "（修正）", "verified": False})
    current = client.get("/api/plans").json()[0]
    assert current["stale_sources"] and not current["confirmed"]
    assert confirm(client, latest).status_code == 409
    assert edit(client, latest).status_code == 409


def test_additive_schema_keeps_existing_records(client):
    plan = import_plan(client)
    init_db(); init_db()
    assert client.get("/api/plans").json()[0]["id"] == plan["id"]
    with connect() as c:
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 10
        assert c.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_plain_exam_is_not_silently_a_catalog(client):
    doc = upload(client, ["1. 解方程 x+1=2", "2. 求三角形面积"], "mock")
    assert client.post("/api/plans", json={"document_id": doc, "title": "错误目录"}).status_code == 422


def test_upgrade_from_database_without_planning_tables(client):
    doc = upload(client, ["七年级上册", "第一章 有理数", "1.1 正数和负数"])
    before = client.get(f"/api/documents/{doc}/blocks").json()
    with connect() as c:
        # Simulate the real 0.1 schema while retaining its existing content.
        c.execute("DROP TABLE plan_draft_links")
        c.execute("DROP TABLE plans")
        c.execute("DROP TABLE schema_migrations")
    init_db()
    assert client.get(f"/api/documents/{doc}/blocks").json() == before
    assert client.get("/api/plans").json() == []
    assert client.post("/api/plans", json={"document_id": doc, "title": "升级后规划"}).status_code == 201
