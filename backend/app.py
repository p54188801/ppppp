"""应用装配。

把路由、认证、静态资源、错误处理串起来，形成一个可直接挂到
HttpServer 上的 dispatch 函数。
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import unquote

from backend import config
from backend.core.errors import AppError, ForbiddenError, NotFoundError, UnauthorizedError
from backend.http.request import Request
from backend.http.response import Response, error_response, json_response, ok
from backend.http.router import Router
from backend.http.static import StaticFiles

logger = logging.getLogger("eduflow.app")


class Application:
    def __init__(self) -> None:
        self.router = Router()
        self.static = StaticFiles(config.FRONTEND_DIST, spa_fallback=True)
        self._register_routes()

    # -- 装配 -------------------------------------------------------------

    def _register_routes(self) -> None:
        from backend.api import (
            timetable_routes,
            group_routes,
            assignment_routes,
            attendance_routes,
            auth_routes,
            chapter_routes,
            content_routes,
            course_routes,
            grade_routes,
            quiz_routes,
            report_routes,
            system_routes,
            user_routes,
        )

        for module in (
            auth_routes,
            user_routes,
            course_routes,
            chapter_routes,
            assignment_routes,
            quiz_routes,
            attendance_routes,
            grade_routes,
            content_routes,
            report_routes,
            system_routes,
            group_routes,
            timetable_routes,
        ):
            self.router.include(module.router)

        # 让 /api/routes 能拿到装配好的应用
        system_routes.bind_application(self)

    # -- 认证 -------------------------------------------------------------

    def authenticate(self, request: Request) -> None:
        token = request.bearer_token
        if not token:
            token = request.header("x-auth-token")
        if not token:
            cookie = request.header("cookie")
            if cookie:
                token = _cookie_value(cookie, config.SESSION_COOKIE_NAME)
        if not token:
            token = request.str_param("token") or None

        if not token:
            return
        from backend.services import auth_service

        user = auth_service.resolve_session(token)
        if user:
            request.user = user
            request.session_token = token

    # -- 分发 -------------------------------------------------------------

    def dispatch(self, request: Request) -> Response:
        started = time.perf_counter()
        request_id = f"{int(started * 1000) % 10 ** 9:09d}"
        try:
            if request.method == "OPTIONS":
                return Response(status=204, body=b"", content_type="text/plain; charset=utf-8")

            self.authenticate(request)
            if request.user and request.user.get("must_change_password"):
                allowed = ("/api/auth/me", "/api/auth/password", "/api/auth/logout", "/api/meta", "/api/health")
                if request.path not in allowed:
                    raise ForbiddenError("请先修改初始密码", code="password_change_required")
            response = self._dispatch_api(request)
        except AppError as exc:
            logger.info("%s %s -> %s %s", request.method, request.path, exc.status, exc.message)
            response = error_response(exc)
        except Exception:  # noqa: BLE001
            logger.exception("未预期异常 %s %s", request.method, request.raw_path)
            response = json_response(
                {"ok": False, "error": {"code": "internal_error", "message": "服务器内部错误"}},
                status=500,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers.setdefault("Server-Timing", f"app;dur={elapsed_ms:.1f}")
        response.headers.setdefault("X-Request-Id", request_id)
        if elapsed_ms > 800:
            logger.warning("慢请求 %s %s 耗时 %.0fms", request.method, request.path, elapsed_ms)
        return response

    def _dispatch_api(self, request: Request) -> Response:
        if request.method == "HEAD":
            request_method = "GET"
        else:
            request_method = request.method

        if not request.path.startswith("/api/"):
            return self._serve_static(request)

        route, params = self.router.resolve(request_method, request.path)
        request.path_params = params

        if route.auth and not request.user:
            raise UnauthorizedError("登录已失效，请重新登录")
        if route.roles:
            if not request.user or request.user.get("role") not in route.roles:
                raise ForbiddenError("当前角色无权执行该操作")

        return route.handler(request)

    def _serve_static(self, request: Request) -> Response:
        path = unquote(request.path)
        if not self.static.exists():
            raise NotFoundError(
                "前端资源未构建，请先在 frontend 目录执行 npm install && npm run build"
            )
        return self.static.serve(path, cache=True)

    # -- 元信息 -----------------------------------------------------------

    def describe_routes(self) -> dict[str, Any]:
        routes = self.router.describe()
        grouped: dict[str, int] = {}
        for item in routes:
            prefix = "/".join(item["pattern"].split("/")[:3])
            grouped[prefix] = grouped.get(prefix, 0) + 1
        return {
            "total": len(routes),
            "groups": grouped,
            "routes": routes,
        }

    def self_test(self) -> dict[str, Any]:
        """启动时的自检：数据库、前端、目录。"""
        from backend.db import connection

        checks: dict[str, Any] = {}
        try:
            connection.scalar("SELECT 1")
            checks["database"] = True
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"failed: {exc}"
        checks["frontend_built"] = self.static.exists()
        checks["routes"] = len(self.router.routes)
        return checks


def _cookie_value(cookie_header: str, name: str) -> str | None:
    for chunk in cookie_header.split(";"):
        key, _, value = chunk.strip().partition("=")
        if key == name:
            return value or None
    return None


# 全局单例，供 system_routes 之类的地方反查路由表
application = Application()
