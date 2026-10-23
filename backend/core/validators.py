"""请求参数校验与类型转换工具。

设计原则：
- 所有从 HTTP 进来的数据都不可信，必须先过这里；
- 校验失败抛 ValidationError，由 HTTP 层统一转成 400；
- 每个函数只做一件事，方便组合和单测。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from backend.core import clock
from backend.core.errors import ValidationError

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
