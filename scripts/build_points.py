"""学生学分 / 德育分：老师加扣学分，管理员加扣德育分，学生收到通知。"""

from pathlib import Path

# ---------------- 迁移 v10 ----------------
m = Path(r"D:\EduFlow\backend\db\migrations.py")
t = m.read_text(encoding="utf-8")
t = t.replace("CURRENT_VERSION = 9", "CURRENT_VERSION = 10")
if "_migrate_v10" not in t:
    func = '''
def _migrate_v10(conn: sqlite3.Connection) -> None:
    """v9 -> v10：学生学分与德育分。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS student_points (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind          TEXT NOT NULL,
            delta         REAL NOT NULL,
            reason        TEXT NOT NULL,
            operator_id   INTEGER NOT NULL REFERENCES users(id),
            operator_role TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_points_student ON student_points(student_id, created_at);
        """
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
'''
    t = t.replace("MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [", func, 1)
    out = []
    for line in t.splitlines():
        out.append(line)
        if line.strip() == "(9, _migrate_v9),":
            out.append("    (10, _migrate_v10),")
    t = "\n".join(out)
    t = t.replace('"group_checkins",', '"group_checkins",\n        "student_points",')
    m.write_text(t, encoding="utf-8")
    print("migrations: v10 学分/德育分")

# ---------------- 服务 ----------------
svc = Path(r"D:\EduFlow\backend\services\points_service.py")
if not svc.exists():
    svc.write_text('''"""学分与德育分。"""

from __future__ import annotations

from typing import Any

from backend.core import clock, permissions
from backend.core.errors import ForbiddenError, NotFoundError, ValidationError
from backend.db import connection
from backend.repositories.audit import AuditRepository
from backend.repositories.users import UserRepository

user_repo = UserRepository()
audit_repo = AuditRepository()

MORAL_BASE = 50
KIND_LABEL = {"credit": "学分", "moral": "德育分"}


def _totals(student_id: int) -> dict[str, float]:
    rows = connection.query_all(
        "SELECT kind, SUM(delta) AS total FROM student_points WHERE student_id = ? GROUP BY kind",
        (student_id,),
    )
    sums = {r["kind"]: float(r["total"] or 0) for r in rows}
    return {
        "credit": round(sums.get("credit", 0.0), 2),
        "moral": round(MORAL_BASE + sums.get("moral", 0.0), 2),
        "moral_delta": round(sums.get("moral", 0.0), 2),
    }


def _can_manage(operator: dict[str, Any], student_id: int) -> bool:
    """老师只能管自己教学班/班级群里的学生；管理员不限。"""
    if operator["role"] == permissions.ROLE_ADMIN:
        return True
    if operator["role"] != permissions.ROLE_TEACHER:
        return False
    oid = int(operator["id"])
    row = connection.query_one(
        """SELECT 1 FROM enrollments e
             JOIN classes cl ON cl.id = e.class_id
             JOIN courses co ON co.id = cl.course_id
            WHERE e.student_id = ? AND e.status = 'active' AND co.teacher_id = ?
            LIMIT 1""",
        (student_id, oid),
    )
    if row:
        return True
    row = connection.query_one(
        """SELECT 1 FROM group_members gm
             JOIN class_groups g ON g.id = gm.group_id
            WHERE gm.user_id = ? AND g.teacher_id = ?
            LIMIT 1""",
        (student_id, oid),
    )
    return row is not None


def adjust(operator: dict[str, Any], student_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "credit").strip()
    if kind not in KIND_LABEL:
        raise ValidationError("类型只能是学分或德育分")
    if kind == "credit" and operator["role"] not in (
        permissions.ROLE_TEACHER, permissions.ROLE_ADMIN
    ):
        raise ForbiddenError("只有老师可以调整学分")
    if kind == "moral" and operator["role"] != permissions.ROLE_ADMIN:
        raise ForbiddenError("只有管理员可以调整德育分")

    delta = float(payload.get("delta") or 0)
    if delta == 0:
        raise ValidationError("分值不能为 0")
    if abs(delta) > 100:
        raise ValidationError("单次调整不能超过 100 分")
    reason = str(payload.get("reason") or "").strip()
    if len(reason) < 2:
        raise ValidationError("请填写理由")

    student = user_repo.find_or_fail(student_id, "学生不存在")
    if student["role"] != permissions.ROLE_STUDENT:
        raise ValidationError("只能给学生加扣分")
    if not _can_manage(operator, student_id):
        raise ForbiddenError("只能管理自己班级的学生")

    connection.execute(
        """INSERT INTO student_points
               (student_id, kind, delta, reason, operator_id, operator_role, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (student_id, kind, delta, reason[:200], int(operator["id"]), operator["role"], clock.now_iso()),
    )
    totals = _totals(student_id)

    sign = "+" if delta > 0 else ""
    from backend.services import notification_service

    notification_service.notify(
        student_id,
        title=f"{KIND_LABEL[kind]}{'加分' if delta > 0 else '扣分'} {sign}{delta:g}",
        content=f"{operator['real_name']}：{reason}（当前{KIND_LABEL[kind]} {totals[kind]:g} 分）",
        category="course",
        link="/profile",
    )
    audit_repo.log(
        user_id=int(operator["id"]), username=operator["username"],
        action=f"points_{kind}", entity="user", entity_id=student_id,
        detail=f"{sign}{delta:g} 分：{reason}",
    )
    return {"student_id": student_id, "kind": kind, "totals": totals}


def history(student_id: int, limit: int = 50) -> list[dict[str, Any]]:
    return connection.query_all(
        """SELECT p.*, u.real_name AS operator_name
             FROM student_points p JOIN users u ON u.id = p.operator_id
            WHERE p.student_id = ? ORDER BY p.id DESC LIMIT ?""",
        (student_id, limit),
    )


def overview(operator: dict[str, Any], keyword: str = "") -> list[dict[str, Any]]:
    """教师/管理员：学生列表 + 分数。"""
    like = f"%{keyword}%"
    if operator["role"] == permissions.ROLE_ADMIN:
        students = connection.query_all(
            """SELECT id, real_name, username, number, class_name FROM users
                WHERE role = 'student' AND (real_name LIKE ? OR username LIKE ? OR number LIKE ?)
                ORDER BY id DESC LIMIT 200""",
            (like, like, like),
        )
    else:
        students = connection.query_all(
            """SELECT DISTINCT u.id, u.real_name, u.username, u.number, u.class_name
                 FROM users u
                 JOIN group_members gm ON gm.user_id = u.id
                 JOIN class_groups g ON g.id = gm.group_id
                WHERE u.role = 'student' AND g.teacher_id = ?
                  AND (u.real_name LIKE ? OR u.username LIKE ? OR u.number LIKE ?)
                ORDER BY u.id DESC LIMIT 200""",
            (int(operator["id"]), like, like, like),
        )
    for s in students:
        t = _totals(int(s["id"]))
        s["credit"] = t["credit"]
        s["moral"] = t["moral"]
    return students


def my_points(student: dict[str, Any]) -> dict[str, Any]:
    sid = int(student["id"])
    return {
        "totals": _totals(sid),
        "history": history(sid, limit=100),
        "moral_base": MORAL_BASE,
    }
''', encoding="utf-8")
    print("points_service: 已创建")

# ---------------- 路由 ----------------
r = Path(r"D:\EduFlow\backend\api\points_routes.py")
if not r.exists():
    r.write_text('''"""学分 / 德育分接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, ok
from backend.http.router import Router
from backend.services import points_service

router = Router()


@router.get("/api/points/students", roles=("teacher", "admin"), summary="学生分数总览")
def overview(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(points_service.overview(user, req.str_param("q")))


@router.post("/api/points/students/<int:student_id>", roles=("teacher", "admin"),
             summary="加扣分")
def adjust(req) -> Response:
    user = permissions.require_login(req.user)
    data = points_service.adjust(user, req.path_params["student_id"], req.json())
    return ok(data, "已记录并通知学生")


@router.get("/api/my/points", roles=("student",), summary="我的学分与德育分")
def my_points(req) -> Response:
    student = permissions.require_role(req.user, "student")
    return ok(points_service.my_points(student))
''', encoding="utf-8")
    print("points_routes: 已创建")

# ---------------- 注册 ----------------
a = Path(r"D:\EduFlow\backend\app.py")
t = a.read_text(encoding="utf-8")
if "points_routes" not in t:
    lines = t.splitlines()
    t = "\n".join(lines)
    t = t.replace("        from backend.api import (", "        from backend.api import (\n            points_routes,", 1)
    idx = t.find("for module in (")
    seg = t[idx: idx + 900]
    seg2 = seg.replace("            checkin_routes,", "            checkin_routes,\n            points_routes,", 1)
    t = t[:idx] + seg2 + t[idx + 900:]
    a.write_text(t, encoding="utf-8")
    print("app.py: 注册 points_routes")
