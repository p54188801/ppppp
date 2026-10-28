"""首页接入班级群数据：学生人数、待批改、即将截止、待交作业。"""

from pathlib import Path

svc = Path(r"D:\EduFlow\backend\services\statistics_service.py")
t = svc.read_text(encoding="utf-8")

if "def group_overlay" not in t:
    func = '''

# ---------------------------------------------------------------------------
# 班级群数据（首页用）
# ---------------------------------------------------------------------------


def _my_group_ids(user: dict[str, Any]) -> list[int]:
    role = user["role"]
    uid = int(user["id"])
    if role == permissions.ROLE_ADMIN:
        rows = connection.query_all("SELECT id FROM class_groups")
    else:
        rows = connection.query_all(
            """SELECT g.id FROM class_groups g
                 LEFT JOIN group_members m ON m.group_id = g.id AND m.user_id = ?
                WHERE g.teacher_id = ? OR m.id IS NOT NULL""",
            (uid, uid),
        )
    return [int(r["id"]) for r in rows]


def group_overlay(user: dict[str, Any]) -> dict[str, Any]:
    """把班级群的人数/作业/提交情况算出来，供首页展示。"""
    gids = _my_group_ids(user)
    if not gids:
        return {"groups": 0, "students": 0, "ungraded": 0, "upcoming": [], "pending": [], "submitted": 0}
    marks = ",".join("?" for _ in gids)
    now = clock.now_iso()

    students = connection.query_all(
        f"""SELECT DISTINCT user_id FROM group_members
             WHERE group_id IN ({marks}) AND role = 'student'""",
        tuple(gids),
    )
    student_ids = [int(r["user_id"]) for r in students]

    ungraded = int(
        connection.scalar(
            f"""SELECT COUNT(*) FROM group_submissions s
                  JOIN group_assignments a ON a.id = s.assignment_id
                 WHERE a.group_id IN ({marks}) AND s.score IS NULL""",
            tuple(gids),
            default=0,
        )
        or 0
    )
    submitted = int(
        connection.scalar(
            f"""SELECT COUNT(*) FROM group_submissions s
                  JOIN group_assignments a ON a.id = s.assignment_id
                 WHERE a.group_id IN ({marks})""",
            tuple(gids),
            default=0,
        )
        or 0
    )
    upcoming = connection.query_all(
        f"""SELECT a.id, a.title, a.deadline, a.full_score, g.name AS class_name,
                   a.group_id, 'group' AS source
              FROM group_assignments a
              JOIN class_groups g ON g.id = a.group_id
             WHERE a.group_id IN ({marks}) AND (a.deadline IS NULL OR a.deadline > ?)
             ORDER BY COALESCE(a.deadline, '9999') ASC LIMIT 8""",
        tuple(gids) + (now,),
    )

    pending: list[dict[str, Any]] = []
    if user["role"] == permissions.ROLE_STUDENT:
        pending = connection.query_all(
            f"""SELECT a.id, a.title, a.deadline, a.full_score, g.name AS class_name,
                       a.group_id, 'group' AS source
                  FROM group_assignments a
                  JOIN class_groups g ON g.id = a.group_id
                 WHERE a.group_id IN ({marks})
                   AND NOT EXISTS (SELECT 1 FROM group_submissions s
                                    WHERE s.assignment_id = a.id AND s.student_id = ?)
                 ORDER BY COALESCE(a.deadline, '9999') ASC""",
            tuple(gids) + (int(user["id"]),),
        )

    return {
        "groups": len(gids),
        "students": len(student_ids),
        "ungraded": ungraded,
        "submitted": submitted,
        "upcoming": upcoming,
        "pending": pending,
    }


def merge_group_overlay(user: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """把群数据合并进首页返回结构。"""
    overlay = group_overlay(user)
    data["group"] = overlay

    upcoming = list(data.get("upcoming") or [])
    upcoming.extend(overlay["upcoming"])
    upcoming.sort(key=lambda x: x.get("deadline") or "9999")
    data["upcoming"] = upcoming[:8]

    totals = data.get("totals")
    if isinstance(totals, dict):
        totals["group_students"] = overlay["students"]
        totals["students"] = max(int(totals.get("students") or 0), overlay["students"])
        totals["ungraded"] = int(totals.get("ungraded") or 0) + overlay["ungraded"]
        totals["pending"] = int(totals.get("pending") or 0) + len(overlay["pending"])

    pending = list(data.get("pending_assignments") or [])
    pending.extend(overlay["pending"])
    pending.sort(key=lambda x: x.get("deadline") or "9999")
    data["pending_assignments"] = pending
    return data
'''
    t = t.rstrip() + func
    svc.write_text(t, encoding="utf-8")
    print("statistics_service: 已加 group_overlay / merge_group_overlay")

# 路由层合并
r = Path(r"D:\EduFlow\backend\api\report_routes.py")
t = r.read_text(encoding="utf-8")
if "merge_group_overlay" not in t:
    t = t.replace(
        "statistics_service.dashboard(user)",
        "statistics_service.merge_group_overlay(user, statistics_service.dashboard(user))",
    )
    r.write_text(t, encoding="utf-8")
    print("report_routes: 首页合并群数据")
