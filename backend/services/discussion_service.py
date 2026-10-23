"""课程讨论区服务。"""

from __future__ import annotations

from typing import Any

from backend.core import permissions, validators
from backend.core.errors import ForbiddenError, NotFoundError
from backend.repositories.audit import AuditRepository
from backend.repositories.content import DiscussionRepository, ReplyRepository
from backend.repositories.courses import ClassRepository, CourseRepository, EnrollmentRepository

discussion_repo = DiscussionRepository()
reply_repo = ReplyRepository()
course_repo = CourseRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
audit_repo = AuditRepository()


def _course_or_fail(course_id: int) -> dict[str, Any]:
    detail = course_repo.detail(course_id)
    if detail is None:
        raise NotFoundError("课程不存在")
    return detail


def _assert_view(viewer: dict[str, Any], course: dict[str, Any]) -> None:
    class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
    enrolled = bool(class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"]))))
    permissions.assert_can_view_course(viewer, course, enrolled=enrolled)


def list_threads(viewer: dict[str, Any], course_id: int) -> list[dict[str, Any]]:
    course = _course_or_fail(course_id)
    _assert_view(viewer, course)
    return discussion_repo.list_by_course(course_id)


def create_thread(viewer: dict[str, Any], course_id: int,
                  payload: dict[str, Any]) -> dict[str, Any]:
    course = _course_or_fail(course_id)
    _assert_view(viewer, course)
    title = validators.required_str(payload, "title", min_len=2, max_len=120)
    content = validators.optional_str(payload, "content", "", max_len=20000)
    discussion_id = discussion_repo.insert(
        {
            "course_id": course_id,
            "title": title,
            "content": content,
            "author_id": int(viewer["id"]),
        }
    )
    audit_repo.log(
        user_id=int(viewer["id"]),
        username=viewer["username"],
        action="create_discussion",
        entity="discussion",
        entity_id=discussion_id,
        detail=title,
    )
    return discussion_repo.detail(discussion_id) or {}


def get_thread(viewer: dict[str, Any], discussion_id: int) -> dict[str, Any]:
    thread = discussion_repo.detail(discussion_id)
    if thread is None:
        raise NotFoundError("话题不存在")
    course = _course_or_fail(int(thread["course_id"]))
    _assert_view(viewer, course)
    discussion_repo.increment_views(discussion_id)
    thread["replies"] = reply_repo.list_by_discussion(discussion_id)
    thread["reply_count"] = len(thread["replies"])
    return thread


def reply(viewer: dict[str, Any], discussion_id: int,
          payload: dict[str, Any]) -> dict[str, Any]:
    thread = discussion_repo.find_or_fail(discussion_id, "话题不存在")
    course = _course_or_fail(int(thread["course_id"]))
    _assert_view(viewer, course)
    if thread.get("locked"):
        raise ForbiddenError("该话题已锁定，不能再回复")

    content = validators.required_str(payload, "content", min_len=1, max_len=10000)
    parent_id = validators.optional_int(payload, "parent_id", None)
    reply_id = reply_repo.insert(
        {
            "discussion_id": discussion_id,
            "author_id": int(viewer["id"]),
            "content": content,
            "parent_id": parent_id,
        }
    )
    return {"id": reply_id, "discussion_id": discussion_id, "content": content}


def set_flags(viewer: dict[str, Any], discussion_id: int,
              payload: dict[str, Any]) -> dict[str, Any]:
    """置顶 / 锁定 / 删除（教师或管理员）。"""
    thread = discussion_repo.find_or_fail(discussion_id, "话题不存在")
    course = _course_or_fail(int(thread["course_id"]))
    permissions.assert_can_manage_course(viewer, course)

    if "pinned" in payload:
        discussion_repo.update(discussion_id, {"pinned": 1 if validators.to_bool(payload["pinned"]) else 0})
    if "locked" in payload:
        discussion_repo.update(discussion_id, {"locked": 1 if validators.to_bool(payload["locked"]) else 0})
    if validators.to_bool(payload.get("delete"), False):
        discussion_repo.delete(discussion_id)
        return {"deleted": True, "discussion_id": discussion_id}
    return discussion_repo.detail(discussion_id) or {}


def delete_reply(viewer: dict[str, Any], reply_id: int) -> dict[str, Any]:
    item = reply_repo.find_or_fail(reply_id, "回复不存在")
    thread = discussion_repo.find_or_fail(int(item["discussion_id"]), "话题不存在")
    course = _course_or_fail(int(thread["course_id"]))
    if int(item["author_id"]) != int(viewer["id"]):
        permissions.assert_can_manage_course(viewer, course)
    reply_repo.delete(reply_id)
    return {"deleted": True, "reply_id": reply_id}


def course_discussion_summary(course_id: int) -> dict[str, Any]:
    threads = discussion_repo.list_by_course(course_id)
    total_replies = sum(int(item.get("reply_count") or 0) for item in threads)
    return {
        "threads": len(threads),
        "replies": total_replies,
        "last_active": threads[0]["created_at"] if threads else None,
    }
