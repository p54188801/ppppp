"""成绩服务：权重配置、成绩计算、成绩单导出。

计算模型（可在每个教学班单独配置）：
    总评 = 作业均分×w1 + 测验均分×w2 + 出勤率×w3 + 期末×w4 + 加分
所有分项先归一化成百分制，再加权，避免不同满分口径互相污染。
"""

from __future__ import annotations

import csv
import io
from typing import Any

from backend import config
from backend.core import permissions, validators
from backend.core.errors import ForbiddenError, NotFoundError, ValidationError
from backend.db import connection
from backend.repositories.assignments import AssignmentRepository, SubmissionRepository
from backend.repositories.attendance import AttendanceRecordRepository
from backend.repositories.courses import ClassRepository, EnrollmentRepository
from backend.repositories.grades import GradeItemRepository, GradeRuleRepository
from backend.repositories.users import UserRepository

class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
assignment_repo = AssignmentRepository()
submission_repo = SubmissionRepository()
attendance_repo = AttendanceRecordRepository()
rule_repo = GradeRuleRepository()
item_repo = GradeItemRepository()
user_repo = UserRepository()


def _class_or_fail(class_id: int) -> dict[str, Any]:
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    return detail


def get_rule(operator: dict[str, Any], class_id: int) -> dict[str, Any]:
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)
    return rule_repo.get_or_default(class_id)


def save_rule(operator: dict[str, Any], class_id: int,
              payload: dict[str, Any]) -> dict[str, Any]:
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)

    weights = {
        "assignment_weight": validators.optional_float(
            payload, "assignment_weight", config.DEFAULT_GRADE_WEIGHTS["assignment"],
            min_value=0, max_value=1,
        ),
        "quiz_weight": validators.optional_float(
            payload, "quiz_weight", config.DEFAULT_GRADE_WEIGHTS["quiz"],
            min_value=0, max_value=1,
        ),
        "attendance_weight": validators.optional_float(
            payload, "attendance_weight", config.DEFAULT_GRADE_WEIGHTS["attendance"],
            min_value=0, max_value=1,
        ),
        "final_weight": validators.optional_float(
            payload, "final_weight", config.DEFAULT_GRADE_WEIGHTS["final"],
            min_value=0, max_value=1,
        ),
        "pass_score": validators.optional_float(payload, "pass_score", 60, min_value=0, max_value=100),
    }
    total_weight = round(sum(
        weights[key] for key in
        ("assignment_weight", "quiz_weight", "attendance_weight", "final_weight")
    ), 4)
    if abs(total_weight - 1.0) > 0.001:
        raise ValidationError(f"各项权重之和必须为 1，当前为 {total_weight}")
    rule_repo.save(class_id, weights)
    return rule_repo.get_or_default(class_id)


def _assignment_component(class_id: int, student_id: int) -> tuple[float, int]:
    rows = submission_repo.student_scores(class_id, student_id)
    total_full = sum(float(row["full_score"] or 100) for row in rows)
    total_got = sum(float(row["score"]) for row in rows if row.get("score") is not None)
    if total_full <= 0:
        return 0.0, 0
    return round(total_got / total_full * 100, 2), len(rows)


def _quiz_component(class_id: int, student_id: int) -> tuple[float, int]:
    rows = connection.query_all(
        """SELECT q.total_score, a.score
             FROM quizzes q
             JOIN quiz_attempts a ON a.quiz_id = q.id AND a.student_id = ?
            WHERE q.class_id = ? AND a.status IN ('submitted', 'graded')""",
        (student_id, class_id),
    )
    if not rows:
        return 0.0, 0
    rates = []
    for row in rows:
        total = float(row["total_score"] or 0)
        if total > 0:
            rates.append(float(row["score"] or 0) / total * 100)
    if not rates:
        return 0.0, len(rows)
    return round(sum(rates) / len(rates), 2), len(rows)


def _attendance_component(class_id: int, student_id: int) -> tuple[float, dict[str, int]]:
    summary = attendance_repo.student_summary(class_id, student_id)
    return round(float(summary.get("rate") or 0) * 100, 2), summary


def compute_student(class_id: int, student_id: int,
                    rule: dict[str, Any] | None = None,
                    final_override: float | None = None) -> dict[str, Any]:
    """计算单个学生的成绩明细。"""
    rule = rule or rule_repo.get_or_default(class_id)
    assignment_score, assignment_count = _assignment_component(class_id, student_id)
    quiz_score, quiz_count = _quiz_component(class_id, student_id)
    attendance_score, attendance_summary = _attendance_component(class_id, student_id)

    item = item_repo.get(class_id, student_id) or {}
    final_score = final_override if final_override is not None else item.get("final_score")
    final_value = float(final_score) if final_score is not None else None
    bonus = float(item.get("bonus") or 0)

    weights = rule
    total = (
        assignment_score * float(weights.get("assignment_weight") or 0)
        + quiz_score * float(weights.get("quiz_weight") or 0)
        + attendance_score * float(weights.get("attendance_weight") or 0)
        + (final_value if final_value is not None else 0) * float(weights.get("final_weight") or 0)
        + bonus
    )
    total = round(min(100.0, max(0.0, total)), 2)
    return {
        "student_id": student_id,
        "assignment_score": assignment_score,
        "assignment_count": assignment_count,
        "quiz_score": quiz_score,
        "quiz_count": quiz_count,
        "attendance_score": attendance_score,
        "attendance": attendance_summary,
        "final_score": final_value,
        "bonus": bonus,
        "total": total,
        "passed": total >= float(weights.get("pass_score") or 60),
        "grade_point": _to_gpa(total),
        "remark": item.get("remark") or "",
    }


def _to_gpa(score: float) -> float:
    """百分制 -> 4.0 绩点（常见换算规则）。"""
    if score >= 90:
        return 4.0
    if score >= 85:
        return 3.7
    if score >= 82:
        return 3.3
    if score >= 78:
        return 3.0
    if score >= 75:
        return 2.7
    if score >= 72:
        return 2.3
    if score >= 68:
        return 2.0
    if score >= 64:
        return 1.5
    if score >= 60:
        return 1.0
    return 0.0


def gradebook(operator: dict[str, Any], class_id: int) -> dict[str, Any]:
    """整班成绩册。"""
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)
    rule = rule_repo.get_or_default(class_id)
    students = class_repo.students(class_id)
    rows = []
    for student in students:
        computed = compute_student(class_id, int(student["id"]), rule)
        computed.update(
            {
                "real_name": student["real_name"],
                "number": student.get("number") or "",
                "department": student.get("department") or "",
            }
        )
        rows.append(computed)

    scores = [row["total"] for row in rows]
    stats = {
        "count": len(rows),
        "average": round(sum(scores) / len(scores), 2) if scores else 0,
        "max": max(scores) if scores else 0,
        "min": min(scores) if scores else 0,
        "pass_count": sum(1 for s in scores if s >= float(rule.get("pass_score") or 60)),
        "excellent_count": sum(1 for s in scores if s >= 90),
    }
    stats["pass_rate"] = round(stats["pass_count"] / stats["count"] * 100, 1) if stats["count"] else 0
    stats["excellent_rate"] = round(stats["excellent_count"] / stats["count"] * 100, 1) if stats["count"] else 0
    return {"class": detail, "rule": rule, "rows": rows, "stats": stats}


def set_final_score(operator: dict[str, Any], class_id: int,
                    payload: dict[str, Any]) -> dict[str, Any]:
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)
    student_id = validators.required_int(payload, "student_id", min_value=1)
    final_score = validators.optional_float(payload, "final_score", None, min_value=0, max_value=100)
    bonus = validators.optional_float(payload, "bonus", 0, min_value=-20, max_value=20)
    remark = validators.optional_str(payload, "remark", "", max_len=200)

    item_repo.upsert(
        class_id,
        student_id,
        {"final_score": final_score, "bonus": bonus, "remark": remark},
    )
    computed = compute_student(class_id, student_id)
    item_repo.set_total(class_id, student_id, computed["total"])
    return computed


def batch_set_final(operator: dict[str, Any], class_id: int,
                    rows: list[dict[str, Any]]) -> dict[str, Any]:
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)
    updated = 0
    failed: list[dict[str, Any]] = []
    for row in rows:
        try:
            set_final_score(operator, class_id, row)
            updated += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"student_id": row.get("student_id"), "error": str(exc)})
    return {"updated": updated, "failed": failed}


def my_transcript(student: dict[str, Any]) -> dict[str, Any]:
    """学生成绩单：按课程列出总分与绩点。"""
    permissions.require_role(student, permissions.ROLE_STUDENT)
    classes = class_repo.all(
        where="id IN (SELECT class_id FROM enrollments WHERE student_id = ? AND status = 'active')",
        params=(int(student["id"]),),
        order_by="id",
    )
    rows = []
    total_credit = 0.0
    total_point = 0.0
    for item in classes:
        class_id = int(item["id"])
        detail = class_repo.detail(class_id) or {}
        computed = compute_student(class_id, int(student["id"]))
        credits = float(detail.get("credits") or 0)
        computed.update(
            {
                "class_id": class_id,
                "class_name": detail.get("class_name") or item.get("name"),
                "course_name": detail.get("course_name"),
                "credits": credits,
            }
        )
        rows.append(computed)
        total_credit += credits
        total_point += computed["grade_point"] * credits

    gpa = round(total_point / total_credit, 2) if total_credit else 0.0
    return {
        "rows": rows,
        "total_credits": round(total_credit, 1),
        "gpa": gpa,
        "average": round(sum(row["total"] for row in rows) / len(rows), 2) if rows else 0,
    }


def export_csv(operator: dict[str, Any], class_id: int) -> str:
    """导出成绩册 CSV 文本。"""
    book = gradebook(operator, class_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["学号", "姓名", "作业", "测验", "出勤", "期末", "加分", "总评", "绩点", "是否通过"]
    )
    for row in book["rows"]:
        writer.writerow(
            [
                row.get("number", ""),
                row.get("real_name", ""),
                row["assignment_score"],
                row["quiz_score"],
                row["attendance_score"],
                "" if row["final_score"] is None else row["final_score"],
                row["bonus"],
                row["total"],
                row["grade_point"],
                "是" if row["passed"] else "否",
            ]
        )
    return buffer.getvalue()


def class_ranking(operator: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
    book = gradebook(operator, class_id)
    rows = sorted(book["rows"], key=lambda item: item["total"], reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows
