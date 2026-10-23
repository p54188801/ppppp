"""签到活动与签到记录的数据访问层。"""

from __future__ import annotations

from typing import Any

from backend.core import clock
from backend.db import connection
from backend.repositories.base import BaseRepository


class AttendanceSessionRepository(BaseRepository):
    table = "attendance_sessions"
    writable = (
        "class_id",
        "title",
        "method",
        "code",
        "start_at",
        "end_at",
        "latitude",
        "longitude",
        "radius",
        "status",
        "created_by",
    )
    updated_field = ""

    BASE_SELECT = """
        SELECT s.*,
               cl.name AS class_name,
               c.name  AS course_name,
               c.id    AS course_id,
               (SELECT COUNT(*) FROM attendance_records r
                 WHERE r.session_id = s.id
                   AND r.status IN ('present', 'late')) AS checked_count,
               (SELECT COUNT(*) FROM enrollments e
                 WHERE e.class_id = s.class_id
                   AND e.status = 'active') AS student_total
          FROM attendance_sessions s
          JOIN classes cl ON cl.id = s.class_id
          JOIN courses c  ON c.id = cl.course_id
    """

    def detail(self, session_id: int) -> dict[str, Any] | None:
        """签到活动详情，附带班级名与课程名。"""
        return connection.query_one(
            self.BASE_SELECT + " WHERE s.id = ?", (session_id,)
        )

    def list_by_class(self, class_id: int) -> list[dict[str, Any]]:
        """某教学班的全部签到活动，新发起的排前面。"""
        return connection.query_all(
            self.BASE_SELECT
            + " WHERE s.class_id = ? ORDER BY s.start_at DESC, s.id DESC",
            (class_id,),
        )

    def list_open_for_student(self, student_id: int) -> list[dict[str, Any]]:
        """该生所在班级中仍在进行（open 且未到结束时间）的签到。"""
        return connection.query_all(
            """
            SELECT s.*,
                   cl.name AS class_name,
                   c.name  AS course_name,
                   c.id    AS course_id,
                   r.status     AS record_status,
                   r.checked_at AS checked_at
              FROM attendance_sessions s
              JOIN classes cl ON cl.id = s.class_id
              JOIN courses c  ON c.id = cl.course_id
              JOIN enrollments e ON e.class_id = s.class_id
                                AND e.student_id = ? AND e.status = 'active'
              LEFT JOIN attendance_records r ON r.session_id = s.id
                                            AND r.student_id = ?
             WHERE s.status = 'open' AND s.end_at > ?
             ORDER BY s.end_at ASC
            """,
            (student_id, student_id, clock.now_iso()),
        )

    def close(self, session_id: int) -> None:
        """手动结束签到。"""
        connection.execute(
            "UPDATE attendance_sessions SET status = 'closed' WHERE id = ?",
            (session_id,),
        )

    def close_expired(self) -> int:
        """把所有已过结束时间但仍是 open 的签到批量关闭，返回关闭数量。"""
        connection.execute(
            """UPDATE attendance_sessions SET status = 'closed'
                WHERE status = 'open' AND end_at <= ?""",
            (clock.now_iso(),),
        )
        # connection.execute 返回的是 lastrowid，这里用 changes() 取真实影响行数
        return int(connection.scalar("SELECT changes()", default=0) or 0)


class AttendanceRecordRepository(BaseRepository):
    table = "attendance_records"
    writable = ("session_id", "student_id", "status", "checked_at", "note")
    created_field = ""
    updated_field = ""

    def mark(self, session_id: int, student_id: int, status: str,
             note: str = "") -> int:
        """签到/改签：已有记录则更新状态，否则新建，返回记录 id。"""
        now = clock.now_iso()
        existing = self.find_by(session_id=session_id, student_id=student_id)
        if existing:
            connection.execute(
                """UPDATE attendance_records
                      SET status = ?, checked_at = ?, note = ?
                    WHERE id = ?""",
                (status, now, note, existing["id"]),
            )
            return int(existing["id"])
        return self.insert(
            {
                "session_id": session_id,
                "student_id": student_id,
                "status": status,
                "checked_at": now,
                "note": note,
            }
        )

    def list_by_session(self, session_id: int) -> list[dict[str, Any]]:
        """某次签到的全部记录，联用户表取姓名与学号。"""
        return connection.query_all(
            """SELECT r.*, u.real_name, u.number
                 FROM attendance_records r
                 JOIN users u ON u.id = r.student_id
                WHERE r.session_id = ?
                ORDER BY u.number, u.id""",
            (session_id,),
        )

    def student_summary(self, class_id: int,
                        student_id: int) -> dict[str, Any]:
        """单个学生在某教学班的出勤统计；rate 为 0~1 的出勤比例（正常 + 迟到）。"""
        row = connection.query_one(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN r.status = 'present' THEN 1 ELSE 0 END) AS present,
                      SUM(CASE WHEN r.status = 'late'    THEN 1 ELSE 0 END) AS late,
                      SUM(CASE WHEN r.status = 'absent'  THEN 1 ELSE 0 END) AS absent,
                      SUM(CASE WHEN r.status = 'leave'   THEN 1 ELSE 0 END) AS leave
                 FROM attendance_records r
                 JOIN attendance_sessions s ON s.id = r.session_id
                WHERE s.class_id = ? AND r.student_id = ?""",
            (class_id, student_id),
        ) or {}
        total = int(row.get("total") or 0)
        present = int(row.get("present") or 0)
        late = int(row.get("late") or 0)
        return {
            "total": total,
            "present": present,
            "late": late,
            "absent": int(row.get("absent") or 0),
            "leave": int(row.get("leave") or 0),
            "rate": round((present + late) / total, 4) if total else 0.0,
        }

    def class_summary(self, class_id: int) -> list[dict[str, Any]]:
        """整班出勤汇总：每个在读学生一行，没有记录的学生也保留。

        rate 与 student_summary 一致，都是 0~1 的比例。
        """
        rows = connection.query_all(
            """SELECT u.id, u.real_name, u.number,
                      COALESCE(a.present, 0) AS present,
                      COALESCE(a.late, 0)    AS late,
                      COALESCE(a.absent, 0)  AS absent,
                      COALESCE(a.leave, 0)   AS leave,
                      COALESCE(a.total, 0)   AS total
                 FROM enrollments e
                 JOIN users u ON u.id = e.student_id
                 LEFT JOIN (
                      SELECT r.student_id,
                             SUM(CASE WHEN r.status = 'present' THEN 1 ELSE 0 END) AS present,
                             SUM(CASE WHEN r.status = 'late'    THEN 1 ELSE 0 END) AS late,
                             SUM(CASE WHEN r.status = 'absent'  THEN 1 ELSE 0 END) AS absent,
                             SUM(CASE WHEN r.status = 'leave'   THEN 1 ELSE 0 END) AS leave,
                             COUNT(*) AS total
                        FROM attendance_records r
                        JOIN attendance_sessions s ON s.id = r.session_id
                       WHERE s.class_id = ?
                       GROUP BY r.student_id
                 ) a ON a.student_id = u.id
                WHERE e.class_id = ? AND e.status = 'active'
                ORDER BY u.number, u.id""",
            (class_id, class_id),
        )
        summary: list[dict[str, Any]] = []
        for row in rows:
            total = int(row["total"] or 0)
            present = int(row["present"] or 0)
            late = int(row["late"] or 0)
            summary.append(
                {
                    "id": int(row["id"]),
                    "real_name": row["real_name"],
                    "number": row["number"],
                    "present": present,
                    "late": late,
                    "absent": int(row["absent"] or 0),
                    "leave": int(row["leave"] or 0),
                    "total": total,
                    "rate": round((present + late) / total, 4)
                    if total
                    else 0.0,
                }
            )
        return summary
