"""通知服务。

系统内所有"需要告诉某人"的动作都走这里：
作业发布、成绩批改、签到开始、课程公告……
统一落库，前端轮询未读数即可。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from backend.core import permissions
from backend.repositories.content import NotificationRepository
from backend.repositories.users import UserRepository

logger = logging.getLogger("eduflow.notify")

notification_repo = NotificationRepository()
user_repo = UserRepository()

MAX_TITLE = 120
MAX_CONTENT = 2000


def notify(
    user_id: int,
    title: str,
    content: str = "",
    *,
    category: str = "system",
    link: str = "",
) -> int:
    """给单个用户发通知。"""
    return notification_repo.create(
        int(user_id),
        title=title[:MAX_TITLE],
        content=content[:MAX_CONTENT],
        category=category,
        link=link,
    )


def notify_many(
    user_ids: Iterable[int],
    title: str,
    content: str = "",
    *,
    category: str = "system",
    link: str = "",
) -> int:
    ids = [int(uid) for uid in dict.fromkeys(user_ids) if uid]
    if not ids:
        return 0
    return notification_repo.create_many(
        ids,
        title=title[:MAX_TITLE],
        content=content[:MAX_CONTENT],
        category=category,
        link=link,
    )


def notify_class(
    user_ids: Iterable[int],
    *,
    title: str,
    content: str = "",
    category: str = "course",
    link: str = "",
) -> int:
    """作业/签到这类课堂通知的语义化包装。"""
    return notify_many(user_ids, title, content, category=category, link=link)


def list_notifications(
    viewer: dict[str, Any],
    *,
    only_unread: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    offset = (max(1, page) - 1) * page_size
    items = notification_repo.list_for_user(
        int(viewer["id"]), only_unread=only_unread, limit=page_size, offset=offset
    )
    total = notification_repo.unread_count(int(viewer["id"])) if only_unread else len(items)
    return items, total


def unread_count(viewer: dict[str, Any]) -> int:
    return notification_repo.unread_count(int(viewer["id"]))


def mark_read(viewer: dict[str, Any], notification_id: int) -> int:
    return notification_repo.mark_read(notification_id, int(viewer["id"]))


def mark_all_read(viewer: dict[str, Any]) -> int:
    return notification_repo.mark_all_read(int(viewer["id"]))


def clear_read(viewer: dict[str, Any]) -> int:
    return notification_repo.clear_read(int(viewer["id"]))


def broadcast(operator: dict[str, Any], payload: dict[str, Any]) -> int:
    """管理员广播通知。

    target: all / student / teacher / class:<class_id>
    """
    permissions.require_admin(operator)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("标题不能为空")
    content = str(payload.get("content") or "")
    target = str(payload.get("target") or "all")

    if target in permissions.ALL_ROLES:
        users = user_repo.all(where="role = ? AND status = 'active'", params=(target,))
        return notify_many(
            [int(item["id"]) for item in users], title, content, category="system"
        )
    if target == "all":
        users = user_repo.all(where="status = 'active'", params=())
        return notify_many(
            [int(item["id"]) for item in users], title, content, category="system"
        )
    raise ValueError(f"不支持的广播目标：{target}")
