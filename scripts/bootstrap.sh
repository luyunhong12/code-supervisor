#!/usr/bin/env bash
# 在独立工具目录安装，不向业务工程安装依赖；需要联网。
set -euo pipefail
supervisor_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$supervisor_root"
unset PYTHONPATH
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt -e '.[quality]' -r requirements-ub.txt
mkdir -p .tools
cp tools/package.json tools/package-lock.json .tools/
npm ci --prefix .tools --no-audit --no-fund
.venv/bin/python - <<'PY'
from pathlib import Path
from tree_sitter_language_pack import configure, PackConfig, get_parser
configure(PackConfig(cache_dir=str(Path('.tools/parsers').resolve())))
get_parser('python')
PY
.venv/bin/supervisor doctor
