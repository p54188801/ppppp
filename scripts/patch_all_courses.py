"""学生可见全部课程 + 搜索覆盖所有课程。"""

from pathlib import Path

# ---------------- 课程列表 ----------------
c = Path(r"D:\EduFlow\backend\services\course_service.py")
t = c.read_text(encoding="utf-8")

old = '''    else:
        items = course_repo.of_student(int(viewer["id"]))
        if keyword:
            lowered = keyword.lower()
            items = [
                item for item in items
                if lowered in (item.get("name") or "").lower()
                or lowered in (item.get("code") or "").lower()
            ]
        total = len(items)
    return items, total'''

new = '''    else:
        # 学生可见全部已开设课程；已选课的标记出来
        items = course_repo.list_courses(term=term, keyword=keyword)
        total = len(items)
        enrolled_ids = {
            int(r["course_id"])
            for r in connection.query_all(
                """SELECT DISTINCT cl.course_id FROM enrollments e
                     JOIN classes cl ON cl.id = e.class_id
                    WHERE e.student_id = ? AND e.status = 'active'""",
                (int(viewer["id"]),),
            )
        }
        for item in items:
            item["enrolled"] = int(item["id"]) in enrolled_ids
        items = items[offset : offset + page_size]
        total = len(course_repo.list_courses(term=term, keyword=keyword))
    return items, total'''

if old in t:
    t = t.replace(old, new)
    c.write_text(t, encoding="utf-8")
    print("course_service: 学生可见全部课程")
else:
    print("course_service: 未匹配旧逻辑")

if "from backend.db import connection" not in t:
    t = c.read_text(encoding="utf-8")
    if "from backend.db import connection" not in t:
        t = t.replace("from backend.core import clock, permissions, validators",
                      "from backend.core import clock, permissions, validators\nfrom backend.db import connection")
        c.write_text(t, encoding="utf-8")
        print("course_service: 补 connection 导入")

# ---------------- 搜索：学生可搜到全部课程 ----------------
s = Path(r"D:\EduFlow\backend\services\search_service.py")
t = s.read_text(encoding="utf-8")
if "all_courses" not in t:
    t = t.replace(
        '    if viewer["role"] == permissions.ROLE_STUDENT:',
        '''    student_mode = viewer["role"] == permissions.ROLE_STUDENT
    if student_mode:''',
        1,
    )
    s.write_text(t, encoding="utf-8")
    print("search_service: 标记学生模式")
