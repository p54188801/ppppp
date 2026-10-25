"""命令行工具。

    python -m backend.cli init      # 建库
    python -m backend.cli seed      # 灌演示数据
    python -m backend.cli reset     # 清空重建 + 重新灌数据
    python -m backend.cli serve     # 只起 HTTP 服务（不开窗口）
    python -m backend.cli check     # 自检
    python -m backend.cli info      # 数据概览
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from backend import config
from backend.app import Application
from backend.db import migrations
from backend.db.seed import is_seeded, seed, summary
from backend.http.server import HttpServer


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_init(_args) -> int:
    config.ensure_dirs()
    migrations.init_db()
    print(f"数据库已就绪：{config.DB_PATH}")
    print(f"当前版本：{migrations.get_version()}")
    return 0


def cmd_seed(args) -> int:
    config.ensure_dirs()
    migrations.init_db()
    result = seed(force=bool(args.force))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_reset(args) -> int:
    config.ensure_dirs()
    migrations.init_db()
    migrations.reset_db()
    result = seed(force=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_serve(args) -> int:
    config.ensure_dirs()
    migrations.init_db()
    # seed() 幂等：已有演示数据时只补齐后来新增的演示内容（如章节任务点）
    seed()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("提示：当前监听公网地址，部署到公网前请先修改 admin / t1001 / s2001 的默认密码，并启用 HTTPS。")
    app = Application()
    server = HttpServer(app.dispatch, host=args.host, port=args.port).start()
    server.wait_ready()
    print(f"服务已启动：{server.url}")
    print("按 Ctrl+C 停止")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.stop()
    return 0


def cmd_check(_args) -> int:
    config.ensure_dirs()
    migrations.init_db()
    app = Application()
    checks = app.self_test()
    checks["db_path"] = str(config.DB_PATH)
    checks["db_size_kb"] = round(config.DB_PATH.stat().st_size / 1024, 1) if config.DB_PATH.exists() else 0
    checks["seeded"] = is_seeded()
    checks["python"] = sys.version.split()[0]
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["database"] is True else 1


def cmd_info(_args) -> int:
    migrations.init_db()
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eduflow", description=config.APP_DESCRIPTION)
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化数据库").set_defaults(func=cmd_init)

    p_seed = sub.add_parser("seed", help="写入演示数据")
    p_seed.add_argument("--force", action="store_true", help="先清空再写入")
    p_seed.set_defaults(func=cmd_seed)

    sub.add_parser("reset", help="清空并重建").set_defaults(func=cmd_reset)

    p_serve = sub.add_parser("serve", help="仅启动 HTTP 服务")
    p_serve.add_argument("--host", default=config.HOST)
    p_serve.add_argument("--port", type=int, default=config.PORT)
    p_serve.set_defaults(func=cmd_serve)

    sub.add_parser("check", help="环境自检").set_defaults(func=cmd_check)
    sub.add_parser("info", help="数据概览").set_defaults(func=cmd_info)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
