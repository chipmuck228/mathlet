import json
from zipfile import ZipFile
from lxml import etree as ET
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .db import connect, data_dir, now
from .formulas import structured_docx, parts_from_text, render_latex

router = APIRouter(prefix="/api", tags=["formulas"])


@router.get('/formulas/capabilities')
def capabilities():
    from .formula_support import COMMANDS, ENVIRONMENTS, DIALECT_VERSION
    return {'dialect_version':DIALECT_VERSION,'commands':sorted(COMMANDS),'environments':sorted(ENVIRONMENTS),'full_tex':False}


class FormulaPreview(BaseModel):
    latex: str = Field(min_length=1, max_length=6000)


@router.post("/formulas/preview")
def preview(body: FormulaPreview):
    try:
        return {"latex": body.latex, "mathml": render_latex(body.latex)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/documents/{document_id}/formula-candidates")
def candidates(document_id: str):
    with connect() as c:
        return [dict(r) | {"content": parts_from_text(r["text"]), "original_content": json.loads(r["original_content"])}
                for r in c.execute("SELECT formula_candidates.* FROM formula_candidates JOIN blocks ON blocks.id=block_id WHERE blocks.document_id=?", (document_id,))]


@router.post("/documents/{document_id}/formula-candidates")
def extract_candidates(document_id: str):
    with connect() as c:
        document = c.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if document is None: raise HTTPException(404, "资料不存在")
        if document["kind"] != "docx" or document["status"] != "ready":
            raise HTTPException(422, "仅已读取的 DOCX 支持从原生公式重新提取；PDF 可手工插入公式")
        blocks = {r["ordinal"]: dict(r) for r in c.execute("SELECT * FROM blocks WHERE document_id=?", (document_id,))}
    with ZipFile(data_dir() / "documents" / document_id / "original.docx") as z:
        xml = ET.fromstring(z.read("word/document.xml"), ET.XMLParser(resolve_entities=False, no_network=True))
        body = xml.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body")
        proposals = []
        for ordinal, node in enumerate(body):
            if ordinal not in blocks: continue
            text, content = structured_docx(node)
            if any(p["type"] in {"math", "unsupported"} for p in content) or "，请合并核对】" in text:
                proposals.append((blocks[ordinal]["id"], blocks[ordinal]["revision"], text, json.dumps(content, ensure_ascii=False), now()))
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        for block_id, revision, *_ in proposals:
            if c.execute("SELECT revision FROM blocks WHERE id=?", (block_id,)).fetchone()[0] != revision:
                raise HTTPException(409, "来源在提取期间改变，请重新生成候选")
        for item in proposals:
            c.execute("INSERT OR REPLACE INTO formula_candidates VALUES(?,?,?,?,?)", item)
    return candidates(document_id)
