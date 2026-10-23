"""课程、教学班、选课关系的数据访问层。"""

from __future__ import annotations

from typing import Any

from backend.core import clock
from backend.db import connection
from backend.repositories.base import BaseRepository


class CourseRepository(BaseRepository):
    table = "courses"
    writable = (
        "code",
        "name",
        "teacher_id",
        "term",
        "credits",
        "hours",
        "category",
        "cover",
        "description",
        "status",
    )

    BASE_SELECT = """
        SELECT c.*,
               u.real_name AS teacher_name,
               u.department AS teacher_department,
               (SELECT COUNT(*) FROM classes cl WHERE cl.course_id = c.id) AS class_count,
               (SELECT COUNT(*) FROM enrollments e
                  JOIN classes cl2 ON cl2.id = e.class_id
                 WHERE cl2.course_id = c.id AND e.status = 'active') AS student_count
          FROM courses c
          LEFT JOIN users u ON u.id = c.teacher_id
    """

    def detail(self, course_id: int) -> dict[str, Any] | None:
        return connection.query_one(
            self.BASE_SELECT + " WHERE c.id = ?", (course_id,)
        )

    def list_courses(
        self,
        *,
        teacher_id: int | None = None,
        term: str = "",
        keyword: str = "",
        status: str = "active",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = self.BASE_SELECT + " WHERE 1 = 1"
        params: list[Any] = []
        if teacher_id:
            sql += " AND c.teacher_id = ?"
            params.append(teacher_id)
        if term:
            sql += " AND c.term = ?"
            params.append(term)
        if status:
            sql += " AND c.status = ?"
            params.append(status)
        if keyword:
            sql += " AND (c.name LIKE ? OR c.code LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like])
        sql += " ORDER BY c.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return connection.query_all(sql, tuple(params))

    def count_courses(self, *, teacher_id: int | None = None, term: str = "",
                      keyword: str = "", status: str = "active") -> int:
        sql = "SELECT COUNT(*) FROM courses c WHERE 1 = 1"
        params: list[Any] = []
        if teacher_id:
            sql += " AND c.teacher_id = ?"
            params.append(teacher_id)
        if term:
            sql += " AND c.term = ?"
            params.append(term)
        if status:
            sql += " AND c.status = ?"
            params.append(status)
        if keyword:
            sql += " AND (c.name LIKE ? OR c.code LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like])
        return int(connection.scalar(sql, tuple(params), default=0) or 0)

    def by_code(self, code: str) -> dict[str, Any] | None:
        return self.find_by(code=code)

    def of_student(self, student_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """
            SELECT c.*, u.real_name AS teacher_name,
                   cl.id AS class_id, cl.name AS class_name, cl.join_code,
                   cl.schedule, cl.location,
                   (SELECT COUNT(*) FROM assignments a
                     WHERE a.class_id = cl.id AND a.status = 'published') AS assignment_count,
                   (SELECT COUNT(*) FROM attendance_sessions s
                     WHERE s.class_id = cl.id) AS attendance_count
              FROM enrollments e
              JOIN classes cl ON cl.id = e.class_id
              JOIN courses c  ON c.id = cl.course_id
              LEFT JOIN users u ON u.id = c.teacher_id
             WHERE e.student_id = ? AND e.status = 'active'
             ORDER BY c.term DESC, c.name
            """,
            (student_id,),
        )

    def teacher_names(self) -> list[dict[str, Any]]:
        return connection.query_all(
            "SELECT id, real_name FROM users WHERE role = 'teacher' AND status = 'active'"
        )


class ClassRepository(BaseRepository):
    table = "classes"
    writable = (
        "course_id",
        "name",
        "join_code",
        "semester",
        "location",
        "schedule",
        "capacity",
        "status",
    )
    updated_field = ""

    def by_join_code(self, code: str) -> dict[str, Any] | None:
        return self.find_by(join_code=code.upper())

    def of_course(self, course_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT cl.*,
                      (SELECT COUNT(*) FROM enrollments e
                        WHERE e.class_id = cl.id AND e.status = 'active') AS student_count
                 FROM classes cl
                WHERE cl.course_id = ?
                ORDER BY cl.id""",
            (course_id,),
        )

    def detail(self, class_id: int) -> dict[str, Any] | None:
        return connection.query_one(
            """SELECT cl.*, c.name AS course_name, c.code AS course_code,
                      c.teacher_id, u.real_name AS teacher_name, c.credits, c.term
                 FROM classes cl
                 JOIN courses c ON c.id = cl.course_id
                 LEFT JOIN users u ON u.id = c.teacher_id
                WHERE cl.id = ?""",
            (class_id,),
        )

    def of_teacher(self, teacher_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT cl.*, c.name AS course_name, c.code AS course_code,
                      (SELECT COUNT(*) FROM enrollments e
                        WHERE e.class_id = cl.id AND e.status = 'active') AS student_count
                 FROM classes cl
                 JOIN courses c ON c.id = cl.course_id
                WHERE c.teacher_id = ?
                ORDER BY c.term DESC, c.name""",
            (teacher_id,),
        )

    def students(self, class_id: int) -> list[dict[str, Any]]:
        return connection.query_all(
            """SELECT u.id, u.username, u.real_name, u.number, u.department,
                      u.class_name, u.email, u.phone, e.created_at AS enrolled_at
                 FROM enrollments e
                 JOIN users u ON u.id = e.student_id
                WHERE e.class_id = ? AND e.status = 'active'
                ORDER BY u.number, u.id""",
            (class_id,),
        )

    def student_count(self, class_id: int) -> int:
        return int(
            connection.scalar(
                "SELECT COUNT(*) FROM enrollments WHERE class_id = ? AND status = 'active'",
                (class_id,),
                default=0,
            )
            or 0
        )


class EnrollmentRepository(BaseRepository):
    table = "enrollments"
    writable = ("class_id", "student_id", "status", "source")
    updated_field = ""

    def get(self, class_id: int, student_id: int) -> dict[str, Any] | None:
        return self.find_by(class_id=class_id, student_id=student_id)

    def enroll(self, class_id: int, student_id: int, source: str = "self") -> int:
        existing = self.get(class_id, student_id)
        if existing:
            if existing["status"] != "active":
                connection.execute(
                    "UPDATE enrollments SET status = 'active', created_at = ? WHERE id = ?",
                    (clock.now_iso(), existing["id"]),
                )
            return int(existing["id"])
        return self.insert(
            {"class_id": class_id, "student_id": student_id, "source": source}
        )

    def drop(self, class_id: int, student_id: int) -> None:
        connection.execute(
            """UPDATE enrollments SET status = 'dropped'
                WHERE class_id = ? AND student_id = ?""",
            (class_id, student_id),
        )

    def is_enrolled(self, class_id: int, student_id: int) -> bool:
        row = connection.scalar(
            """SELECT 1 FROM enrollments
                WHERE class_id = ? AND student_id = ? AND status = 'active'""",
            (class_id, student_id),
        )
        return row is not None

    def class_ids_of_student(self, student_id: int) -> list[int]:
        rows = connection.query_all(
            "SELECT class_id FROM enrollments WHERE student_id = ? AND status = 'active'",
            (student_id,),
        )
        return [int(row["class_id"]) for row in rows]

    def student_count_for_courses(self, course_ids: list[int]) -> dict[int, int]:
        if not course_ids:
            return {}
        placeholders = ",".join("?" for _ in course_ids)
        rows = connection.query_all(
            f"""SELECT cl.course_id, COUNT(e.id) AS n
                  FROM classes cl
                  LEFT JOIN enrollments e
                    ON e.class_id = cl.id AND e.status = 'active'
                 WHERE cl.course_id IN ({placeholders})
                 GROUP BY cl.course_id""",
            tuple(course_ids),
        )
        return {int(row["course_id"]): int(row["n"]) for row in rows}
