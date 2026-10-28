"""用户管理服务：增删改查、批量导入、状态切换。"""

from __future__ import annotations

import csv
import io
from typing import Any

from backend import config
from backend.core import clock, permissions, security, validators
from backend.db import connection
from backend.core.errors import ConflictError, NotFoundError, ValidationError
from backend.repositories.audit import AuditRepository
from backend.repositories.users import SessionRepository, UserRepository
from backend.services import auth_service

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

def kick_user(user_id: int, *, operator: dict[str, Any]) -> dict[str, Any]:
    """强制下线：吊销该用户所有会话，不影响账号状态。"""
    user = user_repo.find_or_fail(user_id, "用户不存在")
    if int(user["id"]) == int(operator["id"]):
        raise ValidationError("不能把自己踢下线")
    count = session_repo.revoke_all_for_user(user_id)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="kick_user",
        entity="user",
        entity_id=user_id,
        detail=f"强制下线 {user['username']}（吊销 {count} 个会话）",
    )
    return {"user_id": user_id, "revoked": count}


def cancel_account(user_id: int, *, operator: dict[str, Any]) -> dict[str, Any]:
    """注销账号：停用并吊销会话，数据保留（可由管理员恢复）。"""
    user = user_repo.find_or_fail(user_id, "用户不存在")
    if int(user["id"]) == int(operator["id"]):
        raise ValidationError("不能注销自己的账号")
    user_repo.set_status(user_id, "disabled")
    session_repo.revoke_all_for_user(user_id)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="cancel_account",
        entity="user",
        entity_id=user_id,
        detail=f"注销账号 {user['username']}",
    )
    return {"user_id": user_id, "status": "disabled"}

def update_profile(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """用户自助修改资料。

    姓名修改时会同步登录名（若登录名原本就是旧姓名）；学号/工号需保持唯一；
    班级变更会自动切换到新的班级群。
    """
    user_id = int(user["id"])
    current = user_repo.find_or_fail(user_id, "用户不存在")
    updates: dict[str, Any] = {}
    old_class = current.get("class_name") or ""
    new_class = old_class

    if "real_name" in payload:
        real_name = validators.required_str(payload, "real_name", min_len=1, max_len=32)
        updates["real_name"] = real_name
        # 登录名与旧姓名一致时同步；否则保持原登录名（避免影响登录习惯）
        if current.get("username") == current.get("real_name"):
            candidate = real_name
            if candidate != current["username"] and not user_repo.by_username(candidate):
                updates["username"] = candidate
    if "number" in payload:
        number = validators.optional_str(payload, "number", "", max_len=32)
        if number and number != (current.get("number") or ""):
            other = user_repo.by_number(number)
            if other and int(other["id"]) != user_id:
                raise ConflictError(f"学号/工号 {number} 已被占用")
        updates["number"] = number
    if "department" in payload:
        updates["department"] = validators.optional_str(payload, "department", "", max_len=64)
    if "class_name" in payload:
        new_class = validators.optional_str(payload, "class_name", "", max_len=64)
        updates["class_name"] = new_class
    if "email" in payload:
        updates["email"] = validators.validate_email(
            validators.optional_str(payload, "email", "", max_len=128)
        )
    if "phone" in payload:
        updates["phone"] = validators.validate_phone(
            validators.optional_str(payload, "phone", "", max_len=20)
        )

    if not updates:
        return auth_service.to_public(current) or {}

    user_repo.update(user_id, updates)

    # 班级变了 → 切换班级群
    if new_class and new_class != old_class:
        from backend.services import group_service

        group = group_service.join_group_by_name(
            {"id": user_id, "role": current["role"], "username": current.get("username", "")},
            new_class,
        )
        # 退出旧班群
        if old_class:
            old = connection.query_one(
                "SELECT id FROM class_groups WHERE name = ?", (old_class,)
            )
            if old and int(old["id"]) != int(group["id"]):
                connection.execute(
                    "DELETE FROM group_members WHERE group_id = ? AND user_id = ?",
                    (int(old["id"]), user_id),
                )

    audit_repo.log(
        user_id=user_id,
        username=current.get("username", ""),
        action="update_profile",
        entity="user",
        entity_id=user_id,
        detail=f"自助修改资料：{', '.join(updates.keys())}",
    )
    return auth_service.to_public(user_repo.find(user_id)) or {}

def forgot_password(payload: dict[str, Any], *, ip: str = "") -> dict[str, Any]:
    """凭「学号/工号 + 姓名」重置为临时密码。

    这是没有短信/邮件的校园小型部署方案：只核对身份信息，
    重置后强制下次登录修改密码，并吊销所有旧会话。
    """
    import secrets

    from backend.core import security

    number = validators.required_str(payload, "number", min_len=2, max_len=32)
    real_name = validators.required_str(payload, "real_name", min_len=1, max_len=32)

    user = user_repo.by_number(number)
    if user is None or (user.get("real_name") or "").strip() != real_name.strip():
        audit_repo.log(
            user_id=None, username=number, action="forgot_password_failed",
            entity="user", entity_id=None, detail=f"身份不匹配（{ip}）", ip=ip,
        )
        raise ValidationError("学号与姓名不匹配，请检查后重试")

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    temp = "".join(secrets.choice(alphabet) for _ in range(8))
    digest, salt = security.hash_password(temp)
    user_repo.update(int(user["id"]), {
        "password_hash": digest,
        "password_salt": salt,
        "must_change_password": 1,
    })
    session_repo.revoke_all_for_user(int(user["id"]))
    audit_repo.log(
        user_id=int(user["id"]), username=user["username"], action="forgot_password",
        entity="user", entity_id=int(user["id"]), detail=f"自助重置为临时密码（{ip}）", ip=ip,
    )
    return {
        "username": user["username"],
        "real_name": user.get("real_name"),
        "temp_password": temp,
        "hint": "登录后用临时密码修改成自己的密码",
    }
