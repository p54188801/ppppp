-- =====================================================================
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
CREATE INDEX IF NOT EXISTS idx_task_progress_task    ON task_progress(task_id, status);