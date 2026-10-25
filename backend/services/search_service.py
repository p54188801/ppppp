"""全局搜索：一个关键词同时搜课程、作业、资料、讨论、公告。

按角色限制可见范围：学生只看已选课程，教师只看自己的课，管理员全站。
SQL 统一用「条件 + 排序 + 限制」三段式拼接，避免把 AND 拼到 ORDER BY 后面。
"""

from __future__ import annotations

from typing import Any

from backend.core import permissions
from backend.db import connection

MAX_PER_TYPE = 10


def _scope_course_ids(viewer: dict[str, Any]) -> list[int] | None:
    """返回可见课程 id；None 表示不限制（管理员）。"""
    role = viewer["role"]
    if role == permissions.ROLE_ADMIN:
        return None
    if role == permissions.ROLE_TEACHER:
        rows = connection.query_all(
            "SELECT id FROM courses WHERE teacher_id = ?", (int(viewer["id"]),)
        )
        return [int(row["id"]) for row in rows]
    rows = connection.query_all(
        """SELECT DISTINCT cl.course_id
             FROM enrollments e JOIN classes cl ON cl.id = e.class_id
            WHERE e.student_id = ? AND e.status = 'active'""",
        (int(viewer["id"]),),
    )
    return [int(row["course_id"]) for row in rows]


def _query(base: str, conditions: list[str], params: list[Any],
           scope_col: str | None, scope: list[int] | None,
           order: str) -> list[dict[str, Any]]:
    """拼出 SELECT：base 已含 FROM/JOIN，conditions 为 WHERE 片段。"""
    conds = list(conditions)
    args = list(params)
    if scope is not None and scope_col:
        if not scope:
            return []
        conds.append(f"{scope_col} IN ({','.join('?' for _ in scope)})")
        args.extend(scope)
    sql = base
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += f" ORDER BY {order} LIMIT ?"
    args.append(MAX_PER_TYPE)
    return connection.query_all(sql, tuple(args))


def global_search(viewer: dict[str, Any], keyword: str) -> dict[str, Any]:
    keyword = (keyword or "").strip()[:64]
    empty = {
        "keyword": keyword,
        "total": 0,
        "courses": [],
        "assignments": [],
        "resources": [],
        "discussions": [],
        "announcements": [],
    }
    if not keyword:
        return empty

    like = f"%{keyword}%"
    scope = _scope_course_ids(viewer)
    if scope is not None and not scope:
        return empty

    courses = _query(
        """SELECT c.id, c.code, c.name, c.term, u.real_name AS teacher_name
             FROM courses c LEFT JOIN users u ON u.id = c.teacher_id""",
        ["(c.name LIKE ? OR c.code LIKE ?)", "c.status = 'active'"],
        [like, like],
        "c.id",
        scope,
        "c.id DESC",
    )

    assignments = _query(
        """SELECT a.id, a.title, a.deadline, a.class_id, cl.name AS class_name,
                  c.name AS course_name
             FROM assignments a
             JOIN classes cl ON cl.id = a.class_id
             JOIN courses c ON c.id = cl.course_id""",
        ["a.title LIKE ?", "a.status <> 'draft'"],
        [like],
        "cl.course_id",
        scope,
        "a.id DESC",
    )

    resources = _query(
        """SELECT r.id, r.title, r.filename, r.course_id, c.name AS course_name
             FROM resources r JOIN courses c ON c.id = r.course_id""",
        ["(r.title LIKE ? OR r.filename LIKE ?)"],
        [like, like],
        "r.course_id",
        scope,
        "r.id DESC",
    )

    discussions = _query(
        """SELECT d.id, d.title, d.course_id, c.name AS course_name,
                  u.real_name AS author_name
             FROM discussions d
             JOIN courses c ON c.id = d.course_id
             LEFT JOIN users u ON u.id = d.author_id""",
        ["d.title LIKE ?"],
        [like],
        "d.course_id",
        scope,
        "d.id DESC",
    )

    announcements = _query(
        """SELECT a.id, a.title, a.course_id, c.name AS course_name, a.created_at
             FROM announcements a JOIN courses c ON c.id = a.course_id""",
        ["a.title LIKE ?"],
        [like],
        "a.course_id",
        scope,
        "a.id DESC",
    )

    return {
        "keyword": keyword,
        "total": len(courses) + len(assignments) + len(resources)
        + len(discussions) + len(announcements),
        "courses": courses,
        "assignments": assignments,
        "resources": resources,
        "discussions": discussions,
        "announcements": announcements,
    }
