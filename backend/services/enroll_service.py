"""入课申请：学生凭邀请码申请，需任课教师审批通过才入班。"""

from __future__ import annotations

from typing import Any

from backend.core import clock, permissions, validators
from backend.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from backend.db import connection
from backend.repositories.audit import AuditRepository
from backend.repositories.courses import ClassRepository, CourseRepository

class_repo = ClassRepository()
course_repo = CourseRepository()
audit_repo = AuditRepository()


def _class_with_course(class_id: int) -> dict[str, Any]:
    row = connection.query_one(
        """SELECT cl.*, co.name AS course_name, co.teacher_id
             FROM classes cl JOIN courses co ON co.id = cl.course_id
            WHERE cl.id = ?""",
        (class_id,),
    )
    if row is None:
        raise NotFoundError("教学班不存在")
    return row


def request_join(student: dict[str, Any], code: str) -> dict[str, Any]:
    """学生提交入课申请（等待审批）。"""
    permissions.require_role(student, permissions.ROLE_STUDENT)
    code = validators.validate_code(code, "邀请码")
    target = class_repo.by_join_code(code)
    if target is None:
        raise NotFoundError("邀请码无效")
    if target["status"] != "active":
        raise ValidationError("该教学班已关闭选课")
    if class_repo.student_count(int(target["id"])) >= int(target.get("capacity") or 60):
        raise ValidationError("教学班人数已满")

    sid = int(student["id"])
    existing = connection.query_one(
        "SELECT * FROM enrollments WHERE class_id = ? AND student_id = ?",
        (int(target["id"]), sid),
    )
    if existing:
        if existing["status"] == "active":
            raise ConflictError("你已经加入该教学班")
        if existing["status"] == "pending":
            raise ConflictError("申请已提交，等待老师审批")
        connection.execute(
            "UPDATE enrollments SET status = 'pending', source = 'request', created_at = ? WHERE id = ?",
            (clock.now_iso(), existing["id"]),
        )
    else:
        connection.execute(
            """INSERT INTO enrollments (class_id, student_id, status, source, created_at)
               VALUES (?, ?, 'pending', 'request', ?)""",
            (int(target["id"]), sid, clock.now_iso()),
        )

    info = _class_with_course(int(target["id"]))
    audit_repo.log(
        user_id=sid, username=student["username"], action="enroll_request",
        entity="class", entity_id=int(target["id"]),
        detail=f"申请加入 {info['course_name']} / {info['name']}",
    )
    return {
        "class_id": int(target["id"]),
        "course_name": info["course_name"],
        "class_name": info["name"],
        "status": "pending",
    }


def list_requests(teacher: dict[str, Any]) -> list[dict[str, Any]]:
    """教师：自己课程下待审批的申请；管理员：全部。"""
    if teacher["role"] == permissions.ROLE_ADMIN:
        rows = connection.query_all(
            """SELECT e.id, e.class_id, e.student_id, e.created_at,
                      u.real_name, u.username, u.number,
                      cl.name AS class_name, co.name AS course_name, co.code AS course_code
                 FROM enrollments e
                 JOIN classes cl ON cl.id = e.class_id
                 JOIN courses co ON co.id = cl.course_id
                 JOIN users u ON u.id = e.student_id
                WHERE e.status = 'pending'
                ORDER BY e.created_at DESC"""
        )
    else:
        rows = connection.query_all(
            """SELECT e.id, e.class_id, e.student_id, e.created_at,
                      u.real_name, u.username, u.number,
                      cl.name AS class_name, co.name AS course_name, co.code AS course_code
                 FROM enrollments e
                 JOIN classes cl ON cl.id = e.class_id
                 JOIN courses co ON co.id = cl.course_id
                 JOIN users u ON u.id = e.student_id
                WHERE e.status = 'pending' AND co.teacher_id = ?
                ORDER BY e.created_at DESC""",
            (int(teacher["id"]),),
        )
    return rows


def _decide(teacher: dict[str, Any], enrollment_id: int, approve: bool) -> dict[str, Any]:
    row = connection.query_one(
        """SELECT e.*, cl.course_id, co.teacher_id, co.name AS course_name
             FROM enrollments e
             JOIN classes cl ON cl.id = e.class_id
             JOIN courses co ON co.id = cl.course_id
            WHERE e.id = ?""",
        (enrollment_id,),
    )
    if row is None:
        raise NotFoundError("申请不存在")
    if teacher["role"] != permissions.ROLE_ADMIN and int(row.get("teacher_id") or 0) != int(teacher["id"]):
        raise ForbiddenError("只有任课教师可以审批")
    if row["status"] != "pending":
        raise ValidationError("该申请已处理")

    status = "active" if approve else "rejected"
    connection.execute("UPDATE enrollments SET status = ? WHERE id = ?", (status, enrollment_id))
    audit_repo.log(
        user_id=int(teacher["id"]), username=teacher["username"],
        action="enroll_" + ("approve" if approve else "reject"),
        entity="enrollment", entity_id=enrollment_id,
        detail=f"{row['course_name']} / 学生 {row['student_id']}",
    )
    return {"id": enrollment_id, "status": status}


def approve(teacher: dict[str, Any], enrollment_id: int) -> dict[str, Any]:
    return _decide(teacher, enrollment_id, True)


def reject(teacher: dict[str, Any], enrollment_id: int) -> dict[str, Any]:
    return _decide(teacher, enrollment_id, False)


def my_requests(student: dict[str, Any]) -> list[dict[str, Any]]:
    return connection.query_all(
        """SELECT e.id, e.status, e.created_at, cl.name AS class_name, co.name AS course_name
             FROM enrollments e
             JOIN classes cl ON cl.id = e.class_id
             JOIN courses co ON co.id = cl.course_id
            WHERE e.student_id = ?
            ORDER BY e.created_at DESC LIMIT 20""",
        (int(student["id"]),),
    )
