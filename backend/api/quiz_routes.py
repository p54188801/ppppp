"""测验接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.services import quiz_service

router = Router()


@router.get("/api/classes/<int:class_id>/quizzes", summary="教学班测验列表")
def list_class_quizzes(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(quiz_service.list_for_class(user, req.path_params["class_id"]))


@router.post("/api/quizzes", roles=("teacher", "admin"), summary="创建测验")
def create_quiz(req) -> Response:
    user = permissions.require_teacher(req.user)
    return created(quiz_service.create_quiz(req.json(), operator=user), "测验已创建")


@router.get("/api/quizzes/<int:quiz_id>", summary="测验详情")
def get_quiz(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(quiz_service.get_quiz(user, req.path_params["quiz_id"]))


@router.get("/api/my/quizzes", roles=("student",), summary="我的测验")
def my_quizzes(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(quiz_service.student_quizzes(user))


@router.post("/api/quizzes/<int:quiz_id>/start", roles=("student",), summary="开始答题")
def start_quiz(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(quiz_service.start_attempt(user, req.path_params["quiz_id"]))


@router.put("/api/quizzes/<int:quiz_id>/answers", roles=("student",), summary="暂存答案")
def save_answers(req) -> Response:
    user = permissions.require_role(req.user, "student")
    payload = req.json()
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise validators.ValidationError("answers 必须是对象")
    return ok(quiz_service.save_answers(user, req.path_params["quiz_id"], answers))


@router.post("/api/quizzes/<int:quiz_id>/submit", roles=("student",), summary="交卷")
def submit_quiz(req) -> Response:
    user = permissions.require_role(req.user, "student")
    payload = req.json()
    answers = payload.get("answers") or {}
    if not isinstance(answers, dict):
        raise validators.ValidationError("answers 必须是对象")
    result = quiz_service.submit_attempt(user, req.path_params["quiz_id"], answers)
    return ok(result, "交卷成功")


@router.get("/api/quizzes/<int:quiz_id>/standings", roles=("teacher", "admin"),
            summary="测验成绩排行")
def standings(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(quiz_service.standings(user, req.path_params["quiz_id"]))


@router.post("/api/quizzes/<int:quiz_id>/grade", roles=("teacher", "admin"),
             summary="人工复核")
def manual_grade(req) -> Response:
    user = permissions.require_teacher(req.user)
    payload = req.json()
    student_id = validators.required_int(payload, "student_id", min_value=1)
    score = validators.required_int(payload, "score", min_value=0)
    return ok(
        quiz_service.manual_grade(user, req.path_params["quiz_id"], student_id, score)
    )
