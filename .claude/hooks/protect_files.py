import json
import os
import sys
from fnmatch import fnmatch

PROTECTED = [".env", ".env.*", "data/private/*", ".git/*", "dbt/target/*", "*.pbix"]
ALLOWED = [".env.example"]  # modelo com valores fictícios, versionado no Git

payload = json.load(sys.stdin)
path = payload.get("tool_input", {}).get("file_path", "")
project = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
relative = os.path.relpath(path, project).replace("\\", "/")

if relative not in ALLOWED and any(fnmatch(relative, pattern) for pattern in PROTECTED):
    print(
        f"Arquivo protegido: {relative}. Peça ao usuário para editar manualmente.", file=sys.stderr
    )
    sys.exit(2)
