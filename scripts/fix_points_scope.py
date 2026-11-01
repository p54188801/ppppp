from pathlib import Path

p = Path(r"D:\EduFlow\backend\services\points_service.py")
t = p.read_text(encoding="utf-8")

old = '''        students = connection.query_all(
            """SELECT DISTINCT u.id, u.real_name, u.username, u.number, u.class_name
                 FROM users u
                 JOIN group_members gm ON gm.user_id = u.id
                 JOIN class_groups g ON g.id = gm.group_id
                WHERE u.role = 'student' AND g.teacher_id = ?
                  AND (u.real_name LIKE ? OR u.username LIKE ? OR u.number LIKE ?)
                ORDER BY u.id DESC LIMIT 200""",
            (int(operator["id"]), like, like, like),
        )'''

new = '''        students = connection.query_all(
            """SELECT DISTINCT u.id, u.real_name, u.username, u.number, u.class_name
                 FROM users u
                 JOIN group_members gm ON gm.user_id = u.id
                 JOIN class_groups g ON g.id = gm.group_id
                 LEFT JOIN group_members me ON me.group_id = g.id AND me.user_id = ?
                WHERE u.role = 'student'
                  AND (g.teacher_id = ? OR me.role = 'teacher')
                  AND (u.real_name LIKE ? OR u.username LIKE ? OR u.number LIKE ?)
                ORDER BY u.id DESC LIMIT 200""",
            (int(operator["id"]), int(operator["id"]), like, like, like),
        )'''

if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding="utf-8")
    print("已放宽教师可见学生范围")
else:
    print("未匹配，检查文件内容")
