"""审计日志与系统设置的数据访问层。"""

from __future__ import annotations

from typing import Any

from backend.db import connection
from backend.repositories.base import BaseRepository


class AuditRepository(BaseRepository):
    table = "audit_logs"
    writable = ("user_id", "username", "action", "entity", "entity_id", "detail", "ip")
    created_field = "created_at"
    updated_field = ""

    def log(self, *, user_id: int | None, username: str, action: str,
            entity: str = "", entity_id: int | None = None,
            detail: str = "", ip: str = "") -> int:
        """记录一条操作日志，返回日志 id。"""
        return self.insert(
            {
                "user_id": user_id,
                "username": username,
                "action": action,
                "entity": entity,
                "entity_id": entity_id,
                "detail": detail,
                "ip": ip,
            }
        )

    def list_logs(self, *, action: str = "", keyword: str = "",
                  limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """按动作类型/关键字筛选日志，最新的排前面。"""
        sql = "SELECT * FROM audit_logs WHERE 1 = 1"
        params: list[Any] = []
        if action:
            sql += " AND action = ?"
            params.append(action)
        if keyword:
            sql += " AND (username LIKE ? OR entity LIKE ? OR detail LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return connection.query_all(sql, tuple(params))

    def count_logs(self, *, action: str = "", keyword: str = "") -> int:
        """与 list_logs 同条件的总数，用于分页。"""
        sql = "SELECT COUNT(*) FROM audit_logs WHERE 1 = 1"
        params: list[Any] = []
        if action:
            sql += " AND action = ?"
            params.append(action)
        if keyword:
            sql += " AND (username LIKE ? OR entity LIKE ? OR detail LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        return int(connection.scalar(sql, tuple(params), default=0) or 0)


class SettingRepository(BaseRepository):
    table = "system_settings"
    pk = "key"
    writable = ("key", "value")
    created_field = ""
    updated_field = "updated_at"

    def get(self, key: str, default: str = "") -> str:
        """读一个配置项，不存在时返回 default。"""
        value = connection.scalar(
            "SELECT value FROM system_settings WHERE key = ?", (key,)
        )
        return str(value) if value is not None else default

    def set(self, key: str, value: str) -> None:
        """写配置项（存在则更新，不存在则插入）。"""
        existing = self.find_by(key=key)
        if existing:
            self.update(key, {"value": value})
            return
        self.insert({"key": key, "value": value})

    def all(self) -> dict[str, str]:
        """一次性读出全部配置，便于启动时做内存缓存。"""
        rows = connection.query_all(
            "SELECT key, value FROM system_settings ORDER BY key"
        )
        return {str(row["key"]): str(row["value"]) for row in rows}
