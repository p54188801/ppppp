"""极简 multipart/form-data 解析器。

只支持本应用需要的场景：
- 一个或多个文本字段
- 一个或零个文件字段
不处理嵌套、不处理 quoted-printable，够用且代码可控。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.core.errors import ValidationError

_BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)


@dataclass
class UploadedFile:
    field_name: str
    filename: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass
class MultipartForm:
    fields: dict[str, str] = field(default_factory=dict)
    files: dict[str, UploadedFile] = field(default_factory=dict)

    def get(self, name: str, default: str = "") -> str:
        return self.fields.get(name, default)

    def file(self, name: str) -> UploadedFile | None:
        return self.files.get(name)

    def first_file(self) -> UploadedFile | None:
        return next(iter(self.files.values()), None)


def is_multipart(content_type: str) -> bool:
    return "multipart/form-data" in (content_type or "").lower()


def parse_multipart(body: bytes, content_type: str) -> MultipartForm:
    matched = _BOUNDARY_RE.search(content_type or "")
    if not matched:
        raise ValidationError("multipart 请求缺少 boundary")
    boundary = matched.group(1).encode("utf-8")
    delimiter = b"--" + boundary

    form = MultipartForm()
    parts = body.split(delimiter)
    for part in parts:
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, content = part.split(b"\r\n\r\n", 1)
        if content.endswith(b"\r\n"):
            content = content[:-2]
        headers = _parse_part_headers(raw_headers)
        disposition = headers.get("content-disposition", "")
        name_match = re.search(r'name="([^"]*)"', disposition)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if filename_match:
            form.files[name] = UploadedFile(
                field_name=name,
                filename=filename_match.group(1),
                content_type=headers.get("content-type", "application/octet-stream"),
                data=content,
            )
        else:
            form.fields[name] = content.decode("utf-8", errors="replace")
    return form


def _parse_part_headers(raw: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in raw.split(b"\r\n"):
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        headers[key.decode("latin-1").strip().lower()] = value.decode("latin-1").strip()
    return headers


def form_to_dict(form: MultipartForm) -> dict[str, Any]:
    payload: dict[str, Any] = dict(form.fields)
    if form.files:
        payload["_files"] = {name: file for name, file in form.files.items()}
    return payload
