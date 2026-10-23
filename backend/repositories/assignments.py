"""作业与作业提交的数据访问层。"""

from __future__ import annotations

from typing import Any

from backend.core import clock
from backend.db import connection
from backend.repositories.base import BaseRepository


class AssignmentRepository(BaseRepository):
    table = "assignments"
    writable = (
        "class_id",
        "title",
        "content",
        "attachments",
        "full_score",
        "deadline",
        "allow_late",
        "late_penalty",
        "publish_at",
        "status",
        "created_by",
    )

    BASE_SELECT = """
        SELECT a.*,
               cl.name AS class_name,
               c.name  AS course_name,
               c.id    AS course_id,
               (SELECT COUNT(*) FROM submissions s
                 WHERE s.assignment_id = a.id) AS submission_count,
               (SELECT COUNT(*) FROM enrollments e
                 WHERE e.class_id = a.class_id AND e.status = 'active') AS student_total
          FROM assignments a
          JOIN classes cl ON cl.id = a.class_id
          JOIN courses c  ON c.id = cl.course_id
    """

    def detail(self, assignment_id: int) -> dict[str, Any] | None:
        return connection.query_one(
            self.BASE_SELECT + " WHERE a.id = ?", (assignment_id,)
        )

    def list_by_class(self, class_id: int, *, limit: int = 50,
                      offset: int = 0) -> list[dict[str, Any]]:
        return connection.query_all(
            self.BASE_SELECT + " WHERE a.class_id = ? ORDER BY a.created_at DESC LIMIT ? OFFSET ?",
            (class_id, limit, offset),
        )

    def list_for_student(self, student_id: int, *, status: str = "",
                         limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        sql = """
            SELECT a.*, cl.name AS class_name, c.name AS course_name,
                   s.status AS submission_status, s.score, s.id AS submission_id,
                   s.submitted_at
              FROM assignments a
              JOIN classes cl ON cl.id = a.class_id
              JOIN courses c  ON c.id = cl.course_id
              JOIN enrollments e ON e.class_id = a.class_id
                                AND e.student_id = ? AND e.status = 'active'
              LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
             WHERE a.status <> 'draft'
        """
        params: list[Any] = [student_id, student_id]
        if status == "pending":
            sql += " AND s.id IS NULL"
        elif status == "submitted":
            sql += " AND s.id IS NOT NULL"
        elif status == "graded":
            sql += " AND s.status = 'graded'"
        sql += " ORDER BY a.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return connection.query_all(sql, tuple(params))

    def count_for_student(self, student_id: int, status: str = "") -> int:
        sql = """
            SELECT COUNT(*)
              FROM assignments a
              JOIN enrollments e ON e.class_id = a.class_id
                                AND e.student_id = ? AND e.status = 'active'
              LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
             WHERE a.status <> 'draft'
        """
        params: list[Any] = [student_id, student_id]
        if status == "pending":
            sql += " AND s.id IS NULL"
        elif status == "submitted":
            sql += " AND s.id IS NOT NULL"
        elif status == "graded":
            sql += " AND s.status = 'graded'"
        return int(connection.scalar(sql, tuple(params), default=0) or 0)

    def upcoming_for_student(self, student_id: int, limit: int = 5) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT a.id, a.title, a.deadline, c.name AS course_name,
                      s.id AS submission_id
                 FROM assignments a
                 JOIN classes cl ON cl.id = a.class_id
                 JOIN courses c  ON c.id = cl.course_id
                 JOIN enrollments e ON e.class_id = a.class_id
                                   AND e.student_id = ? AND e.status = 'active'
                 LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
                WHERE a.status = 'published' AND s.id IS NULL
                  AND (a.deadline IS NULL OR a.deadline > ?)
                ORDER BY COALESCE(a.deadline, '9999') ASC
                LIMIT ?""",
            (student_id, student_id, clock.now_iso(), limit),
        )


class SubmissionRepository(BaseRepository):
    table = "submissions"
    writable = (
        "assignment_id",
        "student_id",
        "content",
        "attachments",
        "status",
        "score",
        "feedback",
        "graded_by",
        "graded_at",
        "is_late",
        "submitted_at",
    )

    def by_student(self, assignment_id: int, student_id: int) -> dict[str, Any] | None:
        return connection.query_one(
            """SELECT s.*, u.real_name AS student_name, u.number
                 FROM submissions s
                 JOIN users u ON u.id = s.student_id
                WHERE s.assignment_id = ? AND s.student_id = ?""",
            (assignment_id, student_id),
        )

    def list_by_assignment(self, assignment_id: int, *, status: str = "") -> list[dict[str, Any]]:
        sql = """
            SELECT s.*, u.real_name AS student_name, u.number, u.department
              FROM submissions s
              JOIN users u ON u.id = s.student_id
             WHERE s.assignment_id = ?
        """
        params: list[Any] = [assignment_id]
        if status:
            sql += " AND s.status = ?"
            params.append(status)
        sql += " ORDER BY s.submitted_at ASC"
        return connection.query_all(sql, tuple(params))

    def upsert_submission(self, assignment_id: int, student_id: int,
                          data: dict[str, Any]) -> int:
        existing = connection.query_one(
            "SELECT id FROM submissions WHERE assignment_id = ? AND student_id = ?",
            (assignment_id, student_id),
        )
        if existing:
            self.update(int(existing["id"]), data)
            return int(existing["id"])
        payload = dict(data)
        payload.update({"assignment_id": assignment_id, "student_id": student_id})
        return self.insert(payload)

    def grade(self, submission_id: int, score: float, feedback: str,
              grader_id: int) -> None:
        connection.execute(
            """UPDATE submissions
                  SET score = ?, feedback = ?, graded_by = ?, graded_at = ?,
                      status = 'graded', updated_at = ?
                WHERE id = ?""",
            (score, feedback, grader_id, clock.now_iso(), clock.now_iso(), submission_id),
        )

    def stats_for_assignment(self, assignment_id: int) -> dict[str, Any]:
        row = connection.query_one(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status = 'graded' THEN 1 ELSE 0 END) AS graded,
                      AVG(CASE WHEN score IS NOT NULL THEN score END) AS avg_score,
                      MAX(score) AS max_score,
                      MIN(score) AS min_score
                 FROM submissions WHERE assignment_id = ?""",
            (assignment_id,),
        ) or {}
        return {
            "total": int(row.get("total") or 0),
            "graded": int(row.get("graded") or 0),
            "avg_score": round(float(row.get("avg_score") or 0), 2),
            "max_score": float(row.get("max_score") or 0),
            "min_score": float(row.get("min_score") or 0),
        }

    def student_scores(self, class_id: int, student_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT a.id, a.title, a.full_score, s.score, s.status
                 FROM assignments a
                 LEFT JOIN submissions s
                   ON s.assignment_id = a.id AND s.student_id = ?
                WHERE a.class_id = ? AND a.status = 'published'
                ORDER BY a.created_at""",
            (student_id, class_id),
        )
