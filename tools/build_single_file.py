"""把分散的 backend 模块合并成一个可运行的单文件系统。

思路：
- 用 ast 精确剥掉模块间的 `from backend... import ...`，把依赖改成函数参数；
- 每个模块包成一个函数，函数返回 SimpleNamespace（相当于模块对象）；
- 尾部按依赖顺序实例化，再拼出 Application / main。

产物：eduflow_all.py，单个文件、可直接运行。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

SRC = Path(r"D:\EduFlow")
OUT = Path(r"D:\EduFlow\eduflow_all.py")

# (命名空间变量名, 相对路径)  —— 顺序即依赖顺序
MODULES: list[tuple[str, str]] = [
    ("config", "backend/config.py"),
    ("ids", "backend/core/ids.py"),
    ("clock", "backend/core/clock.py"),
    ("errors", "backend/core/errors.py"),
    ("security", "backend/core/security.py"),
    ("validators", "backend/core/validators.py"),
    ("permissions", "backend/core/permissions.py"),
    ("response_lib", "backend/http/response.py"),
    ("static_lib", "backend/http/static.py"),
    ("connection", "backend/db/connection.py"),
    ("backup_service", "backend/services/backup_service.py"),
    ("migrations", "backend/db/migrations.py"),
    ("base_repo", "backend/repositories/base.py"),
    ("users_repo", "backend/repositories/users.py"),
    ("courses_repo", "backend/repositories/courses.py"),
    ("assignments_repo", "backend/repositories/assignments.py"),
    ("quizzes_repo", "backend/repositories/quizzes.py"),
    ("attendance_repo", "backend/repositories/attendance.py"),
    ("content_repo", "backend/repositories/content.py"),
    ("grades_repo", "backend/repositories/grades.py"),
    ("audit_repo", "backend/repositories/audit.py"),
    ("chapters_repo", "backend/repositories/chapters.py"),
    ("search_service", "backend/services/search_service.py"),
    ("auth_service", "backend/services/auth_service.py"),
    ("notification_service", "backend/services/notification_service.py"),
    ("announcement_service", "backend/services/announcement_service.py"),
    ("attachment_service", "backend/services/attachment_service.py"),
    ("user_service", "backend/services/user_service.py"),
    ("course_service", "backend/services/course_service.py"),
    ("assignment_service", "backend/services/assignment_service.py"),
    ("quiz_service", "backend/services/quiz_service.py"),
    ("attendance_service", "backend/services/attendance_service.py"),
    ("grade_service", "backend/services/grade_service.py"),
    ("resource_service", "backend/services/resource_service.py"),
    ("discussion_service", "backend/services/discussion_service.py"),
    ("chapter_service", "backend/services/chapter_service.py"),
    ("statistics_service", "backend/services/statistics_service.py"),
    ("request_lib", "backend/http/request.py"),
    ("router_lib", "backend/http/router.py"),
    ("multipart_lib", "backend/http/multipart.py"),
    ("server_lib", "backend/http/server.py"),
    ("seed_lib", "backend/db/seed.py"),
    ("auth_api", "backend/api/auth_routes.py"),
    ("user_api", "backend/api/user_routes.py"),
    ("course_api", "backend/api/course_routes.py"),
    ("chapter_api", "backend/api/chapter_routes.py"),
    ("assignment_api", "backend/api/assignment_routes.py"),
    ("quiz_api", "backend/api/quiz_routes.py"),
    ("attendance_api", "backend/api/attendance_routes.py"),
    ("grade_api", "backend/api/grade_routes.py"),
    ("content_api", "backend/api/content_routes.py"),
    ("report_api", "backend/api/report_routes.py"),
    ("system_api", "backend/api/system_routes.py"),
]

# 模块路径 -> 命名空间变量名
MOD_TO_NS = {rel.replace("/", ".")[:-3]: ns for ns, rel in MODULES}
MOD_TO_NS["backend.config"] = "config"


def module_path_of(name: str) -> str:
    """backend/xxx/yyy.py -> backend.xxx.yyy"""
    return name.replace("/", ".")[:-3]


def strip_backend_imports(text: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """返回（去掉跨模块 import 后的源码, [(模块路径, [导入名])])."""
    tree = ast.parse(text)
    lines = text.splitlines()
    drop: set[int] = set()
    deps: list[tuple[str, list[str]]] = []

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "backend" or module.startswith("backend."):
                for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    drop.add(lineno)
                names = [alias.name for alias in node.names]
                deps.append((module, names))
            elif node.level:
                # 相对导入，本项目没用
                pass
        elif isinstance(node, ast.Import):
            if all(a.name.startswith("backend") for a in node.names):
                for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    drop.add(lineno)

    kept = [line for idx, line in enumerate(lines, start=1) if idx not in drop]
    # 去掉 __future__（文件头统一加一份）
    kept = [line for line in kept if not line.strip().startswith("from __future__")]
    return "\n".join(kept), deps


def public_names(text: str) -> list[str]:
    tree = ast.parse(text)
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.append(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                names.append(node.target.id)
    # 去重保序
    return list(dict.fromkeys(names))


def dep_expression(module: str, name: str) -> str:
    # from backend import config / from backend.core import ids —— 导入的是子模块
    as_module = f"{module}.{name}"
    if as_module in MOD_TO_NS:
        return MOD_TO_NS[as_module]
    if module == "backend":
        return name
    ns = MOD_TO_NS[module]
    last = module.rsplit(".", 1)[-1]
    if name == last:
        return ns
    return f"{ns}.{name}"


def indent(text: str, spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join((pad + line) if line.strip() else "" for line in text.splitlines())


def build() -> str:
    chunks: list[str] = []
    instantiate: list[str] = []

    schema_sql = (SRC / "backend/db/schema.sql").read_text(encoding="utf-8")

    for ns, rel in MODULES:
        path = SRC / rel
        raw = path.read_text(encoding="utf-8")
        body, deps = strip_backend_imports(raw)

        # 单文件环境下的路径修正
        if ns == "config":
            body = body.replace(
                "BASE_DIR = Path(__file__).resolve().parent.parent",
                "BASE_DIR = Path(__file__).resolve().parent",
            )
        if ns == "migrations":
            body = body.replace(
                'return SCHEMA_PATH.read_text(encoding="utf-8")', "return SCHEMA_SQL"
            )
        if ns == "connection":
            # 模块被包成函数后，global 要改成 nonlocal 才能写回函数作用域
            body = body.replace("global _initialized", "nonlocal _initialized")

        params = sorted({name for _, names in deps for name in names})
        args = []
        for module, names in deps:
            for name in names:
                if name in params:
                    args.append(f"{name}={dep_expression(module, name)}")
        # 去重（同一名字可能被多个模块导入）
        seen: set[str] = set()
        call_args: list[str] = []
        for item in args:
            key = item.split("=", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            call_args.append(item)

        exported = public_names(raw)
        body_indented = indent(body)
        header = (
            f"\n# {'=' * 70}\n"
            f"# 模块：{rel}\n"
            f"# {'=' * 70}\n"
            f"def _mod_{ns}({', '.join(params)}):\n"
        )
        footer = (
            f"\n    return SimpleNamespace(\n"
            + "".join(f"        {name}={name},\n" for name in exported)
            + "    )\n"
        )
        chunks.append(header + body_indented + footer)
        instantiate.append(f"{ns} = _mod_{ns}({', '.join(call_args)})")

    return "\n".join(chunks), instantiate, schema_sql


HEADER = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EduFlow 教务系统 —— 单文件版。

整个后端（配置、核心工具、数据访问、业务服务、HTTP 层、全部接口、演示数据）
全部合并在本文件中，不依赖任何第三方库（桌面窗口 pywebview 仅在 --web 模式需要）。

用法::

    python eduflow_all.py              # 启动桌面窗口（需要 pywebview）
    python eduflow_all.py serve        # 只启动 HTTP 服务，浏览器访问 8765
    python eduflow_all.py check        # 环境自检
    python eduflow_all.py info         # 数据概览
    python eduflow_all.py seed         # 重新写入演示数据

演示账号：admin / t1001 / s2001，密码统一 Eduflow@2026
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import io
import json
import logging
import math
import mimetypes
import os
import random
import re
import secrets
import socket
import sqlite3
import string
import sys
import threading
import time
import unicodedata
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Iterator, Sequence
from urllib.parse import parse_qs, quote, unquote, urlparse


# ======================================================================
# 数据库表结构（原 backend/db/schema.sql）
# ======================================================================

SCHEMA_SQL = r"""__SCHEMA_SQL__"""
'''

TAIL = '''

# ======================================================================
# 应用装配：把各模块的 router 合并，处理认证 / 静态资源 / 错误
# ======================================================================


class Application:
    def __init__(self) -> None:
        self.router = router_lib.Router()
        self.static = static_lib.StaticFiles(config.FRONTEND_DIST, spa_fallback=True)
        for module in (
            auth_api, user_api, course_api, chapter_api, assignment_api, quiz_api,
            attendance_api, grade_api, content_api, report_api, system_api,
        ):
            self.router.include(module.router)
        system_api.bind_application(self)

    def authenticate(self, request) -> None:
        token = request.bearer_token or request.header("x-auth-token")
        if not token:
            cookie = request.header("cookie")
            if cookie:
                token = _cookie_value(cookie, config.SESSION_COOKIE_NAME)
        if not token:
            token = request.str_param("token") or None
        if not token:
            return
        user = auth_service.resolve_session(token)
        if user:
            request.user = user
            request.session_token = token

    def dispatch(self, request):
        started = time.perf_counter()
        try:
            if request.method == "OPTIONS":
                return response_lib.Response(status=204, body=b"", content_type="text/plain; charset=utf-8")
            self.authenticate(request)
            response = self._dispatch_api(request)
        except errors.AppError as exc:
            response = response_lib.error_response(exc)
        except Exception:
            logging.getLogger("eduflow").exception("未预期异常 %s %s", request.method, request.raw_path)
            response = response_lib.json_response(
                {"ok": False, "error": {"code": "internal_error", "message": "服务器内部错误"}},
                status=500,
            )
        elapsed = (time.perf_counter() - started) * 1000
        response.headers.setdefault("Server-Timing", f"app;dur={elapsed:.1f}")
        return response

    def _dispatch_api(self, request):
        method = "GET" if request.method == "HEAD" else request.method
        if not request.path.startswith("/api/"):
            if not self.static.exists():
                raise errors.NotFoundError("前端资源未构建")
            return self.static.serve(unquote(request.path), cache=True)
        route, params = self.router.resolve(method, request.path)
        request.path_params = params
        if route.auth and not request.user:
            raise errors.UnauthorizedError("登录已失效，请重新登录")
        if route.roles and (not request.user or request.user.get("role") not in route.roles):
            raise errors.ForbiddenError("当前角色无权执行该操作")
        return route.handler(request)

    def describe_routes(self):
        return {"total": len(self.router.routes), "routes": self.router.describe()}

    def self_test(self):
        try:
            connection.scalar("SELECT 1")
            db_ok = True
        except Exception as exc:  # noqa: BLE001
            db_ok = f"failed: {exc}"
        return {
            "database": db_ok,
            "frontend_built": self.static.exists(),
            "routes": len(self.router.routes),
        }


def _cookie_value(cookie_header: str, name: str):
    for chunk in cookie_header.split(";"):
        key, _, value = chunk.strip().partition("=")
        if key == name:
            return value or None
    return None


application = Application()


# ======================================================================
# 命令行入口
# ======================================================================


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def find_free_port(host: str, start: int) -> int:
    for offset in range(20):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError("没有可用端口")


def cmd_init() -> int:
    config.ensure_dirs()
    migrations.init_db()
    print(f"数据库已就绪：{config.DB_PATH}")
    return 0


def cmd_seed(force: bool = False) -> int:
    config.ensure_dirs()
    migrations.init_db()
    print(json.dumps(seed_lib.seed(force=force), ensure_ascii=False, indent=2))
    return 0


def cmd_check() -> int:
    config.ensure_dirs()
    migrations.init_db()
    checks = application.self_test()
    checks["db_path"] = str(config.DB_PATH)
    checks["seeded"] = seed_lib.is_seeded()
    checks["python"] = sys.version.split()[0]
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["database"] is True else 1


def cmd_info() -> int:
    migrations.init_db()
    print(json.dumps(seed_lib.summary(), ensure_ascii=False, indent=2))
    return 0


def cmd_serve(host: str, port: int, open_browser: bool = False) -> int:
    config.ensure_dirs()
    migrations.init_db()
    seed_lib.seed()
    actual = find_free_port(host, port)
    server = server_lib.HttpServer(application.dispatch, host=host, port=actual).start()
    server.wait_ready()
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{actual}"
    print(f"EduFlow 已启动：{url}")
    print("演示账号 admin / t1001 / s2001，密码 Eduflow@2026")
    if open_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def cmd_window(port: int, debug: bool = False) -> int:
    config.ensure_dirs()
    migrations.init_db()
    seed_lib.seed()
    enable_dpi_awareness()
    actual = find_free_port("127.0.0.1", port)
    server = server_lib.HttpServer(application.dispatch, host="127.0.0.1", port=actual).start()
    if not server.wait_ready(timeout=8):
        print("HTTP 服务启动失败", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{actual}"
    try:
        import webview
    except ImportError:
        print("未安装 pywebview，请执行：pip install pywebview", file=sys.stderr)
        print(f"或直接访问：{url}")
        server.stop()
        return 1

    window = webview.create_window(
        f"EduFlow 教务系统 v{config.APP_VERSION}",
        url=None,
        html="<html><body style='margin:0;background:#0d1117;color:#8b949e;"
             "font-family:Segoe UI;display:grid;place-items:center;height:100vh'>"
             "<div>正在启动 EduFlow…</div></body></html>",
        width=1360,
        height=860,
        min_size=(1024, 700),
        background_color="#0d1117",
    )

    def _load():
        time.sleep(0.6)
        try:
            window.load_url(url)
        except Exception:  # noqa: BLE001
            pass

    try:
        webview.start(_load, gui="edgechromium", debug=debug)
    finally:
        server.stop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EduFlow 教务系统（单文件版）")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init")
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--force", action="store_true")
    sub.add_parser("check")
    sub.add_parser("info")

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default=config.HOST)
    p_serve.add_argument("--port", type=int, default=config.PORT)
    p_serve.add_argument("--open", action="store_true")

    p_win = sub.add_parser("window")
    p_win.add_argument("--port", type=int, default=config.PORT)
    p_win.add_argument("--debug", action="store_true")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    if args.command == "init":
        return cmd_init()
    if args.command == "seed":
        return cmd_seed(force=args.force)
    if args.command == "check":
        return cmd_check()
    if args.command == "info":
        return cmd_info()
    if args.command == "serve":
        return cmd_serve(args.host, args.port, open_browser=args.open)
    # 默认：有 pywebview 就开窗口，否则退化为起服务
    try:
        import webview  # noqa: F401
    except ImportError:
        return cmd_serve(config.HOST, config.PORT, open_browser=True)
    return cmd_window(args.port if args.command == "window" else config.PORT,
                      debug=getattr(args, "debug", False))


if __name__ == "__main__":
    sys.exit(main())
'''


def main() -> int:
    chunks = []
    instantiate = []
    schema_sql = ""

    chunks_text, instantiate, schema_sql = build()

    out = HEADER.replace("__SCHEMA_SQL__", schema_sql)
    out += "\n\n# ======================================================================\n"
    out += "# 第一部分：各功能模块（每个模块封装成一个函数，返回命名空间）\n"
    out += "# ======================================================================\n"
    out += chunks_text
    out += "\n\n# ======================================================================\n"
    out += "# 第二部分：按依赖顺序实例化各模块\n"
    out += "# ======================================================================\n\n"
    out += "\n".join(instantiate)
    out += TAIL

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8")
    lines = len(out.splitlines())
    print(f"已生成：{OUT}")
    print(f"总行数：{lines}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
