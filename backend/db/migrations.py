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
CURRENT_VERSION = 4


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


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """v2 -> v3：新增作业附件表（幂等）。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS assignment_files (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename      TEXT    NOT NULL,
            stored_name   TEXT    NOT NULL UNIQUE,
            size          INTEGER NOT NULL DEFAULT 0,
            mime          TEXT,
            created_at    TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_assignment_files_owner
            ON assignment_files(assignment_id, student_id);
        """
    )


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """v3 -> v4：新增章节、任务点与学习进度表（幂等）。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS chapters (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title       TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            order_no    INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chapters_course ON chapters(course_id, order_no);

        CREATE TABLE IF NOT EXISTS tasks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id    INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            type          TEXT    NOT NULL DEFAULT 'material'
                          CHECK (type IN ('material', 'assignment', 'quiz', 'discussion', 'text')),
            title         TEXT    NOT NULL,
            description   TEXT    NOT NULL DEFAULT '',
            duration      INTEGER NOT NULL DEFAULT 0,
            required      INTEGER NOT NULL DEFAULT 1,
            resource_id   INTEGER REFERENCES resources(id) ON DELETE SET NULL,
            quiz_id       INTEGER REFERENCES quizzes(id) ON DELETE SET NULL,
            assignment_id INTEGER REFERENCES assignments(id) ON DELETE SET NULL,
            order_no      INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL,
            updated_at    TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_chapter ON tasks(chapter_id, order_no);

        CREATE TABLE IF NOT EXISTS task_progress (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status      TEXT    NOT NULL DEFAULT 'in_progress'
                        CHECK (status IN ('in_progress', 'completed')),
            progress    INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
            started_at  TEXT,
            finished_at TEXT,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            UNIQUE (task_id, student_id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_progress_student ON task_progress(student_id);
        CREATE INDEX IF NOT EXISTS idx_task_progress_task    ON task_progress(task_id, status);
        """
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
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
        "assignment_files",
        "task_progress",
        "tasks",
        "chapters",
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
