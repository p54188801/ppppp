"""章节任务点与学习进度接口。"""

from __future__ import annotations

from backend.core import permissions
from backend.http.response import Response, created, ok
from backend.http.router import Router
from backend.services import chapter_service

router = Router()


# ---------------------------------------------------------------- 章节


@router.get("/api/courses/<int:course_id>/chapters", summary="课程章节与任务点")
def list_chapters(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(chapter_service.list_chapters(user, req.path_params["course_id"]))


@router.post("/api/courses/<int:course_id>/chapters",
             roles=("teacher", "admin"), summary="新建章节")
def create_chapter(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = chapter_service.create_chapter(
        user, req.path_params["course_id"], req.json()
    )
    return created(data, "章节已创建")


@router.put("/api/chapters/<int:chapter_id>", roles=("teacher", "admin"),
            summary="更新章节")
def update_chapter(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = chapter_service.update_chapter(
        user, req.path_params["chapter_id"], req.json()
    )
    return ok(data, "章节已更新")


@router.delete("/api/chapters/<int:chapter_id>", roles=("teacher", "admin"),
               summary="删除章节")
def delete_chapter(req) -> Response:
    user = permissions.require_teacher(req.user)
    chapter_service.delete_chapter(user, req.path_params["chapter_id"])
    return ok(None, "章节已删除")


# ---------------------------------------------------------------- 任务点


@router.post("/api/chapters/<int:chapter_id>/tasks",
             roles=("teacher", "admin"), summary="新增任务点")
def create_task(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = chapter_service.create_task(
        user, req.path_params["chapter_id"], req.json()
    )
    return created(data, "任务点已创建")


@router.put("/api/tasks/<int:task_id>", roles=("teacher", "admin"),
            summary="更新任务点")
def update_task(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = chapter_service.update_task(user, req.path_params["task_id"], req.json())
    return ok(data, "任务点已更新")


@router.delete("/api/tasks/<int:task_id>", roles=("teacher", "admin"),
               summary="删除任务点")
def delete_task(req) -> Response:
    user = permissions.require_teacher(req.user)
    chapter_service.delete_task(user, req.path_params["task_id"])
    return ok(None, "任务点已删除")


# ---------------------------------------------------------------- 学习进度


@router.post("/api/tasks/<int:task_id>/progress", roles=("student",),
             summary="上报任务点进度")
def report_progress(req) -> Response:
    user = permissions.require_role(req.user, "student")
    data = chapter_service.report_progress(
        user, req.path_params["task_id"], req.json()
    )
    return ok(data, "学习进度已更新")


@router.get("/api/courses/<int:course_id>/progress", roles=("teacher", "admin"),
            summary="课程学习进度")
def course_progress(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(chapter_service.course_progress(user, req.path_params["course_id"]))


@router.get("/api/my/learning", roles=("student",), summary="我的学习进度")
def my_learning(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(chapter_service.my_learning(user))
