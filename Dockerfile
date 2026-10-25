# syntax=docker/dockerfile:1

# ---------- 1. 构建 Vue3 前端 ----------
FROM node:22-bookworm-slim AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Python 运行时 ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    EDUFLOW_HOST=0.0.0.0 \
    EDUFLOW_PORT=8765 \
    EDUFLOW_DATA_DIR=/data

WORKDIR /app
COPY backend ./backend
COPY --from=web /build/frontend/dist ./frontend/dist

RUN mkdir -p /data \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app /data
USER app

EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; p=os.environ.get('PORT') or os.environ.get('EDUFLOW_PORT') or '8765'; urllib.request.urlopen('http://127.0.0.1:' + p + '/api/health', timeout=2)"

# 不写死 --port：config.PORT 会读取 EDUFLOW_PORT 或平台注入的 PORT
CMD ["python", "-m", "backend.cli", "serve", "--host", "0.0.0.0"]
