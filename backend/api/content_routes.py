"""资料、讨论、通知接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http import multipart
from backend.http.response import Response, created, file_response, ok, paginated
from backend.http.router import Router
from backend.services import ( 
    announcement_service,
    discussion_service,
    notification_service,
    resource_service,
)

router = Router()


# ---------------------------------------------------------------- 公告


@router.get("/api/courses/<int:course_id>/announcements", summary="课程公告列表")
def list_announcements(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(announcement_service.list_for_course(user, req.path_params["course_id"]))


@router.post("/api/courses/<int:course_id>/announcements",
             roles=("teacher", "admin"), summary="发布公告")
def create_announcement(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = announcement_service.create(user, req.path_params["course_id"], req.json())
    return created(data, "公告已发布")


@router.get("/api/my/announcements", roles=("student",), summary="我的课程公告")
def my_announcements(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(announcement_service.student_feed(user))


@router.put("/api/announcements/<int:announcement_id>", roles=("teacher", "admin"),
            summary="更新公告")
def update_announcement(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = announcement_service.update(user, req.path_params["announcement_id"], req.json())
    return ok(data, "公告已更新")


@router.delete("/api/announcements/<int:announcement_id>", roles=("teacher", "admin"),
               summary="删除公告")
def delete_announcement(req) -> Response:
    user = permissions.require_teacher(req.user)
    announcement_service.delete(user, req.path_params["announcement_id"])
    return ok(None, "公告已删除")


# ---------------------------------------------------------------- 资料


@router.get("/api/courses/<int:course_id>/resources", summary="课程资料列表")
def list_resources(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(
        resource_service.list_resources(
            user, req.path_params["course_id"], keyword=req.str_param("keyword")
        )
    )


@router.post("/api/courses/<int:course_id>/resources", roles=("teacher", "admin"),
             summary="上传资料")
def upload_resource(req) -> Response:
    user = permissions.require_teacher(req.user)
    content_type = req.header("content-type")
    if not multipart.is_multipart(content_type):
        raise validators.ValidationError("请使用 multipart/form-data 上传")
    form = multipart.parse_multipart(req.body, content_type)
    uploaded = form.first_file()
    if uploaded is None:
        raise validators.ValidationError("没有找到上传文件")
    data = resource_service.save_upload(
        uploaded.filename,
        uploaded.data,
        course_id=req.path_params["course_id"],
        operator=user,
        title=form.get("title", ""),
        description=form.get("description", ""),
        category=form.get("category", "课件"),
    )
    return created(data, "上传成功")


@router.get("/api/resources/<int:resource_id>/download", summary="下载资料")
def download_resource(req) -> Response:
    user = permissions.require_login(req.user)
    path, filename = resource_service.get_download(user, req.path_params["resource_id"])
    return file_response(path, download_name=filename)


@router.delete("/api/resources/<int:resource_id>", roles=("teacher", "admin"),
               summary="删除资料")
def delete_resource(req) -> Response:
    user = permissions.require_teacher(req.user)
    resource_service.delete_resource(user, req.path_params["resource_id"])
    return ok(None, "已删除")


# ---------------------------------------------------------------- 讨论


@router.get("/api/courses/<int:course_id>/discussions", summary="话题列表")
def list_threads(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(discussion_service.list_threads(user, req.path_params["course_id"]))


@router.post("/api/courses/<int:course_id>/discussions", summary="发布话题")
def create_thread(req) -> Response:
    user = permissions.require_login(req.user)
    data = discussion_service.create_thread(
        user, req.path_params["course_id"], req.json()
    )
    return created(data, "话题已发布")


@router.get("/api/discussions/<int:discussion_id>", summary="话题详情")
def get_thread(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(discussion_service.get_thread(user, req.path_params["discussion_id"]))


@router.post("/api/discussions/<int:discussion_id>/replies", summary="回复话题")
def reply(req) -> Response:
    user = permissions.require_login(req.user)
    return created(discussion_service.reply(user, req.path_params["discussion_id"], req.json()))


@router.put("/api/discussions/<int:discussion_id>", roles=("teacher", "admin"),
            summary="置顶/锁定/删除话题")
def set_flags(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(discussion_service.set_flags(user, req.path_params["discussion_id"], req.json()))


@router.delete("/api/replies/<int:reply_id>", summary="删除回复")
def delete_reply(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(discussion_service.delete_reply(user, req.path_params["reply_id"]))


# ---------------------------------------------------------------- 通知


@router.get("/api/notifications", summary="我的通知")
def list_notifications(req) -> Response:
    user = permissions.require_login(req.user)
    page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
    items, total = notification_service.list_notifications(
        user,
        only_unread=req.bool_param("unread"),
        page=page,
        page_size=page_size,
    )
    return paginated(items, total, page, page_size)


@router.get("/api/notifications/unread-count", summary="未读数")
def unread_count(req) -> Response:
    user = permissions.require_login(req.user)
    return ok({"count": notification_service.unread_count(user)})


@router.post("/api/notifications/<int:notification_id>/read", summary="标记已读")
def mark_read(req) -> Response:
    user = permissions.require_login(req.user)
    notification_service.mark_read(user, req.path_params["notification_id"])
    return ok(None, "已读")


@router.post("/api/notifications/read-all", summary="全部已读")
def mark_all_read(req) -> Response:
    user = permissions.require_login(req.user)
    return ok({"updated": notification_service.mark_all_read(user)})


@router.delete("/api/notifications/read", summary="清空已读")
def clear_read(req) -> Response:
    user = permissions.require_login(req.user)
    return ok({"deleted": notification_service.clear_read(user)})


@router.post("/api/notifications/broadcast", roles=("admin",), summary="广播通知")
def broadcast(req) -> Response:
    user = permissions.require_admin(req.user)
    count = notification_service.broadcast(user, req.json())
    return ok({"sent": count}, f"已发送 {count} 条")
