"""SQLite 连接管理与查询辅助函数。

要点：
- HTTP 服务器是多线程的，sqlite3 连接不能跨线程共享，
  这里用 threading.local 为每个线程各持有一个连接；
- 打开 WAL 模式，读写并发更好，也能避免大量 "database is locked"；
- 事务统一通过 transaction() 上下文管理器，异常自动回滚。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from backend import config

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False


def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        timeout=15.0,
        isolation_level=None,  # 手动管理事务
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_connection() -> sqlite3.Connection:
    """取得当前线程的连接，没有就新建。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _open(config.DB_PATH)
        _local.conn = conn
    return conn


def close_connection() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None


def init_connection() -> None:
    """首次连接时设置 WAL（只需要一次）。"""
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        conn = get_connection()
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_autocheckpoint = 256")
        _initialized = True


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """显式事务：成功提交，异常回滚。"""
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# ---------------------------------------------------------------------------
# 查询辅助
# ---------------------------------------------------------------------------


def query_all(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    cur = get_connection().execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return [dict(row) for row in rows]


def query_one(sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
    cur = get_connection().execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return dict(row) if row else None


def scalar(sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
    cur = get_connection().execute(sql, params)
    row = cur.fetchone()
    cur.close()
    if row is None:
        return default
    return row[0]


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    """执行写语句，返回 lastrowid（无则返回受影响行数）。"""
    conn = get_connection()
    cur = conn.execute(sql, params)
    rowid = cur.lastrowid
    affected = cur.rowcount
    cur.close()
    return int(rowid) if rowid else int(affected)


def execute_many(sql: str, seq: Sequence[Sequence[Any]]) -> int:
    conn = get_connection()
    cur = conn.executemany(sql, seq)
    affected = cur.rowcount
    cur.close()
    return int(affected)


def column_exists(table: str, column: str) -> bool:
    rows = query_all(f"PRAGMA table_info({table})")
    return any(row.get("name") == column for row in rows)


def table_exists(table: str) -> bool:
    row = query_one(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    )
    return row is not None
