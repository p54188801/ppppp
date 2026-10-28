"""作业提交进度：已交名单 / 未交名单。"""

from pathlib import Path

svc = Path(r"D:\EduFlow\backend\services\assignment_service.py")
t = svc.read_text(encoding="utf-8")

if "def submission_progress" not in t:
    func = '''

def submission_progress(user: dict[str, Any], assignment_id: int) -> dict[str, Any]:
    """教师视角：谁交了、谁没交。"""
    from backend.db import connection

    assignment = assignment_repo.find_or_fail(assignment_id, "作业不存在")
    cls = connection.query_one("SELECT * FROM classes WHERE id = ?", (int(assignment["class_id"]),))
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
'''
    t = t.rstrip() + func
    svc.write_text(t, encoding="utf-8")
    print("assignment_service: 已加 submission_progress")

r = Path(r"D:\EduFlow\backend\api\assignment_routes.py")
t = r.read_text(encoding="utf-8")
if "progress" not in t:
    route = '''

@router.get("/api/assignments/<int:assignment_id>/progress",
            roles=("teacher", "admin"), summary="提交进度与未交名单")
def submission_progress(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(assignment_service.submission_progress(user, req.path_params["assignment_id"]))
'''
    t = t.rstrip() + route
    r.write_text(t, encoding="utf-8")
    print("assignment_routes: 已加 progress 接口")
