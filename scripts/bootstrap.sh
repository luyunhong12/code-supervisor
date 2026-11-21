#!/usr/bin/env bash
# 在独立工具目录安装，不向业务工程安装依赖；需要联网。
set -euo pipefail
supervisor_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$supervisor_root"
unset PYTHONPATH
language="${1:-all}"
case "$language" in
    python|cpp|all) ;;
    *) echo "用法：bash scripts/bootstrap.sh [python|cpp|all]" >&2; exit 2 ;;
esac
python3 -m venv .venv
if [[ "$language" == all ]]; then
    .venv/bin/python -m pip install -r requirements-lock.txt -e '.[quality]' -r requirements-ub.txt
elif [[ "$language" == python ]]; then
    .venv/bin/python -m pip install -c requirements-lock.txt -e '.[python]' -r requirements-ub.txt
else
    .venv/bin/python -m pip install -c requirements-lock.txt -e '.[cpp]'
fi
mkdir -p .tools
if [[ "$language" != python ]]; then
    cp tools/package.json tools/package-lock.json .tools/
    npm ci --prefix .tools --no-audit --no-fund
fi
if [[ "$language" != cpp ]]; then
    .venv/bin/python - <<'PARSER'
from pathlib import Path
from tree_sitter_language_pack import configure, PackConfig, get_parser
configure(PackConfig(cache_dir=str(Path('.tools/parsers').resolve())))
get_parser('python')
PARSER
fi
.venv/bin/supervisor doctor --language "$language"
