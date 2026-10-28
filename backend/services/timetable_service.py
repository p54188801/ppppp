"""课表：按班级查看，管理员维护。"""

from __future__ import annotations

from typing import Any

from backend.core import clock, permissions, validators
from backend.core.errors import NotFoundError
from backend.db import connection
from backend.repositories.audit import AuditRepository

audit_repo = AuditRepository()

PERIODS = {
    1: "08:00 - 08:45",
    2: "08:55 - 09:40",
    3: "10:00 - 10:45",
    4: "10:55 - 11:40",
    5: "14:00 - 14:45",
    6: "14:55 - 15:40",
    7: "16:00 - 16:45",
    8: "16:55 - 17:40",
}

WEEKDAYS = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}


def _row(r: dict[str, Any]) -> dict[str, Any]:
    r["period_label"] = PERIODS.get(int(r["period"]), "")
    r["weekday_label"] = WEEKDAYS.get(int(r["weekday"]), "")
    return r


def list_slots(user: dict[str, Any], *, class_name: str = "", teacher_name: str = "",
               semester: str = "") -> dict[str, Any]:
    """学生看自己班；教师看自己的课（也可切到全部）；管理员看全部。"""
    where, params = [], []
    scope = "all"

    if user["role"] == permissions.ROLE_STUDENT:
        cls = (user.get("class_name") or "").strip()
        if not cls:
            return {"scope": "none", "class_name": "", "slots": [], "periods": PERIODS, "weekdays": WEEKDAYS}
        where.append("class_name = ?")
        params.append(cls)
        scope = "class"
    elif user["role"] == permissions.ROLE_TEACHER:
        # 教师默认看全部课表，可再按班级筛选
        if class_name:
            where.append("class_name = ?")
            params.append(class_name)
            scope = "class"
        elif teacher_name:
            where.append("teacher_name = ?")
            params.append(teacher_name)
            scope = "teacher"

    if class_name and user["role"] == permissions.ROLE_ADMIN:
        where.append("class_name = ?")
        params.append(class_name)
        scope = "class"

    semesters = [r["semester"] for r in connection.query_all(
        "SELECT DISTINCT semester FROM timetable WHERE semester <> '' ORDER BY semester DESC"
    )]
    if not semester and semesters:
        semester = semesters[0]
    if semester:
        where.append("semester = ?")
        params.append(semester)

    sql = "SELECT * FROM timetable"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY weekday, period"
    rows = [_row(r) for r in connection.query_all(sql, tuple(params))]
    return {
        "scope": scope,
        "class_name": class_name or (user.get("class_name") or ""),
        "semester": semester,
        "semesters": semesters,
        "slots": rows,
        "periods": PERIODS,
        "weekdays": WEEKDAYS,
    }


def classes() -> list[str]:
    rows = connection.query_all(
        """SELECT DISTINCT class_name FROM timetable
             UNION SELECT DISTINCT name FROM class_groups ORDER BY class_name"""
    )
    return [r["class_name"] for r in rows if r.get("class_name")]


def create_slot(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    data = _validate(payload)
    now = clock.now_iso()
    try:
        sid = connection.execute(
            """INSERT INTO timetable
                   (class_name, weekday, period, course_name, teacher_name, room, note,
                    created_at, updated_at, semester, weeks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data["class_name"], data["weekday"], data["period"], data["course_name"],
             data["teacher_name"], data["room"], data["note"], now, now,
             data["semester"], data["weeks"]),
        )
    except Exception as exc:  # noqa: BLE001
        if "UNIQUE" in str(exc):
            from backend.core.errors import ConflictError

            raise ConflictError("该班级这个时段已经有课了") from None
        raise
    audit_repo.log(user_id=int(user["id"]), username=user["username"], action="timetable_create",
                   entity="timetable", entity_id=sid, detail=f"{data['class_name']} {data['course_name']}")
    return get_slot(sid)


def update_slot(user: dict[str, Any], slot_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if connection.query_one("SELECT id FROM timetable WHERE id = ?", (slot_id,)) is None:
        raise NotFoundError("课表记录不存在")
    data = _validate(payload)
    connection.execute(
        """UPDATE timetable SET class_name=?, weekday=?, period=?, course_name=?,
                  teacher_name=?, room=?, note=?, updated_at=? WHERE id=?""",
        (data["class_name"], data["weekday"], data["period"], data["course_name"],
         data["teacher_name"], data["room"], data["note"], clock.now_iso(),
         data["semester"], data["weeks"], slot_id),
    )
    audit_repo.log(user_id=int(user["id"]), username=user["username"], action="timetable_update",
                   entity="timetable", entity_id=slot_id, detail=f"{data['class_name']} {data['course_name']}")
    return get_slot(slot_id)


def delete_slot(user: dict[str, Any], slot_id: int) -> dict[str, Any]:
    if connection.query_one("SELECT id FROM timetable WHERE id = ?", (slot_id,)) is None:
        raise NotFoundError("课表记录不存在")
    connection.execute("DELETE FROM timetable WHERE id = ?", (slot_id,))
    audit_repo.log(user_id=int(user["id"]), username=user["username"], action="timetable_delete",
                   entity="timetable", entity_id=slot_id, detail="删除课表记录")
    return {"id": slot_id}


def get_slot(slot_id: int) -> dict[str, Any]:
    row = connection.query_one("SELECT * FROM timetable WHERE id = ?", (slot_id,))
    if row is None:
        raise NotFoundError("课表记录不存在")
    return _row(row)


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    class_name = validators.required_str(payload, "class_name", min_len=1, max_len=64)
    course_name = validators.required_str(payload, "course_name", min_len=1, max_len=64)
    weekday = int(validators.optional_int(payload, "weekday", 1, min_value=1, max_value=7))
    period = int(validators.optional_int(payload, "period", 1, min_value=1, max_value=8))
    return {
        "class_name": class_name,
        "course_name": course_name,
        "weekday": weekday,
        "period": period,
        "teacher_name": validators.optional_str(payload, "teacher_name", "", max_len=32),
        "room": validators.optional_str(payload, "room", "", max_len=32),
        "note": validators.optional_str(payload, "note", "", max_len=200),
        "semester": validators.optional_str(payload, "semester", "2026-2027-1", max_len=32),
        "weeks": validators.optional_str(payload, "weeks", "1-20", max_len=64),
    }
