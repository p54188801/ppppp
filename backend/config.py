"""全局配置。

所有路径、端口、安全参数集中在这里，方便打包和二次部署。
支持通过环境变量覆盖，便于测试时使用临时目录。
"""

from __future__ import annotations

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

BASE_DIR = Path(__file__).resolve().parent.parent

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
