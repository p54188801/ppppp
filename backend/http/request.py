"""HTTP 请求对象。

把 http.server 的原始输入整理成好用的结构：
路径参数、查询串、JSON 体、当前登录用户、客户端 IP。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.config import MAX_BODY_BYTES
from backend.core.errors import TooLargeError, ValidationError
from backend.core.ids import safe_int


@dataclass
class Request:
    method: str
    raw_path: str
    headers: dict[str, str]
    body: bytes
    client_ip: str = "127.0.0.1"
    # 路由匹配后填充
    path_params: dict[str, Any] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)
    user: dict[str, Any] | None = None
    session_token: str | None = None
    # 业务侧可挂载的临时数据（如审计上下文）
    context: dict[str, Any] = field(default_factory=dict)

    # -- 基础属性 ---------------------------------------------------------

    @property
    def path(self) -> str:
        return urlparse(self.raw_path).path.rstrip("/") or "/"

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)

    @property
    def bearer_token(self) -> str | None:
        auth = self.header("authorization")
        if not auth:
            return None
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return None

    @property
    def is_json(self) -> bool:
        content_type = self.header("content-type")
        return "application/json" in content_type.lower()

    # -- 参数 -------------------------------------------------------------

    def param(self, name: str, default: Any = None) -> Any:
        if name in self.path_params:
            return self.path_params[name]
        return self.query.get(name, default)

    def int_param(self, name: str, default: int = 0) -> int:
        value = self.param(name)
        if value is None or value == "":
            return default
        if isinstance(value, int):
            return value
        return safe_int(value, default)

    def str_param(self, name: str, default: str = "") -> str:
        value = self.param(name)
        if value is None:
            return default
        return str(value)

    def bool_param(self, name: str, default: bool = False) -> bool:
        value = self.param(name)
        if value is None:
            return default
        return str(value).lower() in {"1", "true", "yes", "on"}

    # -- 请求体 -----------------------------------------------------------

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        if len(self.body) > MAX_BODY_BYTES:
            raise TooLargeError("请求体过大")
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("请求体不是合法的 JSON") from exc
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValidationError("请求体必须是 JSON 对象")
        return data

    def json_list(self) -> list[Any]:
        if not self.body:
            return []
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("请求体不是合法的 JSON") from exc
        if not isinstance(data, list):
            raise ValidationError("请求体必须是 JSON 数组")
        return data

    # -- 鉴权辅助 ---------------------------------------------------------

    def require_user(self) -> dict[str, Any]:
        if not self.user:
            from backend.core.errors import UnauthorizedError

            raise UnauthorizedError()
        return self.user

    def has_role(self, *roles: str) -> bool:
        return bool(self.user) and self.user.get("role") in roles

    def is_admin(self) -> bool:
        return self.has_role("admin")

    def is_teacher(self) -> bool:
        return self.has_role("teacher", "admin")

    @property
    def user_id(self) -> int:
        return int(self.user["id"]) if self.user else 0


def parse_query(raw_path: str) -> dict[str, str]:
    """取查询串里每个键的第一个值。"""
    parsed = urlparse(raw_path)
    result: dict[str, str] = {}
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        result[key] = values[0] if values else ""
    return result


def parse_headers(items: list[tuple[str, str]]) -> dict[str, str]:
    return {key.lower(): value for key, value in items}


def build_request(method: str, raw_path: str, headers: list[tuple[str, str]],
                  body: bytes, client_ip: str) -> Request:
    header_map = parse_headers(headers)
    return Request(
        method=method.upper(),
        raw_path=raw_path,
        headers=header_map,
        body=body,
        client_ip=client_ip,
        query=parse_query(raw_path),
    )


def decode_path_segment(segment: str) -> str:
    return unquote(segment)
