"""课表模块：迁移 + 服务 + 路由。"""

from pathlib import Path

# ---------------------------------------------------------------- 迁移
m = Path(r"D:\EduFlow\backend\db\migrations.py")
t = m.read_text(encoding="utf-8")
t = t.replace("CURRENT_VERSION = 5", "CURRENT_VERSION = 6")

if "_migrate_v6" not in t:
    func = '''
def _migrate_v6(conn: sqlite3.Connection) -> None:
    """v5 -> v6：课表。"""
    from backend.core import clock

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS timetable (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name   TEXT NOT NULL,
            weekday      INTEGER NOT NULL,
            period       INTEGER NOT NULL,
            course_name  TEXT NOT NULL,
            teacher_name TEXT DEFAULT '',
            room         TEXT DEFAULT '',
            note         TEXT DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            UNIQUE (class_name, weekday, period)
        );
        CREATE INDEX IF NOT EXISTS idx_timetable_class ON timetable(class_name, weekday, period);
        """
    )
    # 示例课表：大数据G231
    seed = [
        (1, 1, "大数据技术", "王老师", "A301"),
        (1, 2, "Python 程序设计", "李老师", "机房 2"),
        (1, 3, "高等数学", "赵老师", "B102"),
        (2, 1, "数据结构", "孙老师", "A305"),
        (2, 2, "大学英语", "周老师", "C201"),
        (3, 1, "数据库原理", "王老师", "A301"),
        (3, 3, "体育", "吴老师", "操场"),
        (4, 1, "大数据技术", "王老师", "A301"),
        (4, 2, "职业规划", "郑老师", "B203"),
        (5, 1, "Python 程序设计", "李老师", "机房 2"),
    ]
    now = clock.now_iso()
    for weekday, period, course, teacher, room in seed:
        conn.execute(
            """INSERT OR IGNORE INTO timetable
                   (class_name, weekday, period, course_name, teacher_name, room, created_at, updated_at)
               VALUES ('大数据G231', ?, ?, ?, ?, ?, ?, ?)""",
            (weekday, period, course, teacher, room, now, now),
        )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
'''
    t = t.replace(
        "MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [", func, 1
    )
    lines = t.splitlines()
    out = []
    for line in lines:
        out.append(line)
        if line.strip() == "(5, _migrate_v5),":
            out.append("    (6, _migrate_v6),")
    t = "\n".join(out)
    t = t.replace('"class_groups",', '"class_groups",\n        "timetable",')
    m.write_text(t, encoding="utf-8")
    print("migrations: 已加 v6 课表")

# ---------------------------------------------------------------- 服务
svc = Path(r"D:\EduFlow\backend\services\timetable_service.py")
if not svc.exists():
    svc.write_text('''"""课表：按班级查看，管理员维护。"""

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


def list_slots(user: dict[str, Any], *, class_name: str = "", teacher_name: str = "") -> dict[str, Any]:
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
        if class_name:
            where.append("class_name = ?")
            params.append(class_name)
            scope = "class"
        else:
            where.append("teacher_name = ?")
            params.append(user.get("real_name") or "")
            scope = "teacher"
            if teacher_name:
                where[-1] = "teacher_name = ?"
                params[-1] = teacher_name

    if class_name and user["role"] == permissions.ROLE_ADMIN:
        where.append("class_name = ?")
        params.append(class_name)
        scope = "class"

    sql = "SELECT * FROM timetable"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY weekday, period"
    rows = [_row(r) for r in connection.query_all(sql, tuple(params))]
    return {
        "scope": scope,
        "class_name": class_name or (user.get("class_name") or ""),
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
                   (class_name, weekday, period, course_name, teacher_name, room, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data["class_name"], data["weekday"], data["period"], data["course_name"],
             data["teacher_name"], data["room"], data["note"], now, now),
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
         data["teacher_name"], data["room"], data["note"], clock.now_iso(), slot_id),
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
    }
''', encoding="utf-8")
    print("timetable_service: 已创建")

# ---------------------------------------------------------------- 路由
r = Path(r"D:\EduFlow\backend\api\timetable_routes.py")
if not r.exists():
    r.write_text('''"""课表接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.services import timetable_service

router = Router()


@router.get("/api/timetable", summary="课表")
def list_slots(req) -> Response:
    user = permissions.require_login(req.user)
    data = timetable_service.list_slots(
        user,
        class_name=req.str_param("class_name"),
        teacher_name=req.str_param("teacher_name"),
    )
    return ok(data)


@router.get("/api/timetable/classes", summary="有课表的班级")
def list_classes(req) -> Response:
    permissions.require_login(req.user)
    return ok(timetable_service.classes())


@router.post("/api/timetable", roles=("admin",), summary="新增课程时段")
def create_slot(req) -> Response:
    admin = permissions.require_admin(req.user)
    return created(timetable_service.create_slot(admin, req.json()), "已添加")


@router.put("/api/timetable/<int:slot_id>", roles=("admin",), summary="修改课程时段")
def update_slot(req) -> Response:
    admin = permissions.require_admin(req.user)
    return ok(timetable_service.update_slot(admin, req.path_params["slot_id"], req.json()), "已保存")


@router.delete("/api/timetable/<int:slot_id>", roles=("admin",), summary="删除课程时段")
def delete_slot(req) -> Response:
    admin = permissions.require_admin(req.user)
    return ok(timetable_service.delete_slot(admin, req.path_params["slot_id"]), "已删除")
''', encoding="utf-8")
    print("timetable_routes: 已创建")

# ---------------------------------------------------------------- 注册路由
a = Path(r"D:\EduFlow\backend\app.py")
t = a.read_text(encoding="utf-8")
if "timetable_routes" not in t:
    t = t.replace("            group_routes,", "            group_routes,\n            timetable_routes,", 1)
    t = t.replace("        from backend.api import (", "        from backend.api import (\n            timetable_routes,", 1)
    a.write_text(t, encoding="utf-8")
    print("app.py: 已注册课表路由")
