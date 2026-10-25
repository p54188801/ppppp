"""章节任务点与学习进度验证（正例 + 越权 + 非法参数）。

覆盖：
- 教师建/改/删章节与任务点；
- 学生查看章节、开始学习、推进进度、完成任务；
- 教师查看整门课的完成率明细；
- 非任课教师、未选课学生、未登录用户的越权拦截；
- 进度越界、任务类型非法、关联内容不存在等边界。

用法：python tests/test_chapters.py [port]
"""

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
            raise AssertionError(
                f"{method} {path} -> {resp.status} (期望 {expect}): {raw[:200]!r}"
            )
        if not parse or not raw:
            return {"_bytes": len(raw)}
        return json.loads(raw)

    def login(self, u, p="Eduflow@2026"):
        self.token = self.call(
            "POST", "/api/auth/login", {"username": u, "password": p}
        )["data"]["token"]


def check(name, fn):
    try:
        fn()
        passed.append(name)
        print(f"  [PASS] {name}")
    except Exception as exc:  # noqa: BLE001
        failed.append((name, str(exc)))
        print(f"  [FAIL] {name}: {exc}")


admin, teacher, student, other_teacher, anon = C(), C(), C(), C(), C()
teacher.login("t1001")
student.login("s2001")
other_teacher.login("t1002")
admin.login("admin")
state: dict = {}


def pick_course():
    detail = teacher.call("GET", "/api/courses/1")["data"]
    state["course_id"] = detail["id"]
    state["classes"] = detail["classes"]
    state["class_id"] = detail["classes"][0]["id"]
    state["join_code"] = detail["classes"][0]["join_code"]
    resources = teacher.call("GET", f"/api/courses/{state['course_id']}/resources")["data"]
    assert resources, "演示数据里没有课程资料"
    state["resource_id"] = resources[0]["id"]
    assignments = teacher.call(
        "GET", f"/api/classes/{state['class_id']}/assignments"
    )["data"]
    assert assignments, "演示数据里没有作业"
    state["assignment_id"] = assignments[0]["id"]
    state["student_id"] = student.call("GET", "/api/auth/me")["data"]["id"]


check("取课程与关联内容", pick_course)
check("初始章节列表可读", lambda: isinstance(
    student.call("GET", f"/api/courses/{state['course_id']}/chapters")["data"]["items"], list
) or (_ for _ in ()).throw(AssertionError("格式不对")))
check("学生不能建章节", lambda: student.call(
    "POST", f"/api/courses/{state['course_id']}/chapters", {"title": "越权章节"}, expect=403
))


def create_chapter():
    data = teacher.call(
        "POST",
        f"/api/courses/{state['course_id']}/chapters",
        {"title": "第 9 章 章节测试", "description": "自动化测试章节"},
        expect=201,
    )
    state["chapter_id"] = data["data"]["id"]
    assert data["data"]["order_no"] >= 1


check("教师建章节", create_chapter)
check("章节标题过短被拒", lambda: teacher.call(
    "POST", f"/api/courses/{state['course_id']}/chapters", {"title": "x"}, expect=400
))


def create_tasks():
    material = teacher.call(
        "POST",
        f"/api/chapters/{state['chapter_id']}/tasks",
        {
            "type": "material",
            "title": "阅读课程大纲",
            "description": "了解考核方式",
            "duration": 20,
            "resource_id": state["resource_id"],
        },
        expect=201,
    )["data"]
    state["material_task_id"] = material["id"]
    assert material["resource_id"] == state["resource_id"]

    assignment = teacher.call(
        "POST",
        f"/api/chapters/{state['chapter_id']}/tasks",
        {
            "type": "assignment",
            "title": "完成章节作业",
            "duration": 60,
            "assignment_id": state["assignment_id"],
        },
        expect=201,
    )["data"]
    state["assignment_task_id"] = assignment["id"]
    assert assignment["assignment_id"] == state["assignment_id"]

    text = teacher.call(
        "POST",
        f"/api/chapters/{state['chapter_id']}/tasks",
        {"type": "text", "title": "图文导学", "duration": 10, "required": False},
        expect=201,
    )["data"]
    state["text_task_id"] = text["id"]
    assert text["required"] is False


check("建三种任务点", create_tasks)
check("非法任务类型被拒", lambda: teacher.call(
    "POST", f"/api/chapters/{state['chapter_id']}/tasks",
    {"type": "video", "title": "视频任务"}, expect=400))
check("关联不存在的作业被拒", lambda: teacher.call(
    "POST", f"/api/chapters/{state['chapter_id']}/tasks",
    {"type": "assignment", "title": "坏关联", "assignment_id": 999999}, expect=404))


def student_sees_tasks():
    data = student.call("GET", f"/api/courses/{state['course_id']}/chapters")["data"]
    chapter = next(item for item in data["items"] if item["id"] == state["chapter_id"])
    assert chapter["task_count"] == 3, chapter
    titles = {task["title"] for task in chapter["tasks"]}
    assert {"阅读课程大纲", "完成章节作业", "图文导学"} <= titles
    assert all(task["my_progress"] is None for task in chapter["tasks"])


check("学生看到任务点且未开始", student_sees_tasks)


def start_task():
    data = student.call(
        "POST", f"/api/tasks/{state['text_task_id']}/progress", {"status": "in_progress"}
    )["data"]
    state["start_progress"] = data["progress"]
    assert data["status"] == "in_progress"
    assert data["progress"] == 10, data
    assert data["started_at"]


check("开始学习", start_task)


def advance_task():
    data = student.call(
        "POST", f"/api/tasks/{state['text_task_id']}/progress", {"progress": 60}
    )["data"]
    assert data["status"] == "in_progress"
    assert data["progress"] == 60
    assert data["finished_at"] is None


check("推进到 60%", advance_task)


def partial_progress_counts():
    data = student.call("GET", f"/api/courses/{state['course_id']}/chapters")["data"]
    chapter = next(item for item in data["items"] if item["id"] == state["chapter_id"])
    assert chapter["completed_count"] == 0, chapter
    assert abs(chapter["progress"] - 20.0) < 1e-6, chapter


check("进行中的任务计入学习进度", partial_progress_counts)


def complete_task():
    data = student.call(
        "POST", f"/api/tasks/{state['text_task_id']}/progress", {"progress": 100}
    )["data"]
    assert data["status"] == "completed"
    assert data["progress"] == 100
    assert data["finished_at"]
    assert data["chapter"]["completed_count"] >= 1, data
    state["completed_at"] = data["finished_at"]


check("标记完成", complete_task)


def repeat_complete():
    data = student.call(
        "POST", f"/api/tasks/{state['text_task_id']}/progress", {"status": "completed"}
    )["data"]
    assert data["status"] == "completed" and data["progress"] == 100
    assert data["finished_at"] == state["completed_at"], "重复完成不应刷新完成时间"


check("重复完成幂等", repeat_complete)

check("进度越界被拒", lambda: student.call(
    "POST", f"/api/tasks/{state['text_task_id']}/progress", {"progress": 101}, expect=400))
check("空进度请求被拒", lambda: student.call(
    "POST", f"/api/tasks/{state['text_task_id']}/progress", {}, expect=400))
check("教师不能代报学生进度", lambda: teacher.call(
    "POST", f"/api/tasks/{state['text_task_id']}/progress", {"progress": 100}, expect=403))


def teacher_progress():
    data = teacher.call("GET", f"/api/courses/{state['course_id']}/progress")["data"]
    row = next(item for item in data["students"] if item["student_id"] == state["student_id"])
    assert row["completed_count"] >= 1, row
    assert row["progress"] > 0
    assert any(chapter["id"] == state["chapter_id"] for chapter in data["chapters"])
    assert data["summary"]["student_count"] >= 1


check("教师看完成率明细", teacher_progress)


def my_learning():
    data = student.call("GET", "/api/my/learning")["data"]
    course = next(item for item in data if item["course_id"] == state["course_id"])
    assert course["task_count"] >= 3, course
    assert course["completed_count"] >= 1, course
    assert course["progress"] > 0, course


check("我的学习进度汇总", my_learning)
check("教师不能看我的学习进度", lambda: teacher.call("GET", "/api/my/learning", expect=403))
check("非任课教师看进度被拒", lambda: other_teacher.call(
    "GET", f"/api/courses/{state['course_id']}/progress", expect=403))


def update_items():
    chapter = teacher.call(
        "PUT", f"/api/chapters/{state['chapter_id']}", {"title": "第 9 章 章节测试（改）"}
    )["data"]
    assert chapter["title"].endswith("（改）")
    task = teacher.call(
        "PUT", f"/api/tasks/{state['material_task_id']}", {"title": "阅读课程大纲（改）"}
    )["data"]
    assert task["title"].endswith("（改）")


check("修改章节与任务点", update_items)
check("学生不能改任务点", lambda: student.call(
    "PUT", f"/api/tasks/{state['material_task_id']}", {"title": "越权修改"}, expect=403))


def delete_task():
    teacher.call("DELETE", f"/api/tasks/{state['assignment_task_id']}")
    data = teacher.call("GET", f"/api/courses/{state['course_id']}/chapters")["data"]
    chapter = next(item for item in data["items"] if item["id"] == state["chapter_id"])
    assert chapter["task_count"] == 2, chapter


check("删除任务点", delete_task)


def leave_and_block():
    for item in state["classes"]:
        try:
            student.call("POST", f"/api/classes/{item['id']}/leave")
        except AssertionError:
            pass  # 本来就没选这个班
    student.call("GET", f"/api/courses/{state['course_id']}/chapters", expect=403)


check("退课后看不到章节", leave_and_block)
check("退课后不能上报进度", lambda: student.call(
    "POST", f"/api/tasks/{state['text_task_id']}/progress", {"progress": 100}, expect=403))


def rejoin():
    student.call("POST", "/api/classes/join", {"code": state["join_code"]})
    data = student.call("GET", f"/api/courses/{state['course_id']}/chapters")["data"]
    assert any(item["id"] == state["chapter_id"] for item in data["items"])


check("重新加入后恢复访问", rejoin)


def delete_chapter():
    teacher.call("DELETE", f"/api/chapters/{state['chapter_id']}")
    data = teacher.call("GET", f"/api/courses/{state['course_id']}/chapters")["data"]
    assert all(item["id"] != state["chapter_id"] for item in data["items"])


check("删除章节（级联任务点）", delete_chapter)
check("未登录访问章节被拒", lambda: anon.call(
    "GET", f"/api/courses/{state['course_id']}/chapters", expect=401))
check("未登录上报进度被拒", lambda: anon.call(
    "POST", f"/api/tasks/{state['text_task_id']}/progress", {"progress": 100}, expect=401))

print()
print("=" * 46)
print(f"通过 {len(passed)}，失败 {len(failed)}")
for name, err in failed:
    print(f"  - {name}: {err}")
sys.exit(1 if failed else 0)
