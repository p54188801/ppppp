"""角色与权限判定。

不引入复杂的 RBAC 表，直接按业务语义写死几组判定函数，
调用处语义清晰，也便于审计。
"""

from __future__ import annotations

from typing import Any

from backend.core.errors import ForbiddenError, UnauthorizedError

ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"
ROLE_ADMIN = "admin"

ROLE_LABELS = {
    ROLE_STUDENT: "学生",
    ROLE_TEACHER: "教师",
    ROLE_ADMIN: "管理员",
}

ALL_ROLES = (ROLE_STUDENT, ROLE_TEACHER, ROLE_ADMIN)


def require_login(user: dict[str, Any] | None) -> dict[str, Any]:
    if not user:
        raise UnauthorizedError()
    if user.get("status") != "active":
        raise ForbiddenError("账号已被禁用")
    return user


def require_role(user: dict[str, Any] | None, *roles: str) -> dict[str, Any]:
    current = require_login(user)
    if current["role"] not in roles:
        raise ForbiddenError("当前角色无权访问")
    return current


def require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    return require_role(user, ROLE_ADMIN)


def require_teacher(user: dict[str, Any] | None) -> dict[str, Any]:
    return require_role(user, ROLE_TEACHER, ROLE_ADMIN)


def is_admin(user: dict[str, Any] | None) -> bool:
    return bool(user) and user.get("role") == ROLE_ADMIN


def is_teacher(user: dict[str, Any] | None) -> bool:
    return bool(user) and user.get("role") in (ROLE_TEACHER, ROLE_ADMIN)


def can_manage_course(user: dict[str, Any] | None, course: dict[str, Any]) -> bool:
    """管理员可管理所有课程；教师只能管理自己的课程。"""
    if not user:
        return False
    if user["role"] == ROLE_ADMIN:
        return True
    if user["role"] == ROLE_TEACHER:
        return int(course.get("teacher_id", 0)) == int(user["id"])
    return False


def assert_can_manage_course(user: dict[str, Any], course: dict[str, Any]) -> None:
    if not can_manage_course(user, course):
        raise ForbiddenError("只能管理自己的课程")


def can_view_course(user: dict[str, Any], course: dict[str, Any],
                    *, enrolled: bool = False) -> bool:
    """管理员、任课教师、已选课学生可见。"""
    if not user:
        return False
    if user["role"] == ROLE_ADMIN:
        return True
    if int(course.get("teacher_id", 0)) == int(user["id"]):
        return True
    return enrolled


def assert_can_view_course(user: dict[str, Any], course: dict[str, Any],
                           *, enrolled: bool = False) -> None:
    if not can_view_course(user, course, enrolled=enrolled):
        raise ForbiddenError("无权查看该课程")
