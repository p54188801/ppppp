"""静态资源服务。

前端是 Vue3 + Vite 打包出的 SPA，这里负责：
- 命中真实文件就直接返回（带缓存头）；
- 命中目录则回退到 index.html（history 路由）；
- 严格校验路径，防止 ../ 穿越到项目外。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from backend.config import STATIC_CACHE_SECONDS
from backend.core.errors import ForbiddenError, NotFoundError
from backend.http.response import Response

# 常见前端资源，省去每次查表
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("font/woff2", ".woff2")


class StaticFiles:
    def __init__(self, root: Path, *, spa_fallback: bool = True) -> None:
        self.root = root.resolve()
        self.spa_fallback = spa_fallback

    def exists(self) -> bool:
        return self.root.exists() and (self.root / "index.html").exists()

    def resolve(self, url_path: str) -> Path | None:
        """把 URL 路径映射到磁盘文件；越界返回 None。"""
        relative = url_path.lstrip("/")
        if not relative:
            relative = "index.html"
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            return None
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            index = candidate / "index.html"
            if index.is_file():
                return index
        return None

    def serve(self, url_path: str, *, cache: bool = True) -> Response:
        target = self.resolve(url_path)
        if target is None:
            if self.spa_fallback and "." not in Path(url_path).name:
                index = self.root / "index.html"
                if index.is_file():
                    return self._read(index, url_path, cache=False)
            raise NotFoundError(f"静态资源不存在：{url_path}")
        return self._read(target, url_path, cache=cache)

    def _read(self, path: Path, url_path: str, *, cache: bool) -> Response:
        mime, _ = mimetypes.guess_type(str(path))
        content_type = mime or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
            "image/svg+xml",
        }:
            content_type += "; charset=utf-8"
        body = path.read_bytes()
        headers = {}
        if cache:
            headers["Cache-Control"] = f"public, max-age={STATIC_CACHE_SECONDS}"
        else:
            headers["Cache-Control"] = "no-cache"
        # 带 hash 的构建产物可以长缓存
        if "/assets/" in url_path:
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return Response(status=200, body=body, content_type=content_type, headers=headers)


def safe_join(root: Path, *parts: str) -> Path:
    """拼接路径并确保结果在 root 内，用于上传文件下载。"""
    root = root.resolve()
    target = root.joinpath(*parts).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ForbiddenError("非法路径") from None
    return target
