"""内置 HTTP 服务器。

用标准库的 ThreadingHTTPServer 承载，够轻量，且不引入第三方依赖。
职责很纯粹：收请求 -> 交给 dispatch -> 把 Response 写回去。
业务逻辑全部在 router / api / services 里。
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from backend import config
from backend.core.errors import AppError, TooLargeError
from backend.http.request import Request, build_request
from backend.http.response import Response, error_response, json_response

logger = logging.getLogger("eduflow.http")

Dispatch = Callable[[Request], Response]


class _RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = config.SERVER_NAME
    sys_version = ""

    # 静默默认日志，改用我们自己的 logger
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        logger.debug("%s - %s", self.client_address[0], fmt % args)

    # -- 各方法入口 -------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle("HEAD")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle("OPTIONS")

    # -- 核心流程 ---------------------------------------------------------

    def _read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            return b""
        try:
            length = int(raw_length)
        except ValueError:
            raise TooLargeError("Content-Length 不合法") from None
        if length < 0:
            return b""
        if length > config.MAX_BODY_BYTES:
            raise TooLargeError("请求体超过限制")
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _handle(self, method: str) -> None:
        try:
            body = self._read_body()
            request = build_request(
                method=method,
                raw_path=self.path,
                headers=list(self.headers.items()),
                body=body,
                client_ip=self.client_address[0],
            )
            response = self.server.dispatch(request)  # type: ignore[attr-defined]
        except AppError as exc:
            response = error_response(exc)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("未处理异常: %s", exc)
            response = json_response(
                {
                    "ok": False,
                    "error": {"code": "internal_error", "message": "服务器内部错误"},
                },
                status=500,
            )
        try:
            self._write_response(response, method)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _write_response(self, response: Response, method: str) -> None:
        if method == "HEAD":
            body = b""
        else:
            body = response.body
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        origin = self.headers.get("Origin", "")
        if self._origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Vary", "Origin")
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    @staticmethod
    def _origin_allowed(origin: str) -> bool:
        if not origin:
            return False
        return any(
            host in origin
            for host in ("http://localhost", "http://127.0.0.1", "http://[::1]")
        )


class _ThreadingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler_factory, dispatch: Dispatch) -> None:
        self.dispatch = dispatch  # type: ignore[assignment]
        super().__init__(address, handler_factory)


class HttpServer:
    """对 ThreadingHTTPServer 的封装，支持后台线程启动与优雅停止。"""

    def __init__(self, dispatch: Dispatch, host: str = config.HOST, port: int = config.PORT) -> None:
        self.dispatch = dispatch
        self.host = host
        self.port = port
        self._server: _ThreadingServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, *, background: bool = True) -> "HttpServer":
        self._server = _ThreadingServer(
            (self.host, self.port), _RequestHandler, self.dispatch
        )
        # 端口传 0 时由系统分配，回读真实端口
        self.port = self._server.server_address[1]
        if background:
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="eduflow-http",
                daemon=True,
            )
            self._thread.start()
        logger.info("HTTP 服务已启动: %s", self.url)
        return self

    def serve_forever(self) -> None:
        if self._server is None:
            self.start(background=False)
        assert self._server is not None
        self._server.serve_forever()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("HTTP 服务已停止")

    def wait_ready(self, timeout: float = 5.0) -> bool:
        """等待端口真正可连接，用于 pywebview 启动前自检。"""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.25)
                if sock.connect_ex((self.host, self.port)) == 0:
                    return True
            time.sleep(0.05)
        return False

    def __enter__(self) -> "HttpServer":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()


def read_json_body(raw: bytes) -> dict:
    """给非 Request 场景留的兜底解析。"""
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))
