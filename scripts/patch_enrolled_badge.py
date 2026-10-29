from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\CourseListView.vue")
t = p.read_text(encoding="utf-8")

if "已选课" not in t:
    old = '<span v-else-if="course.class_name" class="badge purple">{{ course.class_name }}</span>'
    new = (
        old
        + '''
          <span v-if="auth.isStudent" class="badge" :class="course.enrolled ? 'green' : 'gray'">
            {{ course.enrolled ? '已选课' : '未选课' }}
          </span>'''
    )
    if old in t:
        t = t.replace(old, new, 1)
    t = t.replace("{{ auth.isStudent ? '我的课程'", "{{ auth.isStudent ? '全部课程'")
    p.write_text(t, encoding="utf-8")
    print("CourseListView: 已加选课标记")
else:
    print("CourseListView: 已存在")
