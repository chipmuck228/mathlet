"""Run local API, worker and Vite; stop all children with Ctrl+C."""
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
npm = shutil.which("npm")
if not python.exists() or not npm:
    raise SystemExit("请先运行 python3 scripts/setup.py")
for port in (8000, 5173):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"端口 {port} 已被占用，请先停止已有服务")
commands = [
    [str(python), "-m", "uvicorn", "mathlet.main:app", "--host", "127.0.0.1", "--port", "8000"],
    [str(python), "-m", "mathlet.worker"],
    [npm, "run", "dev"],
]
children = []
try:
    for command in commands:
        children.append(subprocess.Popen(command, cwd=root, start_new_session=os.name != "nt"))
    print("\nMathlet: http://127.0.0.1:5173  |  Ctrl+C 停止所有服务\n", flush=True)
    while True:
        time.sleep(0.5)
        if any(c.poll() is not None for c in children):
            raise SystemExit("有服务退出，请检查上方日志。其他服务将一起停止。")
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        if child.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(child.pid, signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(child.pid, signal.SIGKILL)
