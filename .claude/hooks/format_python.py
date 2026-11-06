import json
import os
import subprocess
import sys
from pathlib import Path

payload = json.load(sys.stdin)
path = payload.get("tool_input", {}).get("file_path", "")
if not path.endswith(".py"):
    sys.exit(0)

project = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())).resolve()
target = Path(path).resolve()
if not target.is_relative_to(project):
    sys.exit(0)  # só formata arquivos do próprio projeto

# Usa o ruff do .venv do projeto (mesma versão do make lint); senão, o do PATH.
venv_ruff = [project / ".venv" / "Scripts" / "ruff.exe", project / ".venv" / "bin" / "ruff"]
ruff = next((str(p) for p in venv_ruff if p.exists()), "ruff")

subprocess.run([ruff, "format", str(target)], capture_output=True, cwd=project, check=False)
result = subprocess.run(
    [ruff, "check", "--fix", str(target)], capture_output=True, text=True, cwd=project, check=False
)
if result.returncode != 0:
    print(result.stdout, file=sys.stderr)
    sys.exit(2)
