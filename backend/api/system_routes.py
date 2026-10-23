"""系统级接口：健康检查、元信息、设置、接口清单。"""

from __future__ import annotations

from backend import config
from backend.core import clock, permissions, validators
from backend.http.response import Response, ok
from backend.http.router import Router
from backend.repositories.audit import AuditRepository, SettingRepository

router = Router()
setting_repo = SettingRepository()
audit_repo = AuditRepository()


@router.get("/api/health", auth=False, summary="健康检查")
def health(req) -> Response:
    from backend.db import connection

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
    from backend.app import application  # 延迟导入，避免循环

    return ok(application.describe_routes())


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
    from backend.db import connection

    connection.get_connection().execute("VACUUM")
    return ok({"ok": True, "at": clock.now_iso()}, "数据库已整理")
