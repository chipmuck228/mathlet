"""Original-page evidence, independent of extracted/corrected block text."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from filelock import FileLock
from pypdf import PdfReader

from .db import connect, data_dir, now, uid

router = APIRouter(prefix="/api", tags=["original-view"])


def converter():
    configured = os.environ.get("MATHLET_SOFFICE")
    if configured and Path(configured).is_file():
        return configured
    return (shutil.which("soffice") or shutil.which("libreoffice") or
            next((str(p) for p in (Path('/Applications/LibreOffice.app/Contents/MacOS/soffice'),
                  Path('C:/Program Files/LibreOffice/program/soffice.exe')) if p.is_file()), None))


def folder_for(document_id):
    with connect() as c:
        document = c.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if document is None:
            raise HTTPException(404, "资料不存在")
    return dict(document), data_dir() / "documents" / document_id


def status(document_id):
    document, folder = folder_for(document_id)
    pdf = folder / ("original.pdf" if document['kind'] == 'pdf' else 'original-view.pdf')
    available = pdf.is_file()
    with connect() as c:
        job = c.execute("SELECT * FROM jobs WHERE document_id=? AND kind='original_view' ORDER BY created_at DESC,rowid DESC LIMIT 1", (document_id,)).fetchone()
    state = job['status'] if job else 'not_generated'
    if available and state not in {'queued', 'running', 'failed'}:
        state = 'ready'
    return {"status": state, "available": available,
            "pages": len(PdfReader(pdf).pages) if available else 0,
            "version": str(pdf.stat().st_mtime_ns) if available else None,
            "message": job['message'] if job else '尚未生成原页预览',
            "converted": document['kind'] == 'docx'}


def enqueue(c, document_id):
    active = c.execute("SELECT id FROM jobs WHERE document_id=? AND kind='original_view' AND status IN ('queued','running')", (document_id,)).fetchone()
    if not active:
        c.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)", (uid(), document_id, 'original_view', 'queued', '等待 Worker 转换原始文档页面', now(), now()))


@router.get('/documents/{document_id}/original-view')
def get_status(document_id: str):
    return status(document_id)


@router.post('/documents/{document_id}/original-view', status_code=202)
def request_view(document_id: str, regenerate: bool = False):
    document, _ = folder_for(document_id)
    current = status(document_id)
    if document['kind'] == 'pdf' or (current['status'] == 'ready' and not regenerate): return current
    if document['status'] != 'ready': raise HTTPException(409, '请等待资料提取完成')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        enqueue(c, document_id)
    return status(document_id)


@router.get('/documents/{document_id}/original-view.pdf')
def view_pdf(document_id: str):
    document, folder = folder_for(document_id)
    path = folder / ('original.pdf' if document['kind'] == 'pdf' else 'original-view.pdf')
    if not path.is_file(): raise HTTPException(404, '原页预览尚未生成')
    return FileResponse(path, media_type='application/pdf', headers={'Content-Disposition': 'inline', 'Cache-Control': 'no-store'})


def build_view(document_id):
    document, folder = folder_for(document_id)
    if document['kind'] == 'pdf': return
    target = folder / 'original-view.pdf'
    executable = converter()
    if not executable:
        raise ValueError('未找到 LibreOffice。请安装后重试；可设置 MATHLET_SOFFICE 为 soffice 可执行文件路径。原件与提取结果不受影响。')
    # Isolated profile avoids opening/locking a user's interactive LibreOffice session.
    with FileLock(str(folder / 'original-view.lock'), timeout=1), tempfile.TemporaryDirectory(prefix='mathlet-view-') as temp:
        work = Path(temp)
        result = subprocess.run([executable, '-env:UserInstallation=' + (work / 'profile').as_uri(),
                                 '--headless', '--convert-to', 'pdf:writer_pdf_Export', '--outdir', str(work),
                                 str(folder / 'original.docx')], capture_output=True, timeout=120)
        generated = work / 'original.pdf'
        if result.returncode or not generated.is_file():
            raise ValueError('DOCX 原页转换失败，请检查文件是否可在 LibreOffice 打开；可下载原件核对后重试。')
        reader = PdfReader(generated)
        if not 0 < len(reader.pages) <= 120:
            raise ValueError('原页预览仅支持1至120页，请拆分资料')
        staged = folder / 'original-view.tmp'
        shutil.copyfile(generated, staged)
        staged.replace(target)
