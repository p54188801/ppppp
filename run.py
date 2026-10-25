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
from backend.db.seed import seed
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


def enable_dpi_awareness() -> None:
    """声明进程 DPI 感知。

    不声明的话，Windows 在 125%/150% 缩放下会把窗口内 WebView2 的逻辑视口
    放大到超出窗口物理尺寸，右侧内容被裁掉（表现为页面右侧被切）。
    """
    try:
        import ctypes

        # 2 = PER_MONITOR_AWARE_V2，Win8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            logger.debug("当前系统不支持 DPI 感知设置，跳过")


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
    if data_seed:
        logger.info("正在检查/写入演示数据……")
        result = seed()  # 幂等，会补齐新增的演示内容
        logger.info("演示数据就绪：%s", result.get("created") or result.get("chapters"))
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
    enable_dpi_awareness()
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
        # 没装 pywebview 时不要直接失败：退化成浏览器模式，至少能正常用
        logger.warning(
            "未安装 pywebview，已改用浏览器模式；执行 pip install pywebview 可启用桌面窗口"
        )
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到中断信号，退出")
        finally:
            server.stop()
        return 0

    window = webview.create_window(
        WINDOW_TITLE,
        url=None,
        html=(
            "<html><body style='margin:0;background:#0d1117;color:#8b949e;"
            "font-family:Segoe UI,sans-serif;display:grid;place-items:center;"
            "height:100vh'><div>正在启动 EduFlow…</div></body></html>"
        ),
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=(1024, 700),
        background_color="#0d1117",
        text_select=True,
    )

    def _load_app() -> None:
        """等窗口真正显示后再导航。

        直接在 create_window 时传 url，Windows 上偶发 WebView2 首帧不绘制
        （窗口一片底色）；先显示一个占位页、稍后再 load_url 可以稳定规避。
        """
        time.sleep(0.6)
        try:
            window.load_url(url)
        except Exception:  # noqa: BLE001
            logger.exception("加载前端失败")

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
        # gui="edgechromium" 强制使用 WebView2，和前端构建目标一致；
        # func 在 GUI 事件循环启动后于子线程执行，用来延迟加载页面
        webview.start(_load_app, gui="edgechromium", debug=args.debug)
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
