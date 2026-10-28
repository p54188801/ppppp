"""统计分析服务：首页看板、课程活跃度、学习报告。"""

from __future__ import annotations

from typing import Any

from backend.core import clock, permissions
from backend.db import connection
from backend.repositories.audit import AuditRepository
from backend.repositories.courses import ClassRepository, CourseRepository, EnrollmentRepository
from backend.repositories.users import UserRepository

user_repo = UserRepository()
course_repo = CourseRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
audit_repo = AuditRepository()


def admin_dashboard() -> dict[str, Any]:
    """管理员首页：全局数字 + 最近动态。"""
    counts = user_repo.count_all()
    course_total = int(connection.scalar("SELECT COUNT(*) FROM courses", default=0) or 0)
    class_total = int(connection.scalar("SELECT COUNT(*) FROM classes", default=0) or 0)
    assignment_total = int(connection.scalar("SELECT COUNT(*) FROM assignments", default=0) or 0)
    submission_total = int(connection.scalar("SELECT COUNT(*) FROM submissions", default=0) or 0)
    attendance_total = int(
        connection.scalar("SELECT COUNT(*) FROM attendance_records", default=0) or 0
    )
    present_total = int(
        connection.scalar(
            "SELECT COUNT(*) FROM attendance_records WHERE status = 'present'", default=0
        )
        or 0
    )
    attendance_rate = round(present_total / attendance_total * 100, 1) if attendance_total else 0.0

    recent = audit_repo.list_logs(limit=10)
    trend = _activity_trend(days=7)
    return {
        "users": counts,
        "courses": course_total,
        "classes": class_total,
        "assignments": assignment_total,
        "submissions": submission_total,
        "attendance_rate": attendance_rate,
        "recent_logs": recent,
        "trend": trend,
        "generated_at": clock.now_iso(),
    }


def _activity_trend(days: int = 7) -> list[dict[str, Any]]:
    """最近 N 天每天的提交量与登录量。"""
    result: list[dict[str, Any]] = []
    today = clock.utcnow()
    for offset in range(days - 1, -1, -1):
        day = clock.add_days(today, -offset)
        day_start = clock.to_iso(clock.start_of_day(day))
        day_end = clock.to_iso(clock.add_days(clock.start_of_day(day), 1))
        submissions = int(
            connection.scalar(
                "SELECT COUNT(*) FROM submissions WHERE submitted_at >= ? AND submitted_at < ?",
                (day_start, day_end),
                default=0,
            )
            or 0
        )
        logins = int(
            connection.scalar(
                "SELECT COUNT(*) FROM login_attempts WHERE success = 1 AND created_at >= ? AND created_at < ?",
                (day_start, day_end),
                default=0,
            )
            or 0
        )
        result.append(
            {
                "date": day_start[:10],
                "submissions": submissions,
                "logins": logins,
            }
        )
    return result


def course_overview(operator: dict[str, Any], course_id: int) -> dict[str, Any]:
    """单门课程的活跃度概览。"""
    permissions.require_teacher(operator)
    course = course_repo.find_or_fail(course_id, "课程不存在")
    permissions.assert_can_manage_course(operator, course)

    classes = class_repo.of_course(course_id)
    class_ids = [int(item["id"]) for item in classes]
    if not class_ids:
        return {"course": course, "classes": [], "totals": {"students": 0, "submissions": 0}}

    placeholders = ",".join("?" for _ in class_ids)
    students = int(
        connection.scalar(
            f"SELECT COUNT(*) FROM enrollments WHERE status = 'active' AND class_id IN ({placeholders})",
            tuple(class_ids),
            default=0,
        )
        or 0
    )
    submissions = int(
        connection.scalar(
            f"""SELECT COUNT(*) FROM submissions s
                 JOIN assignments a ON a.id = s.assignment_id
                WHERE a.class_id IN ({placeholders})""",
            tuple(class_ids),
            default=0,
        )
        or 0
    )
    graded = int(
        connection.scalar(
            f"""SELECT COUNT(*) FROM submissions s
                 JOIN assignments a ON a.id = s.assignment_id
                WHERE a.class_id IN ({placeholders}) AND s.status = 'graded'""",
            tuple(class_ids),
            default=0,
        )
        or 0
    )
    return {
        "course": course,
        "classes": classes,
        "totals": {
            "students": students,
            "submissions": submissions,
            "graded": graded,
            "grade_rate": round(graded / submissions * 100, 1) if submissions else 0.0,
        },
    }


def student_report(student: dict[str, Any]) -> dict[str, Any]:
    """学生学习报告：待办、出勤、均分。"""
    permissions.require_role(student, permissions.ROLE_STUDENT)
    student_id = int(student["id"])
    pending = int(
        connection.scalar(
            """SELECT COUNT(*)
                 FROM assignments a
                 JOIN enrollments e ON e.class_id = a.class_id
                                   AND e.student_id = ? AND e.status = 'active'
                 LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
                WHERE a.status = 'published' AND s.id IS NULL""",
            (student_id, student_id),
            default=0,
        )
        or 0
    )
    enrolled = int(
        connection.scalar(
            "SELECT COUNT(*) FROM enrollments WHERE student_id = ? AND status = 'active'",
            (student_id,),
            default=0,
        )
        or 0
    )
    attendance = connection.query_one(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present,
                  SUM(CASE WHEN status = 'late' THEN 1 ELSE 0 END) AS late
             FROM attendance_records WHERE student_id = ?""",
        (student_id,),
    ) or {}
    total = int(attendance.get("total") or 0)
    present = int(attendance.get("present") or 0)
    late = int(attendance.get("late") or 0)

    avg_score = connection.scalar(
        """SELECT AVG(score) FROM submissions
            WHERE student_id = ? AND score IS NOT NULL""",
        (student_id,),
    )
    return {
        "student": {
            "id": student_id,
            "real_name": student["real_name"],
            "number": student.get("number") or "",
        },
        "enrolled_classes": enrolled,
        "pending_assignments": pending,
        "attendance": {
            "total": total,
            "present": present,
            "late": late,
            "rate": round((present + late * 0.5) / total * 100, 1) if total else 0.0,
        },
        "average_score": round(float(avg_score), 2) if avg_score is not None else None,
        "generated_at": clock.now_iso(),
    }


def teacher_dashboard(teacher: dict[str, Any]) -> dict[str, Any]:
    """教师首页汇总。"""
    permissions.require_teacher(teacher)
    classes = class_repo.of_teacher(int(teacher["id"]))
    class_ids = [int(item["id"]) for item in classes]
    if not class_ids:
        return {
            "classes": [],
            "totals": {"classes": 0, "students": 0, "pending": 0, "ungraded": 0},
        }
    placeholders = ",".join("?" for _ in class_ids)
    students = int(
        connection.scalar(
            f"SELECT COUNT(*) FROM enrollments WHERE status = 'active' AND class_id IN ({placeholders})",
            tuple(class_ids),
            default=0,
        )
        or 0
    )
    ungraded = int(
        connection.scalar(
            f"""SELECT COUNT(*) FROM submissions s
                 JOIN assignments a ON a.id = s.assignment_id
                WHERE a.class_id IN ({placeholders}) AND s.status <> 'graded'""",
            tuple(class_ids),
            default=0,
        )
        or 0
    )
    upcoming = connection.query_all(
        f"""SELECT a.id, a.title, a.deadline, cl.name AS class_name
              FROM assignments a
              JOIN classes cl ON cl.id = a.class_id
             WHERE a.class_id IN ({placeholders}) AND a.deadline > ?
             ORDER BY a.deadline ASC LIMIT 5""",
        tuple(class_ids) + (clock.now_iso(),),
    )
    return {
        "classes": classes,
        "totals": {
            "classes": len(classes),
            "students": students,
            "pending": 0,
            "ungraded": ungraded,
        },
        "upcoming": upcoming,
        "generated_at": clock.now_iso(),
    }

def my_todos(viewer: dict[str, Any]) -> dict[str, Any]:
    """待办中心：聚合当前用户所有待处理事项。"""
    from backend.repositories.assignments import AssignmentRepository
    from backend.repositories.attendance import AttendanceSessionRepository
    from backend.repositories.courses import ClassRepository

    user_id = int(viewer["id"])
    now = clock.now_iso()
    if viewer["role"] == permissions.ROLE_STUDENT:
        pending = AssignmentRepository().list_for_student(user_id, status="pending", limit=50)
        sessions = AttendanceSessionRepository().list_open_for_student(user_id)
        quizzes = connection.query_all(
            """SELECT q.id, q.title, q.end_at, q.duration, c.name AS course_name,
                      a.id AS attempt_id
                 FROM quizzes q
                 JOIN classes cl ON cl.id = q.class_id
                 JOIN courses c ON c.id = cl.course_id
                 JOIN enrollments e ON e.class_id = q.class_id AND e.student_id = ?
                                   AND e.status = 'active'
                 LEFT JOIN quiz_attempts a ON a.quiz_id = q.id AND a.student_id = ?
                WHERE q.status = 'published' AND a.id IS NULL
                  AND (q.end_at IS NULL OR q.end_at > ?)
                ORDER BY COALESCE(q.end_at, '9999') ASC""",
            (user_id, user_id, now),
        )
        total = len(pending) + len(sessions) + len(quizzes)
        return {
            "role": "student",
            "total": total,
            "pending_assignments": pending,
            "open_attendance": sessions,
            "upcoming_quizzes": quizzes,
        }
    if viewer["role"] == permissions.ROLE_TEACHER:
        classes = ClassRepository().of_teacher(user_id)
        class_ids = [int(c["id"]) for c in classes]
        ungraded = []
        if class_ids:
            marks = ",".join("?" for _ in class_ids)
            ungraded = connection.query_all(
                f"""SELECT s.id, s.submitted_at, a.title, a.class_id, cl.name AS class_name,
                           u.real_name AS student_name
                      FROM submissions s
                      JOIN assignments a ON a.id = s.assignment_id
                      JOIN classes cl ON cl.id = a.class_id
                      JOIN users u ON u.id = s.student_id
                     WHERE a.class_id IN ({marks}) AND s.status <> 'graded'
                     ORDER BY s.submitted_at ASC LIMIT 20""",
                tuple(class_ids),
            )
        return {
            "role": "teacher",
            "total": len(ungraded),
            "ungraded": ungraded,
        }
    return {"role": "admin", "total": 0}