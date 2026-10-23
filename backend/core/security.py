"""密码哈希、令牌、签名等安全原语。

刻意只用标准库：
- 口令用 PBKDF2-HMAC-SHA256（加盐、迭代 18 万次）；
- 比较用 hmac.compare_digest，防时序攻击；
- 一次性签名用 HMAC-SHA256，用于防篡改的快照数据。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import string
from typing import Any

from backend.config import PASSWORD_ITERATIONS, PASSWORD_KEY_LEN
from backend.core.errors import ValidationError

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
