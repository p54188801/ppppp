"""课程与教学班接口。"""

from __future__ import annotations

from backend.core import permissions, validators
from backend.http.response import Response, created, ok, paginated
from backend.http.router import Router
from backend.services import course_service

router = Router()


# ---------------------------------------------------------------- 课程


@router.get("/api/courses", summary="课程列表")
def list_courses(req) -> Response:
    user = permissions.require_login(req.user)
    page, page_size = validators.clamp_page(req.str_param("page"), req.str_param("page_size"))
    items, total = course_service.list_courses(
        user,
        term=req.str_param("term"),
        keyword=req.str_param("keyword"),
        page=page,
        page_size=page_size,
    )
    return paginated(items, total, page, page_size)


@router.post("/api/courses", roles=("teacher", "admin"), summary="新建课程")
def create_course(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = course_service.create_course(req.json(), operator=user)
    return created(data, "课程已创建")


@router.get("/api/courses/<int:course_id>", summary="课程详情")
def get_course(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(course_service.get_course(user, req.path_params["course_id"]))


@router.put("/api/courses/<int:course_id>", roles=("teacher", "admin"), summary="更新课程")
def update_course(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = course_service.update_course(
        req.path_params["course_id"], req.json(), operator=user
    )
    return ok(data, "课程已更新")


@router.get("/api/courses/<int:course_id>/classes", summary="课程下的教学班")
def list_course_classes(req) -> Response:
    user = permissions.require_login(req.user)
    course = course_service.get_course(user, req.path_params["course_id"])
    return ok(course.get("classes", []))


@router.post("/api/courses/<int:course_id>/classes",
             roles=("teacher", "admin"), summary="新建教学班")
def create_class(req) -> Response:
    user = permissions.require_teacher(req.user)
    data = course_service.create_class(
        req.path_params["course_id"], req.json(), operator=user
    )
    return created(data, "教学班已创建")


# ---------------------------------------------------------------- 教学班


@router.get("/api/classes", summary="我相关教学班")
def list_classes(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(course_service.list_classes(user))


@router.get("/api/classes/<int:class_id>", summary="教学班详情")
def get_class(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(course_service.get_class(user, req.path_params["class_id"]))


@router.post("/api/classes/join", roles=("student",), summary="凭邀请码加入")
def join_class(req) -> Response:
    user = permissions.require_role(req.user, "student")
    payload = req.json()
    code = validators.required_str(payload, "code", min_len=4, max_len=12)
    data = course_service.join_class(user, code)
    return ok(data, "加入成功")


@router.get("/api/classes/<int:class_id>/students", summary="教学班学生")
def class_students(req) -> Response:
    user = permissions.require_login(req.user)
    return ok(course_service.class_students(user, req.path_params["class_id"]))


@router.post("/api/classes/<int:class_id>/students",
             roles=("teacher", "admin"), summary="手动添加学生")
def add_student(req) -> Response:
    user = permissions.require_teacher(req.user)
    payload = req.json()
    student_id = validators.required_int(payload, "student_id", min_value=1)
    return ok(course_service.add_student(req.path_params["class_id"], student_id, user))


@router.delete("/api/classes/<int:class_id>/students/<int:student_id>",
               roles=("teacher", "admin"), summary="移出学生")
def drop_student(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(
        course_service.drop_student(
            req.path_params["class_id"], req.path_params["student_id"], user
        )
    )


@router.post("/api/classes/<int:class_id>/leave", roles=("student",), summary="退课")
def leave_class(req) -> Response:
    user = permissions.require_role(req.user, "student")
    return ok(course_service.leave_class(user, req.path_params["class_id"]))


@router.get("/api/teacher/overview", roles=("teacher", "admin"), summary="教师工作台")
def teacher_overview(req) -> Response:
    user = permissions.require_teacher(req.user)
    return ok(course_service.teacher_overview(user))
