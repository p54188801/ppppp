"""入课审批接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.services import enroll_service

router = Router()


@router.post("/api/enroll/request", roles=("student",), summary="凭邀请码申请入课")
def request_join(req) -> Response:
    student = permissions.require_role(req.user, "student")
    data = req.json()
    return created(enroll_service.request_join(student, data.get("code", "")), "申请已提交，等待老师审批")


@router.get("/api/enroll/requests", roles=("teacher", "admin"), summary="待审批的入课申请")
def list_requests(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(enroll_service.list_requests(user))


@router.post("/api/enroll/requests/<int:enrollment_id>/approve",
             roles=("teacher", "admin"), summary="同意入课")
def approve(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(enroll_service.approve(user, req.path_params["enrollment_id"]), "已同意")


@router.post("/api/enroll/requests/<int:enrollment_id>/reject",
             roles=("teacher", "admin"), summary="拒绝入课")
def reject(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(enroll_service.reject(user, req.path_params["enrollment_id"]), "已拒绝")


@router.get("/api/my/enroll-requests", roles=("student",), summary="我的入课申请")
def my_requests(req) -> Response:
    student = permissions.require_role(req.user, "student")
    return ok(enroll_service.my_requests(student))
