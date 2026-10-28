"""班级群与课程推荐接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http import multipart
from backend.http.response import Response, created, file_response, ok
from backend.http.router import Router
from backend.services import group_service

router = Router()


def _read_payload(req) -> tuple[dict, tuple[str, bytes] | None]:
    """同时支持 JSON 和 multipart（带一个文件）。"""
    ctype = req.header("content-type")
    if multipart.is_multipart(ctype):
        form = multipart.parse_multipart(req.body, ctype)
        file = None
        first = form.first_file()
        if first is not None:
            file = (first.filename, first.data)
        return form.fields, file
    return req.json(), None


# ---------------------------------------------------------------- 群


@router.get("/api/groups", summary="我的班级群")
def list_groups(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(group_service.groups_for_user(user))


@router.get("/api/groups/<int:group_id>", summary="班级群详情")
def group_detail(req) -> Response:
    user = permissions.require_login(req.user)
    limit = req.int_param("limit", 100) or 100
    return ok(group_service.group_detail(user, req.path_params["group_id"], limit=min(limit, 500)))


@router.post("/api/groups/<int:group_id>/messages", summary="发群消息")
def post_message(req) -> Response:
    user = permissions.require_login(req.user)
    payload, file = _read_payload(req)
    data = group_service.post_message(
        user, req.path_params["group_id"], content=payload.get("content", ""), file=file
    )
    return created(data, "已发送")


@router.get("/api/messages/<int:message_id>/file", summary="下载群文件")
def message_file(req) -> Response:
    user = permissions.require_login(req.user)
    path, name = group_service.message_file(user, req.path_params["message_id"])
    return file_response(path, download_name=name)


# ---------------------------------------------------------------- 群作业


@router.get("/api/groups/<int:group_id>/assignments", summary="群作业列表")
def list_group_assignments(req) -> Response:
    user = permissions.require_login(req.user)
    group_service._assert_member(user, req.path_params["group_id"])  # noqa: SLF001
    return ok(group_service.list_assignments(req.path_params["group_id"], viewer=user))


@router.post("/api/groups/<int:group_id>/assignments", summary="群内发布作业")
def create_group_assignment(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = group_service.create_assignment(
        user, req.path_params["group_id"], req.json()
    )
    return created(data, "作业已发布")


@router.post("/api/group-assignments/<int:assignment_id>/submit", summary="提交群作业")
def submit_group_assignment(req) -> Response:
    user = permissions.require_login(req.user)
    payload, file = _read_payload(req)
    data = group_service.submit(
        user, req.path_params["assignment_id"], content=payload.get("content", ""), file=file
    )
    return ok(data, "提交成功")


@router.get("/api/group-assignments/<int:assignment_id>/submissions",
            roles=("teacher", "admin"), summary="群作业提交列表")
def list_group_submissions(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(group_service.list_submissions(user, req.path_params["assignment_id"]))


@router.post("/api/group-submissions/<int:submission_id>/grade",
             roles=("teacher", "admin"), summary="群作业打分")
def grade_group_submission(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = group_service.grade_submission(
        user, req.path_params["submission_id"], req.json()
    )
    return ok(data, "已打分")


@router.get("/api/group-submissions/<int:submission_id>/file", summary="下载作业附件")
def submission_file(req) -> Response:
    user = permissions.require_login(req.user)
    path, name = group_service.submission_file(user, req.path_params["submission_id"])
    return file_response(path, download_name=name)


# ---------------------------------------------------------------- 课程推荐


@router.get("/api/my/course-offers", roles=("student",), summary="我的课程推荐")
def my_offers(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(group_service.refresh_offers(user))


@router.post("/api/course-offers/<int:offer_id>/accept", roles=("student",),
             summary="接受课程推荐")
def accept_offer(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(group_service.respond_offer(user, req.path_params["offer_id"], True), "已加入课程")


@router.post("/api/course-offers/<int:offer_id>/reject", roles=("student",),
             summary="拒绝课程推荐")
def reject_offer(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(group_service.respond_offer(user, req.path_params["offer_id"], False), "已拒绝")
