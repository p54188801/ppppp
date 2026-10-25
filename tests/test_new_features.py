"""新增功能验证：公告 / 全局搜索 / 数据备份（正反用例）。"""

from __future__ import annotations

import http.client
import json
import sys

HOST, PORT = "127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8905
passed, failed = [], []


class C:
    def __init__(self):
        self.token = None

    def call(self, method, path, body=None, expect=200, parse=True):
        conn = http.client.HTTPConnection(HOST, PORT, timeout=20)
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        if resp.status != expect:
            raise AssertionError(f"{method} {path} -> {resp.status} (期望 {expect}): {raw[:160]!r}")
        if not parse or not raw:
            return {"_bytes": len(raw)}
        return json.loads(raw)

    def login(self, u, p="Eduflow@2026"):
        self.token = self.call("POST", "/api/auth/login", {"username": u, "password": p})["data"]["token"]


def check(name, fn):
    try:
        fn()
        passed.append(name)
        print(f"  [PASS] {name}")
    except Exception as exc:  # noqa: BLE001
        failed.append((name, str(exc)))
        print(f"  [FAIL] {name}: {exc}")


admin, teacher, student = C(), C(), C()
admin.login("admin")
teacher.login("t1001")
student.login("s2001")
state: dict = {}

# ---- 搜索 ----
check("搜索-管理员有结果", lambda: admin.call("GET", "/api/search?q=%E6%95%B0%E6%8D%AE")["data"].__getitem__("total") or
      (_ for _ in ()).throw(AssertionError("total 为 0")))
check("搜索-教师有结果", lambda: teacher.call("GET", "/api/search?q=%E6%95%B0%E6%8D%AE")["data"]["total"] > 0 or
      (_ for _ in ()).throw(AssertionError("total 为 0")))
check("搜索-学生有结果", lambda: student.call("GET", "/api/search?q=%E6%95%B0%E6%8D%AE")["data"]["total"] > 0 or
      (_ for _ in ()).throw(AssertionError("total 为 0")))
check("搜索-空关键词返回 0", lambda: admin.call("GET", "/api/search?q=")["data"]["total"] == 0 or
      (_ for _ in ()).throw(AssertionError("应为 0")))
check("搜索-未登录被拒", lambda: C().call("GET", "/api/search?q=x", expect=401))


def pick_course():
    items = teacher.call("GET", "/api/courses")["data"]["items"]
    assert items, "教师无课程"
    state["course_id"] = items[0]["id"]


check("取课程", pick_course)


def create_ann():
    data = teacher.call(
        "POST",
        f"/api/courses/{state['course_id']}/announcements",
        {"title": "测试公告：期中安排", "content": "下周三期中测验", "pinned": True},
        expect=201,
    )
    state["ann_id"] = data["data"]["id"]


check("发布公告", create_ann)
check("公告列表包含新公告", lambda: any(
    item["id"] == state["ann_id"]
    for item in teacher.call("GET", f"/api/courses/{state['course_id']}/announcements")["data"]
) or (_ for _ in ()).throw(AssertionError("列表里没有")))
check("学生公告流", lambda: isinstance(student.call("GET", "/api/my/announcements")["data"], list) or
      (_ for _ in ()).throw(AssertionError("格式不对")))
check("更新公告", lambda: student.call("GET", "/api/my/announcements") and teacher.call(
    "PUT", f"/api/announcements/{state['ann_id']}", {"title": "测试公告（已更新）"}
)["data"]["title"].startswith("测试公告"))
check("学生不能发公告", lambda: student.call(
    "POST", f"/api/courses/{state['course_id']}/announcements", {"title": "x2"}, expect=403))
check("公告标题过短被拒", lambda: teacher.call(
    "POST", f"/api/courses/{state['course_id']}/announcements", {"title": "x"}, expect=400))

# ---- 备份 ----


def make_backup():
    data = admin.call("POST", "/api/system/backup", {"note": "auto-test"})["data"]
    state["backup"] = data["filename"]
    assert data["size"] > 0


check("创建备份", make_backup)
check("备份列表包含它", lambda: any(
    item["filename"] == state["backup"]
    for item in admin.call("GET", "/api/system/backups")["data"]["items"]
) or (_ for _ in ()).throw(AssertionError("列表里没有")))
check("教师不能备份", lambda: teacher.call("POST", "/api/system/backup", {}, expect=403))
check("下载备份返回二进制", lambda: admin.call(
    "GET", f"/api/system/backups/{state['backup']}/download", parse=False)["_bytes"] > 0 or
    (_ for _ in ()).throw(AssertionError("空文件")))
check("恢复必须 confirm", lambda: admin.call(
    "POST", f"/api/system/backups/{state['backup']}/restore", {}, expect=400))
check("删除备份", lambda: admin.call("DELETE", f"/api/system/backups/{state['backup']}"))
check("删除公告", lambda: teacher.call("DELETE", f"/api/announcements/{state['ann_id']}"))

print()
print("=" * 46)
print(f"通过 {len(passed)}，失败 {len(failed)}")
for name, err in failed:
    print(f"  - {name}: {err}")
sys.exit(1 if failed else 0)
