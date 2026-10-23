"""最小的 HTTP 路由表。

支持 /api/courses/<int:course_id>/assignments/<int:aid> 这类路径参数，
不依赖任何三方框架，编译成正则后匹配，性能足够。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.core.errors import MethodNotAllowedError, NotFoundError
from backend.http.request import Request
from backend.http.response import Response

Handler = Callable[[Request], Response]

_PARAM_RE = re.compile(r"<(?P<type>int|str|path):(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>")
_CONVERTERS: dict[str, str] = {
    "int": r"(?P<%s>\d+)",
    "str": r"(?P<%s>[^/]+)",
    "path": r"(?P<%s>.+)",
}


@dataclass
class Route:
    method: str
    pattern: str
    regex: re.Pattern[str]
    handler: Handler
    auth: bool = True
    roles: tuple[str, ...] = ()
    name: str = ""
    summary: str = ""
    param_types: dict[str, str] = field(default_factory=dict)

    def match(self, path: str) -> dict[str, Any] | None:
        matched = self.regex.fullmatch(path)
        if not matched:
            return None
        params: dict[str, Any] = {}
        for key, raw in matched.groupdict().items():
            if self.param_types.get(key) == "int":
                params[key] = int(raw)
            else:
                params[key] = raw
        return params


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []
        self._by_method: dict[str, list[Route]] = {}

    # -- 注册 -------------------------------------------------------------

    def add(
        self,
        method: str,
        pattern: str,
        handler: Handler,
        *,
        auth: bool = True,
        roles: tuple[str, ...] = (),
        name: str = "",
        summary: str = "",
    ) -> Route:
        regex, param_types = self._compile(pattern)
        route = Route(
            method=method.upper(),
            pattern=pattern,
            regex=regex,
            handler=handler,
            auth=auth,
            roles=roles,
            name=name or handler.__name__,
            summary=summary,
            param_types=param_types,
        )
        self._routes.append(route)
        self._by_method.setdefault(route.method, []).append(route)
        return route

    def _compile(self, pattern: str) -> tuple[re.Pattern[str], dict[str, str]]:
        param_types: dict[str, str] = {}

        def replace(match: re.Match[str]) -> str:
            kind = match.group("type")
            name = match.group("name")
            param_types[name] = kind
            return _CONVERTERS[kind] % name

        regex_text = _PARAM_RE.sub(replace, pattern)
        return re.compile(regex_text), param_types

    # -- 便捷装饰器 -------------------------------------------------------

    def get(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self._decorator("GET", pattern, **kwargs)

    def post(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self._decorator("POST", pattern, **kwargs)

    def put(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self._decorator("PUT", pattern, **kwargs)

    def patch(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self._decorator("PATCH", pattern, **kwargs)

    def delete(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        return self._decorator("DELETE", pattern, **kwargs)

    def _decorator(self, method: str, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
        def wrapper(handler: Handler) -> Handler:
            self.add(method, pattern, handler, **kwargs)
            return handler

        return wrapper

    def include(self, other: "Router") -> None:
        """把另一个路由表合并进来。"""
        for route in other._routes:
            self._routes.append(route)
            self._by_method.setdefault(route.method, []).append(route)

    # -- 匹配 -------------------------------------------------------------

    def resolve(self, method: str, path: str) -> tuple[Route, dict[str, Any]]:
        candidates = self._by_method.get(method.upper(), [])
        for route in candidates:
            params = route.match(path)
            if params is not None:
                return route, params
        # 路径存在但方法不对 -> 405
        for routes in self._by_method.values():
            for route in routes:
                if route.match(path) is not None:
                    raise MethodNotAllowedError(
                        f"{path} 不支持 {method} 方法",
                        details={"allow": self.allowed_methods(path)},
                    )
        raise NotFoundError(f"接口不存在：{path}")

    def allowed_methods(self, path: str) -> list[str]:
        methods = []
        for routes in self._by_method.values():
            for route in routes:
                if route.match(path) is not None:
                    methods.append(route.method)
                    break
        # 静态资源与预检请求
        methods.extend(["OPTIONS"])
        return sorted(set(methods))

    # -- 元信息 -----------------------------------------------------------

    @property
    def routes(self) -> list[Route]:
        return list(self._routes)

    def describe(self) -> list[dict[str, Any]]:
        """给前端「接口文档」页面用的路由清单。"""
        return [
            {
                "method": route.method,
                "pattern": route.pattern,
                "name": route.name,
                "auth": route.auth,
                "roles": list(route.roles),
                "summary": route.summary,
            }
            for route in self._routes
        ]
