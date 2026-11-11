"""Deterministic catalog proposals and human-owned editorial planning."""
import json
import hashlib
import re
from pathlib import Path
from typing import Literal
from zipfile import ZipFile
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from lxml import etree as ET
from pydantic import BaseModel, Field

from .db import connect, data_dir, draft_json, now, uid

router = APIRouter(prefix="/api/plans", tags=["content planning"])
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
BOOK = re.compile(r"^(?:人教版)?([七八九]年级[上下][册冊])(?:数学(?:目录)?)?$")
CHAPTER = re.compile(r"^第([一二三四五六七八九十百\d]+)章\s*(.+)")
SECTION = re.compile(r"^\*?\s*(\d+(?:\.\d+){1,2})(?![\d.])\s*(.+)")


def row(c, table, key):
    result = c.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
    if result is None:
        raise HTTPException(404, "规划或来源不存在")
    return result


def same_revision(old, revision):
    if old["revision"] != revision:
        raise HTTPException(409, "规划已修改，请保留本地内容并重新载入")


def url_for_blocks(document):
    """Only read hyperlink targets from the DOCX; never fetch them."""
    if document["kind"] != "docx":
        return {}
    path = data_dir() / "documents" / document["id"] / "original.docx"
    with ZipFile(path) as z:
        parser = ET.XMLParser(resolve_entities=False, no_network=True)
        xml = ET.fromstring(z.read("word/document.xml"), parser)
        if "word/_rels/document.xml.rels" not in z.namelist():
            return {}
        rels = {r.get("Id"): r.get("Target", "") for r in ET.fromstring(z.read("word/_rels/document.xml.rels"), parser)}
        found = {}
        for ordinal, p in enumerate(xml.find(f"{{{W}}}body")):
            links = p.findall(f".//{{{W}}}hyperlink")
            if links:
                url = rels.get(links[0].get(f"{{{R}}}id"), "")
                if urlsplit(url).scheme in {"http", "https"}:
                    found[ordinal] = url
        return found


def proposal(document, blocks):
    links = url_for_blocks(document)
    nodes, snapshot, skipped, skipped_entries = [], {b["id"]: b["revision"] for b in blocks}, 0, []
    book = chapter = section = None
    for b in blocks:
        for raw in b["text"].splitlines():
            text = raw.strip()
            if not text:
                continue
            match = BOOK.match(text)
            if match:
                kind, parent = "book", None
            elif CHAPTER.match(text):
                kind, parent = "chapter", book
            elif text.startswith("综合与实践"):
                kind, parent = "activity", book
            elif SECTION.match(text):
                number = SECTION.match(text).group(1)
                kind, parent = ("topic", section) if number.count(".") == 2 else ("section", chapter)
            elif chapter and (text.startswith(("阅读", "信息技术", "图说", "探究", "数学活动", "小结", "复习题", "构建", "习题", "测试", "锐角", "求锐角", "位似", "两个位似", "在平面", "三视图", "例", "反比例", "反比函数"))):
                kind, parent = "activity", chapter
            else:
                skipped += 1
                skipped_entries.append({"source_id": b["id"], "text": text, "locator": b["locator"]})
                continue
            key = uid()
            nodes.append({"id": key, "parent_id": parent, "kind": kind, "title": text,
                          "source_id": b["id"], "source_url": links.get(b["ordinal"], ""), "included": True})
            snapshot[b["id"]] = b["revision"]
            if kind == "book":
                book, chapter, section = key, None, None
            elif kind == "chapter":
                chapter, section = key, None
            elif kind == "section":
                section = key
    if not any(n["kind"] == "chapter" for n in nodes):
        raise HTTPException(422, "未找到“第X章”目录标题。请先修正提取文字，或提供分行清晰的目录；不会把普通试题猜成章节树。")
    return {"document_id": document["id"], "nodes": nodes, "units": [], "requirements": [],
            "source_revisions": snapshot, "source_hashes": {b["id"]: hashlib.sha256(b["text"].encode()).hexdigest() for b in blocks},
            "notes": "", "skipped_lines": skipped, "skipped_entries": skipped_entries}


def warnings_for(payload):
    if payload.get('mode')=='ai_curriculum':
        messages=['AI提出分类与主题，学习目标对应为建议；引用来自导入资料，不代表已核验教育部原文或全册完整覆盖。']
        if payload.get('unreferenced_sources'): messages.append(f"有 {len(payload['unreferenced_sources'])} 个来源块未被引用，请核对是否为说明、表头或遗漏。")
        if any(not u['goals'].strip() for u in payload['units']): messages.append('部分二级主题尚未填写学习目标对应建议。')
        return messages
    messages, numbers = [], {}
    for n in payload["nodes"]:
        match = CHAPTER.match(n["title"])
        if n["included"] and match:
            numbers.setdefault(match.group(1), []).append(n["title"])
    for number, labels in numbers.items():
        if len(labels) > 1:
            messages.append(f"章号 {number} 重复：{'；'.join(labels)}。保留来源，请人工判断，不自动合并。")
    titles = [n["title"] for n in payload["nodes"] if n["included"]]
    if not any("概率" in t for t in titles):
        messages.append("当前目录未识别到“概率”条目。这是关键词提示，不是课标完整性结论，请核对资料范围。")
    if payload["skipped_lines"]:
        messages.append(f"有 {payload['skipped_lines']} 行未识别为目录（可能是说明或缺失条目），请对照原件。")
    if any(n["included"] and n["parent_id"] is None and n["kind"] != "book" for n in payload["nodes"]):
        messages.append("有条目未归入册次，请在树中调整归属。")
    return messages


def plan_json(c, record):
    result = dict(record)
    result["payload"] = json.loads(result["payload"])
    changes = []
    requirements = {r["source_id"] for r in result["payload"]["requirements"] if r.get("origin","official_excerpt")=="official_excerpt"}
    for key, revision in result["payload"]["source_revisions"].items():
        source = c.execute("SELECT revision,text,verified FROM blocks WHERE id=?", (key,)).fetchone()
        digest = result["payload"].get("source_hashes", {}).get(key)
        content_changed = source is not None and (hashlib.sha256(source["text"].encode()).hexdigest() != digest if digest else source["revision"] != revision)
        if source is None or content_changed or (key in requirements and not source["verified"]):
            changes.append(key)
    result["stale_sources"] = changes
    result["confirmed"] = result["confirmed_revision"] == result["revision"] and not changes
    result["warnings"] = warnings_for(result["payload"])
    result["draft_links"] = [dict(r) for r in c.execute("SELECT unit_id,draft_id,plan_revision FROM plan_draft_links WHERE plan_id=?", (record["id"],))]
    return result


class ImportPlan(BaseModel):
    document_id: str
    title: str = Field(min_length=1, max_length=120)


@router.post("", status_code=201)
def import_plan(body: ImportPlan):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        document = row(c, "documents", body.document_id)
        if document["status"] != "ready":
            raise HTTPException(409, "资料尚未完成读取")
        blocks = c.execute("SELECT * FROM blocks WHERE document_id=? ORDER BY ordinal", (body.document_id,)).fetchall()
        payload = proposal(document, blocks)
        key = uid()
        c.execute("INSERT INTO plans(id,title,payload,created_at) VALUES(?,?,?,?)", (key, body.title, json.dumps(payload, ensure_ascii=False), now()))
        return plan_json(c, row(c, "plans", key))


@router.get("")
def list_plans():
    with connect() as c:
        return [plan_json(c, r) for r in c.execute("SELECT * FROM plans ORDER BY created_at DESC").fetchall()]


class Node(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    parent_id: str | None
    kind: Literal["book", "chapter", "section", "topic", "activity", "domain"]
    title: str = Field(min_length=1, max_length=300)
    source_id: str | None = None
    source_url: str = Field(default="", max_length=2000)
    included: bool = True
    source_excerpt: str = Field(default="",max_length=5000)


class Unit(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    kind: Literal["foundation", "connection", "practice"]
    volume: str = Field(default="", max_length=120)
    goals: str = Field(default="", max_length=5000)
    node_ids: list[str] = Field(max_length=200)


class Requirement(BaseModel):
    origin: Literal["official_excerpt","source_excerpt"] = "official_excerpt"
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=5000)
    source_id: str
    unit_ids: list[str] = Field(max_length=100)


class PlanEdit(BaseModel):
    revision: int
    title: str = Field(min_length=1, max_length=120)
    nodes: list[Node] = Field(min_length=1, max_length=2000)
    units: list[Unit] = Field(max_length=300)
    requirements: list[Requirement] = Field(max_length=1000)
    notes: str = Field(max_length=10000)


def unique_ids(items):
    ids = [x.id for x in items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "条目 ID 不能重复")
    return set(ids)


@router.put("/{plan_id}")
def edit_plan(plan_id: str, body: PlanEdit):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        old = row(c, "plans", plan_id)
        same_revision(old, body.revision)
        state = plan_json(c, old)
        if state["stale_sources"]:
            raise HTTPException(409, "目录或课标来源已经修改，请重新导入一个规划；旧规划保留供对照")
        payload = state["payload"]
        ids, units = unique_ids(body.nodes), unique_ids(body.units)
        unique_ids(body.requirements)
        node_map = {n.id: n for n in body.nodes}
        original_nodes = {n["id"]: n for n in payload["nodes"]}
        for n in body.nodes:
            if n.parent_id is not None and n.parent_id not in ids:
                raise HTTPException(422, "上级条目不存在")
            chain, at = {n.id}, n.parent_id
            while at:
                if at in chain:
                    raise HTTPException(422, "章节树不能形成循环")
                chain.add(at); at = node_map[at].parent_id
            if n.source_url and urlsplit(n.source_url).scheme not in {"http", "https"}:
                raise HTTPException(422, "来源链接只允许 http 或 https")
            if (n.id in original_nodes and n.source_id != original_nodes[n.id]["source_id"]) or (n.id not in original_nodes and n.source_id):
                raise HTTPException(422, "导入条目的来源不可更换；新增条目应标记为人工补充")
        if payload.get('mode')=='ai_curriculum':
            for n in body.nodes:
                if len(n.title)>160: raise HTTPException(422,'领域和主题名称不超过160字')
                if n.kind=='domain' and n.parent_id is not None or n.kind=='topic' and (n.parent_id is None or node_map[n.parent_id].kind!='domain') or n.kind not in {'domain','topic'}:
                    raise HTTPException(422,'AI规划采用领域—二级主题两级结构')
                if n.source_excerpt and (not n.source_id or n.source_excerpt not in row(c,'blocks',n.source_id)['text']): raise HTTPException(422,'来源引文须逐字来自绑定资料')
            for u in body.units:
                if len(u.node_ids)!=1 or node_map[u.node_ids[0]].kind!='topic': raise HTTPException(422,'每个AI规划单元应对应一个二级主题')
                topic=node_map[u.node_ids[0]];u.title=topic.title;u.volume=node_map[topic.parent_id].title
            if len({u.node_ids[0] for u in body.units})!=len(body.units): raise HTTPException(422,'同一二级主题不能重复建立单元')
            if {u.node_ids[0] for u in body.units}!={n.id for n in body.nodes if n.kind=='topic'}: raise HTTPException(422,'每个二级主题都需保留对应单元与目标')
        active = {n.id for n in body.nodes if n.included}
        for u in body.units:
            if payload.get("mode")!="ai_curriculum" and not set(u.node_ids) <= active:
                raise HTTPException(422, "单元只能关联当前纳入的目录条目")
        snapshot = dict(payload["source_revisions"])
        hashes = dict(payload.get("source_hashes", {}))
        for req in body.requirements:
            source = row(c, "blocks", req.source_id)
            doc = row(c, "documents", source["document_id"])
            if req.origin=="source_excerpt" and (payload.get("mode")!="ai_curriculum" or source["document_id"]!=payload["document_id"]): raise HTTPException(422,"资料摘要引用只能来自本规划的导入资料")
            if req.origin=="official_excerpt" and (doc["category"] != "standard" or not source["verified"]):
                raise HTTPException(422, "课标要求必须来自已核对的课标／考纲资料")
            if req.text not in source["text"]:
                raise HTTPException(422, "请从已核对课标文本中逐字摘录要求，不能自动编造课标")
            if not set(req.unit_ids) <= units:
                raise HTTPException(422, "要求关联的单元不存在")
            snapshot[req.source_id] = source["revision"]
            hashes[req.source_id] = hashlib.sha256(source["text"].encode()).hexdigest()
        payload.update(nodes=[n.model_dump() for n in body.nodes], units=[u.model_dump() for u in body.units],
                       requirements=[r.model_dump() for r in body.requirements], notes=body.notes, source_revisions=snapshot, source_hashes=hashes)
        c.execute("UPDATE plans SET title=?,payload=?,revision=revision+1,confirmed_revision=NULL,reviewer=NULL WHERE id=?",
                  (body.title, json.dumps(payload, ensure_ascii=False), plan_id))
        for link in c.execute("SELECT draft_id FROM plan_draft_links WHERE plan_id=?", (plan_id,)).fetchall():
            c.execute("UPDATE drafts SET revision=revision+1,approved_revision=NULL,reviewer=NULL WHERE id=?", (link["draft_id"],))
        return plan_json(c, row(c, "plans", plan_id))


class ConfirmPlan(BaseModel):
    revision: int
    reviewer: str = Field(min_length=1, max_length=80)
    acknowledged: bool


@router.post("/{plan_id}/confirm")
def confirm_plan(plan_id: str, body: ConfirmPlan):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        old = row(c, "plans", plan_id)
        same_revision(old, body.revision)
        state = plan_json(c, old)
        if state["stale_sources"]:
            raise HTTPException(409, "来源变更，不能确认旧规划")
        if state['payload'].get('mode')=='ai_curriculum' and not any(n['kind']=='topic' and n['included'] and next(d['included'] for d in state['payload']['nodes'] if d['id']==n['parent_id']) for n in state['payload']['nodes']):
            raise HTTPException(422,'至少需要一个纳入的二级主题')
        if not body.acknowledged or not body.reviewer.strip():
            raise HTTPException(422, "请确认已核对结构和疑问，并填写确认人")
        c.execute("UPDATE plans SET confirmed_revision=revision,reviewer=? WHERE id=?", (body.reviewer.strip(), plan_id))
        return plan_json(c, row(c, "plans", plan_id))


class CreateUnitDraft(BaseModel):
    revision: int


@router.post("/{plan_id}/units/{unit_id}/draft", status_code=201)
def create_unit_draft(plan_id: str, unit_id: str, body: CreateUnitDraft):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        record = row(c, "plans", plan_id)
        same_revision(record, body.revision)
        state = plan_json(c, record)
        if not state["confirmed"]:
            raise HTTPException(409, "请先确认当前规划")
        unit = next((u for u in state["payload"]["units"] if u["id"] == unit_id), None)
        if not unit:
            raise HTTPException(404, "单元不存在")
        existing = c.execute("SELECT * FROM plan_draft_links WHERE plan_id=? AND unit_id=?", (plan_id, unit_id)).fetchone()
        if existing:
            return draft_json(row(c, "drafts", existing["draft_id"]))
        nodes = {n["id"]: n for n in state["payload"]["nodes"]}
        sources = list(dict.fromkeys(nodes[key]["source_id"] for key in unit["node_ids"] if nodes[key]["source_id"]))
        if not sources:
            raise HTTPException(422, "请为单元关联至少一个有原始来源的目录条目")
        if any(not row(c, "blocks", key)["verified"] for key in sources):
            raise HTTPException(409, "关联目录条目尚未在“原题核对”中确认；结构确认不代替来源核对")
        content = (f"分册：{unit['volume']}\n学习目标\n{unit['goals'] or '待编写'}\n\n关联知识\n" +
                   "\n".join(nodes[key]["title"] for key in unit["node_ids"]) +
                   "\n\n必要概念与性质\n待编写准确表述、条件及依据。\n\n知识连接与可行思路\n待研究；此提纲不包含自动生成的数学解答。\n\n独立训练与答案\n待编写与审核。")
        key = uid()
        c.execute("INSERT INTO drafts(id,title,content,source_ids,created_at) VALUES(?,?,?,?,?)", (key, unit["title"], content, json.dumps(sources), now()))
        c.execute("INSERT INTO plan_draft_links VALUES(?,?,?,?)", (plan_id, unit_id, key, record["revision"]))
        return draft_json(row(c, "drafts", key))
