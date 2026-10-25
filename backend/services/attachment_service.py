"""作业附件：学生上传、按权限下载。

文件落在 data/uploads，文件名加随机前缀防冲突；数据库只存元信息。
下载权限：上传者本人 / 该教学班任课教师 / 管理员。
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

from backend import config
from backend.core import clock, ids, permissions, validators
from backend.core.errors import ForbiddenError, NotFoundError, TooLargeError
from backend.db import connection
from backend.http.static import safe_join
from backend.repositories.audit import AuditRepository
from backend.repositories.courses import ClassRepository, EnrollmentRepository

audit_repo = AuditRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()

MAX_FILES = 5


def _sanitize(filename: str) -> str:
    name = os.path.basename((filename or "file").replace("\\", "/"))
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip(". ")
    return (name or "file")[:120]


def list_for(assignment_id: int, student_id: int) -> list[dict[str, Any]]:
    return connection.query_all(
        """SELECT id, filename, stored_name, size, mime, created_at
             FROM assignment_files
            WHERE assignment_id = ? AND student_id = ?
            ORDER BY id""",
        (assignment_id, student_id),
    )


def save_uploads(assignment_id: int, student_id: int,
                 files: list[tuple[str, bytes]]) -> list[dict[str, Any]]:
    if len(files) > MAX_FILES:
        raise TooLargeError(f"一次最多上传 {MAX_FILES} 个附件")

    existing = len(list_for(assignment_id, student_id))
    if existing + len(files) > MAX_FILES:
        raise TooLargeError(f"该作业附件总数不能超过 {MAX_FILES} 个")

    saved: list[dict[str, Any]] = []
    for raw_name, content in files:
        if len(content) > config.MAX_UPLOAD_BYTES:
            raise TooLargeError("单个附件不能超过 64 MB")
        if not content:
            raise validators.ValidationError("附件内容为空")

        name = _sanitize(raw_name)
        stored = f"hw_{ids.new_filename_token()}_{name}"
        target = safe_join(config.UPLOAD_DIR, stored)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

        mime, _ = mimetypes.guess_type(name)
        file_id = connection.execute(
            """INSERT INTO assignment_files
                   (assignment_id, student_id, filename, stored_name, size, mime, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (assignment_id, student_id, name, stored, len(content),
             mime or "application/octet-stream", clock.now_iso()),
        )
        saved.append(
            {"id": file_id, "filename": name, "stored_name": stored,
             "size": len(content), "mime": mime or "application/octet-stream"}
        )

    audit_repo.log(
        user_id=student_id,
        username="",
        action="upload_assignment_attachment",
        entity="assignment",
        entity_id=assignment_id,
        detail=f"上传 {len(saved)} 个附件",
    )
    return saved


def resolve_download(viewer: dict[str, Any], file_id: int) -> tuple[Path, str]:
    row = connection.query_one(
        """SELECT f.*, a.class_id, c.teacher_id
             FROM assignment_files f
             JOIN assignments a ON a.id = f.assignment_id
             JOIN classes cl ON cl.id = a.class_id
             JOIN courses c ON c.id = cl.course_id
            WHERE f.id = ?""",
        (file_id,),
    )
    if row is None:
        raise NotFoundError("附件不存在")

    allowed = (
        int(row["student_id"]) == int(viewer["id"])
        or int(row["teacher_id"]) == int(viewer["id"])
        or viewer["role"] == permissions.ROLE_ADMIN
    )
    if not allowed:
        raise ForbiddenError("无权下载该附件")

    path = safe_join(config.UPLOAD_DIR, row["stored_name"])
    if not path.exists():
        raise NotFoundError("文件已丢失")
    return path, row["filename"]


def delete_file(viewer: dict[str, Any], file_id: int) -> None:
    row = connection.query_one(
        "SELECT * FROM assignment_files WHERE id = ?", (file_id,)
    )
    if row is None:
        raise NotFoundError("附件不存在")
    if int(row["student_id"]) != int(viewer["id"]) and viewer["role"] != permissions.ROLE_ADMIN:
        raise ForbiddenError("只能删除自己的附件")

    path = safe_join(config.UPLOAD_DIR, row["stored_name"])
    if path.exists():
        path.unlink()
    connection.execute("DELETE FROM assignment_files WHERE id = ?", (file_id,))
