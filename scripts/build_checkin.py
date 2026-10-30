"""群签到：老师在班级群发起，学生用数字或图案签到。"""

from pathlib import Path

# ---------------- 迁移 v9 ----------------
m = Path(r"D:\EduFlow\backend\db\migrations.py")
t = m.read_text(encoding="utf-8")
t = t.replace("CURRENT_VERSION = 8", "CURRENT_VERSION = 9")
if "_migrate_v9" not in t:
    func = '''
def _migrate_v9(conn: sqlite3.Connection) -> None:
    """v8 -> v9：群签到。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS group_checkins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id   INTEGER NOT NULL REFERENCES class_groups(id) ON DELETE CASCADE,
            teacher_id INTEGER NOT NULL REFERENCES users(id),
            mode       TEXT NOT NULL DEFAULT 'number',
            answer     TEXT NOT NULL,
            minutes    INTEGER NOT NULL DEFAULT 5,
            started_at TEXT NOT NULL,
            ends_at    TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS group_checkin_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            checkin_id  INTEGER NOT NULL REFERENCES group_checkins(id) ON DELETE CASCADE,
            student_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            answer      TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            UNIQUE (checkin_id, student_id)
        );
        CREATE INDEX IF NOT EXISTS idx_checkin_records ON group_checkin_records(checkin_id);
        """
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
'''
    t = t.replace("MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [", func, 1)
    out = []
    for line in t.splitlines():
        out.append(line)
        if line.strip() == "(8, _migrate_v8),":
            out.append("    (9, _migrate_v9),")
    t = "\n".join(out)
    t = t.replace('"assignment_reminders",', '"assignment_reminders",\n        "group_checkin_records",\n        "group_checkins",')
    m.write_text(t, encoding="utf-8")
    print("migrations: v9 群签到")

# ---------------- 服务 ----------------
svc = Path(r"D:\EduFlow\backend\services\checkin_service.py")
if not svc.exists():
    svc.write_text('''"""群签到：发起、签到、查看谁没来。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from backend.core import clock, permissions
from backend.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from backend.db import connection
from backend.repositories.audit import AuditRepository

audit_repo = AuditRepository()

PATTERNS = ["🍎", "🍊", "🍋", "🍇", "🍓", "🍉", "🥝", "🍑"]


def _group(group_id: int) -> dict[str, Any]:
    row = connection.query_one("SELECT * FROM class_groups WHERE id = ?", (group_id,))
    if row is None:
        raise NotFoundError("班级群不存在")
    return row


def _is_teacher_of(group: dict[str, Any], user: dict[str, Any]) -> bool:
    return user["role"] == permissions.ROLE_ADMIN or int(group.get("teacher_id") or 0) == int(user["id"])


def _member(group_id: int, user_id: int) -> bool:
    return connection.query_one(
        "SELECT id FROM group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id)
    ) is not None


def start_checkin(user: dict[str, Any], group_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    group = _group(group_id)
    if not _is_teacher_of(group, user):
        raise ForbiddenError("只有老师可以发起签到")
    mode = (payload.get("mode") or "number").strip()
    if mode not in ("number", "pattern"):
        raise ValidationError("签到方式只能是数字或图案")
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        raise ValidationError("请设置签到内容")
    if mode == "pattern" and answer not in PATTERNS:
        raise ValidationError("请选择一个图案")
    minutes = int(payload.get("minutes") or 5)
    minutes = max(1, min(minutes, 60))

    # 关闭该群其它未结束的签到
    connection.execute(
        "UPDATE group_checkins SET status = 'closed' WHERE group_id = ? AND status = 'open'",
        (group_id,),
    )
    now = clock.utcnow()
    ends = now + timedelta(minutes=minutes)
    cid = connection.execute(
        """INSERT INTO group_checkins (group_id, teacher_id, mode, answer, minutes, started_at, ends_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open')""",
        (group_id, int(user["id"]), mode, answer, minutes,
         clock.to_iso(now), clock.to_iso(ends)),
    )
    connection.execute(
        """INSERT INTO group_messages (group_id, sender_id, kind, content, ref_id, created_at)
           VALUES (?, ?, 'checkin', ?, ?, ?)""",
        (group_id, int(user["id"]), f"发起签到（{minutes} 分钟）", cid, clock.to_iso(now)),
    )
    audit_repo.log(
        user_id=int(user["id"]), username=user["username"], action="checkin_start",
        entity="checkin", entity_id=cid, detail=f"{group['name']} 签到 {minutes} 分钟",
    )
    return get_checkin(cid)


def get_checkin(checkin_id: int) -> dict[str, Any]:
    row = connection.query_one("SELECT * FROM group_checkins WHERE id = ?", (checkin_id,))
    if row is None:
        raise NotFoundError("签到不存在")
    row["open"] = row["status"] == "open" and row["ends_at"] > clock.now_iso()
    return row


def active_checkin(user: dict[str, Any], group_id: int) -> dict[str, Any] | None:
    if not _member(group_id, int(user["id"])):
        return None
    row = connection.query_one(
        """SELECT * FROM group_checkins
            WHERE group_id = ? AND status = 'open' AND ends_at > ?
            ORDER BY id DESC LIMIT 1""",
        (group_id, clock.now_iso()),
    )
    if row is None:
        return None
    mine = connection.query_one(
        "SELECT * FROM group_checkin_records WHERE checkin_id = ? AND student_id = ?",
        (int(row["id"]), int(user["id"])),
    )
    row["my_record"] = mine
    row["total_students"] = int(
        connection.scalar(
            "SELECT COUNT(*) FROM group_members WHERE group_id = ? AND role = 'student'",
            (group_id,), default=0,
        ) or 0
    )
    row["checked_count"] = int(
        connection.scalar(
            "SELECT COUNT(*) FROM group_checkin_records WHERE checkin_id = ?", (int(row["id"]),), default=0
        ) or 0
    )
    return row


def respond(user: dict[str, Any], checkin_id: int, answer: str) -> dict[str, Any]:
    checkin = get_checkin(checkin_id)
    if not _member(int(checkin["group_id"]), int(user["id"])):
        raise ForbiddenError("你不在这个班级群")
    if user["role"] != permissions.ROLE_STUDENT:
        raise ForbiddenError("只有学生需要签到")
    if not checkin["open"]:
        raise ValidationError("签到已结束")
    exists = connection.query_one(
        "SELECT id FROM group_checkin_records WHERE checkin_id = ? AND student_id = ?",
        (checkin_id, int(user["id"])),
    )
    if exists:
        raise ConflictError("你已经签到过了")
    if str(answer or "").strip() != str(checkin["answer"]):
        raise ValidationError("签到内容不正确")

    connection.execute(
        "INSERT INTO group_checkin_records (checkin_id, student_id, answer, created_at) VALUES (?, ?, ?, ?)",
        (checkin_id, int(user["id"]), str(answer).strip(), clock.now_iso()),
    )
    connection.execute(
        """INSERT INTO group_messages (group_id, sender_id, kind, content, created_at)
           VALUES (?, ?, 'checkin_done', '已完成签到', ?)""",
        (int(checkin["group_id"]), int(user["id"]), clock.now_iso()),
    )
    return {"checkin_id": checkin_id, "ok": True}


def status(user: dict[str, Any], checkin_id: int) -> dict[str, Any]:
    checkin = get_checkin(checkin_id)
    group = _group(int(checkin["group_id"]))
    if not _is_teacher_of(group, user):
        raise ForbiddenError("只有老师可以查看签到情况")

    students = connection.query_all(
        """SELECT u.id, u.real_name, u.username, u.number
             FROM group_members m JOIN users u ON u.id = m.user_id
            WHERE m.group_id = ? AND m.role = 'student'
            ORDER BY u.number, u.id""",
        (int(checkin["group_id"]),),
    )
    records = connection.query_all(
        """SELECT r.*, u.real_name FROM group_checkin_records r
             JOIN users u ON u.id = r.student_id WHERE r.checkin_id = ?""",
        (checkin_id,),
    )
    done = {int(r["student_id"]): r for r in records}
    checked, missing = [], []
    for s in students:
        item = {"student_id": int(s["id"]), "real_name": s["real_name"],
                "number": s.get("number") or "", "username": s["username"]}
        if int(s["id"]) in done:
            item["created_at"] = done[int(s["id"])]["created_at"]
            checked.append(item)
        else:
            missing.append(item)

    return {
        "checkin": checkin,
        "total": len(students),
        "checked_count": len(checked),
        "missing_count": len(missing),
        "checked": checked,
        "missing": missing,
    }


def list_checkins(user: dict[str, Any], group_id: int) -> list[dict[str, Any]]:
    if not _member(group_id, int(user["id"])):
        raise ForbiddenError("你不在这个班级群")
    return connection.query_all(
        """SELECT c.*, (SELECT COUNT(*) FROM group_checkin_records r WHERE r.checkin_id = c.id) AS checked_count
             FROM group_checkins c WHERE c.group_id = ? ORDER BY c.id DESC LIMIT 20""",
        (group_id,),
    )


def close(user: dict[str, Any], checkin_id: int) -> dict[str, Any]:
    checkin = get_checkin(checkin_id)
    group = _group(int(checkin["group_id"]))
    if not _is_teacher_of(group, user):
        raise ForbiddenError("只有老师可以结束签到")
    connection.execute("UPDATE group_checkins SET status = 'closed' WHERE id = ?", (checkin_id,))
    return {"checkin_id": checkin_id, "status": "closed"}
''', encoding="utf-8")
    print("checkin_service: 已创建")

# ---------------- 路由 ----------------
r = Path(r"D:\EduFlow\backend\api\checkin_routes.py")
if not r.exists():
    r.write_text('''"""群签到接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.services import checkin_service

router = Router()


@router.post("/api/groups/<int:group_id>/checkins", roles=("teacher", "admin"), summary="发起签到")
def start_checkin(req) -> Response:
    user = permissions.require_teacher(req.user)
    return created(checkin_service.start_checkin(user, req.path_params["group_id"], req.json()), "签到已开始")


@router.get("/api/groups/<int:group_id>/checkins/active", summary="当前签到")
def active_checkin(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(checkin_service.active_checkin(user, req.path_params["group_id"]))


@router.get("/api/groups/<int:group_id>/checkins", summary="签到历史")
def list_checkins(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(checkin_service.list_checkins(user, req.path_params["group_id"]))


@router.post("/api/checkins/<int:checkin_id>/respond", roles=("student",), summary="学生签到")
def respond(req) -> Response:
    user = permissions.require_role(req.user, "student")
    data = req.json()
    return ok(checkin_service.respond(user, req.path_params["checkin_id"], data.get("answer", "")), "签到成功")


@router.get("/api/checkins/<int:checkin_id>/status", roles=("teacher", "admin"), summary="签到情况")
def status(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(checkin_service.status(user, req.path_params["checkin_id"]))


@router.post("/api/checkins/<int:checkin_id>/close", roles=("teacher", "admin"), summary="结束签到")
def close(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(checkin_service.close(user, req.path_params["checkin_id"]), "已结束")
''', encoding="utf-8")
    print("checkin_routes: 已创建")

# ---------------- 注册 ----------------
a = Path(r"D:\EduFlow\backend\app.py")
t = a.read_text(encoding="utf-8")
if "checkin_routes" not in t:
    lines = t.splitlines()
    out = []
    for line in lines:
        out.append(line)
        if line.strip() == "enroll_routes," and "from backend.api import" not in line:
            pass
    t = t.replace("        from backend.api import (", "        from backend.api import (\n            checkin_routes,", 1)
    t = t.replace("            enroll_routes,", "            enroll_routes,\n            checkin_routes,", 1)
    a.write_text(t, encoding="utf-8")
    print("app.py: 注册签到路由")
