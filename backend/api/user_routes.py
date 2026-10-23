"""用户管理接口（管理员为主）。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http.response import Response, created, ok, paginated
from backend.http.router import Router
from backend.repositories.courses import CourseRepository
from backend.services import user_service

router = Router()


@router.get("/api/users", roles=("admin",), summary="用户列表")
def list_users(req) -> Response:
    permissions.require_admin(req.user)
    role = req.str_param("role")
    keyword = req.str_param("keyword")
    page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
    items, total = user_service.list_users(
        role=role, keyword=keyword, page=page, page_size=page_size
    )
    return paginated(items, total, page, page_size)


@router.post("/api/users", roles=("admin",), summary="新建用户")
def create_user(req) -> Response:
    user = permissions.require_admin(req.user)
    data = user_service.create_user(req.json(), operator=user)
    return created(data, "用户创建成功")


@router.get("/api/users/options", summary="教师与院系选项")
def options(req) -> Response:
    permissions.require_login(req.user)
    teachers = CourseRepository().teacher_names()
    return ok(
        {
            "teachers": [
                {"id": int(row["id"]), "name": row["real_name"]} for row in teachers
            ],
            "departments": user_service.department_options(),
            "roles": [
                {"value": key, "label": label}
                for key, label in permissions.ROLE_LABELS.items()
            ],
        }
    )


@router.get("/api/users/<int:user_id>", roles=("admin",), summary="用户详情")
def get_user(req) -> Response:
    permissions.require_admin(req.user)
    return ok(user_service.get_user(req.path_params["user_id"]))


@router.put("/api/users/<int:user_id>", roles=("admin",), summary="更新用户")
def update_user(req) -> Response:
    admin = permissions.require_admin(req.user)
    data = user_service.update_user(
        req.path_params["user_id"], req.json(), operator=admin
    )
    return ok(data, "已更新")


@router.post("/api/users/<int:user_id>/status", roles=("admin",), summary="启用/禁用账号")
def set_status(req) -> Response:
    admin = permissions.require_admin(req.user)
    payload = req.json()
    status = validators.required_str(payload, "status", max_len=16)
    data = user_service.set_status(req.path_params["user_id"], status, operator=admin)
    return ok(data, "状态已更新")


@router.post("/api/users/<int:user_id>/reset-password", roles=("admin",),
             summary="重置密码")
def reset_password(req) -> Response:
    admin = permissions.require_admin(req.user)
    data = user_service.reset_password(req.path_params["user_id"], operator=admin)
    return ok(data, "新密码已生成，请转告用户")


@router.post("/api/users/import", roles=("admin",), summary="批量导入用户")
def import_users(req) -> Response:
    admin = permissions.require_admin(req.user)
    payload = req.json()
    csv_text = validators.required_str(payload, "csv", min_len=1, max_len=2_000_000, strip=False)
    default_role = validators.optional_str(payload, "default_role", "student", max_len=16)
    result = user_service.import_users(csv_text, default_role=default_role, operator=admin)
    return ok(result, f"导入完成：成功 {result['created']} 条，失败 {result['failed']} 条")
