"""课表接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.services import timetable_service

router = Router()


@router.get("/api/timetable", summary="课表")
def list_slots(req) -> Response:
    user = permissions.require_login(req.user)
    data = timetable_service.list_slots(
        user,
        class_name=req.str_param("class_name"),
        teacher_name=req.str_param("teacher_name"),
        semester=req.str_param("semester"),
    )
    return ok(data)


@router.get("/api/timetable/classes", summary="有课表的班级")
def list_classes(req) -> Response:
    permissions.require_login(req.user)
    return ok(timetable_service.classes())


@router.post("/api/timetable", roles=("admin",), summary="新增课程时段")
def create_slot(req) -> Response:
    admin = permissions.require_admin(req.user)
    return created(timetable_service.create_slot(admin, req.json()), "已添加")


@router.put("/api/timetable/<int:slot_id>", roles=("admin",), summary="修改课程时段")
def update_slot(req) -> Response:
    admin = permissions.require_admin(req.user)
    return ok(timetable_service.update_slot(admin, req.path_params["slot_id"], req.json()), "已保存")


@router.delete("/api/timetable/<int:slot_id>", roles=("admin",), summary="删除课程时段")
def delete_slot(req) -> Response:
    admin = permissions.require_admin(req.user)
    return ok(timetable_service.delete_slot(admin, req.path_params["slot_id"]), "已删除")
