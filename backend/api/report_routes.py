"""统计报表接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http.response import Response, ok, paginated
from backend.http.router import Router
from backend.repositories.audit import AuditRepository
from backend.services import statistics_service

router = Router()


@router.get("/api/dashboard", summary="按角色返回首页数据")
def dashboard(req) -> Response:
    user = permissions.require_login(req.user)
    if user["role"] == permissions.ROLE_ADMIN:
        return ok(statistics_service.admin_dashboard())
    if user["role"] == permissions.ROLE_TEACHER:
        return ok(statistics_service.teacher_dashboard(user))
    return ok(statistics_service.student_report(user))


@router.get("/api/reports/course/<int:course_id>", roles=("teacher", "admin"),
            summary="课程活跃度")
def course_report(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(statistics_service.course_overview(user, req.path_params["course_id"]))


@router.get("/api/reports/student", roles=("student",), summary="学习报告")
def student_report(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(statistics_service.student_report(user))


@router.get("/api/audit-logs", roles=("admin",), summary="审计日志")
def audit_logs(req) -> Response:
    permissions.require_admin(req.user)
    repo = AuditRepository()
    page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
    offset = (page - 1) * page_size
    action = req.str_param("action")
    keyword = req.str_param("keyword")
    items = repo.list_logs(action=action, keyword=keyword, limit=page_size, offset=offset)
    total = repo.count_logs(action=action, keyword=keyword)
    return paginated(items, total, page, page_size)

@router.get("/api/my/todos", summary="待办中心")
def my_todos(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(statistics_service.my_todos(user))