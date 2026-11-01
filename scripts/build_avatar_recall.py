"""头像上传 + 群消息撤回（后端）。"""

from pathlib import Path

# ---------------- 迁移 v11 ----------------
m = Path(r"D:\EduFlow\backend\db\migrations.py")
t = m.read_text(encoding="utf-8")
t = t.replace("CURRENT_VERSION = 10", "CURRENT_VERSION = 11")
if "_migrate_v11" not in t:
    func = '''
def _migrate_v11(conn: sqlite3.Connection) -> None:
    """v10 -> v11：用户头像 + 群消息撤回。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if "avatar" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT ''")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(group_messages)")}
    if "recalled" not in cols:
        conn.execute("ALTER TABLE group_messages ADD COLUMN recalled INTEGER NOT NULL DEFAULT 0")
    if "recalled_at" not in cols:
        conn.execute("ALTER TABLE group_messages ADD COLUMN recalled_at TEXT")


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
'''
    t = t.replace("MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [", func, 1)
    out = []
    for line in t.splitlines():
        out.append(line)
        if line.strip() == "(10, _migrate_v10),":
            out.append("    (11, _migrate_v11),")
    m.write_text("\n".join(out), encoding="utf-8")
    print("migrations: v11 头像 + 撤回")

# ---------------- 头像接口 ----------------
r = Path(r"D:\EduFlow\backend\api\user_routes.py")
t = r.read_text(encoding="utf-8")
if "auth/avatar" not in t:
    t = t.rstrip() + '''

@router.post("/api/auth/avatar", summary="上传我的头像")
def upload_avatar(req) -> Response:
    import base64

    from backend.http import multipart

    user = permissions.require_login(req.user)
    ctype = req.header("content-type")
    if not multipart.is_multipart(ctype):
        raise ValidationError("请用表单上传图片")
    form = multipart.parse_multipart(req.body, ctype)
    first = form.first_file()
    if first is None:
        raise ValidationError("没有收到文件")
    if len(first.data) > 1024 * 1024:
        raise ValidationError("头像不能超过 1 MB")
    mime = first.content_type or "image/png"
    if not mime.startswith("image/"):
        raise ValidationError("只能上传图片")
    data_url = f"data:{mime};base64," + base64.b64encode(first.data).decode()
    user_service.set_avatar(int(user["id"]), data_url)
    return ok({"avatar": data_url}, "头像已更新")


@router.delete("/api/auth/avatar", summary="恢复默认头像")
def clear_avatar(req) -> Response:
    user = permissions.require_login(req.user)
    user_service.set_avatar(int(user["id"]), "")
    return ok({"avatar": ""}, "已恢复默认头像")
'''
    r.write_text(t, encoding="utf-8")
    print("user_routes: 头像接口")

# ---------------- 服务：设置头像 ----------------
s = Path(r"D:\EduFlow\backend\services\user_service.py")
t = s.read_text(encoding="utf-8")
if "def set_avatar" not in t:
    t = t.rstrip() + '''

def set_avatar(user_id: int, data_url: str) -> None:
    user_repo.update(user_id, {"avatar": data_url[:800_000]})
'''
    s.write_text(t, encoding="utf-8")
    print("user_service: set_avatar")

# ---------------- auth_service.to_public 带头像 ----------------
a = Path(r"D:\EduFlow\backend\services\auth_service.py")
t = a.read_text(encoding="utf-8")
if '"avatar"' not in t:
    t = t.replace('"phone": user.get("phone"),', '"phone": user.get("phone"),\n        "avatar": user.get("avatar") or "",')
    if '"avatar"' not in t:
        t = t.replace('"real_name": user["real_name"],', '"real_name": user["real_name"],\n        "avatar": user.get("avatar") or "",')
    a.write_text(t, encoding="utf-8")
    print("auth_service: 返回头像")

# ---------------- 撤回 ----------------
g = Path(r"D:\EduFlow\backend\services\group_service.py")
t = g.read_text(encoding="utf-8")
if "def recall_message" not in t:
    t = t.rstrip() + '''

RECALL_WINDOW_SECONDS = 300


def recall_message(user: dict[str, Any], message_id: int) -> dict[str, Any]:
    """撤回群消息：本人 5 分钟内可撤回；老师/管理员可撤回自己发的消息。"""
    row = connection.query_one("SELECT * FROM group_messages WHERE id = ?", (message_id,))
    if row is None:
        raise NotFoundError("消息不存在")
    if row.get("recalled"):
        raise ValidationError("消息已撤回")
    _assert_member(user, int(row["group_id"]))

    is_owner = int(row["sender_id"]) == int(user["id"])
    is_admin = user["role"] == permissions.ROLE_ADMIN
    if not (is_owner or is_admin):
        raise ForbiddenError("只能撤回自己的消息")

    if is_owner and not is_admin:
        created = row.get("created_at") or ""
        try:
            from datetime import datetime, timezone

            made = datetime.fromisoformat(created.replace("Z", "+00:00"))
            now = clock.utcnow()
            if made.tzinfo is None:
                made = made.replace(tzinfo=timezone.utc)
            if (now - made).total_seconds() > RECALL_WINDOW_SECONDS:
                raise ValidationError("超过 5 分钟，不能撤回了")
        except ValidationError:
            raise
        except Exception:  # noqa: BLE001
            pass

    connection.execute(
        "UPDATE group_messages SET recalled = 1, recalled_at = ? WHERE id = ?",
        (clock.now_iso(), message_id),
    )
    return {"id": message_id, "recalled": True}
'''
    g.write_text(t, encoding="utf-8")
    print("group_service: recall_message")

# 详情返回里带 recalled（SELECT * 已包含）
rr = Path(r"D:\EduFlow\backend\api\group_routes.py")
t = rr.read_text(encoding="utf-8")
if "recall" not in t:
    t = t.rstrip() + '''

@router.post("/api/messages/<int:message_id>/recall", summary="撤回消息")
def recall_message(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(group_service.recall_message(user, req.path_params["message_id"]), "已撤回")
'''
    rr.write_text(t, encoding="utf-8")
    print("group_routes: 撤回接口")
