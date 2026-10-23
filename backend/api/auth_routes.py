"""认证相关接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http.response import Response, ok
from backend.http.router import Router
from backend.services import auth_service

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
