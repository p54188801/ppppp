"""在线测验服务。

覆盖出题、组卷、发卷、答题、自动判分、人工复评的全流程。
自动判分规则：
- 单选/判断：选项完全一致得分；
- 多选：完全一致才得分（不给部分分，避免争议）；
- 填空：忽略首尾空白与大小写，支持用 | 分隔多个可接受答案；
- 简答：不自动判分，等教师人工给分。
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any

from backend import config
from backend.core import clock, permissions, validators
from backend.core.errors import ConflictError, ForbiddenError, NotFoundError
from backend.repositories.audit import AuditRepository
from backend.repositories.content import NotificationRepository
from backend.repositories.courses import ClassRepository, EnrollmentRepository
from backend.repositories.quizzes import (
    AttemptRepository,
    QuestionRepository,
    QuizRepository,
)
from backend.services.notification_service import notify_class

logger = logging.getLogger("eduflow.quiz")

quiz_repo = QuizRepository()
question_repo = QuestionRepository()
attempt_repo = AttemptRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
audit_repo = AuditRepository()

QUESTION_TYPES = ("single", "multi", "judge", "fill", "essay")
TYPE_LABELS = {
    "single": "单选题",
    "multi": "多选题",
    "judge": "判断题",
    "fill": "填空题",
    "essay": "简答题",
}


def _class_or_fail(class_id: int) -> dict[str, Any]:
    detail = class_repo.detail(class_id)
    if detail is None:
        raise NotFoundError("教学班不存在")
    return detail


def _normalize_questions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise validators.ValidationError("至少需要一道题目")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise validators.ValidationError(f"第 {index + 1} 题格式不正确")
        qtype = validators.ensure_enum(
            str(item.get("type") or ""), QUESTION_TYPES, f"第 {index + 1} 题类型"
        )
        stem = validators.required_str(item, "stem", min_len=1, max_len=2000)
        score = validators.optional_float(item, "score", 5, min_value=0.5, max_value=100)
        options = item.get("options") or []
        if qtype in ("single", "multi"):
            if not isinstance(options, list) or len(options) < 2:
                raise validators.ValidationError(f"第 {index + 1} 题至少需要两个选项")
            options = [str(opt) for opt in options]
        else:
            options = []
        answer = str(item.get("answer") or "").strip()
        if qtype != "essay" and not answer:
            raise validators.ValidationError(f"第 {index + 1} 题缺少答案")
        normalized.append(
            {
                "type": qtype,
                "stem": stem,
                "options": json.dumps(options, ensure_ascii=False) if options else None,
                "answer": answer,
                "analysis": validators.optional_str(item, "analysis", "", max_len=2000),
                "score": score,
                "order_no": index,
            }
        )
    return normalized


def create_quiz(payload: dict[str, Any], operator: dict[str, Any]) -> dict[str, Any]:
    permissions.require_teacher(operator)
    class_id = validators.required_int(payload, "class_id", min_value=1)
    detail = _class_or_fail(class_id)
    permissions.assert_can_manage_course(operator, detail)

    title = validators.required_str(payload, "title", min_len=1, max_len=120)
    questions = _normalize_questions(payload.get("questions"))
    total = round(sum(float(item["score"]) for item in questions), 2)
    duration = validators.optional_int(payload, "duration", config.QUIZ_DEFAULT_DURATION,
                                       min_value=1, max_value=300)

    quiz_id = quiz_repo.insert(
        {
            "class_id": class_id,
            "title": title,
            "description": validators.optional_str(payload, "description", "", max_len=2000),
            "start_at": validators.validate_date(payload.get("start_at"), "开始时间", required_field=False) or None,
            "end_at": validators.validate_date(payload.get("end_at"), "结束时间", required_field=False) or None,
            "duration": duration,
            "total_score": total,
            "shuffle": 1 if validators.to_bool(payload.get("shuffle"), True) else 0,
            "show_answer": 1 if validators.to_bool(payload.get("show_answer"), True) else 0,
            "status": "published",
            "created_by": int(operator["id"]),
        }
    )
    question_repo.replace_for_quiz(quiz_id, questions)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="create_quiz",
        entity="quiz",
        entity_id=quiz_id,
        detail=f"{detail['course_name']} / {title} / {len(questions)} 题 / {total} 分",
    )
    students = [int(row["id"]) for row in class_repo.students(class_id)]
    if students:
        notify_class(
            students,
            title=f"新测验：{title}",
            content=f"{detail['course_name']} 发布了测验，共 {len(questions)} 题，满分 {total}",
            category="quiz",
            link=f"/quizzes/{quiz_id}",
        )
    return get_quiz(operator, quiz_id)


def get_quiz(viewer: dict[str, Any], quiz_id: int) -> dict[str, Any]:
    quiz = quiz_repo.detail(quiz_id)
    if quiz is None:
        raise NotFoundError("测验不存在")
    class_id = int(quiz["class_id"])
    detail = _class_or_fail(class_id)
    questions = question_repo.list_by_quiz(quiz_id)
    for question in questions:
        question["options"] = json.loads(question["options"]) if question.get("options") else []
        question["type_label"] = TYPE_LABELS.get(question["type"], question["type"])

    if viewer["role"] == permissions.ROLE_STUDENT:
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")
        attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
        quiz["my_attempt"] = attempt
        quiz["questions"] = _sanitize_questions(questions, show_answer=False)
    else:
        permissions.assert_can_manage_course(viewer, detail)
        quiz["questions"] = questions
        quiz["stats"] = attempt_repo.stats(quiz_id)
    return quiz


def _sanitize_questions(questions: list[dict[str, Any]], *,
                        show_answer: bool) -> list[dict[str, Any]]:
    """给学生的题目必须去掉正确答案与解析。"""
    result = []
    for question in questions:
        item = {
            "id": question["id"],
            "type": question["type"],
            "type_label": question.get("type_label"),
            "stem": question["stem"],
            "options": question.get("options") or [],
            "score": question["score"],
            "order_no": question["order_no"],
        }
        if show_answer:
            item["answer"] = question.get("answer")
            item["analysis"] = question.get("analysis")
        result.append(item)
    return result


def list_for_class(viewer: dict[str, Any], class_id: int) -> list[dict[str, Any]]:
    detail = _class_or_fail(class_id)
    if viewer["role"] == permissions.ROLE_STUDENT:
        if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
            raise ForbiddenError("未选修该课程")
    else:
        permissions.assert_can_manage_course(viewer, detail)
    return quiz_repo.list_by_class(class_id)


def student_quizzes(viewer: dict[str, Any]) -> list[dict[str, Any]]:
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    return quiz_repo.list_for_student(int(viewer["id"]))


def start_attempt(viewer: dict[str, Any], quiz_id: int) -> dict[str, Any]:
    """开始答题；返回题目（可能乱序）与截止时间。"""
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    quiz = quiz_repo.detail(quiz_id)
    if quiz is None:
        raise NotFoundError("测验不存在")
    class_id = int(quiz["class_id"])
    if not enroll_repo.is_enrolled(class_id, int(viewer["id"])):
        raise ForbiddenError("未选修该课程")
    if quiz.get("status") != "published":
        raise ConflictError("该测验未开放")

    now = clock.utcnow()
    start_at = clock.parse_iso(quiz.get("start_at"))
    end_at = clock.parse_iso(quiz.get("end_at"))
    if start_at and now < start_at:
        raise ConflictError("测验尚未开始")
    if end_at and now > end_at:
        raise ConflictError("测验已结束")

    attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
    if attempt and attempt.get("status") in ("submitted", "graded"):
        raise ConflictError("你已经提交过该测验")

    if not attempt:
        attempt_id = attempt_repo.start(quiz_id, int(viewer["id"]))
        attempt = attempt_repo.find(attempt_id)

    questions = question_repo.list_by_quiz(quiz_id)
    for question in questions:
        question["options"] = json.loads(question["options"]) if question.get("options") else []
        question["type_label"] = TYPE_LABELS.get(question["type"], question["type"])
    if quiz.get("shuffle"):
        rng = random.Random(f"{quiz_id}-{viewer['id']}")
        rng.shuffle(questions)

    started = clock.parse_iso(attempt.get("started_at")) or now
    deadline = clock.add_minutes(started, int(quiz.get("duration") or 45))
    if end_at and deadline > end_at:
        deadline = end_at

    saved = json.loads(attempt["answers"]) if attempt.get("answers") else {}
    return {
        "attempt_id": int(attempt["id"]),
        "quiz": {
            "id": quiz_id,
            "title": quiz["title"],
            "duration": quiz["duration"],
            "total_score": quiz["total_score"],
        },
        "questions": _sanitize_questions(questions, show_answer=False),
        "saved_answers": saved,
        "deadline": clock.to_iso(deadline),
        "remaining_seconds": max(0, int((deadline - now).total_seconds())),
    }


def save_answers(viewer: dict[str, Any], quiz_id: int,
                 answers: dict[str, Any]) -> dict[str, Any]:
    """自动保存（前端每 10 秒上报一次）。"""
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
    if not attempt:
        raise NotFoundError("尚未开始答题")
    if attempt.get("status") != "in_progress":
        raise ConflictError("答题已结束")
    payload = json.dumps(answers or {}, ensure_ascii=False)
    attempt_repo.save_answers(int(attempt["id"]), payload)
    return {"saved": len(answers or {}), "at": clock.now_iso()}


def submit_attempt(viewer: dict[str, Any], quiz_id: int,
                   answers: dict[str, Any]) -> dict[str, Any]:
    permissions.require_role(viewer, permissions.ROLE_STUDENT)
    quiz = quiz_repo.detail(quiz_id)
    if quiz is None:
        raise NotFoundError("测验不存在")
    attempt = attempt_repo.by_student(quiz_id, int(viewer["id"]))
    if not attempt:
        raise NotFoundError("尚未开始答题")
    if attempt.get("status") in ("submitted", "graded"):
        raise ConflictError("重复提交")

    questions = question_repo.list_by_quiz(quiz_id)
    score, detail_rows = _auto_grade(questions, answers or {})
    total = float(quiz.get("total_score") or 0)

    payload = json.dumps(answers or {}, ensure_ascii=False)
    attempt_repo.submit(int(attempt["id"]), round(score, 2), payload)
    audit_repo.log(
        user_id=int(viewer["id"]),
        username=viewer["username"],
        action="submit_quiz",
        entity="quiz",
        entity_id=quiz_id,
        detail=f"得分 {round(score, 2)} / {total}",
    )
    return {
        "score": round(score, 2),
        "total_score": total,
        "rate": round(score / total * 100, 1) if total else 0,
        "details": detail_rows,
    }


def _auto_grade(questions: list[dict[str, Any]],
                answers: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    score = 0.0
    rows: list[dict[str, Any]] = []
    for question in questions:
        qid = str(question["id"])
        given = str(answers.get(qid, "") or "").strip()
        expected = str(question.get("answer") or "").strip()
        qtype = question["type"]
        full = float(question.get("score") or 0)
        earned = 0.0
        if qtype == "single":
            earned = full if given and given.lower() == expected.lower() else 0.0
        elif qtype == "multi":
            given_set = {part.strip().lower() for part in given.split(",") if part.strip()}
            expected_set = {part.strip().lower() for part in expected.split(",") if part.strip()}
            earned = full if given_set and given_set == expected_set else 0.0
        elif qtype == "judge":
            earned = full if _judge_equal(given, expected) else 0.0
        elif qtype == "fill":
            accepted = [part.strip().lower() for part in expected.split("|") if part.strip()]
            earned = full if given.lower() in accepted and accepted else 0.0
        else:  # essay 留给人工
            earned = 0.0
        score += earned
        rows.append(
            {
                "question_id": question["id"],
                "type": qtype,
                "given": given,
                "expected": expected if qtype != "essay" else "",
                "earned": round(earned, 2),
                "full": full,
            }
        )
    return score, rows


def _judge_equal(given: str, expected: str) -> bool:
    truthy = {"对", "正确", "true", "t", "1", "是", "yes"}
    falsy = {"错", "错误", "false", "f", "0", "否", "no"}
    g = given.strip().lower()
    e = expected.strip().lower()
    if g in truthy and e in truthy:
        return True
    if g in falsy and e in falsy:
        return True
    return g == e


def manual_grade(operator: dict[str, Any], quiz_id: int,
                 student_id: int, score: float) -> dict[str, Any]:
    """教师给简答题手工复核（直接覆盖总分）。"""
    permissions.require_teacher(operator)
    quiz = quiz_repo.find_or_fail(quiz_id, "测验不存在")
    detail = _class_or_fail(int(quiz["class_id"]))
    permissions.assert_can_manage_course(operator, detail)
    total = float(quiz.get("total_score") or 100)
    final = validators.to_float(score, "分数", min_value=0, max_value=total)
    attempt = attempt_repo.by_student(quiz_id, student_id)
    if attempt is None:
        raise NotFoundError("该学生没有作答记录")
    attempt_repo.submit(int(attempt["id"]), final, attempt.get("answers") or "{}")
    return {"quiz_id": quiz_id, "student_id": student_id, "score": final}


def standings(operator: dict[str, Any], quiz_id: int) -> dict[str, Any]:
    permissions.require_teacher(operator)
    quiz = quiz_repo.find_or_fail(quiz_id, "测验不存在")
    detail = _class_or_fail(int(quiz["class_id"]))
    permissions.assert_can_manage_course(operator, detail)
    return {
        "quiz": quiz,
        "rows": attempt_repo.list_by_quiz(quiz_id),
        "stats": attempt_repo.stats(quiz_id),
    }
