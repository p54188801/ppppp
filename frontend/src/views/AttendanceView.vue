<script setup>
/**
 * 课堂签到（学生 / 教师共用）
 *
 * 学生：查看自己班级中正在进行的签到，倒计时内输入 6 位签到码完成签到；
 *       下方汇总「我的出勤」，并列出各教学班的历史签到与我的状态。
 * 教师：选择教学班后发起 5 分钟签到码签到，大号字体展示签到码与倒计时，
 *       可查看该班签到历史并手动结束进行中的签到。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, formatDate } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

const loading = ref(true)
const now = ref(Date.now())
let clockTimer = null

/* ---------------- 学生 ---------------- */
const openSessions = ref([])
const myAttendance = ref(null)
const history = ref([])
const historyLoading = ref(false)

const checkTarget = ref(null)
const checkCode = ref('')
const checking = ref(false)

/* ---------------- 教师 ---------------- */
const classes = ref([])
const selectedClassId = ref('')
const classSessions = ref([])
const sessionsLoading = ref(false)
const sessionTitle = ref('课堂签到')
const creating = ref(false)
const currentSession = ref(null)

const selectedClass = computed(
  () => classes.value.find((item) => Number(item.id) === Number(selectedClassId.value)) || null,
)

const currentOpen = computed(() => {
  const session = currentSession.value
  if (!session) return false
  return session.status === 'open' && new Date(session.end_at).getTime() > now.value
})

function classLabel(item) {
  if (!item) return ''
  return item.class_name || item.name || ''
}

function courseLabel(item) {
  if (!item) return ''
  return item.course_name || item.name || ''
}

function methodLabel(method) {
  if (method === 'qr') return '二维码'
  if (method === 'location') return '定位'
  return '签到码'
}

function attendanceLabel(status) {
  if (status === 'present') return { label: '正常', tone: 'green' }
  if (status === 'late') return { label: '迟到', tone: 'yellow' }
  if (status === 'absent') return { label: '缺勤', tone: 'red' }
  if (status === 'leave') return { label: '请假', tone: 'blue' }
  return { label: '未签到', tone: 'gray' }
}

function isOpen(session) {
  if (!session) return false
  if (session.status !== 'open') return false
  return new Date(session.end_at).getTime() > now.value
}

function remainingText(endAt) {
  if (!endAt) return '—'
  const diff = new Date(endAt).getTime() - now.value
  if (Number.isNaN(diff)) return '—'
  if (diff <= 0) return '已结束'
  const total = Math.floor(diff / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60)
    return `${hours} 小时 ${minutes % 60} 分钟`
  }
  return `${minutes} 分 ${String(seconds).padStart(2, '0')} 秒`
}

/* ---------------- 学生逻辑 ---------------- */

async function loadStudent() {
  loading.value = true
  try {
    openSessions.value = (await api.get('/api/my/attendance/open')) || []
    const dashboard = await api.get('/api/dashboard')
    myAttendance.value = dashboard?.attendance || null
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
  await loadHistory()
}

async function loadHistory() {
  historyLoading.value = true
  try {
    // 学生调用 /api/classes 会返回自己已选教学班（含 class_id 与班级名）
    const list = (await api.get('/api/classes')) || []
    const results = await Promise.all(
      list.map(async (item) => {
        const classId = item.class_id || item.id
        if (!classId) return []
        try {
          return (await api.get(`/api/classes/${classId}/attendance`)) || []
        } catch {
          return []
        }
      }),
    )
    const rows = results.flat()
    rows.sort((a, b) => new Date(b.start_at).getTime() - new Date(a.start_at).getTime())
    history.value = rows.slice(0, 30)
  } catch (error) {
    ui.error(error.message)
  } finally {
    historyLoading.value = false
  }
}

function openCheckIn(session) {
  checkCode.value = ''
  checkTarget.value = session
}

async function doCheckIn() {
  if (!checkTarget.value) return
  const code = checkCode.value.trim()
  if (!/^\d{6}$/.test(code)) {
    ui.error('请输入 6 位数字签到码')
    return
  }
  checking.value = true
  try {
    await api.post(`/api/attendance/${checkTarget.value.id}/check-in`, { code })
    ui.success('签到成功')
    checkTarget.value = null
    checkCode.value = ''
    await loadStudent()
  } catch (error) {
    ui.error(error.message)
  } finally {
    checking.value = false
  }
}

/* ---------------- 教师逻辑 ---------------- */

async function loadTeacher() {
  loading.value = true
  try {
    classes.value = (await api.get('/api/classes')) || []
    if (classes.value.length) {
      selectedClassId.value = classes.value[0].id
      await loadClassSessions()
    }
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function loadClassSessions() {
  if (!selectedClassId.value) {
    classSessions.value = []
    return
  }
  sessionsLoading.value = true
  try {
    classSessions.value =
      (await api.get(`/api/classes/${selectedClassId.value}/attendance`)) || []
  } catch (error) {
    ui.error(error.message)
  } finally {
    sessionsLoading.value = false
  }
}

async function changeClass() {
  currentSession.value = null
  await loadClassSessions()
}

async function createSession() {
  if (!selectedClassId.value) {
    ui.error('请先选择教学班')
    return
  }
  creating.value = true
  try {
    const data = await api.post('/api/attendance', {
      class_id: Number(selectedClassId.value),
      title: sessionTitle.value.trim() || '课堂签到',
      method: 'code',
      duration: 5,
    })
    currentSession.value = data
    ui.success('签到已发起，请把签到码告诉学生')
    await loadClassSessions()
  } catch (error) {
    ui.error(error.message)
  } finally {
    creating.value = false
  }
}

async function closeSession(session) {
  if (!session) return
  const ok = await ui.confirm({
    title: '结束签到',
    message: `确定结束「${session.title}」吗？结束后学生将无法签到。`,
    danger: true,
  })
  if (!ok) return
  try {
    await api.post(`/api/attendance/${session.id}/close`)
    ui.success('签到已结束')
    if (currentSession.value?.id === session.id) currentSession.value = null
    await loadClassSessions()
  } catch (error) {
    ui.error(error.message)
  }
}

function switchTabByRole() {
  if (auth.isStudent) loadStudent()
  else loadTeacher()
}

onMounted(() => {
  clockTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
  switchTabByRole()
})

onUnmounted(() => {
  if (clockTimer) window.clearInterval(clockTimer)
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>{{ auth.isStudent ? '课堂签到' : '签到管理' }}</h1>
        <p v-if="auth.isStudent">及时完成课堂签到，查看自己的出勤记录</p>
        <p v-else>发起签到、投屏签到码，并查看班级出勤情况</p>
      </div>
      <button
        class="btn"
        :disabled="loading"
        @click="auth.isStudent ? loadStudent() : loadTeacher()"
      >
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </div>

    <!-- ================= 学生 ================= -->
    <template v-if="auth.isStudent">
      <div v-if="loading" class="loading">正在加载签到信息…</div>

      <template v-else>
        <div class="card-title" style="margin-bottom: 10px">
          <span>进行中的签到</span>
          <span class="faint small">{{ openSessions.length }} 个</span>
        </div>

        <div v-if="!openSessions.length" class="card">
          <div class="empty">当前没有进行中的签到，收到通知后再来看看吧</div>
        </div>

        <div v-else class="grid cols-2">
          <div
            v-for="session in openSessions"
            :key="session.id"
            class="card"
            :style="{
              borderColor: isOpen(session) ? 'rgba(63,185,80,.45)' : '',
              marginTop: '0',
            }"
          >
            <div class="row between" style="align-items: flex-start">
              <div>
                <strong>{{ session.title }}</strong>
                <div class="faint small" style="margin-top: 4px">
                  {{ session.course_name }} · {{ session.class_name }}
                </div>
              </div>
              <span class="badge green">{{ remainingText(session.end_at) }}</span>
            </div>
            <div class="divider" />
            <div class="row between wrap">
              <span class="faint small">
                开始于 {{ formatDate(session.start_at, true) }}
              </span>
              <template v-if="session.record_status === 'present' || session.record_status === 'late'">
                <span class="badge" :class="attendanceLabel(session.record_status).tone">
                  已签到 · {{ attendanceLabel(session.record_status).label }}
                </span>
              </template>
              <button v-else class="btn primary sm" @click="openCheckIn(session)">
                签到
              </button>
            </div>
          </div>
        </div>

        <!-- 我的出勤 -->
        <div class="grid cols-4" style="margin-top: 18px">
          <div class="stat">
            <div class="stat-label">应签到次数</div>
            <div class="stat-value">{{ myAttendance?.total ?? 0 }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">正常</div>
            <div class="stat-value" style="color: var(--success)">
              {{ myAttendance?.present ?? 0 }}
            </div>
          </div>
          <div class="stat">
            <div class="stat-label">迟到</div>
            <div class="stat-value" style="color: var(--warning)">
              {{ myAttendance?.late ?? 0 }}
            </div>
          </div>
          <div class="stat">
            <div class="stat-label">出勤率</div>
            <div class="stat-value">{{ myAttendance?.rate ?? 0 }}%</div>
            <div class="progress" style="margin-top: 8px">
              <i :style="{ width: `${Math.min(100, myAttendance?.rate || 0)}%` }" />
            </div>
          </div>
        </div>

        <!-- 历史签到 -->
        <div class="card" style="margin-top: 18px">
          <div class="card-title">
            <span>历史签到</span>
            <button class="btn sm" :disabled="historyLoading" @click="loadHistory">
              {{ historyLoading ? '加载中…' : '刷新' }}
            </button>
          </div>
          <div v-if="historyLoading" class="loading">正在加载历史签到…</div>
          <div v-else-if="!history.length" class="empty">暂无历史签到记录</div>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>课程</th>
                  <th>教学班</th>
                  <th>签到主题</th>
                  <th>开始时间</th>
                  <th>结束时间</th>
                  <th>状态</th>
                  <th>我的出勤</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="session in history" :key="session.id">
                  <td>{{ session.course_name }}</td>
                  <td class="small">{{ session.class_name }}</td>
                  <td>{{ session.title }}</td>
                  <td class="small">{{ formatDate(session.start_at, true) }}</td>
                  <td class="small">{{ formatDate(session.end_at, true) }}</td>
                  <td>
                    <span class="badge" :class="isOpen(session) ? 'green' : 'gray'">
                      {{ isOpen(session) ? '进行中' : '已结束' }}
                    </span>
                  </td>
                  <td>
                    <span class="badge" :class="attendanceLabel(session.my_status).tone">
                      {{ attendanceLabel(session.my_status).label }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>

    <!-- ================= 教师 ================= -->
    <template v-else>
      <div v-if="loading" class="loading">正在加载教学班…</div>

      <template v-else>
        <div v-if="!classes.length" class="card">
          <div class="empty">你还没有教学班，先去创建课程与教学班</div>
        </div>

        <template v-else>
          <div class="card">
            <div class="card-title"><span>发起签到</span></div>
            <div class="form-row">
              <div class="field">
                <label>教学班</label>
                <select v-model="selectedClassId" class="select" @change="changeClass">
                  <option v-for="item in classes" :key="item.id" :value="item.id">
                    {{ classLabel(item) }} · {{ courseLabel(item) }}
                  </option>
                </select>
              </div>
              <div class="field">
                <label>签到主题</label>
                <input
                  v-model="sessionTitle"
                  class="input"
                  placeholder="例如：第 5 周课堂签到"
                  maxlength="64"
                />
              </div>
            </div>
            <div class="row between wrap">
              <span class="hint">签到方式：签到码（6 位数字） · 有效时长：5 分钟</span>
              <button class="btn primary" :disabled="creating" @click="createSession">
                {{ creating ? '发起中…' : '发起签到' }}
              </button>
            </div>
          </div>

          <div
            v-if="currentSession"
            class="card"
            style="margin-top: 16px; border-color: rgba(47, 129, 247, 0.45)"
          >
            <div class="card-title">
              <span>{{ currentSession.title }}</span>
              <span class="badge" :class="currentOpen ? 'green' : 'gray'">
                {{ currentOpen ? '进行中' : '已结束' }}
              </span>
            </div>
            <div class="row between wrap" style="align-items: flex-end">
              <div>
                <div class="faint small">签到码</div>
                <div
                  class="mono"
                  style="font-size: 56px; line-height: 1.15; letter-spacing: 12px; font-weight: 700; color: #79b8ff"
                >
                  {{ currentSession.code }}
                </div>
              </div>
              <div style="text-align: right">
                <div class="faint small">剩余时间</div>
                <div class="stat-value">{{ remainingText(currentSession.end_at) }}</div>
              </div>
            </div>
            <div class="divider" />
            <div class="row between wrap">
              <span class="faint small">
                {{ currentSession.course_name }} · {{ currentSession.class_name }} ·
                已签到 {{ currentSession.checked_count }} / {{ currentSession.student_total }}
              </span>
              <button
                v-if="currentOpen"
                class="btn danger sm"
                @click="closeSession(currentSession)"
              >
                结束签到
              </button>
            </div>
          </div>

          <div class="card" style="margin-top: 16px">
            <div class="card-title">
              <span>签到历史 · {{ selectedClass ? classLabel(selectedClass) : '' }}</span>
              <button class="btn sm" :disabled="sessionsLoading" @click="loadClassSessions">
                {{ sessionsLoading ? '加载中…' : '刷新' }}
              </button>
            </div>
            <div v-if="sessionsLoading" class="loading">正在加载签到记录…</div>
            <div v-else-if="!classSessions.length" class="empty">该教学班还没有签到记录</div>
            <div v-else class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>签到主题</th>
                    <th>方式</th>
                    <th>签到码</th>
                    <th>开始时间</th>
                    <th>结束时间</th>
                    <th>状态</th>
                    <th>出勤</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="session in classSessions" :key="session.id">
                    <td>{{ session.title }}</td>
                    <td class="small">{{ methodLabel(session.method) }}</td>
                    <td class="mono small">{{ session.code }}</td>
                    <td class="small">{{ formatDate(session.start_at, true) }}</td>
                    <td class="small">{{ formatDate(session.end_at, true) }}</td>
                    <td>
                      <span class="badge" :class="isOpen(session) ? 'green' : 'gray'">
                        {{ isOpen(session) ? '进行中' : '已结束' }}
                      </span>
                    </td>
                    <td class="small">
                      {{ session.checked_count }} / {{ session.student_total }}
                    </td>
                    <td>
                      <button
                        v-if="isOpen(session)"
                        class="btn sm danger"
                        @click="closeSession(session)"
                      >
                        结束
                      </button>
                      <span v-else class="faint small">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </template>
    </template>

    <!-- 学生签到弹窗 -->
    <div v-if="checkTarget" class="modal-mask" @click.self="checkTarget = null">
      <div class="modal" style="width: min(420px, 92vw)">
        <div class="modal-head">
          <h3>{{ checkTarget.title }}</h3>
          <button class="btn ghost sm" @click="checkTarget = null">关闭</button>
        </div>
        <p class="muted small" style="margin-top: 0">
          {{ checkTarget.course_name }} · {{ checkTarget.class_name }} ·
          剩余 {{ remainingText(checkTarget.end_at) }}
        </p>
        <div class="field">
          <label>签到码</label>
          <input
            v-model="checkCode"
            class="input mono"
            style="font-size: 26px; letter-spacing: 10px; text-align: center"
            maxlength="6"
            inputmode="numeric"
            placeholder="000000"
            @keyup.enter="doCheckIn"
          />
        </div>
        <div class="form-actions">
          <button class="btn" @click="checkTarget = null">取消</button>
          <button class="btn primary" :disabled="checking" @click="doCheckIn">
            {{ checking ? '签到中…' : '确认签到' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
