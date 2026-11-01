"""学分 / 德育分接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, ok
from backend.http.router import Router
from backend.services import points_service

router = Router()


@router.get("/api/points/students", roles=("teacher", "admin"), summary="学生分数总览")
def overview(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(points_service.overview(user, req.str_param("q")))


@router.post("/api/points/students/<int:student_id>", roles=("teacher", "admin"),
             summary="加扣分")
def adjust(req) -> Response:
    user = permissions.require_login(req.user)
    data = points_service.adjust(user, req.path_params["student_id"], req.json())
    return ok(data, "已记录并通知学生")


@router.get("/api/my/points", roles=("student",), summary="我的学分与德育分")
def my_points(req) -> Response:
    student = permissions.require_role(req.user, "student")
    return ok(points_service.my_points(student))
