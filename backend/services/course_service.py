"""课程与教学班服务。

包含课程 CRUD、开课、教学班管理、选课/退课，以及所有权限校验。
"""

from __future__ import annotations

import logging
from typing import Any

from backend import config
from backend.core import clock, ids, permissions, validators
from backend.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from backend.db import connection
from backend.repositories.audit import AuditRepository
from backend.repositories.courses import (
    ClassRepository,
    CourseRepository,
    EnrollmentRepository,
)
from backend.repositories.users import UserRepository

logger = logging.getLogger("eduflow.course")

course_repo = CourseRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
user_repo = UserRepository()
audit_repo = AuditRepository()


# ---------------------------------------------------------------------------
# 课程
# ---------------------------------------------------------------------------


def list_courses(
    viewer: dict[str, Any],
    *,
    term: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = config.DEFAULT_PAGE_SIZE,
) -> tuple[list[dict[str, Any]], int]:
    page, page_size = validators.clamp_page(page, page_size)
    offset = (page - 1) * page_size
    if viewer["role"] == permissions.ROLE_ADMIN:
        items = course_repo.list_courses(
            term=term, keyword=keyword, limit=page_size, offset=offset
        )
        total = course_repo.count_courses(term=term, keyword=keyword)
    elif viewer["role"] == permissions.ROLE_TEACHER:
        items = course_repo.list_courses(
            teacher_id=int(viewer["id"]), term=term, keyword=keyword,
            limit=page_size, offset=offset,
        )
        total = course_repo.count_courses(
            teacher_id=int(viewer["id"]), term=term, keyword=keyword
        )
    else:
        # 学生可见全部已开设课程；已选课的标记出来
        items = course_repo.list_courses(term=term, keyword=keyword)
        total = len(items)
        enrolled_ids = {
            int(r["course_id"])
            for r in connection.query_all(
                """SELECT DISTINCT cl.course_id FROM enrollments e
                     JOIN classes cl ON cl.id = e.class_id
                    WHERE e.student_id = ? AND e.status = 'active'""",
                (int(viewer["id"]),),
            )
        }
        for item in items:
            item["enrolled"] = int(item["id"]) in enrolled_ids
        items = items[offset : offset + page_size]
        total = len(course_repo.list_courses(term=term, keyword=keyword))
    return items, total


def get_course(viewer: dict[str, Any], course_id: int) -> dict[str, Any]:
    course = course_repo.detail(course_id)
    if course is None:
        raise NotFoundError("课程不存在")
    enrolled = enroll_repo.class_ids_of_student(int(viewer["id"]))
    course_class_ids = {int(item["id"]) for item in class_repo.of_course(course_id)}
    permissions.assert_can_view_course(
        viewer, course, enrolled=bool(course_class_ids & set(enrolled))
    )
    course["classes"] = class_repo.of_course(course_id)
    return course


def create_course(payload: dict[str, Any], operator: dict[str, Any]) -> dict[str, Any]:
    permissions.require_teacher(operator)
    code = validators.required_str(payload, "code", min_len=2, max_len=32).upper()
    name = validators.required_str(payload, "name", min_len=2, max_len=64)
    if course_repo.by_code(code):
        raise ConflictError(f"课程代码 {code} 已存在")

    if operator["role"] == permissions.ROLE_ADMIN:
        teacher_id = validators.optional_int(payload, "teacher_id", int(operator["id"]))
    else:
        teacher_id = int(operator["id"])
    teacher = user_repo.find_or_fail(int(teacher_id), "指定的教师不存在")
    if teacher["role"] not in (permissions.ROLE_TEACHER, permissions.ROLE_ADMIN):
        raise ValidationError("指定用户不是教师")

    term = validators.optional_str(payload, "term", clock.term_of(), max_len=16)
    credits = validators.optional_float(payload, "credits", 2.0, min_value=0.5, max_value=20)
    hours = validators.optional_int(payload, "hours", 32, min_value=1, max_value=200)
    category = validators.optional_str(payload, "category", "必修", max_len=16)
    description = validators.optional_str(payload, "description", "", max_len=2000)

    course_id = course_repo.insert(
        {
            "code": code,
            "name": name,
            "teacher_id": int(teacher_id),
            "term": term,
            "credits": credits,
            "hours": hours,
            "category": category,
            "description": description,
            "status": "active",
        }
    )
    # 建课同时开一个默认教学班，省去用户再点一次
    class_repo.insert(
        {
            "course_id": course_id,
            "name": f"{name}-01班",
            "join_code": _unique_join_code(),
            "semester": term,
            "capacity": 60,
        }
    )
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="create_course",
        entity="course",
        entity_id=course_id,
        detail=f"新建课程 {name}({code})",
    )
    return course_repo.detail(course_id) or {}


def update_course(course_id: int, payload: dict[str, Any],
                  operator: dict[str, Any]) -> dict[str, Any]:
    course = course_repo.find_or_fail(course_id, "课程不存在")
    permissions.assert_can_manage_course(operator, course)

    updates: dict[str, Any] = {}
    for field, max_len in (
        ("name", 64), ("category", 16), ("cover", 500), ("description", 2000),
    ):
        if field in payload:
            updates[field] = validators.optional_str(payload, field, "", max_len=max_len)
    if "name" in updates and not updates["name"]:
        raise ValidationError("课程名称不能为空")
    if "term" in payload:
        updates["term"] = validators.required_str(payload, "term", max_len=16)
    if "credits" in payload:
        updates["credits"] = validators.optional_float(
            payload, "credits", 2.0, min_value=0.5, max_value=20
        )
    if "hours" in payload:
        updates["hours"] = validators.optional_int(payload, "hours", 32, min_value=1, max_value=200)
    if "status" in payload:
        updates["status"] = validators.ensure_enum(
            str(payload["status"]), ("active", "archived"), "课程状态"
        )
    if "teacher_id" in payload and operator["role"] == permissions.ROLE_ADMIN:
        updates["teacher_id"] = validators.required_int(payload, "teacher_id", min_value=1)

    if updates:
        course_repo.update(course_id, updates)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="update_course",
            entity="course",
            entity_id=course_id,
            detail=f"更新课程字段：{', '.join(updates)}",
        )
    return course_repo.detail(course_id) or {}


# ---------------------------------------------------------------------------
# 教学班
# ---------------------------------------------------------------------------


def _unique_join_code() -> str:
    for _ in range(30):
        code = ids.new_join_code()
        if not class_repo.by_join_code(code):
            return code
    raise RuntimeError("生成邀请码失败，请重试")


def list_classes(viewer: dict[str, Any]) -> list[dict[str, Any]]:
    if viewer["role"] == permissions.ROLE_ADMIN:
        rows = class_repo.all(order_by="id DESC")
        result = []
        for row in rows:
            detail = class_repo.detail(int(row["id"]))
            if detail:
                result.append(detail)
        return result
    if viewer["role"] == permissions.ROLE_TEACHER:
        return class_repo.of_teacher(int(viewer["id"]))
    return [item for item in course_repo.of_student(int(viewer["id"]))]


def create_class(course_id: int, payload: dict[str, Any],
                 operator: dict[str, Any]) -> dict[str, Any]:
    course = course_repo.find_or_fail(course_id, "课程不存在")
    permissions.assert_can_manage_course(operator, course)
    name = validators.required_str(payload, "name", min_len=1, max_len=64)
    capacity = validators.optional_int(payload, "capacity", 60, min_value=1, max_value=500)
    schedule = validators.optional_str(payload, "schedule", "", max_len=64)
    location = validators.optional_str(payload, "location", "", max_len=64)

    class_id = class_repo.insert(
        {
            "course_id": course_id,
            "name": name,
            "join_code": _unique_join_code(),
            "semester": course.get("term") or clock.term_of(),
            "capacity": capacity,
            "schedule": schedule,
            "location": location,
        }
    )
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="create_class",
        entity="class",
        entity_id=class_id,
        detail=f"新建教学班 {name}",
    )
    return class_repo.detail(class_id) or {}


def get_class(viewer: dict[str, Any], class_id: int) -> dict[str, Any]:
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    _assert_class_access(viewer, detail)
    detail["students"] = class_repo.students(class_id)
    detail["student_count"] = len(detail["students"])
    return detail


def _assert_class_access(viewer: dict[str, Any], class_detail: dict[str, Any]) -> None:
    if viewer["role"] == permissions.ROLE_ADMIN:
        return
    if int(class_detail.get("teacher_id") or 0) == int(viewer["id"]):
        return
    if viewer["role"] == permissions.ROLE_STUDENT:
        if enroll_repo.is_enrolled(int(class_detail["id"]), int(viewer["id"])):
            return
    raise ForbiddenError("无权访问该教学班")


def join_class(student: dict[str, Any], code: str) -> dict[str, Any]:
    """学生凭邀请码加入教学班。"""
    permissions.require_role(student, permissions.ROLE_STUDENT)
    code = validators.validate_code(code, "邀请码")
    target = class_repo.by_join_code(code)
    if target is None:
        raise NotFoundError("邀请码无效")
    if target["status"] != "active":
        raise ValidationError("该教学班已关闭选课")
    if enroll_repo.is_enrolled(int(target["id"]), int(student["id"])):
        raise ConflictError("你已经加入该教学班")
    current = class_repo.student_count(int(target["id"]))
    if current >= int(target.get("capacity") or 60):
        raise ValidationError("教学班人数已满")
    enroll_repo.enroll(int(target["id"]), int(student["id"]), source="self")
    audit_repo.log(
        user_id=int(student["id"]),
        username=student["username"],
        action="join_class",
        entity="class",
        entity_id=int(target["id"]),
        detail=f"凭邀请码 {code} 加入教学班",
    )
    return class_repo.detail(int(target["id"])) or {}


def add_student(class_id: int, student_id: int, operator: dict[str, Any]) -> dict[str, Any]:
    """教师/管理员手动把学生加入教学班。"""
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    permissions.assert_can_manage_course(operator, detail)
    student = user_repo.find_or_fail(student_id, "学生不存在")
    if student["role"] != permissions.ROLE_STUDENT:
        raise ValidationError("只能添加学生账号")
    enroll_repo.enroll(class_id, student_id, source="admin")
    return {"class_id": class_id, "student_id": student_id, "action": "added"}


def drop_student(class_id: int, student_id: int, operator: dict[str, Any]) -> dict[str, Any]:
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    permissions.assert_can_manage_course(operator, detail)
    enroll_repo.drop(class_id, student_id)
    return {"class_id": class_id, "student_id": student_id, "action": "dropped"}


def leave_class(student: dict[str, Any], class_id: int) -> dict[str, Any]:
    if not enroll_repo.is_enrolled(class_id, int(student["id"])):
        raise ValidationError("你还没有加入该教学班")
    enroll_repo.drop(class_id, int(student["id"]))
    audit_repo.log(
        user_id=int(student["id"]),
        username=student["username"],
        action="leave_class",
        entity="class",
        entity_id=class_id,
        detail="退出教学班",
    )
    return {"class_id": class_id, "action": "left"}


def class_students(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    _assert_class_access(viewer, detail)
    return class_repo.students(class_id)


def teacher_overview(teacher: dict[str, Any]) -> dict[str, Any]:
    """教师工作台的汇总数字。"""
    from backend.repositories.assignments import AssignmentRepository

    classes = class_repo.of_teacher(int(teacher["id"]))
    class_ids = [int(item["id"]) for item in classes]
    total_students = sum(int(item.get("student_count") or 0) for item in classes)
    pending = 0
    assignment_repo = AssignmentRepository()
    for class_id in class_ids:
        assignments = assignment_repo.list_by_class(class_id, limit=200)
        for item in assignments:
            if item.get("status") == "published":
                pending += max(
                    0, int(item.get("student_total") or 0) - int(item.get("submission_count") or 0)
                )
    return {
        "class_count": len(classes),
        "student_count": total_students,
        "pending_submissions": pending,
        "courses": classes,
    }
