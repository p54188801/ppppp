"""桌面端入口：启动内置服务 + pywebview 窗口。

用法：
    python run.py                 # 正常启动（窗口模式）
    python run.py --browser       # 不建窗口，直接在系统浏览器打开
    python run.py --port 9000     # 指定端口
    python run.py --no-seed       # 不自动灌演示数据
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from backend import config
from backend.app import Application
from backend.db import migrations
from backend.db.seed import is_seeded, seed
from backend.http.server import HttpServer

logger = logging.getLogger("eduflow.run")

WINDOW_TITLE = f"{config.APP_NAME} v{config.APP_VERSION}"
WINDOW_SIZE = (1360, 860)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def find_free_port(host: str, start: int) -> int:
    """端口被占用时向后顺延，最多尝试 20 个。"""
    for offset in range(20):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"在 {start} 之后找不到可用端口")


def bootstrap(data_seed: bool = True) -> Application:
    config.ensure_dirs()
    migrations.init_db()
    if data_seed and not is_seeded():
        logger.info("正在写入演示数据……")
        result = seed()
        logger.info("演示数据写入完成：%s", result.get("created"))
    return Application()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=config.APP_DESCRIPTION)
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--browser", action="store_true", help="用系统浏览器打开")
    parser.add_argument("--no-seed", action="store_true", help="不初始化演示数据")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--debug", action="store_true", help="开启 webview 调试")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    app = bootstrap(data_seed=not args.no_seed)
    logger.info("自检结果：%s", app.self_test())

    port = find_free_port(args.host, args.port)
    server = HttpServer(app.dispatch, host=args.host, port=port).start()
    if not server.wait_ready(timeout=8):
        logger.error("HTTP 服务启动失败")
        return 1
    url = server.url
    logger.info("服务地址：%s", url)

    if not app.static.exists():
        logger.warning(
            "未检测到前端构建产物（%s），请先执行：cd frontend && npm install && npm run build",
            config.FRONTEND_DIST,
        )

    if args.browser:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，退出")
        finally:
            server.stop()
        return 0

    try:
        import webview
    except ImportError:
        logger.error("未安装 pywebview，可执行 pip install pywebview，或使用 --browser 模式")
        server.stop()
        return 1

    window = webview.create_window(
        WINDOW_TITLE,
        url=url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=(1024, 700),
        background_color="#0d1117",
        text_select=True,
    )

    def _watchdog() -> None:
        """窗口关闭后让主进程退出，避免残留后台服务。"""
        while True:
            time.sleep(0.5)
            try:
                if not window.events.closed.wait(0.1):
                    continue
            except Exception:  # noqa: BLE001
                continue
            break
        time.sleep(0.2)
        server.stop()

    threading.Thread(target=_watchdog, name="window-watchdog", daemon=True).start()

    try:
        # gui="edgechromium" 强制使用 WebView2，和前端构建目标一致
        webview.start(gui="edgechromium", debug=args.debug)
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
