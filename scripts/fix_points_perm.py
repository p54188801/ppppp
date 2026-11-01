from pathlib import Path

p = Path(r"D:\EduFlow\backend\services\points_service.py")
t = p.read_text(encoding="utf-8")

old = '''    row = connection.query_one(
        """SELECT 1 FROM group_members gm
             JOIN class_groups g ON g.id = gm.group_id
            WHERE gm.user_id = ? AND g.teacher_id = ?
            LIMIT 1""",
        (student_id, oid),
    )
    return row is not None'''

new = '''    row = connection.query_one(
        """SELECT 1 FROM group_members gm
             JOIN class_groups g ON g.id = gm.group_id
             LEFT JOIN group_members me ON me.group_id = g.id AND me.user_id = ?
            WHERE gm.user_id = ? AND (g.teacher_id = ? OR me.role = 'teacher')
            LIMIT 1""",
        (oid, student_id, oid),
    )
    return row is not None'''

if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding="utf-8")
    print("已放宽教师管理权限")
else:
    print("未匹配 _can_manage")
