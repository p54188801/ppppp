"""忘记密码：校验学号+姓名后重置为一次性临时密码。"""

from pathlib import Path

# ---------------- 服务 ----------------
svc = Path(r"D:\EduFlow\backend\services\user_service.py")
t = svc.read_text(encoding="utf-8")

if "def forgot_password" not in t:
    func = '''

def forgot_password(payload: dict[str, Any], *, ip: str = "") -> dict[str, Any]:
    """凭「学号/工号 + 姓名」重置为临时密码。

    这是没有短信/邮件的校园小型部署方案：只核对身份信息，
    重置后强制下次登录修改密码，并吊销所有旧会话。
    """
    import secrets

    from backend.core import security

    number = validators.required_str(payload, "number", min_len=2, max_len=32)
    real_name = validators.required_str(payload, "real_name", min_len=1, max_len=32)

    user = user_repo.by_number(number)
    if user is None or (user.get("real_name") or "").strip() != real_name.strip():
        audit_repo.log(
            user_id=None, username=number, action="forgot_password_failed",
            entity="user", entity_id=None, detail=f"身份不匹配（{ip}）", ip=ip,
        )
        raise ValidationError("学号与姓名不匹配，请检查后重试")

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    temp = "".join(secrets.choice(alphabet) for _ in range(8))
    digest, salt = security.hash_password(temp)
    user_repo.update(int(user["id"]), {
        "password_hash": digest,
        "password_salt": salt,
        "must_change_password": 1,
    })
    session_repo.revoke_all_for_user(int(user["id"]))
    audit_repo.log(
        user_id=int(user["id"]), username=user["username"], action="forgot_password",
        entity="user", entity_id=int(user["id"]), detail=f"自助重置为临时密码（{ip}）", ip=ip,
    )
    return {
        "username": user["username"],
        "real_name": user.get("real_name"),
        "temp_password": temp,
        "hint": "登录后用临时密码修改成自己的密码",
    }
'''
    t = t.rstrip() + func
    svc.write_text(t, encoding="utf-8")
    print("user_service: 已加 forgot_password")

# ---------------- 路由 ----------------
r = Path(r"D:\EduFlow\backend\api\auth_routes.py")
t = r.read_text(encoding="utf-8")
if "forgot-password" not in t:
    route = '''

_RESET_LOG: dict[str, list[float]] = {}


@router.post("/api/auth/forgot-password", auth=False, summary="忘记密码（重置为临时密码）")
def forgot_password(req) -> Response:
    import time

    ip = req.client_ip or "unknown"
    now = time.time()
    hits = [x for x in _RESET_LOG.get(ip, []) if now - x < 600]
    if len(hits) >= 5:
        raise ValidationError("重置过于频繁，请 10 分钟后再试")
    hits.append(now)
    _RESET_LOG[ip] = hits

    data = user_service.forgot_password(req.json(), ip=ip)
    return ok(data, "已重置，请用临时密码登录")
'''
    t = t.rstrip() + route
    r.write_text(t, encoding="utf-8")
    print("auth_routes: 已加 forgot-password 接口")
