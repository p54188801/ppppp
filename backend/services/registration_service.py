"""学生自助注册。

只允许注册学生账号；可选填教学班邀请码，注册后直接入班。
管理员/教师账号仍然只能由管理员创建。
"""

from __future__ import annotations

from typing import Any

from backend.core import permissions, security, validators
from backend.core.errors import ConflictError, ValidationError
from backend.repositories.audit import AuditRepository
from backend.repositories.courses import ClassRepository, EnrollmentRepository
from backend.repositories.users import UserRepository

user_repo = UserRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
audit_repo = AuditRepository()


def register_student(payload: dict[str, Any], *, ip: str = "") -> dict[str, Any]:
    username = validators.validate_username(
        validators.required_str(payload, "username", min_len=3, max_len=32)
    )
    password = validators.required_str(payload, "password", min_len=6, max_len=128, strip=False)
    real_name = validators.required_str(payload, "real_name", min_len=1, max_len=32)
    number = validators.optional_str(payload, "number", "", max_len=32)
    department = validators.optional_str(payload, "department", "", max_len=64)
    class_name = validators.optional_str(payload, "class_name", "", max_len=64)
    email = validators.validate_email(validators.optional_str(payload, "email", "", max_len=128))
    phone = validators.validate_phone(validators.optional_str(payload, "phone", "", max_len=20))
    join_code = validators.optional_str(payload, "join_code", "", max_len=12).upper()

    if user_repo.by_username(username):
        raise ConflictError("用户名已被占用")
    if number and user_repo.by_number(number):
        raise ConflictError("学号已被注册")

    # 注册入口只允许学生，角色写死
    digest, salt = security.hash_password(password)
    user_id = user_repo.insert(
        {
            "username": username,
            "password_hash": digest,
            "password_salt": salt,
            "role": permissions.ROLE_STUDENT,
            "real_name": real_name,
            "number": number,
            "email": email,
            "phone": phone,
            "department": department,
            "class_name": class_name,
            "status": "active",
            "must_change_password": 0,
        }
    )

    joined: dict[str, Any] | None = None
    if join_code:
        target = class_repo.by_join_code(join_code)
        if target is None:
            raise ValidationError("邀请码无效")
        if target["status"] != "active":
            raise ValidationError("该教学班已关闭选课")
        if class_repo.student_count(int(target["id"])) >= int(target.get("capacity") or 60):
            raise ValidationError("教学班人数已满")
        enroll_repo.enroll(int(target["id"]), user_id, source="register")
        joined = {"class_id": int(target["id"]), "class_name": target["name"]}

    audit_repo.log(
        user_id=user_id,
        username=username,
        action="self_register",
        entity="user",
        entity_id=user_id,
        detail=f"学生自助注册{'，加入 ' + joined['class_name'] if joined else ''}（{ip}）",
        ip=ip,
    )
    return {
        "user": {"id": user_id, "username": username, "real_name": real_name, "role": "student"},
        "joined_class": joined,
    }
