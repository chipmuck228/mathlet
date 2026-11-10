"""Single local worker with durable jobs and restart recovery."""
import json
import signal
import time

from filelock import FileLock, Timeout

from .db import connect, data_dir, init_db, now
from .ingest import extract
from .original_view import build_view, enqueue
from .knowledge_worker import run_one_knowledge, recover_knowledge


def run_one():
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY CASE WHEN kind='ingest' THEN 0 ELSE 1 END, created_at LIMIT 1").fetchone()
        if not row:
            c.rollback()
            return run_one_knowledge()
        c.execute("UPDATE jobs SET status='running',message='正在读取原件',updated_at=? WHERE id=?", (now(), row["id"]))
        document = c.execute("SELECT * FROM documents WHERE id=?", (row["document_id"],)).fetchone()
    folder = data_dir() / "documents" / document["id"]
    try:
        if row["kind"] == "original_view":
            conversion_message = build_view(document["id"]) or "原页预览已生成"
            with connect() as c:
                c.execute("UPDATE jobs SET status='completed',message=?,updated_at=? WHERE id=?", (conversion_message, now(), row["id"]))
            return True
        blocks = extract(folder / ("original." + document["kind"]), document["kind"], folder / "assets")
        if not blocks:
            raise ValueError("未提取到可审阅内容，请检查文件")
        with connect() as c:
            # Atomic insertion: no partially imported document is exposed as ready.
            for b in blocks:
                c.execute("INSERT INTO blocks(id,document_id,ordinal,locator,text,preview,assets,warnings,original_content,original_text) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (b["id"], document["id"], b["ordinal"], b["locator"], b["text"], b["preview"],
                           json.dumps(b["assets"]), json.dumps(b["warnings"], ensure_ascii=False), json.dumps(b.get("original_content", []), ensure_ascii=False), b["text"]))
            if document["kind"] == "docx":
                enqueue(c, document["id"])
            c.execute("UPDATE documents SET status='ready' WHERE id=?", (document["id"],))
            c.execute("UPDATE jobs SET status='completed',message=?,updated_at=? WHERE id=?",
                      (f"已提取 {len(blocks)} 个内容块，待人工核对", now(), row["id"]))
    except Exception as e:
        with connect() as c:
            if row["kind"] != "original_view":
                c.execute("UPDATE documents SET status='failed' WHERE id=?", (document["id"],))
            c.execute("UPDATE jobs SET status='failed',message=?,updated_at=? WHERE id=?",
                      (f"读取失败：{type(e).__name__}: {str(e)[:300]}", now(), row["id"]))
    return True


def main():
    init_db()
    try:
        with FileLock(str(data_dir() / "worker.lock"), timeout=0):
            recover_knowledge()
            with connect() as c:
                c.execute("UPDATE jobs SET status='queued',message='Worker 重启后重新读取',updated_at=? WHERE status='running'", (now(),))
            running = True

            def stop(*_):
                nonlocal running
                running = False

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            print("Mathlet worker ready", flush=True)
            while running:
                if not run_one():
                    time.sleep(0.5)
    except Timeout:
        raise SystemExit("已有 Worker 使用此数据目录，请勿重复启动")


if __name__ == "__main__":
    main()
