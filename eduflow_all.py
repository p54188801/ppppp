#!/usr/bin/env python3
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

SCHEMA_SQL = r"""-- =====================================================================
-- EduFlow 教务系统 —— SQLite 表结构
-- 约定：
--   * 时间统一存 UTC ISO-8601 字符串（以 Z 结尾）
--   * 主键统一 INTEGER PRIMARY KEY AUTOINCREMENT
--   * 删除策略：核心业务表用软删除（status 字段），关联表允许级联删除
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 用户与会话
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    password_salt TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
    real_name     TEXT    NOT NULL,
    number        TEXT,                       -- 学号 / 工号
    email         TEXT,
    phone         TEXT,
    department    TEXT,                       -- 学院 / 系
    class_name    TEXT,                       -- 行政班
    avatar        TEXT,
    status        TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    last_login_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_role   ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_number ON users(number);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token      TEXT    NOT NULL UNIQUE,
    user_agent TEXT,
    ip         TEXT,
    expires_at TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_user  ON sessions(user_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL,
    success    INTEGER NOT NULL DEFAULT 0,
    ip         TEXT,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_user ON login_attempts(username, created_at);

-- ---------------------------------------------------------------------
-- 课程与教学班
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,       -- 课程代码
    name        TEXT    NOT NULL,
    teacher_id  INTEGER NOT NULL REFERENCES users(id),
    term        TEXT    NOT NULL,              -- 2026-2027-1
    credits     REAL    NOT NULL DEFAULT 2,
    hours       INTEGER NOT NULL DEFAULT 32,
    category    TEXT    NOT NULL DEFAULT '必修',
    cover       TEXT,
    description TEXT,
    status      TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_courses_teacher ON courses(teacher_id);
CREATE INDEX IF NOT EXISTS idx_courses_term    ON courses(term);

CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    join_code   TEXT    NOT NULL UNIQUE,
    semester    TEXT,
    location    TEXT,
    schedule    TEXT,                          -- 例如「周三 3-4 节」
    capacity    INTEGER NOT NULL DEFAULT 60,
    status      TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_classes_course ON classes(course_id);

CREATE TABLE IF NOT EXISTS enrollments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT    NOT NULL DEFAULT 'active'
               CHECK (status IN ('active', 'dropped', 'pending')),
    source     TEXT    NOT NULL DEFAULT 'self',  -- self / import / admin
    created_at TEXT    NOT NULL,
    UNIQUE (class_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_student ON enrollments(student_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_class   ON enrollments(class_id);

-- ---------------------------------------------------------------------
-- 作业与提交
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS assignments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id     INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    title        TEXT    NOT NULL,
    content      TEXT    NOT NULL DEFAULT '',
    attachments  TEXT,                          -- JSON 数组
    full_score   REAL    NOT NULL DEFAULT 100,
    deadline     TEXT,
    allow_late   INTEGER NOT NULL DEFAULT 1,
    late_penalty REAL    NOT NULL DEFAULT 0.1,
    publish_at   TEXT,
    status       TEXT    NOT NULL DEFAULT 'published'
                 CHECK (status IN ('draft', 'published', 'closed')),
    created_by   INTEGER NOT NULL REFERENCES users(id),
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assignments_class ON assignments(class_id);

CREATE TABLE IF NOT EXISTS submissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content       TEXT    NOT NULL DEFAULT '',
    attachments   TEXT,                         -- JSON 数组
    status        TEXT    NOT NULL DEFAULT 'submitted'
                  CHECK (status IN ('submitted', 'graded', 'returned', 'late')),
    score         REAL,
    feedback      TEXT,
    graded_by     INTEGER REFERENCES users(id),
    graded_at     TEXT,
    is_late       INTEGER NOT NULL DEFAULT 0,
    submitted_at  TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    UNIQUE (assignment_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_submissions_assignment ON submissions(assignment_id);
CREATE INDEX IF NOT EXISTS idx_submissions_student    ON submissions(student_id);

-- ---------------------------------------------------------------------
-- 测验与题库
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS quizzes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id    INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    description TEXT,
    start_at    TEXT,
    end_at      TEXT,
    duration    INTEGER NOT NULL DEFAULT 45,    -- 分钟
    total_score REAL    NOT NULL DEFAULT 100,
    shuffle     INTEGER NOT NULL DEFAULT 0,
    show_answer INTEGER NOT NULL DEFAULT 1,
    status      TEXT    NOT NULL DEFAULT 'published'
                CHECK (status IN ('draft', 'published', 'closed')),
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quizzes_class ON quizzes(class_id);

CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id    INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    type       TEXT    NOT NULL CHECK (type IN ('single', 'multi', 'judge', 'fill', 'essay')),
    stem       TEXT    NOT NULL,
    options    TEXT,                            -- JSON 数组，仅选择题
    answer     TEXT    NOT NULL DEFAULT '',     -- 选择题为选项 key，多选逗号分隔
    analysis   TEXT,
    score      REAL    NOT NULL DEFAULT 5,
    order_no   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_questions_quiz ON questions(quiz_id);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id     INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    answers     TEXT,                           -- JSON: {question_id: answer}
    score       REAL,
    status      TEXT    NOT NULL DEFAULT 'in_progress'
                CHECK (status IN ('in_progress', 'submitted', 'graded')),
    started_at  TEXT    NOT NULL,
    submitted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_attempts_quiz    ON quiz_attempts(quiz_id);
CREATE INDEX IF NOT EXISTS idx_attempts_student ON quiz_attempts(student_id);

-- ---------------------------------------------------------------------
-- 签到
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    method     TEXT    NOT NULL DEFAULT 'code'
               CHECK (method IN ('code', 'qr', 'location')),
    code       TEXT    NOT NULL,
    start_at   TEXT    NOT NULL,
    end_at     TEXT    NOT NULL,
    latitude   REAL,
    longitude  REAL,
    radius     INTEGER NOT NULL DEFAULT 200,
    status     TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_att_sessions_class ON attendance_sessions(class_id);

CREATE TABLE IF NOT EXISTS attendance_records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status     TEXT    NOT NULL DEFAULT 'present'
               CHECK (status IN ('present', 'late', 'absent', 'leave')),
    checked_at TEXT,
    note       TEXT,
    UNIQUE (session_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_att_records_session ON attendance_records(session_id);
CREATE INDEX IF NOT EXISTS idx_att_records_student ON attendance_records(student_id);

-- ---------------------------------------------------------------------
-- 资料
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS resources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    description TEXT,
    filename    TEXT    NOT NULL,
    stored_name TEXT    NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    mime        TEXT,
    category    TEXT    NOT NULL DEFAULT '课件',
    downloads   INTEGER NOT NULL DEFAULT 0,
    uploader_id INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resources_course ON resources(course_id);

-- ---------------------------------------------------------------------
-- 讨论区
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS discussions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id  INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    content    TEXT    NOT NULL DEFAULT '',
    author_id  INTEGER NOT NULL REFERENCES users(id),
    pinned     INTEGER NOT NULL DEFAULT 0,
    locked     INTEGER NOT NULL DEFAULT 0,
    views      INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_discussions_course ON discussions(course_id);

CREATE TABLE IF NOT EXISTS discussion_replies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id INTEGER NOT NULL REFERENCES discussions(id) ON DELETE CASCADE,
    author_id     INTEGER NOT NULL REFERENCES users(id),
    content       TEXT    NOT NULL,
    parent_id     INTEGER REFERENCES discussion_replies(id) ON DELETE CASCADE,
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_replies_discussion ON discussion_replies(discussion_id);

-- ---------------------------------------------------------------------
-- 通知
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    content    TEXT    NOT NULL DEFAULT '',
    category   TEXT    NOT NULL DEFAULT 'system',
    link       TEXT,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);

-- ---------------------------------------------------------------------
-- 成绩
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS grade_rules (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id         INTEGER NOT NULL UNIQUE REFERENCES classes(id) ON DELETE CASCADE,
    assignment_weight REAL NOT NULL DEFAULT 0.30,
    quiz_weight      REAL NOT NULL DEFAULT 0.30,
    attendance_weight REAL NOT NULL DEFAULT 0.20,
    final_weight     REAL NOT NULL DEFAULT 0.20,
    pass_score       REAL NOT NULL DEFAULT 60,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grade_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    final_score REAL,                           -- 期末卷面分
    bonus      REAL NOT NULL DEFAULT 0,         -- 加分
    remark     TEXT,
    total      REAL,                            -- 加权总分（运行时计算后回写缓存）
    updated_at TEXT NOT NULL,
    UNIQUE (class_id, student_id)
);

CREATE INDEX IF NOT EXISTS idx_grade_items_class ON grade_items(class_id);

-- ---------------------------------------------------------------------
-- 审计与设置
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    username   TEXT,
    action     TEXT NOT NULL,
    entity     TEXT,
    entity_id  INTEGER,
    detail     TEXT,
    ip         TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);

CREATE TABLE IF NOT EXISTS system_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- ---------------------------------------------------------------------
-- 课程公告
-- ---------------------------------------------------------------------

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
-- ---------------------------------------------------------------------
-- 作业附件（学生提交时上传的文件）
-- ---------------------------------------------------------------------

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

-- ---------------------------------------------------------------------
-- 章节任务点与学习进度
-- ---------------------------------------------------------------------

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
    duration      INTEGER NOT NULL DEFAULT 0,   -- 预计学习时长（分钟）
    required      INTEGER NOT NULL DEFAULT 1,   -- 是否必修任务点
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
CREATE INDEX IF NOT EXISTS idx_task_progress_task    ON task_progress(task_id, status);"""


# ======================================================================
# 第一部分：各功能模块（每个模块封装成一个函数，返回命名空间）
# ======================================================================

# ======================================================================
# 模块：backend/config.py
# ======================================================================
def _mod_config():
    """全局配置。

    所有路径、端口、安全参数集中在这里，方便打包和二次部署。
    支持通过环境变量覆盖，便于测试时使用临时目录。
    """


    import os
    from pathlib import Path

    # ---------------------------------------------------------------------------
    # 基本信息
    # ---------------------------------------------------------------------------

    APP_NAME = "EduFlow 教务系统"
    APP_SHORT_NAME = "EduFlow"
    APP_VERSION = "1.0.0"
    APP_DESCRIPTION = "面向高校场景的教学管理桌面应用"

    # ---------------------------------------------------------------------------
    # 目录
    # ---------------------------------------------------------------------------

    BASE_DIR = Path(__file__).resolve().parent

    DATA_DIR = Path(os.environ.get("EDUFLOW_DATA_DIR", BASE_DIR / "data"))
    DB_PATH = Path(os.environ.get("EDUFLOW_DB_PATH", DATA_DIR / "eduflow.db"))
    UPLOAD_DIR = DATA_DIR / "uploads"
    EXPORT_DIR = DATA_DIR / "exports"
    BACKUP_DIR = DATA_DIR / "backups"

    FRONTEND_DIST = Path(os.environ.get("EDUFLOW_FRONTEND_DIST", BASE_DIR / "frontend" / "dist"))

    # ---------------------------------------------------------------------------
    # 服务
    # ---------------------------------------------------------------------------

    HOST = os.environ.get("EDUFLOW_HOST", "127.0.0.1")
    PORT = int(os.environ.get("EDUFLOW_PORT", "8765"))
    SERVER_NAME = "EduFlow/1.0"

    # 单次请求体上限（16 MB），超过直接拒绝，避免内存被撑爆
    MAX_BODY_BYTES = 16 * 1024 * 1024
    MAX_UPLOAD_BYTES = 64 * 1024 * 1024

    # 静态资源缓存时长（秒）
    STATIC_CACHE_SECONDS = 3600

    # ---------------------------------------------------------------------------
    # 安全
    # ---------------------------------------------------------------------------

    # PBKDF2-HMAC-SHA256 迭代次数；2026 年的机器上 18 万次约 60~90 ms
    PASSWORD_ITERATIONS = 180_000
    PASSWORD_KEY_LEN = 32

    # 登录令牌有效期
    TOKEN_TTL_HOURS = 72

    # 登录失败保护：同一用户名连续失败 N 次后锁定 M 秒
    LOGIN_MAX_FAILURES = 8
    LOGIN_LOCK_SECONDS = 300

    # 会话令牌在数据库中的表名之外没有额外加密，注意本机安全
    SESSION_COOKIE_NAME = "eduflow_token"

    # ---------------------------------------------------------------------------
    # 业务规则
    # ---------------------------------------------------------------------------

    # 默认成绩权重（作业 / 测验 / 签到 / 期末）
    DEFAULT_GRADE_WEIGHTS = {
        "assignment": 0.30,
        "quiz": 0.30,
        "attendance": 0.20,
        "final": 0.20,
    }

    # 签到迟到阈值（分钟）：签到开始后 N 分钟内算正常，之后算迟到
    ATTENDANCE_LATE_MINUTES = 10

    # 测验默认时长（分钟）
    QUIZ_DEFAULT_DURATION = 45

    # 作业允许迟交时，每晚一天扣的百分比
    LATE_PENALTY_PER_DAY = 0.10

    # 分页
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 200


    def ensure_dirs() -> None:
        """确保运行期需要的目录都存在。"""
        for path in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, BACKUP_DIR):
            path.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        APP_NAME=APP_NAME,
        APP_SHORT_NAME=APP_SHORT_NAME,
        APP_VERSION=APP_VERSION,
        APP_DESCRIPTION=APP_DESCRIPTION,
        BASE_DIR=BASE_DIR,
        DATA_DIR=DATA_DIR,
        DB_PATH=DB_PATH,
        UPLOAD_DIR=UPLOAD_DIR,
        EXPORT_DIR=EXPORT_DIR,
        BACKUP_DIR=BACKUP_DIR,
        FRONTEND_DIST=FRONTEND_DIST,
        HOST=HOST,
        PORT=PORT,
        SERVER_NAME=SERVER_NAME,
        MAX_BODY_BYTES=MAX_BODY_BYTES,
        MAX_UPLOAD_BYTES=MAX_UPLOAD_BYTES,
        STATIC_CACHE_SECONDS=STATIC_CACHE_SECONDS,
        PASSWORD_ITERATIONS=PASSWORD_ITERATIONS,
        PASSWORD_KEY_LEN=PASSWORD_KEY_LEN,
        TOKEN_TTL_HOURS=TOKEN_TTL_HOURS,
        LOGIN_MAX_FAILURES=LOGIN_MAX_FAILURES,
        LOGIN_LOCK_SECONDS=LOGIN_LOCK_SECONDS,
        SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
        DEFAULT_GRADE_WEIGHTS=DEFAULT_GRADE_WEIGHTS,
        ATTENDANCE_LATE_MINUTES=ATTENDANCE_LATE_MINUTES,
        QUIZ_DEFAULT_DURATION=QUIZ_DEFAULT_DURATION,
        LATE_PENALTY_PER_DAY=LATE_PENALTY_PER_DAY,
        DEFAULT_PAGE_SIZE=DEFAULT_PAGE_SIZE,
        MAX_PAGE_SIZE=MAX_PAGE_SIZE,
        ensure_dirs=ensure_dirs,
    )


# ======================================================================
# 模块：backend/core/ids.py
# ======================================================================
def _mod_ids():
    """主键、令牌、短码等标识符的生成工具。

    不用 uuid4 作为对外主键，而是：
    - 数据库主键用自增整数（查询快、分页方便）；
    - 对外暴露的分享码、邀请码用可读的短码（去掉易混淆字符）；
    - 会话令牌用高熵随机串。
    """


    import secrets
    import string

    # 去掉了容易看错的 0/O、1/I/l
    _CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    _CODE_ALPHABET_LOWER = _CODE_ALPHABET.lower()


    def new_token(nbytes: int = 32) -> str:
        """生成会话令牌：64 个十六进制字符。"""
        return secrets.token_hex(nbytes)


    def new_code(length: int = 6, *, lower: bool = False) -> str:
        """生成短码（邀请码、签到码、取件码）。"""
        alphabet = _CODE_ALPHABET_LOWER if lower else _CODE_ALPHABET
        return "".join(secrets.choice(alphabet) for _ in range(length))


    def new_join_code(length: int = 6) -> str:
        """教学班邀请码，统一大写。"""
        return new_code(length, lower=False)


    def new_attendance_code(length: int = 6) -> str:
        """签到码，数字为主，方便学生手输。"""
        return "".join(secrets.choice(string.digits) for _ in range(length))


    def new_filename_token(length: int = 12) -> str:
        """上传文件重命名用的随机片段。"""
        return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))


    def mask_middle(value: str, keep: int = 3) -> str:
        """把手机号/邮箱之类的敏感串中间部分打码。"""
        if not value:
            return ""
        if len(value) <= keep * 2:
            return value[0] * len(value)
        return value[:keep] + "*" * (len(value) - keep * 2) + value[-keep:]


    def safe_int(value, default: int = 0) -> int:
        """宽容地把任意输入转成整数，失败时给默认值。"""
        try:
            if isinstance(value, bool):
                return int(value)
            return int(value)
        except (TypeError, ValueError):
            return default


    def clamp(value: int, low: int, high: int) -> int:
        """夹逼到区间内。"""
        return max(low, min(high, value))
    return SimpleNamespace(
        new_token=new_token,
        new_code=new_code,
        new_join_code=new_join_code,
        new_attendance_code=new_attendance_code,
        new_filename_token=new_filename_token,
        mask_middle=mask_middle,
        safe_int=safe_int,
        clamp=clamp,
    )


# ======================================================================
# 模块：backend/core/clock.py
# ======================================================================
def _mod_clock():
    """时间处理工具。

    约定：数据库里存的一律是 UTC 的 ISO-8601 字符串（带 Z 后缀），
    前端负责转换成浏览器本地时区显示。这样跨时区、夏令时都不会错。
    """


    from datetime import datetime, timedelta, timezone

    ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


    def utcnow() -> datetime:
        """当前 UTC 时间（带时区信息）。"""
        return datetime.now(timezone.utc)


    def now_iso() -> str:
        """当前时间，ISO-8601 字符串。"""
        return to_iso(utcnow())


    def to_iso(value: datetime | None) -> str:
        """datetime -> ISO 字符串（UTC）。"""
        if value is None:
            return ""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime(ISO_FORMAT) + "Z"


    def parse_iso(value: str | None) -> datetime | None:
        """ISO 字符串 -> datetime；解析失败返回 None，不抛异常。"""
        if not value:
            return None
        text = value.strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed


    def from_timestamp(ts: float) -> str:
        """unix 时间戳 -> ISO 字符串。"""
        return to_iso(datetime.fromtimestamp(ts, tz=timezone.utc))


    def start_of_day(value: datetime) -> datetime:
        """当天 00:00（保持原时区）。"""
        return value.replace(hour=0, minute=0, second=0, microsecond=0)


    def add_days(value: datetime, days: int) -> datetime:
        return value + timedelta(days=days)


    def add_minutes(value: datetime, minutes: int) -> datetime:
        return value + timedelta(minutes=minutes)


    def is_past(value: str | None) -> bool:
        """给定时间是否已经过去。"""
        parsed = parse_iso(value)
        if parsed is None:
            return False
        return parsed < utcnow()


    def is_future(value: str | None) -> bool:
        parsed = parse_iso(value)
        if parsed is None:
            return False
        return parsed > utcnow()


    def seconds_between(start: str | None, end: str | None) -> float:
        """两个 ISO 时间之间的秒数，任意一个解析失败就返回 0。"""
        a, b = parse_iso(start), parse_iso(end)
        if a is None or b is None:
            return 0.0
        return (b - a).total_seconds()


    def days_between(start: str | None, end: str | None) -> float:
        return seconds_between(start, end) / 86400.0


    def humanize_duration(seconds: float) -> str:
        """把秒数变成「3 天 4 小时」这种中文描述。"""
        seconds = int(abs(seconds))
        if seconds < 60:
            return f"{seconds} 秒"
        minutes, seconds = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes} 分钟"
        hours, minutes = divmod(minutes, 60)
        if hours < 24:
            return f"{hours} 小时 {minutes} 分钟"
        days, hours = divmod(hours, 24)
        return f"{days} 天 {hours} 小时"


    def deadline_state(deadline: str | None) -> str:
        """根据截止时间给出状态：none / open / soon / overdue。"""
        if not deadline:
            return "none"
        parsed = parse_iso(deadline)
        if parsed is None:
            return "none"
        remaining = (parsed - utcnow()).total_seconds()
        if remaining < 0:
            return "overdue"
        if remaining < 3 * 3600:
            return "soon"
        return "open"


    def term_of(value: datetime | None = None) -> str:
        """根据日期推断学年学期，例如 2026-2027-1。

        9 月到次年 1 月是第一学期，2 月到 8 月是第二学期。
        """
        current = value or utcnow()
        year = current.year
        month = current.month
        if month >= 9:
            return f"{year}-{year + 1}-1"
        if month == 1:
            return f"{year - 1}-{year}-1"
        return f"{year - 1}-{year}-2"


    def week_range(term: str, week: int) -> tuple[str, str]:
        """给定学期与周次，返回该周的起止日期（ISO）。"""
        try:
            start_year = int(term.split("-")[0])
        except (ValueError, IndexError):
            start_year = utcnow().year
        # 第一学期从 9 月 1 日算起，第二学期从 2 月 24 日算起
        if term.endswith("-1"):
            base = datetime(start_year, 9, 1, tzinfo=timezone.utc)
        else:
            base = datetime(start_year + 1, 2, 24, tzinfo=timezone.utc)
        begin = base + timedelta(weeks=week - 1)
        end = begin + timedelta(days=6)
        return to_iso(begin), to_iso(end)
    return SimpleNamespace(
        ISO_FORMAT=ISO_FORMAT,
        utcnow=utcnow,
        now_iso=now_iso,
        to_iso=to_iso,
        parse_iso=parse_iso,
        from_timestamp=from_timestamp,
        start_of_day=start_of_day,
        add_days=add_days,
        add_minutes=add_minutes,
        is_past=is_past,
        is_future=is_future,
        seconds_between=seconds_between,
        days_between=days_between,
        humanize_duration=humanize_duration,
        deadline_state=deadline_state,
        term_of=term_of,
        week_range=week_range,
    )


# ======================================================================
# 模块：backend/core/errors.py
# ======================================================================
def _mod_errors():
    """统一的业务异常体系。

    HTTP 层只需要捕获 AppError，就能把错误码、提示语、HTTP 状态码
    一起映射成统一格式的 JSON 响应，避免到处写 try/except。
    """


    from typing import Any


    class AppError(Exception):
        """所有可预期业务异常的基类。"""

        code: str = "internal_error"
        status: int = 500
        message: str = "服务器内部错误"

        def __init__(
            self,
            message: str | None = None,
            *,
            code: str | None = None,
            status: int | None = None,
            details: Any = None,
        ) -> None:
            super().__init__(message or self.message)
            if message:
                self.message = message
            if code:
                self.code = code
            if status:
                self.status = status
            self.details = details

        def to_dict(self) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "ok": False,
                "error": {
                    "code": self.code,
                    "message": self.message,
                },
            }
            if self.details is not None:
                payload["error"]["details"] = self.details
            return payload


    class ValidationError(AppError):
        code = "validation_error"
        status = 400
        message = "参数不合法"


    class UnauthorizedError(AppError):
        code = "unauthorized"
        status = 401
        message = "请先登录"


    class ForbiddenError(AppError):
        code = "forbidden"
        status = 403
        message = "没有权限执行该操作"


    class NotFoundError(AppError):
        code = "not_found"
        status = 404
        message = "资源不存在"


    class MethodNotAllowedError(AppError):
        code = "method_not_allowed"
        status = 405
        message = "不支持的请求方法"


    class ConflictError(AppError):
        code = "conflict"
        status = 409
        message = "操作冲突"


    class RateLimitError(AppError):
        code = "rate_limited"
        status = 429
        message = "操作过于频繁，请稍后再试"


    class TooLargeError(AppError):
        code = "payload_too_large"
        status = 413
        message = "数据过大"


    class BusinessRuleError(AppError):
        """业务规则不满足，例如「已截止的作业不能再提交」。"""

        code = "business_rule"
        status = 422
        message = "业务规则不满足"


    def require(condition: bool, message: str, *, code: str = "business_rule") -> None:
        """断言式校验，条件不满足时抛 BusinessRuleError。"""
        if not condition:
            raise BusinessRuleError(message, code=code)


    def ensure_found(value: Any, message: str = "资源不存在") -> Any:
        """值为 None 时抛 NotFoundError。"""
        if value is None:
            raise NotFoundError(message)
        return value
    return SimpleNamespace(
        AppError=AppError,
        ValidationError=ValidationError,
        UnauthorizedError=UnauthorizedError,
        ForbiddenError=ForbiddenError,
        NotFoundError=NotFoundError,
        MethodNotAllowedError=MethodNotAllowedError,
        ConflictError=ConflictError,
        RateLimitError=RateLimitError,
        TooLargeError=TooLargeError,
        BusinessRuleError=BusinessRuleError,
        require=require,
        ensure_found=ensure_found,
    )


# ======================================================================
# 模块：backend/core/security.py
# ======================================================================
def _mod_security(PASSWORD_ITERATIONS, PASSWORD_KEY_LEN, ValidationError):
    """密码哈希、令牌、签名等安全原语。

    刻意只用标准库：
    - 口令用 PBKDF2-HMAC-SHA256（加盐、迭代 18 万次）；
    - 比较用 hmac.compare_digest，防时序攻击；
    - 一次性签名用 HMAC-SHA256，用于防篡改的快照数据。
    """


    import base64
    import hashlib
    import hmac
    import json
    import secrets
    import string
    from typing import Any


    _SIGN_SECRET_FALLBACK = "eduflow-local-signing-key"


    def _normalize(password: str) -> bytes:
        """统一做 NFKC 归一化，避免全角/半角输入导致登录失败。"""
        import unicodedata

        return unicodedata.normalize("NFKC", password).encode("utf-8")


    def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
        """返回 (哈希十六进制串, 盐)。盐为空时自动生成。"""
        if not isinstance(password, str):
            raise ValidationError("密码格式不正确")
        if len(password) < 6:
            raise ValidationError("密码至少 6 位")
        if len(password) > 128:
            raise ValidationError("密码不能超过 128 位")
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            _normalize(password),
            salt.encode("utf-8"),
            PASSWORD_ITERATIONS,
            dklen=PASSWORD_KEY_LEN,
        )
        return digest.hex(), salt


    def verify_password(password: str, stored_hash: str, salt: str) -> bool:
        """校验口令；任何异常都当作验证失败。"""
        try:
            candidate, _ = hash_password(password, salt)
        except ValidationError:
            return False
        return hmac.compare_digest(candidate, stored_hash)


    def constant_time_compare(a: str, b: str) -> bool:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


    def new_session_token() -> str:
        """64 位十六进制会话令牌。"""
        return secrets.token_hex(32)


    def random_password(length: int = 10) -> str:
        """生成一个可读性尚可的随机初始密码（去掉易混淆字符）。"""
        alphabet = "".join(
            c for c in string.ascii_letters + string.digits if c not in "0O1lI"
        )
        return "".join(secrets.choice(alphabet) for _ in range(length))


    def password_strength(password: str) -> dict[str, Any]:
        """粗略评估密码强度，用于前端提示。"""
        score = 0
        issues: list[str] = []
        if len(password) >= 8:
            score += 1
        else:
            issues.append("长度建议不少于 8 位")
        if len(password) >= 12:
            score += 1
        if any(c.islower() for c in password) and any(c.isupper() for c in password):
            score += 1
        else:
            issues.append("建议同时包含大小写字母")
        if any(c.isdigit() for c in password):
            score += 1
        else:
            issues.append("建议包含数字")
        if any(not c.isalnum() for c in password):
            score += 1
        else:
            issues.append("建议包含符号")
        label = ["很弱", "弱", "一般", "较强", "很强"][min(score, 4)]
        return {"score": score, "label": label, "issues": issues}


    # ---------------------------------------------------------------------------
    # HMAC 签名（用于防篡改的公开数据，例如成绩单导出令牌）
    # ---------------------------------------------------------------------------


    def _b64encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


    def _b64decode(text: str) -> bytes:
        padding = "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode(text + padding)


    def sign_payload(payload: dict[str, Any], secret: str | None = None) -> str:
        """payload -> "base64(json).base64(hmac)"。"""
        key = (secret or _SIGN_SECRET_FALLBACK).encode("utf-8")
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        body_bytes = body.encode("utf-8")
        signature = hmac.new(key, body_bytes, hashlib.sha256).digest()
        return f"{_b64encode(body_bytes)}.{_b64encode(signature)}"


    def verify_signed(token: str, secret: str | None = None) -> dict[str, Any] | None:
        """校验签名并返回 payload；失败返回 None。"""
        if not token or "." not in token:
            return None
        try:
            body_b64, sig_b64 = token.split(".", 1)
            body_bytes = _b64decode(body_b64)
            signature = _b64decode(sig_b64)
        except (ValueError, TypeError):
            return None
        key = (secret or _SIGN_SECRET_FALLBACK).encode("utf-8")
        expected = hmac.new(key, body_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            return json.loads(body_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    return SimpleNamespace(
        hash_password=hash_password,
        verify_password=verify_password,
        constant_time_compare=constant_time_compare,
        new_session_token=new_session_token,
        random_password=random_password,
        password_strength=password_strength,
        sign_payload=sign_payload,
        verify_signed=verify_signed,
    )


# ======================================================================
# 模块：backend/core/validators.py
# ======================================================================
def _mod_validators(ValidationError, clock):
    """请求参数校验与类型转换工具。

    设计原则：
    - 所有从 HTTP 进来的数据都不可信，必须先过这里；
    - 校验失败抛 ValidationError，由 HTTP 层统一转成 400；
    - 每个函数只做一件事，方便组合和单测。
    """


    import re
    from datetime import datetime, timezone
    from typing import Any, Iterable, Sequence


    USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{2,31}$")
    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
    CODE_RE = re.compile(r"^[A-Z0-9]{4,12}$")


    def ensure_dict(value: Any, field: str = "请求体") -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValidationError(f"{field}必须是 JSON 对象")
        return value


    def required(data: dict[str, Any], key: str) -> Any:
        if key not in data or data[key] is None:
            raise ValidationError(f"缺少必填字段：{key}")
        return data[key]


    def required_str(
        data: dict[str, Any],
        key: str,
        *,
        min_len: int = 1,
        max_len: int = 200,
        strip: bool = True,
    ) -> str:
        raw = required(data, key)
        if not isinstance(raw, str):
            raise ValidationError(f"{key} 必须是字符串")
        value = raw.strip() if strip else raw
        if len(value) < min_len:
            raise ValidationError(f"{key} 不能少于 {min_len} 个字符")
        if len(value) > max_len:
            raise ValidationError(f"{key} 不能超过 {max_len} 个字符")
        return value


    def optional_str(
        data: dict[str, Any],
        key: str,
        default: str = "",
        *,
        max_len: int = 2000,
        strip: bool = True,
    ) -> str:
        if key not in data or data[key] is None:
            return default
        raw = data[key]
        if not isinstance(raw, str):
            raise ValidationError(f"{key} 必须是字符串")
        value = raw.strip() if strip else raw
        if len(value) > max_len:
            raise ValidationError(f"{key} 不能超过 {max_len} 个字符")
        return value


    def required_int(
        data: dict[str, Any],
        key: str,
        *,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        raw = required(data, key)
        return to_int(raw, key, min_value=min_value, max_value=max_value)


    def optional_int(
        data: dict[str, Any],
        key: str,
        default: int | None = None,
        *,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int | None:
        if key not in data or data[key] is None or data[key] == "":
            return default
        return to_int(data[key], key, min_value=min_value, max_value=max_value)


    def to_int(
        raw: Any,
        field: str,
        *,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        if isinstance(raw, bool):
            raise ValidationError(f"{field} 必须是整数")
        try:
            value = int(str(raw).strip()) if isinstance(raw, str) else int(raw)
        except (TypeError, ValueError):
            raise ValidationError(f"{field} 必须是整数") from None
        if min_value is not None and value < min_value:
            raise ValidationError(f"{field} 不能小于 {min_value}")
        if max_value is not None and value > max_value:
            raise ValidationError(f"{field} 不能大于 {max_value}")
        return value


    def to_float(
        raw: Any,
        field: str,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> float:
        if isinstance(raw, bool):
            raise ValidationError(f"{field} 必须是数字")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValidationError(f"{field} 必须是数字") from None
        if value != value:  # NaN
            raise ValidationError(f"{field} 不是合法数字")
        if min_value is not None and value < min_value:
            raise ValidationError(f"{field} 不能小于 {min_value}")
        if max_value is not None and value > max_value:
            raise ValidationError(f"{field} 不能大于 {max_value}")
        return round(value, 2)


    def optional_float(
        data: dict[str, Any],
        key: str,
        default: float | None = None,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> float | None:
        if key not in data or data[key] is None or data[key] == "":
            return default
        return to_float(data[key], key, min_value=min_value, max_value=max_value)


    def to_bool(raw: Any, default: bool = False) -> bool:
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            text = raw.strip().lower()
            if text in {"1", "true", "yes", "on", "y"}:
                return True
            if text in {"0", "false", "no", "off", "n", ""}:
                return False
        return default


    def ensure_enum(value: str, allowed: Iterable[str], field: str) -> str:
        allowed_set = set(allowed)
        if value not in allowed_set:
            raise ValidationError(
                f"{field} 取值必须是 {', '.join(sorted(allowed_set))} 之一"
            )
        return value


    def validate_username(username: str) -> str:
        """字母开头，3~32 位字母数字下划线。"""
        value = (username or "").strip()
        if not USERNAME_RE.match(value):
            raise ValidationError("用户名需以字母开头，3~32 位字母、数字或下划线")
        return value


    def validate_email(email: str) -> str:
        value = (email or "").strip()
        if value and not EMAIL_RE.match(value):
            raise ValidationError("邮箱格式不正确")
        return value


    def validate_phone(phone: str) -> str:
        value = (phone or "").strip()
        if value and not PHONE_RE.match(value):
            raise ValidationError("手机号格式不正确")
        return value


    def validate_code(code: str, field: str = "邀请码") -> str:
        value = (code or "").strip().upper()
        if not CODE_RE.match(value):
            raise ValidationError(f"{field}格式不正确")
        return value


    def validate_date(value: Any, field: str, *, required_field: bool = True) -> str:
        """接受 ISO 字符串或时间戳，统一返回 ISO 字符串。"""
        if value in (None, ""):
            if required_field:
                raise ValidationError(f"{field}不能为空")
            return ""
        text = str(value).strip()
        parsed = clock.parse_iso(text)
        if parsed is None:
            # 尝试纯日期 YYYY-MM-DD
            try:
                parsed = datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                raise ValidationError(f"{field}不是合法时间") from None
        return clock.to_iso(parsed)


    def require_one_of(data: dict[str, Any], keys: Sequence[str], field: str) -> None:
        """至少提供其中一个字段。"""
        if not any(k in data and data[k] not in (None, "") for k in keys):
            raise ValidationError(f"{field}至少需要提供一项：{', '.join(keys)}")


    def validate_score(score: Any, full_score: float = 100.0) -> float:
        value = to_float(score, "分数", min_value=0, max_value=full_score)
        return round(value, 2)


    def sanitize_text(text: str, *, max_len: int = 5000) -> str:
        """去掉不可见控制字符，限制长度。"""
        cleaned = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
        return cleaned[:max_len]


    def parse_int_list(raw: Any, field: str = "列表") -> list[int]:
        """接受 [1,2] 或 "1,2" 两种写法。"""
        if raw is None:
            return []
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.split(",") if p.strip()]
        elif isinstance(raw, (list, tuple, set)):
            parts = list(raw)
        else:
            raise ValidationError(f"{field}格式不正确")
        result: list[int] = []
        for item in parts:
            result.append(to_int(item, field))
        return result


    def clamp_page(page: Any, size: Any) -> tuple[int, int]:
        """规范化分页参数：非法值一律夹逼到合法区间，而不是报错。"""
        from backend.config import MAX_PAGE_SIZE
        from backend.core.ids import safe_int

        page_no = safe_int(page, 1) if page not in (None, "") else 1
        page_size = safe_int(size, 20) if size not in (None, "") else 20
        page_no = max(1, page_no)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        return page_no, page_size
    return SimpleNamespace(
        USERNAME_RE=USERNAME_RE,
        EMAIL_RE=EMAIL_RE,
        PHONE_RE=PHONE_RE,
        CODE_RE=CODE_RE,
        ensure_dict=ensure_dict,
        required=required,
        required_str=required_str,
        optional_str=optional_str,
        required_int=required_int,
        optional_int=optional_int,
        to_int=to_int,
        to_float=to_float,
        optional_float=optional_float,
        to_bool=to_bool,
        ensure_enum=ensure_enum,
        validate_username=validate_username,
        validate_email=validate_email,
        validate_phone=validate_phone,
        validate_code=validate_code,
        validate_date=validate_date,
        require_one_of=require_one_of,
        validate_score=validate_score,
        sanitize_text=sanitize_text,
        parse_int_list=parse_int_list,
        clamp_page=clamp_page,
    )


# ======================================================================
# 模块：backend/core/permissions.py
# ======================================================================
def _mod_permissions(ForbiddenError, UnauthorizedError):
    """角色与权限判定。

    不引入复杂的 RBAC 表，直接按业务语义写死几组判定函数，
    调用处语义清晰，也便于审计。
    """


    from typing import Any


    ROLE_STUDENT = "student"
    ROLE_TEACHER = "teacher"
    ROLE_ADMIN = "admin"

    ROLE_LABELS = {
        ROLE_STUDENT: "学生",
        ROLE_TEACHER: "教师",
        ROLE_ADMIN: "管理员",
    }

    ALL_ROLES = (ROLE_STUDENT, ROLE_TEACHER, ROLE_ADMIN)


    def require_login(user: dict[str, Any] | None) -> dict[str, Any]:
        if not user:
            raise UnauthorizedError()
        if user.get("status") != "active":
            raise ForbiddenError("账号已被禁用")
        return user


    def require_role(user: dict[str, Any] | None, *roles: str) -> dict[str, Any]:
        current = require_login(user)
        if current["role"] not in roles:
            raise ForbiddenError("当前角色无权访问")
        return current


    def require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
        return require_role(user, ROLE_ADMIN)


    def require_teacher(user: dict[str, Any] | None) -> dict[str, Any]:
        return require_role(user, ROLE_TEACHER, ROLE_ADMIN)


    def is_admin(user: dict[str, Any] | None) -> bool:
        return bool(user) and user.get("role") == ROLE_ADMIN


    def is_teacher(user: dict[str, Any] | None) -> bool:
        return bool(user) and user.get("role") in (ROLE_TEACHER, ROLE_ADMIN)


    def can_manage_course(user: dict[str, Any] | None, course: dict[str, Any]) -> bool:
        """管理员可管理所有课程；教师只能管理自己的课程。"""
        if not user:
            return False
        if user["role"] == ROLE_ADMIN:
            return True
        if user["role"] == ROLE_TEACHER:
            return int(course.get("teacher_id", 0)) == int(user["id"])
        return False


    def assert_can_manage_course(user: dict[str, Any], course: dict[str, Any]) -> None:
        if not can_manage_course(user, course):
            raise ForbiddenError("只能管理自己的课程")


    def can_view_course(user: dict[str, Any], course: dict[str, Any],
                        *, enrolled: bool = False) -> bool:
        """管理员、任课教师、已选课学生可见。"""
        if not user:
            return False
        if user["role"] == ROLE_ADMIN:
            return True
        if int(course.get("teacher_id", 0)) == int(user["id"]):
            return True
        return enrolled


    def assert_can_view_course(user: dict[str, Any], course: dict[str, Any],
                               *, enrolled: bool = False) -> None:
        if not can_view_course(user, course, enrolled=enrolled):
            raise ForbiddenError("无权查看该课程")
    return SimpleNamespace(
        ROLE_STUDENT=ROLE_STUDENT,
        ROLE_TEACHER=ROLE_TEACHER,
        ROLE_ADMIN=ROLE_ADMIN,
        ROLE_LABELS=ROLE_LABELS,
        ALL_ROLES=ALL_ROLES,
        require_login=require_login,
        require_role=require_role,
        require_admin=require_admin,
        require_teacher=require_teacher,
        is_admin=is_admin,
        is_teacher=is_teacher,
        can_manage_course=can_manage_course,
        assert_can_manage_course=assert_can_manage_course,
        can_view_course=can_view_course,
        assert_can_view_course=assert_can_view_course,
    )


# ======================================================================
# 模块：backend/http/response.py
# ======================================================================
def _mod_response_lib(AppError):
    """HTTP 响应封装。

    统一响应格式：
      成功: {"ok": true, "data": ..., "message": ...}
      失败: {"ok": false, "error": {"code": ..., "message": ..., "details": ...}}
    """


    import json
    import mimetypes
    from dataclasses import dataclass, field
    from pathlib import Path
    from typing import Any


    JSON_CONTENT_TYPE = "application/json; charset=utf-8"


    @dataclass
    class Response:
        status: int = 200
        body: bytes = b""
        content_type: str = JSON_CONTENT_TYPE
        headers: dict[str, str] = field(default_factory=dict)

        def with_header(self, key: str, value: str) -> "Response":
            self.headers[key] = value
            return self

        def to_bytes(self) -> bytes:
            return self.body


    def _dumps(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


    def json_response(payload: Any, status: int = 200) -> Response:
        return Response(status=status, body=_dumps(payload), content_type=JSON_CONTENT_TYPE)


    def ok(data: Any = None, message: str | None = None, status: int = 200) -> Response:
        payload: dict[str, Any] = {"ok": True, "data": data}
        if message:
            payload["message"] = message
        return json_response(payload, status)


    def created(data: Any = None, message: str = "创建成功") -> Response:
        return ok(data, message, status=201)


    def no_content() -> Response:
        return Response(status=204, body=b"", content_type=JSON_CONTENT_TYPE)


    def error_response(error: AppError) -> Response:
        return json_response(error.to_dict(), status=error.status)


    def text_response(text: str, status: int = 200) -> Response:
        return Response(
            status=status,
            body=text.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
        )


    def redirect(location: str, status: int = 302) -> Response:
        return Response(
            status=status,
            body=b"",
            content_type="text/plain; charset=utf-8",
            headers={"Location": location},
        )


    def file_response(path: Path, *, download_name: str | None = None,
                      cache_seconds: int = 0) -> Response:
        if not path.exists() or not path.is_file():
            from backend.core.errors import NotFoundError

            raise NotFoundError("文件不存在")
        mime, _ = mimetypes.guess_type(str(path))
        body = path.read_bytes()
        headers = {"Cache-Control": f"public, max-age={cache_seconds}" if cache_seconds else "no-cache"}
        if download_name:
            from urllib.parse import quote

            headers["Content-Disposition"] = (
                f"attachment; filename*=UTF-8''{quote(download_name)}"
            )
        return Response(
            status=200,
            body=body,
            content_type=(mime or "application/octet-stream") + (
                "; charset=utf-8" if (mime or "").startswith("text/") else ""
            ),
            headers=headers,
        )


    def stream_response(chunks, content_type: str = "application/octet-stream") -> Response:
        """把可迭代的字节块拼成一个响应（文件不大时足够用）。"""
        return Response(status=200, body=b"".join(chunks), content_type=content_type)


    def paginated(items: list[Any], total: int, page: int, page_size: int) -> Response:
        pages = max(1, (total + page_size - 1) // page_size)
        return ok(
            {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
            }
        )
    return SimpleNamespace(
        JSON_CONTENT_TYPE=JSON_CONTENT_TYPE,
        Response=Response,
        json_response=json_response,
        ok=ok,
        created=created,
        no_content=no_content,
        error_response=error_response,
        text_response=text_response,
        redirect=redirect,
        file_response=file_response,
        stream_response=stream_response,
        paginated=paginated,
    )


# ======================================================================
# 模块：backend/http/static.py
# ======================================================================
def _mod_static_lib(ForbiddenError, NotFoundError, Response, STATIC_CACHE_SECONDS):
    """静态资源服务。

    前端是 Vue3 + Vite 打包出的 SPA，这里负责：
    - 命中真实文件就直接返回（带缓存头）；
    - 命中目录则回退到 index.html（history 路由）；
    - 严格校验路径，防止 ../ 穿越到项目外。
    """


    import mimetypes
    from pathlib import Path


    # 常见前端资源，省去每次查表
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")
    mimetypes.add_type("application/json", ".json")
    mimetypes.add_type("font/woff2", ".woff2")


    class StaticFiles:
        def __init__(self, root: Path, *, spa_fallback: bool = True) -> None:
            self.root = root.resolve()
            self.spa_fallback = spa_fallback

        def exists(self) -> bool:
            return self.root.exists() and (self.root / "index.html").exists()

        def resolve(self, url_path: str) -> Path | None:
            """把 URL 路径映射到磁盘文件；越界返回 None。"""
            relative = url_path.lstrip("/")
            if not relative:
                relative = "index.html"
            candidate = (self.root / relative).resolve()
            try:
                candidate.relative_to(self.root)
            except ValueError:
                return None
            if candidate.is_file():
                return candidate
            if candidate.is_dir():
                index = candidate / "index.html"
                if index.is_file():
                    return index
            return None

        def serve(self, url_path: str, *, cache: bool = True) -> Response:
            target = self.resolve(url_path)
            if target is None:
                if self.spa_fallback and "." not in Path(url_path).name:
                    index = self.root / "index.html"
                    if index.is_file():
                        return self._read(index, url_path, cache=False)
                raise NotFoundError(f"静态资源不存在：{url_path}")
            return self._read(target, url_path, cache=cache)

        def _read(self, path: Path, url_path: str, *, cache: bool) -> Response:
            mime, _ = mimetypes.guess_type(str(path))
            content_type = mime or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {
                "application/javascript",
                "application/json",
                "image/svg+xml",
            }:
                content_type += "; charset=utf-8"
            body = path.read_bytes()
            headers = {}
            if cache:
                headers["Cache-Control"] = f"public, max-age={STATIC_CACHE_SECONDS}"
            else:
                headers["Cache-Control"] = "no-cache"
            # 带 hash 的构建产物可以长缓存
            if "/assets/" in url_path:
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return Response(status=200, body=body, content_type=content_type, headers=headers)


    def safe_join(root: Path, *parts: str) -> Path:
        """拼接路径并确保结果在 root 内，用于上传文件下载。"""
        root = root.resolve()
        target = root.joinpath(*parts).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise ForbiddenError("非法路径") from None
        return target
    return SimpleNamespace(
        StaticFiles=StaticFiles,
        safe_join=safe_join,
    )


# ======================================================================
# 模块：backend/db/connection.py
# ======================================================================
def _mod_connection(config):
    """SQLite 连接管理与查询辅助函数。

    要点：
    - HTTP 服务器是多线程的，sqlite3 连接不能跨线程共享，
      这里用 threading.local 为每个线程各持有一个连接；
    - 打开 WAL 模式，读写并发更好，也能避免大量 "database is locked"；
    - 事务统一通过 transaction() 上下文管理器，异常自动回滚。
    """


    import sqlite3
    import threading
    from contextlib import contextmanager
    from pathlib import Path
    from typing import Any, Iterator, Sequence


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
        nonlocal _initialized
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
    return SimpleNamespace(
        get_connection=get_connection,
        close_connection=close_connection,
        init_connection=init_connection,
        transaction=transaction,
        query_all=query_all,
        query_one=query_one,
        scalar=scalar,
        execute=execute,
        execute_many=execute_many,
        column_exists=column_exists,
        table_exists=table_exists,
    )


# ======================================================================
# 模块：backend/services/backup_service.py
# ======================================================================
def _mod_backup_service(NotFoundError, ValidationError, clock, config, connection):
    """数据备份与恢复。

    用 SQLite 官方 backup API 在服务运行中做一致性快照；备份放在 data/backups。
    恢复是破坏性操作，接口层要求 confirm=true 才执行。
    """


    import sqlite3
    from pathlib import Path
    from typing import Any


    PREFIX = "eduflow-"


    def _dir() -> Path:
        path = Path(config.BACKUP_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


    def create_backup(note: str = "") -> dict[str, Any]:
        stamp = clock.utcnow().strftime("%Y%m%d-%H%M%S")
        safe_note = "".join(ch for ch in note if ch.isalnum() or ch in "-_")[:20]
        name = f"{PREFIX}{stamp}{('-' + safe_note) if safe_note else ''}.db"
        target = _dir() / name

        source = connection.get_connection()
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()

        stat = target.stat()
        return {
            "filename": name,
            "size": stat.st_size,
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": clock.now_iso(),
            "note": note,
        }


    def list_backups() -> list[dict[str, Any]]:
        items = []
        for path in sorted(_dir().glob(f"{PREFIX}*.db"), reverse=True):
            stat = path.stat()
            items.append(
                {
                    "filename": path.name,
                    "size": stat.st_size,
                    "size_kb": round(stat.st_size / 1024, 1),
                    "created_at": clock.from_timestamp(stat.st_mtime),
                }
            )
        return items


    def resolve_backup(filename: str) -> Path:
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise ValidationError("备份文件名不合法")
        if not filename.startswith(PREFIX):
            raise ValidationError("备份文件名不合法")
        path = _dir() / filename
        if not path.is_file():
            raise NotFoundError("备份文件不存在")
        return path


    def delete_backup(filename: str) -> None:
        resolve_backup(filename).unlink()


    def restore_backup(filename: str) -> dict[str, Any]:
        path = resolve_backup(filename)
        source = sqlite3.connect(str(path))
        target = connection.get_connection()
        try:
            source.backup(target)
        finally:
            source.close()
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"restored_from": filename, "at": clock.now_iso()}


    def stats() -> dict[str, Any]:
        items = list_backups()
        return {
            "count": len(items),
            "total_kb": round(sum(item["size"] for item in items) / 1024, 1),
            "latest": items[0] if items else None,
            "dir": str(_dir()),
        }
    return SimpleNamespace(
        PREFIX=PREFIX,
        create_backup=create_backup,
        list_backups=list_backups,
        resolve_backup=resolve_backup,
        delete_backup=delete_backup,
        restore_backup=restore_backup,
        stats=stats,
    )


# ======================================================================
# 模块：backend/db/migrations.py
# ======================================================================
def _mod_migrations(clock, config, connection):
    """数据库初始化与版本迁移。

    当前只有 schema v1，但保留迁移框架，后续加字段只需要在
    MIGRATIONS 里追加一个 (版本号, 函数) 即可。
    """


    import sqlite3
    from pathlib import Path
    from typing import Callable


    SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
    CURRENT_VERSION = 4


    def _read_schema() -> str:
        return SCHEMA_SQL


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
    return SimpleNamespace(
        SCHEMA_PATH=SCHEMA_PATH,
        CURRENT_VERSION=CURRENT_VERSION,
        get_version=get_version,
        MIGRATIONS=MIGRATIONS,
        init_db=init_db,
        reset_db=reset_db,
    )


# ======================================================================
# 模块：backend/repositories/base.py
# ======================================================================
def _mod_base_repo(NotFoundError, ValidationError, clock, connection):
    """仓储基类。

    把「按主键查、按条件查、插入、更新、软删除」这些重复动作收口，
    子类只需要声明表名和可写字段，减少大量样板代码。

    注意：所有拼接进 SQL 的字段名都会先和表的真实列做比对，
    不合法的列名直接抛异常，避免 SQL 注入。
    """


    from typing import Any, Iterable, Sequence



    class BaseRepository:
        table: str = ""
        pk: str = "id"
        # 允许通过 insert/update 写入的列
        writable: tuple[str, ...] = ()
        # 创建/更新时间戳字段（没有则为空串）
        created_field: str = "created_at"
        updated_field: str = "updated_at"

        _column_cache: dict[str, set[str]] = {}

        # -- 元信息 -----------------------------------------------------------

        @classmethod
        def columns(cls) -> set[str]:
            if cls.table not in cls._column_cache:
                rows = connection.query_all(f"PRAGMA table_info({cls.table})")
                cls._column_cache[cls.table] = {row["name"] for row in rows}
            return cls._column_cache[cls.table]

        @classmethod
        def ensure_table(cls) -> None:
            if not cls.table:
                raise ValidationError("仓储未声明 table")

        def _check_field(self, field: str) -> str:
            if field not in self.columns():
                raise ValidationError(f"{self.table} 不存在字段 {field}")
            return field

        def _check_writable(self, data: dict[str, Any]) -> dict[str, Any]:
            cleaned: dict[str, Any] = {}
            for key, value in data.items():
                if key not in self.writable:
                    raise ValidationError(f"{self.table} 不允许写入字段 {key}")
                cleaned[key] = value
            return cleaned

        # -- 查询 -------------------------------------------------------------

        def find(self, pk_value: Any) -> dict[str, Any] | None:
            return connection.query_one(
                f"SELECT * FROM {self.table} WHERE {self.pk} = ?", (pk_value,)
            )

        def find_or_fail(self, pk_value: Any, message: str = "记录不存在") -> dict[str, Any]:
            row = self.find(pk_value)
            if row is None:
                raise NotFoundError(message)
            return row

        def find_by(self, **filters: Any) -> dict[str, Any] | None:
            if not filters:
                return None
            clause, params = self._where(filters)
            return connection.query_one(
                f"SELECT * FROM {self.table} WHERE {clause} LIMIT 1", params
            )

        def all(
            self,
            *,
            where: str = "",
            params: Sequence[Any] = (),
            order_by: str = "",
            limit: int | None = None,
            offset: int = 0,
        ) -> list[dict[str, Any]]:
            sql = f"SELECT * FROM {self.table}"
            if where:
                sql += f" WHERE {where}"
            if order_by:
                sql += f" ORDER BY {order_by}"
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                params = tuple(params) + (limit, offset)
            return connection.query_all(sql, params)

        def count(self, where: str = "", params: Sequence[Any] = ()) -> int:
            sql = f"SELECT COUNT(*) FROM {self.table}"
            if where:
                sql += f" WHERE {where}"
            return int(connection.scalar(sql, params, default=0) or 0)

        def exists(self, **filters: Any) -> bool:
            if not filters:
                return False
            clause, params = self._where(filters)
            found = connection.scalar(
                f"SELECT 1 FROM {self.table} WHERE {clause} LIMIT 1", params
            )
            return found is not None

        def _where(self, filters: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
            parts: list[str] = []
            params: list[Any] = []
            for key, value in filters.items():
                self._check_field(key)
                parts.append(f"{key} = ?")
                params.append(value)
            return " AND ".join(parts), tuple(params)

        # -- 写入 -------------------------------------------------------------

        def insert(self, data: dict[str, Any]) -> int:
            payload = self._check_writable(data)
            now = clock.now_iso()
            if self.created_field and self.created_field in self.columns():
                payload.setdefault(self.created_field, now)
            if self.updated_field and self.updated_field in self.columns():
                payload.setdefault(self.updated_field, now)
            if not payload:
                raise ValidationError("没有可写入的字段")
            columns = ", ".join(payload.keys())
            placeholders = ", ".join("?" for _ in payload)
            sql = f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})"
            return connection.execute(sql, tuple(payload.values()))

        def update(self, pk_value: Any, data: dict[str, Any]) -> int:
            payload = self._check_writable(data)
            if self.updated_field and self.updated_field in self.columns():
                payload[self.updated_field] = clock.now_iso()
            if not payload:
                return 0
            assignments = ", ".join(f"{key} = ?" for key in payload)
            sql = f"UPDATE {self.table} SET {assignments} WHERE {self.pk} = ?"
            params = tuple(payload.values()) + (pk_value,)
            return connection.execute(sql, params)

        def update_where(self, where: str, params: Sequence[Any], data: dict[str, Any]) -> int:
            payload = self._check_writable(data)
            if self.updated_field and self.updated_field in self.columns():
                payload[self.updated_field] = clock.now_iso()
            if not payload:
                return 0
            assignments = ", ".join(f"{key} = ?" for key in payload)
            sql = f"UPDATE {self.table} SET {assignments} WHERE {where}"
            return connection.execute(sql, tuple(payload.values()) + tuple(params))

        def delete(self, pk_value: Any) -> int:
            return connection.execute(
                f"DELETE FROM {self.table} WHERE {self.pk} = ?", (pk_value,)
            )

        def delete_where(self, where: str, params: Sequence[Any]) -> int:
            return connection.execute(f"DELETE FROM {self.table} WHERE {where}", params)

        def upsert(self, keys: dict[str, Any], data: dict[str, Any]) -> int:
            """有则更新，无则插入。"""
            existing = self.find_by(**keys)
            if existing:
                self.update(existing[self.pk], data)
                return int(existing[self.pk])
            merged = dict(keys)
            merged.update(data)
            return self.insert(merged)

        # -- 批量 -------------------------------------------------------------

        def insert_many(self, rows: Iterable[dict[str, Any]]) -> int:
            items = list(rows)
            if not items:
                return 0
            now = clock.now_iso()
            prepared: list[tuple[Any, ...]] = []
            columns = list(self._check_writable(items[0]).keys())
            for row in items:
                payload = self._check_writable(row)
                if self.created_field and self.created_field in self.columns():
                    payload.setdefault(self.created_field, now)
                if self.updated_field and self.updated_field in self.columns():
                    payload.setdefault(self.updated_field, now)
                prepared.append(tuple(payload.get(col) for col in columns))
            placeholders = ", ".join("?" for _ in columns)
            sql = f"INSERT INTO {self.table} ({', '.join(columns)}) VALUES ({placeholders})"
            return connection.execute_many(sql, prepared)
    return SimpleNamespace(
        BaseRepository=BaseRepository,
    )


# ======================================================================
# 模块：backend/repositories/users.py
# ======================================================================
def _mod_users_repo(BaseRepository, clock, connection):
    """用户、会话、登录记录的数据访问层。"""


    from typing import Any



    class UserRepository(BaseRepository):
        table = "users"
        writable = (
            "username",
            "password_hash",
            "password_salt",
            "role",
            "real_name",
            "number",
            "email",
            "phone",
            "department",
            "class_name",
            "avatar",
            "status",
            "must_change_password",
            "last_login_at",
        )

        def by_username(self, username: str) -> dict[str, Any] | None:
            return self.find_by(username=username)

        def by_number(self, number: str) -> dict[str, Any] | None:
            return self.find_by(number=number)

        def list_by_role(self, role: str, *, keyword: str = "",
                         limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
            sql = "SELECT * FROM users WHERE role = ?"
            params: list[Any] = [role]
            if keyword:
                sql += " AND (username LIKE ? OR real_name LIKE ? OR number LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like, like])
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return connection.query_all(sql, tuple(params))

        def count_by_role(self, role: str, keyword: str = "") -> int:
            sql = "SELECT COUNT(*) FROM users WHERE role = ?"
            params: list[Any] = [role]
            if keyword:
                sql += " AND (username LIKE ? OR real_name LIKE ? OR number LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like, like])
            return int(connection.scalar(sql, tuple(params), default=0) or 0)

        def search(self, keyword: str, *, limit: int = 20) -> list[dict[str, Any]]:
            like = f"%{keyword}%"
            return connection.query_all(
                """SELECT id, username, real_name, role, number, department
                   FROM users
                   WHERE status = 'active'
                     AND (username LIKE ? OR real_name LIKE ? OR number LIKE ?)
                   ORDER BY role, id
                   LIMIT ?""",
                (like, like, like, limit),
            )

        def touch_login(self, user_id: int) -> None:
            connection.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (clock.now_iso(), clock.now_iso(), user_id),
            )

        def set_password(self, user_id: int, password_hash: str, salt: str,
                         must_change: bool = False) -> None:
            connection.execute(
                """UPDATE users
                      SET password_hash = ?, password_salt = ?, must_change_password = ?,
                          updated_at = ?
                    WHERE id = ?""",
                (password_hash, salt, 1 if must_change else 0, clock.now_iso(), user_id),
            )

        def set_status(self, user_id: int, status: str) -> None:
            connection.execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
                (status, clock.now_iso(), user_id),
            )

        def count_all(self) -> dict[str, int]:
            rows = connection.query_all(
                "SELECT role, COUNT(*) AS n FROM users GROUP BY role"
            )
            result = {"student": 0, "teacher": 0, "admin": 0}
            for row in rows:
                result[row["role"]] = row["n"]
            return result

        def departments(self) -> list[str]:
            rows = connection.query_all(
                """SELECT DISTINCT department FROM users
                   WHERE department IS NOT NULL AND department <> ''
                   ORDER BY department"""
            )
            return [row["department"] for row in rows]


    class SessionRepository(BaseRepository):
        table = "sessions"
        writable = ("user_id", "token", "user_agent", "ip", "expires_at", "revoked_at")
        created_field = "created_at"
        updated_field = ""

        def by_token(self, token: str) -> dict[str, Any] | None:
            return self.find_by(token=token)

        def create(self, user_id: int, token: str, expires_at: str,
                   *, ip: str = "", user_agent: str = "") -> int:
            return self.insert(
                {
                    "user_id": user_id,
                    "token": token,
                    "expires_at": expires_at,
                    "ip": ip,
                    "user_agent": user_agent[:300],
                }
            )

        def revoke(self, token: str) -> None:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token = ?",
                (clock.now_iso(), token),
            )

        def revoke_all_for_user(self, user_id: int) -> int:
            return connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (clock.now_iso(), user_id),
            )

        def purge_expired(self) -> int:
            return connection.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (clock.now_iso(),)
            )

        def active_sessions(self, user_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                """SELECT id, ip, user_agent, created_at, expires_at
                     FROM sessions
                    WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?
                    ORDER BY created_at DESC""",
                (user_id, clock.now_iso()),
            )


    class LoginAttemptRepository(BaseRepository):
        table = "login_attempts"
        writable = ("username", "success", "ip")
        created_field = "created_at"
        updated_field = ""

        def record(self, username: str, success: bool, ip: str = "") -> None:
            self.insert({"username": username, "success": 1 if success else 0, "ip": ip})

        def recent_failures(self, username: str, seconds: int) -> int:
            threshold = clock.from_timestamp(
                clock.utcnow().timestamp() - seconds
            )
            return int(
                connection.scalar(
                    """SELECT COUNT(*) FROM login_attempts
                        WHERE username = ? AND success = 0 AND created_at > ?""",
                    (username, threshold),
                    default=0,
                )
                or 0
            )

        def last_failure_at(self, username: str) -> str | None:
            return connection.scalar(
                """SELECT created_at FROM login_attempts
                    WHERE username = ? AND success = 0
                    ORDER BY id DESC LIMIT 1""",
                (username,),
            )

        def clear(self, username: str) -> None:
            connection.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
    return SimpleNamespace(
        UserRepository=UserRepository,
        SessionRepository=SessionRepository,
        LoginAttemptRepository=LoginAttemptRepository,
    )


# ======================================================================
# 模块：backend/repositories/courses.py
# ======================================================================
def _mod_courses_repo(BaseRepository, clock, connection):
    """课程、教学班、选课关系的数据访问层。"""


    from typing import Any



    class CourseRepository(BaseRepository):
        table = "courses"
        writable = (
            "code",
            "name",
            "teacher_id",
            "term",
            "credits",
            "hours",
            "category",
            "cover",
            "description",
            "status",
        )

        BASE_SELECT = """
            SELECT c.*,
                   u.real_name AS teacher_name,
                   u.department AS teacher_department,
                   (SELECT COUNT(*) FROM classes cl WHERE cl.course_id = c.id) AS class_count,
                   (SELECT COUNT(*) FROM enrollments e
                      JOIN classes cl2 ON cl2.id = e.class_id
                     WHERE cl2.course_id = c.id AND e.status = 'active') AS student_count
              FROM courses c
              LEFT JOIN users u ON u.id = c.teacher_id
        """

        def detail(self, course_id: int) -> dict[str, Any] | None:
            return connection.query_one(
                self.BASE_SELECT + " WHERE c.id = ?", (course_id,)
            )

        def list_courses(
            self,
            *,
            teacher_id: int | None = None,
            term: str = "",
            keyword: str = "",
            status: str = "active",
            limit: int = 20,
            offset: int = 0,
        ) -> list[dict[str, Any]]:
            sql = self.BASE_SELECT + " WHERE 1 = 1"
            params: list[Any] = []
            if teacher_id:
                sql += " AND c.teacher_id = ?"
                params.append(teacher_id)
            if term:
                sql += " AND c.term = ?"
                params.append(term)
            if status:
                sql += " AND c.status = ?"
                params.append(status)
            if keyword:
                sql += " AND (c.name LIKE ? OR c.code LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like])
            sql += " ORDER BY c.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return connection.query_all(sql, tuple(params))

        def count_courses(self, *, teacher_id: int | None = None, term: str = "",
                          keyword: str = "", status: str = "active") -> int:
            sql = "SELECT COUNT(*) FROM courses c WHERE 1 = 1"
            params: list[Any] = []
            if teacher_id:
                sql += " AND c.teacher_id = ?"
                params.append(teacher_id)
            if term:
                sql += " AND c.term = ?"
                params.append(term)
            if status:
                sql += " AND c.status = ?"
                params.append(status)
            if keyword:
                sql += " AND (c.name LIKE ? OR c.code LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like])
            return int(connection.scalar(sql, tuple(params), default=0) or 0)

        def by_code(self, code: str) -> dict[str, Any] | None:
            return self.find_by(code=code)

        def of_student(self, student_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                """
                SELECT c.*, u.real_name AS teacher_name,
                       cl.id AS class_id, cl.name AS class_name, cl.join_code,
                       cl.schedule, cl.location,
                       (SELECT COUNT(*) FROM assignments a
                         WHERE a.class_id = cl.id AND a.status = 'published') AS assignment_count,
                       (SELECT COUNT(*) FROM attendance_sessions s
                         WHERE s.class_id = cl.id) AS attendance_count
                  FROM enrollments e
                  JOIN classes cl ON cl.id = e.class_id
                  JOIN courses c  ON c.id = cl.course_id
                  LEFT JOIN users u ON u.id = c.teacher_id
                 WHERE e.student_id = ? AND e.status = 'active'
                 ORDER BY c.term DESC, c.name
                """,
                (student_id,),
            )

        def teacher_names(self) -> list[dict[str, Any]]:
            return connection.query_all(
                "SELECT id, real_name FROM users WHERE role = 'teacher' AND status = 'active'"
            )


    class ClassRepository(BaseRepository):
        table = "classes"
        writable = (
            "course_id",
            "name",
            "join_code",
            "semester",
            "location",
            "schedule",
            "capacity",
            "status",
        )
        updated_field = ""

        def by_join_code(self, code: str) -> dict[str, Any] | None:
            return self.find_by(join_code=code.upper())

        def of_course(self, course_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                """SELECT cl.*,
                          (SELECT COUNT(*) FROM enrollments e
                            WHERE e.class_id = cl.id AND e.status = 'active') AS student_count
                     FROM classes cl
                    WHERE cl.course_id = ?
                    ORDER BY cl.id""",
                (course_id,),
            )

        def detail(self, class_id: int) -> dict[str, Any] | None:
            return connection.query_one(
                """SELECT cl.*, c.name AS course_name, c.code AS course_code,
                          c.teacher_id, u.real_name AS teacher_name, c.credits, c.term
                     FROM classes cl
                     JOIN courses c ON c.id = cl.course_id
                     LEFT JOIN users u ON u.id = c.teacher_id
                    WHERE cl.id = ?""",
                (class_id,),
            )

        def of_teacher(self, teacher_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                """SELECT cl.*, c.name AS course_name, c.code AS course_code,
                          (SELECT COUNT(*) FROM enrollments e
                            WHERE e.class_id = cl.id AND e.status = 'active') AS student_count
                     FROM classes cl
                     JOIN courses c ON c.id = cl.course_id
                    WHERE c.teacher_id = ?
                    ORDER BY c.term DESC, c.name""",
                (teacher_id,),
            )

        def students(self, class_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                """SELECT u.id, u.username, u.real_name, u.number, u.department,
                          u.class_name, u.email, u.phone, e.created_at AS enrolled_at
                     FROM enrollments e
                     JOIN users u ON u.id = e.student_id
                    WHERE e.class_id = ? AND e.status = 'active'
                    ORDER BY u.number, u.id""",
                (class_id,),
            )

        def student_count(self, class_id: int) -> int:
            return int(
                connection.scalar(
                    "SELECT COUNT(*) FROM enrollments WHERE class_id = ? AND status = 'active'",
                    (class_id,),
                    default=0,
                )
                or 0
            )


    class EnrollmentRepository(BaseRepository):
        table = "enrollments"
        writable = ("class_id", "student_id", "status", "source")
        updated_field = ""

        def get(self, class_id: int, student_id: int) -> dict[str, Any] | None:
            return self.find_by(class_id=class_id, student_id=student_id)

        def enroll(self, class_id: int, student_id: int, source: str = "self") -> int:
            existing = self.get(class_id, student_id)
            if existing:
                if existing["status"] != "active":
                    connection.execute(
                        "UPDATE enrollments SET status = 'active', created_at = ? WHERE id = ?",
                        (clock.now_iso(), existing["id"]),
                    )
                return int(existing["id"])
            return self.insert(
                {"class_id": class_id, "student_id": student_id, "source": source}
            )

        def drop(self, class_id: int, student_id: int) -> None:
            connection.execute(
                """UPDATE enrollments SET status = 'dropped'
                    WHERE class_id = ? AND student_id = ?""",
                (class_id, student_id),
            )

        def is_enrolled(self, class_id: int, student_id: int) -> bool:
            row = connection.scalar(
                """SELECT 1 FROM enrollments
                    WHERE class_id = ? AND student_id = ? AND status = 'active'""",
                (class_id, student_id),
            )
            return row is not None

        def class_ids_of_student(self, student_id: int) -> list[int]:
            rows = connection.query_all(
                "SELECT class_id FROM enrollments WHERE student_id = ? AND status = 'active'",
                (student_id,),
            )
            return [int(row["class_id"]) for row in rows]

        def student_count_for_courses(self, course_ids: list[int]) -> dict[int, int]:
            if not course_ids:
                return {}
            placeholders = ",".join("?" for _ in course_ids)
            rows = connection.query_all(
                f"""SELECT cl.course_id, COUNT(e.id) AS n
                      FROM classes cl
                      LEFT JOIN enrollments e
                        ON e.class_id = cl.id AND e.status = 'active'
                     WHERE cl.course_id IN ({placeholders})
                     GROUP BY cl.course_id""",
                tuple(course_ids),
            )
            return {int(row["course_id"]): int(row["n"]) for row in rows}
    return SimpleNamespace(
        CourseRepository=CourseRepository,
        ClassRepository=ClassRepository,
        EnrollmentRepository=EnrollmentRepository,
    )


# ======================================================================
# 模块：backend/repositories/assignments.py
# ======================================================================
def _mod_assignments_repo(BaseRepository, clock, connection):
    """作业与作业提交的数据访问层。"""


    from typing import Any



    class AssignmentRepository(BaseRepository):
        table = "assignments"
        writable = (
            "class_id",
            "title",
            "content",
            "attachments",
            "full_score",
            "deadline",
            "allow_late",
            "late_penalty",
            "publish_at",
            "status",
            "created_by",
        )

        BASE_SELECT = """
            SELECT a.*,
                   cl.name AS class_name,
                   c.name  AS course_name,
                   c.id    AS course_id,
                   (SELECT COUNT(*) FROM submissions s
                     WHERE s.assignment_id = a.id) AS submission_count,
                   (SELECT COUNT(*) FROM enrollments e
                     WHERE e.class_id = a.class_id AND e.status = 'active') AS student_total
              FROM assignments a
              JOIN classes cl ON cl.id = a.class_id
              JOIN courses c  ON c.id = cl.course_id
        """

        def detail(self, assignment_id: int) -> dict[str, Any] | None:
            return connection.query_one(
                self.BASE_SELECT + " WHERE a.id = ?", (assignment_id,)
            )

        def list_by_class(self, class_id: int, *, limit: int = 50,
                          offset: int = 0) -> list[dict[str, Any]]:
            return connection.query_all(
                self.BASE_SELECT + " WHERE a.class_id = ? ORDER BY a.created_at DESC LIMIT ? OFFSET ?",
                (class_id, limit, offset),
            )

        def list_for_student(self, student_id: int, *, status: str = "",
                             limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
            sql = """
                SELECT a.*, cl.name AS class_name, c.name AS course_name,
                       s.status AS submission_status, s.score, s.id AS submission_id,
                       s.submitted_at
                  FROM assignments a
                  JOIN classes cl ON cl.id = a.class_id
                  JOIN courses c  ON c.id = cl.course_id
                  JOIN enrollments e ON e.class_id = a.class_id
                                    AND e.student_id = ? AND e.status = 'active'
                  LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
                 WHERE a.status <> 'draft'
            """
            params: list[Any] = [student_id, student_id]
            if status == "pending":
                sql += " AND s.id IS NULL"
            elif status == "submitted":
                sql += " AND s.id IS NOT NULL"
            elif status == "graded":
                sql += " AND s.status = 'graded'"
            sql += " ORDER BY a.created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return connection.query_all(sql, tuple(params))

        def count_for_student(self, student_id: int, status: str = "") -> int:
            sql = """
                SELECT COUNT(*)
                  FROM assignments a
                  JOIN enrollments e ON e.class_id = a.class_id
                                    AND e.student_id = ? AND e.status = 'active'
                  LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
                 WHERE a.status <> 'draft'
            """
            params: list[Any] = [student_id, student_id]
            if status == "pending":
                sql += " AND s.id IS NULL"
            elif status == "submitted":
                sql += " AND s.id IS NOT NULL"
            elif status == "graded":
                sql += " AND s.status = 'graded'"
            return int(connection.scalar(sql, tuple(params), default=0) or 0)

        def upcoming_for_student(self, student_id: int, limit: int = 5) -> list[dict[str, Any]]:
            return connection.query_all(
                """SELECT a.id, a.title, a.deadline, c.name AS course_name,
                          s.id AS submission_id
                     FROM assignments a
                     JOIN classes cl ON cl.id = a.class_id
                     JOIN courses c  ON c.id = cl.course_id
                     JOIN enrollments e ON e.class_id = a.class_id
                                       AND e.student_id = ? AND e.status = 'active'
                     LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
                    WHERE a.status = 'published' AND s.id IS NULL
                      AND (a.deadline IS NULL OR a.deadline > ?)
                    ORDER BY COALESCE(a.deadline, '9999') ASC
                    LIMIT ?""",
                (student_id, student_id, clock.now_iso(), limit),
            )


    class SubmissionRepository(BaseRepository):
        table = "submissions"
        writable = (
            "assignment_id",
            "student_id",
            "content",
            "attachments",
            "status",
            "score",
            "feedback",
            "graded_by",
            "graded_at",
            "is_late",
            "submitted_at",
        )

        def by_student(self, assignment_id: int, student_id: int) -> dict[str, Any] | None:
            return connection.query_one(
                """SELECT s.*, u.real_name AS student_name, u.number
                     FROM submissions s
                     JOIN users u ON u.id = s.student_id
                    WHERE s.assignment_id = ? AND s.student_id = ?""",
                (assignment_id, student_id),
            )

        def list_by_assignment(self, assignment_id: int, *, status: str = "") -> list[dict[str, Any]]:
            sql = """
                SELECT s.*, u.real_name AS student_name, u.number, u.department
                  FROM submissions s
                  JOIN users u ON u.id = s.student_id
                 WHERE s.assignment_id = ?
            """
            params: list[Any] = [assignment_id]
            if status:
                sql += " AND s.status = ?"
                params.append(status)
            sql += " ORDER BY s.submitted_at ASC"
            return connection.query_all(sql, tuple(params))

        def upsert_submission(self, assignment_id: int, student_id: int,
                              data: dict[str, Any]) -> int:
            existing = connection.query_one(
                "SELECT id FROM submissions WHERE assignment_id = ? AND student_id = ?",
                (assignment_id, student_id),
            )
            if existing:
                self.update(int(existing["id"]), data)
                return int(existing["id"])
            payload = dict(data)
            payload.update({"assignment_id": assignment_id, "student_id": student_id})
            return self.insert(payload)

        def grade(self, submission_id: int, score: float, feedback: str,
                  grader_id: int) -> None:
            connection.execute(
                """UPDATE submissions
                      SET score = ?, feedback = ?, graded_by = ?, graded_at = ?,
                          status = 'graded', updated_at = ?
                    WHERE id = ?""",
                (score, feedback, grader_id, clock.now_iso(), clock.now_iso(), submission_id),
            )

        def stats_for_assignment(self, assignment_id: int) -> dict[str, Any]:
            row = connection.query_one(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN status = 'graded' THEN 1 ELSE 0 END) AS graded,
                          AVG(CASE WHEN score IS NOT NULL THEN score END) AS avg_score,
                          MAX(score) AS max_score,
                          MIN(score) AS min_score
                     FROM submissions WHERE assignment_id = ?""",
                (assignment_id,),
            ) or {}
            return {
                "total": int(row.get("total") or 0),
                "graded": int(row.get("graded") or 0),
                "avg_score": round(float(row.get("avg_score") or 0), 2),
                "max_score": float(row.get("max_score") or 0),
                "min_score": float(row.get("min_score") or 0),
            }

        def student_scores(self, class_id: int, student_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                """SELECT a.id, a.title, a.full_score, s.score, s.status
                     FROM assignments a
                     LEFT JOIN submissions s
                       ON s.assignment_id = a.id AND s.student_id = ?
                    WHERE a.class_id = ? AND a.status = 'published'
                    ORDER BY a.created_at""",
                (student_id, class_id),
            )
    return SimpleNamespace(
        AssignmentRepository=AssignmentRepository,
        SubmissionRepository=SubmissionRepository,
    )


# ======================================================================
# 模块：backend/repositories/quizzes.py
# ======================================================================
def _mod_quizzes_repo(BaseRepository, clock, connection):
    """测验、题库与作答记录的数据访问层。"""


    import json
    from typing import Any



    def _dumps(value: Any) -> str | None:
        """把列表/字典转成 JSON 文本；已经是字符串则原样返回。"""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)


    class QuizRepository(BaseRepository):
        table = "quizzes"
        writable = (
            "class_id",
            "title",
            "description",
            "start_at",
            "end_at",
            "duration",
            "total_score",
            "shuffle",
            "show_answer",
            "status",
            "created_by",
        )
        updated_field = ""

        BASE_SELECT = """
            SELECT q.*,
                   cl.name AS class_name,
                   c.name  AS course_name,
                   c.id    AS course_id,
                   (SELECT COUNT(*) FROM questions qs
                     WHERE qs.quiz_id = q.id) AS question_count,
                   (SELECT COUNT(*) FROM quiz_attempts a
                     WHERE a.quiz_id = q.id) AS attempt_count
              FROM quizzes q
              JOIN classes cl ON cl.id = q.class_id
              JOIN courses c  ON c.id = cl.course_id
        """

        def detail(self, quiz_id: int) -> dict[str, Any] | None:
            """测验详情，附带班级、课程与题量/作答数。"""
            return connection.query_one(
                self.BASE_SELECT + " WHERE q.id = ?", (quiz_id,)
            )

        def list_by_class(self, class_id: int) -> list[dict[str, Any]]:
            """某教学班下的全部测验，按创建时间倒序。"""
            return connection.query_all(
                self.BASE_SELECT
                + " WHERE q.class_id = ? ORDER BY q.created_at DESC, q.id DESC",
                (class_id,),
            )

        def list_for_student(self, student_id: int) -> list[dict[str, Any]]:
            """学生所在班级的全部已发布测验，并带上该生自己的作答状态。"""
            return connection.query_all(
                """
                SELECT q.*,
                       cl.name AS class_name,
                       c.name  AS course_name,
                       c.id    AS course_id,
                       a.id     AS attempt_id,
                       a.status AS attempt_status,
                       a.score
                  FROM quizzes q
                  JOIN classes cl ON cl.id = q.class_id
                  JOIN courses c  ON c.id = cl.course_id
                  JOIN enrollments e ON e.class_id = q.class_id
                                    AND e.student_id = ? AND e.status = 'active'
                  LEFT JOIN quiz_attempts a ON a.quiz_id = q.id
                                           AND a.student_id = ?
                 WHERE q.status = 'published'
                 ORDER BY COALESCE(q.start_at, q.created_at) DESC, q.id DESC
                """,
                (student_id, student_id),
            )


    class QuestionRepository(BaseRepository):
        table = "questions"
        writable = (
            "quiz_id",
            "type",
            "stem",
            "options",
            "answer",
            "analysis",
            "score",
            "order_no",
        )
        created_field = ""
        updated_field = ""

        def list_by_quiz(self, quiz_id: int) -> list[dict[str, Any]]:
            """按题号取出整份试卷的题目。"""
            return connection.query_all(
                "SELECT * FROM questions WHERE quiz_id = ? ORDER BY order_no, id",
                (quiz_id,),
            )

        def count_by_quiz(self, quiz_id: int) -> int:
            return int(
                connection.scalar(
                    "SELECT COUNT(*) FROM questions WHERE quiz_id = ?",
                    (quiz_id,),
                    default=0,
                )
                or 0
            )

        def total_score(self, quiz_id: int) -> float:
            """题目分值合计；没有题目时为 0。"""
            return float(
                connection.scalar(
                    "SELECT COALESCE(SUM(score), 0) FROM questions WHERE quiz_id = ?",
                    (quiz_id,),
                    default=0,
                )
                or 0
            )

        def replace_for_quiz(self, quiz_id: int, questions: list[dict[str, Any]]) -> int:
            """整卷重建：先删除旧题目，再按传入顺序批量插入，返回新题数。"""
            rows: list[tuple[Any, ...]] = []
            for index, item in enumerate(questions):
                score = item.get("score")
                rows.append(
                    (
                        quiz_id,
                        item.get("type", "single"),
                        item.get("stem", ""),
                        _dumps(item.get("options")),
                        item.get("answer", ""),
                        item.get("analysis", ""),
                        5.0 if score is None else float(score),
                        int(item.get("order_no") or index + 1),
                    )
                )
            with connection.transaction() as conn:
                conn.execute("DELETE FROM questions WHERE quiz_id = ?", (quiz_id,))
                if rows:
                    conn.executemany(
                        """INSERT INTO questions
                               (quiz_id, type, stem, options, answer, analysis,
                                score, order_no)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        rows,
                    )
            return len(rows)

        def delete_by_quiz(self, quiz_id: int) -> int:
            return connection.execute(
                "DELETE FROM questions WHERE quiz_id = ?", (quiz_id,)
            )


    class AttemptRepository(BaseRepository):
        table = "quiz_attempts"
        writable = (
            "quiz_id",
            "student_id",
            "answers",
            "score",
            "status",
            "started_at",
            "submitted_at",
        )
        created_field = ""
        updated_field = ""

        def by_student(self, quiz_id: int, student_id: int) -> dict[str, Any] | None:
            """取该生在这份测验上最近的一次作答记录。"""
            return connection.query_one(
                """SELECT * FROM quiz_attempts
                    WHERE quiz_id = ? AND student_id = ?
                    ORDER BY id DESC LIMIT 1""",
                (quiz_id, student_id),
            )

        def start(self, quiz_id: int, student_id: int) -> int:
            """开始作答；已有未提交的记录时直接复用，避免重复开卷。"""
            existing = self.by_student(quiz_id, student_id)
            if existing and existing["status"] == "in_progress":
                return int(existing["id"])
            return self.insert(
                {
                    "quiz_id": quiz_id,
                    "student_id": student_id,
                    "status": "in_progress",
                    "started_at": clock.now_iso(),
                }
            )

        def save_answers(self, attempt_id: int, answers_json: str) -> None:
            """暂存答案（自动保存），不改变作答状态。"""
            connection.execute(
                "UPDATE quiz_attempts SET answers = ? WHERE id = ?",
                (answers_json, attempt_id),
            )

        def submit(self, attempt_id: int, score: float, answers_json: str) -> None:
            """交卷：写入答案、得分与提交时间。"""
            connection.execute(
                """UPDATE quiz_attempts
                      SET answers = ?, score = ?, status = 'submitted',
                          submitted_at = ?
                    WHERE id = ?""",
                (answers_json, score, clock.now_iso(), attempt_id),
            )

        def list_by_quiz(self, quiz_id: int) -> list[dict[str, Any]]:
            """某场测验的全部作答，按分数从高到低（未交卷的排在最后）。"""
            return connection.query_all(
                """SELECT a.*, u.real_name, u.number
                     FROM quiz_attempts a
                     JOIN users u ON u.id = a.student_id
                    WHERE a.quiz_id = ?
                    ORDER BY (a.score IS NULL), a.score DESC, a.id ASC""",
                (quiz_id,),
            )

        def stats(self, quiz_id: int) -> dict[str, Any]:
            """测验统计；及格线固定按卷面总分的 60% 计算，通过率返回百分数。"""
            quiz_total = float(
                connection.scalar(
                    "SELECT total_score FROM quizzes WHERE id = ?",
                    (quiz_id,),
                    default=0,
                )
                or 0
            )
            pass_score = round(quiz_total * 0.6, 2)
            row = connection.query_one(
                """SELECT COUNT(*) AS count,
                          SUM(CASE WHEN status IN ('submitted', 'graded')
                                   THEN 1 ELSE 0 END) AS submitted,
                          AVG(CASE WHEN status IN ('submitted', 'graded')
                                   THEN score END) AS avg_score,
                          MAX(CASE WHEN status IN ('submitted', 'graded')
                                   THEN score END) AS max_score,
                          MIN(CASE WHEN status IN ('submitted', 'graded')
                                   THEN score END) AS min_score,
                          SUM(CASE WHEN status IN ('submitted', 'graded')
                                    AND score >= ? THEN 1 ELSE 0 END) AS passed
                     FROM quiz_attempts
                    WHERE quiz_id = ?""",
                (pass_score, quiz_id),
            ) or {}
            submitted = int(row.get("submitted") or 0)
            passed = int(row.get("passed") or 0)
            return {
                "count": int(row.get("count") or 0),
                "submitted": submitted,
                "avg_score": round(float(row.get("avg_score") or 0), 2),
                "max_score": round(float(row.get("max_score") or 0), 2),
                "min_score": round(float(row.get("min_score") or 0), 2),
                "pass_rate": round(passed / submitted * 100, 1) if submitted else 0.0,
            }
    return SimpleNamespace(
        QuizRepository=QuizRepository,
        QuestionRepository=QuestionRepository,
        AttemptRepository=AttemptRepository,
    )


# ======================================================================
# 模块：backend/repositories/attendance.py
# ======================================================================
def _mod_attendance_repo(BaseRepository, clock, connection):
    """签到活动与签到记录的数据访问层。"""


    from typing import Any



    class AttendanceSessionRepository(BaseRepository):
        table = "attendance_sessions"
        writable = (
            "class_id",
            "title",
            "method",
            "code",
            "start_at",
            "end_at",
            "latitude",
            "longitude",
            "radius",
            "status",
            "created_by",
        )
        updated_field = ""

        BASE_SELECT = """
            SELECT s.*,
                   cl.name AS class_name,
                   c.name  AS course_name,
                   c.id    AS course_id,
                   (SELECT COUNT(*) FROM attendance_records r
                     WHERE r.session_id = s.id
                       AND r.status IN ('present', 'late')) AS checked_count,
                   (SELECT COUNT(*) FROM enrollments e
                     WHERE e.class_id = s.class_id
                       AND e.status = 'active') AS student_total
              FROM attendance_sessions s
              JOIN classes cl ON cl.id = s.class_id
              JOIN courses c  ON c.id = cl.course_id
        """

        def detail(self, session_id: int) -> dict[str, Any] | None:
            """签到活动详情，附带班级名与课程名。"""
            return connection.query_one(
                self.BASE_SELECT + " WHERE s.id = ?", (session_id,)
            )

        def list_by_class(self, class_id: int) -> list[dict[str, Any]]:
            """某教学班的全部签到活动，新发起的排前面。"""
            return connection.query_all(
                self.BASE_SELECT
                + " WHERE s.class_id = ? ORDER BY s.start_at DESC, s.id DESC",
                (class_id,),
            )

        def list_open_for_student(self, student_id: int) -> list[dict[str, Any]]:
            """该生所在班级中仍在进行（open 且未到结束时间）的签到。"""
            return connection.query_all(
                """
                SELECT s.*,
                       cl.name AS class_name,
                       c.name  AS course_name,
                       c.id    AS course_id,
                       r.status     AS record_status,
                       r.checked_at AS checked_at
                  FROM attendance_sessions s
                  JOIN classes cl ON cl.id = s.class_id
                  JOIN courses c  ON c.id = cl.course_id
                  JOIN enrollments e ON e.class_id = s.class_id
                                    AND e.student_id = ? AND e.status = 'active'
                  LEFT JOIN attendance_records r ON r.session_id = s.id
                                                AND r.student_id = ?
                 WHERE s.status = 'open' AND s.end_at > ?
                 ORDER BY s.end_at ASC
                """,
                (student_id, student_id, clock.now_iso()),
            )

        def close(self, session_id: int) -> None:
            """手动结束签到。"""
            connection.execute(
                "UPDATE attendance_sessions SET status = 'closed' WHERE id = ?",
                (session_id,),
            )

        def close_expired(self) -> int:
            """把所有已过结束时间但仍是 open 的签到批量关闭，返回关闭数量。"""
            connection.execute(
                """UPDATE attendance_sessions SET status = 'closed'
                    WHERE status = 'open' AND end_at <= ?""",
                (clock.now_iso(),),
            )
            # connection.execute 返回的是 lastrowid，这里用 changes() 取真实影响行数
            return int(connection.scalar("SELECT changes()", default=0) or 0)


    class AttendanceRecordRepository(BaseRepository):
        table = "attendance_records"
        writable = ("session_id", "student_id", "status", "checked_at", "note")
        created_field = ""
        updated_field = ""

        def mark(self, session_id: int, student_id: int, status: str,
                 note: str = "") -> int:
            """签到/改签：已有记录则更新状态，否则新建，返回记录 id。"""
            now = clock.now_iso()
            existing = self.find_by(session_id=session_id, student_id=student_id)
            if existing:
                connection.execute(
                    """UPDATE attendance_records
                          SET status = ?, checked_at = ?, note = ?
                        WHERE id = ?""",
                    (status, now, note, existing["id"]),
                )
                return int(existing["id"])
            return self.insert(
                {
                    "session_id": session_id,
                    "student_id": student_id,
                    "status": status,
                    "checked_at": now,
                    "note": note,
                }
            )

        def list_by_session(self, session_id: int) -> list[dict[str, Any]]:
            """某次签到的全部记录，联用户表取姓名与学号。"""
            return connection.query_all(
                """SELECT r.*, u.real_name, u.number
                     FROM attendance_records r
                     JOIN users u ON u.id = r.student_id
                    WHERE r.session_id = ?
                    ORDER BY u.number, u.id""",
                (session_id,),
            )

        def student_summary(self, class_id: int,
                            student_id: int) -> dict[str, Any]:
            """单个学生在某教学班的出勤统计；rate 为 0~1 的出勤比例（正常 + 迟到）。"""
            row = connection.query_one(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN r.status = 'present' THEN 1 ELSE 0 END) AS present,
                          SUM(CASE WHEN r.status = 'late'    THEN 1 ELSE 0 END) AS late,
                          SUM(CASE WHEN r.status = 'absent'  THEN 1 ELSE 0 END) AS absent,
                          SUM(CASE WHEN r.status = 'leave'   THEN 1 ELSE 0 END) AS leave
                     FROM attendance_records r
                     JOIN attendance_sessions s ON s.id = r.session_id
                    WHERE s.class_id = ? AND r.student_id = ?""",
                (class_id, student_id),
            ) or {}
            total = int(row.get("total") or 0)
            present = int(row.get("present") or 0)
            late = int(row.get("late") or 0)
            return {
                "total": total,
                "present": present,
                "late": late,
                "absent": int(row.get("absent") or 0),
                "leave": int(row.get("leave") or 0),
                "rate": round((present + late) / total, 4) if total else 0.0,
            }

        def class_summary(self, class_id: int) -> list[dict[str, Any]]:
            """整班出勤汇总：每个在读学生一行，没有记录的学生也保留。

            rate 与 student_summary 一致，都是 0~1 的比例。
            """
            rows = connection.query_all(
                """SELECT u.id, u.real_name, u.number,
                          COALESCE(a.present, 0) AS present,
                          COALESCE(a.late, 0)    AS late,
                          COALESCE(a.absent, 0)  AS absent,
                          COALESCE(a.leave, 0)   AS leave,
                          COALESCE(a.total, 0)   AS total
                     FROM enrollments e
                     JOIN users u ON u.id = e.student_id
                     LEFT JOIN (
                          SELECT r.student_id,
                                 SUM(CASE WHEN r.status = 'present' THEN 1 ELSE 0 END) AS present,
                                 SUM(CASE WHEN r.status = 'late'    THEN 1 ELSE 0 END) AS late,
                                 SUM(CASE WHEN r.status = 'absent'  THEN 1 ELSE 0 END) AS absent,
                                 SUM(CASE WHEN r.status = 'leave'   THEN 1 ELSE 0 END) AS leave,
                                 COUNT(*) AS total
                            FROM attendance_records r
                            JOIN attendance_sessions s ON s.id = r.session_id
                           WHERE s.class_id = ?
                           GROUP BY r.student_id
                     ) a ON a.student_id = u.id
                    WHERE e.class_id = ? AND e.status = 'active'
                    ORDER BY u.number, u.id""",
                (class_id, class_id),
            )
            summary: list[dict[str, Any]] = []
            for row in rows:
                total = int(row["total"] or 0)
                present = int(row["present"] or 0)
                late = int(row["late"] or 0)
                summary.append(
                    {
                        "id": int(row["id"]),
                        "real_name": row["real_name"],
                        "number": row["number"],
                        "present": present,
                        "late": late,
                        "absent": int(row["absent"] or 0),
                        "leave": int(row["leave"] or 0),
                        "total": total,
                        "rate": round((present + late) / total, 4)
                        if total
                        else 0.0,
                    }
                )
            return summary
    return SimpleNamespace(
        AttendanceSessionRepository=AttendanceSessionRepository,
        AttendanceRecordRepository=AttendanceRecordRepository,
    )


# ======================================================================
# 模块：backend/repositories/content.py
# ======================================================================
def _mod_content_repo(BaseRepository, clock, connection):
    """教学资料、讨论区、通知的数据访问层。"""


    from typing import Any



    class AnnouncementRepository(BaseRepository):
        """课程公告。"""

        table = "announcements"
        writable = ("course_id", "title", "content", "author_id", "pinned")

        BASE_SELECT = """
            SELECT a.*, u.real_name AS author_name, c.name AS course_name
              FROM announcements a
              LEFT JOIN users u ON u.id = a.author_id
              LEFT JOIN courses c ON c.id = a.course_id
        """

        def list_by_course(self, course_id: int, limit: int = 50) -> list[dict[str, Any]]:
            return connection.query_all(
                self.BASE_SELECT
                + " WHERE a.course_id = ? ORDER BY a.pinned DESC, a.created_at DESC, a.id DESC LIMIT ?",
                (course_id, limit),
            )

        def detail(self, announcement_id: int) -> dict[str, Any] | None:
            return connection.query_one(self.BASE_SELECT + " WHERE a.id = ?", (announcement_id,))

        def list_for_student(self, student_id: int, limit: int = 20) -> list[dict[str, Any]]:
            return connection.query_all(
                self.BASE_SELECT
                + """ WHERE a.course_id IN (
                          SELECT cl.course_id FROM enrollments e
                            JOIN classes cl ON cl.id = e.class_id
                           WHERE e.student_id = ? AND e.status = 'active')
                      ORDER BY a.created_at DESC, a.id DESC LIMIT ?""",
                (student_id, limit),
            )


    class ResourceRepository(BaseRepository):
        table = "resources"
        writable = (
            "course_id",
            "title",
            "description",
            "filename",
            "stored_name",
            "size",
            "mime",
            "category",
            "downloads",
            "uploader_id",
        )
        updated_field = ""

        BASE_SELECT = """
            SELECT r.*, u.real_name AS uploader_name
              FROM resources r
              LEFT JOIN users u ON u.id = r.uploader_id
        """

        def list_by_course(self, course_id: int,
                           keyword: str = "") -> list[dict[str, Any]]:
            """某课程下的资料列表，可按标题/文件名/说明模糊筛选。"""
            sql = self.BASE_SELECT + " WHERE r.course_id = ?"
            params: list[Any] = [course_id]
            if keyword:
                sql += " AND (r.title LIKE ? OR r.filename LIKE ? OR r.description LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like, like])
            sql += " ORDER BY r.created_at DESC, r.id DESC"
            return connection.query_all(sql, tuple(params))

        def detail(self, resource_id: int) -> dict[str, Any] | None:
            """资料详情（含上传者姓名）。"""
            return connection.query_one(
                self.BASE_SELECT + " WHERE r.id = ?", (resource_id,)
            )

        def increment_download(self, resource_id: int) -> None:
            """下载计数加一。"""
            connection.execute(
                "UPDATE resources SET downloads = downloads + 1 WHERE id = ?",
                (resource_id,),
            )


    class DiscussionRepository(BaseRepository):
        table = "discussions"
        writable = ("course_id", "title", "content", "author_id", "pinned", "locked")

        BASE_SELECT = """
            SELECT d.*,
                   u.real_name AS author_name,
                   (SELECT COUNT(*) FROM discussion_replies r
                     WHERE r.discussion_id = d.id) AS reply_count
              FROM discussions d
              JOIN users u ON u.id = d.author_id
        """

        def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
            """课程讨论列表：置顶帖优先，其余按最后更新时间倒序。"""
            return connection.query_all(
                self.BASE_SELECT
                + """ WHERE d.course_id = ?
                      ORDER BY d.pinned DESC, d.updated_at DESC, d.id DESC""",
                (course_id,),
            )

        def detail(self, discussion_id: int) -> dict[str, Any] | None:
            """讨论帖详情（含作者姓名与回复数）。"""
            return connection.query_one(
                self.BASE_SELECT + " WHERE d.id = ?", (discussion_id,)
            )

        def increment_views(self, discussion_id: int) -> None:
            """浏览计数加一。"""
            connection.execute(
                "UPDATE discussions SET views = views + 1 WHERE id = ?",
                (discussion_id,),
            )


    class ReplyRepository(BaseRepository):
        table = "discussion_replies"
        writable = ("discussion_id", "author_id", "content", "parent_id")
        updated_field = ""

        def list_by_discussion(self, discussion_id: int) -> list[dict[str, Any]]:
            """按时间正序取出某帖的全部回复，联用户表带作者姓名与角色。"""
            return connection.query_all(
                """SELECT r.*,
                          u.real_name AS author_name,
                          u.role      AS author_role
                     FROM discussion_replies r
                     JOIN users u ON u.id = r.author_id
                    WHERE r.discussion_id = ?
                    ORDER BY r.created_at ASC, r.id ASC""",
                (discussion_id,),
            )

        def count_by_discussion(self, discussion_id: int) -> int:
            return int(
                connection.scalar(
                    "SELECT COUNT(*) FROM discussion_replies WHERE discussion_id = ?",
                    (discussion_id,),
                    default=0,
                )
                or 0
            )


    class NotificationRepository(BaseRepository):
        table = "notifications"
        writable = ("user_id", "title", "content", "category", "link", "is_read")
        updated_field = ""

        def create(self, user_id: int, title: str, content: str = "",
                   category: str = "system", link: str = "") -> int:
            """给单个用户发一条通知，返回通知 id。"""
            return self.insert(
                {
                    "user_id": user_id,
                    "title": title,
                    "content": content,
                    "category": category,
                    "link": link,
                    "is_read": 0,
                }
            )

        def create_many(self, user_ids: list[int], title: str, content: str = "",
                        category: str = "system", link: str = "") -> int:
            """批量发送同一内容的通知，返回实际写入条数。"""
            if not user_ids:
                return 0
            now = clock.now_iso()
            rows = [
                (user_id, title, content, category, link, 0, now)
                for user_id in user_ids
            ]
            return connection.execute_many(
                """INSERT INTO notifications
                       (user_id, title, content, category, link, is_read, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

        def list_for_user(self, user_id: int, only_unread: bool = False,
                          limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
            """用户的通知列表，默认按时间倒序；可只看未读并分页。"""
            sql = "SELECT * FROM notifications WHERE user_id = ?"
            params: list[Any] = [user_id]
            if only_unread:
                sql += " AND is_read = 0"
            sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return connection.query_all(sql, tuple(params))

        def unread_count(self, user_id: int) -> int:
            return int(
                connection.scalar(
                    "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
                    (user_id,),
                    default=0,
                )
                or 0
            )

        def count_for_user(self, user_id: int, only_unread: bool = False) -> int:
            """通知总数（分页用），可只统计未读。"""
            sql = "SELECT COUNT(*) FROM notifications WHERE user_id = ?"
            if only_unread:
                sql += " AND is_read = 0"
            return int(connection.scalar(sql, (user_id,), default=0) or 0)

        def mark_read(self, notification_id: int, user_id: int) -> int:
            """把某条通知标为已读，返回本次真正更新的行数。"""
            connection.execute(
                """UPDATE notifications SET is_read = 1
                    WHERE id = ? AND user_id = ? AND is_read = 0""",
                (notification_id, user_id),
            )
            # connection.execute 返回的是 lastrowid，这里用 changes() 取真实影响行数
            return int(connection.scalar("SELECT changes()", default=0) or 0)

        def mark_all_read(self, user_id: int) -> int:
            """全部标为已读，返回更新条数。"""
            connection.execute(
                "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
                (user_id,),
            )
            return int(connection.scalar("SELECT changes()", default=0) or 0)

        def clear_read(self, user_id: int) -> int:
            """清空该用户所有已读通知，返回删除条数。"""
            connection.execute(
                "DELETE FROM notifications WHERE user_id = ? AND is_read = 1",
                (user_id,),
            )
            return int(connection.scalar("SELECT changes()", default=0) or 0)
    return SimpleNamespace(
        AnnouncementRepository=AnnouncementRepository,
        ResourceRepository=ResourceRepository,
        DiscussionRepository=DiscussionRepository,
        ReplyRepository=ReplyRepository,
        NotificationRepository=NotificationRepository,
    )


# ======================================================================
# 模块：backend/repositories/grades.py
# ======================================================================
def _mod_grades_repo(BaseRepository, connection):
    """成绩规则与成绩项的数据访问层。"""


    from typing import Any



    class GradeRuleRepository(BaseRepository):
        table = "grade_rules"
        writable = (
            "class_id",
            "assignment_weight",
            "quiz_weight",
            "attendance_weight",
            "final_weight",
            "pass_score",
        )
        created_field = ""
        updated_field = "updated_at"

        # 与 schema.sql 的默认值保持一致
        DEFAULT_WEIGHTS: dict[str, float] = {
            "assignment_weight": 0.30,
            "quiz_weight": 0.30,
            "attendance_weight": 0.20,
            "final_weight": 0.20,
            "pass_score": 60.0,
        }
        WEIGHT_FIELDS = tuple(DEFAULT_WEIGHTS)
        ALIASES = {
            "assignment": "assignment_weight",
            "quiz": "quiz_weight",
            "attendance": "attendance_weight",
            "final": "final_weight",
        }

        def get_or_default(self, class_id: int) -> dict[str, Any]:
            """取班级成绩权重；尚未配置时返回内置默认值，不写库。"""
            row = self.find_by(class_id=class_id)
            if row:
                return row
            return {"class_id": class_id, **self.DEFAULT_WEIGHTS}

        def save(self, class_id: int, weights: dict[str, Any]) -> int:
            """保存权重（存在则更新、不存在则插入），返回规则 id。

            weights 可传完整列名，也可传 assignment/quiz/attendance/final 简写；
            未传的字段沿用已有配置，首次配置时用默认值。
            """
            existing = self.find_by(class_id=class_id)
            payload = {
                field: (float(existing[field]) if existing and existing[field] is not None
                        else float(self.DEFAULT_WEIGHTS[field]))
                for field in self.WEIGHT_FIELDS
            }
            for key, value in weights.items():
                field = self.ALIASES.get(key, key)
                if field in self.WEIGHT_FIELDS and value is not None:
                    payload[field] = float(value)
            if existing:
                self.update(int(existing["id"]), payload)
                return int(existing["id"])
            return self.insert({"class_id": class_id, **payload})


    class GradeItemRepository(BaseRepository):
        table = "grade_items"
        writable = ("class_id", "student_id", "final_score", "bonus", "remark", "total")
        created_field = ""
        updated_field = "updated_at"

        def get(self, class_id: int, student_id: int) -> dict[str, Any] | None:
            """取某学生在某教学班的成绩行。"""
            return self.find_by(class_id=class_id, student_id=student_id)

        def upsert(self, class_id: int, student_id: int,
                   data: dict[str, Any]) -> int:
            """有则更新、无则插入，返回成绩行 id。"""
            existing = self.get(class_id, student_id)
            if existing:
                self.update(int(existing["id"]), data)
                return int(existing["id"])
            payload = dict(data)
            payload.update({"class_id": class_id, "student_id": student_id})
            return self.insert(payload)

        def list_by_class(self, class_id: int) -> list[dict[str, Any]]:
            """整班成绩行，联用户表取姓名与学号，按学号排序。"""
            return connection.query_all(
                """SELECT g.*, u.real_name, u.number
                     FROM grade_items g
                     JOIN users u ON u.id = g.student_id
                    WHERE g.class_id = ?
                    ORDER BY u.number, u.id""",
                (class_id,),
            )

        def set_total(self, class_id: int, student_id: int, total: float) -> None:
            """回写加权总分缓存；没有成绩行时创建一条。"""
            existing = self.get(class_id, student_id)
            if existing:
                self.update(int(existing["id"]), {"total": total})
                return
            self.insert(
                {"class_id": class_id, "student_id": student_id, "total": total}
            )
    return SimpleNamespace(
        GradeRuleRepository=GradeRuleRepository,
        GradeItemRepository=GradeItemRepository,
    )


# ======================================================================
# 模块：backend/repositories/audit.py
# ======================================================================
def _mod_audit_repo(BaseRepository, connection):
    """审计日志与系统设置的数据访问层。"""


    from typing import Any



    class AuditRepository(BaseRepository):
        table = "audit_logs"
        writable = ("user_id", "username", "action", "entity", "entity_id", "detail", "ip")
        created_field = "created_at"
        updated_field = ""

        def log(self, *, user_id: int | None, username: str, action: str,
                entity: str = "", entity_id: int | None = None,
                detail: str = "", ip: str = "") -> int:
            """记录一条操作日志，返回日志 id。"""
            return self.insert(
                {
                    "user_id": user_id,
                    "username": username,
                    "action": action,
                    "entity": entity,
                    "entity_id": entity_id,
                    "detail": detail,
                    "ip": ip,
                }
            )

        def list_logs(self, *, action: str = "", keyword: str = "",
                      limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
            """按动作类型/关键字筛选日志，最新的排前面。"""
            sql = "SELECT * FROM audit_logs WHERE 1 = 1"
            params: list[Any] = []
            if action:
                sql += " AND action = ?"
                params.append(action)
            if keyword:
                sql += " AND (username LIKE ? OR entity LIKE ? OR detail LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like, like])
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return connection.query_all(sql, tuple(params))

        def count_logs(self, *, action: str = "", keyword: str = "") -> int:
            """与 list_logs 同条件的总数，用于分页。"""
            sql = "SELECT COUNT(*) FROM audit_logs WHERE 1 = 1"
            params: list[Any] = []
            if action:
                sql += " AND action = ?"
                params.append(action)
            if keyword:
                sql += " AND (username LIKE ? OR entity LIKE ? OR detail LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like, like])
            return int(connection.scalar(sql, tuple(params), default=0) or 0)


    class SettingRepository(BaseRepository):
        table = "system_settings"
        pk = "key"
        writable = ("key", "value")
        created_field = ""
        updated_field = "updated_at"

        def get(self, key: str, default: str = "") -> str:
            """读一个配置项，不存在时返回 default。"""
            value = connection.scalar(
                "SELECT value FROM system_settings WHERE key = ?", (key,)
            )
            return str(value) if value is not None else default

        def set(self, key: str, value: str) -> None:
            """写配置项（存在则更新，不存在则插入）。"""
            existing = self.find_by(key=key)
            if existing:
                self.update(key, {"value": value})
                return
            self.insert({"key": key, "value": value})

        def all(self) -> dict[str, str]:
            """一次性读出全部配置，便于启动时做内存缓存。"""
            rows = connection.query_all(
                "SELECT key, value FROM system_settings ORDER BY key"
            )
            return {str(row["key"]): str(row["value"]) for row in rows}
    return SimpleNamespace(
        AuditRepository=AuditRepository,
        SettingRepository=SettingRepository,
    )


# ======================================================================
# 模块：backend/repositories/chapters.py
# ======================================================================
def _mod_chapters_repo(BaseRepository, connection):
    """章节、任务点与学习进度的数据访问层。

    章节属于课程（不是教学班），一个课程下的所有教学班共用同一套章节；
    任务点通过可选的 resource_id / quiz_id / assignment_id 关联到具体内容，
    学生每完成一个任务点就在 task_progress 里留一条记录。
    """


    from typing import Any



    class ChapterRepository(BaseRepository):
        table = "chapters"
        writable = ("course_id", "title", "description", "order_no")

        BASE_SELECT = """
            SELECT ch.*, c.name AS course_name, c.teacher_id,
                   (SELECT COUNT(*) FROM tasks t WHERE t.chapter_id = ch.id) AS task_count
              FROM chapters ch
              JOIN courses c ON c.id = ch.course_id
        """

        def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                self.BASE_SELECT
                + " WHERE ch.course_id = ? ORDER BY ch.order_no, ch.id",
                (course_id,),
            )

        def detail(self, chapter_id: int) -> dict[str, Any] | None:
            return connection.query_one(
                self.BASE_SELECT + " WHERE ch.id = ?", (chapter_id,)
            )

        def next_order_no(self, course_id: int) -> int:
            value = connection.scalar(
                "SELECT MAX(order_no) FROM chapters WHERE course_id = ?",
                (course_id,),
                default=0,
            )
            return int(value or 0) + 1

        def students_of_course(self, course_id: int) -> list[dict[str, Any]]:
            """课程下所有教学班的学生（按学号排序，同一个学生只出现一次）。"""
            return connection.query_all(
                """SELECT u.id AS student_id, u.real_name, u.number, u.department,
                          MIN(cl.id) AS class_id, MIN(cl.name) AS class_name
                     FROM enrollments e
                     JOIN classes cl ON cl.id = e.class_id
                     JOIN users u ON u.id = e.student_id
                    WHERE cl.course_id = ? AND e.status = 'active'
                    GROUP BY u.id
                    ORDER BY u.number, u.id""",
                (course_id,),
            )


    class TaskRepository(BaseRepository):
        table = "tasks"
        writable = (
            "chapter_id",
            "type",
            "title",
            "description",
            "duration",
            "required",
            "resource_id",
            "quiz_id",
            "assignment_id",
            "order_no",
        )

        BASE_SELECT = """
            SELECT t.*, ch.course_id, ch.title AS chapter_title, ch.order_no AS chapter_order,
                   r.title AS resource_title, r.filename AS resource_filename,
                   q.title AS quiz_title, a.title AS assignment_title
              FROM tasks t
              JOIN chapters ch ON ch.id = t.chapter_id
              LEFT JOIN resources r   ON r.id = t.resource_id
              LEFT JOIN quizzes q     ON q.id = t.quiz_id
              LEFT JOIN assignments a ON a.id = t.assignment_id
        """

        def list_by_chapter(self, chapter_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                self.BASE_SELECT
                + " WHERE t.chapter_id = ? ORDER BY t.order_no, t.id",
                (chapter_id,),
            )

        def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                self.BASE_SELECT
                + """ WHERE ch.course_id = ?
                      ORDER BY ch.order_no, ch.id, t.order_no, t.id""",
                (course_id,),
            )

        def detail(self, task_id: int) -> dict[str, Any] | None:
            return connection.query_one(
                self.BASE_SELECT + " WHERE t.id = ?", (task_id,)
            )

        def next_order_no(self, chapter_id: int) -> int:
            value = connection.scalar(
                "SELECT MAX(order_no) FROM tasks WHERE chapter_id = ?",
                (chapter_id,),
                default=0,
            )
            return int(value or 0) + 1

        def course_of(self, task_id: int) -> int | None:
            value = connection.scalar(
                """SELECT ch.course_id FROM tasks t
                     JOIN chapters ch ON ch.id = t.chapter_id
                    WHERE t.id = ?""",
                (task_id,),
            )
            return int(value) if value is not None else None


    class TaskProgressRepository(BaseRepository):
        table = "task_progress"
        writable = (
            "task_id",
            "student_id",
            "status",
            "progress",
            "started_at",
            "finished_at",
        )

        def get(self, task_id: int, student_id: int) -> dict[str, Any] | None:
            return self.find_by(task_id=task_id, student_id=student_id)

        def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
            """课程下所有学习进度，统计用；章节/任务信息一并带出。"""
            return connection.query_all(
                """SELECT tp.*, t.chapter_id, t.title AS task_title
                     FROM task_progress tp
                     JOIN tasks t ON t.id = tp.task_id
                     JOIN chapters ch ON ch.id = t.chapter_id
                    WHERE ch.course_id = ?""",
                (course_id,),
            )

        def list_by_student_course(self, student_id: int,
                                   course_id: int) -> list[dict[str, Any]]:
            return connection.query_all(
                """SELECT tp.task_id, tp.status, tp.progress,
                          tp.started_at, tp.finished_at, tp.updated_at
                     FROM task_progress tp
                     JOIN tasks t ON t.id = tp.task_id
                     JOIN chapters ch ON ch.id = t.chapter_id
                    WHERE ch.course_id = ? AND tp.student_id = ?""",
                (course_id, student_id),
            )

        def save(self, task_id: int, student_id: int,
                 data: dict[str, Any]) -> dict[str, Any]:
            """有记录则更新，无记录则创建，返回最新一条。"""
            existing = self.get(task_id, student_id)
            if existing:
                self.update(int(existing["id"]), data)
            else:
                payload = dict(data)
                payload.update({"task_id": task_id, "student_id": student_id})
                self.insert(payload)
            return self.get(task_id, student_id) or {}
    return SimpleNamespace(
        ChapterRepository=ChapterRepository,
        TaskRepository=TaskRepository,
        TaskProgressRepository=TaskProgressRepository,
    )


# ======================================================================
# 模块：backend/services/search_service.py
# ======================================================================
def _mod_search_service(connection, permissions):
    """全局搜索：一个关键词同时搜课程、作业、资料、讨论、公告。

    按角色限制可见范围：学生只看已选课程，教师只看自己的课，管理员全站。
    SQL 统一用「条件 + 排序 + 限制」三段式拼接，避免把 AND 拼到 ORDER BY 后面。
    """


    from typing import Any


    MAX_PER_TYPE = 10


    def _scope_course_ids(viewer: dict[str, Any]) -> list[int] | None:
        """返回可见课程 id；None 表示不限制（管理员）。"""
        role = viewer["role"]
        if role == permissions.ROLE_ADMIN:
            return None
        if role == permissions.ROLE_TEACHER:
            rows = connection.query_all(
                "SELECT id FROM courses WHERE teacher_id = ?", (int(viewer["id"]),)
            )
            return [int(row["id"]) for row in rows]
        rows = connection.query_all(
            """SELECT DISTINCT cl.course_id
                 FROM enrollments e JOIN classes cl ON cl.id = e.class_id
                WHERE e.student_id = ? AND e.status = 'active'""",
            (int(viewer["id"]),),
        )
        return [int(row["course_id"]) for row in rows]


    def _query(base: str, conditions: list[str], params: list[Any],
               scope_col: str | None, scope: list[int] | None,
               order: str) -> list[dict[str, Any]]:
        """拼出 SELECT：base 已含 FROM/JOIN，conditions 为 WHERE 片段。"""
        conds = list(conditions)
        args = list(params)
        if scope is not None and scope_col:
            if not scope:
                return []
            conds.append(f"{scope_col} IN ({','.join('?' for _ in scope)})")
            args.extend(scope)
        sql = base
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += f" ORDER BY {order} LIMIT ?"
        args.append(MAX_PER_TYPE)
        return connection.query_all(sql, tuple(args))


    def global_search(viewer: dict[str, Any], keyword: str) -> dict[str, Any]:
        keyword = (keyword or "").strip()[:64]
        empty = {
            "keyword": keyword,
            "total": 0,
            "courses": [],
            "assignments": [],
            "resources": [],
            "discussions": [],
            "announcements": [],
        }
        if not keyword:
            return empty

        like = f"%{keyword}%"
        scope = _scope_course_ids(viewer)
        if scope is not None and not scope:
            return empty

        courses = _query(
            """SELECT c.id, c.code, c.name, c.term, u.real_name AS teacher_name
                 FROM courses c LEFT JOIN users u ON u.id = c.teacher_id""",
            ["(c.name LIKE ? OR c.code LIKE ?)", "c.status = 'active'"],
            [like, like],
            "c.id",
            scope,
            "c.id DESC",
        )

        assignments = _query(
            """SELECT a.id, a.title, a.deadline, a.class_id, cl.name AS class_name,
                      c.name AS course_name
                 FROM assignments a
                 JOIN classes cl ON cl.id = a.class_id
                 JOIN courses c ON c.id = cl.course_id""",
            ["a.title LIKE ?", "a.status <> 'draft'"],
            [like],
            "cl.course_id",
            scope,
            "a.id DESC",
        )

        resources = _query(
            """SELECT r.id, r.title, r.filename, r.course_id, c.name AS course_name
                 FROM resources r JOIN courses c ON c.id = r.course_id""",
            ["(r.title LIKE ? OR r.filename LIKE ?)"],
            [like, like],
            "r.course_id",
            scope,
            "r.id DESC",
        )

        discussions = _query(
            """SELECT d.id, d.title, d.course_id, c.name AS course_name,
                      u.real_name AS author_name
                 FROM discussions d
                 JOIN courses c ON c.id = d.course_id
                 LEFT JOIN users u ON u.id = d.author_id""",
            ["d.title LIKE ?"],
            [like],
            "d.course_id",
            scope,
            "d.id DESC",
        )

        announcements = _query(
            """SELECT a.id, a.title, a.course_id, c.name AS course_name, a.created_at
                 FROM announcements a JOIN courses c ON c.id = a.course_id""",
            ["a.title LIKE ?"],
            [like],
            "a.course_id",
            scope,
            "a.id DESC",
        )

        return {
            "keyword": keyword,
            "total": len(courses) + len(assignments) + len(resources)
            + len(discussions) + len(announcements),
            "courses": courses,
            "assignments": assignments,
            "resources": resources,
            "discussions": discussions,
            "announcements": announcements,
        }
    return SimpleNamespace(
        MAX_PER_TYPE=MAX_PER_TYPE,
        global_search=global_search,
    )


# ======================================================================
# 模块：backend/services/auth_service.py
# ======================================================================
def _mod_auth_service(AuditRepository, ForbiddenError, LoginAttemptRepository, RateLimitError, SessionRepository, UnauthorizedError, UserRepository, ValidationError, clock, config, ids, permissions, security):
    """认证服务：登录、登出、会话解析、改密。

    这里承担了所有"谁能进来"的判断：
    - 口令校验（PBKDF2）
    - 失败次数锁定
    - 令牌下发与吊销
    - 账号状态检查
    """


    import logging
    from typing import Any


    logger = logging.getLogger("eduflow.auth")

    user_repo = UserRepository()
    session_repo = SessionRepository()
    attempt_repo = LoginAttemptRepository()
    audit_repo = AuditRepository()

    PUBLIC_USER_FIELDS = (
        "id",
        "username",
        "role",
        "real_name",
        "number",
        "email",
        "phone",
        "department",
        "class_name",
        "avatar",
        "status",
        "created_at",
        "last_login_at",
    )


    def to_public(user: dict[str, Any] | None) -> dict[str, Any] | None:
        """去掉密码哈希等敏感字段。"""
        if not user:
            return None
        result = {key: user.get(key) for key in PUBLIC_USER_FIELDS}
        result["role_label"] = permissions.ROLE_LABELS.get(user.get("role", ""), "")
        result["must_change_password"] = bool(user.get("must_change_password"))
        return result


    def login(username: str, password: str, *, ip: str = "",
              user_agent: str = "") -> dict[str, Any]:
        """校验口令并返回 {token, expires_at, user}。"""
        username = (username or "").strip()
        if not username or not password:
            raise ValidationError("用户名和密码不能为空")

        _check_lock(username, ip)

        user = user_repo.by_username(username) or user_repo.by_number(username)
        if not user:
            attempt_repo.record(username, False, ip)
            raise UnauthorizedError("用户名或密码错误")

        if user["status"] != "active":
            attempt_repo.record(username, False, ip)
            raise ForbiddenError("账号已被禁用，请联系管理员")

        if not security.verify_password(password, user["password_hash"], user["password_salt"]):
            attempt_repo.record(username, False, ip)
            remaining = config.LOGIN_MAX_FAILURES - attempt_repo.recent_failures(
                username, config.LOGIN_LOCK_SECONDS
            )
            if remaining <= 0:
                raise RateLimitError("失败次数过多，账号已临时锁定，请稍后再试")
            raise UnauthorizedError(f"用户名或密码错误，还可尝试 {remaining} 次")

        # 登录成功
        attempt_repo.record(username, True, ip)
        attempt_repo.clear(username)
        token = _issue_token(user, ip=ip, user_agent=user_agent)
        user_repo.touch_login(int(user["id"]))
        audit_repo.log(
            user_id=int(user["id"]),
            username=user["username"],
            action="login",
            entity="user",
            entity_id=int(user["id"]),
            detail=f"登录成功（{ip}）",
            ip=ip,
        )
        refreshed = user_repo.find(int(user["id"])) or user
        return {
            "token": token,
            "expires_at": _expiry(),
            "user": to_public(refreshed),
        }


    def _check_lock(username: str, ip: str) -> None:
        failures = attempt_repo.recent_failures(username, config.LOGIN_LOCK_SECONDS)
        if failures >= config.LOGIN_MAX_FAILURES:
            raise RateLimitError("失败次数过多，账号已临时锁定，请 5 分钟后再试")


    def _expiry() -> str:
        expires = clock.add_minutes(clock.utcnow(), config.TOKEN_TTL_HOURS * 60)
        return clock.to_iso(expires)


    def _issue_token(user: dict[str, Any], *, ip: str, user_agent: str) -> str:
        token = security.new_session_token()
        session_repo.create(
            int(user["id"]), token, _expiry(), ip=ip, user_agent=user_agent
        )
        return token


    def logout(token: str | None) -> None:
        if not token:
            return
        session = session_repo.by_token(token)
        session_repo.revoke(token)
        if session:
            audit_repo.log(
                user_id=int(session["user_id"]),
                username="",
                action="logout",
                entity="session",
                entity_id=int(session["id"]),
                detail="退出登录",
            )


    def resolve_session(token: str | None) -> dict[str, Any] | None:
        """根据令牌取出登录用户；令牌过期/被吊销返回 None。"""
        if not token:
            return None
        session = session_repo.by_token(token)
        if session is None:
            return None
        if session.get("revoked_at"):
            return None
        expires = clock.parse_iso(session.get("expires_at"))
        if expires is None or expires < clock.utcnow():
            return None
        user = user_repo.find(int(session["user_id"]))
        if user is None or user.get("status") != "active":
            return None
        return user


    def change_password(user_id: int, old_password: str, new_password: str) -> None:
        user = user_repo.find_or_fail(user_id, "用户不存在")
        if not security.verify_password(old_password, user["password_hash"], user["password_salt"]):
            raise ValidationError("原密码不正确")
        if old_password == new_password:
            raise ValidationError("新密码不能与原密码相同")
        digest, salt = security.hash_password(new_password)
        user_repo.set_password(user_id, digest, salt, must_change=False)
        session_repo.revoke_all_for_user(user_id)
        audit_repo.log(
            user_id=user_id,
            username=user["username"],
            action="change_password",
            entity="user",
            entity_id=user_id,
            detail="修改密码",
        )


    def admin_reset_password(user_id: int, new_password: str | None = None) -> str:
        """管理员重置密码，返回新口令（明文，仅此一次可见）。"""
        user = user_repo.find_or_fail(user_id, "用户不存在")
        plain = new_password or security.random_password(10)
        digest, salt = security.hash_password(plain)
        user_repo.set_password(user_id, digest, salt, must_change=True)
        session_repo.revoke_all_for_user(user_id)
        audit_repo.log(
            user_id=user_id,
            username=user["username"],
            action="reset_password",
            entity="user",
            entity_id=user_id,
            detail="管理员重置密码",
        )
        return plain


    def issue_token_for_user(user_id: int, *, ip: str = "",
                              user_agent: str = "") -> str:
        """给已登录用户换发新令牌（例如切换角色后刷新会话）。"""
        user = user_repo.find_or_fail(user_id, "用户不存在")
        return _issue_token(user, ip=ip, user_agent=user_agent)


    def cleanup_sessions() -> int:
        """清理过期会话，服务启动时调用一次。"""
        return session_repo.purge_expired()


    def generate_initial_password() -> str:
        return security.random_password(10)
    return SimpleNamespace(
        logger=logger,
        user_repo=user_repo,
        session_repo=session_repo,
        attempt_repo=attempt_repo,
        audit_repo=audit_repo,
        PUBLIC_USER_FIELDS=PUBLIC_USER_FIELDS,
        to_public=to_public,
        login=login,
        logout=logout,
        resolve_session=resolve_session,
        change_password=change_password,
        admin_reset_password=admin_reset_password,
        issue_token_for_user=issue_token_for_user,
        cleanup_sessions=cleanup_sessions,
        generate_initial_password=generate_initial_password,
    )


# ======================================================================
# 模块：backend/services/notification_service.py
# ======================================================================
def _mod_notification_service(NotificationRepository, UserRepository, permissions):
    """通知服务。

    系统内所有"需要告诉某人"的动作都走这里：
    作业发布、成绩批改、签到开始、课程公告……
    统一落库，前端轮询未读数即可。
    """


    import logging
    from typing import Any, Iterable


    logger = logging.getLogger("eduflow.notify")

    notification_repo = NotificationRepository()
    user_repo = UserRepository()

    MAX_TITLE = 120
    MAX_CONTENT = 2000


    def notify(
        user_id: int,
        title: str,
        content: str = "",
        *,
        category: str = "system",
        link: str = "",
    ) -> int:
        """给单个用户发通知。"""
        return notification_repo.create(
            int(user_id),
            title=title[:MAX_TITLE],
            content=content[:MAX_CONTENT],
            category=category,
            link=link,
        )


    def notify_many(
        user_ids: Iterable[int],
        title: str,
        content: str = "",
        *,
        category: str = "system",
        link: str = "",
    ) -> int:
        ids = [int(uid) for uid in dict.fromkeys(user_ids) if uid]
        if not ids:
            return 0
        return notification_repo.create_many(
            ids,
            title=title[:MAX_TITLE],
            content=content[:MAX_CONTENT],
            category=category,
            link=link,
        )


    def notify_class(
        user_ids: Iterable[int],
        *,
        title: str,
        content: str = "",
        category: str = "course",
        link: str = "",
    ) -> int:
        """作业/签到这类课堂通知的语义化包装。"""
        return notify_many(user_ids, title, content, category=category, link=link)


    def list_notifications(
        viewer: dict[str, Any],
        *,
        only_unread: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        offset = (max(1, page) - 1) * page_size
        items = notification_repo.list_for_user(
            int(viewer["id"]), only_unread=only_unread, limit=page_size, offset=offset
        )
        total = notification_repo.count_for_user(int(viewer["id"]), only_unread=only_unread)
        return items, total


    def unread_count(viewer: dict[str, Any]) -> int:
        return notification_repo.unread_count(int(viewer["id"]))


    def mark_read(viewer: dict[str, Any], notification_id: int) -> int:
        return notification_repo.mark_read(notification_id, int(viewer["id"]))


    def mark_all_read(viewer: dict[str, Any]) -> int:
        return notification_repo.mark_all_read(int(viewer["id"]))


    def clear_read(viewer: dict[str, Any]) -> int:
        return notification_repo.clear_read(int(viewer["id"]))


    def broadcast(operator: dict[str, Any], payload: dict[str, Any]) -> int:
        """管理员广播通知。

        target: all / student / teacher / class:<class_id>
        """
        permissions.require_admin(operator)
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("标题不能为空")
        content = str(payload.get("content") or "")
        target = str(payload.get("target") or "all")

        if target in permissions.ALL_ROLES:
            users = user_repo.all(where="role = ? AND status = 'active'", params=(target,))
            return notify_many(
                [int(item["id"]) for item in users], title, content, category="system"
            )
        if target == "all":
            users = user_repo.all(where="status = 'active'", params=())
            return notify_many(
                [int(item["id"]) for item in users], title, content, category="system"
            )
        raise ValueError(f"不支持的广播目标：{target}")
    return SimpleNamespace(
        logger=logger,
        notification_repo=notification_repo,
        user_repo=user_repo,
        MAX_TITLE=MAX_TITLE,
        MAX_CONTENT=MAX_CONTENT,
        notify=notify,
        notify_many=notify_many,
        notify_class=notify_class,
        list_notifications=list_notifications,
        unread_count=unread_count,
        mark_read=mark_read,
        mark_all_read=mark_all_read,
        clear_read=clear_read,
        broadcast=broadcast,
    )


# ======================================================================
# 模块：backend/services/announcement_service.py
# ======================================================================
def _mod_announcement_service(AnnouncementRepository, AuditRepository, ClassRepository, CourseRepository, EnrollmentRepository, NotFoundError, notify_many, permissions, validators):
    """课程公告。

    教师发公告，学生进课程或首页能看到；发布时顺带推一条站内通知。
    """


    from typing import Any


    announcement_repo = AnnouncementRepository()
    course_repo = CourseRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    audit_repo = AuditRepository()


    def _course_or_fail(course_id: int) -> dict[str, Any]:
        course = course_repo.detail(course_id)
        if course is None:
            raise NotFoundError("课程不存在")
        return course


    def _assert_view(viewer: dict[str, Any], course: dict[str, Any]) -> None:
        class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
        enrolled = bool(class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"]))))
        permissions.assert_can_view_course(viewer, course, enrolled=enrolled)


    def list_for_course(viewer: dict[str, Any], course_id: int) -> list[dict[str, Any]]:
        course = _course_or_fail(course_id)
        _assert_view(viewer, course)
        return announcement_repo.list_by_course(course_id)


    def student_feed(student: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        permissions.require_role(student, permissions.ROLE_STUDENT)
        return announcement_repo.list_for_student(int(student["id"]), limit=limit)


    def create(viewer: dict[str, Any], course_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        course = _course_or_fail(course_id)
        permissions.assert_can_manage_course(viewer, course)

        title = validators.required_str(payload, "title", min_len=2, max_len=120)
        content = validators.optional_str(payload, "content", "", max_len=20000)
        pinned = 1 if validators.to_bool(payload.get("pinned"), False) else 0

        announcement_id = announcement_repo.insert(
            {
                "course_id": course_id,
                "title": title,
                "content": content,
                "author_id": int(viewer["id"]),
                "pinned": pinned,
            }
        )

        students: list[int] = []
        for class_row in class_repo.of_course(course_id):
            students.extend(int(row["id"]) for row in class_repo.students(int(class_row["id"])))
        if students:
            notify_many(
                students,
                title=f"课程公告：{title}",
                content=f"{course['name']} 发布了新公告",
                category="announcement",
                link=f"/courses/{course_id}",
            )

        audit_repo.log(
            user_id=int(viewer["id"]),
            username=viewer["username"],
            action="create_announcement",
            entity="announcement",
            entity_id=announcement_id,
            detail=f"{course['name']} / {title}",
        )
        return announcement_repo.detail(announcement_id) or {}


    def update(viewer: dict[str, Any], announcement_id: int,
               payload: dict[str, Any]) -> dict[str, Any]:
        item = announcement_repo.find_or_fail(announcement_id, "公告不存在")
        course = _course_or_fail(int(item["course_id"]))
        permissions.assert_can_manage_course(viewer, course)

        updates: dict[str, Any] = {}
        if "title" in payload:
            updates["title"] = validators.required_str(payload, "title", min_len=2, max_len=120)
        if "content" in payload:
            updates["content"] = validators.optional_str(payload, "content", "", max_len=20000)
        if "pinned" in payload:
            updates["pinned"] = 1 if validators.to_bool(payload.get("pinned")) else 0
        if updates:
            announcement_repo.update(announcement_id, updates)
        return announcement_repo.detail(announcement_id) or {}


    def delete(viewer: dict[str, Any], announcement_id: int) -> None:
        item = announcement_repo.find_or_fail(announcement_id, "公告不存在")
        course = _course_or_fail(int(item["course_id"]))
        permissions.assert_can_manage_course(viewer, course)
        announcement_repo.delete(announcement_id)
        audit_repo.log(
            user_id=int(viewer["id"]),
            username=viewer["username"],
            action="delete_announcement",
            entity="announcement",
            entity_id=announcement_id,
            detail=item.get("title", ""),
        )
    return SimpleNamespace(
        announcement_repo=announcement_repo,
        course_repo=course_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        audit_repo=audit_repo,
        list_for_course=list_for_course,
        student_feed=student_feed,
        create=create,
        update=update,
        delete=delete,
    )


# ======================================================================
# 模块：backend/services/attachment_service.py
# ======================================================================
def _mod_attachment_service(AuditRepository, ClassRepository, EnrollmentRepository, ForbiddenError, NotFoundError, TooLargeError, clock, config, connection, ids, permissions, safe_join, validators):
    """作业附件：学生上传、按权限下载。

    文件落在 data/uploads，文件名加随机前缀防冲突；数据库只存元信息。
    下载权限：上传者本人 / 该教学班任课教师 / 管理员。
    """


    import mimetypes
    import os
    from pathlib import Path
    from typing import Any


    audit_repo = AuditRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()

    MAX_FILES = 5


    def _sanitize(filename: str) -> str:
        name = os.path.basename((filename or "file").replace("\\", "/"))
        name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip(". ")
        return (name or "file")[:120]


    def list_for(assignment_id: int, student_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT id, filename, stored_name, size, mime, created_at
                 FROM assignment_files
                WHERE assignment_id = ? AND student_id = ?
                ORDER BY id""",
            (assignment_id, student_id),
        )


    def save_uploads(assignment_id: int, student_id: int,
                     files: list[tuple[str, bytes]]) -> list[dict[str, Any]]:
        if len(files) > MAX_FILES:
            raise TooLargeError(f"一次最多上传 {MAX_FILES} 个附件")

        existing = len(list_for(assignment_id, student_id))
        if existing + len(files) > MAX_FILES:
            raise TooLargeError(f"该作业附件总数不能超过 {MAX_FILES} 个")

        saved: list[dict[str, Any]] = []
        for raw_name, content in files:
            if len(content) > config.MAX_UPLOAD_BYTES:
                raise TooLargeError("单个附件不能超过 64 MB")
            if not content:
                raise validators.ValidationError("附件内容为空")

            name = _sanitize(raw_name)
            stored = f"hw_{ids.new_filename_token()}_{name}"
            target = safe_join(config.UPLOAD_DIR, stored)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

            mime, _ = mimetypes.guess_type(name)
            file_id = connection.execute(
                """INSERT INTO assignment_files
                       (assignment_id, student_id, filename, stored_name, size, mime, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (assignment_id, student_id, name, stored, len(content),
                 mime or "application/octet-stream", clock.now_iso()),
            )
            saved.append(
                {"id": file_id, "filename": name, "stored_name": stored,
                 "size": len(content), "mime": mime or "application/octet-stream"}
            )

        audit_repo.log(
            user_id=student_id,
            username="",
            action="upload_assignment_attachment",
            entity="assignment",
            entity_id=assignment_id,
            detail=f"上传 {len(saved)} 个附件",
        )
        return saved


    def resolve_download(viewer: dict[str, Any], file_id: int) -> tuple[Path, str]:
        row = connection.query_one(
            """SELECT f.*, a.class_id, c.teacher_id
                 FROM assignment_files f
                 JOIN assignments a ON a.id = f.assignment_id
                 JOIN classes cl ON cl.id = a.class_id
                 JOIN courses c ON c.id = cl.course_id
                WHERE f.id = ?""",
            (file_id,),
        )
        if row is None:
            raise NotFoundError("附件不存在")

        allowed = (
            int(row["student_id"]) == int(viewer["id"])
            or int(row["teacher_id"]) == int(viewer["id"])
            or viewer["role"] == permissions.ROLE_ADMIN
        )
        if not allowed:
            raise ForbiddenError("无权下载该附件")

        path = safe_join(config.UPLOAD_DIR, row["stored_name"])
        if not path.exists():
            raise NotFoundError("文件已丢失")
        return path, row["filename"]


    def delete_file(viewer: dict[str, Any], file_id: int) -> None:
        row = connection.query_one(
            "SELECT * FROM assignment_files WHERE id = ?", (file_id,)
        )
        if row is None:
            raise NotFoundError("附件不存在")
        if int(row["student_id"]) != int(viewer["id"]) and viewer["role"] != permissions.ROLE_ADMIN:
            raise ForbiddenError("只能删除自己的附件")

        path = safe_join(config.UPLOAD_DIR, row["stored_name"])
        if path.exists():
            path.unlink()
        connection.execute("DELETE FROM assignment_files WHERE id = ?", (file_id,))
    return SimpleNamespace(
        audit_repo=audit_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        MAX_FILES=MAX_FILES,
        list_for=list_for,
        save_uploads=save_uploads,
        resolve_download=resolve_download,
        delete_file=delete_file,
    )


# ======================================================================
# 模块：backend/services/user_service.py
# ======================================================================
def _mod_user_service(AuditRepository, ConflictError, NotFoundError, SessionRepository, UserRepository, ValidationError, auth_service, clock, config, permissions, security, validators):
    """用户管理服务：增删改查、批量导入、状态切换。"""


    import csv
    import io
    from typing import Any


    user_repo = UserRepository()
    session_repo = SessionRepository()
    audit_repo = AuditRepository()


    def list_users(
        *,
        role: str = "",
        keyword: str = "",
        page: int = 1,
        page_size: int = config.DEFAULT_PAGE_SIZE,
    ) -> tuple[list[dict[str, Any]], int]:
        page = max(1, page)
        page_size = validators.clamp_page(page, page_size)[1]
        offset = (page - 1) * page_size
        if role:
            validators.ensure_enum(role, permissions.ALL_ROLES, "角色")
            items = user_repo.list_by_role(role, keyword=keyword, limit=page_size, offset=offset)
            total = user_repo.count_by_role(role, keyword)
        else:
            items = user_repo.all(
                where="1 = 1" + _keyword_clause(keyword)[0],
                params=_keyword_clause(keyword)[1],
                order_by="id DESC",
                limit=page_size,
                offset=offset,
            )
            total = user_repo.count("1 = 1" + _keyword_clause(keyword)[0],
                                    _keyword_clause(keyword)[1])
        return [auth_service.to_public(item) for item in items], total


    def _keyword_clause(keyword: str) -> tuple[str, tuple[Any, ...]]:
        if not keyword:
            return "", ()
        like = f"%{keyword}%"
        return (
            " AND (username LIKE ? OR real_name LIKE ? OR number LIKE ?)",
            (like, like, like),
        )


    def get_user(user_id: int) -> dict[str, Any]:
        user = user_repo.find_or_fail(user_id, "用户不存在")
        return auth_service.to_public(user)


    def create_user(payload: dict[str, Any], *, operator: dict[str, Any] | None = None) -> dict[str, Any]:
        username = validators.validate_username(
            validators.required_str(payload, "username", min_len=3, max_len=32)
        )
        role = validators.ensure_enum(
            validators.required_str(payload, "role"), permissions.ALL_ROLES, "角色"
        )
        real_name = validators.required_str(payload, "real_name", max_len=32)
        number = validators.optional_str(payload, "number", max_len=32)
        email = validators.validate_email(validators.optional_str(payload, "email", max_len=128))
        phone = validators.validate_phone(validators.optional_str(payload, "phone", max_len=20))
        department = validators.optional_str(payload, "department", max_len=64)
        class_name = validators.optional_str(payload, "class_name", max_len=64)

        if user_repo.by_username(username):
            raise ConflictError(f"用户名 {username} 已存在")
        if number and user_repo.by_number(number):
            raise ConflictError(f"学号/工号 {number} 已存在")

        plain_password = validators.optional_str(payload, "password", "") or security.random_password(10)
        digest, salt = security.hash_password(plain_password)

        user_id = user_repo.insert(
            {
                "username": username,
                "password_hash": digest,
                "password_salt": salt,
                "role": role,
                "real_name": real_name,
                "number": number,
                "email": email,
                "phone": phone,
                "department": department,
                "class_name": class_name,
                "status": "active",
                "must_change_password": 1,
            }
        )
        audit_repo.log(
            user_id=int(operator["id"]) if operator else None,
            username=operator["username"] if operator else "system",
            action="create_user",
            entity="user",
            entity_id=user_id,
            detail=f"新建{permissions.ROLE_LABELS.get(role, role)} {real_name}({username})",
        )
        created = auth_service.to_public(user_repo.find(user_id))
        if created is not None:
            created["initial_password"] = plain_password
        return created or {}


    def update_user(user_id: int, payload: dict[str, Any], *,
                    operator: dict[str, Any] | None = None) -> dict[str, Any]:
        user = user_repo.find_or_fail(user_id, "用户不存在")
        updates: dict[str, Any] = {}

        if "real_name" in payload:
            updates["real_name"] = validators.required_str(payload, "real_name", max_len=32)
        if "email" in payload:
            updates["email"] = validators.validate_email(
                validators.optional_str(payload, "email", max_len=128)
            )
        if "phone" in payload:
            updates["phone"] = validators.validate_phone(
                validators.optional_str(payload, "phone", max_len=20)
            )
        if "department" in payload:
            updates["department"] = validators.optional_str(payload, "department", max_len=64)
        if "class_name" in payload:
            updates["class_name"] = validators.optional_str(payload, "class_name", max_len=64)
        if "number" in payload:
            number = validators.optional_str(payload, "number", max_len=32)
            if number and number != user.get("number"):
                other = user_repo.by_number(number)
                if other and int(other["id"]) != user_id:
                    raise ConflictError(f"学号/工号 {number} 已被占用")
            updates["number"] = number
        if "avatar" in payload:
            updates["avatar"] = validators.optional_str(payload, "avatar", max_len=500)

        if not updates:
            return auth_service.to_public(user) or {}

        user_repo.update(user_id, updates)
        audit_repo.log(
            user_id=int(operator["id"]) if operator else None,
            username=operator["username"] if operator else "",
            action="update_user",
            entity="user",
            entity_id=user_id,
            detail=f"更新资料：{', '.join(updates.keys())}",
        )
        return auth_service.to_public(user_repo.find(user_id)) or {}


    def set_status(user_id: int, status: str, *, operator: dict[str, Any]) -> dict[str, Any]:
        validators.ensure_enum(status, ("active", "disabled"), "状态")
        user = user_repo.find_or_fail(user_id, "用户不存在")
        if int(user["id"]) == int(operator["id"]) and status == "disabled":
            raise ValidationError("不能禁用自己")
        user_repo.set_status(user_id, status)
        if status == "disabled":
            session_repo.revoke_all_for_user(user_id)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="set_user_status",
            entity="user",
            entity_id=user_id,
            detail=f"状态改为 {status}",
        )
        return auth_service.to_public(user_repo.find(user_id)) or {}


    def reset_password(user_id: int, *, operator: dict[str, Any]) -> dict[str, Any]:
        user = user_repo.find_or_fail(user_id, "用户不存在")
        plain = auth_service.admin_reset_password(user_id)
        return {
            "user_id": user_id,
            "username": user["username"],
            "initial_password": plain,
            "must_change_password": True,
        }


    def import_users(csv_text: str, *, default_role: str = "student",
                     operator: dict[str, Any] | None = None) -> dict[str, Any]:
        """从 CSV 批量建号。

        期望表头：username,real_name,role,number,department,class_name,email,phone
        role 为空时用 default_role。返回创建成功与失败的明细。
        """
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        if reader.fieldnames is None:
            raise ValidationError("CSV 内容为空")
        success: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for index, row in enumerate(reader, start=2):
            try:
                payload = {key: (value or "").strip() for key, value in row.items() if key}
                payload.setdefault("role", default_role)
                if not payload.get("role"):
                    payload["role"] = default_role
                created = create_user(payload, operator=operator)
                success.append(
                    {
                        "line": index,
                        "username": created.get("username"),
                        "initial_password": created.get("initial_password"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failed.append({"line": index, "username": row.get("username", ""), "error": str(exc)})
        return {
            "created": len(success),
            "failed": len(failed),
            "details": success,
            "errors": failed,
        }


    def department_options() -> list[str]:
        return user_repo.departments()


    def overview() -> dict[str, Any]:
        """管理员首页概览数字。"""
        counts = user_repo.count_all()
        from backend.repositories.courses import CourseRepository

        course_repo = CourseRepository()
        counts["courses"] = int(course_repo.count() or 0)
        counts["sessions_today"] = 0
        counts["updated_at"] = clock.now_iso()
        return counts
    return SimpleNamespace(
        user_repo=user_repo,
        session_repo=session_repo,
        audit_repo=audit_repo,
        list_users=list_users,
        get_user=get_user,
        create_user=create_user,
        update_user=update_user,
        set_status=set_status,
        reset_password=reset_password,
        import_users=import_users,
        department_options=department_options,
        overview=overview,
    )


# ======================================================================
# 模块：backend/services/course_service.py
# ======================================================================
def _mod_course_service(AuditRepository, ClassRepository, ConflictError, CourseRepository, EnrollmentRepository, ForbiddenError, NotFoundError, UserRepository, ValidationError, clock, config, ids, permissions, validators):
    """课程与教学班服务。

    包含课程 CRUD、开课、教学班管理、选课/退课，以及所有权限校验。
    """


    import logging
    from typing import Any


    logger = logging.getLogger("eduflow.course")

    course_repo = CourseRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    user_repo = UserRepository()
    audit_repo = AuditRepository()


    # ---------------------------------------------------------------------------
    # 课程
    # ---------------------------------------------------------------------------


    def list_courses(
        viewer: dict[str, Any],
        *,
        term: str = "",
        keyword: str = "",
        page: int = 1,
        page_size: int = config.DEFAULT_PAGE_SIZE,
    ) -> tuple[list[dict[str, Any]], int]:
        page, page_size = validators.clamp_page(page, page_size)
        offset = (page - 1) * page_size
        if viewer["role"] == permissions.ROLE_ADMIN:
            items = course_repo.list_courses(
                term=term, keyword=keyword, limit=page_size, offset=offset
            )
            total = course_repo.count_courses(term=term, keyword=keyword)
        elif viewer["role"] == permissions.ROLE_TEACHER:
            items = course_repo.list_courses(
                teacher_id=int(viewer["id"]), term=term, keyword=keyword,
                limit=page_size, offset=offset,
            )
            total = course_repo.count_courses(
                teacher_id=int(viewer["id"]), term=term, keyword=keyword
            )
        else:
            items = course_repo.of_student(int(viewer["id"]))
            if keyword:
                lowered = keyword.lower()
                items = [
                    item for item in items
                    if lowered in (item.get("name") or "").lower()
                    or lowered in (item.get("code") or "").lower()
                ]
            total = len(items)
        return items, total


    def get_course(viewer: dict[str, Any], course_id: int) -> dict[str, Any]:
        course = course_repo.detail(course_id)
        if course is None:
            raise NotFoundError("课程不存在")
        enrolled = enroll_repo.class_ids_of_student(int(viewer["id"]))
        course_class_ids = {int(item["id"]) for item in class_repo.of_course(course_id)}
        permissions.assert_can_view_course(
            viewer, course, enrolled=bool(course_class_ids & set(enrolled))
        )
        course["classes"] = class_repo.of_course(course_id)
        return course


    def create_course(payload: dict[str, Any], operator: dict[str, Any]) -> dict[str, Any]:
        permissions.require_teacher(operator)
        code = validators.required_str(payload, "code", min_len=2, max_len=32).upper()
        name = validators.required_str(payload, "name", min_len=2, max_len=64)
        if course_repo.by_code(code):
            raise ConflictError(f"课程代码 {code} 已存在")

        if operator["role"] == permissions.ROLE_ADMIN:
            teacher_id = validators.optional_int(payload, "teacher_id", int(operator["id"]))
        else:
            teacher_id = int(operator["id"])
        teacher = user_repo.find_or_fail(int(teacher_id), "指定的教师不存在")
        if teacher["role"] not in (permissions.ROLE_TEACHER, permissions.ROLE_ADMIN):
            raise ValidationError("指定用户不是教师")

        term = validators.optional_str(payload, "term", clock.term_of(), max_len=16)
        credits = validators.optional_float(payload, "credits", 2.0, min_value=0.5, max_value=20)
        hours = validators.optional_int(payload, "hours", 32, min_value=1, max_value=200)
        category = validators.optional_str(payload, "category", "必修", max_len=16)
        description = validators.optional_str(payload, "description", "", max_len=2000)

        course_id = course_repo.insert(
            {
                "code": code,
                "name": name,
                "teacher_id": int(teacher_id),
                "term": term,
                "credits": credits,
                "hours": hours,
                "category": category,
                "description": description,
                "status": "active",
            }
        )
        # 建课同时开一个默认教学班，省去用户再点一次
        class_repo.insert(
            {
                "course_id": course_id,
                "name": f"{name}-01班",
                "join_code": _unique_join_code(),
                "semester": term,
                "capacity": 60,
            }
        )
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="create_course",
            entity="course",
            entity_id=course_id,
            detail=f"新建课程 {name}({code})",
        )
        return course_repo.detail(course_id) or {}


    def update_course(course_id: int, payload: dict[str, Any],
                      operator: dict[str, Any]) -> dict[str, Any]:
        course = course_repo.find_or_fail(course_id, "课程不存在")
        permissions.assert_can_manage_course(operator, course)

        updates: dict[str, Any] = {}
        for field, max_len in (
            ("name", 64), ("category", 16), ("cover", 500), ("description", 2000),
        ):
            if field in payload:
                updates[field] = validators.optional_str(payload, field, "", max_len=max_len)
        if "name" in updates and not updates["name"]:
            raise ValidationError("课程名称不能为空")
        if "term" in payload:
            updates["term"] = validators.required_str(payload, "term", max_len=16)
        if "credits" in payload:
            updates["credits"] = validators.optional_float(
                payload, "credits", 2.0, min_value=0.5, max_value=20
            )
        if "hours" in payload:
            updates["hours"] = validators.optional_int(payload, "hours", 32, min_value=1, max_value=200)
        if "status" in payload:
            updates["status"] = validators.ensure_enum(
                str(payload["status"]), ("active", "archived"), "课程状态"
            )
        if "teacher_id" in payload and operator["role"] == permissions.ROLE_ADMIN:
            updates["teacher_id"] = validators.required_int(payload, "teacher_id", min_value=1)

        if updates:
            course_repo.update(course_id, updates)
            audit_repo.log(
                user_id=int(operator["id"]),
                username=operator["username"],
                action="update_course",
                entity="course",
                entity_id=course_id,
                detail=f"更新课程字段：{', '.join(updates)}",
            )
        return course_repo.detail(course_id) or {}


    # ---------------------------------------------------------------------------
    # 教学班
    # ---------------------------------------------------------------------------


    def _unique_join_code() -> str:
        for _ in range(30):
            code = ids.new_join_code()
            if not class_repo.by_join_code(code):
                return code
        raise RuntimeError("生成邀请码失败，请重试")


    def list_classes(viewer: dict[str, Any]) -> list[dict[str, Any]]:
        if viewer["role"] == permissions.ROLE_ADMIN:
            rows = class_repo.all(order_by="id DESC")
            result = []
            for row in rows:
                detail = class_repo.detail(int(row["id"]))
                if detail:
                    result.append(detail)
            return result
        if viewer["role"] == permissions.ROLE_TEACHER:
            return class_repo.of_teacher(int(viewer["id"]))
        return [item for item in course_repo.of_student(int(viewer["id"]))]


    def create_class(course_id: int, payload: dict[str, Any],
                     operator: dict[str, Any]) -> dict[str, Any]:
        course = course_repo.find_or_fail(course_id, "课程不存在")
        permissions.assert_can_manage_course(operator, course)
        name = validators.required_str(payload, "name", min_len=1, max_len=64)
        capacity = validators.optional_int(payload, "capacity", 60, min_value=1, max_value=500)
        schedule = validators.optional_str(payload, "schedule", "", max_len=64)
        location = validators.optional_str(payload, "location", "", max_len=64)

        class_id = class_repo.insert(
            {
                "course_id": course_id,
                "name": name,
                "join_code": _unique_join_code(),
                "semester": course.get("term") or clock.term_of(),
                "capacity": capacity,
                "schedule": schedule,
                "location": location,
            }
        )
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="create_class",
            entity="class",
            entity_id=class_id,
            detail=f"新建教学班 {name}",
        )
        return class_repo.detail(class_id) or {}


    def get_class(viewer: dict[str, Any], class_id: int) -> dict[str, Any]:
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        _assert_class_access(viewer, detail)
        detail["students"] = class_repo.students(class_id)
        detail["student_count"] = len(detail["students"])
        return detail


    def _assert_class_access(viewer: dict[str, Any], class_detail: dict[str, Any]) -> None:
        if viewer["role"] == permissions.ROLE_ADMIN:
            return
        if int(class_detail.get("teacher_id") or 0) == int(viewer["id"]):
            return
        if viewer["role"] == permissions.ROLE_STUDENT:
            if enroll_repo.is_enrolled(int(class_detail["id"]), int(viewer["id"])):
                return
        raise ForbiddenError("无权访问该教学班")


    def join_class(student: dict[str, Any], code: str) -> dict[str, Any]:
        """学生凭邀请码加入教学班。"""
        permissions.require_role(student, permissions.ROLE_STUDENT)
        code = validators.validate_code(code, "邀请码")
        target = class_repo.by_join_code(code)
        if target is None:
            raise NotFoundError("邀请码无效")
        if target["status"] != "active":
            raise ValidationError("该教学班已关闭选课")
        if enroll_repo.is_enrolled(int(target["id"]), int(student["id"])):
            raise ConflictError("你已经加入该教学班")
        current = class_repo.student_count(int(target["id"]))
        if current >= int(target.get("capacity") or 60):
            raise ValidationError("教学班人数已满")
        enroll_repo.enroll(int(target["id"]), int(student["id"]), source="self")
        audit_repo.log(
            user_id=int(student["id"]),
            username=student["username"],
            action="join_class",
            entity="class",
            entity_id=int(target["id"]),
            detail=f"凭邀请码 {code} 加入教学班",
        )
        return class_repo.detail(int(target["id"])) or {}


    def add_student(class_id: int, student_id: int, operator: dict[str, Any]) -> dict[str, Any]:
        """教师/管理员手动把学生加入教学班。"""
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        permissions.assert_can_manage_course(operator, detail)
        student = user_repo.find_or_fail(student_id, "学生不存在")
        if student["role"] != permissions.ROLE_STUDENT:
            raise ValidationError("只能添加学生账号")
        enroll_repo.enroll(class_id, student_id, source="admin")
        return {"class_id": class_id, "student_id": student_id, "action": "added"}


    def drop_student(class_id: int, student_id: int, operator: dict[str, Any]) -> dict[str, Any]:
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        permissions.assert_can_manage_course(operator, detail)
        enroll_repo.drop(class_id, student_id)
        return {"class_id": class_id, "student_id": student_id, "action": "dropped"}


    def leave_class(student: dict[str, Any], class_id: int) -> dict[str, Any]:
        if not enroll_repo.is_enrolled(class_id, int(student["id"])):
            raise ValidationError("你还没有加入该教学班")
        enroll_repo.drop(class_id, int(student["id"]))
        audit_repo.log(
            user_id=int(student["id"]),
            username=student["username"],
            action="leave_class",
            entity="class",
            entity_id=class_id,
            detail="退出教学班",
        )
        return {"class_id": class_id, "action": "left"}


    def class_students(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        _assert_class_access(viewer, detail)
        return class_repo.students(class_id)


    def teacher_overview(teacher: dict[str, Any]) -> dict[str, Any]:
        """教师工作台的汇总数字。"""
        from backend.repositories.assignments import AssignmentRepository

        classes = class_repo.of_teacher(int(teacher["id"]))
        class_ids = [int(item["id"]) for item in classes]
        total_students = sum(int(item.get("student_count") or 0) for item in classes)
        pending = 0
        assignment_repo = AssignmentRepository()
        for class_id in class_ids:
            assignments = assignment_repo.list_by_class(class_id, limit=200)
            for item in assignments:
                if item.get("status") == "published":
                    pending += max(
                        0, int(item.get("student_total") or 0) - int(item.get("submission_count") or 0)
                    )
        return {
            "class_count": len(classes),
            "student_count": total_students,
            "pending_submissions": pending,
            "courses": classes,
        }
    return SimpleNamespace(
        logger=logger,
        course_repo=course_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        user_repo=user_repo,
        audit_repo=audit_repo,
        list_courses=list_courses,
        get_course=get_course,
        create_course=create_course,
        update_course=update_course,
        list_classes=list_classes,
        create_class=create_class,
        get_class=get_class,
        join_class=join_class,
        add_student=add_student,
        drop_student=drop_student,
        leave_class=leave_class,
        class_students=class_students,
        teacher_overview=teacher_overview,
    )


# ======================================================================
# 模块：backend/services/assignment_service.py
# ======================================================================
def _mod_assignment_service(AssignmentRepository, AuditRepository, ClassRepository, ConflictError, EnrollmentRepository, ForbiddenError, NotFoundError, SubmissionRepository, UserRepository, clock, config, notify_class, permissions, validators):
    """作业服务：发布、提交、批改、统计。

    关键业务规则：
    - 截止后是否允许提交，由作业的 allow_late 决定；
    - 迟交按天扣分，扣分比例写在作业上，便于一门课一个口径；
    - 每次提交都会写审计日志，方便教师追溯。
    """


    import json
    import logging
    from typing import Any


    logger = logging.getLogger("eduflow.assignment")

    assignment_repo = AssignmentRepository()
    submission_repo = SubmissionRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    user_repo = UserRepository()
    audit_repo = AuditRepository()


    def _class_or_fail(class_id: int) -> dict[str, Any]:
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        return detail


    def create_assignment(payload: dict[str, Any],
                          operator: dict[str, Any]) -> dict[str, Any]:
        permissions.require_teacher(operator)
        class_id = validators.required_int(payload, "class_id", min_value=1)
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)

        title = validators.required_str(payload, "title", min_len=1, max_len=120)
        content = validators.optional_str(payload, "content", "", max_len=20000)
        full_score = validators.optional_float(payload, "full_score", 100, min_value=1, max_value=1000)
        deadline = validators.validate_date(
            payload.get("deadline"), "截止时间", required_field=False
        )
        allow_late = validators.to_bool(payload.get("allow_late"), True)
        late_penalty = validators.optional_float(
            payload, "late_penalty", config.LATE_PENALTY_PER_DAY, min_value=0, max_value=1
        )
        attachments = payload.get("attachments") or []
        if not isinstance(attachments, list):
            raise validators.ValidationError("附件必须是数组")

        assignment_id = assignment_repo.insert(
            {
                "class_id": class_id,
                "title": title,
                "content": content,
                "attachments": json.dumps(attachments, ensure_ascii=False) if attachments else None,
                "full_score": full_score,
                "deadline": deadline or None,
                "allow_late": 1 if allow_late else 0,
                "late_penalty": late_penalty,
                "status": "published",
                "created_by": int(operator["id"]),
            }
        )
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="create_assignment",
            entity="assignment",
            entity_id=assignment_id,
            detail=f"{detail['course_name']} / {title}",
        )
        students = [int(row["id"]) for row in class_repo.students(class_id)]
        if students:
            notify_class(
                students,
                title=f"新作业：{title}",
                content=f"{detail['course_name']} 发布了新作业，截止时间 {deadline or '未设置'}",
                category="assignment",
                link=f"/assignments/{assignment_id}",
            )
        return assignment_repo.detail(assignment_id) or {}


    def update_assignment(assignment_id: int, payload: dict[str, Any],
                          operator: dict[str, Any]) -> dict[str, Any]:
        assignment = assignment_repo.find_or_fail(assignment_id, "作业不存在")
        detail = _class_or_fail(int(assignment["class_id"]))
        permissions.assert_can_manage_course(operator, detail)

        updates: dict[str, Any] = {}
        if "title" in payload:
            updates["title"] = validators.required_str(payload, "title", max_len=120)
        if "content" in payload:
            updates["content"] = validators.optional_str(payload, "content", "", max_len=20000)
        if "deadline" in payload:
            updates["deadline"] = validators.validate_date(
                payload.get("deadline"), "截止时间", required_field=False
            ) or None
        if "full_score" in payload:
            updates["full_score"] = validators.optional_float(
                payload, "full_score", 100, min_value=1, max_value=1000
            )
        if "allow_late" in payload:
            updates["allow_late"] = 1 if validators.to_bool(payload.get("allow_late")) else 0
        if "status" in payload:
            updates["status"] = validators.ensure_enum(
                str(payload["status"]), ("draft", "published", "closed"), "作业状态"
            )
        if updates:
            assignment_repo.update(assignment_id, updates)
        return assignment_repo.detail(assignment_id) or {}


    def list_assignments(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
        detail = _class_or_fail(class_id)
        if viewer["role"] == permissions.ROLE_STUDENT and not enroll_repo.is_enrolled(
            class_id, int(viewer["id"])
        ):
            raise ForbiddenError("未选修该课程")
        if viewer["role"] != permissions.ROLE_STUDENT:
            permissions.assert_can_manage_course(viewer, detail)
        items = assignment_repo.list_by_class(class_id, limit=200)
        if viewer["role"] == permissions.ROLE_STUDENT:
            for item in items:
                submission = submission_repo.by_student(int(item["id"]), int(viewer["id"]))
                item["my_submission"] = submission
        return items


    def student_assignments(viewer: dict[str, Any], status: str = "") -> list[dict[str, Any]]:
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        return assignment_repo.list_for_student(
            int(viewer["id"]), status=status, limit=200
        )


    def get_assignment(viewer: dict[str, Any], assignment_id: int) -> dict[str, Any]:
        item = assignment_repo.detail(assignment_id)
        if item is None:
            raise NotFoundError("作业不存在")
        class_id = int(item["class_id"])
        detail = _class_or_fail(class_id)
        if viewer["role"] == permissions.ROLE_STUDENT:
            if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
                raise ForbiddenError("未选修该课程")
            item["my_submission"] = submission_repo.by_student(assignment_id, int(viewer["id"]))
        else:
            permissions.assert_can_manage_course(viewer, detail)
            item["stats"] = submission_repo.stats_for_assignment(assignment_id)
        item["deadline_state"] = clock.deadline_state(item.get("deadline"))
        return item


    def submit(viewer: dict[str, Any], assignment_id: int,
               payload: dict[str, Any]) -> dict[str, Any]:
        """学生提交作业。"""
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        assignment = assignment_repo.find_or_fail(assignment_id, "作业不存在")
        class_id = int(assignment["class_id"])
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")
        if assignment["status"] != "published":
            raise ConflictError("该作业当前不可提交")

        existing = submission_repo.by_student(assignment_id, int(viewer["id"]))
        if existing and existing.get("status") == "graded":
            raise ConflictError("作业已批改，不能重复提交")

        content = validators.optional_str(payload, "content", "", max_len=50000)
        attachments = payload.get("attachments") or []
        if not isinstance(attachments, list):
            raise validators.ValidationError("附件必须是数组")
        if not content.strip() and not attachments:
            raise validators.ValidationError("作业内容和附件不能同时为空")

        now = clock.utcnow()
        deadline = clock.parse_iso(assignment.get("deadline"))
        is_late = bool(deadline and now > deadline)
        if is_late and not assignment.get("allow_late"):
            raise ConflictError("已过截止时间，且该作业不允许迟交")

        submission_id = submission_repo.upsert_submission(
            assignment_id,
            int(viewer["id"]),
            {
                "content": content,
                "attachments": json.dumps(attachments, ensure_ascii=False) if attachments else None,
                "status": "late" if is_late else "submitted",
                "submitted_at": clock.to_iso(now),
                "is_late": 1 if is_late else 0,
            },
        )
        audit_repo.log(
            user_id=int(viewer["id"]),
            username=viewer["username"],
            action="submit_assignment",
            entity="submission",
            entity_id=submission_id,
            detail=f"作业 {assignment['title']}" + ("（迟交）" if is_late else ""),
        )
        result = submission_repo.by_student(assignment_id, int(viewer["id"])) or {}
        result["is_late"] = is_late
        result["deduction_hint"] = (
            f"迟交，每迟一天扣 {int(float(assignment.get('late_penalty') or 0) * 100)}%"
            if is_late else ""
        )
        return result


    def grade_submission(operator: dict[str, Any], submission_id: int,
                         payload: dict[str, Any]) -> dict[str, Any]:
        permissions.require_teacher(operator)
        submission = submission_repo.find_or_fail(submission_id, "提交记录不存在")
        assignment = assignment_repo.find_or_fail(int(submission["assignment_id"]), "作业不存在")
        detail = _class_or_fail(int(assignment["class_id"]))
        permissions.assert_can_manage_course(operator, detail)

        full_score = float(assignment.get("full_score") or 100)
        score = validators.validate_score(payload.get("score"), full_score)
        feedback = validators.optional_str(payload, "feedback", "", max_len=2000)

        submission_repo.grade(submission_id, score, feedback, int(operator["id"]))
        notify_class(
            [int(submission["student_id"])],
            title=f"作业已批改：{assignment['title']}",
            content=f"得分 {score} / {full_score}",
            category="grade",
            link=f"/assignments/{assignment['id']}",
        )
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="grade_submission",
            entity="submission",
            entity_id=submission_id,
            detail=f"打分 {score}",
        )
        return submission_repo.by_student(
            int(submission["assignment_id"]), int(submission["student_id"])
        ) or {}


    def batch_grade(operator: dict[str, Any], assignment_id: int,
                    rows: list[dict[str, Any]]) -> dict[str, Any]:
        """批量打分：rows = [{submission_id, score, feedback}]。"""
        permissions.require_teacher(operator)
        assignment = assignment_repo.find_or_fail(assignment_id, "作业不存在")
        detail = _class_or_fail(int(assignment["class_id"]))
        permissions.assert_can_manage_course(operator, detail)
        full_score = float(assignment.get("full_score") or 100)

        updated = 0
        failed: list[dict[str, Any]] = []
        for row in rows:
            try:
                submission_id = validators.to_int(row.get("submission_id"), "submission_id")
                score = validators.validate_score(row.get("score"), full_score)
                submission_repo.grade(
                    submission_id, score, str(row.get("feedback") or ""), int(operator["id"])
                )
                updated += 1
            except Exception as exc:  # noqa: BLE001
                failed.append({"submission_id": row.get("submission_id"), "error": str(exc)})
        return {"updated": updated, "failed": failed}


    def list_submissions(operator: dict[str, Any], assignment_id: int) -> dict[str, Any]:
        permissions.require_teacher(operator)
        assignment = assignment_repo.find_or_fail(assignment_id, "作业不存在")
        detail = _class_or_fail(int(assignment["class_id"]))
        permissions.assert_can_manage_course(operator, detail)
        submissions = submission_repo.list_by_assignment(assignment_id)
        students = class_repo.students(int(assignment["class_id"]))
        submitted_ids = {int(item["student_id"]) for item in submissions}
        missing = [student for student in students if int(student["id"]) not in submitted_ids]
        return {
            "assignment": assignment_repo.detail(assignment_id),
            "submissions": submissions,
            "not_submitted": missing,
            "stats": submission_repo.stats_for_assignment(assignment_id),
        }


    def delete_assignment(operator: dict[str, Any], assignment_id: int) -> None:
        assignment = assignment_repo.find_or_fail(assignment_id, "作业不存在")
        detail = _class_or_fail(int(assignment["class_id"]))
        permissions.assert_can_manage_course(operator, detail)
        assignment_repo.delete(assignment_id)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="delete_assignment",
            entity="assignment",
            entity_id=assignment_id,
            detail=assignment["title"],
        )
    return SimpleNamespace(
        logger=logger,
        assignment_repo=assignment_repo,
        submission_repo=submission_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        user_repo=user_repo,
        audit_repo=audit_repo,
        create_assignment=create_assignment,
        update_assignment=update_assignment,
        list_assignments=list_assignments,
        student_assignments=student_assignments,
        get_assignment=get_assignment,
        submit=submit,
        grade_submission=grade_submission,
        batch_grade=batch_grade,
        list_submissions=list_submissions,
        delete_assignment=delete_assignment,
    )


# ======================================================================
# 模块：backend/services/quiz_service.py
# ======================================================================
def _mod_quiz_service(AttemptRepository, AuditRepository, ClassRepository, ConflictError, EnrollmentRepository, ForbiddenError, NotFoundError, NotificationRepository, QuestionRepository, QuizRepository, clock, config, notify_class, permissions, validators):
    """在线测验服务。

    覆盖出题、组卷、发卷、答题、自动判分、人工复评的全流程。
    自动判分规则：
    - 单选/判断：选项完全一致得分；
    - 多选：完全一致才得分（不给部分分，避免争议）；
    - 填空：忽略首尾空白与大小写，支持用 | 分隔多个可接受答案；
    - 简答：不自动判分，等教师人工给分。
    """


    import json
    import logging
    import random
    from typing import Any


    logger = logging.getLogger("eduflow.quiz")

    quiz_repo = QuizRepository()
    question_repo = QuestionRepository()
    attempt_repo = AttemptRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    audit_repo = AuditRepository()

    QUESTION_TYPES = ("single", "multi", "judge", "fill", "essay")
    TYPE_LABELS = {
        "single": "单选题",
        "multi": "多选题",
        "judge": "判断题",
        "fill": "填空题",
        "essay": "简答题",
    }


    def _class_or_fail(class_id: int) -> dict[str, Any]:
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        return detail


    def _normalize_questions(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise validators.ValidationError("至少需要一道题目")
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise validators.ValidationError(f"第 {index + 1} 题格式不正确")
            qtype = validators.ensure_enum(
                str(item.get("type") or ""), QUESTION_TYPES, f"第 {index + 1} 题类型"
            )
            stem = validators.required_str(item, "stem", min_len=1, max_len=2000)
            score = validators.optional_float(item, "score", 5, min_value=0.5, max_value=100)
            options = item.get("options") or []
            if qtype in ("single", "multi"):
                if not isinstance(options, list) or len(options) < 2:
                    raise validators.ValidationError(f"第 {index + 1} 题至少需要两个选项")
                options = [str(opt) for opt in options]
            else:
                options = []
            answer = str(item.get("answer") or "").strip()
            if qtype != "essay" and not answer:
                raise validators.ValidationError(f"第 {index + 1} 题缺少答案")
            normalized.append(
                {
                    "type": qtype,
                    "stem": stem,
                    "options": json.dumps(options, ensure_ascii=False) if options else None,
                    "answer": answer,
                    "analysis": validators.optional_str(item, "analysis", "", max_len=2000),
                    "score": score,
                    "order_no": index,
                }
            )
        return normalized


    def create_quiz(payload: dict[str, Any], operator: dict[str, Any]) -> dict[str, Any]:
        permissions.require_teacher(operator)
        class_id = validators.required_int(payload, "class_id", min_value=1)
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)

        title = validators.required_str(payload, "title", min_len=1, max_len=120)
        questions = _normalize_questions(payload.get("questions"))
        total = round(sum(float(item["score"]) for item in questions), 2)
        duration = validators.optional_int(payload, "duration", config.QUIZ_DEFAULT_DURATION,
                                           min_value=1, max_value=300)

        quiz_id = quiz_repo.insert(
            {
                "class_id": class_id,
                "title": title,
                "description": validators.optional_str(payload, "description", "", max_len=2000),
                "start_at": validators.validate_date(payload.get("start_at"), "开始时间", required_field=False) or None,
                "end_at": validators.validate_date(payload.get("end_at"), "结束时间", required_field=False) or None,
                "duration": duration,
                "total_score": total,
                "shuffle": 1 if validators.to_bool(payload.get("shuffle"), True) else 0,
                "show_answer": 1 if validators.to_bool(payload.get("show_answer"), True) else 0,
                "status": "published",
                "created_by": int(operator["id"]),
            }
        )
        question_repo.replace_for_quiz(quiz_id, questions)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="create_quiz",
            entity="quiz",
            entity_id=quiz_id,
            detail=f"{detail['course_name']} / {title} / {len(questions)} 题 / {total} 分",
        )
        students = [int(row["id"]) for row in class_repo.students(class_id)]
        if students:
            notify_class(
                students,
                title=f"新测验：{title}",
                content=f"{detail['course_name']} 发布了测验，共 {len(questions)} 题，满分 {total}",
                category="quiz",
                link=f"/quizzes/{quiz_id}",
            )
        return get_quiz(operator, quiz_id)


    def get_quiz(viewer: dict[str, Any], quiz_id: int) -> dict[str, Any]:
        quiz = quiz_repo.detail(quiz_id)
        if quiz is None:
            raise NotFoundError("测验不存在")
        class_id = int(quiz["class_id"])
        detail = _class_or_fail(class_id)
        questions = question_repo.list_by_quiz(quiz_id)
        for question in questions:
            question["options"] = json.loads(question["options"]) if question.get("options") else []
            question["type_label"] = TYPE_LABELS.get(question["type"], question["type"])

        if viewer["role"] == permissions.ROLE_STUDENT:
            if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
                raise ForbiddenError("未选修该课程")
            attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
            quiz["my_attempt"] = attempt
            quiz["questions"] = _sanitize_questions(questions, show_answer=False)
        else:
            permissions.assert_can_manage_course(viewer, detail)
            quiz["questions"] = questions
            quiz["stats"] = attempt_repo.stats(quiz_id)
        return quiz


    def _sanitize_questions(questions: list[dict[str, Any]], *,
                            show_answer: bool) -> list[dict[str, Any]]:
        """给学生的题目必须去掉正确答案与解析。"""
        result = []
        for question in questions:
            item = {
                "id": question["id"],
                "type": question["type"],
                "type_label": question.get("type_label"),
                "stem": question["stem"],
                "options": question.get("options") or [],
                "score": question["score"],
                "order_no": question["order_no"],
            }
            if show_answer:
                item["answer"] = question.get("answer")
                item["analysis"] = question.get("analysis")
            result.append(item)
        return result


    def list_for_class(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
        detail = _class_or_fail(class_id)
        if viewer["role"] == permissions.ROLE_STUDENT:
            if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
                raise ForbiddenError("未选修该课程")
        else:
            permissions.assert_can_manage_course(viewer, detail)
        return quiz_repo.list_by_class(class_id)


    def student_quizzes(viewer: dict[str, Any]) -> list[dict[str, Any]]:
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        return quiz_repo.list_for_student(int(viewer["id"]))


    def start_attempt(viewer: dict[str, Any], quiz_id: int) -> dict[str, Any]:
        """开始答题；返回题目（可能乱序）与截止时间。"""
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        quiz = quiz_repo.detail(quiz_id)
        if quiz is None:
            raise NotFoundError("测验不存在")
        class_id = int(quiz["class_id"])
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")
        if quiz.get("status") != "published":
            raise ConflictError("该测验未开放")

        now = clock.utcnow()
        start_at = clock.parse_iso(quiz.get("start_at"))
        end_at = clock.parse_iso(quiz.get("end_at"))
        if start_at and now < start_at:
            raise ConflictError("测验尚未开始")
        if end_at and now > end_at:
            raise ConflictError("测验已结束")

        attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
        if attempt and attempt.get("status") in ("submitted", "graded"):
            raise ConflictError("你已经提交过该测验")

        if not attempt:
            attempt_id = attempt_repo.start(quiz_id, int(viewer["id"]))
            attempt = attempt_repo.find(attempt_id)

        questions = question_repo.list_by_quiz(quiz_id)
        for question in questions:
            question["options"] = json.loads(question["options"]) if question.get("options") else []
            question["type_label"] = TYPE_LABELS.get(question["type"], question["type"])
        if quiz.get("shuffle"):
            rng = random.Random(f"{quiz_id}-{viewer['id']}")
            rng.shuffle(questions)

        started = clock.parse_iso(attempt.get("started_at")) or now
        deadline = clock.add_minutes(started, int(quiz.get("duration") or 45))
        if end_at and deadline > end_at:
            deadline = end_at

        saved = json.loads(attempt["answers"]) if attempt.get("answers") else {}
        return {
            "attempt_id": int(attempt["id"]),
            "quiz": {
                "id": quiz_id,
                "title": quiz["title"],
                "duration": quiz["duration"],
                "total_score": quiz["total_score"],
            },
            "questions": _sanitize_questions(questions, show_answer=False),
            "saved_answers": saved,
            "deadline": clock.to_iso(deadline),
            "remaining_seconds": max(0, int((deadline - now).total_seconds())),
        }


    def save_answers(viewer: dict[str, Any], quiz_id: int,
                     answers: dict[str, Any]) -> dict[str, Any]:
        """自动保存（前端每 10 秒上报一次）。"""
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
        if not attempt:
            raise NotFoundError("尚未开始答题")
        if attempt.get("status") != "in_progress":
            raise ConflictError("答题已结束")
        payload = json.dumps(answers or {}, ensure_ascii=False)
        attempt_repo.save_answers(int(attempt["id"]), payload)
        return {"saved": len(answers or {}), "at": clock.now_iso()}


    def submit_attempt(viewer: dict[str, Any], quiz_id: int,
                       answers: dict[str, Any]) -> dict[str, Any]:
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        quiz = quiz_repo.detail(quiz_id)
        if quiz is None:
            raise NotFoundError("测验不存在")
        attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
        if not attempt:
            raise NotFoundError("尚未开始答题")
        if attempt.get("status") in ("submitted", "graded"):
            raise ConflictError("重复提交")

        questions = question_repo.list_by_quiz(quiz_id)
        score, detail_rows = _auto_grade(questions, answers or {})
        total = float(quiz.get("total_score") or 0)

        payload = json.dumps(answers or {}, ensure_ascii=False)
        attempt_repo.submit(int(attempt["id"]), round(score, 2), payload)
        audit_repo.log(
            user_id=int(viewer["id"]),
            username=viewer["username"],
            action="submit_quiz",
            entity="quiz",
            entity_id=quiz_id,
            detail=f"得分 {round(score, 2)} / {total}",
        )
        return {
            "score": round(score, 2),
            "total_score": total,
            "rate": round(score / total * 100, 1) if total else 0,
            "details": detail_rows,
        }


    def _auto_grade(questions: list[dict[str, Any]],
                    answers: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
        score = 0.0
        rows: list[dict[str, Any]] = []
        for question in questions:
            qid = str(question["id"])
            given = str(answers.get(qid, "") or "").strip()
            expected = str(question.get("answer") or "").strip()
            qtype = question["type"]
            full = float(question.get("score") or 0)
            earned = 0.0
            if qtype == "single":
                earned = full if given and given.lower() == expected.lower() else 0.0
            elif qtype == "multi":
                given_set = {part.strip().lower() for part in given.split(",") if part.strip()}
                expected_set = {part.strip().lower() for part in expected.split(",") if part.strip()}
                earned = full if given_set and given_set == expected_set else 0.0
            elif qtype == "judge":
                earned = full if _judge_equal(given, expected) else 0.0
            elif qtype == "fill":
                accepted = [part.strip().lower() for part in expected.split("|") if part.strip()]
                earned = full if given.lower() in accepted and accepted else 0.0
            else:  # essay 留给人工
                earned = 0.0
            score += earned
            rows.append(
                {
                    "question_id": question["id"],
                    "type": qtype,
                    "given": given,
                    "expected": expected if qtype != "essay" else "",
                    "earned": round(earned, 2),
                    "full": full,
                }
            )
        return score, rows


    def _judge_equal(given: str, expected: str) -> bool:
        truthy = {"对", "正确", "true", "t", "1", "是", "yes"}
        falsy = {"错", "错误", "false", "f", "0", "否", "no"}
        g = given.strip().lower()
        e = expected.strip().lower()
        if g in truthy and e in truthy:
            return True
        if g in falsy and e in falsy:
            return True
        return g == e


    def manual_grade(operator: dict[str, Any], quiz_id: int,
                     student_id: int, score: float) -> dict[str, Any]:
        """教师给简答题手工复核（直接覆盖总分）。"""
        permissions.require_teacher(operator)
        quiz = quiz_repo.find_or_fail(quiz_id, "测验不存在")
        detail = _class_or_fail(int(quiz["class_id"]))
        permissions.assert_can_manage_course(operator, detail)
        total = float(quiz.get("total_score") or 100)
        final = validators.to_float(score, "分数", min_value=0, max_value=total)
        attempt = attempt_repo.by_student(quiz_id, student_id)
        if attempt is None:
            raise NotFoundError("该学生没有作答记录")
        attempt_repo.submit(int(attempt["id"]), final, attempt.get("answers") or "{}")
        return {"quiz_id": quiz_id, "student_id": student_id, "score": final}


    def standings(operator: dict[str, Any], quiz_id: int) -> dict[str, Any]:
        permissions.require_teacher(operator)
        quiz = quiz_repo.find_or_fail(quiz_id, "测验不存在")
        detail = _class_or_fail(int(quiz["class_id"]))
        permissions.assert_can_manage_course(operator, detail)
        return {
            "quiz": quiz,
            "rows": attempt_repo.list_by_quiz(quiz_id),
            "stats": attempt_repo.stats(quiz_id),
        }
    return SimpleNamespace(
        logger=logger,
        quiz_repo=quiz_repo,
        question_repo=question_repo,
        attempt_repo=attempt_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        audit_repo=audit_repo,
        QUESTION_TYPES=QUESTION_TYPES,
        TYPE_LABELS=TYPE_LABELS,
        create_quiz=create_quiz,
        get_quiz=get_quiz,
        list_for_class=list_for_class,
        student_quizzes=student_quizzes,
        start_attempt=start_attempt,
        save_answers=save_answers,
        submit_attempt=submit_attempt,
        manual_grade=manual_grade,
        standings=standings,
    )


# ======================================================================
# 模块：backend/services/attendance_service.py
# ======================================================================
def _mod_attendance_service(AttendanceRecordRepository, AttendanceSessionRepository, AuditRepository, ClassRepository, ConflictError, EnrollmentRepository, ForbiddenError, NotFoundError, clock, config, ids, notify_class, permissions, validators):
    """签到服务。

    支持三种签到方式：
    - code：教师发一个 6 位数字码，学生输入；
    - qr：本质同上，只是前端把它渲染成二维码；
    - location：除验证码外还校验经纬度是否在半径内。

    迟到判定：签到开始 ATTENDANCE_LATE_MINUTES 分钟内算正常，之后算迟到。
    """


    import math
    from typing import Any


    session_repo = AttendanceSessionRepository()
    record_repo = AttendanceRecordRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    audit_repo = AuditRepository()

    METHODS = ("code", "qr", "location")


    def _class_or_fail(class_id: int) -> dict[str, Any]:
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        return detail


    def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """两点的球面距离（米）。"""
        radius = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(d_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        )
        return 2 * radius * math.asin(math.sqrt(a))


    def create_session(payload: dict[str, Any], operator: dict[str, Any]) -> dict[str, Any]:
        permissions.require_teacher(operator)
        class_id = validators.required_int(payload, "class_id", min_value=1)
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)

        title = validators.optional_str(payload, "title", "课堂签到", max_len=64)
        method = validators.ensure_enum(
            validators.optional_str(payload, "method", "code", max_len=16), METHODS, "签到方式"
        )
        duration = validators.optional_int(payload, "duration", 5, min_value=1, max_value=120)

        latitude = longitude = None
        radius = 200
        if method == "location":
            latitude = validators.optional_float(payload, "latitude", None)
            longitude = validators.optional_float(payload, "longitude", None)
            radius = validators.optional_int(payload, "radius", 200, min_value=20, max_value=5000)
            if latitude is None or longitude is None:
                raise validators.ValidationError("位置签到必须提供经纬度")

        start = clock.utcnow()
        end = clock.add_minutes(start, duration)
        code = ids.new_attendance_code()

        session_id = session_repo.insert(
            {
                "class_id": class_id,
                "title": title,
                "method": method,
                "code": code,
                "start_at": clock.to_iso(start),
                "end_at": clock.to_iso(end),
                "latitude": latitude,
                "longitude": longitude,
                "radius": radius,
                "status": "open",
                "created_by": int(operator["id"]),
            }
        )
        students = [int(row["id"]) for row in class_repo.students(class_id)]
        if students:
            notify_class(
                students,
                title=f"签到开始：{title}",
                content=f"{detail['course_name']} 正在签到，{duration} 分钟内完成",
                category="attendance",
                link=f"/attendance/{session_id}",
            )
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="create_attendance",
            entity="attendance_session",
            entity_id=session_id,
            detail=f"{detail['course_name']} / {method}",
        )
        return session_repo.detail(session_id) or {}


    def list_sessions(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
        detail = _class_or_fail(class_id)
        if viewer["role"] == permissions.ROLE_STUDENT:
            if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
                raise ForbiddenError("未选修该课程")
        else:
            permissions.assert_can_manage_course(viewer, detail)
        items = session_repo.list_by_class(class_id)
        if viewer["role"] == permissions.ROLE_STUDENT:
            for item in items:
                record = record_repo.find_by(
                    session_id=int(item["id"]), student_id=int(viewer["id"])
                )
                item["my_status"] = record.get("status") if record else None
        return items


    def open_sessions_for_student(viewer: dict[str, Any]) -> list[dict[str, Any]]:
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        return session_repo.list_open_for_student(int(viewer["id"]))


    def check_in(viewer: dict[str, Any], session_id: int,
                 payload: dict[str, Any]) -> dict[str, Any]:
        """学生签到。"""
        permissions.require_role(viewer, permissions.ROLE_STUDENT)
        session = session_repo.find_or_fail(session_id, "签到不存在")
        if session.get("status") != "open":
            raise ConflictError("签到已结束")

        now = clock.utcnow()
        end_at = clock.parse_iso(session.get("end_at"))
        if end_at and now > end_at:
            session_repo.close(session_id)
            raise ConflictError("签到已超时")

        class_id = int(session["class_id"])
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")

        existing = record_repo.find_by(session_id=session_id, student_id=int(viewer["id"]))
        if existing and existing.get("status") in ("present", "late"):
            raise ConflictError("你已经签过到了")

        submitted_code = validators.optional_str(payload, "code", "", max_len=16).upper()
        if submitted_code != str(session["code"]).upper():
            raise ConflictError("签到码不正确")

        if session["method"] == "location":
            lat = validators.optional_float(payload, "latitude", None)
            lon = validators.optional_float(payload, "longitude", None)
            if lat is None or lon is None:
                raise validators.ValidationError("位置签到需要提供定位")
            distance = haversine_meters(
                float(session["latitude"]), float(session["longitude"]), lat, lon
            )
            if distance > float(session.get("radius") or 200):
                raise ConflictError(f"距离签到点 {distance:.0f} 米，超出允许范围")
            note = f"距离 {distance:.0f} 米"
        else:
            note = ""

        started = clock.parse_iso(session.get("start_at")) or now
        late_threshold = clock.add_minutes(started, config.ATTENDANCE_LATE_MINUTES)
        status = "late" if now > late_threshold else "present"

        record_repo.mark(session_id, int(viewer["id"]), status, note)
        return {
            "session_id": session_id,
            "status": status,
            "status_label": "正常" if status == "present" else "迟到",
            "checked_at": clock.to_iso(now),
            "note": note,
        }


    def mark_manually(operator: dict[str, Any], session_id: int,
                      payload: dict[str, Any]) -> dict[str, Any]:
        """教师补签/改签。"""
        permissions.require_teacher(operator)
        session = session_repo.find_or_fail(session_id, "签到不存在")
        detail = _class_or_fail(int(session["class_id"]))
        permissions.assert_can_manage_course(operator, detail)

        student_id = validators.required_int(payload, "student_id", min_value=1)
        status = validators.ensure_enum(
            validators.required_str(payload, "status"),
            ("present", "late", "absent", "leave"),
            "签到状态",
        )
        note = validators.optional_str(payload, "note", "教师手动标记", max_len=200)
        record_repo.mark(session_id, student_id, status, note)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="mark_attendance",
            entity="attendance_record",
            entity_id=session_id,
            detail=f"学生 {student_id} -> {status}",
        )
        return {"session_id": session_id, "student_id": student_id, "status": status}


    def session_detail(viewer: dict[str, Any], session_id: int) -> dict[str, Any]:
        session = session_repo.detail(session_id)
        if session is None:
            raise NotFoundError("签到不存在")
        class_id = int(session["class_id"])
        detail = _class_or_fail(class_id)
        if viewer["role"] == permissions.ROLE_STUDENT:
            if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
                raise ForbiddenError("未选修该课程")
            records = [row for row in record_repo.list_by_session(session_id)
                       if int(row["student_id"]) == int(viewer["id"])]
        else:
            permissions.assert_can_manage_course(viewer, detail)
            records = record_repo.list_by_session(session_id)
        session["records"] = records
        session["class_detail"] = detail
        return session


    def close_session(operator: dict[str, Any], session_id: int) -> dict[str, Any]:
        permissions.require_teacher(operator)
        session = session_repo.find_or_fail(session_id, "签到不存在")
        detail = _class_or_fail(int(session["class_id"]))
        permissions.assert_can_manage_course(operator, detail)
        session_repo.close(session_id)
        return {"session_id": session_id, "status": "closed"}


    def class_attendance_summary(operator: dict[str, Any],
                                 class_id: int) -> dict[str, Any]:
        permissions.require_teacher(operator)
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)
        return {
            "class": detail,
            "rows": record_repo.class_summary(class_id),
            "session_count": len(session_repo.list_by_class(class_id)),
        }
    return SimpleNamespace(
        session_repo=session_repo,
        record_repo=record_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        audit_repo=audit_repo,
        METHODS=METHODS,
        haversine_meters=haversine_meters,
        create_session=create_session,
        list_sessions=list_sessions,
        open_sessions_for_student=open_sessions_for_student,
        check_in=check_in,
        mark_manually=mark_manually,
        session_detail=session_detail,
        close_session=close_session,
        class_attendance_summary=class_attendance_summary,
    )


# ======================================================================
# 模块：backend/services/grade_service.py
# ======================================================================
def _mod_grade_service(AssignmentRepository, AttendanceRecordRepository, ClassRepository, EnrollmentRepository, ForbiddenError, GradeItemRepository, GradeRuleRepository, NotFoundError, SubmissionRepository, UserRepository, ValidationError, config, connection, permissions, validators):
    """成绩服务：权重配置、成绩计算、成绩单导出。

    计算模型（可在每个教学班单独配置）：
        总评 = 作业均分×w1 + 测验均分×w2 + 出勤率×w3 + 期末×w4 + 加分
    所有分项先归一化成百分制，再加权，避免不同满分口径互相污染。
    """


    import csv
    import io
    from typing import Any


    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    assignment_repo = AssignmentRepository()
    submission_repo = SubmissionRepository()
    attendance_repo = AttendanceRecordRepository()
    rule_repo = GradeRuleRepository()
    item_repo = GradeItemRepository()
    user_repo = UserRepository()


    def _class_or_fail(class_id: int) -> dict[str, Any]:
        detail = class_repo.detail(class_id)
        if detail is None:
            raise NotFoundError("教学班不存在")
        return detail


    def get_rule(operator: dict[str, Any], class_id: int) -> dict[str, Any]:
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)
        return rule_repo.get_or_default(class_id)


    def save_rule(operator: dict[str, Any], class_id: int,
                  payload: dict[str, Any]) -> dict[str, Any]:
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)

        weights = {
            "assignment_weight": validators.optional_float(
                payload, "assignment_weight", config.DEFAULT_GRADE_WEIGHTS["assignment"],
                min_value=0, max_value=1,
            ),
            "quiz_weight": validators.optional_float(
                payload, "quiz_weight", config.DEFAULT_GRADE_WEIGHTS["quiz"],
                min_value=0, max_value=1,
            ),
            "attendance_weight": validators.optional_float(
                payload, "attendance_weight", config.DEFAULT_GRADE_WEIGHTS["attendance"],
                min_value=0, max_value=1,
            ),
            "final_weight": validators.optional_float(
                payload, "final_weight", config.DEFAULT_GRADE_WEIGHTS["final"],
                min_value=0, max_value=1,
            ),
            "pass_score": validators.optional_float(payload, "pass_score", 60, min_value=0, max_value=100),
        }
        total_weight = round(sum(
            weights[key] for key in
            ("assignment_weight", "quiz_weight", "attendance_weight", "final_weight")
        ), 4)
        if abs(total_weight - 1.0) > 0.001:
            raise ValidationError(f"各项权重之和必须为 1，当前为 {total_weight}")
        rule_repo.save(class_id, weights)
        return rule_repo.get_or_default(class_id)


    def _assignment_component(class_id: int, student_id: int) -> tuple[float, int]:
        rows = submission_repo.student_scores(class_id, student_id)
        total_full = sum(float(row["full_score"] or 100) for row in rows)
        total_got = sum(float(row["score"]) for row in rows if row.get("score") is not None)
        if total_full <= 0:
            return 0.0, 0
        return round(total_got / total_full * 100, 2), len(rows)


    def _quiz_component(class_id: int, student_id: int) -> tuple[float, int]:
        rows = connection.query_all(
            """SELECT q.total_score, a.score
                 FROM quizzes q
                 JOIN quiz_attempts a ON a.quiz_id = q.id AND a.student_id = ?
                WHERE q.class_id = ? AND a.status IN ('submitted', 'graded')""",
            (student_id, class_id),
        )
        if not rows:
            return 0.0, 0
        rates = []
        for row in rows:
            total = float(row["total_score"] or 0)
            if total > 0:
                rates.append(float(row["score"] or 0) / total * 100)
        if not rates:
            return 0.0, len(rows)
        return round(sum(rates) / len(rates), 2), len(rows)


    def _attendance_component(class_id: int, student_id: int) -> tuple[float, dict[str, int]]:
        summary = attendance_repo.student_summary(class_id, student_id)
        return round(float(summary.get("rate") or 0) * 100, 2), summary


    def compute_student(class_id: int, student_id: int,
                        rule: dict[str, Any] | None = None,
                        final_override: float | None = None) -> dict[str, Any]:
        """计算单个学生的成绩明细。"""
        rule = rule or rule_repo.get_or_default(class_id)
        assignment_score, assignment_count = _assignment_component(class_id, student_id)
        quiz_score, quiz_count = _quiz_component(class_id, student_id)
        attendance_score, attendance_summary = _attendance_component(class_id, student_id)

        item = item_repo.get(class_id, student_id) or {}
        final_score = final_override if final_override is not None else item.get("final_score")
        final_value = float(final_score) if final_score is not None else None
        bonus = float(item.get("bonus") or 0)

        weights = rule
        total = (
            assignment_score * float(weights.get("assignment_weight") or 0)
            + quiz_score * float(weights.get("quiz_weight") or 0)
            + attendance_score * float(weights.get("attendance_weight") or 0)
            + (final_value if final_value is not None else 0) * float(weights.get("final_weight") or 0)
            + bonus
        )
        total = round(min(100.0, max(0.0, total)), 2)
        return {
            "student_id": student_id,
            "assignment_score": assignment_score,
            "assignment_count": assignment_count,
            "quiz_score": quiz_score,
            "quiz_count": quiz_count,
            "attendance_score": attendance_score,
            "attendance": attendance_summary,
            "final_score": final_value,
            "bonus": bonus,
            "total": total,
            "passed": total >= float(weights.get("pass_score") or 60),
            "grade_point": _to_gpa(total),
            "remark": item.get("remark") or "",
        }


    def _to_gpa(score: float) -> float:
        """百分制 -> 4.0 绩点（常见换算规则）。"""
        if score >= 90:
            return 4.0
        if score >= 85:
            return 3.7
        if score >= 82:
            return 3.3
        if score >= 78:
            return 3.0
        if score >= 75:
            return 2.7
        if score >= 72:
            return 2.3
        if score >= 68:
            return 2.0
        if score >= 64:
            return 1.5
        if score >= 60:
            return 1.0
        return 0.0


    def gradebook(operator: dict[str, Any], class_id: int) -> dict[str, Any]:
        """整班成绩册。"""
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)
        rule = rule_repo.get_or_default(class_id)
        students = class_repo.students(class_id)
        rows = []
        for student in students:
            computed = compute_student(class_id, int(student["id"]), rule)
            computed.update(
                {
                    "real_name": student["real_name"],
                    "number": student.get("number") or "",
                    "department": student.get("department") or "",
                }
            )
            rows.append(computed)

        scores = [row["total"] for row in rows]
        stats = {
            "count": len(rows),
            "average": round(sum(scores) / len(scores), 2) if scores else 0,
            "max": max(scores) if scores else 0,
            "min": min(scores) if scores else 0,
            "pass_count": sum(1 for s in scores if s >= float(rule.get("pass_score") or 60)),
            "excellent_count": sum(1 for s in scores if s >= 90),
        }
        stats["pass_rate"] = round(stats["pass_count"] / stats["count"] * 100, 1) if stats["count"] else 0
        stats["excellent_rate"] = round(stats["excellent_count"] / stats["count"] * 100, 1) if stats["count"] else 0
        return {"class": detail, "rule": rule, "rows": rows, "stats": stats}


    def set_final_score(operator: dict[str, Any], class_id: int,
                        payload: dict[str, Any]) -> dict[str, Any]:
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)
        student_id = validators.required_int(payload, "student_id", min_value=1)
        final_score = validators.optional_float(payload, "final_score", None, min_value=0, max_value=100)
        bonus = validators.optional_float(payload, "bonus", 0, min_value=-20, max_value=20)
        remark = validators.optional_str(payload, "remark", "", max_len=200)

        item_repo.upsert(
            class_id,
            student_id,
            {"final_score": final_score, "bonus": bonus, "remark": remark},
        )
        computed = compute_student(class_id, student_id)
        item_repo.set_total(class_id, student_id, computed["total"])
        return computed


    def batch_set_final(operator: dict[str, Any], class_id: int,
                        rows: list[dict[str, Any]]) -> dict[str, Any]:
        detail = _class_or_fail(class_id)
        permissions.assert_can_manage_course(operator, detail)
        updated = 0
        failed: list[dict[str, Any]] = []
        for row in rows:
            try:
                set_final_score(operator, class_id, row)
                updated += 1
            except Exception as exc:  # noqa: BLE001
                failed.append({"student_id": row.get("student_id"), "error": str(exc)})
        return {"updated": updated, "failed": failed}


    def my_transcript(student: dict[str, Any]) -> dict[str, Any]:
        """学生成绩单：按课程列出总分与绩点。"""
        permissions.require_role(student, permissions.ROLE_STUDENT)
        classes = class_repo.all(
            where="id IN (SELECT class_id FROM enrollments WHERE student_id = ? AND status = 'active')",
            params=(int(student["id"]),),
            order_by="id",
        )
        rows = []
        total_credit = 0.0
        total_point = 0.0
        for item in classes:
            class_id = int(item["id"])
            detail = class_repo.detail(class_id) or {}
            computed = compute_student(class_id, int(student["id"]))
            credits = float(detail.get("credits") or 0)
            computed.update(
                {
                    "class_id": class_id,
                    "class_name": detail.get("class_name") or item.get("name"),
                    "course_name": detail.get("course_name"),
                    "credits": credits,
                }
            )
            rows.append(computed)
            total_credit += credits
            total_point += computed["grade_point"] * credits

        gpa = round(total_point / total_credit, 2) if total_credit else 0.0
        return {
            "rows": rows,
            "total_credits": round(total_credit, 1),
            "gpa": gpa,
            "average": round(sum(row["total"] for row in rows) / len(rows), 2) if rows else 0,
        }


    def export_csv(operator: dict[str, Any], class_id: int) -> str:
        """导出成绩册 CSV 文本。"""
        book = gradebook(operator, class_id)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["学号", "姓名", "作业", "测验", "出勤", "期末", "加分", "总评", "绩点", "是否通过"]
        )
        for row in book["rows"]:
            writer.writerow(
                [
                    row.get("number", ""),
                    row.get("real_name", ""),
                    row["assignment_score"],
                    row["quiz_score"],
                    row["attendance_score"],
                    "" if row["final_score"] is None else row["final_score"],
                    row["bonus"],
                    row["total"],
                    row["grade_point"],
                    "是" if row["passed"] else "否",
                ]
            )
        return buffer.getvalue()


    def class_ranking(operator: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
        book = gradebook(operator, class_id)
        rows = sorted(book["rows"], key=lambda item: item["total"], reverse=True)
        for index, row in enumerate(rows, start=1):
            row["rank"] = index
        return rows
    return SimpleNamespace(
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        assignment_repo=assignment_repo,
        submission_repo=submission_repo,
        attendance_repo=attendance_repo,
        rule_repo=rule_repo,
        item_repo=item_repo,
        user_repo=user_repo,
        get_rule=get_rule,
        save_rule=save_rule,
        compute_student=compute_student,
        gradebook=gradebook,
        set_final_score=set_final_score,
        batch_set_final=batch_set_final,
        my_transcript=my_transcript,
        export_csv=export_csv,
        class_ranking=class_ranking,
    )


# ======================================================================
# 模块：backend/services/resource_service.py
# ======================================================================
def _mod_resource_service(AuditRepository, ClassRepository, CourseRepository, EnrollmentRepository, ForbiddenError, NotFoundError, ResourceRepository, TooLargeError, clock, config, ids, permissions, safe_join, validators):
    """课程资料服务：上传、下载、删除、统计。"""


    import logging
    import mimetypes
    import os
    from pathlib import Path
    from typing import Any


    logger = logging.getLogger("eduflow.resource")

    resource_repo = ResourceRepository()
    course_repo = CourseRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    audit_repo = AuditRepository()

    ALLOWED_CATEGORIES = ("课件", "课件视频", "参考资料", "作业模板", "其他")


    def _course_or_fail(course_id: int) -> dict[str, Any]:
        detail = course_repo.detail(course_id)
        if detail is None:
            raise NotFoundError("课程不存在")
        return detail


    def _assert_view(viewer: dict[str, Any], course: dict[str, Any]) -> None:
        class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
        enrolled = bool(class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"]))))
        permissions.assert_can_view_course(viewer, course, enrolled=enrolled)


    def save_upload(filename: str, content: bytes, *,
                    course_id: int, operator: dict[str, Any],
                    title: str = "", description: str = "",
                    category: str = "课件") -> dict[str, Any]:
        """落盘 + 入库。文件名会做安全处理并加随机前缀。"""
        course = _course_or_fail(course_id)
        permissions.assert_can_manage_course(operator, course)

        if len(content) > config.MAX_UPLOAD_BYTES:
            raise TooLargeError("文件超过 64 MB 限制")
        if not content:
            raise validators.ValidationError("文件内容为空")

        safe_name = _sanitize_filename(filename)
        stored = f"{ids.new_filename_token()}_{safe_name}"
        target = safe_join(config.UPLOAD_DIR, stored)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

        mime, _ = mimetypes.guess_type(safe_name)
        resource_id = resource_repo.insert(
            {
                "course_id": course_id,
                "title": title or Path(safe_name).stem,
                "description": description,
                "filename": safe_name,
                "stored_name": stored,
                "size": len(content),
                "mime": mime or "application/octet-stream",
                "category": category if category in ALLOWED_CATEGORIES else "其他",
                "uploader_id": int(operator["id"]),
            }
        )
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="upload_resource",
            entity="resource",
            entity_id=resource_id,
            detail=f"{course['name']} / {safe_name} / {len(content)} bytes",
        )
        return resource_repo.detail(resource_id) or {}


    def _sanitize_filename(filename: str) -> str:
        name = os.path.basename((filename or "unnamed").replace("\\", "/"))
        name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
        name = name.strip(". ")
        if not name:
            name = "unnamed"
        if len(name) > 120:
            stem, ext = os.path.splitext(name)
            name = stem[:100] + ext[:20]
        return name


    def list_resources(viewer: dict[str, Any], course_id: int,
                       keyword: str = "") -> list[dict[str, Any]]:
        course = _course_or_fail(course_id)
        _assert_view(viewer, course)
        return resource_repo.list_by_course(course_id, keyword=keyword)


    def get_download(viewer: dict[str, Any], resource_id: int) -> tuple[Path, str]:
        resource = resource_repo.find_or_fail(resource_id, "资料不存在")
        course = _course_or_fail(int(resource["course_id"]))
        _assert_view(viewer, course)
        path = safe_join(config.UPLOAD_DIR, resource["stored_name"])
        if not path.exists():
            raise NotFoundError("文件已丢失，请联系管理员")
        resource_repo.increment_download(resource_id)
        return path, resource["filename"]


    def delete_resource(operator: dict[str, Any], resource_id: int) -> None:
        resource = resource_repo.find_or_fail(resource_id, "资料不存在")
        course = _course_or_fail(int(resource["course_id"]))
        permissions.assert_can_manage_course(operator, course)
        path = safe_join(config.UPLOAD_DIR, resource["stored_name"])
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:  # noqa: BLE001
                logger.warning("删除文件失败: %s", exc)
        resource_repo.delete(resource_id)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="delete_resource",
            entity="resource",
            entity_id=resource_id,
            detail=resource["filename"],
        )


    def storage_usage() -> dict[str, Any]:
        total = 0
        count = 0
        if config.UPLOAD_DIR.exists():
            for path in config.UPLOAD_DIR.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
                    count += 1
        return {
            "files": count,
            "bytes": total,
            "megabytes": round(total / 1024 / 1024, 2),
            "limit_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
            "checked_at": clock.now_iso(),
        }


    def ensure_upload_dir() -> None:
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        logger=logger,
        resource_repo=resource_repo,
        course_repo=course_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        audit_repo=audit_repo,
        ALLOWED_CATEGORIES=ALLOWED_CATEGORIES,
        save_upload=save_upload,
        list_resources=list_resources,
        get_download=get_download,
        delete_resource=delete_resource,
        storage_usage=storage_usage,
        ensure_upload_dir=ensure_upload_dir,
    )


# ======================================================================
# 模块：backend/services/discussion_service.py
# ======================================================================
def _mod_discussion_service(AuditRepository, ClassRepository, CourseRepository, DiscussionRepository, EnrollmentRepository, ForbiddenError, NotFoundError, ReplyRepository, permissions, validators):
    """课程讨论区服务。"""


    from typing import Any


    discussion_repo = DiscussionRepository()
    reply_repo = ReplyRepository()
    course_repo = CourseRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    audit_repo = AuditRepository()


    def _course_or_fail(course_id: int) -> dict[str, Any]:
        detail = course_repo.detail(course_id)
        if detail is None:
            raise NotFoundError("课程不存在")
        return detail


    def _assert_view(viewer: dict[str, Any], course: dict[str, Any]) -> None:
        class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
        enrolled = bool(class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"]))))
        permissions.assert_can_view_course(viewer, course, enrolled=enrolled)


    def list_threads(viewer: dict[str, Any], course_id: int) -> list[dict[str, Any]]:
        course = _course_or_fail(course_id)
        _assert_view(viewer, course)
        return discussion_repo.list_by_course(course_id)


    def create_thread(viewer: dict[str, Any], course_id: int,
                      payload: dict[str, Any]) -> dict[str, Any]:
        course = _course_or_fail(course_id)
        _assert_view(viewer, course)
        title = validators.required_str(payload, "title", min_len=2, max_len=120)
        content = validators.optional_str(payload, "content", "", max_len=20000)
        discussion_id = discussion_repo.insert(
            {
                "course_id": course_id,
                "title": title,
                "content": content,
                "author_id": int(viewer["id"]),
            }
        )
        audit_repo.log(
            user_id=int(viewer["id"]),
            username=viewer["username"],
            action="create_discussion",
            entity="discussion",
            entity_id=discussion_id,
            detail=title,
        )
        return discussion_repo.detail(discussion_id) or {}


    def get_thread(viewer: dict[str, Any], discussion_id: int) -> dict[str, Any]:
        thread = discussion_repo.detail(discussion_id)
        if thread is None:
            raise NotFoundError("话题不存在")
        course = _course_or_fail(int(thread["course_id"]))
        _assert_view(viewer, course)
        discussion_repo.increment_views(discussion_id)
        thread["replies"] = reply_repo.list_by_discussion(discussion_id)
        thread["reply_count"] = len(thread["replies"])
        return thread


    def reply(viewer: dict[str, Any], discussion_id: int,
              payload: dict[str, Any]) -> dict[str, Any]:
        thread = discussion_repo.find_or_fail(discussion_id, "话题不存在")
        course = _course_or_fail(int(thread["course_id"]))
        _assert_view(viewer, course)
        if thread.get("locked"):
            raise ForbiddenError("该话题已锁定，不能再回复")

        content = validators.required_str(payload, "content", min_len=1, max_len=10000)
        parent_id = validators.optional_int(payload, "parent_id", None)
        reply_id = reply_repo.insert(
            {
                "discussion_id": discussion_id,
                "author_id": int(viewer["id"]),
                "content": content,
                "parent_id": parent_id,
            }
        )
        return {"id": reply_id, "discussion_id": discussion_id, "content": content}


    def set_flags(viewer: dict[str, Any], discussion_id: int,
                  payload: dict[str, Any]) -> dict[str, Any]:
        """置顶 / 锁定 / 删除（教师或管理员）。"""
        thread = discussion_repo.find_or_fail(discussion_id, "话题不存在")
        course = _course_or_fail(int(thread["course_id"]))
        permissions.assert_can_manage_course(viewer, course)

        if "pinned" in payload:
            discussion_repo.update(discussion_id, {"pinned": 1 if validators.to_bool(payload["pinned"]) else 0})
        if "locked" in payload:
            discussion_repo.update(discussion_id, {"locked": 1 if validators.to_bool(payload["locked"]) else 0})
        if validators.to_bool(payload.get("delete"), False):
            discussion_repo.delete(discussion_id)
            return {"deleted": True, "discussion_id": discussion_id}
        return discussion_repo.detail(discussion_id) or {}


    def delete_reply(viewer: dict[str, Any], reply_id: int) -> dict[str, Any]:
        item = reply_repo.find_or_fail(reply_id, "回复不存在")
        thread = discussion_repo.find_or_fail(int(item["discussion_id"]), "话题不存在")
        course = _course_or_fail(int(thread["course_id"]))
        if int(item["author_id"]) != int(viewer["id"]):
            permissions.assert_can_manage_course(viewer, course)
        reply_repo.delete(reply_id)
        return {"deleted": True, "reply_id": reply_id}


    def course_discussion_summary(course_id: int) -> dict[str, Any]:
        threads = discussion_repo.list_by_course(course_id)
        total_replies = sum(int(item.get("reply_count") or 0) for item in threads)
        return {
            "threads": len(threads),
            "replies": total_replies,
            "last_active": threads[0]["created_at"] if threads else None,
        }
    return SimpleNamespace(
        discussion_repo=discussion_repo,
        reply_repo=reply_repo,
        course_repo=course_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        audit_repo=audit_repo,
        list_threads=list_threads,
        create_thread=create_thread,
        get_thread=get_thread,
        reply=reply,
        set_flags=set_flags,
        delete_reply=delete_reply,
        course_discussion_summary=course_discussion_summary,
    )


# ======================================================================
# 模块：backend/services/chapter_service.py
# ======================================================================
def _mod_chapter_service(AssignmentRepository, AuditRepository, ChapterRepository, ClassRepository, CourseRepository, EnrollmentRepository, ForbiddenError, NotFoundError, QuizRepository, ResourceRepository, TaskProgressRepository, TaskRepository, ValidationError, clock, permissions, validators):
    """章节任务点与学习进度。

    学习通的课程内容以「章节 -> 任务点」组织：教师建章节、往章节里放任务点
    （资料、作业、测验、讨论或纯图文），学生逐个完成，系统记录完成度并汇总
    成课程学习进度。

    设计要点：
    - 章节挂在课程上，一门课的所有教学班共用同一套章节；
    - 任务点通过 resource_id / quiz_id / assignment_id 关联到已有内容，不复制一份；
    - task_progress 只在学生真正开始后才写记录，没有记录即「未开始」；
    - 学生只能给自己上报进度，教师只能看自己课程的完成率。
    """


    from collections import defaultdict
    from typing import Any


    chapter_repo = ChapterRepository()
    task_repo = TaskRepository()
    progress_repo = TaskProgressRepository()
    course_repo = CourseRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    resource_repo = ResourceRepository()
    assignment_repo = AssignmentRepository()
    quiz_repo = QuizRepository()
    audit_repo = AuditRepository()

    TASK_TYPES = ("material", "assignment", "quiz", "discussion", "text")
    TASK_TYPE_LABELS = {
        "material": "资料",
        "assignment": "作业",
        "quiz": "测验",
        "discussion": "讨论",
        "text": "图文",
    }

    # 任务点类型 -> 允许关联的字段
    TYPE_LINK_FIELDS = {
        "material": "resource_id",
        "assignment": "assignment_id",
        "quiz": "quiz_id",
    }

    _MISSING = object()


    # ---------------------------------------------------------------------------
    # 内部工具
    # ---------------------------------------------------------------------------


    def _course_or_fail(course_id: int) -> dict[str, Any]:
        course = course_repo.detail(course_id)
        if course is None:
            raise NotFoundError("课程不存在")
        return course


    def _chapter_or_fail(chapter_id: int) -> dict[str, Any]:
        chapter = chapter_repo.detail(chapter_id)
        if chapter is None:
            raise NotFoundError("章节不存在")
        return chapter


    def _task_or_fail(task_id: int, message: str = "任务点不存在") -> dict[str, Any]:
        task = task_repo.detail(task_id)
        if task is None:
            raise NotFoundError(message)
        return task


    def _assert_can_view(viewer: dict[str, Any], course: dict[str, Any]) -> bool:
        """校验课程可见性，返回学生是否已选课。"""
        class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
        enrolled = bool(
            class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"])))
        )
        permissions.assert_can_view_course(viewer, course, enrolled=enrolled)
        return enrolled


    def _assert_enrolled(student: dict[str, Any], course_id: int) -> None:
        class_ids = {int(item["id"]) for item in class_repo.of_course(course_id)}
        if not (class_ids & set(enroll_repo.class_ids_of_student(int(student["id"])))):
            raise ForbiddenError("你还没有加入该课程的教学班")


    def _percent(done: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round(min(100.0, done * 100.0 / total), 1)


    def _progress_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "status": row.get("status") or "in_progress",
            "progress": int(row.get("progress") or 0),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "updated_at": row.get("updated_at"),
        }


    def _task_public(task: dict[str, Any]) -> dict[str, Any]:
        """任务点的公共字段（去掉仅统计需要的列）。"""
        return {
            "id": int(task["id"]),
            "chapter_id": int(task["chapter_id"]),
            "type": task["type"],
            "type_label": TASK_TYPE_LABELS.get(task["type"], task["type"]),
            "title": task["title"],
            "description": task.get("description") or "",
            "duration": int(task.get("duration") or 0),
            "required": bool(task.get("required", 1)),
            "resource_id": task.get("resource_id"),
            "resource_title": task.get("resource_title"),
            "resource_filename": task.get("resource_filename"),
            "quiz_id": task.get("quiz_id"),
            "quiz_title": task.get("quiz_title"),
            "assignment_id": task.get("assignment_id"),
            "assignment_title": task.get("assignment_title"),
            "order_no": int(task.get("order_no") or 0),
        }


    # ---------------------------------------------------------------------------
    # 章节
    # ---------------------------------------------------------------------------


    def list_chapters(viewer: dict[str, Any], course_id: int) -> dict[str, Any]:
        """课程章节树 + 任务点，学生带自己的进度，教师带完成率。"""
        course = _course_or_fail(course_id)
        _assert_can_view(viewer, course)

        chapters = chapter_repo.list_by_course(course_id)
        tasks = task_repo.list_by_course(course_id)
        grouped: dict[int, list[dict[str, Any]]] = {int(ch["id"]): [] for ch in chapters}
        for task in tasks:
            grouped.setdefault(int(task["chapter_id"]), []).append(task)

        is_student = viewer["role"] == permissions.ROLE_STUDENT
        viewer_id = int(viewer["id"])
        students = [] if is_student else chapter_repo.students_of_course(course_id)
        student_count = len(students)
        student_ids = {int(row["student_id"]) for row in students}

        my_progress: dict[int, dict[str, Any]] = {}
        completed_by_task: dict[int, int] = defaultdict(int)
        for row in progress_repo.list_by_course(course_id):
            task_id = int(row["task_id"])
            student_id = int(row["student_id"])
            if is_student and student_id == viewer_id:
                my_progress[task_id] = row
            if student_id in student_ids and row["status"] == "completed":
                completed_by_task[task_id] += 1

        items: list[dict[str, Any]] = []
        for chapter in chapters:
            chapter_id = int(chapter["id"])
            chapter_tasks: list[dict[str, Any]] = []
            completed = 0
            progress_sum = 0
            for task in grouped.get(chapter_id, []):
                task_id = int(task["id"])
                item = _task_public(task)
                if is_student:
                    row = my_progress.get(task_id)
                    item["my_progress"] = _progress_payload(row)
                    item["progress"] = int(row.get("progress") or 0) if row else 0
                    item["completed"] = bool(row and row["status"] == "completed")
                    progress_sum += item["progress"]
                    if item["completed"]:
                        completed += 1
                else:
                    done = completed_by_task.get(task_id, 0)
                    item["completed_count"] = done
                    item["student_count"] = student_count
                    item["progress"] = _percent(done, student_count)
                    completed += done
                chapter_tasks.append(item)

            total = len(chapter_tasks)
            if is_student:
                # 学生视角看「学习进度」：进行中的任务按百分比计入，
                # 而不是只有 100% 才算数。
                progress = round(progress_sum / total, 1) if total else 0.0
            else:
                progress = _percent(completed, total * student_count)

            items.append(
                {
                    "id": chapter_id,
                    "course_id": int(chapter["course_id"]),
                    "title": chapter["title"],
                    "description": chapter.get("description") or "",
                    "order_no": int(chapter.get("order_no") or 0),
                    "task_count": len(chapter_tasks),
                    "completed_count": completed,
                    "progress": progress,
                    "student_count": student_count,
                    "tasks": chapter_tasks,
                }
            )

        total_tasks = len(tasks)
        if is_student:
            completed_total = sum(
                1
                for row in my_progress.values()
                if row.get("status") == "completed"
            )
            progress_sum = sum(
                int(row.get("progress") or 0)
                for row in my_progress.values()
            )
            summary_progress = (
                round(progress_sum / total_tasks, 1) if total_tasks else 0.0
            )
        else:
            completed_total = sum(completed_by_task.values())
            summary_progress = _percent(completed_total, total_tasks * student_count)

        return {
            "course_id": course_id,
            "course_name": course["name"],
            "items": items,
            "summary": {
                "chapter_count": len(items),
                "task_count": total_tasks,
                "completed_count": completed_total,
                "progress": summary_progress,
                "student_count": student_count,
            },
        }


    def create_chapter(operator: dict[str, Any], course_id: int,
                       payload: dict[str, Any]) -> dict[str, Any]:
        course = _course_or_fail(course_id)
        permissions.assert_can_manage_course(operator, course)

        title = validators.required_str(payload, "title", min_len=2, max_len=120)
        description = validators.optional_str(payload, "description", "", max_len=2000)
        order_no = validators.optional_int(
            payload, "order_no", chapter_repo.next_order_no(course_id), min_value=1,
            max_value=9999,
        )
        chapter_id = chapter_repo.insert(
            {
                "course_id": course_id,
                "title": title,
                "description": description,
                "order_no": int(order_no or 1),
            }
        )
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="create_chapter",
            entity="chapter",
            entity_id=chapter_id,
            detail=f"{course['name']} / {title}",
        )
        return chapter_repo.detail(chapter_id) or {}


    def update_chapter(operator: dict[str, Any], chapter_id: int,
                       payload: dict[str, Any]) -> dict[str, Any]:
        chapter = _chapter_or_fail(chapter_id)
        course = _course_or_fail(int(chapter["course_id"]))
        permissions.assert_can_manage_course(operator, course)

        updates: dict[str, Any] = {}
        if "title" in payload:
            updates["title"] = validators.required_str(payload, "title", min_len=2, max_len=120)
        if "description" in payload:
            updates["description"] = validators.optional_str(
                payload, "description", "", max_len=2000
            )
        if "order_no" in payload:
            updates["order_no"] = validators.required_int(
                payload, "order_no", min_value=1, max_value=9999
            )
        if updates:
            chapter_repo.update(chapter_id, updates)
            audit_repo.log(
                user_id=int(operator["id"]),
                username=operator["username"],
                action="update_chapter",
                entity="chapter",
                entity_id=chapter_id,
                detail=f"更新章节字段：{', '.join(updates)}",
            )
        return chapter_repo.detail(chapter_id) or {}


    def delete_chapter(operator: dict[str, Any], chapter_id: int) -> None:
        chapter = _chapter_or_fail(chapter_id)
        course = _course_or_fail(int(chapter["course_id"]))
        permissions.assert_can_manage_course(operator, course)
        chapter_repo.delete(chapter_id)  # 任务点与进度由外键级联删除
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="delete_chapter",
            entity="chapter",
            entity_id=chapter_id,
            detail=chapter.get("title", ""),
        )


    # ---------------------------------------------------------------------------
    # 任务点
    # ---------------------------------------------------------------------------


    def _link_int(payload: dict[str, Any], key: str) -> Any:
        if key not in payload:
            return _MISSING
        raw = payload[key]
        if raw in (None, "", 0, "0"):
            return None
        return validators.to_int(raw, key, min_value=1)


    def _validate_resource(course_id: int, resource_id: int) -> None:
        row = resource_repo.find(resource_id)
        if row is None:
            raise NotFoundError("关联的资料不存在")
        if int(row["course_id"]) != course_id:
            raise ValidationError("关联的资料不属于本课程")


    def _validate_assignment(course_id: int, assignment_id: int) -> None:
        row = assignment_repo.detail(assignment_id)
        if row is None:
            raise NotFoundError("关联的作业不存在")
        if int(row["course_id"]) != course_id:
            raise ValidationError("关联的作业不属于本课程")


    def _validate_quiz(course_id: int, quiz_id: int) -> None:
        row = quiz_repo.detail(quiz_id)
        if row is None:
            raise NotFoundError("关联的测验不存在")
        if int(row["course_id"]) != course_id:
            raise ValidationError("关联的测验不属于本课程")


    def _task_fields(payload: dict[str, Any], course_id: int,
                     existing: dict[str, Any] | None = None) -> dict[str, Any]:
        """把请求体规范化成可写字段，同时校验关联内容归属。"""
        if "type" in payload:
            task_type = validators.ensure_enum(
                str(payload["type"]).strip(), TASK_TYPES, "任务点类型"
            )
        elif existing:
            task_type = str(existing["type"])
        else:
            task_type = "material"

        fields: dict[str, Any] = {"type": task_type}
        if "title" in payload or not existing:
            fields["title"] = validators.required_str(payload, "title", min_len=2, max_len=120)
        if "description" in payload:
            fields["description"] = validators.optional_str(
                payload, "description", "", max_len=2000
            )
        if "duration" in payload:
            fields["duration"] = validators.optional_int(
                payload, "duration", 0, min_value=0, max_value=600
            )
        if "required" in payload:
            fields["required"] = 1 if validators.to_bool(payload.get("required"), True) else 0
        if "order_no" in payload:
            fields["order_no"] = validators.required_int(
                payload, "order_no", min_value=1, max_value=9999
            )

        allowed = TYPE_LINK_FIELDS.get(task_type)
        type_changed = bool(existing and str(existing["type"]) != task_type)
        for key in ("resource_id", "assignment_id", "quiz_id"):
            raw = _link_int(payload, key)
            if key == allowed:
                if raw is _MISSING:
                    if not existing or type_changed:
                        fields[key] = None
                    continue
                if raw is None:
                    fields[key] = None
                    continue
                if key == "resource_id":
                    _validate_resource(course_id, int(raw))
                elif key == "assignment_id":
                    _validate_assignment(course_id, int(raw))
                else:
                    _validate_quiz(course_id, int(raw))
                fields[key] = int(raw)
            else:
                if raw not in (_MISSING, None):
                    raise ValidationError("任务点类型与关联内容不匹配")
                if type_changed:
                    fields[key] = None
        return fields


    def create_task(operator: dict[str, Any], chapter_id: int,
                    payload: dict[str, Any]) -> dict[str, Any]:
        chapter = _chapter_or_fail(chapter_id)
        course = _course_or_fail(int(chapter["course_id"]))
        permissions.assert_can_manage_course(operator, course)

        fields = _task_fields(payload, int(chapter["course_id"]))
        fields["chapter_id"] = chapter_id
        fields.setdefault("order_no", task_repo.next_order_no(chapter_id))
        task_id = task_repo.insert(fields)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="create_task",
            entity="task",
            entity_id=task_id,
            detail=f"{chapter['title']} / {fields['title']}",
        )
        return _task_public(task_repo.detail(task_id) or {})


    def update_task(operator: dict[str, Any], task_id: int,
                    payload: dict[str, Any]) -> dict[str, Any]:
        task = _task_or_fail(task_id)
        course = _course_or_fail(int(task["course_id"]))
        permissions.assert_can_manage_course(operator, course)

        fields = _task_fields(payload, int(task["course_id"]), existing=task)
        changes = {
            key: value for key, value in fields.items() if task.get(key) != value
        }
        if changes:
            task_repo.update(task_id, changes)
            audit_repo.log(
                user_id=int(operator["id"]),
                username=operator["username"],
                action="update_task",
                entity="task",
                entity_id=task_id,
                detail=f"更新任务点字段：{', '.join(changes)}",
            )
        return _task_public(task_repo.detail(task_id) or {})


    def delete_task(operator: dict[str, Any], task_id: int) -> None:
        task = _task_or_fail(task_id)
        course = _course_or_fail(int(task["course_id"]))
        permissions.assert_can_manage_course(operator, course)
        task_repo.delete(task_id)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="delete_task",
            entity="task",
            entity_id=task_id,
            detail=task.get("title", ""),
        )


    # ---------------------------------------------------------------------------
    # 学习进度
    # ---------------------------------------------------------------------------


    def _student_course_stats(course_id: int,
                              student_id: int) -> dict[str, Any]:
        """某个学生在某门课上的任务进度快照。"""
        tasks = task_repo.list_by_course(course_id)
        rows = {
            int(row["task_id"]): row
            for row in progress_repo.list_by_student_course(student_id, course_id)
        }
        chapter_tasks: dict[int, list[int]] = defaultdict(list)
        for task in tasks:
            chapter_tasks[int(task["chapter_id"])].append(int(task["id"]))

        chapters: dict[int, dict[str, Any]] = {}
        for chapter_id, task_ids in chapter_tasks.items():
            done = sum(
                1 for task_id in task_ids
                if rows.get(task_id, {}).get("status") == "completed"
            )
            progress_sum = sum(
                int(rows.get(task_id, {}).get("progress") or 0)
                for task_id in task_ids
            )
            chapters[chapter_id] = {
                "task_count": len(task_ids),
                "completed_count": done,
                "progress": (
                    round(progress_sum / len(task_ids), 1) if task_ids else 0.0
                ),
            }
        completed_total = sum(
            1 for row in rows.values() if row.get("status") == "completed"
        )
        progress_sum = sum(int(row.get("progress") or 0) for row in rows.values())
        return {
            "task_count": len(tasks),
            "completed_count": completed_total,
            "progress": round(progress_sum / len(tasks), 1) if tasks else 0.0,
            "chapters": chapters,
        }


    def report_progress(student: dict[str, Any], task_id: int,
                        payload: dict[str, Any]) -> dict[str, Any]:
        """学生上报任务点进度；100 即完成，会自动写入完成时间。"""
        permissions.require_role(student, permissions.ROLE_STUDENT)
        task = _task_or_fail(task_id)
        course_id = int(task["course_id"])
        _assert_enrolled(student, course_id)

        existing = progress_repo.get(task_id, int(student["id"]))
        raw_status = payload.get("status")
        status = None
        if raw_status not in (None, ""):
            status = validators.ensure_enum(
                str(raw_status).strip(), ("in_progress", "completed"), "进度状态"
            )

        has_progress = "progress" in payload and payload["progress"] not in (None, "")
        progress = (
            validators.to_int(payload["progress"], "学习进度", min_value=0, max_value=100)
            if has_progress
            else None
        )
        if progress is None and status is None:
            raise ValidationError("请提供 progress 或 status")

        if status == "completed":
            progress = 100
        elif progress == 100:
            status = "completed"
        elif progress is not None:
            status = "in_progress"
        else:  # status == in_progress 且没给具体数值：至少推进到 10%
            progress = max(int(existing["progress"]) if existing else 0, 10)

        now = clock.now_iso()
        started_at = None
        if existing and existing.get("started_at"):
            started_at = existing["started_at"]
        if not started_at:
            started_at = now
        if progress >= 100:
            # 重复点「完成」不应刷新首次完成时间
            if (
                existing
                and existing.get("status") == "completed"
                and existing.get("finished_at")
            ):
                finished_at = existing["finished_at"]
            else:
                finished_at = now
        else:
            finished_at = None

        row = progress_repo.save(
            task_id,
            int(student["id"]),
            {
                "status": status,
                "progress": progress,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )

        newly_completed = (
            status == "completed"
            and (not existing or existing.get("status") != "completed")
        )
        if newly_completed:
            audit_repo.log(
                user_id=int(student["id"]),
                username=student["username"],
                action="complete_task",
                entity="task",
                entity_id=task_id,
                detail=task.get("title", ""),
            )

        stats = _student_course_stats(course_id, int(student["id"]))
        chapter = stats["chapters"].get(int(task["chapter_id"]), {})
        return {
            "task_id": task_id,
            "status": row.get("status"),
            "progress": int(row.get("progress") or 0),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "chapter": {
                "id": int(task["chapter_id"]),
                "task_count": chapter.get("task_count", 0),
                "completed_count": chapter.get("completed_count", 0),
                "progress": chapter.get("progress", 0.0),
            },
            "course": {
                "task_count": stats["task_count"],
                "completed_count": stats["completed_count"],
                "progress": stats["progress"],
            },
        }


    def course_progress(viewer: dict[str, Any], course_id: int) -> dict[str, Any]:
        """教师视角：整门课的任务点完成率与学生明细。"""
        course = _course_or_fail(course_id)
        permissions.assert_can_manage_course(viewer, course)

        chapters = chapter_repo.list_by_course(course_id)
        tasks = task_repo.list_by_course(course_id)
        students = chapter_repo.students_of_course(course_id)
        student_count = len(students)
        student_ids = {int(row["student_id"]) for row in students}

        rows = progress_repo.list_by_course(course_id)
        completed_by_task: dict[int, int] = defaultdict(int)
        by_student: dict[int, dict[str, Any]] = {}
        completed_pairs: set[tuple[int, int]] = set()
        for row in rows:
            student_id = int(row["student_id"])
            if student_id not in student_ids:
                continue
            record = by_student.setdefault(
                student_id, {"completed": 0, "last_active_at": None}
            )
            record["last_active_at"] = max(
                filter(None, [record["last_active_at"], row.get("updated_at")]),
                default=None,
            )
            if row["status"] == "completed":
                record["completed"] += 1
                completed_by_task[int(row["task_id"])] += 1
                completed_pairs.add((student_id, int(row["task_id"])))

        total_tasks = len(tasks)
        student_rows = []
        for student in students:
            student_id = int(student["student_id"])
            record = by_student.get(student_id, {"completed": 0, "last_active_at": None})
            student_rows.append(
                {
                    "student_id": student_id,
                    "real_name": student["real_name"],
                    "number": student.get("number"),
                    "class_name": student.get("class_name"),
                    "completed_count": record["completed"],
                    "task_count": total_tasks,
                    "progress": _percent(record["completed"], total_tasks),
                    "last_active_at": record["last_active_at"],
                }
            )

        chapter_rows = []
        for chapter in chapters:
            chapter_task_ids = [
                int(task["id"]) for task in tasks
                if int(task["chapter_id"]) == int(chapter["id"])
            ]
            done = sum(completed_by_task.get(task_id, 0) for task_id in chapter_task_ids)
            total = len(chapter_task_ids)
            completed_students = sum(
                1
                for student in students
                if chapter_task_ids
                and all(
                    (int(student["student_id"]), task_id) in completed_pairs
                    for task_id in chapter_task_ids
                )
            )
            chapter_rows.append(
                {
                    "id": int(chapter["id"]),
                    "title": chapter["title"],
                    "task_count": total,
                    "completed_count": done,
                    "progress": _percent(done, total * student_count),
                    "completed_students": completed_students,
                }
            )

        avg_progress = (
            round(sum(row["progress"] for row in student_rows) / len(student_rows), 1)
            if student_rows
            else 0.0
        )
        return {
            "course_id": course_id,
            "course_name": course["name"],
            "task_count": total_tasks,
            "student_count": student_count,
            "tasks": [
                {
                    "id": int(task["id"]),
                    "chapter_id": int(task["chapter_id"]),
                    "chapter_title": task.get("chapter_title"),
                    "title": task["title"],
                    "type": task["type"],
                    "type_label": TASK_TYPE_LABELS.get(task["type"], task["type"]),
                }
                for task in tasks
            ],
            "chapters": chapter_rows,
            "students": student_rows,
            "summary": {
                "avg_progress": avg_progress,
                "completed_students": sum(
                    1 for row in student_rows if row["progress"] >= 100
                ),
                "student_count": student_count,
                "task_count": total_tasks,
            },
        }


    def my_learning(student: dict[str, Any]) -> list[dict[str, Any]]:
        """学生视角：我在每门课上的章节任务完成情况（首页/课程页用）。"""
        permissions.require_role(student, permissions.ROLE_STUDENT)
        student_id = int(student["id"])
        seen: set[int] = set()
        result: list[dict[str, Any]] = []
        for row in course_repo.of_student(student_id):
            course_id = int(row["id"])
            if course_id in seen:
                continue
            seen.add(course_id)
            stats = _student_course_stats(course_id, student_id)
            result.append(
                {
                    "course_id": course_id,
                    "code": row.get("code"),
                    "name": row.get("name"),
                    "teacher_name": row.get("teacher_name"),
                    "class_name": row.get("class_name"),
                    "term": row.get("term"),
                    "chapter_count": chapter_repo.count(
                        "course_id = ?", (course_id,)
                    ),
                    "task_count": stats["task_count"],
                    "completed_count": stats["completed_count"],
                    "progress": stats["progress"],
                }
            )
        result.sort(key=lambda item: (-item["progress"], item["name"] or ""))
        return result
    return SimpleNamespace(
        chapter_repo=chapter_repo,
        task_repo=task_repo,
        progress_repo=progress_repo,
        course_repo=course_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        resource_repo=resource_repo,
        assignment_repo=assignment_repo,
        quiz_repo=quiz_repo,
        audit_repo=audit_repo,
        TASK_TYPES=TASK_TYPES,
        TASK_TYPE_LABELS=TASK_TYPE_LABELS,
        TYPE_LINK_FIELDS=TYPE_LINK_FIELDS,
        list_chapters=list_chapters,
        create_chapter=create_chapter,
        update_chapter=update_chapter,
        delete_chapter=delete_chapter,
        create_task=create_task,
        update_task=update_task,
        delete_task=delete_task,
        report_progress=report_progress,
        course_progress=course_progress,
        my_learning=my_learning,
    )


# ======================================================================
# 模块：backend/services/statistics_service.py
# ======================================================================
def _mod_statistics_service(AuditRepository, ClassRepository, CourseRepository, EnrollmentRepository, UserRepository, clock, connection, permissions):
    """统计分析服务：首页看板、课程活跃度、学习报告。"""


    from typing import Any


    user_repo = UserRepository()
    course_repo = CourseRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    audit_repo = AuditRepository()


    def admin_dashboard() -> dict[str, Any]:
        """管理员首页：全局数字 + 最近动态。"""
        counts = user_repo.count_all()
        course_total = int(connection.scalar("SELECT COUNT(*) FROM courses", default=0) or 0)
        class_total = int(connection.scalar("SELECT COUNT(*) FROM classes", default=0) or 0)
        assignment_total = int(connection.scalar("SELECT COUNT(*) FROM assignments", default=0) or 0)
        submission_total = int(connection.scalar("SELECT COUNT(*) FROM submissions", default=0) or 0)
        attendance_total = int(
            connection.scalar("SELECT COUNT(*) FROM attendance_records", default=0) or 0
        )
        present_total = int(
            connection.scalar(
                "SELECT COUNT(*) FROM attendance_records WHERE status = 'present'", default=0
            )
            or 0
        )
        attendance_rate = round(present_total / attendance_total * 100, 1) if attendance_total else 0.0

        recent = audit_repo.list_logs(limit=10)
        trend = _activity_trend(days=7)
        return {
            "users": counts,
            "courses": course_total,
            "classes": class_total,
            "assignments": assignment_total,
            "submissions": submission_total,
            "attendance_rate": attendance_rate,
            "recent_logs": recent,
            "trend": trend,
            "generated_at": clock.now_iso(),
        }


    def _activity_trend(days: int = 7) -> list[dict[str, Any]]:
        """最近 N 天每天的提交量与登录量。"""
        result: list[dict[str, Any]] = []
        today = clock.utcnow()
        for offset in range(days - 1, -1, -1):
            day = clock.add_days(today, -offset)
            day_start = clock.to_iso(clock.start_of_day(day))
            day_end = clock.to_iso(clock.add_days(clock.start_of_day(day), 1))
            submissions = int(
                connection.scalar(
                    "SELECT COUNT(*) FROM submissions WHERE submitted_at >= ? AND submitted_at < ?",
                    (day_start, day_end),
                    default=0,
                )
                or 0
            )
            logins = int(
                connection.scalar(
                    "SELECT COUNT(*) FROM login_attempts WHERE success = 1 AND created_at >= ? AND created_at < ?",
                    (day_start, day_end),
                    default=0,
                )
                or 0
            )
            result.append(
                {
                    "date": day_start[:10],
                    "submissions": submissions,
                    "logins": logins,
                }
            )
        return result


    def course_overview(operator: dict[str, Any], course_id: int) -> dict[str, Any]:
        """单门课程的活跃度概览。"""
        permissions.require_teacher(operator)
        course = course_repo.find_or_fail(course_id, "课程不存在")
        permissions.assert_can_manage_course(operator, course)

        classes = class_repo.of_course(course_id)
        class_ids = [int(item["id"]) for item in classes]
        if not class_ids:
            return {"course": course, "classes": [], "totals": {"students": 0, "submissions": 0}}

        placeholders = ",".join("?" for _ in class_ids)
        students = int(
            connection.scalar(
                f"SELECT COUNT(*) FROM enrollments WHERE status = 'active' AND class_id IN ({placeholders})",
                tuple(class_ids),
                default=0,
            )
            or 0
        )
        submissions = int(
            connection.scalar(
                f"""SELECT COUNT(*) FROM submissions s
                     JOIN assignments a ON a.id = s.assignment_id
                    WHERE a.class_id IN ({placeholders})""",
                tuple(class_ids),
                default=0,
            )
            or 0
        )
        graded = int(
            connection.scalar(
                f"""SELECT COUNT(*) FROM submissions s
                     JOIN assignments a ON a.id = s.assignment_id
                    WHERE a.class_id IN ({placeholders}) AND s.status = 'graded'""",
                tuple(class_ids),
                default=0,
            )
            or 0
        )
        return {
            "course": course,
            "classes": classes,
            "totals": {
                "students": students,
                "submissions": submissions,
                "graded": graded,
                "grade_rate": round(graded / submissions * 100, 1) if submissions else 0.0,
            },
        }


    def student_report(student: dict[str, Any]) -> dict[str, Any]:
        """学生学习报告：待办、出勤、均分。"""
        permissions.require_role(student, permissions.ROLE_STUDENT)
        student_id = int(student["id"])
        pending = int(
            connection.scalar(
                """SELECT COUNT(*)
                     FROM assignments a
                     JOIN enrollments e ON e.class_id = a.class_id
                                       AND e.student_id = ? AND e.status = 'active'
                     LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
                    WHERE a.status = 'published' AND s.id IS NULL""",
                (student_id, student_id),
                default=0,
            )
            or 0
        )
        enrolled = int(
            connection.scalar(
                "SELECT COUNT(*) FROM enrollments WHERE student_id = ? AND status = 'active'",
                (student_id,),
                default=0,
            )
            or 0
        )
        attendance = connection.query_one(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present,
                      SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) AS late
                 FROM attendance_records WHERE student_id = ?""",
            (student_id,),
        ) or {}
        total = int(attendance.get("total") or 0)
        present = int(attendance.get("present") or 0)
        late = int(attendance.get("late") or 0)

        avg_score = connection.scalar(
            """SELECT AVG(score) FROM submissions
                WHERE student_id = ? AND score IS NOT NULL""",
            (student_id,),
        )
        return {
            "student": {
                "id": student_id,
                "real_name": student["real_name"],
                "number": student.get("number") or "",
            },
            "enrolled_classes": enrolled,
            "pending_assignments": pending,
            "attendance": {
                "total": total,
                "present": present,
                "late": late,
                "rate": round((present + late * 0.5) / total * 100, 1) if total else 0.0,
            },
            "average_score": round(float(avg_score), 2) if avg_score is not None else None,
            "generated_at": clock.now_iso(),
        }


    def teacher_dashboard(teacher: dict[str, Any]) -> dict[str, Any]:
        """教师首页汇总。"""
        permissions.require_teacher(teacher)
        classes = class_repo.of_teacher(int(teacher["id"]))
        class_ids = [int(item["id"]) for item in classes]
        if not class_ids:
            return {
                "classes": [],
                "totals": {"classes": 0, "students": 0, "pending": 0, "ungraded": 0},
            }
        placeholders = ",".join("?" for _ in class_ids)
        students = int(
            connection.scalar(
                f"SELECT COUNT(*) FROM enrollments WHERE status = 'active' AND class_id IN ({placeholders})",
                tuple(class_ids),
                default=0,
            )
            or 0
        )
        ungraded = int(
            connection.scalar(
                f"""SELECT COUNT(*) FROM submissions s
                     JOIN assignments a ON a.id = s.assignment_id
                    WHERE a.class_id IN ({placeholders}) AND s.status <> 'graded'""",
                tuple(class_ids),
                default=0,
            )
            or 0
        )
        upcoming = connection.query_all(
            f"""SELECT a.id, a.title, a.deadline, cl.name AS class_name
                  FROM assignments a
                  JOIN classes cl ON cl.id = a.class_id
                 WHERE a.class_id IN ({placeholders}) AND a.deadline > ?
                 ORDER BY a.deadline ASC LIMIT 5""",
            tuple(class_ids) + (clock.now_iso(),),
        )
        return {
            "classes": classes,
            "totals": {
                "classes": len(classes),
                "students": students,
                "pending": 0,
                "ungraded": ungraded,
            },
            "upcoming": upcoming,
            "generated_at": clock.now_iso(),
        }
    return SimpleNamespace(
        user_repo=user_repo,
        course_repo=course_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        audit_repo=audit_repo,
        admin_dashboard=admin_dashboard,
        course_overview=course_overview,
        student_report=student_report,
        teacher_dashboard=teacher_dashboard,
    )


# ======================================================================
# 模块：backend/http/request.py
# ======================================================================
def _mod_request_lib(MAX_BODY_BYTES, TooLargeError, ValidationError, safe_int):
    """HTTP 请求对象。

    把 http.server 的原始输入整理成好用的结构：
    路径参数、查询串、JSON 体、当前登录用户、客户端 IP。
    """


    import json
    from dataclasses import dataclass, field
    from typing import Any
    from urllib.parse import parse_qs, unquote, urlparse



    @dataclass
    class Request:
        method: str
        raw_path: str
        headers: dict[str, str]
        body: bytes
        client_ip: str = "127.0.0.1"
        # 路由匹配后填充
        path_params: dict[str, Any] = field(default_factory=dict)
        query: dict[str, str] = field(default_factory=dict)
        user: dict[str, Any] | None = None
        session_token: str | None = None
        # 业务侧可挂载的临时数据（如审计上下文）
        context: dict[str, Any] = field(default_factory=dict)

        def __post_init__(self) -> None:
            # 允许直接构造 Request（例如单测），此时手工补齐查询参数与头部小写化
            if not self.query and "?" in self.raw_path:
                self.query = parse_query(self.raw_path)
            if self.headers:
                self.headers = {str(k).lower(): str(v) for k, v in self.headers.items()}

        # -- 基础属性 ---------------------------------------------------------

        @property
        def path(self) -> str:
            return urlparse(self.raw_path).path.rstrip("/") or "/"

        def header(self, name: str, default: str = "") -> str:
            return self.headers.get(name.lower(), default)

        @property
        def bearer_token(self) -> str | None:
            auth = self.header("authorization")
            if not auth:
                return None
            parts = auth.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1].strip()
            return None

        @property
        def is_json(self) -> bool:
            content_type = self.header("content-type")
            return "application/json" in content_type.lower()

        # -- 参数 -------------------------------------------------------------

        def param(self, name: str, default: Any = None) -> Any:
            if name in self.path_params:
                return self.path_params[name]
            return self.query.get(name, default)

        def int_param(self, name: str, default: int = 0) -> int:
            value = self.param(name)
            if value is None or value == "":
                return default
            if isinstance(value, int):
                return value
            return safe_int(value, default)

        def str_param(self, name: str, default: str = "") -> str:
            value = self.param(name)
            if value is None:
                return default
            return str(value)

        def bool_param(self, name: str, default: bool = False) -> bool:
            value = self.param(name)
            if value is None:
                return default
            return str(value).lower() in {"1", "true", "yes", "on"}

        # -- 请求体 -----------------------------------------------------------

        def json(self) -> dict[str, Any]:
            if not self.body:
                return {}
            if len(self.body) > MAX_BODY_BYTES:
                raise TooLargeError("请求体过大")
            try:
                data = json.loads(self.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("请求体不是合法的 JSON") from exc
            if data is None:
                return {}
            if not isinstance(data, dict):
                raise ValidationError("请求体必须是 JSON 对象")
            return data

        def json_list(self) -> list[Any]:
            if not self.body:
                return []
            try:
                data = json.loads(self.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("请求体不是合法的 JSON") from exc
            if not isinstance(data, list):
                raise ValidationError("请求体必须是 JSON 数组")
            return data

        # -- 鉴权辅助 ---------------------------------------------------------

        def require_user(self) -> dict[str, Any]:
            if not self.user:
                from backend.core.errors import UnauthorizedError

                raise UnauthorizedError()
            return self.user

        def has_role(self, *roles: str) -> bool:
            return bool(self.user) and self.user.get("role") in roles

        def is_admin(self) -> bool:
            return self.has_role("admin")

        def is_teacher(self) -> bool:
            return self.has_role("teacher", "admin")

        @property
        def user_id(self) -> int:
            return int(self.user["id"]) if self.user else 0


    def parse_query(raw_path: str) -> dict[str, str]:
        """取查询串里每个键的第一个值。"""
        parsed = urlparse(raw_path)
        result: dict[str, str] = {}
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
            result[key] = values[0] if values else ""
        return result


    def parse_headers(items: list[tuple[str, str]]) -> dict[str, str]:
        return {key.lower(): value for key, value in items}


    def build_request(method: str, raw_path: str, headers: list[tuple[str, str]],
                      body: bytes, client_ip: str) -> Request:
        header_map = parse_headers(headers)
        return Request(
            method=method.upper(),
            raw_path=raw_path,
            headers=header_map,
            body=body,
            client_ip=client_ip,
            query=parse_query(raw_path),
        )


    def decode_path_segment(segment: str) -> str:
        return unquote(segment)
    return SimpleNamespace(
        Request=Request,
        parse_query=parse_query,
        parse_headers=parse_headers,
        build_request=build_request,
        decode_path_segment=decode_path_segment,
    )


# ======================================================================
# 模块：backend/http/router.py
# ======================================================================
def _mod_router_lib(MethodNotAllowedError, NotFoundError, Request, Response):
    """最小的 HTTP 路由表。

    支持 /api/courses/<int:course_id>/assignments/<int:aid> 这类路径参数，
    不依赖任何三方框架，编译成正则后匹配，性能足够。
    """


    import re
    from dataclasses import dataclass, field
    from typing import Any, Callable


    Handler = Callable[[Request], Response]

    _PARAM_RE = re.compile(r"<(?P<type>int|str|path):(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>")
    _CONVERTERS: dict[str, str] = {
        "int": r"(?P<%s>\d+)",
        "str": r"(?P<%s>[^/]+)",
        "path": r"(?P<%s>.+)",
    }


    @dataclass
    class Route:
        method: str
        pattern: str
        regex: re.Pattern[str]
        handler: Handler
        auth: bool = True
        roles: tuple[str, ...] = ()
        name: str = ""
        summary: str = ""
        param_types: dict[str, str] = field(default_factory=dict)

        def match(self, path: str) -> dict[str, Any] | None:
            matched = self.regex.fullmatch(path)
            if not matched:
                return None
            params: dict[str, Any] = {}
            for key, raw in matched.groupdict().items():
                if self.param_types.get(key) == "int":
                    params[key] = int(raw)
                else:
                    params[key] = raw
            return params


    class Router:
        def __init__(self) -> None:
            self._routes: list[Route] = []
            self._by_method: dict[str, list[Route]] = {}

        # -- 注册 -------------------------------------------------------------

        def add(
            self,
            method: str,
            pattern: str,
            handler: Handler,
            *,
            auth: bool = True,
            roles: tuple[str, ...] = (),
            name: str = "",
            summary: str = "",
        ) -> Route:
            regex, param_types = self._compile(pattern)
            route = Route(
                method=method.upper(),
                pattern=pattern,
                regex=regex,
                handler=handler,
                auth=auth,
                roles=roles,
                name=name or handler.__name__,
                summary=summary,
                param_types=param_types,
            )
            self._routes.append(route)
            self._by_method.setdefault(route.method, []).append(route)
            return route

        def _compile(self, pattern: str) -> tuple[re.Pattern[str], dict[str, str]]:
            param_types: dict[str, str] = {}

            def replace(match: re.Match[str]) -> str:
                kind = match.group("type")
                name = match.group("name")
                param_types[name] = kind
                return _CONVERTERS[kind] % name

            regex_text = _PARAM_RE.sub(replace, pattern)
            return re.compile(regex_text), param_types

        # -- 便捷装饰器 -------------------------------------------------------

        def get(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
            return self._decorator("GET", pattern, **kwargs)

        def post(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
            return self._decorator("POST", pattern, **kwargs)

        def put(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
            return self._decorator("PUT", pattern, **kwargs)

        def patch(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
            return self._decorator("PATCH", pattern, **kwargs)

        def delete(self, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
            return self._decorator("DELETE", pattern, **kwargs)

        def _decorator(self, method: str, pattern: str, **kwargs: Any) -> Callable[[Handler], Handler]:
            def wrapper(handler: Handler) -> Handler:
                self.add(method, pattern, handler, **kwargs)
                return handler

            return wrapper

        def include(self, other: "Router") -> None:
            """把另一个路由表合并进来。"""
            for route in other._routes:
                self._routes.append(route)
                self._by_method.setdefault(route.method, []).append(route)

        # -- 匹配 -------------------------------------------------------------

        def resolve(self, method: str, path: str) -> tuple[Route, dict[str, Any]]:
            candidates = self._by_method.get(method.upper(), [])
            for route in candidates:
                params = route.match(path)
                if params is not None:
                    return route, params
            # 路径存在但方法不对 -> 405
            for routes in self._by_method.values():
                for route in routes:
                    if route.match(path) is not None:
                        raise MethodNotAllowedError(
                            f"{path} 不支持 {method} 方法",
                            details={"allow": self.allowed_methods(path)},
                        )
            raise NotFoundError(f"接口不存在：{path}")

        def allowed_methods(self, path: str) -> list[str]:
            methods = []
            for routes in self._by_method.values():
                for route in routes:
                    if route.match(path) is not None:
                        methods.append(route.method)
                        break
            # 静态资源与预检请求
            methods.extend(["OPTIONS"])
            return sorted(set(methods))

        # -- 元信息 -----------------------------------------------------------

        @property
        def routes(self) -> list[Route]:
            return list(self._routes)

        def describe(self) -> list[dict[str, Any]]:
            """给前端「接口文档」页面用的路由清单。"""
            return [
                {
                    "method": route.method,
                    "pattern": route.pattern,
                    "name": route.name,
                    "auth": route.auth,
                    "roles": list(route.roles),
                    "summary": route.summary,
                }
                for route in self._routes
            ]
    return SimpleNamespace(
        Handler=Handler,
        Route=Route,
        Router=Router,
    )


# ======================================================================
# 模块：backend/http/multipart.py
# ======================================================================
def _mod_multipart_lib(ValidationError):
    """极简 multipart/form-data 解析器。

    只支持本应用需要的场景：
    - 一个或多个文本字段
    - 一个或零个文件字段
    不处理嵌套、不处理 quoted-printable，够用且代码可控。
    """


    import re
    from dataclasses import dataclass, field
    from typing import Any


    _BOUNDARY_RE = re.compile(r'boundary="?([^";]+)"?', re.IGNORECASE)


    @dataclass
    class UploadedFile:
        field_name: str
        filename: str
        content_type: str
        data: bytes

        @property
        def size(self) -> int:
            return len(self.data)


    @dataclass
    class MultipartForm:
        fields: dict[str, str] = field(default_factory=dict)
        files: dict[str, UploadedFile] = field(default_factory=dict)

        def get(self, name: str, default: str = "") -> str:
            return self.fields.get(name, default)

        def file(self, name: str) -> UploadedFile | None:
            return self.files.get(name)

        def first_file(self) -> UploadedFile | None:
            return next(iter(self.files.values()), None)


    def is_multipart(content_type: str) -> bool:
        return "multipart/form-data" in (content_type or "").lower()


    def parse_multipart(body: bytes, content_type: str) -> MultipartForm:
        matched = _BOUNDARY_RE.search(content_type or "")
        if not matched:
            raise ValidationError("multipart 请求缺少 boundary")
        boundary = matched.group(1).encode("utf-8")
        delimiter = b"--" + boundary

        form = MultipartForm()
        parts = body.split(delimiter)
        for part in parts:
            if not part or part in (b"--\r\n", b"--", b"\r\n"):
                continue
            part = part.strip(b"\r\n")
            if not part or part == b"--":
                continue
            if b"\r\n\r\n" not in part:
                continue
            raw_headers, content = part.split(b"\r\n\r\n", 1)
            if content.endswith(b"\r\n"):
                content = content[:-2]
            headers = _parse_part_headers(raw_headers)
            disposition = headers.get("content-disposition", "")
            name_match = re.search(r'name="([^"]*)"', disposition)
            if not name_match:
                continue
            name = name_match.group(1)
            filename_match = re.search(r'filename="([^"]*)"', disposition)
            if filename_match:
                form.files[name] = UploadedFile(
                    field_name=name,
                    filename=filename_match.group(1),
                    content_type=headers.get("content-type", "application/octet-stream"),
                    data=content,
                )
            else:
                form.fields[name] = content.decode("utf-8", errors="replace")
        return form


    def _parse_part_headers(raw: bytes) -> dict[str, str]:
        headers: dict[str, str] = {}
        for line in raw.split(b"\r\n"):
            if b":" not in line:
                continue
            key, value = line.split(b":", 1)
            headers[key.decode("latin-1").strip().lower()] = value.decode("latin-1").strip()
        return headers


    def form_to_dict(form: MultipartForm) -> dict[str, Any]:
        payload: dict[str, Any] = dict(form.fields)
        if form.files:
            payload["_files"] = {name: file for name, file in form.files.items()}
        return payload
    return SimpleNamespace(
        UploadedFile=UploadedFile,
        MultipartForm=MultipartForm,
        is_multipart=is_multipart,
        parse_multipart=parse_multipart,
        form_to_dict=form_to_dict,
    )


# ======================================================================
# 模块：backend/http/server.py
# ======================================================================
def _mod_server_lib(AppError, Request, Response, TooLargeError, build_request, config, error_response, json_response):
    """内置 HTTP 服务器。

    用标准库的 ThreadingHTTPServer 承载，够轻量，且不引入第三方依赖。
    职责很纯粹：收请求 -> 交给 dispatch -> 把 Response 写回去。
    业务逻辑全部在 router / api / services 里。
    """


    import json
    import logging
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from typing import Callable


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
    return SimpleNamespace(
        logger=logger,
        Dispatch=Dispatch,
        HttpServer=HttpServer,
        read_json_body=read_json_body,
    )


# ======================================================================
# 模块：backend/db/seed.py
# ======================================================================
def _mod_seed_lib(AssignmentRepository, AttemptRepository, AttendanceRecordRepository, AttendanceSessionRepository, ChapterRepository, ClassRepository, CourseRepository, DiscussionRepository, EnrollmentRepository, GradeItemRepository, GradeRuleRepository, NotificationRepository, QuestionRepository, QuizRepository, ReplyRepository, ResourceRepository, SettingRepository, SubmissionRepository, TaskProgressRepository, TaskRepository, UserRepository, clock, config, connection, ids, migrations, security):
    """演示数据初始化。

    生成一套完整可演示的数据：管理员、教师、学生、课程、教学班、
    作业与提交、测验与答卷、签到与记录、讨论、通知、成绩。

    执行：python -m backend.cli seed
    幂等：检测到 admin 账号已存在时直接跳过，不会重复灌数据。
    """


    import json
    import random
    from typing import Any


    user_repo = UserRepository()
    course_repo = CourseRepository()
    class_repo = ClassRepository()
    enroll_repo = EnrollmentRepository()
    assignment_repo = AssignmentRepository()
    submission_repo = SubmissionRepository()
    quiz_repo = QuizRepository()
    question_repo = QuestionRepository()
    attempt_repo = AttemptRepository()
    session_repo = AttendanceSessionRepository()
    record_repo = AttendanceRecordRepository()
    resource_repo = ResourceRepository()
    discussion_repo = DiscussionRepository()
    reply_repo = ReplyRepository()
    notification_repo = NotificationRepository()
    rule_repo = GradeRuleRepository()
    item_repo = GradeItemRepository()
    chapter_repo = ChapterRepository()
    task_repo = TaskRepository()
    progress_repo = TaskProgressRepository()
    setting_repo = SettingRepository()

    DEFAULT_PASSWORD = "Eduflow@2026"

    TEACHERS = [
        ("t1001", "张伟", "计算机学院", "教授"),
        ("t1002", "李娜", "数学学院", "副教授"),
        ("t1003", "王强", "外国语学院", "讲师"),
    ]

    STUDENTS = [
        ("s2001", "陈晓", "计算机学院", "计科2301"),
        ("s2002", "刘洋", "计算机学院", "计科2301"),
        ("s2003", "赵敏", "计算机学院", "计科2302"),
        ("s2004", "孙浩", "计算机学院", "计科2302"),
        ("s2005", "周婷", "数学学院", "数学2301"),
        ("s2006", "吴磊", "数学学院", "数学2301"),
        ("s2007", "郑爽", "外国语学院", "英语2301"),
        ("s2008", "冯佳", "外国语学院", "英语2301"),
        ("s2009", "陆明", "计算机学院", "计科2301"),
        ("s2010", "何雨", "计算机学院", "计科2302"),
        ("s2011", "许静", "数学学院", "数学2301"),
        ("s2012", "邓超", "外国语学院", "英语2301"),
    ]

    COURSES = [
        {
            "code": "CS101",
            "name": "数据结构与算法",
            "teacher": "t1001",
            "term": "2026-2027-1",
            "credits": 4,
            "hours": 64,
            "category": "必修",
            "description": "线性表、树、图、排序与查找，配套上机实验。",
        },
        {
            "code": "CS205",
            "name": "操作系统原理",
            "teacher": "t1001",
            "term": "2026-2027-1",
            "credits": 3,
            "hours": 48,
            "category": "必修",
            "description": "进程、内存、文件系统与并发控制。",
        },
        {
            "code": "MA102",
            "name": "高等数学（下）",
            "teacher": "t1002",
            "term": "2026-2027-1",
            "credits": 5,
            "hours": 80,
            "category": "必修",
            "description": "多元函数微积分、级数与常微分方程。",
        },
    ]

    ASSIGNMENT_TEMPLATES = [
        ("第一次上机：顺序表实现", "用 C/C++ 实现顺序表的增删改查，提交源码与测试截图。", 7),
        ("第二次上机：二叉树遍历", "实现二叉树的先序、中序、后序遍历，并给出复杂度分析。", 10),
        ("课程小论文：算法复杂度思考", "结合一个真实问题，谈谈你对时间复杂度的理解，不少于 800 字。", 14),
    ]

    QUIZ_QUESTIONS = [
        {
            "type": "single",
            "stem": "顺序表插入元素平均需要移动多少个元素？",
            "options": ["n", "n/2", "1", "log n"],
            "answer": "B",
            "score": 10,
            "analysis": "平均移动 n/2 个元素。",
        },
        {
            "type": "multi",
            "stem": "下列哪些属于线性结构？",
            "options": ["栈", "队列", "二叉树", " linked list"],
            "answer": "A,B,D",
            "score": 10,
            "analysis": "二叉树属于树形结构。",
        },
        {
            "type": "judge",
            "stem": "快速排序在最坏情况下的时间复杂度是 O(n log n)。",
            "options": [],
            "answer": "错",
            "score": 10,
            "analysis": "最坏是 O(n^2)。",
        },
        {
            "type": "fill",
            "stem": "二分查找要求数据必须______。",
            "options": [],
            "answer": "有序|排好序",
            "score": 10,
            "analysis": "必须有序。",
        },
        {
            "type": "essay",
            "stem": "简述哈希表的冲突解决方法。",
            "options": [],
            "answer": "",
            "score": 20,
            "analysis": "开放定址法、链地址法等。",
        },
    ]


    def is_seeded() -> bool:
        return user_repo.by_username("admin") is not None


    # ---------------------------------------------------------------------------
    # 章节任务点与学习进度（对已有演示库同样可补，幂等）
    # ---------------------------------------------------------------------------


    def _add_chapter(course_id: int, title: str, description: str,
                     order_no: int) -> int:
        return chapter_repo.insert(
            {
                "course_id": course_id,
                "title": title,
                "description": description,
                "order_no": order_no,
            }
        )


    def _add_task(chapter_id: int, task_type: str, title: str, *,
                  description: str = "", duration: int = 30, required: int = 1,
                  resource_id: int | None = None, quiz_id: int | None = None,
                  assignment_id: int | None = None) -> int:
        return task_repo.insert(
            {
                "chapter_id": chapter_id,
                "type": task_type,
                "title": title,
                "description": description,
                "duration": duration,
                "required": required,
                "resource_id": resource_id,
                "quiz_id": quiz_id,
                "assignment_id": assignment_id,
                "order_no": task_repo.next_order_no(chapter_id),
            }
        )


    def ensure_chapters() -> dict[str, Any]:
        """给 CS101 建一套演示章节；已有章节或已初始化过时直接跳过。"""
        if setting_repo.get("chapters_seeded") == "1":
            return {"skipped": True, "reason": "章节演示数据已初始化"}
        if chapter_repo.count() > 0:
            setting_repo.set("chapters_seeded", "1")
            return {"skipped": True, "reason": "已存在章节数据"}

        course = course_repo.find_by(code="CS101")
        teacher = user_repo.by_username("t1001")
        if not course or not teacher:
            return {"skipped": True, "reason": "缺少 CS101 演示课程或教师"}

        course_id = int(course["id"])
        teacher_id = int(teacher["id"])
        classes = class_repo.of_course(course_id)
        if not classes:
            return {"skipped": True, "reason": "CS101 还没有教学班"}

        class_id = int(classes[0]["id"])
        resource = resource_repo.find_by(course_id=course_id, title="课程大纲")
        quiz = quiz_repo.find_by(class_id=class_id)
        discussion = discussion_repo.find_by(course_id=course_id)
        assignments = sorted(
            assignment_repo.list_by_class(class_id, limit=10), key=lambda row: int(row["id"])
        )

        chapter_one = _add_chapter(
            course_id, "第 1 章 绪论与算法分析", "课程导学、算法复杂度与学习要求。", 1
        )
        task_ids: dict[str, int] = {}
        task_ids["syllabus"] = _add_task(
            chapter_one, "material", "阅读《课程大纲》",
            description="了解考核方式、教材与实验安排。", duration=20,
            resource_id=int(resource["id"]) if resource else None,
        )
        task_ids["guide"] = _add_task(
            chapter_one, "text", "课程导学：如何学好数据结构",
            description="先修知识、学习路线与常见误区。", duration=15,
        )

        chapter_two = _add_chapter(
            course_id, "第 2 章 线性表", "顺序表、链表与相关操作的复杂度分析。", 2
        )
        task_ids["linear"] = _add_task(
            chapter_two, "text", "线性表重点梳理",
            description="顺序表与链表的插入、删除、查找对比。", duration=40,
        )
        if quiz:
            task_ids["quiz"] = _add_task(
                chapter_two, "quiz", "第一章随堂测验",
                description="限时 30 分钟，检验线性表掌握情况。", duration=30,
                quiz_id=int(quiz["id"]),
            )
        if discussion:
            task_ids["discussion"] = _add_task(
                chapter_two, "discussion", "参与讨论：复杂度疑问",
                description="在讨论区提出或回答一个复杂度相关的问题。", duration=10,
            )

        chapter_three = _add_chapter(
            course_id, "第 3 章 树与二叉树", "二叉树遍历、递归与典型应用。", 3
        )
        for index, assignment in enumerate(assignments[:2]):
            task_ids[f"assignment_{index}"] = _add_task(
                chapter_three,
                "assignment",
                assignment["title"],
                description="按作业要求提交源码与实验报告。",
                duration=90,
                assignment_id=int(assignment["id"]),
            )

        # 给前几位学生造一些学习痕迹，让进度条不是空的
        students = chapter_repo.students_of_course(course_id)
        now = clock.utcnow()
        plan = [
            (0, "syllabus", "completed", 100, 9),
            (0, "guide", "completed", 100, 9),
            (0, "linear", "completed", 100, 7),
            (0, "quiz", "in_progress", 40, 2),
            (0, "discussion", "completed", 100, 6),
            (1, "syllabus", "completed", 100, 8),
            (1, "guide", "completed", 100, 8),
            (1, "linear", "in_progress", 60, 3),
            (2, "syllabus", "completed", 100, 10),
            (2, "guide", "completed", 100, 10),
            (2, "linear", "completed", 100, 9),
            (2, "quiz", "completed", 100, 5),
            (2, "discussion", "completed", 100, 8),
            (3, "syllabus", "completed", 100, 6),
            (4, "syllabus", "completed", 100, 4),
            (4, "guide", "completed", 100, 4),
        ]
        progress_count = 0
        for student_index, key, status, progress, days_ago in plan:
            if student_index >= len(students) or key not in task_ids:
                continue
            student_id = int(students[student_index]["student_id"])
            started = clock.to_iso(clock.add_days(now, -days_ago))
            progress_repo.insert(
                {
                    "task_id": task_ids[key],
                    "student_id": student_id,
                    "status": status,
                    "progress": progress,
                    "started_at": started,
                    "finished_at": started if status == "completed" else None,
                }
            )
            progress_count += 1

        setting_repo.set("chapters_seeded", "1")
        return {
            "skipped": False,
            "chapters": 3,
            "tasks": len(task_ids),
            "progress": progress_count,
        }


    def seed(force: bool = False) -> dict[str, Any]:
        migrations.init_db()
        if is_seeded() and not force:
            return {
                "skipped": True,
                "reason": "已存在演示数据",
                "chapters": ensure_chapters(),
            }

        if force:
            migrations.reset_db()

        created: dict[str, int] = {}

        # ---------------------------------------------------------------- 用户
        admin_digest, admin_salt = security.hash_password(DEFAULT_PASSWORD)
        admin_id = user_repo.insert(
            {
                "username": "admin",
                "password_hash": admin_digest,
                "password_salt": admin_salt,
                "role": "admin",
                "real_name": "系统管理员",
                "number": "0001",
                "email": "admin@eduflow.local",
                "department": "教务处",
                "status": "active",
            }
        )
        created["admin"] = admin_id

        teacher_ids: dict[str, int] = {}
        for username, name, dept, title in TEACHERS:
            digest, salt = security.hash_password(DEFAULT_PASSWORD)
            teacher_ids[username] = user_repo.insert(
                {
                    "username": username,
                    "password_hash": digest,
                    "password_salt": salt,
                    "role": "teacher",
                    "real_name": name,
                    "number": username.upper(),
                    "email": f"{username}@eduflow.local",
                    "department": dept,
                    "phone": f"1380000{random.randint(1000, 9999)}",
                    "status": "active",
                }
            )
        created["teachers"] = len(teacher_ids)

        student_ids: list[int] = []
        for username, name, dept, clazz in STUDENTS:
            digest, salt = security.hash_password(DEFAULT_PASSWORD)
            student_ids.append(
                user_repo.insert(
                    {
                        "username": username,
                        "password_hash": digest,
                        "password_salt": salt,
                        "role": "student",
                        "real_name": name,
                        "number": username.upper(),
                        "email": f"{username}@eduflow.local",
                        "department": dept,
                        "class_name": clazz,
                        "status": "active",
                    }
                )
            )
        created["students"] = len(student_ids)

        # ---------------------------------------------------------------- 课程
        course_ids: list[int] = []
        class_ids: list[int] = []
        for index, item in enumerate(COURSES):
            teacher_id = teacher_ids[item["teacher"]]
            course_id = course_repo.insert(
                {
                    "code": item["code"],
                    "name": item["name"],
                    "teacher_id": teacher_id,
                    "term": item["term"],
                    "credits": item["credits"],
                    "hours": item["hours"],
                    "category": item["category"],
                    "description": item["description"],
                    "status": "active",
                }
            )
            course_ids.append(course_id)
            class_id = class_repo.insert(
                {
                    "course_id": course_id,
                    "name": f"{item['name']}-01班",
                    "join_code": ids.new_join_code(),
                    "semester": item["term"],
                    "location": f"教学楼 A{index + 2}0{index + 1}",
                    "schedule": "周一 3-4 节、周三 5-6 节",
                    "capacity": 60,
                }
            )
            class_ids.append(class_id)
            if index == 0:
                second = class_repo.insert(
                    {
                        "course_id": course_id,
                        "name": f"{item['name']}-02班",
                        "join_code": ids.new_join_code(),
                        "semester": item["term"],
                        "location": "教学楼 A301",
                        "schedule": "周二 1-2 节",
                        "capacity": 60,
                    }
                )
                class_ids.append(second)
        created["courses"] = len(course_ids)
        created["classes"] = len(class_ids)

        # ---------------------------------------------------------------- 选课
        enroll_count = 0
        for index, class_id in enumerate(class_ids):
            for student_id in student_ids:
                # 第一个教学班全员选课，保证演示数据里作业/成绩/签到都有足够样本
                if index == 0 or random.random() < 0.55:
                    enroll_repo.enroll(class_id, student_id, source="import")
                    enroll_count += 1
        created["enrollments"] = enroll_count

        # ---------------------------------------------------------------- 作业
        assignment_ids: list[int] = []
        now = clock.utcnow()
        for order, (title, content, days) in enumerate(ASSIGNMENT_TEMPLATES):
            class_id = class_ids[0]
            deadline = clock.to_iso(clock.add_days(now, days - 3))
            assignment_id = assignment_repo.insert(
                {
                    "class_id": class_id,
                    "title": title,
                    "content": content,
                    "full_score": 100,
                    "deadline": deadline,
                    "allow_late": 1,
                    "late_penalty": 0.1,
                    "status": "published",
                    "created_by": teacher_ids["t1001"],
                }
            )
            assignment_ids.append(assignment_id)

        # 提交与批改
        submitted = graded = 0
        for assignment_id in assignment_ids[:2]:
            for student_id in student_ids:
                if not enroll_repo.is_enrolled(class_ids[0], student_id):
                    continue
                if random.random() > 0.75:
                    continue
                submission_id = submission_repo.insert(
                    {
                        "assignment_id": assignment_id,
                        "student_id": student_id,
                        "content": "老师好，这是我的作业，详见附件。",
                        "status": "submitted",
                        "submitted_at": clock.to_iso(clock.add_days(now, -random.randint(1, 3))),
                    }
                )
                submitted += 1
                if random.random() < 0.7:
                    submission_repo.grade(
                        submission_id,
                        round(random.uniform(65, 98), 1),
                        random.choice(["完成得不错", "思路清晰，注意边界条件", "代码规范有待加强"]),
                        teacher_ids["t1001"],
                    )
                    graded += 1
        created["submissions"] = submitted
        created["graded"] = graded

        # ---------------------------------------------------------------- 测验
        quiz_id = quiz_repo.insert(
            {
                "class_id": class_ids[0],
                "title": "第一章 线性表 随堂测验",
                "description": "限时 30 分钟，共 5 题。",
                "start_at": clock.to_iso(clock.add_days(now, -2)),
                "end_at": clock.to_iso(clock.add_days(now, 20)),
                "duration": 30,
                "total_score": 60,
                "shuffle": 0,
                "show_answer": 1,
                "status": "published",
                "created_by": teacher_ids["t1001"],
            }
        )
        questions = []
        for index, item in enumerate(QUIZ_QUESTIONS):
            questions.append(
                {
                    "type": item["type"],
                    "stem": item["stem"],
                    "options": json.dumps(item["options"], ensure_ascii=False) if item["options"] else None,
                    "answer": item["answer"],
                    "analysis": item["analysis"],
                    "score": item["score"],
                    "order_no": index,
                }
            )
        question_repo.replace_for_quiz(quiz_id, questions)

        attempt_count = 0
        for student_id in student_ids:
            if not enroll_repo.is_enrolled(class_ids[0], student_id):
                continue
            if random.random() > 0.6:
                continue
            attempt_id = attempt_repo.start(quiz_id, student_id)
            score = round(random.uniform(20, 58), 1)
            attempt_repo.submit(attempt_id, score, json.dumps({}))
            attempt_count += 1
        created["quiz_attempts"] = attempt_count

        # ---------------------------------------------------------------- 签到
        att_count = 0
        for offset in range(3):
            start = clock.add_days(now, -7 * (offset + 1))
            session_id = session_repo.insert(
                {
                    "class_id": class_ids[0],
                    "title": f"第{3 - offset}周 课堂签到",
                    "method": "code",
                    "code": ids.new_attendance_code(),
                    "start_at": clock.to_iso(start),
                    "end_at": clock.to_iso(clock.add_minutes(start, 10)),
                    "status": "closed",
                    "created_by": teacher_ids["t1001"],
                }
            )
            for student_id in student_ids:
                if not enroll_repo.is_enrolled(class_ids[0], student_id):
                    continue
                status = random.choices(
                    ["present", "late", "absent", "leave"], weights=[80, 10, 7, 3]
                )[0]
                record_repo.mark(session_id, student_id, status, "")
                att_count += 1
        created["attendance_records"] = att_count

        # ---------------------------------------------------------------- 资料
        # 真实落一个文件，保证「下载」按钮可用（而不是 0 字节的死链）
        syllabus_text = (
            "数据结构与算法 课程大纲\n"
            "========================\n\n"
            "课程代码：CS101    学分：4    学时：64\n"
            "授课教师：张伟\n\n"
            "一、课程简介\n"
            "本课程系统讲解线性表、栈与队列、树与二叉树、图、查找与排序等经典数据结构，\n"
            "并结合上机实验训练算法实现与复杂度分析能力。\n\n"
            "二、考核方式\n"
            "作业 30% + 测验 30% + 出勤 20% + 期末 20%\n\n"
            "三、参考教材\n"
            "《数据结构（C 语言版）》严蔚敏\n"
            "《算法导论》Cormen 等\n"
        )
        stored_name = "seed_syllabus_cs101.txt"
        upload_target = config.UPLOAD_DIR / stored_name
        upload_target.parent.mkdir(parents=True, exist_ok=True)
        upload_target.write_text(syllabus_text, encoding="utf-8")
        resource_repo.insert(
            {
                "course_id": course_ids[0],
                "title": "课程大纲",
                "description": "本学期的教学安排与考核方式",
                "filename": "数据结构与算法-课程大纲.txt",
                "stored_name": stored_name,
                "size": len(syllabus_text.encode("utf-8")),
                "mime": "text/plain",
                "category": "参考资料",
                "uploader_id": teacher_ids["t1001"],
            }
        )
        created["resources"] = 1

        # ---------------------------------------------------------------- 讨论
        discussion_id = discussion_repo.insert(
            {
                "course_id": course_ids[0],
                "title": "关于第二次上机的疑问",
                "content": "二叉树的非递归遍历该怎么写？有大佬能讲讲思路吗？",
                "author_id": student_ids[0],
                "pinned": 1,
            }
        )
        reply_repo.insert(
            {
                "discussion_id": discussion_id,
                "author_id": teacher_ids["t1001"],
                "content": "核心是用栈模拟递归调用，先压左孩子，回溯时再访问根节点。",
            }
        )
        created["discussions"] = 1

        # ---------------------------------------------------------------- 成绩
        for class_id in class_ids[:1]:
            rule_repo.save(
                class_id,
                {
                    "assignment_weight": 0.30,
                    "quiz_weight": 0.30,
                    "attendance_weight": 0.20,
                    "final_weight": 0.20,
                    "pass_score": 60,
                },
            )
            for student_id in student_ids:
                if not enroll_repo.is_enrolled(class_id, student_id):
                    continue
                item_repo.upsert(
                    class_id,
                    student_id,
                    {
                        "final_score": round(random.uniform(55, 95), 1),
                        "bonus": 0,
                        "remark": "",
                    },
                )

        # ---------------------------------------------------------------- 通知
        for user_id in [admin_id] + list(teacher_ids.values()) + student_ids[:5]:
            notification_repo.create(
                user_id,
                "欢迎使用 EduFlow",
                "这是演示数据，你可以自由新增课程、作业与测验。",
                category="system",
            )
        created["notifications"] = 6

        chapter_stats = ensure_chapters()
        created["chapters"] = chapter_stats.get("chapters", 0)
        created["tasks"] = chapter_stats.get("tasks", 0)
        created["task_progress"] = chapter_stats.get("progress", 0)

        connection.get_connection().execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"skipped": False, "created": created, "password": DEFAULT_PASSWORD}


    def summary() -> dict[str, int]:
        return {
            "users": int(connection.scalar("SELECT COUNT(*) FROM users", default=0) or 0),
            "courses": int(connection.scalar("SELECT COUNT(*) FROM courses", default=0) or 0),
            "classes": int(connection.scalar("SELECT COUNT(*) FROM classes", default=0) or 0),
            "assignments": int(connection.scalar("SELECT COUNT(*) FROM assignments", default=0) or 0),
            "submissions": int(connection.scalar("SELECT COUNT(*) FROM submissions", default=0) or 0),
            "quizzes": int(connection.scalar("SELECT COUNT(*) FROM quizzes", default=0) or 0),
            "attendance": int(connection.scalar("SELECT COUNT(*) FROM attendance_records", default=0) or 0),
            "chapters": int(connection.scalar("SELECT COUNT(*) FROM chapters", default=0) or 0),
            "tasks": int(connection.scalar("SELECT COUNT(*) FROM tasks", default=0) or 0),
            "task_progress": int(connection.scalar("SELECT COUNT(*) FROM task_progress", default=0) or 0),
        }
    return SimpleNamespace(
        user_repo=user_repo,
        course_repo=course_repo,
        class_repo=class_repo,
        enroll_repo=enroll_repo,
        assignment_repo=assignment_repo,
        submission_repo=submission_repo,
        quiz_repo=quiz_repo,
        question_repo=question_repo,
        attempt_repo=attempt_repo,
        session_repo=session_repo,
        record_repo=record_repo,
        resource_repo=resource_repo,
        discussion_repo=discussion_repo,
        reply_repo=reply_repo,
        notification_repo=notification_repo,
        rule_repo=rule_repo,
        item_repo=item_repo,
        chapter_repo=chapter_repo,
        task_repo=task_repo,
        progress_repo=progress_repo,
        setting_repo=setting_repo,
        DEFAULT_PASSWORD=DEFAULT_PASSWORD,
        TEACHERS=TEACHERS,
        STUDENTS=STUDENTS,
        COURSES=COURSES,
        ASSIGNMENT_TEMPLATES=ASSIGNMENT_TEMPLATES,
        QUIZ_QUESTIONS=QUIZ_QUESTIONS,
        is_seeded=is_seeded,
        ensure_chapters=ensure_chapters,
        seed=seed,
        summary=summary,
    )


# ======================================================================
# 模块：backend/api/auth_routes.py
# ======================================================================
def _mod_auth_api(Response, Router, auth_service, ok, permissions, validators):
    """认证相关接口。"""



    router = Router()


    @router.post("/api/auth/login", auth=False, summary="账号密码登录")
    def login(req) -> Response:
        payload = req.json()
        username = validators.required_str(payload, "username", max_len=64)
        password = validators.required_str(payload, "password", max_len=128, strip=False)
        data = auth_service.login(
            username,
            password,
            ip=req.client_ip,
            user_agent=req.header("user-agent"),
        )
        return ok(data, "登录成功")


    @router.post("/api/auth/logout", summary="退出登录")
    def logout(req) -> Response:
        auth_service.logout(req.session_token)
        return ok(None, "已退出登录")


    @router.get("/api/auth/me", summary="获取当前登录用户")
    def me(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(auth_service.to_public(user))


    @router.post("/api/auth/password", summary="修改自己的密码")
    def change_password(req) -> Response:
        user = permissions.require_login(req.user)
        payload = req.json()
        old = validators.required_str(payload, "old_password", max_len=128, strip=False)
        new = validators.required_str(payload, "new_password", min_len=6, max_len=128, strip=False)
        auth_service.change_password(int(user["id"]), old, new)
        return ok(None, "密码修改成功，请重新登录")


    @router.get("/api/auth/sessions", summary="查看在线会话")
    def sessions(req) -> Response:
        user = permissions.require_login(req.user)
        from backend.repositories.users import SessionRepository

        return ok(SessionRepository().active_sessions(int(user["id"])))


    @router.post("/api/auth/password/strength", auth=False, summary="密码强度评估")
    def strength(req) -> Response:
        payload = req.json()
        password = validators.required_str(payload, "password", max_len=128, strip=False)
        from backend.core.security import password_strength

        return ok(password_strength(password))
    return SimpleNamespace(
        router=router,
        login=login,
        logout=logout,
        me=me,
        change_password=change_password,
        sessions=sessions,
        strength=strength,
    )


# ======================================================================
# 模块：backend/api/user_routes.py
# ======================================================================
def _mod_user_api(CourseRepository, Response, Router, created, ok, paginated, permissions, user_service, validators):
    """用户管理接口（管理员为主）。"""



    router = Router()


    @router.get("/api/users", roles=("admin",), summary="用户列表")
    def list_users(req) -> Response:
        permissions.require_admin(req.user)
        role = req.str_param("role")
        keyword = req.str_param("keyword")
        page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
        items, total = user_service.list_users(
            role=role, keyword=keyword, page=page, page_size=page_size
        )
        return paginated(items, total, page, page_size)


    @router.post("/api/users", roles=("admin",), summary="新建用户")
    def create_user(req) -> Response:
        user = permissions.require_admin(req.user)
        data = user_service.create_user(req.json(), operator=user)
        return created(data, "用户创建成功")


    @router.get("/api/users/options", summary="教师与院系选项")
    def options(req) -> Response:
        permissions.require_login(req.user)
        teachers = CourseRepository().teacher_names()
        return ok(
            {
                "teachers": [
                    {"id": int(row["id"]), "name": row["real_name"]} for row in teachers
                ],
                "departments": user_service.department_options(),
                "roles": [
                    {"value": key, "label": label}
                    for key, label in permissions.ROLE_LABELS.items()
                ],
            }
        )


    @router.get("/api/users/<int:user_id>", roles=("admin",), summary="用户详情")
    def get_user(req) -> Response:
        permissions.require_admin(req.user)
        return ok(user_service.get_user(req.path_params["user_id"]))


    @router.put("/api/users/<int:user_id>", roles=("admin",), summary="更新用户")
    def update_user(req) -> Response:
        admin = permissions.require_admin(req.user)
        data = user_service.update_user(
            req.path_params["user_id"], req.json(), operator=admin
        )
        return ok(data, "已更新")


    @router.post("/api/users/<int:user_id>/status", roles=("admin",), summary="启用/禁用账号")
    def set_status(req) -> Response:
        admin = permissions.require_admin(req.user)
        payload = req.json()
        status = validators.required_str(payload, "status", max_len=16)
        data = user_service.set_status(req.path_params["user_id"], status, operator=admin)
        return ok(data, "状态已更新")


    @router.post("/api/users/<int:user_id>/reset-password", roles=("admin",),
                 summary="重置密码")
    def reset_password(req) -> Response:
        admin = permissions.require_admin(req.user)
        data = user_service.reset_password(req.path_params["user_id"], operator=admin)
        return ok(data, "新密码已生成，请转告用户")


    @router.post("/api/users/import", roles=("admin",), summary="批量导入用户")
    def import_users(req) -> Response:
        admin = permissions.require_admin(req.user)
        payload = req.json()
        csv_text = validators.required_str(payload, "csv", min_len=1, max_len=2_000_000, strip=False)
        default_role = validators.optional_str(payload, "default_role", "student", max_len=16)
        result = user_service.import_users(csv_text, default_role=default_role, operator=admin)
        return ok(result, f"导入完成：成功 {result['created']} 条，失败 {result['failed']} 条")
    return SimpleNamespace(
        router=router,
        list_users=list_users,
        create_user=create_user,
        options=options,
        get_user=get_user,
        update_user=update_user,
        set_status=set_status,
        reset_password=reset_password,
        import_users=import_users,
    )


# ======================================================================
# 模块：backend/api/course_routes.py
# ======================================================================
def _mod_course_api(Response, Router, course_service, created, ok, paginated, permissions, validators):
    """课程与教学班接口。"""



    router = Router()


    # ---------------------------------------------------------------- 课程


    @router.get("/api/courses", summary="课程列表")
    def list_courses(req) -> Response:
        user = permissions.require_login(req.user)
        page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
        items, total = course_service.list_courses(
            user,
            term=req.str_param("term"),
            keyword=req.str_param("keyword"),
            page=page,
            page_size=page_size,
        )
        return paginated(items, total, page, page_size)


    @router.post("/api/courses", roles=("teacher", "admin"), summary="新建课程")
    def create_course(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = course_service.create_course(req.json(), operator=user)
        return created(data, "课程已创建")


    @router.get("/api/courses/<int:course_id>", summary="课程详情")
    def get_course(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(course_service.get_course(user, req.path_params["course_id"]))


    @router.put("/api/courses/<int:course_id>", roles=("teacher", "admin"), summary="更新课程")
    def update_course(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = course_service.update_course(
            req.path_params["course_id"], req.json(), operator=user
        )
        return ok(data, "课程已更新")


    @router.get("/api/courses/<int:course_id>/classes", summary="课程下的教学班")
    def list_course_classes(req) -> Response:
        user = permissions.require_login(req.user)
        course = course_service.get_course(user, req.path_params["course_id"])
        return ok(course.get("classes", []))


    @router.post("/api/courses/<int:course_id>/classes",
                 roles=("teacher", "admin"), summary="新建教学班")
    def create_class(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = course_service.create_class(
            req.path_params["course_id"], req.json(), operator=user
        )
        return created(data, "教学班已创建")


    # ---------------------------------------------------------------- 教学班


    @router.get("/api/classes", summary="我相关教学班")
    def list_classes(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(course_service.list_classes(user))


    @router.get("/api/classes/<int:class_id>", summary="教学班详情")
    def get_class(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(course_service.get_class(user, req.path_params["class_id"]))


    @router.post("/api/classes/join", roles=("student",), summary="凭邀请码加入")
    def join_class(req) -> Response:
        user = permissions.require_role(req.user, "student")
        payload = req.json()
        code = validators.required_str(payload, "code", min_len=4, max_len=12)
        data = course_service.join_class(user, code)
        return ok(data, "加入成功")


    @router.get("/api/classes/<int:class_id>/students", summary="教学班学生")
    def class_students(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(course_service.class_students(user, req.path_params["class_id"]))


    @router.post("/api/classes/<int:class_id>/students",
                 roles=("teacher", "admin"), summary="手动添加学生")
    def add_student(req) -> Response:
        user = permissions.require_teacher(req.user)
        payload = req.json()
        student_id = validators.required_int(payload, "student_id", min_value=1)
        return ok(course_service.add_student(req.path_params["class_id"], student_id, user))


    @router.delete("/api/classes/<int:class_id>/students/<int:student_id>",
                   roles=("teacher", "admin"), summary="移出学生")
    def drop_student(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(
            course_service.drop_student(
                req.path_params["class_id"], req.path_params["student_id"], user
            )
        )


    @router.post("/api/classes/<int:class_id>/leave", roles=("student",), summary="退课")
    def leave_class(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(course_service.leave_class(user, req.path_params["class_id"]))


    @router.get("/api/teacher/overview", roles=("teacher", "admin"), summary="教师工作台")
    def teacher_overview(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(course_service.teacher_overview(user))
    return SimpleNamespace(
        router=router,
        list_courses=list_courses,
        create_course=create_course,
        get_course=get_course,
        update_course=update_course,
        list_course_classes=list_course_classes,
        create_class=create_class,
        list_classes=list_classes,
        get_class=get_class,
        join_class=join_class,
        class_students=class_students,
        add_student=add_student,
        drop_student=drop_student,
        leave_class=leave_class,
        teacher_overview=teacher_overview,
    )


# ======================================================================
# 模块：backend/api/chapter_routes.py
# ======================================================================
def _mod_chapter_api(Response, Router, chapter_service, created, ok, permissions):
    """章节任务点与学习进度接口。"""



    router = Router()


    # ---------------------------------------------------------------- 章节


    @router.get("/api/courses/<int:course_id>/chapters", summary="课程章节与任务点")
    def list_chapters(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(chapter_service.list_chapters(user, req.path_params["course_id"]))


    @router.post("/api/courses/<int:course_id>/chapters",
                 roles=("teacher", "admin"), summary="新建章节")
    def create_chapter(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = chapter_service.create_chapter(
            user, req.path_params["course_id"], req.json()
        )
        return created(data, "章节已创建")


    @router.put("/api/chapters/<int:chapter_id>", roles=("teacher", "admin"),
                summary="更新章节")
    def update_chapter(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = chapter_service.update_chapter(
            user, req.path_params["chapter_id"], req.json()
        )
        return ok(data, "章节已更新")


    @router.delete("/api/chapters/<int:chapter_id>", roles=("teacher", "admin"),
                   summary="删除章节")
    def delete_chapter(req) -> Response:
        user = permissions.require_teacher(req.user)
        chapter_service.delete_chapter(user, req.path_params["chapter_id"])
        return ok(None, "章节已删除")


    # ---------------------------------------------------------------- 任务点


    @router.post("/api/chapters/<int:chapter_id>/tasks",
                 roles=("teacher", "admin"), summary="新增任务点")
    def create_task(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = chapter_service.create_task(
            user, req.path_params["chapter_id"], req.json()
        )
        return created(data, "任务点已创建")


    @router.put("/api/tasks/<int:task_id>", roles=("teacher", "admin"),
                summary="更新任务点")
    def update_task(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = chapter_service.update_task(user, req.path_params["task_id"], req.json())
        return ok(data, "任务点已更新")


    @router.delete("/api/tasks/<int:task_id>", roles=("teacher", "admin"),
                   summary="删除任务点")
    def delete_task(req) -> Response:
        user = permissions.require_teacher(req.user)
        chapter_service.delete_task(user, req.path_params["task_id"])
        return ok(None, "任务点已删除")


    # ---------------------------------------------------------------- 学习进度


    @router.post("/api/tasks/<int:task_id>/progress", roles=("student",),
                 summary="上报任务点进度")
    def report_progress(req) -> Response:
        user = permissions.require_role(req.user, "student")
        data = chapter_service.report_progress(
            user, req.path_params["task_id"], req.json()
        )
        return ok(data, "学习进度已更新")


    @router.get("/api/courses/<int:course_id>/progress", roles=("teacher", "admin"),
                summary="课程学习进度")
    def course_progress(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(chapter_service.course_progress(user, req.path_params["course_id"]))


    @router.get("/api/my/learning", roles=("student",), summary="我的学习进度")
    def my_learning(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(chapter_service.my_learning(user))
    return SimpleNamespace(
        router=router,
        list_chapters=list_chapters,
        create_chapter=create_chapter,
        update_chapter=update_chapter,
        delete_chapter=delete_chapter,
        create_task=create_task,
        update_task=update_task,
        delete_task=delete_task,
        report_progress=report_progress,
        course_progress=course_progress,
        my_learning=my_learning,
    )


# ======================================================================
# 模块：backend/api/assignment_routes.py
# ======================================================================
def _mod_assignment_api(Response, Router, assignment_service, attachment_service, created, file_response, multipart, ok, permissions, validators):
    """作业接口。"""



    router = Router()


    @router.get("/api/classes/<int:class_id>/assignments", summary="教学班作业列表")
    def list_class_assignments(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(assignment_service.list_assignments(user, req.path_params["class_id"]))


    @router.post("/api/assignments", roles=("teacher", "admin"), summary="发布作业")
    def create_assignment(req) -> Response:
        user = permissions.require_teacher(req.user)
        return created(assignment_service.create_assignment(req.json(), operator=user), "作业已发布")


    @router.get("/api/assignments/<int:assignment_id>", summary="作业详情")
    def get_assignment(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(assignment_service.get_assignment(user, req.path_params["assignment_id"]))


    @router.put("/api/assignments/<int:assignment_id>", roles=("teacher", "admin"),
                summary="更新作业")
    def update_assignment(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = assignment_service.update_assignment(
            req.path_params["assignment_id"], req.json(), operator=user
        )
        return ok(data, "作业已更新")


    @router.delete("/api/assignments/<int:assignment_id>", roles=("teacher", "admin"),
                   summary="删除作业")
    def delete_assignment(req) -> Response:
        user = permissions.require_teacher(req.user)
        assignment_service.delete_assignment(user, req.path_params["assignment_id"])
        return ok(None, "作业已删除")


    @router.get("/api/my/assignments", roles=("student",), summary="我的作业")
    def my_assignments(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(assignment_service.student_assignments(user, status=req.str_param("status")))


    @router.post("/api/assignments/<int:assignment_id>/submit", roles=("student",),
                 summary="提交作业")
    def submit_assignment(req) -> Response:
        user = permissions.require_role(req.user, "student")
        data = assignment_service.submit(user, req.path_params["assignment_id"], req.json())
        return ok(data, "提交成功")


    @router.get("/api/assignments/<int:assignment_id>/submissions",
                roles=("teacher", "admin"), summary="作业提交列表")
    def list_submissions(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(assignment_service.list_submissions(user, req.path_params["assignment_id"]))


    @router.post("/api/submissions/<int:submission_id>/grade",
                 roles=("teacher", "admin"), summary="批改单份作业")
    def grade_submission(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = assignment_service.grade_submission(
            user, req.path_params["submission_id"], req.json()
        )
        return ok(data, "批改完成")


    @router.post("/api/assignments/<int:assignment_id>/batch-grade",
                 roles=("teacher", "admin"), summary="批量批改")
    def batch_grade(req) -> Response:
        user = permissions.require_teacher(req.user)
        payload = req.json()
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise validators.ValidationError("rows 必须是数组")
        result = assignment_service.batch_grade(
            user, req.path_params["assignment_id"], rows
        )
        return ok(result, f"已批改 {result['updated']} 份")

    # ---------------------------------------------------------------- 附件


    @router.get("/api/assignments/<int:assignment_id>/attachments", summary="我的附件列表")
    def list_attachments(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(attachment_service.list_for(req.path_params["assignment_id"], int(user["id"])))


    @router.post("/api/assignments/<int:assignment_id>/attachments", roles=("student",),
                 summary="上传作业附件")
    def upload_attachment(req) -> Response:
        user = permissions.require_role(req.user, "student")
        content_type = req.header("content-type")
        if not multipart.is_multipart(content_type):
            raise validators.ValidationError("请使用 multipart/form-data 上传")
        form = multipart.parse_multipart(req.body, content_type)
        files = [(f.filename, f.data) for f in form.files.values()]
        if not files:
            raise validators.ValidationError("没有找到上传文件")
        saved = attachment_service.save_uploads(
            req.path_params["assignment_id"], int(user["id"]), files
        )
        return created({"files": saved}, "上传成功")


    @router.get("/api/attachments/<int:file_id>/download", summary="下载作业附件")
    def download_attachment(req) -> Response:
        user = permissions.require_login(req.user)
        path, filename = attachment_service.resolve_download(user, req.path_params["file_id"])
        return file_response(path, download_name=filename)


    @router.delete("/api/attachments/<int:file_id>", roles=("student",), summary="删除附件")
    def delete_attachment(req) -> Response:
        user = permissions.require_role(req.user, "student")
        attachment_service.delete_file(user, req.path_params["file_id"])
        return ok(None, "已删除")
    return SimpleNamespace(
        router=router,
        list_class_assignments=list_class_assignments,
        create_assignment=create_assignment,
        get_assignment=get_assignment,
        update_assignment=update_assignment,
        delete_assignment=delete_assignment,
        my_assignments=my_assignments,
        submit_assignment=submit_assignment,
        list_submissions=list_submissions,
        grade_submission=grade_submission,
        batch_grade=batch_grade,
        list_attachments=list_attachments,
        upload_attachment=upload_attachment,
        download_attachment=download_attachment,
        delete_attachment=delete_attachment,
    )


# ======================================================================
# 模块：backend/api/quiz_routes.py
# ======================================================================
def _mod_quiz_api(Response, Router, created, ok, permissions, quiz_service, validators):
    """测验接口。"""



    router = Router()


    @router.get("/api/classes/<int:class_id>/quizzes", summary="教学班测验列表")
    def list_class_quizzes(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(quiz_service.list_for_class(user, req.path_params["class_id"]))


    @router.post("/api/quizzes", roles=("teacher", "admin"), summary="创建测验")
    def create_quiz(req) -> Response:
        user = permissions.require_teacher(req.user)
        return created(quiz_service.create_quiz(req.json(), operator=user), "测验已创建")


    @router.get("/api/quizzes/<int:quiz_id>", summary="测验详情")
    def get_quiz(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(quiz_service.get_quiz(user, req.path_params["quiz_id"]))


    @router.get("/api/my/quizzes", roles=("student",), summary="我的测验")
    def my_quizzes(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(quiz_service.student_quizzes(user))


    @router.post("/api/quizzes/<int:quiz_id>/start", roles=("student",), summary="开始答题")
    def start_quiz(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(quiz_service.start_attempt(user, req.path_params["quiz_id"]))


    @router.put("/api/quizzes/<int:quiz_id>/answers", roles=("student",), summary="暂存答案")
    def save_answers(req) -> Response:
        user = permissions.require_role(req.user, "student")
        payload = req.json()
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise validators.ValidationError("answers 必须是对象")
        return ok(quiz_service.save_answers(user, req.path_params["quiz_id"], answers))


    @router.post("/api/quizzes/<int:quiz_id>/submit", roles=("student",), summary="交卷")
    def submit_quiz(req) -> Response:
        user = permissions.require_role(req.user, "student")
        payload = req.json()
        answers = payload.get("answers") or {}
        if not isinstance(answers, dict):
            raise validators.ValidationError("answers 必须是对象")
        result = quiz_service.submit_attempt(user, req.path_params["quiz_id"], answers)
        return ok(result, "交卷成功")


    @router.get("/api/quizzes/<int:quiz_id>/standings", roles=("teacher", "admin"),
                summary="测验成绩排行")
    def standings(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(quiz_service.standings(user, req.path_params["quiz_id"]))


    @router.post("/api/quizzes/<int:quiz_id>/grade", roles=("teacher", "admin"),
                 summary="人工复核")
    def manual_grade(req) -> Response:
        user = permissions.require_teacher(req.user)
        payload = req.json()
        student_id = validators.required_int(payload, "student_id", min_value=1)
        score = validators.required_int(payload, "score", min_value=0)
        return ok(
            quiz_service.manual_grade(user, req.path_params["quiz_id"], student_id, score)
        )
    return SimpleNamespace(
        router=router,
        list_class_quizzes=list_class_quizzes,
        create_quiz=create_quiz,
        get_quiz=get_quiz,
        my_quizzes=my_quizzes,
        start_quiz=start_quiz,
        save_answers=save_answers,
        submit_quiz=submit_quiz,
        standings=standings,
        manual_grade=manual_grade,
    )


# ======================================================================
# 模块：backend/api/attendance_routes.py
# ======================================================================
def _mod_attendance_api(Response, Router, attendance_service, created, ok, permissions, validators):
    """签到接口。"""



    router = Router()


    @router.get("/api/classes/<int:class_id>/attendance", summary="教学班签到列表")
    def list_sessions(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(attendance_service.list_sessions(user, req.path_params["class_id"]))


    @router.post("/api/attendance", roles=("teacher", "admin"), summary="发起签到")
    def create_session(req) -> Response:
        user = permissions.require_teacher(req.user)
        return created(attendance_service.create_session(req.json(), operator=user), "签到已发起")


    @router.get("/api/my/attendance/open", roles=("student",), summary="进行中的签到")
    def open_sessions(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(attendance_service.open_sessions_for_student(user))


    @router.get("/api/attendance/<int:session_id>", summary="签到详情")
    def session_detail(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(attendance_service.session_detail(user, req.path_params["session_id"]))


    @router.post("/api/attendance/<int:session_id>/check-in", roles=("student",),
                 summary="学生签到")
    def check_in(req) -> Response:
        user = permissions.require_role(req.user, "student")
        data = attendance_service.check_in(user, req.path_params["session_id"], req.json())
        return ok(data, "签到成功")


    @router.post("/api/attendance/<int:session_id>/mark", roles=("teacher", "admin"),
                 summary="教师补签")
    def mark(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(
            attendance_service.mark_manually(user, req.path_params["session_id"], req.json())
        )


    @router.post("/api/attendance/<int:session_id>/close", roles=("teacher", "admin"),
                 summary="结束签到")
    def close(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(attendance_service.close_session(user, req.path_params["session_id"]))


    @router.get("/api/classes/<int:class_id>/attendance/summary",
                roles=("teacher", "admin"), summary="出勤汇总")
    def summary(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(attendance_service.class_attendance_summary(user, req.path_params["class_id"]))


    @router.get("/api/system/storage", roles=("admin",), summary="存储占用")
    def storage(req) -> Response:
        permissions.require_admin(req.user)
        from backend.services import resource_service

        return ok(resource_service.storage_usage())
    return SimpleNamespace(
        router=router,
        list_sessions=list_sessions,
        create_session=create_session,
        open_sessions=open_sessions,
        session_detail=session_detail,
        check_in=check_in,
        mark=mark,
        close=close,
        summary=summary,
        storage=storage,
    )


# ======================================================================
# 模块：backend/api/grade_routes.py
# ======================================================================
def _mod_grade_api(Response, Router, grade_service, ok, permissions):
    """成绩接口。"""



    router = Router()


    @router.get("/api/classes/<int:class_id>/grade-rule", roles=("teacher", "admin"),
                summary="成绩权重")
    def get_rule(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(grade_service.get_rule(user, req.path_params["class_id"]))


    @router.put("/api/classes/<int:class_id>/grade-rule", roles=("teacher", "admin"),
                summary="保存成绩权重")
    def save_rule(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = grade_service.save_rule(user, req.path_params["class_id"], req.json())
        return ok(data, "权重已保存")


    @router.get("/api/classes/<int:class_id>/gradebook", roles=("teacher", "admin"),
                summary="成绩册")
    def gradebook(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(grade_service.gradebook(user, req.path_params["class_id"]))


    @router.post("/api/classes/<int:class_id>/grades", roles=("teacher", "admin"),
                 summary="录入期末成绩")
    def set_final(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = grade_service.set_final_score(user, req.path_params["class_id"], req.json())
        return ok(data, "成绩已更新")


    @router.post("/api/classes/<int:class_id>/grades/batch", roles=("teacher", "admin"),
                 summary="批量录入")
    def batch_set_final(req) -> Response:
        user = permissions.require_teacher(req.user)
        payload = req.json()
        rows = payload.get("rows")
        if not isinstance(rows, list):
            from backend.core.errors import ValidationError

            raise ValidationError("rows 必须是数组")
        result = grade_service.batch_set_final(user, req.path_params["class_id"], rows)
        return ok(result, f"已更新 {result['updated']} 条")


    @router.get("/api/classes/<int:class_id>/ranking", roles=("teacher", "admin"),
                summary="班级排名")
    def ranking(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(grade_service.class_ranking(user, req.path_params["class_id"]))


    @router.get("/api/my/transcript", roles=("student",), summary="我的成绩单")
    def transcript(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(grade_service.my_transcript(user))


    @router.get("/api/classes/<int:class_id>/grades/export", roles=("teacher", "admin"),
                summary="导出成绩 CSV")
    def export(req) -> Response:
        user = permissions.require_teacher(req.user)
        text = grade_service.export_csv(user, req.path_params["class_id"])
        from backend.http.response import Response as R

        return R(
            status=200,
            body=text.encode("utf-8-sig"),
            content_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=gradebook_{req.path_params['class_id']}.csv"
            },
        )
    return SimpleNamespace(
        router=router,
        get_rule=get_rule,
        save_rule=save_rule,
        gradebook=gradebook,
        set_final=set_final,
        batch_set_final=batch_set_final,
        ranking=ranking,
        transcript=transcript,
        export=export,
    )


# ======================================================================
# 模块：backend/api/content_routes.py
# ======================================================================
def _mod_content_api(Response, Router, announcement_service, created, discussion_service, file_response, multipart, notification_service, ok, paginated, permissions, resource_service, validators):
    """资料、讨论、通知接口。"""



    router = Router()


    # ---------------------------------------------------------------- 公告


    @router.get("/api/courses/<int:course_id>/announcements", summary="课程公告列表")
    def list_announcements(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(announcement_service.list_for_course(user, req.path_params["course_id"]))


    @router.post("/api/courses/<int:course_id>/announcements",
                 roles=("teacher", "admin"), summary="发布公告")
    def create_announcement(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = announcement_service.create(user, req.path_params["course_id"], req.json())
        return created(data, "公告已发布")


    @router.get("/api/my/announcements", roles=("student",), summary="我的课程公告")
    def my_announcements(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(announcement_service.student_feed(user))


    @router.put("/api/announcements/<int:announcement_id>", roles=("teacher", "admin"),
                summary="更新公告")
    def update_announcement(req) -> Response:
        user = permissions.require_teacher(req.user)
        data = announcement_service.update(user, req.path_params["announcement_id"], req.json())
        return ok(data, "公告已更新")


    @router.delete("/api/announcements/<int:announcement_id>", roles=("teacher", "admin"),
                   summary="删除公告")
    def delete_announcement(req) -> Response:
        user = permissions.require_teacher(req.user)
        announcement_service.delete(user, req.path_params["announcement_id"])
        return ok(None, "公告已删除")


    # ---------------------------------------------------------------- 资料


    @router.get("/api/courses/<int:course_id>/resources", summary="课程资料列表")
    def list_resources(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(
            resource_service.list_resources(
                user, req.path_params["course_id"], keyword=req.str_param("keyword")
            )
        )


    @router.post("/api/courses/<int:course_id>/resources", roles=("teacher", "admin"),
                 summary="上传资料")
    def upload_resource(req) -> Response:
        user = permissions.require_teacher(req.user)
        content_type = req.header("content-type")
        if not multipart.is_multipart(content_type):
            raise validators.ValidationError("请使用 multipart/form-data 上传")
        form = multipart.parse_multipart(req.body, content_type)
        uploaded = form.first_file()
        if uploaded is None:
            raise validators.ValidationError("没有找到上传文件")
        data = resource_service.save_upload(
            uploaded.filename,
            uploaded.data,
            course_id=req.path_params["course_id"],
            operator=user,
            title=form.get("title", ""),
            description=form.get("description", ""),
            category=form.get("category", "课件"),
        )
        return created(data, "上传成功")


    @router.get("/api/resources/<int:resource_id>/download", summary="下载资料")
    def download_resource(req) -> Response:
        user = permissions.require_login(req.user)
        path, filename = resource_service.get_download(user, req.path_params["resource_id"])
        return file_response(path, download_name=filename)


    @router.delete("/api/resources/<int:resource_id>", roles=("teacher", "admin"),
                   summary="删除资料")
    def delete_resource(req) -> Response:
        user = permissions.require_teacher(req.user)
        resource_service.delete_resource(user, req.path_params["resource_id"])
        return ok(None, "已删除")


    # ---------------------------------------------------------------- 讨论


    @router.get("/api/courses/<int:course_id>/discussions", summary="话题列表")
    def list_threads(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(discussion_service.list_threads(user, req.path_params["course_id"]))


    @router.post("/api/courses/<int:course_id>/discussions", summary="发布话题")
    def create_thread(req) -> Response:
        user = permissions.require_login(req.user)
        data = discussion_service.create_thread(
            user, req.path_params["course_id"], req.json()
        )
        return created(data, "话题已发布")


    @router.get("/api/discussions/<int:discussion_id>", summary="话题详情")
    def get_thread(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(discussion_service.get_thread(user, req.path_params["discussion_id"]))


    @router.post("/api/discussions/<int:discussion_id>/replies", summary="回复话题")
    def reply(req) -> Response:
        user = permissions.require_login(req.user)
        return created(discussion_service.reply(user, req.path_params["discussion_id"], req.json()))


    @router.put("/api/discussions/<int:discussion_id>", roles=("teacher", "admin"),
                summary="置顶/锁定/删除话题")
    def set_flags(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(discussion_service.set_flags(user, req.path_params["discussion_id"], req.json()))


    @router.delete("/api/replies/<int:reply_id>", summary="删除回复")
    def delete_reply(req) -> Response:
        user = permissions.require_login(req.user)
        return ok(discussion_service.delete_reply(user, req.path_params["reply_id"]))


    # ---------------------------------------------------------------- 通知


    @router.get("/api/notifications", summary="我的通知")
    def list_notifications(req) -> Response:
        user = permissions.require_login(req.user)
        page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
        items, total = notification_service.list_notifications(
            user,
            only_unread=req.bool_param("unread"),
            page=page,
            page_size=page_size,
        )
        return paginated(items, total, page, page_size)


    @router.get("/api/notifications/unread-count", summary="未读数")
    def unread_count(req) -> Response:
        user = permissions.require_login(req.user)
        return ok({"count": notification_service.unread_count(user)})


    @router.post("/api/notifications/<int:notification_id>/read", summary="标记已读")
    def mark_read(req) -> Response:
        user = permissions.require_login(req.user)
        notification_service.mark_read(user, req.path_params["notification_id"])
        return ok(None, "已读")


    @router.post("/api/notifications/read-all", summary="全部已读")
    def mark_all_read(req) -> Response:
        user = permissions.require_login(req.user)
        return ok({"updated": notification_service.mark_all_read(user)})


    @router.delete("/api/notifications/read", summary="清空已读")
    def clear_read(req) -> Response:
        user = permissions.require_login(req.user)
        return ok({"deleted": notification_service.clear_read(user)})


    @router.post("/api/notifications/broadcast", roles=("admin",), summary="广播通知")
    def broadcast(req) -> Response:
        user = permissions.require_admin(req.user)
        count = notification_service.broadcast(user, req.json())
        return ok({"sent": count}, f"已发送 {count} 条")
    return SimpleNamespace(
        router=router,
        list_announcements=list_announcements,
        create_announcement=create_announcement,
        my_announcements=my_announcements,
        update_announcement=update_announcement,
        delete_announcement=delete_announcement,
        list_resources=list_resources,
        upload_resource=upload_resource,
        download_resource=download_resource,
        delete_resource=delete_resource,
        list_threads=list_threads,
        create_thread=create_thread,
        get_thread=get_thread,
        reply=reply,
        set_flags=set_flags,
        delete_reply=delete_reply,
        list_notifications=list_notifications,
        unread_count=unread_count,
        mark_read=mark_read,
        mark_all_read=mark_all_read,
        clear_read=clear_read,
        broadcast=broadcast,
    )


# ======================================================================
# 模块：backend/api/report_routes.py
# ======================================================================
def _mod_report_api(AuditRepository, Response, Router, ok, paginated, permissions, statistics_service, validators):
    """统计报表接口。"""



    router = Router()


    @router.get("/api/dashboard", summary="按角色返回首页数据")
    def dashboard(req) -> Response:
        user = permissions.require_login(req.user)
        if user["role"] == permissions.ROLE_ADMIN:
            return ok(statistics_service.admin_dashboard())
        if user["role"] == permissions.ROLE_TEACHER:
            return ok(statistics_service.teacher_dashboard(user))
        return ok(statistics_service.student_report(user))


    @router.get("/api/reports/course/<int:course_id>", roles=("teacher", "admin"),
                summary="课程活跃度")
    def course_report(req) -> Response:
        user = permissions.require_teacher(req.user)
        return ok(statistics_service.course_overview(user, req.path_params["course_id"]))


    @router.get("/api/reports/student", roles=("student",), summary="学习报告")
    def student_report(req) -> Response:
        user = permissions.require_role(req.user, "student")
        return ok(statistics_service.student_report(user))


    @router.get("/api/audit-logs", roles=("admin",), summary="审计日志")
    def audit_logs(req) -> Response:
        permissions.require_admin(req.user)
        repo = AuditRepository()
        page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
        offset = (page - 1) * page_size
        action = req.str_param("action")
        keyword = req.str_param("keyword")
        items = repo.list_logs(action=action, keyword=keyword, limit=page_size, offset=offset)
        total = repo.count_logs(action=action, keyword=keyword)
        return paginated(items, total, page, page_size)
    return SimpleNamespace(
        router=router,
        dashboard=dashboard,
        course_report=course_report,
        student_report=student_report,
        audit_logs=audit_logs,
    )


# ======================================================================
# 模块：backend/api/system_routes.py
# ======================================================================
def _mod_system_api(AuditRepository, Response, Router, SettingRepository, backup_service, clock, config, connection, errors, file_response, ok, permissions, search_service, validators):
    """系统级接口：健康检查、元信息、设置、接口清单。"""




    _app_ref = None


    def bind_application(app) -> None:
        """由 app.py 在装配完成后注入，供 /api/routes 使用。"""
        global _app_ref
        _app_ref = app


    router = Router()
    setting_repo = SettingRepository()
    audit_repo = AuditRepository()


    @router.get("/api/health", auth=False, summary="健康检查")
    def health(req) -> Response:

        db_ok = True
        try:
            connection.scalar("SELECT 1")
        except Exception:  # noqa: BLE001
            db_ok = False
        return ok(
            {
                "status": "ok" if db_ok else "degraded",
                "database": db_ok,
                "time": clock.now_iso(),
                "version": config.APP_VERSION,
            }
        )


    @router.get("/api/meta", auth=False, summary="应用元信息")
    def meta(req) -> Response:
        return ok(
            {
                "name": config.APP_NAME,
                "short_name": config.APP_SHORT_NAME,
                "version": config.APP_VERSION,
                "description": config.APP_DESCRIPTION,
                "term": setting_repo.get("term", clock.term_of()),
                "school_name": setting_repo.get("school_name", "EduFlow 大学"),
                "server_time": clock.now_iso(),
            }
        )


    @router.get("/api/routes", summary="接口清单（开发用）")
    def routes(req) -> Response:

        if _app_ref is None:
            return ok({"total": 0, "routes": []})
        return ok(_app_ref.describe_routes())


    @router.get("/api/settings", roles=("admin",), summary="系统设置")
    def get_settings(req) -> Response:
        permissions.require_admin(req.user)
        return ok(setting_repo.all())


    @router.put("/api/settings", roles=("admin",), summary="更新系统设置")
    def update_settings(req) -> Response:
        admin = permissions.require_admin(req.user)
        payload = req.json()
        updated: dict[str, str] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or len(key) > 64:
                continue
            setting_repo.set(key, str(value)[:2000])
            updated[key] = str(value)
        audit_repo.log(
            user_id=int(admin["id"]),
            username=admin["username"],
            action="update_settings",
            entity="settings",
            detail=f"更新 {', '.join(updated)}",
        )
        return ok(setting_repo.all(), "设置已保存")


    @router.get("/api/audit/actions", roles=("admin",), summary="审计动作枚举")
    def audit_actions(req) -> Response:
        permissions.require_admin(req.user)
        rows = audit_repo.list_logs(limit=500)
        actions = sorted({row["action"] for row in rows})
        return ok(actions)


    @router.post("/api/system/vacuum", roles=("admin",), summary="整理数据库")
    def vacuum(req) -> Response:
        permissions.require_admin(req.user)

        connection.get_connection().execute("VACUUM")
        return ok({"ok": True, "at": clock.now_iso()}, "数据库已整理")


    @router.get("/api/search", summary="全局搜索")
    def search(req) -> Response:

        user = permissions.require_login(req.user)
        keyword = req.str_param("q") or req.str_param("keyword")
        return ok(search_service.global_search(user, keyword))


    @router.post("/api/system/backup", roles=("admin",), summary="创建数据备份")
    def create_backup(req) -> Response:
        admin = permissions.require_admin(req.user)

        payload = req.json()
        note = validators.optional_str(payload, "note", "", max_len=40)
        info = backup_service.create_backup(note)
        audit_repo.log(
            user_id=int(admin["id"]),
            username=admin["username"],
            action="create_backup",
            entity="backup",
            detail=info["filename"],
        )
        return ok(info, "备份已创建")


    @router.get("/api/system/backups", roles=("admin",), summary="备份列表")
    def list_backups(req) -> Response:
        permissions.require_admin(req.user)

        return ok({"items": backup_service.list_backups(), "stats": backup_service.stats()})


    @router.get("/api/system/backups/<str:filename>/download", roles=("admin",),
                summary="下载备份")
    def download_backup(req) -> Response:
        permissions.require_admin(req.user)

        path = backup_service.resolve_backup(req.path_params["filename"])
        return file_response(path, download_name=path.name)


    @router.delete("/api/system/backups/<str:filename>", roles=("admin",),
                   summary="删除备份")
    def delete_backup(req) -> Response:
        permissions.require_admin(req.user)

        backup_service.delete_backup(req.path_params["filename"])
        return ok(None, "备份已删除")


    @router.post("/api/system/backups/<str:filename>/restore", roles=("admin",),
                 summary="用备份恢复数据")
    def restore_backup(req) -> Response:
        admin = permissions.require_admin(req.user)

        payload = req.json()
        if not validators.to_bool(payload.get("confirm"), False):
            raise errors.ValidationError("恢复数据需要传 confirm=true 明确确认")
        result = backup_service.restore_backup(req.path_params["filename"])
        audit_repo.log(
            user_id=int(admin["id"]),
            username=admin["username"],
            action="restore_backup",
            entity="backup",
            detail=req.path_params["filename"],
        )
        return ok(result, "数据已恢复，建议重新登录")
    return SimpleNamespace(
        bind_application=bind_application,
        router=router,
        setting_repo=setting_repo,
        audit_repo=audit_repo,
        health=health,
        meta=meta,
        routes=routes,
        get_settings=get_settings,
        update_settings=update_settings,
        audit_actions=audit_actions,
        vacuum=vacuum,
        search=search,
        create_backup=create_backup,
        list_backups=list_backups,
        download_backup=download_backup,
        delete_backup=delete_backup,
        restore_backup=restore_backup,
    )


# ======================================================================
# 第二部分：按依赖顺序实例化各模块
# ======================================================================

config = _mod_config()
ids = _mod_ids()
clock = _mod_clock()
errors = _mod_errors()
security = _mod_security(PASSWORD_ITERATIONS=config.PASSWORD_ITERATIONS, PASSWORD_KEY_LEN=config.PASSWORD_KEY_LEN, ValidationError=errors.ValidationError)
validators = _mod_validators(clock=clock, ValidationError=errors.ValidationError)
permissions = _mod_permissions(ForbiddenError=errors.ForbiddenError, UnauthorizedError=errors.UnauthorizedError)
response_lib = _mod_response_lib(AppError=errors.AppError)
static_lib = _mod_static_lib(STATIC_CACHE_SECONDS=config.STATIC_CACHE_SECONDS, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, Response=response_lib.Response)
connection = _mod_connection(config=config)
backup_service = _mod_backup_service(config=config, clock=clock, NotFoundError=errors.NotFoundError, ValidationError=errors.ValidationError, connection=connection)
migrations = _mod_migrations(config=config, clock=clock, connection=connection)
base_repo = _mod_base_repo(clock=clock, NotFoundError=errors.NotFoundError, ValidationError=errors.ValidationError, connection=connection)
users_repo = _mod_users_repo(clock=clock, connection=connection, BaseRepository=base_repo.BaseRepository)
courses_repo = _mod_courses_repo(clock=clock, connection=connection, BaseRepository=base_repo.BaseRepository)
assignments_repo = _mod_assignments_repo(clock=clock, connection=connection, BaseRepository=base_repo.BaseRepository)
quizzes_repo = _mod_quizzes_repo(clock=clock, connection=connection, BaseRepository=base_repo.BaseRepository)
attendance_repo = _mod_attendance_repo(clock=clock, connection=connection, BaseRepository=base_repo.BaseRepository)
content_repo = _mod_content_repo(clock=clock, connection=connection, BaseRepository=base_repo.BaseRepository)
grades_repo = _mod_grades_repo(connection=connection, BaseRepository=base_repo.BaseRepository)
audit_repo = _mod_audit_repo(connection=connection, BaseRepository=base_repo.BaseRepository)
chapters_repo = _mod_chapters_repo(connection=connection, BaseRepository=base_repo.BaseRepository)
search_service = _mod_search_service(permissions=permissions, connection=connection)
auth_service = _mod_auth_service(config=config, clock=clock, ids=ids, permissions=permissions, security=security, ForbiddenError=errors.ForbiddenError, RateLimitError=errors.RateLimitError, UnauthorizedError=errors.UnauthorizedError, ValidationError=errors.ValidationError, AuditRepository=audit_repo.AuditRepository, LoginAttemptRepository=users_repo.LoginAttemptRepository, SessionRepository=users_repo.SessionRepository, UserRepository=users_repo.UserRepository)
notification_service = _mod_notification_service(permissions=permissions, NotificationRepository=content_repo.NotificationRepository, UserRepository=users_repo.UserRepository)
announcement_service = _mod_announcement_service(permissions=permissions, validators=validators, NotFoundError=errors.NotFoundError, AuditRepository=audit_repo.AuditRepository, AnnouncementRepository=content_repo.AnnouncementRepository, ClassRepository=courses_repo.ClassRepository, CourseRepository=courses_repo.CourseRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, notify_many=notification_service.notify_many)
attachment_service = _mod_attachment_service(config=config, clock=clock, ids=ids, permissions=permissions, validators=validators, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, TooLargeError=errors.TooLargeError, connection=connection, safe_join=static_lib.safe_join, AuditRepository=audit_repo.AuditRepository, ClassRepository=courses_repo.ClassRepository, EnrollmentRepository=courses_repo.EnrollmentRepository)
user_service = _mod_user_service(config=config, clock=clock, permissions=permissions, security=security, validators=validators, ConflictError=errors.ConflictError, NotFoundError=errors.NotFoundError, ValidationError=errors.ValidationError, AuditRepository=audit_repo.AuditRepository, SessionRepository=users_repo.SessionRepository, UserRepository=users_repo.UserRepository, auth_service=auth_service)
course_service = _mod_course_service(config=config, clock=clock, ids=ids, permissions=permissions, validators=validators, ConflictError=errors.ConflictError, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, ValidationError=errors.ValidationError, AuditRepository=audit_repo.AuditRepository, ClassRepository=courses_repo.ClassRepository, CourseRepository=courses_repo.CourseRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, UserRepository=users_repo.UserRepository)
assignment_service = _mod_assignment_service(config=config, clock=clock, permissions=permissions, validators=validators, ConflictError=errors.ConflictError, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, AssignmentRepository=assignments_repo.AssignmentRepository, SubmissionRepository=assignments_repo.SubmissionRepository, AuditRepository=audit_repo.AuditRepository, ClassRepository=courses_repo.ClassRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, UserRepository=users_repo.UserRepository, notify_class=notification_service.notify_class)
quiz_service = _mod_quiz_service(config=config, clock=clock, permissions=permissions, validators=validators, ConflictError=errors.ConflictError, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, AuditRepository=audit_repo.AuditRepository, NotificationRepository=content_repo.NotificationRepository, ClassRepository=courses_repo.ClassRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, AttemptRepository=quizzes_repo.AttemptRepository, QuestionRepository=quizzes_repo.QuestionRepository, QuizRepository=quizzes_repo.QuizRepository, notify_class=notification_service.notify_class)
attendance_service = _mod_attendance_service(config=config, clock=clock, ids=ids, permissions=permissions, validators=validators, ConflictError=errors.ConflictError, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, AttendanceRecordRepository=attendance_repo.AttendanceRecordRepository, AttendanceSessionRepository=attendance_repo.AttendanceSessionRepository, AuditRepository=audit_repo.AuditRepository, ClassRepository=courses_repo.ClassRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, notify_class=notification_service.notify_class)
grade_service = _mod_grade_service(config=config, permissions=permissions, validators=validators, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, ValidationError=errors.ValidationError, connection=connection, AssignmentRepository=assignments_repo.AssignmentRepository, SubmissionRepository=assignments_repo.SubmissionRepository, AttendanceRecordRepository=attendance_repo.AttendanceRecordRepository, ClassRepository=courses_repo.ClassRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, GradeItemRepository=grades_repo.GradeItemRepository, GradeRuleRepository=grades_repo.GradeRuleRepository, UserRepository=users_repo.UserRepository)
resource_service = _mod_resource_service(config=config, clock=clock, ids=ids, permissions=permissions, validators=validators, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, TooLargeError=errors.TooLargeError, safe_join=static_lib.safe_join, AuditRepository=audit_repo.AuditRepository, ResourceRepository=content_repo.ResourceRepository, ClassRepository=courses_repo.ClassRepository, CourseRepository=courses_repo.CourseRepository, EnrollmentRepository=courses_repo.EnrollmentRepository)
discussion_service = _mod_discussion_service(permissions=permissions, validators=validators, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, AuditRepository=audit_repo.AuditRepository, DiscussionRepository=content_repo.DiscussionRepository, ReplyRepository=content_repo.ReplyRepository, ClassRepository=courses_repo.ClassRepository, CourseRepository=courses_repo.CourseRepository, EnrollmentRepository=courses_repo.EnrollmentRepository)
chapter_service = _mod_chapter_service(clock=clock, permissions=permissions, validators=validators, ForbiddenError=errors.ForbiddenError, NotFoundError=errors.NotFoundError, ValidationError=errors.ValidationError, AssignmentRepository=assignments_repo.AssignmentRepository, AuditRepository=audit_repo.AuditRepository, ChapterRepository=chapters_repo.ChapterRepository, TaskProgressRepository=chapters_repo.TaskProgressRepository, TaskRepository=chapters_repo.TaskRepository, ResourceRepository=content_repo.ResourceRepository, ClassRepository=courses_repo.ClassRepository, CourseRepository=courses_repo.CourseRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, QuizRepository=quizzes_repo.QuizRepository)
statistics_service = _mod_statistics_service(clock=clock, permissions=permissions, connection=connection, AuditRepository=audit_repo.AuditRepository, ClassRepository=courses_repo.ClassRepository, CourseRepository=courses_repo.CourseRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, UserRepository=users_repo.UserRepository)
request_lib = _mod_request_lib(MAX_BODY_BYTES=config.MAX_BODY_BYTES, TooLargeError=errors.TooLargeError, ValidationError=errors.ValidationError, safe_int=ids.safe_int)
router_lib = _mod_router_lib(MethodNotAllowedError=errors.MethodNotAllowedError, NotFoundError=errors.NotFoundError, Request=request_lib.Request, Response=response_lib.Response)
multipart_lib = _mod_multipart_lib(ValidationError=errors.ValidationError)
server_lib = _mod_server_lib(config=config, AppError=errors.AppError, TooLargeError=errors.TooLargeError, Request=request_lib.Request, build_request=request_lib.build_request, Response=response_lib.Response, error_response=response_lib.error_response, json_response=response_lib.json_response)
seed_lib = _mod_seed_lib(config=config, clock=clock, ids=ids, security=security, connection=connection, migrations=migrations, AssignmentRepository=assignments_repo.AssignmentRepository, SubmissionRepository=assignments_repo.SubmissionRepository, AttendanceRecordRepository=attendance_repo.AttendanceRecordRepository, AttendanceSessionRepository=attendance_repo.AttendanceSessionRepository, SettingRepository=audit_repo.SettingRepository, ChapterRepository=chapters_repo.ChapterRepository, TaskProgressRepository=chapters_repo.TaskProgressRepository, TaskRepository=chapters_repo.TaskRepository, DiscussionRepository=content_repo.DiscussionRepository, NotificationRepository=content_repo.NotificationRepository, ReplyRepository=content_repo.ReplyRepository, ResourceRepository=content_repo.ResourceRepository, ClassRepository=courses_repo.ClassRepository, CourseRepository=courses_repo.CourseRepository, EnrollmentRepository=courses_repo.EnrollmentRepository, GradeItemRepository=grades_repo.GradeItemRepository, GradeRuleRepository=grades_repo.GradeRuleRepository, AttemptRepository=quizzes_repo.AttemptRepository, QuestionRepository=quizzes_repo.QuestionRepository, QuizRepository=quizzes_repo.QuizRepository, UserRepository=users_repo.UserRepository)
auth_api = _mod_auth_api(permissions=permissions, validators=validators, Response=response_lib.Response, ok=response_lib.ok, Router=router_lib.Router, auth_service=auth_service)
user_api = _mod_user_api(permissions=permissions, validators=validators, Response=response_lib.Response, created=response_lib.created, ok=response_lib.ok, paginated=response_lib.paginated, Router=router_lib.Router, CourseRepository=courses_repo.CourseRepository, user_service=user_service)
course_api = _mod_course_api(permissions=permissions, validators=validators, Response=response_lib.Response, created=response_lib.created, ok=response_lib.ok, paginated=response_lib.paginated, Router=router_lib.Router, course_service=course_service)
chapter_api = _mod_chapter_api(permissions=permissions, Response=response_lib.Response, created=response_lib.created, ok=response_lib.ok, Router=router_lib.Router, chapter_service=chapter_service)
assignment_api = _mod_assignment_api(permissions=permissions, validators=validators, Response=response_lib.Response, created=response_lib.created, ok=response_lib.ok, Router=router_lib.Router, multipart=multipart_lib, file_response=response_lib.file_response, assignment_service=assignment_service, attachment_service=attachment_service)
quiz_api = _mod_quiz_api(permissions=permissions, validators=validators, Response=response_lib.Response, created=response_lib.created, ok=response_lib.ok, Router=router_lib.Router, quiz_service=quiz_service)
attendance_api = _mod_attendance_api(permissions=permissions, validators=validators, Response=response_lib.Response, created=response_lib.created, ok=response_lib.ok, Router=router_lib.Router, attendance_service=attendance_service)
grade_api = _mod_grade_api(permissions=permissions, Response=response_lib.Response, ok=response_lib.ok, Router=router_lib.Router, grade_service=grade_service)
content_api = _mod_content_api(permissions=permissions, validators=validators, multipart=multipart_lib, Response=response_lib.Response, created=response_lib.created, file_response=response_lib.file_response, ok=response_lib.ok, paginated=response_lib.paginated, Router=router_lib.Router, announcement_service=announcement_service, discussion_service=discussion_service, notification_service=notification_service, resource_service=resource_service)
report_api = _mod_report_api(permissions=permissions, validators=validators, Response=response_lib.Response, ok=response_lib.ok, paginated=response_lib.paginated, Router=router_lib.Router, AuditRepository=audit_repo.AuditRepository, statistics_service=statistics_service)
system_api = _mod_system_api(config=config, clock=clock, errors=errors, permissions=permissions, validators=validators, Response=response_lib.Response, file_response=response_lib.file_response, ok=response_lib.ok, backup_service=backup_service, search_service=search_service, Router=router_lib.Router, AuditRepository=audit_repo.AuditRepository, SettingRepository=audit_repo.SettingRepository, connection=connection)

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
