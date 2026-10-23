"""签到服务。

支持三种签到方式：
- code：教师发一个 6 位数字码，学生输入；
- qr：本质同上，只是前端把它渲染成二维码；
- location：除验证码外还校验经纬度是否在半径内。

迟到判定：签到开始 ATTENDANCE_LATE_MINUTES 分钟内算正常，之后算迟到。
"""

from __future__ import annotations

import math
from typing import Any

from backend import config
from backend.core import clock, ids, permissions, validators
from backend.core.errors import ConflictError, ForbiddenError, NotFoundError
from backend.repositories.attendance import (
    AttendanceRecordRepository,
    AttendanceSessionRepository,
)
from backend.repositories.audit import AuditRepository
from backend.repositories.courses import ClassRepository, EnrollmentRepository
from backend.services.notification_service import notify_class

session_repo = AttendanceSessionRepository()
record_repo = AttendanceRecordRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
audit_repo = AuditRepository()

METHODS = ("code", "qr", "location")


def _class_or_fail(class_id: int) -> dict[str, Any]:
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    return detail


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点的球面距离（米）。"""
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def create_session(payload: dict[str, Any], operator: dict[str, Any]) -> dict[str, Any]:
    permissions.require_teacher(operator)
    class_id = validators.required_int(payload, "class_id", min_value=1)
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)

    title = validators.optional_str(payload, "title", "课堂签到", max_len=64)
    method = validators.ensure_enum(
        validators.optional_str(payload, "method", "code", max_len=16), METHODS, "签到方式"
    )
    duration = validators.optional_int(payload, "duration", 5, min_value=1, max_value=120)

    latitude = longitude = None
    radius = 200
    if method == "location":
        latitude = validators.optional_float(payload, "latitude", None)
        longitude = validators.optional_float(payload, "longitude", None)
        radius = validators.optional_int(payload, "radius", 200, min_value=20, max_value=5000)
        if latitude is None or longitude is None:
            raise validators.ValidationError("位置签到必须提供经纬度")

    start = clock.utcnow()
    end = clock.add_minutes(start, duration)
    code = ids.new_attendance_code()

    session_id = session_repo.insert(
        {
            "class_id": class_id,
            "title": title,
            "method": method,
            "code": code,
            "start_at": clock.to_iso(start),
            "end_at": clock.to_iso(end),
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius,
            "status": "open",
            "created_by": int(operator["id"]),
        }
    )
    students = [int(row["id"]) for row in class_repo.students(class_id)]
    if students:
        notify_class(
            students,
            title=f"签到开始：{title}",
            content=f"{detail['course_name']} 正在签到，{duration} 分钟内完成",
            category="attendance",
            link=f"/attendance/{session_id}",
        )
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="create_attendance",
        entity="attendance_session",
        entity_id=session_id,
        detail=f"{detail['course_name']} / {method}",
    )
    return session_repo.detail(session_id) or {}


def list_sessions(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
    detail = _class_or_fail(class_id)
    if viewer["role"] == permissions.ROLE_STUDENT:
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")
    else:
        permissions.assert_can_manage_course(viewer, detail)
    items = session_repo.list_by_class(class_id)
    if viewer["role"] == permissions.ROLE_STUDENT:
        for item in items:
            record = record_repo.find_by(
                session_id=int(item["id"]), student_id=int(viewer["id"])
            )
            item["my_status"] = record.get("status") if record else None
    return items


def open_sessions_for_student(viewer: dict[str, Any]) -> list[dict[str, Any]]:
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    return session_repo.list_open_for_student(int(viewer["id"]))


def check_in(viewer: dict[str, Any], session_id: int,
             payload: dict[str, Any]) -> dict[str, Any]:
    """学生签到。"""
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    session = session_repo.find_or_fail(session_id, "签到不存在")
    if session.get("status") != "open":
        raise ConflictError("签到已结束")

    now = clock.utcnow()
    end_at = clock.parse_iso(session.get("end_at"))
    if end_at and now > end_at:
        session_repo.close(session_id)
        raise ConflictError("签到已超时")

    class_id = int(session["class_id"])
    if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
        raise ForbiddenError("未选修该课程")

    existing = record_repo.find_by(session_id=session_id, student_id=int(viewer["id"]))
    if existing and existing.get("status") in ("present", "late"):
        raise ConflictError("你已经签过到了")

    submitted_code = validators.optional_str(payload, "code", "", max_len=16).upper()
    if submitted_code != str(session["code"]).upper():
        raise ConflictError("签到码不正确")

    if session["method"] == "location":
        lat = validators.optional_float(payload, "latitude", None)
        lon = validators.optional_float(payload, "longitude", None)
        if lat is None or lon is None:
            raise validators.ValidationError("位置签到需要提供定位")
        distance = haversine_meters(
            float(session["latitude"]), float(session["longitude"]), lat, lon
        )
        if distance > float(session.get("radius") or 200):
            raise ConflictError(f"距离签到点 {distance:.0f} 米，超出允许范围")
        note = f"距离 {distance:.0f} 米"
    else:
        note = ""

    started = clock.parse_iso(session.get("start_at")) or now
    late_threshold = clock.add_minutes(started, config.ATTENDANCE_LATE_MINUTES)
    status = "late" if now > late_threshold else "present"

    record_repo.mark(session_id, int(viewer["id"]), status, note)
    return {
        "session_id": session_id,
        "status": status,
        "status_label": "正常" if status == "present" else "迟到",
        "checked_at": clock.to_iso(now),
        "note": note,
    }


def mark_manually(operator: dict[str, Any], session_id: int,
                  payload: dict[str, Any]) -> dict[str, Any]:
    """教师补签/改签。"""
    permissions.require_teacher(operator)
    session = session_repo.find_or_fail(session_id, "签到不存在")
    detail = _class_or_fail(int(session["class_id"]))
    permissions.assert_can_manage_course(operator, detail)

    student_id = validators.required_int(payload, "student_id", min_value=1)
    status = validators.ensure_enum(
        validators.required_str(payload, "status"),
        ("present", "late", "absent", "leave"),
        "签到状态",
    )
    note = validators.optional_str(payload, "note", "教师手动标记", max_len=200)
    record_repo.mark(session_id, student_id, status, note)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="mark_attendance",
        entity="attendance_record",
        entity_id=session_id,
        detail=f"学生 {student_id} -> {status}",
    )
    return {"session_id": session_id, "student_id": student_id, "status": status}


def session_detail(viewer: dict[str, Any], session_id: int) -> dict[str, Any]:
    session = session_repo.detail(session_id)
    if session is None:
        raise NotFoundError("签到不存在")
    class_id = int(session["class_id"])
    detail = _class_or_fail(class_id)
    if viewer["role"] == permissions.ROLE_STUDENT:
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")
        records = [row for row in record_repo.list_by_session(session_id)
                   if int(row["student_id"]) == int(viewer["id"])]
    else:
        permissions.assert_can_manage_course(viewer, detail)
        records = record_repo.list_by_session(session_id)
    session["records"] = records
    session["class_detail"] = detail
    return session


def close_session(operator: dict[str, Any], session_id: int) -> dict[str, Any]:
    permissions.require_teacher(operator)
    session = session_repo.find_or_fail(session_id, "签到不存在")
    detail = _class_or_fail(int(session["class_id"]))
    permissions.assert_can_manage_course(operator, detail)
    session_repo.close(session_id)
    return {"session_id": session_id, "status": "closed"}


def class_attendance_summary(operator: dict[str, Any],
                             class_id: int) -> dict[str, Any]:
    permissions.require_teacher(operator)
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)
    return {
        "class": detail,
        "rows": record_repo.class_summary(class_id),
        "session_count": len(session_repo.list_by_class(class_id)),
    }
