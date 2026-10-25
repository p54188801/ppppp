"""章节、任务点与学习进度的数据访问层。

章节属于课程（不是教学班），一个课程下的所有教学班共用同一套章节；
任务点通过可选的 resource_id / quiz_id / assignment_id 关联到具体内容，
学生每完成一个任务点就在 task_progress 里留一条记录。
"""

from __future__ import annotations

from typing import Any

from backend.db import connection
from backend.repositories.base import BaseRepository


class ChapterRepository(BaseRepository):
    table = "chapters"
    writable = ("course_id", "title", "description", "order_no")

    BASE_SELECT = """
        SELECT ch.*, c.name AS course_name, c.teacher_id,
               (SELECT COUNT(*) FROM tasks t WHERE t.chapter_id = ch.id) AS task_count
          FROM chapters ch
          JOIN courses c ON c.id = ch.course_id
    """

    def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            self.BASE_SELECT
            + " WHERE ch.course_id = ? ORDER BY ch.order_no, ch.id",
            (course_id,),
        )

    def detail(self, chapter_id: int) -> dict[str, Any] | None:
        return connection.query_one(
            self.BASE_SELECT + " WHERE ch.id = ?", (chapter_id,)
        )

    def next_order_no(self, course_id: int) -> int:
        value = connection.scalar(
            "SELECT MAX(order_no) FROM chapters WHERE course_id = ?",
            (course_id,),
            default=0,
        )
        return int(value or 0) + 1

    def students_of_course(self, course_id: int) -> list[dict[str, Any]]:
        """课程下所有教学班的学生（按学号排序，同一个学生只出现一次）。"""
        return connection.query_all(
            """SELECT u.id AS student_id, u.real_name, u.number, u.department,
                      MIN(cl.id) AS class_id, MIN(cl.name) AS class_name
                 FROM enrollments e
                 JOIN classes cl ON cl.id = e.class_id
                 JOIN users u ON u.id = e.student_id
                WHERE cl.course_id = ? AND e.status = 'active'
                GROUP BY u.id
                ORDER BY u.number, u.id""",
            (course_id,),
        )


class TaskRepository(BaseRepository):
    table = "tasks"
    writable = (
        "chapter_id",
        "type",
        "title",
        "description",
        "duration",
        "required",
        "resource_id",
        "quiz_id",
        "assignment_id",
        "order_no",
    )

    BASE_SELECT = """
        SELECT t.*, ch.course_id, ch.title AS chapter_title, ch.order_no AS chapter_order,
               r.title AS resource_title, r.filename AS resource_filename,
               q.title AS quiz_title, a.title AS assignment_title
          FROM tasks t
          JOIN chapters ch ON ch.id = t.chapter_id
          LEFT JOIN resources r   ON r.id = t.resource_id
          LEFT JOIN quizzes q     ON q.id = t.quiz_id
          LEFT JOIN assignments a ON a.id = t.assignment_id
    """

    def list_by_chapter(self, chapter_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            self.BASE_SELECT
            + " WHERE t.chapter_id = ? ORDER BY t.order_no, t.id",
            (chapter_id,),
        )

    def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            self.BASE_SELECT
            + """ WHERE ch.course_id = ?
                  ORDER BY ch.order_no, ch.id, t.order_no, t.id""",
            (course_id,),
        )

    def detail(self, task_id: int) -> dict[str, Any] | None:
        return connection.query_one(
            self.BASE_SELECT + " WHERE t.id = ?", (task_id,)
        )

    def next_order_no(self, chapter_id: int) -> int:
        value = connection.scalar(
            "SELECT MAX(order_no) FROM tasks WHERE chapter_id = ?",
            (chapter_id,),
            default=0,
        )
        return int(value or 0) + 1

    def course_of(self, task_id: int) -> int | None:
        value = connection.scalar(
            """SELECT ch.course_id FROM tasks t
                 JOIN chapters ch ON ch.id = t.chapter_id
                WHERE t.id = ?""",
            (task_id,),
        )
        return int(value) if value is not None else None


class TaskProgressRepository(BaseRepository):
    table = "task_progress"
    writable = (
        "task_id",
        "student_id",
        "status",
        "progress",
        "started_at",
        "finished_at",
    )

    def get(self, task_id: int, student_id: int) -> dict[str, Any] | None:
        return self.find_by(task_id=task_id, student_id=student_id)

    def list_by_course(self, course_id: int) -> list[dict[str, Any]]:
        """课程下所有学习进度，统计用；章节/任务信息一并带出。"""
        return connection.query_all(
            """SELECT tp.*, t.chapter_id, t.title AS task_title
                 FROM task_progress tp
                 JOIN tasks t ON t.id = tp.task_id
                 JOIN chapters ch ON ch.id = t.chapter_id
                WHERE ch.course_id = ?""",
            (course_id,),
        )

    def list_by_student_course(self, student_id: int,
                               course_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT tp.task_id, tp.status, tp.progress,
                      tp.started_at, tp.finished_at, tp.updated_at
                 FROM task_progress tp
                 JOIN tasks t ON t.id = tp.task_id
                 JOIN chapters ch ON ch.id = t.chapter_id
                WHERE ch.course_id = ? AND tp.student_id = ?""",
            (course_id, student_id),
        )

    def save(self, task_id: int, student_id: int,
             data: dict[str, Any]) -> dict[str, Any]:
        """有记录则更新，无记录则创建，返回最新一条。"""
        existing = self.get(task_id, student_id)
        if existing:
            self.update(int(existing["id"]), data)
        else:
            payload = dict(data)
            payload.update({"task_id": task_id, "student_id": student_id})
            self.insert(payload)
        return self.get(task_id, student_id) or {}
