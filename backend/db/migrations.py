"""数据库初始化与版本迁移。

当前只有 schema v1，但保留迁移框架，后续加字段只需要在
MIGRATIONS 里追加一个 (版本号, 函数) 即可。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from backend import config
from backend.core import clock
from backend.db import connection

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
CURRENT_VERSION = 2


def _read_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def get_version() -> int:
    return int(connection.scalar("PRAGMA user_version", default=0) or 0)


def _set_version(version: int) -> None:
    connection.get_connection().execute(f"PRAGMA user_version = {int(version)}")


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """v0 -> v1：建表。"""
    conn.executescript(_read_schema())


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """v1 -> v2：新增课程公告表（幂等）。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title      TEXT    NOT NULL,
            content    TEXT    NOT NULL DEFAULT '',
            author_id  INTEGER NOT NULL REFERENCES users(id),
            pinned     INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL,
            updated_at TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_announcements_course ON announcements(course_id);
        """
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
]


def init_db() -> None:
    """建库建表，可重复调用。"""
    config.ensure_dirs()
    connection.init_connection()
    version = get_version()
    if version >= CURRENT_VERSION:
        _ensure_settings()
        return
    for target, func in MIGRATIONS:
        if version < target:
            # 注意：executescript 会隐式提交，不能包在 BEGIN IMMEDIATE 里，
            # 否则 COMMIT 时会报 "no transaction is active"。
            # 每个迁移函数内部自行保证原子性。
            func(connection.get_connection())
            _set_version(target)
            version = target
    _ensure_settings()


def _ensure_settings() -> None:
    """写入默认系统设置（已存在则跳过）。"""
    defaults = {
        "term": clock.term_of(),
        "school_name": "EduFlow 大学",
        "grade_weights": "0.30,0.30,0.20,0.20",
        "attendance_late_minutes": str(config.ATTENDANCE_LATE_MINUTES),
        "initialized": "1",
    }
    existing = {
        row["key"] for row in connection.query_all("SELECT key FROM system_settings")
    }
    now = clock.now_iso()
    for key, value in defaults.items():
        if key in existing:
            continue
        connection.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now),
        )


def reset_db() -> None:
    """清空数据表（保留结构），仅供开发/测试使用。"""
    tables = [
        "sessions",
        "login_attempts",
        "enrollments",
        "submissions",
        "assignments",
        "quiz_attempts",
        "questions",
        "quizzes",
        "attendance_records",
        "attendance_sessions",
        "resources",
        "discussion_replies",
        "discussions",
        "announcements",
        "notifications",
        "grade_items",
        "grade_rules",
        "audit_logs",
        "classes",
        "courses",
        "users",
        "system_settings",
    ]
    with connection.transaction() as conn:
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")
    _ensure_settings()
