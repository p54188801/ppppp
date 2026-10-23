"""课程资料服务：上传、下载、删除、统计。"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from backend import config
from backend.core import clock, ids, permissions, validators
from backend.core.errors import ForbiddenError, NotFoundError, TooLargeError
from backend.http.static import safe_join
from backend.repositories.audit import AuditRepository
from backend.repositories.content import ResourceRepository
from backend.repositories.courses import ClassRepository, CourseRepository, EnrollmentRepository

logger = logging.getLogger("eduflow.resource")

resource_repo = ResourceRepository()
course_repo = CourseRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
audit_repo = AuditRepository()

ALLOWED_CATEGORIES = ("课件", "课件视频", "参考资料", "作业模板", "其他")


def _course_or_fail(course_id: int) -> dict[str, Any]:
    detail = course_repo.detail(course_id)
    if detail is None:
        raise NotFoundError("课程不存在")
    return detail


def _assert_view(viewer: dict[str, Any], course: dict[str, Any]) -> None:
    class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
    enrolled = bool(class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"]))))
    permissions.assert_can_view_course(viewer, course, enrolled=enrolled)


def save_upload(filename: str, content: bytes, *,
                course_id: int, operator: dict[str, Any],
                title: str = "", description: str = "",
                category: str = "课件") -> dict[str, Any]:
    """落盘 + 入库。文件名会做安全处理并加随机前缀。"""
    course = _course_or_fail(course_id)
    permissions.assert_can_manage_course(operator, course)

    if len(content) > config.MAX_UPLOAD_BYTES:
        raise TooLargeError("文件超过 64 MB 限制")
    if not content:
        raise validators.ValidationError("文件内容为空")

    safe_name = _sanitize_filename(filename)
    stored = f"{ids.new_filename_token()}_{safe_name}"
    target = safe_join(config.UPLOAD_DIR, stored)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    mime, _ = mimetypes.guess_type(safe_name)
    resource_id = resource_repo.insert(
        {
            "course_id": course_id,
            "title": title or Path(safe_name).stem,
            "description": description,
            "filename": safe_name,
            "stored_name": stored,
            "size": len(content),
            "mime": mime or "application/octet-stream",
            "category": category if category in ALLOWED_CATEGORIES else "其他",
            "uploader_id": int(operator["id"]),
        }
    )
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="upload_resource",
        entity="resource",
        entity_id=resource_id,
        detail=f"{course['name']} / {safe_name} / {len(content)} bytes",
    )
    return resource_repo.detail(resource_id) or {}


def _sanitize_filename(filename: str) -> str:
    name = os.path.basename((filename or "unnamed").replace("\\", "/"))
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    name = name.strip(". ")
    if not name:
        name = "unnamed"
    if len(name) > 120:
        stem, ext = os.path.splitext(name)
        name = stem[:100] + ext[:20]
    return name


def list_resources(viewer: dict[str, Any], course_id: int,
                   keyword: str = "") -> list[dict[str, Any]]:
    course = _course_or_fail(course_id)
    _assert_view(viewer, course)
    return resource_repo.list_by_course(course_id, keyword=keyword)


def get_download(viewer: dict[str, Any], resource_id: int) -> tuple[Path, str]:
    resource = resource_repo.find_or_fail(resource_id, "资料不存在")
    course = _course_or_fail(int(resource["course_id"]))
    _assert_view(viewer, course)
    path = safe_join(config.UPLOAD_DIR, resource["stored_name"])
    if not path.exists():
        raise NotFoundError("文件已丢失，请联系管理员")
    resource_repo.increment_download(resource_id)
    return path, resource["filename"]


def delete_resource(operator: dict[str, Any], resource_id: int) -> None:
    resource = resource_repo.find_or_fail(resource_id, "资料不存在")
    course = _course_or_fail(int(resource["course_id"]))
    permissions.assert_can_manage_course(operator, course)
    path = safe_join(config.UPLOAD_DIR, resource["stored_name"])
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:  # noqa: BLE001
            logger.warning("删除文件失败: %s", exc)
    resource_repo.delete(resource_id)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="delete_resource",
        entity="resource",
        entity_id=resource_id,
        detail=resource["filename"],
    )


def storage_usage() -> dict[str, Any]:
    total = 0
    count = 0
    if config.UPLOAD_DIR.exists():
        for path in config.UPLOAD_DIR.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
                count += 1
    return {
        "files": count,
        "bytes": total,
        "megabytes": round(total / 1024 / 1024, 2),
        "limit_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
        "checked_at": clock.now_iso(),
    }


def ensure_upload_dir() -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
