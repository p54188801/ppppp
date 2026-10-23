"""教学资料、讨论区、通知的数据访问层。"""

from __future__ import annotations

from typing import Any

from backend.core import clock
from backend.db import connection
from backend.repositories.base import BaseRepository


class ResourceRepository(BaseRepository):
    table = "resources"
    writable = (
        "course_id",
        "title",
        "description",
        "filename",
        "stored_name",
        "size",
        "mime",
        "category",
        "downloads",
        "uploader_id",
    )
    updated_field = ""

    BASE_SELECT = """
        SELECT r.*, u.real_name AS uploader_name
          FROM resources r
          LEFT JOIN users u ON u.id = r.uploader_id
    """

    def list_by_course(self, course_id: int,
                       keyword: str = "") -> list[dict[str, Any]]:
        """某课程下的资料列表，可按标题/文件名/说明模糊筛选。"""
        sql = self.BASE_SELECT + " WHERE r.course_id = ?"
        params: list[Any] = [course_id]
        if keyword:
            sql += " AND (r.title LIKE ? OR r.filename LIKE ? OR r.description LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        sql += " ORDER BY r.created_at DESC, r.id DESC"
        return connection.query_all(sql, tuple(params))

    def detail(self, resource_id: int) -> dict[str, Any] | None:
        """资料详情（含上传者姓名）。"""
        return connection.query_one(
            self.BASE_SELECT + " WHERE r.id = ?", (resource_id,)
        )

    def increment_download(self, resource_id: int) -> None:
        """下载计数加一。"""
        connection.execute(
            "UPDATE resources SET downloads = downloads + 1 WHERE id = ?",
            (resource_id,),
        )


class DiscussionRepository(BaseRepository):
    table = "discussions"
    writable = ("course_id", "title", "content", "author_id", "pinned", "locked")

    BASE_SELECT = """
        SELECT d.*,
               u.real_name AS author_name,
               (SELECT COUNT(*) FROM discussion_replies r
                 WHERE r.discussion_id = d.id) AS reply_count
          FROM discussions d
          JOIN users u ON u.id = d.author_id
    """

    def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
        """课程讨论列表：置顶帖优先，其余按最后更新时间倒序。"""
        return connection.query_all(
            self.BASE_SELECT
            + """ WHERE d.course_id = ?
                  ORDER BY d.pinned DESC, d.updated_at DESC, d.id DESC""",
            (course_id,),
        )

    def detail(self, discussion_id: int) -> dict[str, Any] | None:
        """讨论帖详情（含作者姓名与回复数）。"""
        return connection.query_one(
            self.BASE_SELECT + " WHERE d.id = ?", (discussion_id,)
        )

    def increment_views(self, discussion_id: int) -> None:
        """浏览计数加一。"""
        connection.execute(
            "UPDATE discussions SET views = views + 1 WHERE id = ?",
            (discussion_id,),
        )


class ReplyRepository(BaseRepository):
    table = "discussion_replies"
    writable = ("discussion_id", "author_id", "content", "parent_id")
    updated_field = ""

    def list_by_discussion(self, discussion_id: int) -> list[dict[str, Any]]:
        """按时间正序取出某帖的全部回复，联用户表带作者姓名与角色。"""
        return connection.query_all(
            """SELECT r.*,
                      u.real_name AS author_name,
                      u.role      AS author_role
                 FROM discussion_replies r
                 JOIN users u ON u.id = r.author_id
                WHERE r.discussion_id = ?
                ORDER BY r.created_at ASC, r.id ASC""",
            (discussion_id,),
        )

    def count_by_discussion(self, discussion_id: int) -> int:
        return int(
            connection.scalar(
                "SELECT COUNT(*) FROM discussion_replies WHERE discussion_id = ?",
                (discussion_id,),
                default=0,
            )
            or 0
        )


class NotificationRepository(BaseRepository):
    table = "notifications"
    writable = ("user_id", "title", "content", "category", "link", "is_read")
    updated_field = ""

    def create(self, user_id: int, title: str, content: str = "",
               category: str = "system", link: str = "") -> int:
        """给单个用户发一条通知，返回通知 id。"""
        return self.insert(
            {
                "user_id": user_id,
                "title": title,
                "content": content,
                "category": category,
                "link": link,
                "is_read": 0,
            }
        )

    def create_many(self, user_ids: list[int], title: str, content: str = "",
                    category: str = "system", link: str = "") -> int:
        """批量发送同一内容的通知，返回实际写入条数。"""
        if not user_ids:
            return 0
        now = clock.now_iso()
        rows = [
            (user_id, title, content, category, link, 0, now)
            for user_id in user_ids
        ]
        return connection.execute_many(
            """INSERT INTO notifications
                   (user_id, title, content, category, link, is_read, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def list_for_user(self, user_id: int, only_unread: bool = False,
                      limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """用户的通知列表，默认按时间倒序；可只看未读并分页。"""
        sql = "SELECT * FROM notifications WHERE user_id = ?"
        params: list[Any] = [user_id]
        if only_unread:
            sql += " AND is_read = 0"
        sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return connection.query_all(sql, tuple(params))

    def unread_count(self, user_id: int) -> int:
        return int(
            connection.scalar(
                "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
                (user_id,),
                default=0,
            )
            or 0
        )

    def mark_read(self, notification_id: int, user_id: int) -> int:
        """把某条通知标为已读，返回本次真正更新的行数。"""
        connection.execute(
            """UPDATE notifications SET is_read = 1
                WHERE id = ? AND user_id = ? AND is_read = 0""",
            (notification_id, user_id),
        )
        # connection.execute 返回的是 lastrowid，这里用 changes() 取真实影响行数
        return int(connection.scalar("SELECT changes()", default=0) or 0)

    def mark_all_read(self, user_id: int) -> int:
        """全部标为已读，返回更新条数。"""
        connection.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
            (user_id,),
        )
        return int(connection.scalar("SELECT changes()", default=0) or 0)

    def clear_read(self, user_id: int) -> int:
        """清空该用户所有已读通知，返回删除条数。"""
        connection.execute(
            "DELETE FROM notifications WHERE user_id = ? AND is_read = 1",
            (user_id,),
        )
        return int(connection.scalar("SELECT changes()", default=0) or 0)
