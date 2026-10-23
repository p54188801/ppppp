"""签到接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.services import attendance_service

router = Router()


@router.get("/api/classes/<int:class_id>/attendance", summary="教学班签到列表")
def list_sessions(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(attendance_service.list_sessions(user, req.path_params["class_id"]))


@router.post("/api/attendance", roles=("teacher", "admin"), summary="发起签到")
def create_session(req) -> Response:
    user = permissions.require_teacher(req.user)
    return created(attendance_service.create_session(req.json(), operator=user), "签到已发起")


@router.get("/api/my/attendance/open", roles=("student",), summary="进行中的签到")
def open_sessions(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(attendance_service.open_sessions_for_student(user))


@router.get("/api/attendance/<int:session_id>", summary="签到详情")
def session_detail(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(attendance_service.session_detail(user, req.path_params["session_id"]))


@router.post("/api/attendance/<int:session_id>/check-in", roles=("student",),
             summary="学生签到")
def check_in(req) -> Response:
    user = permissions.require_role(req.user, "student")
    data = attendance_service.check_in(user, req.path_params["session_id"], req.json())
    return ok(data, "签到成功")


@router.post("/api/attendance/<int:session_id>/mark", roles=("teacher", "admin"),
             summary="教师补签")
def mark(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(
        attendance_service.mark_manually(user, req.path_params["session_id"], req.json())
    )


@router.post("/api/attendance/<int:session_id>/close", roles=("teacher", "admin"),
             summary="结束签到")
def close(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(attendance_service.close_session(user, req.path_params["session_id"]))


@router.get("/api/classes/<int:class_id>/attendance/summary",
            roles=("teacher", "admin"), summary="出勤汇总")
def summary(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(attendance_service.class_attendance_summary(user, req.path_params["class_id"]))


@router.get("/api/system/storage", roles=("admin",), summary="存储占用")
def storage(req) -> Response:
    permissions.require_admin(req.user)
    from backend.services import resource_service

    return ok(resource_service.storage_usage())
