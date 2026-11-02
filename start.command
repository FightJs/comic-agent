#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements-lock.txt
fi
if [[ ! -d frontend/node_modules ]]; then npm ci --prefix frontend; fi
if [[ ! -d frontend/dist ]]; then npm run build --prefix frontend; fi
print '条漫 Agent: http://127.0.0.1:8765 （按 Ctrl+C 停止）'
exec .venv/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8765 --no-access-log
