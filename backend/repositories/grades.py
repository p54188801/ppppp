"""成绩规则与成绩项的数据访问层。"""

from __future__ import annotations

from typing import Any

from backend.db import connection
from backend.repositories.base import BaseRepository


class GradeRuleRepository(BaseRepository):
    table = "grade_rules"
    writable = (
        "class_id",
        "assignment_weight",
        "quiz_weight",
        "attendance_weight",
        "final_weight",
        "pass_score",
    )
    created_field = ""
    updated_field = "updated_at"

    # 与 schema.sql 的默认值保持一致
    DEFAULT_WEIGHTS: dict[str, float] = {
        "assignment_weight": 0.30,
        "quiz_weight": 0.30,
        "attendance_weight": 0.20,
        "final_weight": 0.20,
        "pass_score": 60.0,
    }
    WEIGHT_FIELDS = tuple(DEFAULT_WEIGHTS)
    ALIASES = {
        "assignment": "assignment_weight",
        "quiz": "quiz_weight",
        "attendance": "attendance_weight",
        "final": "final_weight",
    }

    def get_or_default(self, class_id: int) -> dict[str, Any]:
        """取班级成绩权重；尚未配置时返回内置默认值，不写库。"""
        row = self.find_by(class_id=class_id)
        if row:
            return row
        return {"class_id": class_id, **self.DEFAULT_WEIGHTS}

    def save(self, class_id: int, weights: dict[str, Any]) -> int:
        """保存权重（存在则更新、不存在则插入），返回规则 id。

        weights 可传完整列名，也可传 assignment/quiz/attendance/final 简写；
        未传的字段沿用已有配置，首次配置时用默认值。
        """
        existing = self.find_by(class_id=class_id)
        payload = {
            field: (float(existing[field]) if existing and existing[field] is not None
                    else float(self.DEFAULT_WEIGHTS[field]))
            for field in self.WEIGHT_FIELDS
        }
        for key, value in weights.items():
            field = self.ALIASES.get(key, key)
            if field in self.WEIGHT_FIELDS and value is not None:
                payload[field] = float(value)
        if existing:
            self.update(int(existing["id"]), payload)
            return int(existing["id"])
        return self.insert({"class_id": class_id, **payload})


class GradeItemRepository(BaseRepository):
    table = "grade_items"
    writable = ("class_id", "student_id", "final_score", "bonus", "remark", "total")
    created_field = ""
    updated_field = "updated_at"

    def get(self, class_id: int, student_id: int) -> dict[str, Any] | None:
        """取某学生在某教学班的成绩行。"""
        return self.find_by(class_id=class_id, student_id=student_id)

    def upsert(self, class_id: int, student_id: int,
               data: dict[str, Any]) -> int:
        """有则更新、无则插入，返回成绩行 id。"""
        existing = self.get(class_id, student_id)
        if existing:
            self.update(int(existing["id"]), data)
            return int(existing["id"])
        payload = dict(data)
        payload.update({"class_id": class_id, "student_id": student_id})
        return self.insert(payload)

    def list_by_class(self, class_id: int) -> list[dict[str, Any]]:
        """整班成绩行，联用户表取姓名与学号，按学号排序。"""
        return connection.query_all(
            """SELECT g.*, u.real_name, u.number
                 FROM grade_items g
                 JOIN users u ON u.id = g.student_id
                WHERE g.class_id = ?
                ORDER BY u.number, u.id""",
            (class_id,),
        )

    def set_total(self, class_id: int, student_id: int, total: float) -> None:
        """回写加权总分缓存；没有成绩行时创建一条。"""
        existing = self.get(class_id, student_id)
        if existing:
            self.update(int(existing["id"]), {"total": total})
            return
        self.insert(
            {"class_id": class_id, "student_id": student_id, "total": total}
        )
