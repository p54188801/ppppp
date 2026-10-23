"""测验、题库与作答记录的数据访问层。"""

from __future__ import annotations

import json
from typing import Any

from backend.core import clock
from backend.db import connection
from backend.repositories.base import BaseRepository


def _dumps(value: Any) -> str | None:
    """把列表/字典转成 JSON 文本；已经是字符串则原样返回。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class QuizRepository(BaseRepository):
    table = "quizzes"
    writable = (
        "class_id",
        "title",
        "description",
        "start_at",
        "end_at",
        "duration",
        "total_score",
        "shuffle",
        "show_answer",
        "status",
        "created_by",
    )
    updated_field = ""

    BASE_SELECT = """
        SELECT q.*,
               cl.name AS class_name,
               c.name  AS course_name,
               c.id    AS course_id,
               (SELECT COUNT(*) FROM questions qs
                 WHERE qs.quiz_id = q.id) AS question_count,
               (SELECT COUNT(*) FROM quiz_attempts a
                 WHERE a.quiz_id = q.id) AS attempt_count
          FROM quizzes q
          JOIN classes cl ON cl.id = q.class_id
          JOIN courses c  ON c.id = cl.course_id
    """

    def detail(self, quiz_id: int) -> dict[str, Any] | None:
        """测验详情，附带班级、课程与题量/作答数。"""
        return connection.query_one(
            self.BASE_SELECT + " WHERE q.id = ?", (quiz_id,)
        )

    def list_by_class(self, class_id: int) -> list[dict[str, Any]]:
        """某教学班下的全部测验，按创建时间倒序。"""
        return connection.query_all(
            self.BASE_SELECT
            + " WHERE q.class_id = ? ORDER BY q.created_at DESC, q.id DESC",
            (class_id,),
        )

    def list_for_student(self, student_id: int) -> list[dict[str, Any]]:
        """学生所在班级的全部已发布测验，并带上该生自己的作答状态。"""
        return connection.query_all(
            """
            SELECT q.*,
                   cl.name AS class_name,
                   c.name  AS course_name,
                   c.id    AS course_id,
                   a.id     AS attempt_id,
                   a.status AS attempt_status,
                   a.score
              FROM quizzes q
              JOIN classes cl ON cl.id = q.class_id
              JOIN courses c  ON c.id = cl.course_id
              JOIN enrollments e ON e.class_id = q.class_id
                                AND e.student_id = ? AND e.status = 'active'
              LEFT JOIN quiz_attempts a ON a.quiz_id = q.id
                                       AND a.student_id = ?
             WHERE q.status = 'published'
             ORDER BY COALESCE(q.start_at, q.created_at) DESC, q.id DESC
            """,
            (student_id, student_id),
        )


class QuestionRepository(BaseRepository):
    table = "questions"
    writable = (
        "quiz_id",
        "type",
        "stem",
        "options",
        "answer",
        "analysis",
        "score",
        "order_no",
    )
    created_field = ""
    updated_field = ""

    def list_by_quiz(self, quiz_id: int) -> list[dict[str, Any]]:
        """按题号取出整份试卷的题目。"""
        return connection.query_all(
            "SELECT * FROM questions WHERE quiz_id = ? ORDER BY order_no, id",
            (quiz_id,),
        )

    def count_by_quiz(self, quiz_id: int) -> int:
        return int(
            connection.scalar(
                "SELECT COUNT(*) FROM questions WHERE quiz_id = ?",
                (quiz_id,),
                default=0,
            )
            or 0
        )

    def total_score(self, quiz_id: int) -> float:
        """题目分值合计；没有题目时为 0。"""
        return float(
            connection.scalar(
                "SELECT COALESCE(SUM(score), 0) FROM questions WHERE quiz_id = ?",
                (quiz_id,),
                default=0,
            )
            or 0
        )

    def replace_for_quiz(self, quiz_id: int, questions: list[dict[str, Any]]) -> int:
        """整卷重建：先删除旧题目，再按传入顺序批量插入，返回新题数。"""
        rows: list[tuple[Any, ...]] = []
        for index, item in enumerate(questions):
            score = item.get("score")
            rows.append(
                (
                    quiz_id,
                    item.get("type", "single"),
                    item.get("stem", ""),
                    _dumps(item.get("options")),
                    item.get("answer", ""),
                    item.get("analysis", ""),
                    5.0 if score is None else float(score),
                    int(item.get("order_no") or index + 1),
                )
            )
        with connection.transaction() as conn:
            conn.execute("DELETE FROM questions WHERE quiz_id = ?", (quiz_id,))
            if rows:
                conn.executemany(
                    """INSERT INTO questions
                           (quiz_id, type, stem, options, answer, analysis,
                            score, order_no)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
        return len(rows)

    def delete_by_quiz(self, quiz_id: int) -> int:
        return connection.execute(
            "DELETE FROM questions WHERE quiz_id = ?", (quiz_id,)
        )


class AttemptRepository(BaseRepository):
    table = "quiz_attempts"
    writable = (
        "quiz_id",
        "student_id",
        "answers",
        "score",
        "status",
        "started_at",
        "submitted_at",
    )
    created_field = ""
    updated_field = ""

    def by_student(self, quiz_id: int, student_id: int) -> dict[str, Any] | None:
        """取该生在这份测验上最近的一次作答记录。"""
        return connection.query_one(
            """SELECT * FROM quiz_attempts
                WHERE quiz_id = ? AND student_id = ?
                ORDER BY id DESC LIMIT 1""",
            (quiz_id, student_id),
        )

    def start(self, quiz_id: int, student_id: int) -> int:
        """开始作答；已有未提交的记录时直接复用，避免重复开卷。"""
        existing = self.by_student(quiz_id, student_id)
        if existing and existing["status"] == "in_progress":
            return int(existing["id"])
        return self.insert(
            {
                "quiz_id": quiz_id,
                "student_id": student_id,
                "status": "in_progress",
                "started_at": clock.now_iso(),
            }
        )

    def save_answers(self, attempt_id: int, answers_json: str) -> None:
        """暂存答案（自动保存），不改变作答状态。"""
        connection.execute(
            "UPDATE quiz_attempts SET answers = ? WHERE id = ?",
            (answers_json, attempt_id),
        )

    def submit(self, attempt_id: int, score: float, answers_json: str) -> None:
        """交卷：写入答案、得分与提交时间。"""
        connection.execute(
            """UPDATE quiz_attempts
                  SET answers = ?, score = ?, status = 'submitted',
                      submitted_at = ?
                WHERE id = ?""",
            (answers_json, score, clock.now_iso(), attempt_id),
        )

    def list_by_quiz(self, quiz_id: int) -> list[dict[str, Any]]:
        """某场测验的全部作答，按分数从高到低（未交卷的排在最后）。"""
        return connection.query_all(
            """SELECT a.*, u.real_name, u.number
                 FROM quiz_attempts a
                 JOIN users u ON u.id = a.student_id
                WHERE a.quiz_id = ?
                ORDER BY (a.score IS NULL), a.score DESC, a.id ASC""",
            (quiz_id,),
        )

    def stats(self, quiz_id: int) -> dict[str, Any]:
        """测验统计；及格线固定按卷面总分的 60% 计算，通过率返回百分数。"""
        quiz_total = float(
            connection.scalar(
                "SELECT total_score FROM quizzes WHERE id = ?",
                (quiz_id,),
                default=0,
            )
            or 0
        )
        pass_score = round(quiz_total * 0.6, 2)
        row = connection.query_one(
            """SELECT COUNT(*) AS count,
                      SUM(CASE WHEN status IN ('submitted', 'graded')
                               THEN 1 ELSE 0 END) AS submitted,
                      AVG(CASE WHEN status IN ('submitted', 'graded')
                               THEN score END) AS avg_score,
                      MAX(CASE WHEN status IN ('submitted', 'graded')
                               THEN score END) AS max_score,
                      MIN(CASE WHEN status IN ('submitted', 'graded')
                               THEN score END) AS min_score,
                      SUM(CASE WHEN status IN ('submitted', 'graded')
                                AND score >= ? THEN 1 ELSE 0 END) AS passed
                 FROM quiz_attempts
                WHERE quiz_id = ?""",
            (pass_score, quiz_id),
        ) or {}
        submitted = int(row.get("submitted") or 0)
        passed = int(row.get("passed") or 0)
        return {
            "count": int(row.get("count") or 0),
            "submitted": submitted,
            "avg_score": round(float(row.get("avg_score") or 0), 2),
            "max_score": round(float(row.get("max_score") or 0), 2),
            "min_score": round(float(row.get("min_score") or 0), 2),
            "pass_rate": round(passed / submitted * 100, 1) if submitted else 0.0,
        }
