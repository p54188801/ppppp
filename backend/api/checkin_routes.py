"""群签到接口。"""

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
