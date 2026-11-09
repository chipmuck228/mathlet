"""Create the project-local Python environment and install locked frontend deps."""
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11 或更新版本")
python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.exists():
    venv.EnvBuilder(with_pip=True).create(root / ".venv")
npm = shutil.which("npm")
if not npm:
    raise SystemExit("请先安装 Node.js 22.12+（建议当前 LTS），确保 npm 可用")
subprocess.run([str(python), "-m", "pip", "install", "-r", "apps/api/requirements.lock"], cwd=root, check=True)
subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "-e", "apps/api"], cwd=root, check=True)
subprocess.run([npm, "ci"], cwd=root, check=True)
print("安装完成。运行 python3 scripts/dev.py；Windows 可使用 py scripts/dev.py。")
