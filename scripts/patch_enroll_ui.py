"""入课审批：前端页面 + 课程页申请入口。"""

from pathlib import Path

# ---------------- 教师端页面 ----------------
view = Path(r"D:\EduFlow\frontend\src\views\EnrollRequestsView.vue")
view.write_text('''<script setup>
/**
 * 入课审批：学生凭邀请码申请后，任课老师在这里同意或拒绝。
 */
import { computed, onMounted, ref } from 'vue'
import { api, formatDate } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

const items = ref([])
const loading = ref(true)
const acting = ref(0)

const grouped = computed(() => {
  const map = new Map()
  for (const it of items.value) {
    const key = `${it.course_name} / ${it.class_name}`
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(it)
  }
  return [...map.entries()].map(([name, list]) => ({ name, list }))
})

async function load() {
  loading.value = true
  try {
    items.value = await api.get('/api/enroll/requests')
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function decide(item, approve) {
  acting.value = item.id
  try {
    await api.post(`/api/enroll/requests/${item.id}/${approve ? 'approve' : 'reject'}`)
    ui.success(approve ? `已同意 ${item.real_name} 加入` : `已拒绝 ${item.real_name}`)
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    acting.value = 0
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>入课审批</h1>
        <p>学生凭邀请码申请加入课程，同意后才会出现在你的班级名单里</p>
      </div>
      <button class="btn" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!items.length" class="card empty" style="text-align: center; padding: 30px">
      暂无待审批的申请
    </div>

    <div v-for="group in grouped" :key="group.name" class="card" style="margin-bottom: 14px">
      <div class="card-title">
        <span>{{ group.name }}</span>
        <span class="badge yellow">{{ group.list.length }} 人待审批</span>
      </div>
      <div
        v-for="item in group.list"
        :key="item.id"
        class="row between"
        style="padding: 10px 0; border-bottom: 1px solid var(--border)"
      >
        <div>
          <strong>{{ item.real_name }}</strong>
          <span class="faint small"> {{ item.number || item.username }}</span>
          <div class="faint small">申请时间 {{ formatDate(item.created_at, true) }}</div>
        </div>
        <div class="row" style="gap: 8px">
          <button class="btn sm" :disabled="acting === item.id" @click="decide(item, false)">拒绝</button>
          <button class="btn sm primary" :disabled="acting === item.id" @click="decide(item, true)">同意</button>
        </div>
      </div>
    </div>
  </div>
</template>
''', encoding="utf-8")
print("EnrollRequestsView: 已创建")

# ---------------- 路由 ----------------
r = Path(r"D:\EduFlow\frontend\src\router\index.js")
t = r.read_text(encoding="utf-8")
if "enroll-requests" not in t:
    anchor = "    path: '/timetable',"
    t = t.replace(anchor, """    path: '/enroll-requests',
    name: 'enroll-requests',
    component: () => import('@/views/EnrollRequestsView.vue'),
    meta: { title: '入课审批' },
  },
  {
""" + anchor, 1)
    r.write_text(t, encoding="utf-8")
    print("router: 已加入课审批路由")

# ---------------- 导航 ----------------
a = Path(r"D:\EduFlow\frontend\src\App.vue")
t = a.read_text(encoding="utf-8")
if "入课审批" not in t:
    t = t.replace(
        "  items.push({ name: 'timetable', label: '课表', icon: '🗓', group: '学习' })",
        "  items.push({ name: 'timetable', label: '课表', icon: '🗓', group: '学习' })\n"
        "  if (auth.isTeacher || auth.isAdmin) {\n"
        "    items.push({ name: 'enroll-requests', label: '入课审批', icon: '✅', group: '教学' })\n"
        "  }",
    )
    a.write_text(t, encoding="utf-8")
    print("App: 已加导航")

# ---------------- 课程页：邀请码申请 ----------------
c = Path(r"D:\EduFlow\frontend\src\views\CourseListView.vue")
t = c.read_text(encoding="utf-8")
if "requestJoin" not in t:
    t = t.replace("const offers = ref([])", "const offers = ref([])\nconst joinCode = ref('')\nconst joining = ref(false)", 1)
    logic = '''
async function requestJoin() {
  if (!joinCode.value.trim()) return ui.error('请输入邀请码')
  joining.value = true
  try {
    const data = await api.post('/api/enroll/request', { code: joinCode.value.trim().toUpperCase() })
    ui.success(`已申请加入《${data.course_name}》，等待老师审批`)
    joinCode.value = ''
  } catch (error) {
    ui.error(error.message)
  } finally {
    joining.value = false
  }
}
'''
    t = t.replace("async function load(", logic + "\nasync function load(", 1)

    card = '''
    <div v-if="auth.isStudent" class="card" style="margin-bottom: 16px">
      <div class="card-title">
        <span>凭邀请码加入课程</span>
        <span class="faint small">提交后需要任课老师同意</span>
      </div>
      <div class="row" style="gap: 10px; margin-top: 6px">
        <input
          v-model="joinCode"
          class="input mono"
          placeholder="输入老师给的邀请码，例如 SA36Y4"
          style="max-width: 320px; text-transform: uppercase"
          @keyup.enter="requestJoin"
        />
        <button class="btn primary" :disabled="joining || !joinCode.trim()" @click="requestJoin">
          {{ joining ? '提交中…' : '申请加入' }}
        </button>
      </div>
    </div>
'''
    idx = t.find("<template>")
    marker = "<div v-if=\"auth.isStudent && offers.length\""
    pos = t.find(marker)
    if pos > 0:
        t = t[:pos] + card + "\n" + t[pos:]
    else:
        t = t.replace("<template>", "<template>\n  <div>\n" + card, 1)
    c.write_text(t, encoding="utf-8")
    print("CourseListView: 已加邀请码申请")
