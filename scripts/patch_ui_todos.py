"""在首页加「待办中心」卡片（学生：待交作业/待测验/签到；教师：待批改）。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\DashboardView.vue")
t = p.read_text(encoding="utf-8")

if "todos" not in t:
    # 1) 状态
    t = t.replace(
        "const data = ref(null)",
        "const data = ref(null)\nconst todos = ref(null)",
        1,
    )
    # 2) 拉取
    t = t.replace(
        "    data.value = await api.get('/api/dashboard')",
        "    data.value = await api.get('/api/dashboard')\n"
        "    try {\n"
        "      todos.value = await api.get('/api/my/todos')\n"
        "    } catch {\n"
        "      todos.value = null\n"
        "    }",
        1,
    )

    card = """
      <div v-if="todos && todos.total" class="card" style="margin-bottom: 16px; border-color: rgba(210, 153, 34, 0.45)">
        <div class="card-title">
          <span style="color: var(--warning)">待办提醒 · {{ todos.total }} 项</span>
          <router-link v-if="auth.isStudent" class="small" :to="{ name: 'my-assignments' }">全部</router-link>
        </div>
        <div
          v-for="item in (todos.pending_assignments || []).slice(0, 3)"
          :key="'a' + item.id"
          class="row between"
          style="padding: 6px 0; border-bottom: 1px solid var(--border)"
        >
          <span>作业 · {{ item.title }}</span>
          <span class="badge yellow">{{ deadlineText(item.deadline) }}</span>
        </div>
        <div
          v-for="item in (todos.upcoming_quizzes || []).slice(0, 3)"
          :key="'q' + item.id"
          class="row between"
          style="padding: 6px 0; border-bottom: 1px solid var(--border)"
        >
          <span>测验 · {{ item.title }}</span>
          <span class="badge blue">待完成</span>
        </div>
        <div
          v-for="item in (todos.open_attendance || []).slice(0, 3)"
          :key="'s' + item.id"
          class="row between"
          style="padding: 6px 0; border-bottom: 1px solid var(--border)"
        >
          <span>签到 · {{ item.title }}</span>
          <span class="badge green">进行中</span>
        </div>
        <div
          v-for="item in (todos.ungraded || []).slice(0, 4)"
          :key="'u' + item.id"
          class="row between"
          style="padding: 6px 0; border-bottom: 1px solid var(--border)"
        >
          <span>待批改 · {{ item.student_name }} · {{ item.title }}</span>
          <span class="badge yellow">{{ item.class_name }}</span>
        </div>
      </div>
"""
    for anchor in (
        '<template v-else-if="auth.isStudent && data">',
        '<template v-else-if="auth.isTeacher && data">',
    ):
        if anchor in t:
            t = t.replace(anchor, anchor + card, 1)

    p.write_text(t, encoding="utf-8")
    print("DashboardView: 已加入待办卡片")
else:
    print("DashboardView: 已存在待办卡片")
