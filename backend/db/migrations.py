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
CURRENT_VERSION = 8


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


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """v4 -> v5：班级群、群消息、群作业、课程推荐。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS class_groups (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            teacher_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS group_members (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id  INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE CASCADE,
            user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role      TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            UNIQUE (group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS group_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE CASCADE,
            sender_id   INTEGER NOT NULL REFERENCES users(id),
            kind        TEXT NOT NULL DEFAULT 'text',
            content     TEXT NOT NULL DEFAULT '',
            file_name   TEXT,
            stored_name TEXT,
            size        INTEGER DEFAULT 0,
            mime        TEXT,
            ref_id      INTEGER,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_group_messages ON group_messages(group_id, id);
        CREATE TABLE IF NOT EXISTS group_assignments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id   INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE CASCADE,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL DEFAULT '',
            full_score REAL NOT NULL DEFAULT 100,
            deadline   TEXT,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS group_submissions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES group_assignments(id) ON DELETE CASCADE,
            student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content       TEXT NOT NULL DEFAULT '',
            file_name     TEXT,
            stored_name   TEXT,
            size          INTEGER DEFAULT 0,
            mime          TEXT,
            score         REAL,
            feedback      TEXT,
            graded_by     INTEGER,
            graded_at     TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            UNIQUE (assignment_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS course_offers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            status     TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, course_id)
        );
        """
    )



def _migrate_v6(conn: sqlite3.Connection) -> None:
    """v5 -> v6：课表。"""
    from backend.core import clock

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS timetable (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name   TEXT NOT NULL,
            weekday      INTEGER NOT NULL,
            period       INTEGER NOT NULL,
            course_name  TEXT NOT NULL,
            teacher_name TEXT DEFAULT '',
            room         TEXT DEFAULT '',
            note         TEXT DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            UNIQUE (class_name, weekday, period)
        );
        CREATE INDEX IF NOT EXISTS idx_timetable_class ON timetable(class_name, weekday, period);
        """
    )
    # 示例课表：大数据G231
    seed = [
        (1, 1, "大数据技术", "王老师", "A301"),
        (1, 2, "Python 程序设计", "李老师", "机房 2"),
        (1, 3, "高等数学", "赵老师", "B102"),
        (2, 1, "数据结构", "孙老师", "A305"),
        (2, 2, "大学英语", "周老师", "C201"),
        (3, 1, "数据库原理", "王老师", "A301"),
        (3, 3, "体育", "吴老师", "操场"),
        (4, 1, "大数据技术", "王老师", "A301"),
        (4, 2, "职业规划", "郑老师", "B203"),
        (5, 1, "Python 程序设计", "李老师", "机房 2"),
    ]
    now = clock.now_iso()
    for weekday, period, course, teacher, room in seed:
        conn.execute(
            """INSERT OR IGNORE INTO timetable
                   (class_name, weekday, period, course_name, teacher_name, room, created_at, updated_at)
               VALUES ('大数据G231', ?, ?, ?, ?, ?, ?, ?)""",
            (weekday, period, course, teacher, room, now, now),
        )



def _migrate_v7(conn: sqlite3.Connection) -> None:
    """v6 -> v7：催交记录。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS assignment_reminders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            operator_id   INTEGER NOT NULL REFERENCES users(id),
            created_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reminders ON assignment_reminders(assignment_id, created_at);
        """
    )



def _migrate_v8(conn: sqlite3.Connection) -> None:
    """v7 -> v8：课表增加学期与周次。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(timetable)")}
    if "semester" not in cols:
        conn.execute("ALTER TABLE timetable ADD COLUMN semester TEXT NOT NULL DEFAULT ''")
    if "weeks" not in cols:
        conn.execute("ALTER TABLE timetable ADD COLUMN weeks TEXT NOT NULL DEFAULT '1-20'")
    conn.execute(
        "UPDATE timetable SET semester = '2026-2027-1' WHERE semester = '' OR semester IS NULL"
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [



    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
    (7, _migrate_v7),
    (8, _migrate_v8),
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
        "group_messages",
        "group_submissions",
        "group_assignments",
        "group_members",
        "course_offers",
        "class_groups",
        "timetable",
        "assignment_reminders",
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