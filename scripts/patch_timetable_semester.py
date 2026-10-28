"""课表升级：学期、周次、时间。"""

from pathlib import Path

# ---------------- 迁移 v8 ----------------
m = Path(r"D:\EduFlow\backend\db\migrations.py")
t = m.read_text(encoding="utf-8")
t = t.replace("CURRENT_VERSION = 7", "CURRENT_VERSION = 8")
if "_migrate_v8" not in t:
    func = '''
def _migrate_v8(conn: sqlite3.Connection) -> None:
    """v7 -> v8：课表增加学期与周次。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(timetable)")}
    if "semester" not in cols:
        conn.execute("ALTER TABLE timetable ADD COLUMN semester TEXT NOT NULL DEFAULT ''")
    if "weeks" not in cols:
        conn.execute("ALTER TABLE timetable ADD COLUMN weeks TEXT NOT NULL DEFAULT '1-20'")
    conn.execute(
        "UPDATE timetable SET semester = '2026-2027-1' WHERE semester = '' OR semester IS NULL"
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
'''
    t = t.replace("MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [", func, 1)
    out = []
    for line in t.splitlines():
        out.append(line)
        if line.strip() == "(7, _migrate_v7),":
            out.append("    (8, _migrate_v8),")
    m.write_text("\n".join(out), encoding="utf-8")
    print("migrations: v8")

# ---------------- 服务 ----------------
s = Path(r"D:\EduFlow\backend\services\timetable_service.py")
t = s.read_text(encoding="utf-8")

# 列表：支持 semester
t = t.replace(
    'def list_slots(user: dict[str, Any], *, class_name: str = "", teacher_name: str = "") -> dict[str, Any]:',
    'def list_slots(user: dict[str, Any], *, class_name: str = "", teacher_name: str = "",\n'
    '               semester: str = "") -> dict[str, Any]:',
)
t = t.replace(
    '    sql = "SELECT * FROM timetable"',
    '''    semesters = [r["semester"] for r in connection.query_all(
        "SELECT DISTINCT semester FROM timetable WHERE semester <> '' ORDER BY semester DESC"
    )]
    if not semester and semesters:
        semester = semesters[0]
    if semester:
        where.append("semester = ?")
        params.append(semester)

    sql = "SELECT * FROM timetable"''',
)
t = t.replace(
    '''    return {
        "scope": scope,
        "class_name": class_name or (user.get("class_name") or ""),
        "slots": rows,
        "periods": PERIODS,
        "weekdays": WEEKDAYS,
    }''',
    '''    return {
        "scope": scope,
        "class_name": class_name or (user.get("class_name") or ""),
        "semester": semester,
        "semesters": semesters,
        "slots": rows,
        "periods": PERIODS,
        "weekdays": WEEKDAYS,
    }''',
)

# 校验：接受 semester / weeks
t = t.replace(
    '''        "note": validators.optional_str(payload, "note", "", max_len=200),
    }''',
    '''        "note": validators.optional_str(payload, "note", "", max_len=200),
        "semester": validators.optional_str(payload, "semester", "2026-2027-1", max_len=32),
        "weeks": validators.optional_str(payload, "weeks", "1-20", max_len=64),
    }''',
)
t = t.replace(
    '''            (data["class_name"], data["weekday"], data["period"], data["course_name"],
             data["teacher_name"], data["room"], data["note"], now, now),''',
    '''            (data["class_name"], data["weekday"], data["period"], data["course_name"],
             data["teacher_name"], data["room"], data["note"], now, now,
             data["semester"], data["weeks"]),''',
)
t = t.replace(
    '''                   (class_name, weekday, period, course_name, teacher_name, room, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
    '''                   (class_name, weekday, period, course_name, teacher_name, room, note,
                    created_at, updated_at, semester, weeks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
)
t = t.replace(
    '''                "UPDATE timetable SET class_name=?, weekday=?, period=?, course_name=?,
                  teacher_name=?, room=?, note=?, updated_at=? WHERE id=?"''',
    '''                "UPDATE timetable SET class_name=?, weekday=?, period=?, course_name=?,"
                  " teacher_name=?, room=?, note=?, updated_at=?, semester=?, weeks=? WHERE id=?"''',
)
t = t.replace(
    '''        (data["class_name"], data["weekday"], data["period"], data["course_name"],
         data["teacher_name"], data["room"], data["note"], clock.now_iso(), slot_id),''',
    '''        (data["class_name"], data["weekday"], data["period"], data["course_name"],
         data["teacher_name"], data["room"], data["note"], clock.now_iso(),
         data["semester"], data["weeks"], slot_id),''',
)
s.write_text(t, encoding="utf-8")
print("timetable_service: 学期与周次")

# ---------------- 路由传参 ----------------
r = Path(r"D:\EduFlow\backend\api\timetable_routes.py")
t = r.read_text(encoding="utf-8")
t = t.replace(
    '        teacher_name=req.str_param("teacher_name"),\n    )',
    '        teacher_name=req.str_param("teacher_name"),\n        semester=req.str_param("semester"),\n    )',
)
r.write_text(t, encoding="utf-8")
print("timetable_routes: semester 参数")
