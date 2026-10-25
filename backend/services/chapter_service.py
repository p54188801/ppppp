"""章节任务点与学习进度。

学习通的课程内容以「章节 -> 任务点」组织：教师建章节、往章节里放任务点
（资料、作业、测验、讨论或纯图文），学生逐个完成，系统记录完成度并汇总
成课程学习进度。

设计要点：
- 章节挂在课程上，一门课的所有教学班共用同一套章节；
- 任务点通过 resource_id / quiz_id / assignment_id 关联到已有内容，不复制一份；
- task_progress 只在学生真正开始后才写记录，没有记录即「未开始」；
- 学生只能给自己上报进度，教师只能看自己课程的完成率。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.core import clock, permissions, validators
from backend.core.errors import ForbiddenError, NotFoundError, ValidationError
from backend.repositories.assignments import AssignmentRepository
from backend.repositories.audit import AuditRepository
from backend.repositories.chapters import (
    ChapterRepository,
    TaskProgressRepository,
    TaskRepository,
)
from backend.repositories.content import ResourceRepository
from backend.repositories.courses import ClassRepository, CourseRepository, EnrollmentRepository
from backend.repositories.quizzes import QuizRepository

chapter_repo = ChapterRepository()
task_repo = TaskRepository()
progress_repo = TaskProgressRepository()
course_repo = CourseRepository()
class_repo = ClassRepository()
enroll_repo = EnrollmentRepository()
resource_repo = ResourceRepository()
assignment_repo = AssignmentRepository()
quiz_repo = QuizRepository()
audit_repo = AuditRepository()

TASK_TYPES = ("material", "assignment", "quiz", "discussion", "text")
TASK_TYPE_LABELS = {
    "material": "资料",
    "assignment": "作业",
    "quiz": "测验",
    "discussion": "讨论",
    "text": "图文",
}

# 任务点类型 -> 允许关联的字段
TYPE_LINK_FIELDS = {
    "material": "resource_id",
    "assignment": "assignment_id",
    "quiz": "quiz_id",
}

_MISSING = object()


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _course_or_fail(course_id: int) -> dict[str, Any]:
    course = course_repo.detail(course_id)
    if course is None:
        raise NotFoundError("课程不存在")
    return course


def _chapter_or_fail(chapter_id: int) -> dict[str, Any]:
    chapter = chapter_repo.detail(chapter_id)
    if chapter is None:
        raise NotFoundError("章节不存在")
    return chapter


def _task_or_fail(task_id: int, message: str = "任务点不存在") -> dict[str, Any]:
    task = task_repo.detail(task_id)
    if task is None:
        raise NotFoundError(message)
    return task


def _assert_can_view(viewer: dict[str, Any], course: dict[str, Any]) -> bool:
    """校验课程可见性，返回学生是否已选课。"""
    class_ids = {int(item["id"]) for item in class_repo.of_course(int(course["id"]))}
    enrolled = bool(
        class_ids & set(enroll_repo.class_ids_of_student(int(viewer["id"])))
    )
    permissions.assert_can_view_course(viewer, course, enrolled=enrolled)
    return enrolled


def _assert_enrolled(student: dict[str, Any], course_id: int) -> None:
    class_ids = {int(item["id"]) for item in class_repo.of_course(course_id)}
    if not (class_ids & set(enroll_repo.class_ids_of_student(int(student["id"])))):
        raise ForbiddenError("你还没有加入该课程的教学班")


def _percent(done: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(min(100.0, done * 100.0 / total), 1)


def _progress_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "status": row.get("status") or "in_progress",
        "progress": int(row.get("progress") or 0),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "updated_at": row.get("updated_at"),
    }


def _task_public(task: dict[str, Any]) -> dict[str, Any]:
    """任务点的公共字段（去掉仅统计需要的列）。"""
    return {
        "id": int(task["id"]),
        "chapter_id": int(task["chapter_id"]),
        "type": task["type"],
        "type_label": TASK_TYPE_LABELS.get(task["type"], task["type"]),
        "title": task["title"],
        "description": task.get("description") or "",
        "duration": int(task.get("duration") or 0),
        "required": bool(task.get("required", 1)),
        "resource_id": task.get("resource_id"),
        "resource_title": task.get("resource_title"),
        "resource_filename": task.get("resource_filename"),
        "quiz_id": task.get("quiz_id"),
        "quiz_title": task.get("quiz_title"),
        "assignment_id": task.get("assignment_id"),
        "assignment_title": task.get("assignment_title"),
        "order_no": int(task.get("order_no") or 0),
    }


# ---------------------------------------------------------------------------
# 章节
# ---------------------------------------------------------------------------


def list_chapters(viewer: dict[str, Any], course_id: int) -> dict[str, Any]:
    """课程章节树 + 任务点，学生带自己的进度，教师带完成率。"""
    course = _course_or_fail(course_id)
    _assert_can_view(viewer, course)

    chapters = chapter_repo.list_by_course(course_id)
    tasks = task_repo.list_by_course(course_id)
    grouped: dict[int, list[dict[str, Any]]] = {int(ch["id"]): [] for ch in chapters}
    for task in tasks:
        grouped.setdefault(int(task["chapter_id"]), []).append(task)

    is_student = viewer["role"] == permissions.ROLE_STUDENT
    viewer_id = int(viewer["id"])
    students = [] if is_student else chapter_repo.students_of_course(course_id)
    student_count = len(students)
    student_ids = {int(row["student_id"]) for row in students}

    my_progress: dict[int, dict[str, Any]] = {}
    completed_by_task: dict[int, int] = defaultdict(int)
    for row in progress_repo.list_by_course(course_id):
        task_id = int(row["task_id"])
        student_id = int(row["student_id"])
        if is_student and student_id == viewer_id:
            my_progress[task_id] = row
        if student_id in student_ids and row["status"] == "completed":
            completed_by_task[task_id] += 1

    items: list[dict[str, Any]] = []
    for chapter in chapters:
        chapter_id = int(chapter["id"])
        chapter_tasks: list[dict[str, Any]] = []
        completed = 0
        progress_sum = 0
        for task in grouped.get(chapter_id, []):
            task_id = int(task["id"])
            item = _task_public(task)
            if is_student:
                row = my_progress.get(task_id)
                item["my_progress"] = _progress_payload(row)
                item["progress"] = int(row.get("progress") or 0) if row else 0
                item["completed"] = bool(row and row["status"] == "completed")
                progress_sum += item["progress"]
                if item["completed"]:
                    completed += 1
            else:
                done = completed_by_task.get(task_id, 0)
                item["completed_count"] = done
                item["student_count"] = student_count
                item["progress"] = _percent(done, student_count)
                completed += done
            chapter_tasks.append(item)

        total = len(chapter_tasks)
        if is_student:
            # 学生视角看「学习进度」：进行中的任务按百分比计入，
            # 而不是只有 100% 才算数。
            progress = round(progress_sum / total, 1) if total else 0.0
        else:
            progress = _percent(completed, total * student_count)

        items.append(
            {
                "id": chapter_id,
                "course_id": int(chapter["course_id"]),
                "title": chapter["title"],
                "description": chapter.get("description") or "",
                "order_no": int(chapter.get("order_no") or 0),
                "task_count": len(chapter_tasks),
                "completed_count": completed,
                "progress": progress,
                "student_count": student_count,
                "tasks": chapter_tasks,
            }
        )

    total_tasks = len(tasks)
    if is_student:
        completed_total = sum(
            1
            for row in my_progress.values()
            if row.get("status") == "completed"
        )
        progress_sum = sum(
            int(row.get("progress") or 0)
            for row in my_progress.values()
        )
        summary_progress = (
            round(progress_sum / total_tasks, 1) if total_tasks else 0.0
        )
    else:
        completed_total = sum(completed_by_task.values())
        summary_progress = _percent(completed_total, total_tasks * student_count)

    return {
        "course_id": course_id,
        "course_name": course["name"],
        "items": items,
        "summary": {
            "chapter_count": len(items),
            "task_count": total_tasks,
            "completed_count": completed_total,
            "progress": summary_progress,
            "student_count": student_count,
        },
    }


def create_chapter(operator: dict[str, Any], course_id: int,
                   payload: dict[str, Any]) -> dict[str, Any]:
    course = _course_or_fail(course_id)
    permissions.assert_can_manage_course(operator, course)

    title = validators.required_str(payload, "title", min_len=2, max_len=120)
    description = validators.optional_str(payload, "description", "", max_len=2000)
    order_no = validators.optional_int(
        payload, "order_no", chapter_repo.next_order_no(course_id), min_value=1,
        max_value=9999,
    )
    chapter_id = chapter_repo.insert(
        {
            "course_id": course_id,
            "title": title,
            "description": description,
            "order_no": int(order_no or 1),
        }
    )
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="create_chapter",
        entity="chapter",
        entity_id=chapter_id,
        detail=f"{course['name']} / {title}",
    )
    return chapter_repo.detail(chapter_id) or {}


def update_chapter(operator: dict[str, Any], chapter_id: int,
                   payload: dict[str, Any]) -> dict[str, Any]:
    chapter = _chapter_or_fail(chapter_id)
    course = _course_or_fail(int(chapter["course_id"]))
    permissions.assert_can_manage_course(operator, course)

    updates: dict[str, Any] = {}
    if "title" in payload:
        updates["title"] = validators.required_str(payload, "title", min_len=2, max_len=120)
    if "description" in payload:
        updates["description"] = validators.optional_str(
            payload, "description", "", max_len=2000
        )
    if "order_no" in payload:
        updates["order_no"] = validators.required_int(
            payload, "order_no", min_value=1, max_value=9999
        )
    if updates:
        chapter_repo.update(chapter_id, updates)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="update_chapter",
            entity="chapter",
            entity_id=chapter_id,
            detail=f"更新章节字段：{', '.join(updates)}",
        )
    return chapter_repo.detail(chapter_id) or {}


def delete_chapter(operator: dict[str, Any], chapter_id: int) -> None:
    chapter = _chapter_or_fail(chapter_id)
    course = _course_or_fail(int(chapter["course_id"]))
    permissions.assert_can_manage_course(operator, course)
    chapter_repo.delete(chapter_id)  # 任务点与进度由外键级联删除
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="delete_chapter",
        entity="chapter",
        entity_id=chapter_id,
        detail=chapter.get("title", ""),
    )


# ---------------------------------------------------------------------------
# 任务点
# ---------------------------------------------------------------------------


def _link_int(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        return _MISSING
    raw = payload[key]
    if raw in (None, "", 0, "0"):
        return None
    return validators.to_int(raw, key, min_value=1)


def _validate_resource(course_id: int, resource_id: int) -> None:
    row = resource_repo.find(resource_id)
    if row is None:
        raise NotFoundError("关联的资料不存在")
    if int(row["course_id"]) != course_id:
        raise ValidationError("关联的资料不属于本课程")


def _validate_assignment(course_id: int, assignment_id: int) -> None:
    row = assignment_repo.detail(assignment_id)
    if row is None:
        raise NotFoundError("关联的作业不存在")
    if int(row["course_id"]) != course_id:
        raise ValidationError("关联的作业不属于本课程")


def _validate_quiz(course_id: int, quiz_id: int) -> None:
    row = quiz_repo.detail(quiz_id)
    if row is None:
        raise NotFoundError("关联的测验不存在")
    if int(row["course_id"]) != course_id:
        raise ValidationError("关联的测验不属于本课程")


def _task_fields(payload: dict[str, Any], course_id: int,
                 existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """把请求体规范化成可写字段，同时校验关联内容归属。"""
    if "type" in payload:
        task_type = validators.ensure_enum(
            str(payload["type"]).strip(), TASK_TYPES, "任务点类型"
        )
    elif existing:
        task_type = str(existing["type"])
    else:
        task_type = "material"

    fields: dict[str, Any] = {"type": task_type}
    if "title" in payload or not existing:
        fields["title"] = validators.required_str(payload, "title", min_len=2, max_len=120)
    if "description" in payload:
        fields["description"] = validators.optional_str(
            payload, "description", "", max_len=2000
        )
    if "duration" in payload:
        fields["duration"] = validators.optional_int(
            payload, "duration", 0, min_value=0, max_value=600
        )
    if "required" in payload:
        fields["required"] = 1 if validators.to_bool(payload.get("required"), True) else 0
    if "order_no" in payload:
        fields["order_no"] = validators.required_int(
            payload, "order_no", min_value=1, max_value=9999
        )

    allowed = TYPE_LINK_FIELDS.get(task_type)
    type_changed = bool(existing and str(existing["type"]) != task_type)
    for key in ("resource_id", "assignment_id", "quiz_id"):
        raw = _link_int(payload, key)
        if key == allowed:
            if raw is _MISSING:
                if not existing or type_changed:
                    fields[key] = None
                continue
            if raw is None:
                fields[key] = None
                continue
            if key == "resource_id":
                _validate_resource(course_id, int(raw))
            elif key == "assignment_id":
                _validate_assignment(course_id, int(raw))
            else:
                _validate_quiz(course_id, int(raw))
            fields[key] = int(raw)
        else:
            if raw not in (_MISSING, None):
                raise ValidationError("任务点类型与关联内容不匹配")
            if type_changed:
                fields[key] = None
    return fields


def create_task(operator: dict[str, Any], chapter_id: int,
                payload: dict[str, Any]) -> dict[str, Any]:
    chapter = _chapter_or_fail(chapter_id)
    course = _course_or_fail(int(chapter["course_id"]))
    permissions.assert_can_manage_course(operator, course)

    fields = _task_fields(payload, int(chapter["course_id"]))
    fields["chapter_id"] = chapter_id
    fields.setdefault("order_no", task_repo.next_order_no(chapter_id))
    task_id = task_repo.insert(fields)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="create_task",
        entity="task",
        entity_id=task_id,
        detail=f"{chapter['title']} / {fields['title']}",
    )
    return _task_public(task_repo.detail(task_id) or {})


def update_task(operator: dict[str, Any], task_id: int,
                payload: dict[str, Any]) -> dict[str, Any]:
    task = _task_or_fail(task_id)
    course = _course_or_fail(int(task["course_id"]))
    permissions.assert_can_manage_course(operator, course)

    fields = _task_fields(payload, int(task["course_id"]), existing=task)
    changes = {
        key: value for key, value in fields.items() if task.get(key) != value
    }
    if changes:
        task_repo.update(task_id, changes)
        audit_repo.log(
            user_id=int(operator["id"]),
            username=operator["username"],
            action="update_task",
            entity="task",
            entity_id=task_id,
            detail=f"更新任务点字段：{', '.join(changes)}",
        )
    return _task_public(task_repo.detail(task_id) or {})


def delete_task(operator: dict[str, Any], task_id: int) -> None:
    task = _task_or_fail(task_id)
    course = _course_or_fail(int(task["course_id"]))
    permissions.assert_can_manage_course(operator, course)
    task_repo.delete(task_id)
    audit_repo.log(
        user_id=int(operator["id"]),
        username=operator["username"],
        action="delete_task",
        entity="task",
        entity_id=task_id,
        detail=task.get("title", ""),
    )


# ---------------------------------------------------------------------------
# 学习进度
# ---------------------------------------------------------------------------


def _student_course_stats(course_id: int,
                          student_id: int) -> dict[str, Any]:
    """某个学生在某门课上的任务进度快照。"""
    tasks = task_repo.list_by_course(course_id)
    rows = {
        int(row["task_id"]): row
        for row in progress_repo.list_by_student_course(student_id, course_id)
    }
    chapter_tasks: dict[int, list[int]] = defaultdict(list)
    for task in tasks:
        chapter_tasks[int(task["chapter_id"])].append(int(task["id"]))

    chapters: dict[int, dict[str, Any]] = {}
    for chapter_id, task_ids in chapter_tasks.items():
        done = sum(
            1 for task_id in task_ids
            if rows.get(task_id, {}).get("status") == "completed"
        )
        progress_sum = sum(
            int(rows.get(task_id, {}).get("progress") or 0)
            for task_id in task_ids
        )
        chapters[chapter_id] = {
            "task_count": len(task_ids),
            "completed_count": done,
            "progress": (
                round(progress_sum / len(task_ids), 1) if task_ids else 0.0
            ),
        }
    completed_total = sum(
        1 for row in rows.values() if row.get("status") == "completed"
    )
    progress_sum = sum(int(row.get("progress") or 0) for row in rows.values())
    return {
        "task_count": len(tasks),
        "completed_count": completed_total,
        "progress": round(progress_sum / len(tasks), 1) if tasks else 0.0,
        "chapters": chapters,
    }


def report_progress(student: dict[str, Any], task_id: int,
                    payload: dict[str, Any]) -> dict[str, Any]:
    """学生上报任务点进度；100 即完成，会自动写入完成时间。"""
    permissions.require_role(student, permissions.ROLE_STUDENT)
    task = _task_or_fail(task_id)
    course_id = int(task["course_id"])
    _assert_enrolled(student, course_id)

    existing = progress_repo.get(task_id, int(student["id"]))
    raw_status = payload.get("status")
    status = None
    if raw_status not in (None, ""):
        status = validators.ensure_enum(
            str(raw_status).strip(), ("in_progress", "completed"), "进度状态"
        )

    has_progress = "progress" in payload and payload["progress"] not in (None, "")
    progress = (
        validators.to_int(payload["progress"], "学习进度", min_value=0, max_value=100)
        if has_progress
        else None
    )
    if progress is None and status is None:
        raise ValidationError("请提供 progress 或 status")

    if status == "completed":
        progress = 100
    elif progress == 100:
        status = "completed"
    elif progress is not None:
        status = "in_progress"
    else:  # status == in_progress 且没给具体数值：至少推进到 10%
        progress = max(int(existing["progress"]) if existing else 0, 10)

    now = clock.now_iso()
    started_at = None
    if existing and existing.get("started_at"):
        started_at = existing["started_at"]
    if not started_at:
        started_at = now
    if progress >= 100:
        # 重复点「完成」不应刷新首次完成时间
        if (
            existing
            and existing.get("status") == "completed"
            and existing.get("finished_at")
        ):
            finished_at = existing["finished_at"]
        else:
            finished_at = now
    else:
        finished_at = None

    row = progress_repo.save(
        task_id,
        int(student["id"]),
        {
            "status": status,
            "progress": progress,
            "started_at": started_at,
            "finished_at": finished_at,
        },
    )

    newly_completed = (
        status == "completed"
        and (not existing or existing.get("status") != "completed")
    )
    if newly_completed:
        audit_repo.log(
            user_id=int(student["id"]),
            username=student["username"],
            action="complete_task",
            entity="task",
            entity_id=task_id,
            detail=task.get("title", ""),
        )

    stats = _student_course_stats(course_id, int(student["id"]))
    chapter = stats["chapters"].get(int(task["chapter_id"]), {})
    return {
        "task_id": task_id,
        "status": row.get("status"),
        "progress": int(row.get("progress") or 0),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "chapter": {
            "id": int(task["chapter_id"]),
            "task_count": chapter.get("task_count", 0),
            "completed_count": chapter.get("completed_count", 0),
            "progress": chapter.get("progress", 0.0),
        },
        "course": {
            "task_count": stats["task_count"],
            "completed_count": stats["completed_count"],
            "progress": stats["progress"],
        },
    }


def course_progress(viewer: dict[str, Any], course_id: int) -> dict[str, Any]:
    """教师视角：整门课的任务点完成率与学生明细。"""
    course = _course_or_fail(course_id)
    permissions.assert_can_manage_course(viewer, course)

    chapters = chapter_repo.list_by_course(course_id)
    tasks = task_repo.list_by_course(course_id)
    students = chapter_repo.students_of_course(course_id)
    student_count = len(students)
    student_ids = {int(row["student_id"]) for row in students}

    rows = progress_repo.list_by_course(course_id)
    completed_by_task: dict[int, int] = defaultdict(int)
    by_student: dict[int, dict[str, Any]] = {}
    completed_pairs: set[tuple[int, int]] = set()
    for row in rows:
        student_id = int(row["student_id"])
        if student_id not in student_ids:
            continue
        record = by_student.setdefault(
            student_id, {"completed": 0, "last_active_at": None}
        )
        record["last_active_at"] = max(
            filter(None, [record["last_active_at"], row.get("updated_at")]),
            default=None,
        )
        if row["status"] == "completed":
            record["completed"] += 1
            completed_by_task[int(row["task_id"])] += 1
            completed_pairs.add((student_id, int(row["task_id"])))

    total_tasks = len(tasks)
    student_rows = []
    for student in students:
        student_id = int(student["student_id"])
        record = by_student.get(student_id, {"completed": 0, "last_active_at": None})
        student_rows.append(
            {
                "student_id": student_id,
                "real_name": student["real_name"],
                "number": student.get("number"),
                "class_name": student.get("class_name"),
                "completed_count": record["completed"],
                "task_count": total_tasks,
                "progress": _percent(record["completed"], total_tasks),
                "last_active_at": record["last_active_at"],
            }
        )

    chapter_rows = []
    for chapter in chapters:
        chapter_task_ids = [
            int(task["id"]) for task in tasks
            if int(task["chapter_id"]) == int(chapter["id"])
        ]
        done = sum(completed_by_task.get(task_id, 0) for task_id in chapter_task_ids)
        total = len(chapter_task_ids)
        completed_students = sum(
            1
            for student in students
            if chapter_task_ids
            and all(
                (int(student["student_id"]), task_id) in completed_pairs
                for task_id in chapter_task_ids
            )
        )
        chapter_rows.append(
            {
                "id": int(chapter["id"]),
                "title": chapter["title"],
                "task_count": total,
                "completed_count": done,
                "progress": _percent(done, total * student_count),
                "completed_students": completed_students,
            }
        )

    avg_progress = (
        round(sum(row["progress"] for row in student_rows) / len(student_rows), 1)
        if student_rows
        else 0.0
    )
    return {
        "course_id": course_id,
        "course_name": course["name"],
        "task_count": total_tasks,
        "student_count": student_count,
        "tasks": [
            {
                "id": int(task["id"]),
                "chapter_id": int(task["chapter_id"]),
                "chapter_title": task.get("chapter_title"),
                "title": task["title"],
                "type": task["type"],
                "type_label": TASK_TYPE_LABELS.get(task["type"], task["type"]),
            }
            for task in tasks
        ],
        "chapters": chapter_rows,
        "students": student_rows,
        "summary": {
            "avg_progress": avg_progress,
            "completed_students": sum(
                1 for row in student_rows if row["progress"] >= 100
            ),
            "student_count": student_count,
            "task_count": total_tasks,
        },
    }


def my_learning(student: dict[str, Any]) -> list[dict[str, Any]]:
    """学生视角：我在每门课上的章节任务完成情况（首页/课程页用）。"""
    permissions.require_role(student, permissions.ROLE_STUDENT)
    student_id = int(student["id"])
    seen: set[int] = set()
    result: list[dict[str, Any]] = []
    for row in course_repo.of_student(student_id):
        course_id = int(row["id"])
        if course_id in seen:
            continue
        seen.add(course_id)
        stats = _student_course_stats(course_id, student_id)
        result.append(
            {
                "course_id": course_id,
                "code": row.get("code"),
                "name": row.get("name"),
                "teacher_name": row.get("teacher_name"),
                "class_name": row.get("class_name"),
                "term": row.get("term"),
                "chapter_count": chapter_repo.count(
                    "course_id = ?", (course_id,)
                ),
                "task_count": stats["task_count"],
                "completed_count": stats["completed_count"],
                "progress": stats["progress"],
            }
        )
    result.sort(key=lambda item: (-item["progress"], item["name"] or ""))
    return result
