import base64
import html
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .db import ROOT, block_json, connect, data_dir, draft_json, init_db, now, uid
from .formulas import UNSUPPORTED, parts_from_text, render_text


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(title="Mathlet", version="0.3.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
@app.exception_handler(RequestValidationError)
async def redact_provider_validation(request: Request, exc: RequestValidationError):
    if request.url.path == '/api/knowledge/provider' or request.url.path.startswith('/api/editor/profiles'):
        return JSONResponse({'detail': [{'loc': error['loc'], 'msg': error['msg'], 'type': error['type']} for error in exc.errors()]}, status_code=422)
    return await request_validation_exception_handler(request, exc)


ALLOWED_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}


@app.middleware("http")
async def local_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": "只接受本地工作台发起的修改"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def get_row(c, table, key):
    # Table is an internal constant, never a request parameter.
    row = c.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
    if row is None:
        raise HTTPException(404, "记录不存在")
    return row


def require_revision(row, revision):
    if row["revision"] != revision:
        raise HTTPException(409, "内容已变化，请刷新后重新核对")


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.3.0", "generation_mode": "knowledge_drafting_and_editorial_scaffold", "model_connected": False}


@app.get("/api/documents")
def documents():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM documents ORDER BY created_at DESC")]


@app.post("/api/documents", status_code=201)
async def upload(file: UploadFile = File(...), category: Literal["unknown", "standard", "textbook", "exam", "mock", "term"] = "unknown"):
    name = Path((file.filename or "document").replace("\\", "/")).name[:200]
    kind = Path(name).suffix.lower().lstrip(".")
    if kind not in {"docx", "pdf"}:
        raise HTTPException(415, "仅支持 DOCX 与 PDF")
    document_id, job_id = uid(), uid()
    folder = data_dir() / "documents" / document_id
    folder.mkdir(parents=True)
    size = 0
    try:
        with (folder / ("original." + kind)).open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 30 * 1024 * 1024:
                    raise HTTPException(413, "单份文件不能超过30MB")
                out.write(chunk)
        if not size:
            raise HTTPException(400, "文件为空")
        with connect() as c:
            c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)", (document_id, name, kind, category, "queued", now()))
            c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)", (job_id, document_id, "ingest", "queued", "等待本地 Worker", now(), now()))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        await file.close()
    return {"id": document_id, "job_id": job_id}


@app.get("/api/jobs")
def jobs():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT jobs.*,documents.name FROM jobs JOIN documents ON documents.id=jobs.document_id ORDER BY jobs.created_at DESC LIMIT 100")]


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = get_row(c, "jobs", job_id)
        if row["status"] != "failed":
            raise HTTPException(409, "仅失败任务可以重试")
        if row["kind"] == "original_view":
            from .original_view import enqueue
            enqueue(c, row["document_id"])
            return {"ok": True}
        c.execute("UPDATE jobs SET status='queued',message='等待重试',updated_at=? WHERE id=?", (now(), job_id))
        c.execute("UPDATE documents SET status='queued' WHERE id=?", (row["document_id"],))
    return {"ok": True}


@app.get("/api/documents/{document_id}/blocks")
def blocks(document_id: str):
    with connect() as c:
        get_row(c, "documents", document_id)
        return [block_json(r) for r in c.execute("SELECT * FROM blocks WHERE document_id=? ORDER BY ordinal", (document_id,))]


@app.get("/api/documents/{document_id}/original")
def original(document_id: str):
    with connect() as c:
        row = get_row(c, "documents", document_id)
    return FileResponse(data_dir() / "documents" / document_id / ("original." + row["kind"]), filename=row["name"])


@app.get("/api/documents/{document_id}/assets/{name}")
def asset(document_id: str, name: str):
    if not all(c in "0123456789abcdef" for c in document_id) or len(document_id) != 32:
        raise HTTPException(404)
    if not name.endswith(".png") or len(name) != 36 or not all(c in "0123456789abcdef" for c in name[:-4]):
        raise HTTPException(404)
    path = data_dir() / "documents" / document_id / "assets" / name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


class BlockEdit(BaseModel):
    revision: int
    text: str = Field(max_length=150_000)
    verified: bool


def apply_block_edits(c, changes):
    """Check revisions atomically; human confirmation does not depend on formula syntax."""
    old_rows = {}
    for key, body in changes:
        old = get_row(c, "blocks", key)
        require_revision(old, body.revision)
        old_rows[key] = old
    changed = [(key,body) for key,body in changes if body.text != old_rows[key]["text"] or bool(body.verified) != bool(old_rows[key]["verified"])]
    for key, body in changed:
        c.execute("UPDATE blocks SET text=?,verified=?,revision=revision+1 WHERE id=?", (body.text, int(body.verified), key))
    keys = {key for key,_ in changed}
    affected = set()
    for draft in c.execute("SELECT id,source_ids FROM drafts").fetchall():
        if keys.intersection(json.loads(draft["source_ids"])):
            affected.add(draft["id"])
    for plan in c.execute("SELECT id,payload FROM plans").fetchall():
        payload = json.loads(plan["payload"])
        requirements = {r["source_id"] for r in payload["requirements"]}
        if any(key in payload["source_revisions"] and
               (body.text != old_rows[key]["text"] or (key in requirements and not body.verified))
               for key, body in changed):
            c.execute("UPDATE plans SET confirmed_revision=NULL,reviewer=NULL WHERE id=?", (plan["id"],))
            affected.update(r["draft_id"] for r in c.execute("SELECT draft_id FROM plan_draft_links WHERE plan_id=?", (plan["id"],)))
    for draft_id in affected:
        c.execute("UPDATE drafts SET revision=revision+1,approved_revision=NULL,reviewer=NULL WHERE id=?", (draft_id,))
    from .source_review import snapshot_review
    for document_id in {value["document_id"] for value in old_rows.values()}:
        snapshot_review(c, document_id, [(key,body) for key,body in changes if old_rows[key]["document_id"] == document_id])
    return [block_json(get_row(c, "blocks", key)) for key, _ in changes]


@app.put("/api/blocks/{block_id}")
def edit_block(block_id: str, body: BlockEdit):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        updated = apply_block_edits(c, [(block_id, body)])[0]
    from .source_review import result
    result(updated["document_id"])
    return updated


class RangeBlockEdit(BlockEdit):
    id: str


class RangeReview(BaseModel):
    changes: list[RangeBlockEdit] = Field(min_length=1, max_length=500)


@app.put("/api/documents/{document_id}/blocks/review")
def review_range(document_id: str, body: RangeReview):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        get_row(c, "documents", document_id)
        ids = [b.id for b in body.changes]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, "同一范围不能包含重复来源块")
        for key in ids:
            if get_row(c, "blocks", key)["document_id"] != document_id:
                raise HTTPException(422, "不能跨资料保存核对范围")
        updated = apply_block_edits(c, [(b.id, b) for b in body.changes])
    from .source_review import result
    result(document_id)
    return updated


class NewDraft(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    source_ids: list[str] = Field(min_length=1, max_length=30)


@app.post("/api/drafts", status_code=201)
def create_draft(body: NewDraft):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        ids = list(dict.fromkeys(body.source_ids))
        for key in ids:
            if not get_row(c, "blocks", key)["verified"]:
                raise HTTPException(409, "所有选用原题必须先人工核对")
        content = ("学习目标\n请填写学生应能够解释和完成的任务。\n\n"
                   "必要概念与性质\n请填写准确表述、成立条件与来源。\n\n"
                   "共同对象与知识连接\n已知什么？同一对象受到哪些约束？连接依据是什么？\n\n"
                   "一条可行思考路径\n请填写每一步的目的与数学依据。允许补充其他有效路径。\n\n"
                   "范围、边界与检验\n请检查分类完整性、退化情况及结果是否满足原条件。\n\n"
                   "独立练习与核对\n请编写迁移任务及答案，并交由教师审核。")
        key = uid()
        c.execute("INSERT INTO drafts(id,title,content,source_ids,created_at) VALUES(?,?,?,?,?)",
                  (key, body.title.strip(), content, json.dumps(ids), now()))
        return draft_json(get_row(c, "drafts", key))


@app.get("/api/drafts")
def drafts():
    with connect() as c:
        return [draft_json(r) for r in c.execute("SELECT * FROM drafts ORDER BY created_at DESC")]


class DraftEdit(BaseModel):
    revision: int
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=200_000)


@app.put("/api/drafts/{draft_id}")
def edit_draft(draft_id: str, body: DraftEdit):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        require_revision(get_row(c, "drafts", draft_id), body.revision)
        c.execute("UPDATE drafts SET title=?,content=?,revision=revision+1,approved_revision=NULL,reviewer=NULL WHERE id=?",
                  (body.title.strip(), body.content, draft_id))
        return draft_json(get_row(c, "drafts", draft_id))


class Comment(BaseModel):
    revision: int
    author: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=10_000)


@app.post("/api/drafts/{draft_id}/comments", status_code=201)
def comment(draft_id: str, body: Comment):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        require_revision(get_row(c, "drafts", draft_id), body.revision)
        c.execute("INSERT INTO comments VALUES(?,?,?,?,?,?)", (uid(), draft_id, body.revision, body.author, body.body, now()))
    return {"ok": True}


@app.get("/api/drafts/{draft_id}/comments")
def comments(draft_id: str):
    with connect() as c:
        get_row(c, "drafts", draft_id)
        return [dict(r) for r in c.execute("SELECT * FROM comments WHERE draft_id=? ORDER BY created_at", (draft_id,))]


class Approval(BaseModel):
    revision: int
    reviewer: str = Field(min_length=1, max_length=80)
    confirmed: bool


@app.post("/api/drafts/{draft_id}/approve")
def approve(draft_id: str, body: Approval):
    if not body.confirmed or not body.reviewer.strip():
        raise HTTPException(422, "需要审核人及明确审核确认")
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        draft = get_row(c, "drafts", draft_id)
        require_revision(draft, body.revision)
        try:
            parts_from_text(draft["content"], strict=True)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        for key in json.loads(draft["source_ids"]):
            if not get_row(c, "blocks", key)["verified"]:
                raise HTTPException(409, "关联原题尚未确认")
        c.execute("UPDATE drafts SET approved_revision=revision,reviewer=? WHERE id=?", (body.reviewer.strip(), draft_id))
        return draft_json(get_row(c, "drafts", draft_id))


def capture(c, draft):
    sources = []
    for key in json.loads(draft["source_ids"]):
        block = block_json(get_row(c, "blocks", key))
        document = get_row(c, "documents", block["document_id"])
        block["document_name"] = document["name"]
        block["category"] = document["category"]
        block["images"] = ["data:image/png;base64," + base64.b64encode(
            (data_dir() / "documents" / block["document_id"] / "assets" / name).read_bytes()).decode()
                           for name in block["assets"]]
        sources.append(block)
    return {"draft": draft_json(draft), "sources": sources, "created_at": now(), "format_version": 2}


def render_book(snapshot):
    draft = snapshot["draft"]
    render = render_text if snapshot.get("format_version", 1) >= 2 else html.escape
    source_html = ""
    for b in snapshot["sources"]:
        # Corrected source text is authoritative, not a stale formula preview.
        images = "".join('<img alt="原件图或页面" src="' + image + '">' for image in b["images"])
        source_html += '<section><h3>' + html.escape(b["document_name"] + " · " + b["locator"]) + '</h3><p class="text">' + render(b["text"]) + "</p>" + images + "</section>"
    status = f"审核人：{draft['reviewer']} · 修订 {draft['revision']}" if draft["approved"] else "草稿 · 尚未批准"
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
            '<title>' + html.escape(draft["title"]) + '</title><style>body{font:17px/1.9 system-ui;color:#263b34;background:#fffdf8;max-width:800px;margin:40px auto;padding:0 24px}h1{font-weight:500}h3{font-size:16px}.text{white-space:pre-wrap;overflow-wrap:anywhere}img{display:block;max-width:100%;max-height:700px;object-fit:contain;margin:20px 0}section{border-bottom:1px solid #ddd;padding:12px 0}small{color:#666}@media print{body{margin:0;max-width:none;background:white}img{max-height:210mm}h1,h3{break-after:avoid}}</style>'
            '<h1>' + html.escape(draft["title"]) + '</h1><small>' + html.escape(status) + '</small>' + source_html
            + '<h2>讲解与训练</h2><div class="text">' + render(draft["content"]) + '</div></html>')


@app.get("/api/drafts/{draft_id}/preview", response_class=HTMLResponse)
def preview(draft_id: str):
    with connect() as c:
        return render_book(capture(c, get_row(c, "drafts", draft_id)))


class ReleaseRequest(BaseModel):
    revision: int


@app.post("/api/drafts/{draft_id}/releases", status_code=201)
def release(draft_id: str, body: ReleaseRequest):
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        draft = get_row(c, "drafts", draft_id)
        require_revision(draft, body.revision)
        if draft["approved_revision"] != draft["revision"]:
            raise HTTPException(409, "当前修订尚未人工批准")
        for key in json.loads(draft["source_ids"]):
            if not get_row(c, "blocks", key)["verified"]:
                raise HTTPException(409, "关联原题需要复核")
        key = uid()
        snapshot = capture(c, draft)
        snapshot["rendered_html"] = render_book(snapshot)
        c.execute("INSERT INTO releases VALUES(?,?,?,?,?)", (key, draft_id, draft["revision"], json.dumps(snapshot, ensure_ascii=False), now()))
        return {"id": key, "revision": draft["revision"]}


@app.get("/api/releases")
def releases():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT id,draft_id,revision,created_at FROM releases ORDER BY created_at DESC")]


@app.get("/api/releases/{release_id}/download", response_class=HTMLResponse)
def download_release(release_id: str):
    with connect() as c:
        row = get_row(c, "releases", release_id)
        snapshot = json.loads(row["snapshot"])
        return HTMLResponse(snapshot.get("rendered_html") or render_book(snapshot), headers={"Content-Disposition": f'attachment; filename="mathlet-{release_id[:8]}.html"'})


from .planning import router as planning_router
app.include_router(planning_router)
from .formula_api import router as formula_router
app.include_router(formula_router)

from .original_view import router as original_view_router
app.include_router(original_view_router)

from .knowledge import router as knowledge_router
app.include_router(knowledge_router)

from .knowledge_actions import router as knowledge_actions_router
app.include_router(knowledge_actions_router)

from .planning_ai import router as planning_ai_router
app.include_router(planning_ai_router)

from .research import router as research_router
app.include_router(research_router)

from .editorial import router as editorial_router
app.include_router(editorial_router)

from .research_editor import router as research_editor_router
app.include_router(research_editor_router)

from .source_review import router as source_review_router
app.include_router(source_review_router)

from .paper_research import router as paper_router
app.include_router(paper_router)

from .teaching import router as teaching_router
app.include_router(teaching_router)

from .exam_extraction import router as exam_router
app.include_router(exam_router)

from .exam_formulas import router as exam_formula_router
app.include_router(exam_formula_router)

web = ROOT / "apps" / "web" / "dist"
if web.is_dir():
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
