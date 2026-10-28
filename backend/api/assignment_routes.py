"""作业接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.http import multipart
from backend.http.response import file_response
from backend.services import assignment_service, attachment_service

router = Router()


@router.get("/api/classes/<int:class_id>/assignments", summary="教学班作业列表")
def list_class_assignments(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(assignment_service.list_assignments(user, req.path_params["class_id"]))


@router.post("/api/assignments", roles=("teacher", "admin"), summary="发布作业")
def create_assignment(req) -> Response:
    user = permissions.require_teacher(req.user)
    return created(assignment_service.create_assignment(req.json(), operator=user), "作业已发布")


@router.get("/api/assignments/<int:assignment_id>", summary="作业详情")
def get_assignment(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(assignment_service.get_assignment(user, req.path_params["assignment_id"]))


@router.put("/api/assignments/<int:assignment_id>", roles=("teacher", "admin"),
            summary="更新作业")
def update_assignment(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = assignment_service.update_assignment(
        req.path_params["assignment_id"], req.json(), operator=user
    )
    return ok(data, "作业已更新")


@router.delete("/api/assignments/<int:assignment_id>", roles=("teacher", "admin"),
               summary="删除作业")
def delete_assignment(req) -> Response:
    user = permissions.require_teacher(req.user)
    assignment_service.delete_assignment(user, req.path_params["assignment_id"])
    return ok(None, "作业已删除")


@router.get("/api/my/assignments", roles=("student",), summary="我的作业")
def my_assignments(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(assignment_service.student_assignments(user, status=req.str_param("status")))


@router.post("/api/assignments/<int:assignment_id>/submit", roles=("student",),
             summary="提交作业")
def submit_assignment(req) -> Response:
    user = permissions.require_role(req.user, "student")
    data = assignment_service.submit(user, req.path_params["assignment_id"], req.json())
    return ok(data, "提交成功")


@router.get("/api/assignments/<int:assignment_id>/submissions",
            roles=("teacher", "admin"), summary="作业提交列表")
def list_submissions(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(assignment_service.list_submissions(user, req.path_params["assignment_id"]))


@router.post("/api/submissions/<int:submission_id>/grade",
             roles=("teacher", "admin"), summary="批改单份作业")
def grade_submission(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = assignment_service.grade_submission(
        user, req.path_params["submission_id"], req.json()
    )
    return ok(data, "批改完成")


@router.post("/api/assignments/<int:assignment_id>/batch-grade",
             roles=("teacher", "admin"), summary="批量批改")
def batch_grade(req) -> Response:
    user = permissions.require_teacher(req.user)
    payload = req.json()
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise validators.ValidationError("rows 必须是数组")
    result = assignment_service.batch_grade(
        user, req.path_params["assignment_id"], rows
    )
    return ok(result, f"已批改 {result['updated']} 份")

# ---------------------------------------------------------------- 附件


@router.get("/api/assignments/<int:assignment_id>/attachments", summary="我的附件列表")
def list_attachments(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(attachment_service.list_for(req.path_params["assignment_id"], int(user["id"])))


@router.post("/api/assignments/<int:assignment_id>/attachments", roles=("student",),
             summary="上传作业附件")
def upload_attachment(req) -> Response:
    user = permissions.require_role(req.user, "student")
    content_type = req.header("content-type")
    if not multipart.is_multipart(content_type):
        raise validators.ValidationError("请使用 multipart/form-data 上传")
    form = multipart.parse_multipart(req.body, content_type)
    files = [(f.filename, f.data) for f in form.files.values()]
    if not files:
        raise validators.ValidationError("没有找到上传文件")
    saved = attachment_service.save_uploads(
        req.path_params["assignment_id"], int(user["id"]), files
    )
    return created({"files": saved}, "上传成功")


@router.get("/api/attachments/<int:file_id>/download", summary="下载作业附件")
def download_attachment(req) -> Response:
    user = permissions.require_login(req.user)
    path, filename = attachment_service.resolve_download(user, req.path_params["file_id"])
    return file_response(path, download_name=filename)


@router.delete("/api/attachments/<int:file_id>", roles=("student",), summary="删除附件")
def delete_attachment(req) -> Response:
    user = permissions.require_role(req.user, "student")
    attachment_service.delete_file(user, req.path_params["file_id"])
    return ok(None, "已删除")

@router.get("/api/assignments/<int:assignment_id>/progress",
            roles=("teacher", "admin"), summary="提交进度与未交名单")
def submission_progress(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(assignment_service.submission_progress(user, req.path_params["assignment_id"]))
