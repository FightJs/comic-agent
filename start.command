#!/bin/zsh
set -e
cd "${0:A:h}"
node_compatible() {
  local version major minor
  version=$("$1" --version 2>/dev/null) || return 1
  [[ "$version" =~ '^v([0-9]+)\.([0-9]+)\.([0-9]+)$' ]] || return 1
  major=$match[1]; minor=$match[2]
  (( major > 22 || (major == 22 && minor >= 19) ))
}
if ! node_compatible node; then
  best_node=''; best_major=0; best_minor=0; best_patch=0
  for candidate in "$HOME"/.nvm/versions/node/*/bin/node(N); do
    [[ -x "$candidate" ]] && node_compatible "$candidate" || continue
    candidate_version=$("$candidate" --version)
    [[ "$candidate_version" =~ '^v([0-9]+)\.([0-9]+)\.([0-9]+)$' ]] || continue
    candidate_major=$match[1]; candidate_minor=$match[2]; candidate_patch=$match[3]
    if (( candidate_major > best_major || (candidate_major == best_major && candidate_minor > best_minor) || (candidate_major == best_major && candidate_minor == best_minor && candidate_patch > best_patch) )); then
      best_node="$candidate"; best_major=$candidate_major; best_minor=$candidate_minor; best_patch=$candidate_patch
    fi
  done
  if [[ -z "$best_node" ]]; then
    print -u2 '需要 Node.js ≥22.19；当前 PATH 和本机 nvm 中未找到合格版本。'
    exit 1
  fi
  export PATH="${best_node:h}:$PATH"
fi
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if(major<22 || (major===22 && minor<19)){console.error("需要 Node.js ≥22.19");process.exit(1)}'
if [[ ! -d agent-runtime/node_modules ]]; then npm ci --prefix agent-runtime; fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r backend/requirements-lock.txt
fi
if [[ ! -d frontend/node_modules ]]; then npm ci --prefix frontend; fi
if [[ ! -d frontend/dist ]]; then npm run build --prefix frontend; fi
print '条漫 Agent: http://127.0.0.1:8765 （按 Ctrl+C 停止）'
exec .venv/bin/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8765 --no-access-log
