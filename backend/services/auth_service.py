"""认证服务：登录、登出、会话解析、改密。

这里承担了所有"谁能进来"的判断：
- 口令校验（PBKDF2）
- 失败次数锁定
- 令牌下发与吊销
- 账号状态检查
"""

from __future__ import annotations

import logging
from typing import Any

from backend import config
from backend.core import clock, ids, permissions, security
from backend.core.errors import (
    ForbiddenError,
    RateLimitError,
    UnauthorizedError,
    ValidationError,
)
from backend.repositories.audit import AuditRepository
from backend.repositories.users import (
    LoginAttemptRepository,
    SessionRepository,
    UserRepository,
)

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
