"""数据备份与恢复。

用 SQLite 官方 backup API 在服务运行中做一致性快照；备份放在 data/backups。
恢复是破坏性操作，接口层要求 confirm=true 才执行。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from backend import config
from backend.core import clock
from backend.core.errors import NotFoundError, ValidationError
from backend.db import connection

PREFIX = "eduflow-"


def _dir() -> Path:
    path = Path(config.BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(note: str = "") -> dict[str, Any]:
    stamp = clock.utcnow().strftime("%Y%m%d-%H%M%S")
    safe_note = "".join(ch for ch in note if ch.isalnum() or ch in "-_")[:20]
    name = f"{PREFIX}{stamp}{('-' + safe_note) if safe_note else ''}.db"
    target = _dir() / name

    source = connection.get_connection()
    dest = sqlite3.connect(str(target))
    try:
        source.backup(dest)
    finally:
        dest.close()

    stat = target.stat()
    return {
        "filename": name,
        "size": stat.st_size,
        "size_kb": round(stat.st_size / 1024, 1),
        "created_at": clock.now_iso(),
        "note": note,
    }


def list_backups() -> list[dict[str, Any]]:
    items = []
    for path in sorted(_dir().glob(f"{PREFIX}*.db"), reverse=True):
        stat = path.stat()
        items.append(
            {
                "filename": path.name,
                "size": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 1),
                "created_at": clock.from_timestamp(stat.st_mtime),
            }
        )
    return items


def resolve_backup(filename: str) -> Path:
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise ValidationError("备份文件名不合法")
    if not filename.startswith(PREFIX):
        raise ValidationError("备份文件名不合法")
    path = _dir() / filename
    if not path.is_file():
        raise NotFoundError("备份文件不存在")
    return path


def delete_backup(filename: str) -> None:
    resolve_backup(filename).unlink()


def restore_backup(filename: str) -> dict[str, Any]:
    path = resolve_backup(filename)
    source = sqlite3.connect(str(path))
    target = connection.get_connection()
    try:
        source.backup(target)
    finally:
        source.close()
    target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"restored_from": filename, "at": clock.now_iso()}


def stats() -> dict[str, Any]:
    items = list_backups()
    return {
        "count": len(items),
        "total_kb": round(sum(item["size"] for item in items) / 1024, 1),
        "latest": items[0] if items else None,
        "dir": str(_dir()),
    }
