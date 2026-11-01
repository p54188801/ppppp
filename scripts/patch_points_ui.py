"""接入分数页面：路由 + 导航 + 学生个人中心展示。"""

from pathlib import Path

# 路由
r = Path(r"D:\EduFlow\frontend\src\router\index.js")
t = r.read_text(encoding="utf-8")
if "points" not in t:
    anchor = "    path: '/timetable',"
    t = t.replace(anchor, """    path: '/points',
    name: 'points',
    component: () => import('@/views/PointsView.vue'),
    meta: { title: '学分德育分' },
  },
  {
""" + anchor, 1)
    r.write_text(t, encoding="utf-8")
    print("router: 已加 points")

# 导航
a = Path(r"D:\EduFlow\frontend\src\App.vue")
t = a.read_text(encoding="utf-8")
if "学分德育分" not in t:
    t = t.replace(
        "    items.push({ name: 'enroll-requests', label: '入课审批', icon: '✅', group: '教学' })\n  }",
        "    items.push({ name: 'enroll-requests', label: '入课审批', icon: '✅', group: '教学' })\n"
        "    items.push({ name: 'points', label: '学分德育分', icon: '⭐', group: '教学' })\n  }",
        1,
    )
    a.write_text(t, encoding="utf-8")
    print("App: 已加导航")

# 学生个人中心：显示分数
p = Path(r"D:\EduFlow\frontend\src\views\ProfileView.vue")
t = p.read_text(encoding="utf-8")
if "myPoints" not in t:
    t = t.replace(
        "const editing = ref(false)",
        """const myPoints = ref(null)

const editing = ref(false)""",
        1,
    )
    t = t.replace(
        "async function startEdit() {",
        """async function loadPoints() {
  if (!auth.isStudent) return
  try {
    myPoints.value = await api.get('/api/my/points')
  } catch {
    myPoints.value = null
  }
}

async function startEdit() {""",
        1,
    )
    t = t.replace("onMounted(load)", "onMounted(async () => {\n  await load()\n  await loadPoints()\n})", 1)

    card = '''
        <div v-if="auth.isStudent && myPoints" class="card" style="margin-top: 14px">
          <div class="card-title">
            <span>我的学分与德育分</span>
            <span class="faint small">由老师和管理员评定</span>
          </div>
          <div class="grid cols-2" style="gap: 12px">
            <div class="stat">
              <div class="stat-label">学分</div>
              <div class="stat-value" :style="{ color: myPoints.totals.credit >= 0 ? 'var(--success)' : 'var(--danger)' }">
                {{ myPoints.totals.credit }}
              </div>
              <div class="stat-hint">初始 0 分，老师评定</div>
            </div>
            <div class="stat">
              <div class="stat-label">德育分</div>
              <div class="stat-value" :style="{ color: myPoints.totals.moral >= 50 ? 'var(--success)' : 'var(--danger)' }">
                {{ myPoints.totals.moral }}
              </div>
              <div class="stat-hint">初始 {{ myPoints.moral_base }} 分，管理员评定</div>
            </div>
          </div>

          <div v-if="myPoints.history.length" style="margin-top: 12px">
            <div class="stat-label" style="margin-bottom: 6px">最近记录</div>
            <div
              v-for="h in myPoints.history.slice(0, 8)"
              :key="h.id"
              class="row between"
              style="padding: 7px 0; border-bottom: 1px solid var(--border)"
            >
              <span class="small">
                <span class="badge" :class="h.kind === 'moral' ? 'blue' : 'yellow'">
                  {{ h.kind === 'moral' ? '德育' : '学分' }}
                </span>
                {{ h.reason }}
              </span>
              <span class="row" style="gap: 8px">
                <span class="badge" :class="h.delta > 0 ? 'green' : 'red'">
                  {{ h.delta > 0 ? '+' : '' }}{{ h.delta }}
                </span>
                <span class="faint small">{{ h.operator_name }}</span>
              </span>
            </div>
          </div>
          <div v-else class="empty" style="padding: 10px">还没有加扣分记录</div>
        </div>
'''
    anchor = '<div v-if="me.must_change_password"'
    idx = t.find(anchor)
    if idx > 0:
        t = t[:idx] + card + "\n" + t[idx:]
        p.write_text(t, encoding="utf-8")
        print("ProfileView: 已加分数卡片")
    else:
        print("ProfileView: 未找到插入点")
