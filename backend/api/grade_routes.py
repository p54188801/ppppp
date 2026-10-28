"""成绩接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, ok
from backend.http.router import Router
from backend.services import grade_service

router = Router()


@router.get("/api/classes/<int:class_id>/grade-rule", roles=("teacher", "admin"),
            summary="成绩权重")
def get_rule(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(grade_service.get_rule(user, req.path_params["class_id"]))


@router.put("/api/classes/<int:class_id>/grade-rule", roles=("teacher", "admin"),
            summary="保存成绩权重")
def save_rule(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = grade_service.save_rule(user, req.path_params["class_id"], req.json())
    return ok(data, "权重已保存")


@router.get("/api/classes/<int:class_id>/gradebook", roles=("teacher", "admin"),
            summary="成绩册")
def gradebook(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(grade_service.gradebook(user, req.path_params["class_id"]))


@router.post("/api/classes/<int:class_id>/grades", roles=("teacher", "admin"),
             summary="录入期末成绩")
def set_final(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = grade_service.set_final_score(user, req.path_params["class_id"], req.json())
    return ok(data, "成绩已更新")


@router.post("/api/classes/<int:class_id>/grades/batch", roles=("teacher", "admin"),
             summary="批量录入")
def batch_set_final(req) -> Response:
    user = permissions.require_teacher(req.user)
    payload = req.json()
    rows = payload.get("rows")
    if not isinstance(rows, list):
        from backend.core.errors import ValidationError

        raise ValidationError("rows 必须是数组")
    result = grade_service.batch_set_final(user, req.path_params["class_id"], rows)
    return ok(result, f"已更新 {result['updated']} 条")


@router.get("/api/classes/<int:class_id>/ranking", roles=("teacher", "admin"),
            summary="班级排名")
def ranking(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(grade_service.class_ranking(user, req.path_params["class_id"]))


@router.get("/api/my/transcript", roles=("student",), summary="我的成绩单")
def transcript(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(grade_service.my_transcript(user))


@router.get("/api/classes/<int:class_id>/grades/export", roles=("teacher", "admin"),
            summary="导出成绩 CSV")
def export(req) -> Response:
    user = permissions.require_teacher(req.user)
    text = grade_service.export_csv(user, req.path_params["class_id"])
    from backend.http.response import Response as R

    return R(
        status=200,
        body=text.encode("utf-8-sig"),
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=gradebook_{req.path_params['class_id']}.csv"
        },
    )

@router.get("/api/my/transcript/export", roles=("student",), summary="导出我的成绩单 CSV")
def export_transcript(req) -> Response:
    import csv
    import io

    user = permissions.require_role(req.user, "student")
    data = grade_service.my_transcript(user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["课程", "教学班", "学分", "作业", "测验", "出勤", "期末", "总评", "绩点", "是否通过"])
    for row in data["rows"]:
        w.writerow([
            row.get("course_name", ""), row.get("class_name", ""), row.get("credits", ""),
            row.get("assignment_score"), row.get("quiz_score"), row.get("attendance_score"),
            "" if row.get("final_score") is None else row["final_score"],
            row.get("total"), row.get("grade_point"), "是" if row.get("passed") else "否",
        ])
    w.writerow([])
    w.writerow(["总学分", data["total_credits"], "GPA", data["gpa"], "平均分", data["average"]])
    from backend.http.response import Response as R

    return R(status=200, body=buf.getvalue().encode("utf-8-sig"),
             content_type="text/csv; charset=utf-8",
             headers={"Content-Disposition": "attachment; filename=my_transcript.csv"})