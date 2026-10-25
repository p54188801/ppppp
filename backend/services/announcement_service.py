"""课程公告。

教师发公告，学生进课程或首页能看到；发布时顺带推一条站内通知。
"""

from __future__ import annotations

from typing import Any

from backend.core import permissions, validators
from backend.core.errors import NotFoundError
from backend.repositories.audit import AuditRepository
from backend.repositories.content import AnnouncementRepository
from backend.repositories.courses import ClassRepository, CourseRepository, EnrollmentRepository
from backend.services.notification_service import notify_many

announcement_repo = AnnouncementRepository()
course_repo = CourseRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
audit_repo = AuditRepository()


def _course_or_fail(course_id: int) -> dict[str, Any]:
    course = course_repo.detail(course_id)
    if course is None:
        raise NotFoundError("课程不存在")
    return course


def _assert_view(viewer: dict[str, Any], course: dict[str, Any]) -> None:
    class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
    enrolled = bool(class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"]))))
    permissions.assert_can_view_course(viewer, course, enrolled=enrolled)


def list_for_course(viewer: dict[str, Any], course_id: int) -> list[dict[str, Any]]:
    course = _course_or_fail(course_id)
    _assert_view(viewer, course)
    return announcement_repo.list_by_course(course_id)


def student_feed(student: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    permissions.require_role(student, permissions.ROLE_STUDENT)
    return announcement_repo.list_for_student(int(student["id"]), limit=limit)


def create(viewer: dict[str, Any], course_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    course = _course_or_fail(course_id)
    permissions.assert_can_manage_course(viewer, course)

    title = validators.required_str(payload, "title", min_len=2, max_len=120)
    content = validators.optional_str(payload, "content", "", max_len=20000)
    pinned = 1 if validators.to_bool(payload.get("pinned"), False) else 0

    announcement_id = announcement_repo.insert(
        {
            "course_id": course_id,
            "title": title,
            "content": content,
            "author_id": int(viewer["id"]),
            "pinned": pinned,
        }
    )

    students: list[int] = []
    for class_row in class_repo.of_course(course_id):
        students.extend(int(row["id"]) for row in class_repo.students(int(class_row["id"])))
    if students:
        notify_many(
            students,
            title=f"课程公告：{title}",
            content=f"{course['name']} 发布了新公告",
            category="announcement",
            link=f"/courses/{course_id}",
        )

    audit_repo.log(
        user_id=int(viewer["id"]),
        username=viewer["username"],
        action="create_announcement",
        entity="announcement",
        entity_id=announcement_id,
        detail=f"{course['name']} / {title}",
    )
    return announcement_repo.detail(announcement_id) or {}


def update(viewer: dict[str, Any], announcement_id: int,
           payload: dict[str, Any]) -> dict[str, Any]:
    item = announcement_repo.find_or_fail(announcement_id, "公告不存在")
    course = _course_or_fail(int(item["course_id"]))
    permissions.assert_can_manage_course(viewer, course)

    updates: dict[str, Any] = {}
    if "title" in payload:
        updates["title"] = validators.required_str(payload, "title", min_len=2, max_len=120)
    if "content" in payload:
        updates["content"] = validators.optional_str(payload, "content", "", max_len=20000)
    if "pinned" in payload:
        updates["pinned"] = 1 if validators.to_bool(payload.get("pinned")) else 0
    if updates:
        announcement_repo.update(announcement_id, updates)
    return announcement_repo.detail(announcement_id) or {}


def delete(viewer: dict[str, Any], announcement_id: int) -> None:
    item = announcement_repo.find_or_fail(announcement_id, "公告不存在")
    course = _course_or_fail(int(item["course_id"]))
    permissions.assert_can_manage_course(viewer, course)
    announcement_repo.delete(announcement_id)
    audit_repo.log(
        user_id=int(viewer["id"]),
        username=viewer["username"],
        action="delete_announcement",
        entity="announcement",
        entity_id=announcement_id,
        detail=item.get("title", ""),
    )
