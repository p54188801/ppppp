"""HTTP 响应封装。

统一响应格式：
  成功: {"ok": true, "data": ..., "message": ...}
  失败: {"ok": false, "error": {"code": ..., "message": ..., "details": ...}}
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core.errors import AppError

JSON_CONTENT_TYPE = "application/json; charset=utf-8"


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = JSON_CONTENT_TYPE
    headers: dict[str, str] = field(default_factory=dict)

    def with_header(self, key: str, value: str) -> "Response":
        self.headers[key] = value
        return self

    def to_bytes(self) -> bytes:
        return self.body


def _dumps(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def json_response(payload: Any, status: int = 200) -> Response:
    return Response(status=status, body=_dumps(payload), content_type=JSON_CONTENT_TYPE)


def ok(data: Any = None, message: str | None = None, status: int = 200) -> Response:
    payload: dict[str, Any] = {"ok": True, "data": data}
    if message:
        payload["message"] = message
    return json_response(payload, status)


def created(data: Any = None, message: str = "创建成功") -> Response:
    return ok(data, message, status=201)


def no_content() -> Response:
    return Response(status=204, body=b"", content_type=JSON_CONTENT_TYPE)


def error_response(error: AppError) -> Response:
    return json_response(error.to_dict(), status=error.status)


def text_response(text: str, status: int = 200) -> Response:
    return Response(
        status=status,
        body=text.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )


def redirect(location: str, status: int = 302) -> Response:
    return Response(
        status=status,
        body=b"",
        content_type="text/plain; charset=utf-8",
        headers={"Location": location},
    )


def file_response(path: Path, *, download_name: str | None = None,
                  cache_seconds: int = 0) -> Response:
    if not path.exists() or not path.is_file():
        from backend.core.errors import NotFoundError

        raise NotFoundError("文件不存在")
    mime, _ = mimetypes.guess_type(str(path))
    body = path.read_bytes()
    headers = {"Cache-Control": f"public, max-age={cache_seconds}" if cache_seconds else "no-cache"}
    if download_name:
        from urllib.parse import quote

        headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(download_name)}"
        )
    return Response(
        status=200,
        body=body,
        content_type=(mime or "application/octet-stream") + (
            "; charset=utf-8" if (mime or "").startswith("text/") else ""
        ),
        headers=headers,
    )


def stream_response(chunks, content_type: str = "application/octet-stream") -> Response:
    """把可迭代的字节块拼成一个响应（文件不大时足够用）。"""
    return Response(status=200, body=b"".join(chunks), content_type=content_type)


def paginated(items: list[Any], total: int, page: int, page_size: int) -> Response:
    pages = max(1, (total + page_size - 1) // page_size)
    return ok(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    )
