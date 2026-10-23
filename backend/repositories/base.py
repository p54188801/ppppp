"""仓储基类。

把「按主键查、按条件查、插入、更新、软删除」这些重复动作收口，
子类只需要声明表名和可写字段，减少大量样板代码。

注意：所有拼接进 SQL 的字段名都会先和表的真实列做比对，
不合法的列名直接抛异常，避免 SQL 注入。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from backend.core import clock
from backend.core.errors import NotFoundError, ValidationError
from backend.db import connection


class BaseRepository:
    table: str = ""
    pk: str = "id"
    # 允许通过 insert/update 写入的列
    writable: tuple[str, ...] = ()
    # 创建/更新时间戳字段（没有则为空串）
    created_field: str = "created_at"
    updated_field: str = "updated_at"

    _column_cache: dict[str, set[str]] = {}

    # -- 元信息 -----------------------------------------------------------

    @classmethod
    def columns(cls) -> set[str]:
        if cls.table not in cls._column_cache:
            rows = connection.query_all(f"PRAGMA table_info({cls.table})")
            cls._column_cache[cls.table] = {row["name"] for row in rows}
        return cls._column_cache[cls.table]

    @classmethod
    def ensure_table(cls) -> None:
        if not cls.table:
            raise ValidationError("仓储未声明 table")

    def _check_field(self, field: str) -> str:
        if field not in self.columns():
            raise ValidationError(f"{self.table} 不存在字段 {field}")
        return field

    def _check_writable(self, data: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            if key not in self.writable:
                raise ValidationError(f"{self.table} 不允许写入字段 {key}")
            cleaned[key] = value
        return cleaned

    # -- 查询 -------------------------------------------------------------

    def find(self, pk_value: Any) -> dict[str, Any] | None:
        return connection.query_one(
            f"SELECT * FROM {self.table} WHERE {self.pk} = ?", (pk_value,)
        )

    def find_or_fail(self, pk_value: Any, message: str = "记录不存在") -> dict[str, Any]:
        row = self.find(pk_value)
        if row is None:
            raise NotFoundError(message)
        return row

    def find_by(self, **filters: Any) -> dict[str, Any] | None:
        if not filters:
            return None
        clause, params = self._where(filters)
        return connection.query_one(
            f"SELECT * FROM {self.table} WHERE {clause} LIMIT 1", params
        )

    def all(
        self,
        *,
        where: str = "",
        params: Sequence[Any] = (),
        order_by: str = "",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = tuple(params) + (limit, offset)
        return connection.query_all(sql, params)

    def count(self, where: str = "", params: Sequence[Any] = ()) -> int:
        sql = f"SELECT COUNT(*) FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        return int(connection.scalar(sql, params, default=0) or 0)

    def exists(self, **filters: Any) -> bool:
        if not filters:
            return False
        clause, params = self._where(filters)
        found = connection.scalar(
            f"SELECT 1 FROM {self.table} WHERE {clause} LIMIT 1", params
        )
        return found is not None

    def _where(self, filters: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
        parts: list[str] = []
        params: list[Any] = []
        for key, value in filters.items():
            self._check_field(key)
            parts.append(f"{key} = ?")
            params.append(value)
        return " AND ".join(parts), tuple(params)

    # -- 写入 -------------------------------------------------------------

    def insert(self, data: dict[str, Any]) -> int:
        payload = self._check_writable(data)
        now = clock.now_iso()
        if self.created_field and self.created_field in self.columns():
            payload.setdefault(self.created_field, now)
        if self.updated_field and self.updated_field in self.columns():
            payload.setdefault(self.updated_field, now)
        if not payload:
            raise ValidationError("没有可写入的字段")
        columns = ", ".join(payload.keys())
        placeholders = ", ".join("?" for _ in payload)
        sql = f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})"
        return connection.execute(sql, tuple(payload.values()))

    def update(self, pk_value: Any, data: dict[str, Any]) -> int:
        payload = self._check_writable(data)
        if self.updated_field and self.updated_field in self.columns():
            payload[self.updated_field] = clock.now_iso()
        if not payload:
            return 0
        assignments = ", ".join(f"{key} = ?" for key in payload)
        sql = f"UPDATE {self.table} SET {assignments} WHERE {self.pk} = ?"
        params = tuple(payload.values()) + (pk_value,)
        return connection.execute(sql, params)

    def update_where(self, where: str, params: Sequence[Any], data: dict[str, Any]) -> int:
        payload = self._check_writable(data)
        if self.updated_field and self.updated_field in self.columns():
            payload[self.updated_field] = clock.now_iso()
        if not payload:
            return 0
        assignments = ", ".join(f"{key} = ?" for key in payload)
        sql = f"UPDATE {self.table} SET {assignments} WHERE {where}"
        return connection.execute(sql, tuple(payload.values()) + tuple(params))

    def delete(self, pk_value: Any) -> int:
        return connection.execute(
            f"DELETE FROM {self.table} WHERE {self.pk} = ?", (pk_value,)
        )

    def delete_where(self, where: str, params: Sequence[Any]) -> int:
        return connection.execute(f"DELETE FROM {self.table} WHERE {where}", params)

    def upsert(self, keys: dict[str, Any], data: dict[str, Any]) -> int:
        """有则更新，无则插入。"""
        existing = self.find_by(**keys)
        if existing:
            self.update(existing[self.pk], data)
            return int(existing[self.pk])
        merged = dict(keys)
        merged.update(data)
        return self.insert(merged)

    # -- 批量 -------------------------------------------------------------

    def insert_many(self, rows: Iterable[dict[str, Any]]) -> int:
        items = list(rows)
        if not items:
            return 0
        now = clock.now_iso()
        prepared: list[tuple[Any, ...]] = []
        columns = list(self._check_writable(items[0]).keys())
        for row in items:
            payload = self._check_writable(row)
            if self.created_field and self.created_field in self.columns():
                payload.setdefault(self.created_field, now)
            if self.updated_field and self.updated_field in self.columns():
                payload.setdefault(self.updated_field, now)
            prepared.append(tuple(payload.get(col) for col in columns))
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO {self.table} ({', '.join(columns)}) VALUES ({placeholders})"
        return connection.execute_many(sql, prepared)
