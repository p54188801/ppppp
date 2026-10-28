"""班级群 + 群作业 + 课程推荐 端到端验证。"""

from __future__ import annotations

import http.client
import json
import sys

H, P = "127.0.0.1", 8765
passed, failed = [], []


def call(method, path, body=None, token=None, raw=None, ctype="application/json", expect=200):
    c = http.client.HTTPConnection(H, P, timeout=20)
    h = {"Content-Type": ctype}
    if token:
        h["Authorization"] = "Bearer " + token
    data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode() if body else None)
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    d = r.read()
    c.close()
    if r.status != expect:
        raise AssertionError(f"{method} {path} -> {r.status} 期望 {expect}: {d[:160]!r}")
    return json.loads(d) if d else {}


def check(name, fn):
    try:
        fn()
        passed.append(name)
        print(f"  [PASS] {name}")
    except Exception as exc:  # noqa: BLE001
        failed.append((name, str(exc)))
        print(f"  [FAIL] {name}: {exc}")


import time
SFX = str(int(time.time()))[-5:]
NAME_T = '群老师' + SFX
NAME_S = '群学生' + SFX
NUM_T = 'T' + SFX
NUM_S = 'S' + SFX

state: dict = {}


def register_teacher():
    data = call("POST", "/api/auth/register", {
        "real_name": NAME_T, "number": NUM_T, "password": "abc123456",
        "role": "teacher", "class_name": "大数据G231",
    }, expect=201)["data"]
    state["teacher"] = data["user"]["username"]
    state["group_id"] = data["joined_group"]["id"]
    assert data["joined_group"]["name"] == "大数据G231"


check("教师注册并自动建群", register_teacher)


def register_student():
    data = call("POST", "/api/auth/register", {
        "real_name": NAME_S, "number": NUM_S, "password": "abc123456",
        "role": "student", "class_name": "大数据G231",
    }, expect=201)["data"]
    state["student"] = data["user"]["username"]
    assert data["joined_group"]["id"] == state["group_id"], data


check("学生注册自动进同一个群", register_student)


def login(user):
    return call("POST", "/api/auth/login", {"username": user, "password": "abc123456"})["data"]["token"]


state["tt"] = login(state["teacher"])
state["st"] = login(state["student"])


def group_detail():
    d = call("GET", f"/api/groups/{state['group_id']}", token=state["st"])["data"]
    roles = {m["username"]: m["role"] for m in d["members"]}
    assert roles.get(state["teacher"]) == "teacher", roles
    assert roles.get(state["student"]) == "student", roles


check("群成员包含师生", group_detail)
check("群列表", lambda: call("GET", "/api/groups", token=state["st"])["data"])


def post_text():
    d = call("POST", f"/api/groups/{state['group_id']}/messages",
             {"content": "大家好，这是班级群"}, token=state["st"], expect=201)["data"]
    assert d["kind"] == "text"


check("发文字消息", post_text)


def post_image():
    bnd = "----gt"
    payload = (
        f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="pic.png"\r\n'
        f'Content-Type: image/png\r\n\r\n'
    ).encode() + b"\x89PNG\r\n\x1a\n" + f"\r\n--{bnd}--\r\n".encode()
    d = call("POST", f"/api/groups/{state['group_id']}/messages", token=state["st"],
             raw=payload, ctype=f"multipart/form-data; boundary={bnd}", expect=201)["data"]
    assert d["kind"] == "image", d
    state["msg_id"] = d["id"]


check("发图片消息", post_image)
def download_file():
    c = http.client.HTTPConnection(H, P, timeout=20)
    c.request("GET", f"/api/messages/{state['msg_id']}/file",
              headers={"Authorization": "Bearer " + state["tt"]})
    r = c.getresponse(); body = r.read(); c.close()
    assert r.status == 200, r.status
    assert len(body) > 0, "空文件"


check("下载群文件", download_file)


def create_assignment():
    d = call("POST", f"/api/groups/{state['group_id']}/assignments",
             {"title": "第一次群作业", "content": "交一份截图", "full_score": 100},
             token=state["tt"], expect=201)["data"]
    state["aid"] = d["id"]


check("老师发布群作业", create_assignment)
check("学生不能发作业", lambda: call(
    "POST", f"/api/groups/{state['group_id']}/assignments", {"title": "x"},
    token=state["st"], expect=403))


def submit():
    bnd = "----gs"
    payload = (
        f'--{bnd}\r\nContent-Disposition: form-data; name="content"\r\n\r\n我的作业答案\r\n'
        f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="ans.txt"\r\n'
        f'Content-Type: text/plain\r\n\r\nhello homework\r\n--{bnd}--\r\n'
    ).encode()
    d = call("POST", f"/api/group-assignments/{state['aid']}/submit", token=state["st"],
             raw=payload, ctype=f"multipart/form-data; boundary={bnd}")["data"]
    state["sid"] = d["id"]
    assert d["content"] == "我的作业答案"


check("学生提交作业（文字+文件）", submit)


def grade():
    d = call("POST", f"/api/group-submissions/{state['sid']}/grade",
             {"score": 92, "feedback": "不错"}, token=state["tt"])["data"]
    assert d["score"] == 92


check("老师批改打分", grade)
check("查看提交列表", lambda: call(
    "GET", f"/api/group-assignments/{state['aid']}/submissions", token=state["tt"])["data"])
check("学生不能看别人的提交", lambda: call(
    "GET", f"/api/group-assignments/{state['aid']}/submissions", token=state["st"], expect=403))


def offers():
    d = call("GET", "/api/my/course-offers", token=state["st"])["data"]
    assert isinstance(d, list), d
    state["offer"] = d[0] if d else None


check("课程推荐列表", offers)


def accept_offer():
    if not state["offer"]:
        raise AssertionError("没有推荐可接受（库里没有大数据相关课程？）")
    d = call("POST", f"/api/course-offers/{state['offer']['offer_id']}/accept", token=state["st"])["data"]
    assert d["status"] == "accepted"


check("接受课程推荐并入班", accept_offer)

print()
print("=" * 50)
print(f"通过 {len(passed)}，失败 {len(failed)}")
for n, e in failed:
    print("  -", n, e)
sys.exit(1 if failed else 0)
