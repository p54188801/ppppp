#!/usr/bin/env bash
# Codespaces 容器创建后自动执行：装依赖 + 构建前端
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 安装 Python 依赖"
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt || true

echo "==> 安装前端依赖并构建"
cd frontend
npm install --no-audit --no-fund
npm run build
cd ..

echo "==> 初始化数据库（首次会自动写入演示数据）"
python -m backend.cli init
python -m backend.cli seed || true

echo ""
echo "环境就绪。运行：bash scripts/codespace_start.sh"
