"""演示数据初始化。

生成一套完整可演示的数据：管理员、教师、学生、课程、教学班、
作业与提交、测验与答卷、签到与记录、讨论、通知、成绩。

执行：python -m backend.cli seed
幂等：检测到 admin 账号已存在时直接跳过，不会重复灌数据。
"""

from __future__ import annotations

import json
import random
from typing import Any

from backend.core import clock, ids, security
from backend.db import connection
from backend.db import migrations
from backend.repositories.assignments import AssignmentRepository, SubmissionRepository
from backend.repositories.attendance import AttendanceRecordRepository, AttendanceSessionRepository
from backend.repositories.content import (
    DiscussionRepository,
    NotificationRepository,
    ReplyRepository,
    ResourceRepository,
)
from backend.repositories.courses import ClassRepository, CourseRepository, EnrollmentRepository
from backend.repositories.grades import GradeItemRepository, GradeRuleRepository
from backend.repositories.quizzes import AttemptRepository, QuestionRepository, QuizRepository
from backend.repositories.users import UserRepository

user_repo = UserRepository()
course_repo = CourseRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
assignment_repo = AssignmentRepository()
submission_repo = SubmissionRepository()
quiz_repo = QuizRepository()
question_repo = QuestionRepository()
attempt_repo = AttemptRepository()
session_repo = AttendanceSessionRepository()
record_repo = AttendanceRecordRepository()
resource_repo = ResourceRepository()
discussion_repo = DiscussionRepository()
reply_repo = ReplyRepository()
notification_repo = NotificationRepository()
rule_repo = GradeRuleRepository()
item_repo = GradeItemRepository()

DEFAULT_PASSWORD = "Eduflow@2026"

TEACHERS = [
    ("t1001", "张伟", "计算机学院", "教授"),
    ("t1002", "李娜", "数学学院", "副教授"),
    ("t1003", "王强", "外国语学院", "讲师"),
]

STUDENTS = [
    ("s2001", "陈晓", "计算机学院", "计科2301"),
    ("s2002", "刘洋", "计算机学院", "计科2301"),
    ("s2003", "赵敏", "计算机学院", "计科2302"),
    ("s2004", "孙浩", "计算机学院", "计科2302"),
    ("s2005", "周婷", "数学学院", "数学2301"),
    ("s2006", "吴磊", "数学学院", "数学2301"),
    ("s2007", "郑爽", "外国语学院", "英语2301"),
    ("s2008", "冯佳", "外国语学院", "英语2301"),
    ("s2009", "陆明", "计算机学院", "计科2301"),
    ("s2010", "何雨", "计算机学院", "计科2302"),
    ("s2011", "许静", "数学学院", "数学2301"),
    ("s2012", "邓超", "外国语学院", "英语2301"),
]

COURSES = [
    {
        "code": "CS101",
        "name": "数据结构与算法",
        "teacher": "t1001",
        "term": "2026-2027-1",
        "credits": 4,
        "hours": 64,
        "category": "必修",
        "description": "线性表、树、图、排序与查找，配套上机实验。",
    },
    {
        "code": "CS205",
        "name": "操作系统原理",
        "teacher": "t1001",
        "term": "2026-2027-1",
        "credits": 3,
        "hours": 48,
        "category": "必修",
        "description": "进程、内存、文件系统与并发控制。",
    },
    {
        "code": "MA102",
        "name": "高等数学（下）",
        "teacher": "t1002",
        "term": "2026-2027-1",
        "credits": 5,
        "hours": 80,
        "category": "必修",
        "description": "多元函数微积分、级数与常微分方程。",
    },
]

ASSIGNMENT_TEMPLATES = [
    ("第一次上机：顺序表实现", "用 C/C++ 实现顺序表的增删改查，提交源码与测试截图。", 7),
    ("第二次上机：二叉树遍历", "实现二叉树的先序、中序、后序遍历，并给出复杂度分析。", 10),
    ("课程小论文：算法复杂度思考", "结合一个真实问题，谈谈你对时间复杂度的理解，不少于 800 字。", 14),
]

QUIZ_QUESTIONS = [
    {
        "type": "single",
        "stem": "顺序表插入元素平均需要移动多少个元素？",
        "options": ["n", "n/2", "1", "log n"],
        "answer": "B",
        "score": 10,
        "analysis": "平均移动 n/2 个元素。",
    },
    {
        "type": "multi",
        "stem": "下列哪些属于线性结构？",
        "options": ["栈", "队列", "二叉树", " linked list"],
        "answer": "A,B,D",
        "score": 10,
        "analysis": "二叉树属于树形结构。",
    },
    {
        "type": "judge",
        "stem": "快速排序在最坏情况下的时间复杂度是 O(n log n)。",
        "options": [],
        "answer": "错",
        "score": 10,
        "analysis": "最坏是 O(n^2)。",
    },
    {
        "type": "fill",
        "stem": "二分查找要求数据必须______。",
        "options": [],
        "answer": "有序|排好序",
        "score": 10,
        "analysis": "必须有序。",
    },
    {
        "type": "essay",
        "stem": "简述哈希表的冲突解决方法。",
        "options": [],
        "answer": "",
        "score": 20,
        "analysis": "开放定址法、链地址法等。",
    },
]


def is_seeded() -> bool:
    return user_repo.by_username("admin") is not None


def seed(force: bool = False) -> dict[str, Any]:
    migrations.init_db()
    if is_seeded() and not force:
        return {"skipped": True, "reason": "已存在演示数据"}

    if force:
        migrations.reset_db()

    created: dict[str, int] = {}

    # ---------------------------------------------------------------- 用户
    admin_digest, admin_salt = security.hash_password(DEFAULT_PASSWORD)
    admin_id = user_repo.insert(
        {
            "username": "admin",
            "password_hash": admin_digest,
            "password_salt": admin_salt,
            "role": "admin",
            "real_name": "系统管理员",
            "number": "0001",
            "email": "admin@eduflow.local",
            "department": "教务处",
            "status": "active",
        }
    )
    created["admin"] = admin_id

    teacher_ids: dict[str, int] = {}
    for username, name, dept, title in TEACHERS:
        digest, salt = security.hash_password(DEFAULT_PASSWORD)
        teacher_ids[username] = user_repo.insert(
            {
                "username": username,
                "password_hash": digest,
                "password_salt": salt,
                "role": "teacher",
                "real_name": name,
                "number": username.upper(),
                "email": f"{username}@eduflow.local",
                "department": dept,
                "phone": f"1380000{random.randint(1000, 9999)}",
                "status": "active",
            }
        )
    created["teachers"] = len(teacher_ids)

    student_ids: list[int] = []
    for username, name, dept, clazz in STUDENTS:
        digest, salt = security.hash_password(DEFAULT_PASSWORD)
        student_ids.append(
            user_repo.insert(
                {
                    "username": username,
                    "password_hash": digest,
                    "password_salt": salt,
                    "role": "student",
                    "real_name": name,
                    "number": username.upper(),
                    "email": f"{username}@eduflow.local",
                    "department": dept,
                    "class_name": clazz,
                    "status": "active",
                }
            )
        )
    created["students"] = len(student_ids)

    # ---------------------------------------------------------------- 课程
    course_ids: list[int] = []
    class_ids: list[int] = []
    for index, item in enumerate(COURSES):
        teacher_id = teacher_ids[item["teacher"]]
        course_id = course_repo.insert(
            {
                "code": item["code"],
                "name": item["name"],
                "teacher_id": teacher_id,
                "term": item["term"],
                "credits": item["credits"],
                "hours": item["hours"],
                "category": item["category"],
                "description": item["description"],
                "status": "active",
            }
        )
        course_ids.append(course_id)
        class_id = class_repo.insert(
            {
                "course_id": course_id,
                "name": f"{item['name']}-01班",
                "join_code": ids.new_join_code(),
                "semester": item["term"],
                "location": f"教学楼 A{index + 2}0{index + 1}",
                "schedule": "周一 3-4 节、周三 5-6 节",
                "capacity": 60,
            }
        )
        class_ids.append(class_id)
        if index == 0:
            second = class_repo.insert(
                {
                    "course_id": course_id,
                    "name": f"{item['name']}-02班",
                    "join_code": ids.new_join_code(),
                    "semester": item["term"],
                    "location": "教学楼 A301",
                    "schedule": "周二 1-2 节",
                    "capacity": 60,
                }
            )
            class_ids.append(second)
    created["courses"] = len(course_ids)
    created["classes"] = len(class_ids)

    # ---------------------------------------------------------------- 选课
    enroll_count = 0
    for class_id in class_ids:
        for student_id in student_ids:
            if random.random() < 0.65:
                enroll_repo.enroll(class_id, student_id, source="import")
                enroll_count += 1
    created["enrollments"] = enroll_count

    # ---------------------------------------------------------------- 作业
    assignment_ids: list[int] = []
    now = clock.utcnow()
    for order, (title, content, days) in enumerate(ASSIGNMENT_TEMPLATES):
        class_id = class_ids[0]
        deadline = clock.to_iso(clock.add_days(now, days - 3))
        assignment_id = assignment_repo.insert(
            {
                "class_id": class_id,
                "title": title,
                "content": content,
                "full_score": 100,
                "deadline": deadline,
                "allow_late": 1,
                "late_penalty": 0.1,
                "status": "published",
                "created_by": teacher_ids["t1001"],
            }
        )
        assignment_ids.append(assignment_id)

    # 提交与批改
    submitted = graded = 0
    for assignment_id in assignment_ids[:2]:
        for student_id in student_ids:
            if not enroll_repo.is_enrolled(class_ids[0], student_id):
                continue
            if random.random() > 0.75:
                continue
            submission_id = submission_repo.insert(
                {
                    "assignment_id": assignment_id,
                    "student_id": student_id,
                    "content": "老师好，这是我的作业，详见附件。",
                    "status": "submitted",
                    "submitted_at": clock.to_iso(clock.add_days(now, -random.randint(1, 3))),
                }
            )
            submitted += 1
            if random.random() < 0.7:
                submission_repo.grade(
                    submission_id,
                    round(random.uniform(65, 98), 1),
                    random.choice(["完成得不错", "思路清晰，注意边界条件", "代码规范有待加强"]),
                    teacher_ids["t1001"],
                )
                graded += 1
    created["submissions"] = submitted
    created["graded"] = graded

    # ---------------------------------------------------------------- 测验
    quiz_id = quiz_repo.insert(
        {
            "class_id": class_ids[0],
            "title": "第一章 线性表 随堂测验",
            "description": "限时 30 分钟，共 5 题。",
            "start_at": clock.to_iso(clock.add_days(now, -2)),
            "end_at": clock.to_iso(clock.add_days(now, 20)),
            "duration": 30,
            "total_score": 60,
            "shuffle": 0,
            "show_answer": 1,
            "status": "published",
            "created_by": teacher_ids["t1001"],
        }
    )
    questions = []
    for index, item in enumerate(QUIZ_QUESTIONS):
        questions.append(
            {
                "type": item["type"],
                "stem": item["stem"],
                "options": json.dumps(item["options"], ensure_ascii=False) if item["options"] else None,
                "answer": item["answer"],
                "analysis": item["analysis"],
                "score": item["score"],
                "order_no": index,
            }
        )
    question_repo.replace_for_quiz(quiz_id, questions)

    attempt_count = 0
    for student_id in student_ids:
        if not enroll_repo.is_enrolled(class_ids[0], student_id):
            continue
        if random.random() > 0.6:
            continue
        attempt_id = attempt_repo.start(quiz_id, student_id)
        score = round(random.uniform(20, 58), 1)
        attempt_repo.submit(attempt_id, score, json.dumps({}))
        attempt_count += 1
    created["quiz_attempts"] = attempt_count

    # ---------------------------------------------------------------- 签到
    att_count = 0
    for offset in range(3):
        start = clock.add_days(now, -7 * (offset + 1))
        session_id = session_repo.insert(
            {
                "class_id": class_ids[0],
                "title": f"第{3 - offset}周 课堂签到",
                "method": "code",
                "code": ids.new_attendance_code(),
                "start_at": clock.to_iso(start),
                "end_at": clock.to_iso(clock.add_minutes(start, 10)),
                "status": "closed",
                "created_by": teacher_ids["t1001"],
            }
        )
        for student_id in student_ids:
            if not enroll_repo.is_enrolled(class_ids[0], student_id):
                continue
            status = random.choices(
                ["present", "late", "absent", "leave"], weights=[80, 10, 7, 3]
            )[0]
            record_repo.mark(session_id, student_id, status, "")
            att_count += 1
    created["attendance_records"] = att_count

    # ---------------------------------------------------------------- 资料
    learn_resource = resource_repo.insert(
        {
            "course_id": course_ids[0],
            "title": "课程大纲",
            "description": "本学期的教学安排与考核方式",
            "filename": "syllabus.txt",
            "stored_name": "",
            "size": 0,
            "mime": "text/plain",
            "category": "参考资料",
            "uploader_id": teacher_ids["t1001"],
        }
    )
    created["resources"] = 1

    # ---------------------------------------------------------------- 讨论
    discussion_id = discussion_repo.insert(
        {
            "course_id": course_ids[0],
            "title": "关于第二次上机的疑问",
            "content": "二叉树的非递归遍历该怎么写？有大佬能讲讲思路吗？",
            "author_id": student_ids[0],
            "pinned": 1,
        }
    )
    reply_repo.insert(
        {
            "discussion_id": discussion_id,
            "author_id": teacher_ids["t1001"],
            "content": "核心是用栈模拟递归调用，先压左孩子，回溯时再访问根节点。",
        }
    )
    created["discussions"] = 1

    # ---------------------------------------------------------------- 成绩
    for class_id in class_ids[:1]:
        rule_repo.save(
            class_id,
            {
                "assignment_weight": 0.30,
                "quiz_weight": 0.30,
                "attendance_weight": 0.20,
                "final_weight": 0.20,
                "pass_score": 60,
            },
        )
        for student_id in student_ids:
            if not enroll_repo.is_enrolled(class_id, student_id):
                continue
            item_repo.upsert(
                class_id,
                student_id,
                {
                    "final_score": round(random.uniform(55, 95), 1),
                    "bonus": 0,
                    "remark": "",
                },
            )

    # ---------------------------------------------------------------- 通知
    for user_id in [admin_id] + list(teacher_ids.values()) + student_ids[:5]:
        notification_repo.create(
            user_id,
            "欢迎使用 EduFlow",
            "这是演示数据，你可以自由新增课程、作业与测验。",
            category="system",
        )
    created["notifications"] = 6

    connection.get_connection().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"skipped": False, "created": created, "password": DEFAULT_PASSWORD}


def summary() -> dict[str, int]:
    return {
        "users": int(connection.scalar("SELECT COUNT(*) FROM users", default=0) or 0),
        "courses": int(connection.scalar("SELECT COUNT(*) FROM courses", default=0) or 0),
        "classes": int(connection.scalar("SELECT COUNT(*) FROM classes", default=0) or 0),
        "assignments": int(connection.scalar("SELECT COUNT(*) FROM assignments", default=0) or 0),
        "submissions": int(connection.scalar("SELECT COUNT(*) FROM submissions", default=0) or 0),
        "quizzes": int(connection.scalar("SELECT COUNT(*) FROM quizzes", default=0) or 0),
        "attendance": int(connection.scalar("SELECT COUNT(*) FROM attendance_records", default=0) or 0),
    }
