"""自助注册：学生和教师共用。

只要姓名、学号/工号、密码；用户名就是姓名（重名自动加序号）。
不填邀请码，入班由教师后续添加或学生自己用邀请码加入。
"""

from __future__ import annotations

from typing import Any

from backend.core import permissions, security, validators
from backend.core.errors import ConflictError, ValidationError
from backend.repositories.audit import AuditRepository
from backend.repositories.users import UserRepository
from backend.services import group_service

user_repo = UserRepository()
audit_repo = AuditRepository()

ALLOWED_ROLES = (permissions.ROLE_STUDENT, permissions.ROLE_TEACHER)


def _unique_username(base: str) -> str:
    """用户名默认等于姓名；重名时依次加 2、3……"""
    name = base.strip()
    if not user_repo.by_username(name):
        return name
    for i in range(2, 200):
        candidate = f"{name}{i}"
        if not user_repo.by_username(candidate):
            return candidate
    raise ConflictError("同名账号过多，请换一个名字注册")


def register(payload: dict[str, Any], *, ip: str = "") -> dict[str, Any]:
    real_name = validators.required_str(payload, "real_name", min_len=1, max_len=32)
    number = validators.required_str(payload, "number", min_len=2, max_len=32)
    password = validators.required_str(payload, "password", min_len=6, max_len=128, strip=False)
    role = validators.optional_str(payload, "role", permissions.ROLE_STUDENT, max_len=16)
    if role not in ALLOWED_ROLES:
        raise ValidationError("只能注册为学生或教师")

    class_name = validators.required_str(payload, "class_name", min_len=2, max_len=64)

    if user_repo.by_number(number):
        raise ConflictError("该学号/工号已存在账号，无法重复注册，请直接登录")

    username = _unique_username(real_name)
    digest, salt = security.hash_password(password)

    user_id = user_repo.insert(
        {
            "username": username,
            "password_hash": digest,
            "password_salt": salt,
            "role": role,
            "real_name": real_name,
            "number": number,
            "class_name": class_name,
            "status": "active",
            "must_change_password": 0,
        }
    )

    joined_group = None
    if class_name:
        group = group_service.join_group_by_name(
            {"id": user_id, "role": role, "username": username}, class_name
        )
        joined_group = {"id": int(group["id"]), "name": group["name"]}

        audit_repo.log(
        user_id=user_id,
        username=username,
        action="self_register",
        entity="user",
        entity_id=user_id,
        detail=f"{permissions.ROLE_LABELS.get(role, role)}自助注册（{ip}）",
        ip=ip,
    )
    if role == permissions.ROLE_STUDENT:
        try:
            group_service.refresh_offers(user_repo.find(user_id) or {})
        except Exception:  # noqa: BLE001
            pass

    return {
        "joined_group": joined_group,
        "user": {
            "id": user_id,
            "username": username,
            "real_name": real_name,
            "role": role,
        },
        "login_hint": f"用户名就是你的姓名：{username}",
    }
