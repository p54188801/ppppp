"""催交记录表 + 未交名单导出 + 催交历史接口。"""

from pathlib import Path

# ---------------- 迁移 v7 ----------------
m = Path(r"D:\EduFlow\backend\db\migrations.py")
t = m.read_text(encoding="utf-8")
t = t.replace("CURRENT_VERSION = 6", "CURRENT_VERSION = 7")
if "_migrate_v7" not in t:
    func = '''
def _migrate_v7(conn: sqlite3.Connection) -> None:
    """v6 -> v7：催交记录。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS assignment_reminders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            operator_id   INTEGER NOT NULL REFERENCES users(id),
            created_at    TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reminders ON assignment_reminders(assignment_id, created_at);
        """
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
'''
    t = t.replace("MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [", func, 1)
    out = []
    for line in t.splitlines():
        out.append(line)
        if line.strip() == "(6, _migrate_v6),":
            out.append("    (7, _migrate_v7),")
    t = "\n".join(out)
    t = t.replace('"timetable",', '"timetable",\n        "assignment_reminders",')
    m.write_text(t, encoding="utf-8")
    print("migrations: 已加 v7 催交记录")

# ---------------- 服务 ----------------
s = Path(r"D:\EduFlow\backend\services\assignment_service.py")
t = s.read_text(encoding="utf-8")

if "assignment_reminders" not in t:
    t = t.replace(
        "    sent = notification_service.notify_many(",
        """    from backend.db import connection

    now = clock.now_iso()
    for m in missing:
        connection.execute(
            "INSERT INTO assignment_reminders (assignment_id, student_id, operator_id, created_at)"
            " VALUES (?, ?, ?, ?)",
            (assignment_id, int(m["student_id"]), int(user["id"]), now),
        )
    sent = notification_service.notify_many(""",
        1,
    )
    s.write_text(t, encoding="utf-8")
    print("assignment_service: 已记录催交")

if "def reminder_history" not in t:
    func = '''

def reminder_history(user: dict[str, Any], assignment_id: int) -> dict[str, Any]:
    """催交记录：最近几次催交 + 每人被催次数。"""
    from backend.db import connection

    progress = submission_progress(user, assignment_id)
    rows = connection.query_all(
        """SELECT r.created_at, r.student_id, u.real_name AS student_name,
                  op.real_name AS operator_name
             FROM assignment_reminders r
             JOIN users u ON u.id = r.student_id
             LEFT JOIN users op ON op.id = r.operator_id
            WHERE r.assignment_id = ?
            ORDER BY r.created_at DESC""",
        (assignment_id,),
    )
    batches: dict[str, dict[str, Any]] = {}
    per_student: dict[int, dict[str, Any]] = {}
    for r in rows:
        key = r["created_at"]
        batch = batches.setdefault(
            key, {"created_at": key, "operator_name": r["operator_name"] or "", "students": []}
        )
        batch["students"].append(r["student_name"])
        item = per_student.setdefault(
            int(r["student_id"]), {"student_id": int(r["student_id"]), "name": r["student_name"], "times": 0}
        )
        item["times"] += 1

    return {
        "assignment_id": assignment_id,
        "title": progress["title"],
        "total_reminded": len(rows),
        "batches": list(batches.values())[:20],
        "per_student": sorted(per_student.values(), key=lambda x: -x["times"]),
    }
'''
    t = t.rstrip() + func
    s.write_text(t, encoding="utf-8")
    print("assignment_service: 已加 reminder_history")

# ---------------- 路由 ----------------
r = Path(r"D:\EduFlow\backend\api\assignment_routes.py")
t = r.read_text(encoding="utf-8")
if "remind-history" not in t:
    route = '''

@router.get("/api/assignments/<int:assignment_id>/remind-history",
            roles=("teacher", "admin"), summary="催交记录")
def reminder_history(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(assignment_service.reminder_history(user, req.path_params["assignment_id"]))


@router.get("/api/assignments/<int:assignment_id>/missing/export",
            roles=("teacher", "admin"), summary="导出未交名单 CSV")
def export_missing(req) -> Response:
    import csv
    import io

    user = permissions.require_login(req.user)
    data = assignment_service.submission_progress(user, req.path_params["assignment_id"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["作业", data["title"]])
    w.writerow(["班级", data["class_name"]])
    w.writerow(["应交", data["total"], "已交", data["submitted_count"], "未交", data["missing_count"]])
    w.writerow([])
    w.writerow(["学号", "姓名", "状态"])
    for m in data["missing"]:
        w.writerow([m["number"], m["real_name"], "未交"])
    if not data["missing"]:
        w.writerow(["-", "全部已交", ""])
    from backend.http.response import Response as R

    return R(status=200, body=buf.getvalue().encode("utf-8-sig"),
             content_type="text/csv; charset=utf-8",
             headers={"Content-Disposition": "attachment; filename=missing_students.csv"})
'''
    t = t.rstrip() + route
    r.write_text(t, encoding="utf-8")
    print("assignment_routes: 已加催交记录与导出")
