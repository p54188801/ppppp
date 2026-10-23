"""主键、令牌、短码等标识符的生成工具。

不用 uuid4 作为对外主键，而是：
- 数据库主键用自增整数（查询快、分页方便）；
- 对外暴露的分享码、邀请码用可读的短码（去掉易混淆字符）；
- 会话令牌用高熵随机串。
"""

from __future__ import annotations

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
