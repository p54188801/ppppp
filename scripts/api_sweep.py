"""全量接口巡检：按 /api/routes 清单逐个调用，报告失败项。

用法：python scripts/api_sweep.py [port]
"""

from __future__ import annotations

import http.client
import json
import re
import sys

HOST = "127.0.0.1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

# 参数占位：路径里的 <int:xxx> 用这些值替换
SAMPLE = {
    "course_id": 1, "class_id": 1, "assignment_id": 1, "quiz_id": 1,
    "session_id": 1, "resource_id": 1, "discussion_id": 1, "reply_id": 1,
    "notification_id": 1, "user_id": 2, "file_id": 1, "announcement_id": 1,
    "submission_id": 1, "filename": "none.db",
}


def call(method, path, token=None, body=None):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=15)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps(body).encode() if body is not None else None
    conn.request(method, path, body=payload, headers=headers)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data


def login(user, pwd="Eduflow@2026"):
    st, b = call("POST", "/api/auth/login", body={"username": user, "password": pwd})
    if st != 200:
        raise SystemExit(f"登录失败 {user}: {st} {b[:100]}")
    return json.loads(b)["data"]["token"]


# 只读接口做安全巡检；写接口单独在功能测试里覆盖
admin = login("admin")
teacher = login("t1001")
student = login("s2001")
TOKENS = {"admin": admin, "teacher": teacher, "student": student}

st, body = call("GET", "/api/routes", admin)
routes = json.loads(body)["data"]["routes"]

PATTERN = re.compile(r"<(?:\w+):(\w+)>")

ok_count = 0
problems: list[str] = []
skipped = 0

for route in routes:
    if route["method"] != "GET":
        skipped += 1
        continue
    path = route["pattern"]
    for name in PATTERN.findall(path):
        path = PATTERN.sub(str(SAMPLE.get(name, 1)), path, count=1)

    # 按路由要求挑角色
    roles = route.get("roles") or []
    if "admin" in roles:
        token = admin
    elif "teacher" in roles:
        token = teacher
    elif "student" in roles:
        token = student
    else:
        token = admin

    try:
        status, data = call("GET", path, token)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{path:55} EXC {exc}")
        continue

    if 200 <= status < 300:
        ok_count += 1
    elif status == 404:
        # 样本 id 不存在属正常
        ok_count += 1
    else:
        problems.append(f"{path:55} HTTP {status} {data[:80]!r}")

print(f"GET 接口 {ok_count + len(problems)} 个：通过 {ok_count}，异常 {len(problems)}（跳过写接口 {skipped} 个）")
for p in problems:
    print("  ✗", p)

sys.exit(1 if problems else 0)
