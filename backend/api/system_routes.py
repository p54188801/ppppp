"""系统级接口：健康检查、元信息、设置、接口清单。"""

from __future__ import annotations

from backend import config
from backend.core import clock, errors, permissions, validators
from backend.http.response import Response, file_response, ok
from backend.services import backup_service, search_service
from backend.http.router import Router
from backend.repositories.audit import AuditRepository, SettingRepository

from backend.db import connection

_app_ref = None


def bind_application(app) -> None:
    """由 app.py 在装配完成后注入，供 /api/routes 使用。"""
    global _app_ref
    _app_ref = app


router = Router()
setting_repo = SettingRepository()
audit_repo = AuditRepository()


@router.get("/api/health", auth=False, summary="健康检查")
def health(req) -> Response:

    db_ok = True
    try:
        connection.scalar("SELECT 1")
    except Exception:  # noqa: BLE001
        db_ok = False
    return ok(
        {
            "status": "ok" if db_ok else "degraded",
            "database": db_ok,
            "time": clock.now_iso(),
            "version": config.APP_VERSION,
        }
    )


@router.get("/api/meta", auth=False, summary="应用元信息")
def meta(req) -> Response:
    return ok(
        {
            "name": config.APP_NAME,
            "short_name": config.APP_SHORT_NAME,
            "version": config.APP_VERSION,
            "description": config.APP_DESCRIPTION,
            "term": setting_repo.get("term", clock.term_of()),
            "school_name": setting_repo.get("school_name", "EduFlow 大学"),
            "server_time": clock.now_iso(),
        }
    )


@router.get("/api/routes", summary="接口清单（开发用）")
def routes(req) -> Response:

    if _app_ref is None:
        return ok({"total": 0, "routes": []})
    return ok(_app_ref.describe_routes())


@router.get("/api/settings", roles=("admin",), summary="系统设置")
def get_settings(req) -> Response:
    permissions.require_admin(req.user)
    return ok(setting_repo.all())


@router.put("/api/settings", roles=("admin",), summary="更新系统设置")
def update_settings(req) -> Response:
    admin = permissions.require_admin(req.user)
    payload = req.json()
    updated: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or len(key) > 64:
            continue
        setting_repo.set(key, str(value)[:2000])
        updated[key] = str(value)
    audit_repo.log(
        user_id=int(admin["id"]),
        username=admin["username"],
        action="update_settings",
        entity="settings",
        detail=f"更新 {', '.join(updated)}",
    )
    return ok(setting_repo.all(), "设置已保存")


@router.get("/api/audit/actions", roles=("admin",), summary="审计动作枚举")
def audit_actions(req) -> Response:
    permissions.require_admin(req.user)
    rows = audit_repo.list_logs(limit=500)
    actions = sorted({row["action"] for row in rows})
    return ok(actions)


@router.post("/api/system/vacuum", roles=("admin",), summary="整理数据库")
def vacuum(req) -> Response:
    permissions.require_admin(req.user)

    connection.get_connection().execute("VACUUM")
    return ok({"ok": True, "at": clock.now_iso()}, "数据库已整理")


@router.get("/api/search", summary="全局搜索")
def search(req) -> Response:

    user = permissions.require_login(req.user)
    keyword = req.str_param("q") or req.str_param("keyword")
    return ok(search_service.global_search(user, keyword))


@router.post("/api/system/backup", roles=("admin",), summary="创建数据备份")
def create_backup(req) -> Response:
    admin = permissions.require_admin(req.user)

    payload = req.json()
    note = validators.optional_str(payload, "note", "", max_len=40)
    info = backup_service.create_backup(note)
    audit_repo.log(
        user_id=int(admin["id"]),
        username=admin["username"],
        action="create_backup",
        entity="backup",
        detail=info["filename"],
    )
    return ok(info, "备份已创建")


@router.get("/api/system/backups", roles=("admin",), summary="备份列表")
def list_backups(req) -> Response:
    permissions.require_admin(req.user)

    return ok({"items": backup_service.list_backups(), "stats": backup_service.stats()})


@router.get("/api/system/backups/<str:filename>/download", roles=("admin",),
            summary="下载备份")
def download_backup(req) -> Response:
    permissions.require_admin(req.user)

    path = backup_service.resolve_backup(req.path_params["filename"])
    return file_response(path, download_name=path.name)


@router.delete("/api/system/backups/<str:filename>", roles=("admin",),
               summary="删除备份")
def delete_backup(req) -> Response:
    permissions.require_admin(req.user)

    backup_service.delete_backup(req.path_params["filename"])
    return ok(None, "备份已删除")


@router.post("/api/system/backups/<str:filename>/restore", roles=("admin",),
             summary="用备份恢复数据")
def restore_backup(req) -> Response:
    admin = permissions.require_admin(req.user)

    payload = req.json()
    if not validators.to_bool(payload.get("confirm"), False):
        raise errors.ValidationError("恢复数据需要传 confirm=true 明确确认")
    result = backup_service.restore_backup(req.path_params["filename"])
    audit_repo.log(
        user_id=int(admin["id"]),
        username=admin["username"],
        action="restore_backup",
        entity="backup",
        detail=req.path_params["filename"],
    )
    return ok(result, "数据已恢复，建议重新登录")

