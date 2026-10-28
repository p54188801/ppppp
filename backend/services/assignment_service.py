"""作业服务：发布、提交、批改、统计。

关键业务规则：
- 截止后是否允许提交，由作业的 allow_late 决定；
- 迟交按天扣分，扣分比例写在作业上，便于一门课一个口径；
- 每次提交都会写审计日志，方便教师追溯。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend import config
from backend.core import clock, permissions, validators
from backend.core.errors import ConflictError, ForbiddenError, NotFoundError
from backend.repositories.assignments import AssignmentRepository, SubmissionRepository
from backend.repositories.audit import AuditRepository
from backend.repositories.courses import ClassRepository, EnrollmentRepository
from backend.repositories.users import UserRepository
from backend.services.notification_service import notify_class

logger = logging.getLogger("eduflow.assignment")

assignment_repo = AssignmentRepository()
submission_repo = SubmissionRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
user_repo = UserRepository()
audit_repo = AuditRepository()


def _class_or_fail(class_id: int) -> dict[str, Any]:
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    return detail


def create_assignment(payload: dict[str, Any],
                      operator: dict[str, Any]) -> dict[str, Any]:
    permissions.require_teacher(operator)
    class_id = validators.required_int(payload, "class_id", min_value=1)
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)

    title = validators.required_str(payload, "title", min_len=1, max_len=120)
    content = validators.optional_str(payload, "content", "", max_len=20000)
    full_score = validators.optional_float(payload, "full_score", 100, min_value=1, max_value=1000)
    deadline = validators.validate_date(
        payload.get("deadline"), "截止时间", required_field=False
    )
    allow_late = validators.to_bool(payload.get("allow_late"), True)
    late_penalty = validators.optional_float(
        payload, "late_penalty", config.LATE_PENALTY_PER_DAY, min_value=0, max_value=1
    )
    attachments = payload.get("attachments") or []
    if not isinstance(attachments, list):
        raise validators.ValidationError("附件必须是数组")

    assignment_id = assignment_repo.insert(
        {
            "class_id": class_id,
            "title": title,
            "content": content,
            "attachments": json.dumps(attachments, ensure_ascii=False) if attachments else None,
            "full_score": full_score,
            "deadline": deadline or None,
            "allow_late": 1 if allow_late else 0,
            "late_penalty": late_penalty,
            "status": "published",
            "created_by": int(operator["id"]),
        }
    )
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="create_assignment",
        entity="assignment",
        entity_id=assignment_id,
        detail=f"{detail['course_name']} / {title}",
    )
    students = [int(row["id"]) for row in class_repo.students(class_id)]
    if students:
        notify_class(
            students,
            title=f"新作业：{title}",
            content=f"{detail['course_name']} 发布了新作业，截止时间 {deadline or '未设置'}",
            category="assignment",
            link=f"/assignments/{assignment_id}",
        )
    return assignment_repo.detail(assignment_id) or {}


def update_assignment(assignment_id: int, payload: dict[str, Any],
                      operator: dict[str, Any]) -> dict[str, Any]:
    assignment = assignment_repo.detail(assignment_id)
    if assignment is None:
        raise NotFoundError("作业不存在")
    detail = _class_or_fail(int(assignment["class_id"]))
    permissions.assert_can_manage_course(operator, detail)

    updates: dict[str, Any] = {}
    if "title" in payload:
        updates["title"] = validators.required_str(payload, "title", max_len=120)
    if "content" in payload:
        updates["content"] = validators.optional_str(payload, "content", "", max_len=20000)
    if "deadline" in payload:
        updates["deadline"] = validators.validate_date(
            payload.get("deadline"), "截止时间", required_field=False
        ) or None
    if "full_score" in payload:
        updates["full_score"] = validators.optional_float(
            payload, "full_score", 100, min_value=1, max_value=1000
        )
    if "allow_late" in payload:
        updates["allow_late"] = 1 if validators.to_bool(payload.get("allow_late")) else 0
    if "status" in payload:
        updates["status"] = validators.ensure_enum(
            str(payload["status"]), ("draft", "published", "closed"), "作业状态"
        )
    if updates:
        assignment_repo.update(assignment_id, updates)
    return assignment_repo.detail(assignment_id) or {}


def list_assignments(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
    detail = _class_or_fail(class_id)
    if viewer["role"] == permissions.ROLE_STUDENT and not enroll_repo.is_enrolled(
        class_id, int(viewer["id"])
    ):
        raise ForbiddenError("未选修该课程")
    if viewer["role"] != permissions.ROLE_STUDENT:
        permissions.assert_can_manage_course(viewer, detail)
    items = assignment_repo.list_by_class(class_id, limit=200)
    if viewer["role"] == permissions.ROLE_STUDENT:
        for item in items:
            submission = submission_repo.by_student(int(item["id"]), int(viewer["id"]))
            item["my_submission"] = submission
    return items


def student_assignments(viewer: dict[str, Any], status: str = "") -> list[dict[str, Any]]:
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    return assignment_repo.list_for_student(
        int(viewer["id"]), status=status, limit=200
    )


def get_assignment(viewer: dict[str, Any], assignment_id: int) -> dict[str, Any]:
    item = assignment_repo.detail(assignment_id)
    if item is None:
        raise NotFoundError("作业不存在")
    class_id = int(item["class_id"])
    detail = _class_or_fail(class_id)
    if viewer["role"] == permissions.ROLE_STUDENT:
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")
        item["my_submission"] = submission_repo.by_student(assignment_id, int(viewer["id"]))
    else:
        permissions.assert_can_manage_course(viewer, detail)
        item["stats"] = submission_repo.stats_for_assignment(assignment_id)
    item["deadline_state"] = clock.deadline_state(item.get("deadline"))
    return item


def submit(viewer: dict[str, Any], assignment_id: int,
           payload: dict[str, Any]) -> dict[str, Any]:
    """学生提交作业。"""
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    assignment = assignment_repo.detail(assignment_id)
    if assignment is None:
        raise NotFoundError("作业不存在")
    class_id = int(assignment["class_id"])
    if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
        raise ForbiddenError("未选修该课程")
    if assignment["status"] != "published":
        raise ConflictError("该作业当前不可提交")

    existing = submission_repo.by_student(assignment_id, int(viewer["id"]))
    if existing and existing.get("status") == "graded":
        raise ConflictError("作业已批改，不能重复提交")

    content = validators.optional_str(payload, "content", "", max_len=50000)
    attachments = payload.get("attachments") or []
    if not isinstance(attachments, list):
        raise validators.ValidationError("附件必须是数组")
    if not content.strip() and not attachments:
        raise validators.ValidationError("作业内容和附件不能同时为空")

    now = clock.utcnow()
    deadline = clock.parse_iso(assignment.get("deadline"))
    is_late = bool(deadline and now > deadline)
    if is_late and not assignment.get("allow_late"):
        raise ConflictError("已过截止时间，且该作业不允许迟交")

    submission_id = submission_repo.upsert_submission(
        assignment_id,
        int(viewer["id"]),
        {
            "content": content,
            "attachments": json.dumps(attachments, ensure_ascii=False) if attachments else None,
            "status": "late" if is_late else "submitted",
            "submitted_at": clock.to_iso(now),
            "is_late": 1 if is_late else 0,
        },
    )
    audit_repo.log(
        user_id=int(viewer["id"]),
        username=viewer["username"],
        action="submit_assignment",
        entity="submission",
        entity_id=submission_id,
        detail=f"作业 {assignment['title']}" + ("（迟交）" if is_late else ""),
    )
    result = submission_repo.by_student(assignment_id, int(viewer["id"])) or {}
    result["is_late"] = is_late
    result["deduction_hint"] = (
        f"迟交，每迟一天扣 {int(float(assignment.get('late_penalty') or 0) * 100)}%"
        if is_late else ""
    )
    return result


def grade_submission(operator: dict[str, Any], submission_id: int,
                     payload: dict[str, Any]) -> dict[str, Any]:
    permissions.require_teacher(operator)
    submission = submission_repo.find_or_fail(submission_id, "提交记录不存在")
    assignment = assignment_repo.find_or_fail(int(submission["assignment_id"]), "作业不存在")
    detail = _class_or_fail(int(assignment["class_id"]))
    permissions.assert_can_manage_course(operator, detail)

    full_score = float(assignment.get("full_score") or 100)
    score = validators.validate_score(payload.get("score"), full_score)
    feedback = validators.optional_str(payload, "feedback", "", max_len=2000)

    submission_repo.grade(submission_id, score, feedback, int(operator["id"]))
    notify_class(
        [int(submission["student_id"])],
        title=f"作业已批改：{assignment['title']}",
        content=f"得分 {score} / {full_score}",
        category="grade",
        link=f"/assignments/{assignment['id']}",
    )
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="grade_submission",
        entity="submission",
        entity_id=submission_id,
        detail=f"打分 {score}",
    )
    return submission_repo.by_student(
        int(submission["assignment_id"]), int(submission["student_id"])
    ) or {}


def batch_grade(operator: dict[str, Any], assignment_id: int,
                rows: list[dict[str, Any]]) -> dict[str, Any]:
    """批量打分：rows = [{submission_id, score, feedback}]。"""
    permissions.require_teacher(operator)
    assignment = assignment_repo.detail(assignment_id)
    if assignment is None:
        raise NotFoundError("作业不存在")
    detail = _class_or_fail(int(assignment["class_id"]))
    permissions.assert_can_manage_course(operator, detail)
    full_score = float(assignment.get("full_score") or 100)

    updated = 0
    failed: list[dict[str, Any]] = []
    for row in rows:
        try:
            submission_id = validators.to_int(row.get("submission_id"), "submission_id")
            score = validators.validate_score(row.get("score"), full_score)
            submission_repo.grade(
                submission_id, score, str(row.get("feedback") or ""), int(operator["id"])
            )
            updated += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"submission_id": row.get("submission_id"), "error": str(exc)})
    return {"updated": updated, "failed": failed}


def list_submissions(operator: dict[str, Any], assignment_id: int) -> dict[str, Any]:
    permissions.require_teacher(operator)
    assignment = assignment_repo.detail(assignment_id)
    if assignment is None:
        raise NotFoundError("作业不存在")
    detail = _class_or_fail(int(assignment["class_id"]))
    permissions.assert_can_manage_course(operator, detail)
    submissions = submission_repo.list_by_assignment(assignment_id)
    students = class_repo.students(int(assignment["class_id"]))
    submitted_ids = {int(item["student_id"]) for item in submissions}
    missing = [student for student in students if int(student["id"]) not in submitted_ids]
    return {
        "assignment": assignment_repo.detail(assignment_id),
        "submissions": submissions,
        "not_submitted": missing,
        "stats": submission_repo.stats_for_assignment(assignment_id),
    }


def delete_assignment(operator: dict[str, Any], assignment_id: int) -> None:
    assignment = assignment_repo.detail(assignment_id)
    if assignment is None:
        raise NotFoundError("作业不存在")
    detail = _class_or_fail(int(assignment["class_id"]))
    permissions.assert_can_manage_course(operator, detail)
    assignment_repo.delete(assignment_id)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="delete_assignment",
        entity="assignment",
        entity_id=assignment_id,
        detail=assignment["title"],
    )

def submission_progress(user: dict[str, Any], assignment_id: int) -> dict[str, Any]:
    """教师视角：谁交了、谁没交。"""
    from backend.db import connection

    assignment = assignment_repo.detail(assignment_id)
    if assignment is None:
        raise NotFoundError("作业不存在")
    cls = connection.query_one(
        """SELECT c.*, co.teacher_id FROM classes c
             JOIN courses co ON co.id = c.course_id WHERE c.id = ?""",
        (int(assignment["class_id"]),),
    )
    if cls is None:
        raise NotFoundError("教学班不存在")
    if user["role"] != permissions.ROLE_ADMIN and int(cls.get("teacher_id") or 0) != int(user["id"]):
        raise ForbiddenError("只有任课教师可以查看")

    students = connection.query_all(
        """SELECT u.id, u.real_name, u.username, u.number
             FROM enrollments e JOIN users u ON u.id = e.student_id
            WHERE e.class_id = ? AND e.status = 'active'
            ORDER BY u.number, u.id""",
        (int(assignment["class_id"]),),
    )
    subs = connection.query_all(
        """SELECT s.*, u.real_name, u.username, u.number
             FROM submissions s JOIN users u ON u.id = s.student_id
            WHERE s.assignment_id = ?""",
        (assignment_id,),
    )
    by_student = {int(s["student_id"]): s for s in subs}

    submitted, missing = [], []
    for st in students:
        sid = int(st["id"])
        sub = by_student.get(sid)
        item = {
            "student_id": sid,
            "real_name": st["real_name"],
            "number": st.get("number") or "",
            "username": st["username"],
        }
        if sub is None:
            missing.append(item)
        else:
            item.update(
                submission_id=sub["id"],
                submitted_at=sub.get("submitted_at"),
                status=sub.get("status"),
                score=sub.get("score"),
                late=bool(sub.get("late")),
            )
            submitted.append(item)

    return {
        "assignment_id": assignment_id,
        "title": assignment["title"],
        "class_name": cls["name"],
        "total": len(students),
        "submitted_count": len(submitted),
        "missing_count": len(missing),
        "graded_count": sum(1 for s in submitted if s.get("status") == "graded"),
        "submitted": submitted,
        "missing": missing,
    }
