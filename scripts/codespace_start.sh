#!/usr/bin/env bash
# 在 Linux / Codespaces 中启动 Web 服务（无桌面窗口，用浏览器访问）
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${EDUFLOW_HOST:-0.0.0.0}"
PORT="${EDUFLOW_PORT:-8765}"

if [ ! -d "frontend/node_modules" ]; then
  echo "==> 未找到前端依赖，开始安装"
  (cd frontend && npm install --no-audit --no-fund)
fi

# 默认每次启动都重新构建，保证 git pull 后的新前端能生效；
# 想跳过可设 EDUFLOW_REBUILD=0
if [ ! -f "frontend/dist/index.html" ] || [ "${EDUFLOW_REBUILD:-1}" = "1" ]; then
  echo "==> 构建前端"
  (cd frontend && npm run build)
fi

echo "==> 启动 EduFlow：http://${HOST}:${PORT}"
exec python -m backend.cli serve --host "$HOST" --port "$PORT"
