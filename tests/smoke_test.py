"""端到端冒烟测试。

不依赖 pytest，直接起一个内置服务器，用真实 HTTP 请求把主要业务链路
走一遍：登录 -> 建课 -> 建作业 -> 学生提交 -> 教师批改 -> 测验 -> 签到 ->
成绩册 -> 通知。

运行：python tests/smoke_test.py
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import traceback
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 用临时数据目录，避免污染开发库
TMP = tempfile.mkdtemp(prefix="eduflow-test-")
os.environ["EDUFLOW_DATA_DIR"] = TMP
os.environ["EDUFLOW_DB_PATH"] = os.path.join(TMP, "test.db")

from backend import config  # noqa: E402

config.DATA_DIR = __import__("pathlib").Path(TMP)
config.DB_PATH = config.DATA_DIR / "test.db"
config.UPLOAD_DIR = config.DATA_DIR / "uploads"

from backend.app import Application  # noqa: E402
from backend.db import migrations  # noqa: E402
from backend.db.seed import seed  # noqa: E402
from backend.http.server import HttpServer  # noqa: E402

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


class Client:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        raw: bytes | None = None,
        content_type: str = "application/json",
        expect: int = 200,
    ) -> dict[str, Any]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=20)
        headers = {"Content-Type": content_type}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = raw if raw is not None else (
            json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        )
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read()
        status = response.status
        conn.close()
        if status != expect:
            raise AssertionError(
                f"{method} {path} 期望 {expect} 实际 {status}: {data[:400]!r}"
            )
        if not data:
            return {}
        try:
            return json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            return {"_raw": data.decode("utf-8", "replace")}

    def get(self, path: str, **kwargs) -> dict[str, Any]:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        return self.request("POST", path, body, **kwargs)

    def put(self, path: str, body: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        return self.request("PUT", path, body, **kwargs)


def check(name: str, func):
    try:
        func()
        PASSED.append(name)
        print(f"  [PASS] {name}")
    except Exception as exc:  # noqa: BLE001
        FAILED.append((name, str(exc)))
        print(f"  [FAIL] {name}: {exc}")
        traceback.print_exc()


def main() -> int:
    print("启动测试服务器……")
    migrations.init_db()
    seed()
    app = Application()
    server = HttpServer(app.dispatch, host="127.0.0.1", port=0).start()
    server.wait_ready()
    host, port = "127.0.0.1", server.port
    print(f"服务地址 http://{host}:{port}\n")

    admin = Client(host, port)
    teacher = Client(host, port)
    student = Client(host, port)
    anon = Client(host, port)

    state: dict[str, Any] = {}

    def t_health():
        data = anon.get("/api/health")
        assert data["data"]["status"] == "ok", data

    def t_meta():
        data = anon.get("/api/meta")
        assert data["data"]["version"], data

    def t_login_admin():
        data = admin.post("/api/auth/login", {"username": "admin", "password": "Eduflow@2026"})
        admin.token = data["data"]["token"]
        assert data["data"]["user"]["role"] == "admin"

    def t_login_teacher():
        data = teacher.post(
            "/api/auth/login", {"username": "t1001", "password": "Eduflow@2026"}
        )
        teacher.token = data["data"]["token"]
        assert data["data"]["user"]["role"] == "teacher"

    def t_login_student():
        data = student.post(
            "/api/auth/login", {"username": "s2001", "password": "Eduflow@2026"}
        )
        student.token = data["data"]["token"]
        assert data["data"]["user"]["role"] == "student"

    def t_me():
        data = student.get("/api/auth/me")
        assert data["data"]["username"] == "s2001"

    def t_bad_login():
        resp = anon.request(
            "POST", "/api/auth/login",
            {"username": "admin", "password": "wrong"}, expect=401,
        )
        assert resp["ok"] is False

    def t_unauthorized():
        anon.request("GET", "/api/courses", expect=401)

    def t_admin_dashboard():
        data = admin.get("/api/dashboard")
        assert "users" in data["data"], data

    def t_user_list():
        data = admin.get("/api/users?role=student&page=1&page_size=5")
        assert data["data"]["total"] >= 1

    def t_create_course():
        data = teacher.post(
            "/api/courses",
            {
                "code": "TST101",
                "name": "测试课程",
                "credits": 3,
                "hours": 32,
                "description": "冒烟测试用课程",
            },
        expect=201)
        course = data["data"]
        state["course_id"] = course["id"]
        assert course["code"] == "TST101"

    def t_course_classes():
        data = teacher.get(f"/api/courses/{state['course_id']}")
        classes = data["data"]["classes"]
        assert classes, data
        state["class_id"] = classes[0]["id"]
        state["join_code"] = classes[0]["join_code"]

    def t_join_class():
        data = student.post("/api/classes/join", {"code": state["join_code"]})
        assert data["ok"]

    def t_create_chapter():
        data = teacher.post(
            f"/api/courses/{state['course_id']}/chapters",
            {"title": "第 1 章 冒烟测试", "description": "章节任务点冒烟"},
            expect=201,
        )
        state["chapter_id"] = data["data"]["id"]

    def t_create_chapter_task():
        data = teacher.post(
            f"/api/chapters/{state['chapter_id']}/tasks",
            {
                "type": "text",
                "title": "阅读课程导学",
                "description": "了解课程安排",
                "duration": 10,
                "required": True,
            },
            expect=201,
        )
        state["task_id"] = data["data"]["id"]
        assert data["data"]["type"] == "text"

    def t_student_chapters():
        data = student.get(f"/api/courses/{state['course_id']}/chapters")
        chapter = next(item for item in data["data"]["items"] if item["id"] == state["chapter_id"])
        assert chapter["task_count"] == 1
        assert chapter["tasks"][0]["my_progress"] is None

    def t_report_progress():
        data = student.post(
            f"/api/tasks/{state['task_id']}/progress", {"progress": 100}
        )
        assert data["data"]["status"] == "completed"
        assert data["data"]["progress"] == 100
        assert data["data"]["finished_at"]

    def t_teacher_progress():
        data = teacher.get(f"/api/courses/{state['course_id']}/progress")
        rows = data["data"]["students"]
        assert rows and rows[0]["completed_count"] >= 1, rows

    def t_create_assignment():
        data = teacher.post(
            "/api/assignments",
            {
                "class_id": state["class_id"],
                "title": "冒烟测试作业",
                "content": "请提交一段文字",
                "full_score": 100,
                "allow_late": True,
            },
        expect=201)
        state["assignment_id"] = data["data"]["id"]
        assert data["data"]["title"] == "冒烟测试作业"

    def t_student_assignments():
        data = student.get("/api/my/assignments")
        titles = [item["title"] for item in data["data"]]
        assert "冒烟测试作业" in titles, titles

    def t_submit_assignment():
        data = student.post(
            f"/api/assignments/{state['assignment_id']}/submit",
            {"content": "这是我的作业内容", "attachments": []},
        )
        assert data["ok"]
        state["submission_id"] = data["data"]["id"]

    def t_list_submissions():
        data = teacher.get(f"/api/assignments/{state['assignment_id']}/submissions")
        assert data["data"]["stats"]["total"] >= 1

    def t_grade_submission():
        data = teacher.post(
            f"/api/submissions/{state['submission_id']}/grade",
            {"score": 92, "feedback": "不错"},
        )
        assert data["data"]["score"] == 92

    def t_create_quiz():
        data = teacher.post(
            "/api/quizzes",
            {
                "class_id": state["class_id"],
                "title": "冒烟测试测验",
                "duration": 20,
                "questions": [
                    {
                        "type": "single",
                        "stem": "1 + 1 = ?",
                        "options": ["1", "2", "3"],
                        "answer": "B",
                        "score": 50,
                    },
                    {
                        "type": "judge",
                        "stem": "地球是圆的",
                        "answer": "对",
                        "score": 50,
                    },
                ],
            },
        expect=201)
        state["quiz_id"] = data["data"]["id"]
        assert data["data"]["total_score"] == 100

    def t_start_quiz():
        data = student.post(f"/api/quizzes/{state['quiz_id']}/start")
        assert len(data["data"]["questions"]) == 2
        qs = data["data"]["questions"]
        state["answers"] = {str(qs[0]["id"]): "B", str(qs[1]["id"]): "对"}

    def t_submit_quiz():
        data = student.post(
            f"/api/quizzes/{state['quiz_id']}/submit", {"answers": state["answers"]}
        )
        assert data["data"]["score"] == 100, data

    def t_create_attendance():
        data = teacher.post(
            "/api/attendance",
            {"class_id": state["class_id"], "title": "冒烟测试签到", "duration": 10},
        expect=201)
        state["session_id"] = data["data"]["id"]
        state["att_code"] = data["data"]["code"]

    def t_check_in():
        data = student.post(
            f"/api/attendance/{state['session_id']}/check-in",
            {"code": state["att_code"]},
        )
        assert data["data"]["status"] in ("present", "late")

    def t_grade_rule():
        data = teacher.put(
            f"/api/classes/{state['class_id']}/grade-rule",
            {
                "assignment_weight": 0.4,
                "quiz_weight": 0.3,
                "attendance_weight": 0.2,
                "final_weight": 0.1,
            },
        )
        assert abs(data["data"]["assignment_weight"] - 0.4) < 1e-6

    def t_gradebook():
        data = teacher.get(f"/api/classes/{state['class_id']}/gradebook")
        assert data["data"]["rows"], data
        assert "average" in data["data"]["stats"]

    def t_set_final():
        student_id = student.get("/api/auth/me")["data"]["id"]
        data = teacher.post(
            f"/api/classes/{state['class_id']}/grades",
            {"student_id": student_id, "final_score": 88},
        )
        assert data["data"]["final_score"] == 88

    def t_transcript():
        data = student.get("/api/my/transcript")
        assert "gpa" in data["data"]

    def t_discussion():
        data = student.post(
            f"/api/courses/{state['course_id']}/discussions",
            {"title": "冒烟测试话题", "content": "有人吗"},
            expect=201,
        )
        did = data["data"]["id"]
        reply = teacher.post(
            f"/api/discussions/{did}/replies", {"content": "在的"}, expect=201
        )
        assert reply["ok"]
        detail = student.get(f"/api/discussions/{did}")
        assert detail["data"]["reply_count"] >= 1

    def t_notifications():
        data = student.get("/api/notifications")
        assert data["data"]["total"] >= 0
        unread = student.get("/api/notifications/unread-count")
        assert "count" in unread["data"]

    def t_upload_resource():
        boundary = "----eduflowtest"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="title"\r\n\r\n'
            "测试文件\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="hello.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            "hello eduflow\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        data = teacher.request(
            "POST",
            f"/api/courses/{state['course_id']}/resources",
            raw=body,
            content_type=f"multipart/form-data; boundary={boundary}",
            expect=201,
        )
        assert data["data"]["filename"] == "hello.txt"
        rid = data["data"]["id"]
        listing = student.get(f"/api/courses/{state['course_id']}/resources")
        assert listing["data"][0]["id"] == rid

    def t_student_dashboard():
        data = student.get("/api/dashboard")
        assert "pending_assignments" in data["data"]

    def t_teacher_overview():
        data = teacher.get("/api/teacher/overview")
        assert data["data"]["class_count"] >= 1

    def t_audit():
        data = admin.get("/api/audit-logs")
        assert data["data"]["total"] >= 1

    def t_routes():
        data = admin.get("/api/routes")
        assert data["data"]["total"] > 50

    tests = [
        ("健康检查", t_health),
        ("元信息", t_meta),
        ("管理员登录", t_login_admin),
        ("教师登录", t_login_teacher),
        ("学生登录", t_login_student),
        ("当前用户", t_me),
        ("错误密码被拒", t_bad_login),
        ("未登录被拦", t_unauthorized),
        ("管理员看板", t_admin_dashboard),
        ("用户列表", t_user_list),
        ("创建课程", t_create_course),
        ("课程详情含教学班", t_course_classes),
        ("学生加入教学班", t_join_class),
        ("创建章节", t_create_chapter),
        ("创建任务点", t_create_chapter_task),
        ("学生看章节任务点", t_student_chapters),
        ("学生上报进度", t_report_progress),
        ("教师看学习进度", t_teacher_progress),
        ("发布作业", t_create_assignment),
        ("学生作业列表", t_student_assignments),
        ("提交作业", t_submit_assignment),
        ("教师查看提交", t_list_submissions),
        ("批改作业", t_grade_submission),
        ("创建测验", t_create_quiz),
        ("学生开始测验", t_start_quiz),
        ("学生交卷并判分", t_submit_quiz),
        ("发起签到", t_create_attendance),
        ("学生签到", t_check_in),
        ("配置成绩权重", t_grade_rule),
        ("查看成绩册", t_gradebook),
        ("录入期末成绩", t_set_final),
        ("学生成绩单", t_transcript),
        ("讨论区", t_discussion),
        ("通知", t_notifications),
        ("上传资料", t_upload_resource),
        ("学生看板", t_student_dashboard),
        ("教师工作台", t_teacher_overview),
        ("审计日志", t_audit),
        ("接口清单", t_routes),
    ]

    print(f"共 {len(tests)} 项测试\n")
    for name, func in tests:
        check(name, func)

    server.stop()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / {len(tests)}，失败 {len(FAILED)}")
    if FAILED:
        print("\n失败项：")
        for name, error in FAILED:
            print(f"  - {name}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

