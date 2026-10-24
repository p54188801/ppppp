#!/usr/bin/env bash
# 在 Linux / Codespaces 中启动 Web 服务（无桌面窗口，用浏览器访问）
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${EDUFLOW_HOST:-0.0.0.0}"
PORT="${EDUFLOW_PORT:-8765}"

if [ ! -f "frontend/dist/index.html" ]; then
  echo "==> 未找到前端产物，开始构建"
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

echo "==> 启动 EduFlow：http://${HOST}:${PORT}"
exec python -m backend.cli serve --host "$HOST" --port "$PORT"
