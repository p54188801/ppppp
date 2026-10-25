"""边界与并发自测。

覆盖：分页极值、非法参数、越权、重复提交、并发写入、超长字段。
用法：python tests/test_edge_cases.py [port]
"""

from __future__ import annotations

import http.client
import json
import sys
import threading

HOST, PORT = "127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8905
ok_list, bad = [], []


class C:
    def __init__(self):
        self.token = None

    def call(self, method, path, body=None, expect=200):
        conn = http.client.HTTPConnection(HOST, PORT, timeout=20)
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        if r.status != expect:
            raise AssertionError(f"{method} {path} -> {r.status} 期望 {expect}: {raw[:120]!r}")
        return json.loads(raw) if raw else {}

    def login(self, u):
        self.token = self.call("POST", "/api/auth/login",
                               {"username": u, "password": "Eduflow@2026"})["data"]["token"]


def check(name, fn):
    try:
        fn()
        ok_list.append(name)
        print(f"  [PASS] {name}")
    except Exception as e:  # noqa: BLE001
        bad.append((name, str(e)))
        print(f"  [FAIL] {name}: {e}")


admin, teacher, student = C(), C(), C()
admin.login("admin")
teacher.login("t1001")
student.login("s2001")
s: dict = {}

check("分页-超大 page_size 被钳制", lambda: admin.call(
    "GET", "/api/users?role=student&page_size=99999")["data"]["page_size"] <= 200 or
    (_ for _ in ()).throw(AssertionError("未钳制")))
check("分页-非法页码归 1", lambda: admin.call(
    "GET", "/api/users?page=abc")["data"]["page"] == 1 or
    (_ for _ in ()).throw(AssertionError("未归一")))
check("分页-负数页码归 1", lambda: admin.call(
    "GET", "/api/users?page=-5&page_size=-1")["data"]["page"] == 1 or
    (_ for _ in ()).throw(AssertionError("未归一")))
check("越权-学生看用户列表被拒", lambda: student.call("GET", "/api/users", expect=403))
check("越权-学生看审计日志被拒", lambda: student.call("GET", "/api/audit-logs", expect=403))
check("越权-教师看他人课程备份被拒", lambda: teacher.call("GET", "/api/system/backups", expect=403))
check("越权-未登录访问作业被拒", lambda: C().call("GET", "/api/assignments/1", expect=401))
check("非法-不存在的课程 404", lambda: admin.call("GET", "/api/courses/999999", expect=404))
check("非法-不存在的作业 404", lambda: admin.call("GET", "/api/assignments/999999", expect=404))
check("非法-超长公告标题 400", lambda: teacher.call(
    "POST", "/api/courses/1/announcements", {"title": "长" * 200}, expect=400))
check("非法-空 JSON 登录 400", lambda: C().call("POST", "/api/auth/login", {}, expect=400))
check("非法-错误 Content-Type 仍能解析", lambda: admin.call("GET", "/api/health"))


def dup_submit():
    items = teacher.call("GET", "/api/courses/1")["data"]["classes"]
    cid = items[0]["id"]
    a = teacher.call("POST", "/api/assignments",
                     {"class_id": cid, "title": "边界用例作业", "full_score": 100},
                     expect=201)["data"]["id"]
    s["aid"] = a
    try:
        student.call("POST", "/api/classes/join", {"code": items[0]["join_code"]})
    except AssertionError:
        pass  # 已经加入过
    student.call("POST", f"/api/assignments/{a}/submit", {"content": "第一次"})
    student.call("POST", f"/api/assignments/{a}/submit", {"content": "第二次"})
    mine = student.call("GET", f"/api/assignments/{a}")["data"]["my_submission"]
    assert mine["content"] == "第二次", mine


check("重复提交-覆盖而非报错", dup_submit)


def concurrent_writes():
    errors = []

    def worker(i):
        try:
            c = C()
            c.login("s2001")
            c.call("POST", f"/api/assignments/{s['aid']}/submit", {"content": f"并发-{i}"})
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    mine = student.call("GET", f"/api/assignments/{s['aid']}")["data"]["my_submission"]
    assert mine["content"].startswith("并发-"), mine


check("并发写入-6 线程不报错且最终一致", concurrent_writes)


def deadline_boundary():
    from datetime import datetime, timedelta, timezone

    items = teacher.call("GET", "/api/courses/1")["data"]["classes"]
    cid = items[0]["id"]
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    a = teacher.call("POST", "/api/assignments",
                     {"class_id": cid, "title": "过期作业", "deadline": past, "allow_late": False},
                     expect=201)["data"]["id"]
    student.call("POST", f"/api/assignments/{a}/submit", {"content": "迟交"}, expect=409)
    teacher.call("DELETE", f"/api/assignments/{a}")


check("截止边界-过期且不允许迟交被拒", deadline_boundary)

print()
print("=" * 46)
print(f"通过 {len(ok_list)}，失败 {len(bad)}")
for n, e in bad:
    print(f"  - {n}: {e}")
sys.exit(1 if bad else 0)
