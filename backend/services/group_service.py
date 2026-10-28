"""班级群：同班师生自动成群，群内发消息、发作业、交作业、批改。"""

from __future__ import annotations

import math
import mimetypes
import re
from typing import Any

from backend import config
from backend.core import clock, ids, permissions, validators
from backend.core.errors import ForbiddenError, NotFoundError, ValidationError
from backend.db import connection
from backend.http.static import safe_join
from backend.repositories.audit import AuditRepository
from backend.repositories.users import UserRepository

user_repo = UserRepository()
audit_repo = AuditRepository()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _now() -> str:
    return clock.now_iso()


def _store_file(filename: str, content: bytes, prefix: str = "g") -> dict[str, Any]:
    if not content:
        raise ValidationError("文件内容为空")
    if len(content) > config.MAX_UPLOAD_BYTES:
        raise ValidationError("文件不能超过 64 MB")
    name = "".join(ch for ch in (filename or "file") if ch.isprintable() and ch not in '<>:"|?*')[:120] or "file"
    stored = f"{prefix}_{ids.new_filename_token()}_{name}"
    target = safe_join(config.UPLOAD_DIR, stored)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    mime, _ = mimetypes.guess_type(name)
    return {
        "file_name": name,
        "stored_name": stored,
        "size": len(content),
        "mime": mime or "application/octet-stream",
    }


def _member(group_id: int, user_id: int) -> dict[str, Any] | None:
    return connection.query_one(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    )


def _group_or_fail(group_id: int) -> dict[str, Any]:
    row = connection.query_one("SELECT * FROM class_groups WHERE id = ?", (group_id,))
    if row is None:
        raise NotFoundError("班级群不存在")
    return row


def _assert_member(user: dict[str, Any], group_id: int) -> dict[str, Any]:
    group = _group_or_fail(group_id)
    if user["role"] == permissions.ROLE_ADMIN:
        return group
    if _member(group_id, int(user["id"])) is None:
        raise ForbiddenError("你不在这个班级群里")
    return group


# ---------------------------------------------------------------------------
# 建群 / 入群
# ---------------------------------------------------------------------------


def ensure_group(name: str, teacher_id: int | None = None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValidationError("班级名称不能为空")
    row = connection.query_one("SELECT * FROM class_groups WHERE name = ?", (name,))
    if row:
        if teacher_id and not row.get("teacher_id"):
            connection.execute(
                "UPDATE class_groups SET teacher_id = ? WHERE id = ?", (teacher_id, row["id"])
            )
            row["teacher_id"] = teacher_id
        return row
    gid = connection.execute(
        "INSERT INTO class_groups (name, teacher_id, created_at) VALUES (?, ?, ?)",
        (name, teacher_id, _now()),
    )
    return connection.query_one("SELECT * FROM class_groups WHERE id = ?", (gid,)) or {}


def join_group_by_name(user: dict[str, Any], class_name: str) -> dict[str, Any]:
    """注册时调用：按班级名入群，教师自动成为群主。"""
    teacher_id = int(user["id"]) if user["role"] == permissions.ROLE_TEACHER else None
    group = ensure_group(class_name, teacher_id)
    existing = _member(int(group["id"]), int(user["id"]))
    if existing is None:
        connection.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
            (int(group["id"]), int(user["id"]), user["role"], _now()),
        )
    return group


def groups_for_user(user: dict[str, Any]) -> list[dict[str, Any]]:
    if user["role"] == permissions.ROLE_ADMIN:
        return connection.query_all(
            """SELECT g.*, (SELECT COUNT(*) FROM group_members m WHERE m.group_id = g.id) AS member_count
                 FROM class_groups g ORDER BY g.id DESC"""
        )
    return connection.query_all(
        """SELECT g.*, (SELECT COUNT(*) FROM group_members m2 WHERE m2.group_id = g.id) AS member_count
             FROM class_groups g
             JOIN group_members m ON m.group_id = g.id AND m.user_id = ?
            ORDER BY g.id DESC""",
        (int(user["id"]),),
    )


def group_detail(user: dict[str, Any], group_id: int, limit: int = 100) -> dict[str, Any]:
    group = _assert_member(user, group_id)
    members = connection.query_all(
        """SELECT u.id, u.real_name, u.username, u.role, m.role AS member_role
             FROM group_members m JOIN users u ON u.id = m.user_id
            WHERE m.group_id = ? ORDER BY m.role DESC, u.id""",
        (group_id,),
    )
    messages = connection.query_all(
        """SELECT gm.*, u.real_name AS sender_name, u.role AS sender_role
             FROM group_messages gm JOIN users u ON u.id = gm.sender_id
            WHERE gm.group_id = ? ORDER BY gm.id DESC LIMIT ?""",
        (group_id, limit),
    )
    messages.reverse()
    assignments = list_assignments(group_id, viewer=user)
    group["members"] = members
    group["messages"] = messages
    group["assignments"] = assignments
    group["is_teacher"] = user["role"] in (permissions.ROLE_TEACHER, permissions.ROLE_ADMIN) or int(
        group.get("teacher_id") or 0
    ) == int(user["id"])
    return group


# ---------------------------------------------------------------------------
# 群消息
# ---------------------------------------------------------------------------


def post_message(user: dict[str, Any], group_id: int, *, content: str = "",
                 file: tuple[str, bytes] | None = None) -> dict[str, Any]:
    _assert_member(user, group_id)
    content = (content or "").strip()
    info: dict[str, Any] = {}
    kind = "text"
    if file is not None:
        info = _store_file(file[0], file[1], prefix="gm")
        kind = "image" if (info["mime"] or "").startswith("image/") else "file"
    if not content and not info:
        raise ValidationError("消息内容不能为空")

    mid = connection.execute(
        """INSERT INTO group_messages
               (group_id, sender_id, kind, content, file_name, stored_name, size, mime, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (group_id, int(user["id"]), kind, content, info.get("file_name"),
         info.get("stored_name"), info.get("size", 0), info.get("mime"), _now()),
    )
    return connection.query_one(
        """SELECT gm.*, u.real_name AS sender_name FROM group_messages gm
             JOIN users u ON u.id = gm.sender_id WHERE gm.id = ?""",
        (mid,),
    ) or {}


def message_file(user: dict[str, Any], message_id: int) -> tuple[Any, str]:
    row = connection.query_one("SELECT * FROM group_messages WHERE id = ?", (message_id,))
    if row is None or not row.get("stored_name"):
        raise NotFoundError("附件不存在")
    _assert_member(user, int(row["group_id"]))
    path = safe_join(config.UPLOAD_DIR, row["stored_name"])
    if not path.exists():
        raise NotFoundError("文件已丢失")
    return path, row.get("file_name") or "file"


# ---------------------------------------------------------------------------
# 群作业
# ---------------------------------------------------------------------------


def create_assignment(user: dict[str, Any], group_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    group = _assert_member(user, group_id)
    is_teacher = user["role"] in (permissions.ROLE_TEACHER, permissions.ROLE_ADMIN) or int(
        group.get("teacher_id") or 0
    ) == int(user["id"])
    if not is_teacher:
        raise ForbiddenError("只有老师可以发布作业")

    title = validators.required_str(payload, "title", min_len=1, max_len=120)
    content = validators.optional_str(payload, "content", "", max_len=20000)
    full_score = validators.optional_float(payload, "full_score", 100, min_value=1, max_value=1000)
    deadline = validators.validate_date(payload.get("deadline"), "截止时间", required_field=False) or None

    aid = connection.execute(
        """INSERT INTO group_assignments
               (group_id, title, content, full_score, deadline, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (group_id, title, content, full_score, deadline, int(user["id"]), _now()),
    )
    # 群里发一条作业通知消息
    connection.execute(
        """INSERT INTO group_messages (group_id, sender_id, kind, content, ref_id, created_at)
           VALUES (?, ?, 'assignment', ?, ?, ?)""",
        (group_id, int(user["id"]), title, aid, _now()),
    )
    audit_repo.log(
        user_id=int(user["id"]), username=user["username"], action="group_assignment",
        entity="group_assignment", entity_id=aid, detail=f"{group['name']} / {title}",
    )
    return connection.query_one("SELECT * FROM group_assignments WHERE id = ?", (aid,)) or {}


def list_assignments(group_id: int, *, viewer: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = connection.query_all(
        """SELECT a.*, u.real_name AS teacher_name,
                  (SELECT COUNT(*) FROM group_submissions s WHERE s.assignment_id = a.id) AS submission_count
             FROM group_assignments a LEFT JOIN users u ON u.id = a.created_by
            WHERE a.group_id = ? ORDER BY a.id DESC""",
        (group_id,),
    )
    if viewer and viewer["role"] == permissions.ROLE_STUDENT:
        for row in rows:
            mine = connection.query_one(
                "SELECT * FROM group_submissions WHERE assignment_id = ? AND student_id = ?",
                (int(row["id"]), int(viewer["id"])),
            )
            row["my_submission"] = mine
    return rows


def submit(user: dict[str, Any], assignment_id: int, *, content: str = "",
           file: tuple[str, bytes] | None = None) -> dict[str, Any]:
    row = connection.query_one("SELECT * FROM group_assignments WHERE id = ?", (assignment_id,))
    if row is None:
        raise NotFoundError("作业不存在")
    _assert_member(user, int(row["group_id"]))
    if user["role"] != permissions.ROLE_STUDENT:
        raise ForbiddenError("只有学生需要提交作业")

    info: dict[str, Any] = {}
    if file is not None:
        info = _store_file(file[0], file[1], prefix="gs")
    content = (content or "").strip()
    if not content and not info:
        raise ValidationError("请填写内容或上传文件")

    existing = connection.query_one(
        "SELECT id FROM group_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, int(user["id"])),
    )
    if existing:
        connection.execute(
            """UPDATE group_submissions
                  SET content = ?, file_name = ?, stored_name = ?, size = ?, mime = ?, updated_at = ?
                WHERE id = ?""",
            (content, info.get("file_name"), info.get("stored_name"), info.get("size", 0),
             info.get("mime"), _now(), existing["id"]),
        )
        sid = existing["id"]
    else:
        sid = connection.execute(
            """INSERT INTO group_submissions
                   (assignment_id, student_id, content, file_name, stored_name, size, mime, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (assignment_id, int(user["id"]), content, info.get("file_name"),
             info.get("stored_name"), info.get("size", 0), info.get("mime"), _now(), _now()),
        )
    return connection.query_one("SELECT * FROM group_submissions WHERE id = ?", (sid,)) or {}


def list_submissions(user: dict[str, Any], assignment_id: int) -> list[dict[str, Any]]:
    row = connection.query_one("SELECT * FROM group_assignments WHERE id = ?", (assignment_id,))
    if row is None:
        raise NotFoundError("作业不存在")
    group = _assert_member(user, int(row["group_id"]))
    is_teacher = user["role"] in (permissions.ROLE_TEACHER, permissions.ROLE_ADMIN) or int(
        group.get("teacher_id") or 0
    ) == int(user["id"])
    if not is_teacher:
        raise ForbiddenError("只有老师可以查看全部提交")
    return connection.query_all(
        """SELECT s.*, u.real_name AS student_name, u.username
             FROM group_submissions s JOIN users u ON u.id = s.student_id
            WHERE s.assignment_id = ? ORDER BY s.updated_at DESC""",
        (assignment_id,),
    )


def grade_submission(user: dict[str, Any], submission_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = connection.query_one("SELECT * FROM group_submissions WHERE id = ?", (submission_id,))
    if row is None:
        raise NotFoundError("提交记录不存在")
    ass = connection.query_one("SELECT * FROM group_assignments WHERE id = ?", (int(row["assignment_id"]),))
    group = _assert_member(user, int(ass["group_id"]))
    is_teacher = user["role"] in (permissions.ROLE_TEACHER, permissions.ROLE_ADMIN) or int(
        group.get("teacher_id") or 0
    ) == int(user["id"])
    if not is_teacher:
        raise ForbiddenError("只有老师可以打分")

    full = float(ass.get("full_score") or 100)
    score = validators.validate_score(payload.get("score"), full)
    feedback = validators.optional_str(payload, "feedback", "", max_len=2000)
    connection.execute(
        "UPDATE group_submissions SET score = ?, feedback = ?, graded_by = ?, graded_at = ? WHERE id = ?",
        (score, feedback, int(user["id"]), _now(), submission_id),
    )
    return connection.query_one("SELECT * FROM group_submissions WHERE id = ?", (submission_id,)) or {}


def submission_file(user: dict[str, Any], submission_id: int) -> tuple[Any, str]:
    row = connection.query_one("SELECT * FROM group_submissions WHERE id = ?", (submission_id,))
    if row is None or not row.get("stored_name"):
        raise NotFoundError("附件不存在")
    ass = connection.query_one("SELECT * FROM group_assignments WHERE id = ?", (int(row["assignment_id"]),))
    group = _assert_member(user, int(ass["group_id"]))
    is_teacher = user["role"] in (permissions.ROLE_TEACHER, permissions.ROLE_ADMIN) or int(
        group.get("teacher_id") or 0
    ) == int(user["id"])
    if not is_teacher and int(row["student_id"]) != int(user["id"]):
        raise ForbiddenError("无权下载")
    path = safe_join(config.UPLOAD_DIR, row["stored_name"])
    if not path.exists():
        raise NotFoundError("文件已丢失")
    return path, row.get("file_name") or "file"


# ---------------------------------------------------------------------------
# 课程推荐
# ---------------------------------------------------------------------------


def _keywords(class_name: str) -> list[str]:
    """大数据G231 -> ['大数据']；计算机应用2301 -> ['计算机应用']"""
    raw = (class_name or "").strip()
    if not raw:
        return []
    parts = re.split(r"[0-9A-Za-z\-_]+", raw)
    return [p.strip() for p in parts if len(p.strip()) >= 2]


def refresh_offers(user: dict[str, Any]) -> list[dict[str, Any]]:
    """按班级关键词给该学生生成课程推荐（已接受/拒绝的不再出现）。"""
    if user["role"] != permissions.ROLE_STUDENT:
        return []
    class_name = user.get("class_name") or ""
    kws = _keywords(class_name)
    enrolled = {
        int(r["course_id"])
        for r in connection.query_all(
            """SELECT cl.course_id FROM enrollments e JOIN classes cl ON cl.id = e.class_id
                WHERE e.student_id = ? AND e.status = 'active'""",
            (int(user["id"]),),
        )
    }
    courses = connection.query_all("SELECT * FROM courses WHERE status = 'active'")
    matched = []
    for c in courses:
        if int(c["id"]) in enrolled:
            continue
        hit = any(k in (c["name"] or "") or k in (c["category"] or "") for k in kws) if kws else True
        if hit:
            matched.append(c)
    for c in matched:
        existing = connection.query_one(
            "SELECT * FROM course_offers WHERE user_id = ? AND course_id = ?",
            (int(user["id"]), int(c["id"])),
        )
        if existing is None:
            connection.execute(
                "INSERT INTO course_offers (user_id, course_id, status, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)",
                (int(user["id"]), int(c["id"]), _now(), _now()),
            )
    return connection.query_all(
        """SELECT o.id AS offer_id, o.status, c.id AS course_id, c.code, c.name, c.credits,
                  c.category, u.real_name AS teacher_name
             FROM course_offers o
             JOIN courses c ON c.id = o.course_id
             LEFT JOIN users u ON u.id = c.teacher_id
            WHERE o.user_id = ? AND o.status = 'pending'
            ORDER BY o.id DESC""",
        (int(user["id"]),),
    )


def respond_offer(user: dict[str, Any], offer_id: int, accept: bool) -> dict[str, Any]:
    row = connection.query_one(
        "SELECT * FROM course_offers WHERE id = ? AND user_id = ?", (offer_id, int(user["id"]))
    )
    if row is None:
        raise NotFoundError("推荐不存在")
    status = "accepted" if accept else "rejected"
    connection.execute(
        "UPDATE course_offers SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), offer_id)
    )
    joined = None
    if accept:
        target = connection.query_one(
            "SELECT * FROM classes WHERE course_id = ? ORDER BY id LIMIT 1", (int(row["course_id"]),)
        )
        if target:
            exists = connection.query_one(
                "SELECT id FROM enrollments WHERE class_id = ? AND student_id = ?",
                (int(target["id"]), int(user["id"])),
            )
            if exists:
                connection.execute(
                    "UPDATE enrollments SET status = 'active' WHERE id = ?", (exists["id"],)
                )
            else:
                connection.execute(
                    """INSERT INTO enrollments (class_id, student_id, status, source, created_at)
                       VALUES (?, ?, 'active', 'offer', ?)""",
                    (int(target["id"]), int(user["id"]), _now()),
                )
            joined = {"class_id": int(target["id"]), "class_name": target["name"]}
    return {"offer_id": offer_id, "status": status, "joined_class": joined}
