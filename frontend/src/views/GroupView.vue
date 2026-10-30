<script setup>
/**
 * 班级群：微信式聊天 + 群作业。
 * - 老师发的作业消息点一下就能打开作业
 * - 提交作业用弹窗：支持文字 + 图片 + 文件
 * - 老师点作业卡片任意位置看「谁交了 / 谁没交」
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatDate, relativeTime } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const groups = ref([])
const current = ref(null)
const loading = ref(true)
const tab = ref('chat')
const draft = ref('')
const sending = ref(false)
const limit = ref(60)
const chatBox = ref(null)
const fileInput = ref(null)

/* 发布作业 */
const showAssign = ref(false)
const assignForm = ref(blankAssign())

/* 作业详情 */
const detail = ref(null)
const detailTab = ref('in')
const detailLoading = ref(false)
const submissions = ref([])

/* 签到 */
const activeCheckin = ref(null)
const showStartCheckin = ref(false)
const checkinForm = ref({ mode: 'number', answer: '', pattern: '🍎', minutes: 5 })
const checkinStatus = ref(null)
const checkinAnswer = ref('')
const checkinBusy = ref(false)
const patterns = ['🍎', '🍊', '🍋', '🍇', '🍓', '🍉', '🥝', '🍑']

/* 提交作业 */
const showSubmit = ref(false)
const submitTarget = ref(null)
const submitText = ref('')
const submitFile = ref(null)
const submitPreview = ref('')
const submitting = ref(false)
const submitFileInput = ref(null)

const groupId = computed(() => Number(route.params.id) || 0)
const isTeacher = computed(() => Boolean(current.value?.is_teacher))

function blankAssign() {
  return { title: '', content: '', full_score: 100, date: '', time: '23:59' }
}

async function loadGroups() {
  groups.value = await api.get('/api/groups').catch(() => [])
  if (!groupId.value && groups.value.length) {
    const id = groups.value[0].id
    router.replace({ name: 'group', params: { id } })
    current.value = await api.get(`/api/groups/${id}?limit=${limit.value}`).catch(() => null)
    loading.value = false
    return
  }
  if (groupId.value) await loadGroup()
  loading.value = false
}

async function loadGroup() {
  try {
    current.value = await api.get(`/api/groups/${groupId.value}?limit=${limit.value}`)
    activeCheckin.value = await api
      .get(`/api/groups/${groupId.value}/checkins/active`)
      .catch(() => null)
  } catch (error) {
    ui.error(error.message)
  }
}

function switchGroup(id) {
  router.push({ name: 'group', params: { id } })
}

async function loadMore() {
  limit.value += 60
  await loadGroup()
}

function isMine(m) {
  return Number(m.sender_id) === Number(auth.user?.id)
}

function roleBadge(m) {
  if (m.sender_role === 'teacher' || m.sender_role === 'admin') return { text: '老师', cls: 'teacher' }
  return { text: '学生', cls: 'student' }
}

/* ---------------------------- 聊天 ---------------------------- */
async function send() {
  if (!draft.value.trim() || sending.value) return
  sending.value = true
  try {
    await api.post(`/api/groups/${groupId.value}/messages`, { content: draft.value.trim() })
    draft.value = ''
    await loadGroup()
    scrollToBottom()
  } catch (error) {
    ui.error(error.message)
  } finally {
    sending.value = false
  }
}

async function pickFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  if (draft.value.trim()) form.append('content', draft.value.trim())
  sending.value = true
  try {
    await api.upload(`/api/groups/${groupId.value}/messages`, form)
    draft.value = ''
    await loadGroup()
    scrollToBottom()
  } catch (error) {
    ui.error(error.message)
  } finally {
    sending.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function downloadMessage(m) {
  const token = localStorage.getItem('eduflow_token') || ''
  const res = await fetch(`/api/messages/${m.id}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) return ui.error('下载失败')
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = m.file_name || 'file'
  a.click()
  URL.revokeObjectURL(a.href)
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = chatBox.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function openAssignmentFromMessage(m) {
  const found = (current.value?.assignments || []).find((a) => Number(a.id) === Number(m.ref_id))
  openAssignment(found || { id: m.ref_id, title: m.content })
}


/* ---------------------------- 签到 ---------------------------- */
async function startCheckin() {
  const form = checkinForm.value
  const answer = form.mode === 'pattern' ? form.pattern : form.answer.trim()
  if (!answer) return ui.error(form.mode === 'pattern' ? '请选择图案' : '请设置签到数字')
  checkinBusy.value = true
  try {
    await api.post(`/api/groups/${groupId.value}/checkins`, {
      mode: form.mode,
      answer,
      minutes: Number(form.minutes) || 5,
    })
    showStartCheckin.value = false
    checkinForm.value = { mode: 'number', answer: '', pattern: '🍎', minutes: 5 }
    ui.success('签到已开始')
    await loadGroup()
    scrollToBottom()
  } catch (error) {
    ui.error(error.message)
  } finally {
    checkinBusy.value = false
  }
}

async function doCheckin() {
  const answer = checkinForm.value.mode === 'pattern' ? checkinAnswer.value : checkinAnswer.value.trim()
  if (!answer && activeCheckin.value?.mode === 'number') return ui.error('请输入签到数字')
  checkinBusy.value = true
  try {
    await api.post(`/api/checkins/${activeCheckin.value.id}/respond`, { answer })
    ui.success('签到成功')
    checkinAnswer.value = ''
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  } finally {
    checkinBusy.value = false
  }
}

async function pickPattern(p) {
  checkinAnswer.value = p
  await doCheckin()
}

async function viewCheckinStatus(checkin) {
  try {
    checkinStatus.value = await api.get(`/api/checkins/${checkin.id}/status`)
  } catch (error) {
    ui.error(error.message)
  }
}

async function closeCheckin(checkin) {
  try {
    await api.post(`/api/checkins/${checkin.id}/close`)
    ui.success('签到已结束')
    checkinStatus.value = null
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  }
}

function remainText(c) {
  if (!c) return ''
  const left = Math.max(0, Math.round((new Date(c.ends_at) - Date.now()) / 1000))
  if (left <= 0) return '已结束'
  return `剩余 ${Math.floor(left / 60)} 分 ${left % 60} 秒`
}

/* ---------------------------- 发布作业 ---------------------------- */
const presets = [
  { label: '今晚 23:59', days: 0 },
  { label: '3 天后', days: 3 },
  { label: '一周后', days: 7 },
  { label: '两周后', days: 14 },
]

function applyPreset(p) {
  const d = new Date()
  d.setDate(d.getDate() + p.days)
  assignForm.value.date = d.toISOString().slice(0, 10)
  assignForm.value.time = '23:59'
}

function deadlineValue() {
  const { date, time } = assignForm.value
  if (!date) return ''
  return `${date}T${time || '23:59'}`
}

async function createAssignment() {
  if (!assignForm.value.title.trim()) return ui.error('请填写作业标题')
  try {
    await api.post(`/api/groups/${groupId.value}/assignments`, {
      title: assignForm.value.title.trim(),
      content: assignForm.value.content,
      full_score: Number(assignForm.value.full_score) || 100,
      deadline: deadlineValue(),
    })
    showAssign.value = false
    assignForm.value = blankAssign()
    await loadGroup()
    tab.value = 'assign'
    ui.success('作业已发布')
  } catch (error) {
    ui.error(error.message)
  }
}

/* ---------------------------- 作业详情 ---------------------------- */
async function openAssignment(item) {
  detail.value = item
  detailTab.value = 'in'
  detailLoading.value = true
  submissions.value = []
  try {
    if (isTeacher.value) {
      submissions.value = await api.get(`/api/group-assignments/${item.id}/submissions`)
    }
  } catch {
    submissions.value = []
  } finally {
    detailLoading.value = false
  }
}

const studentsInGroup = computed(() =>
  (current.value?.members || []).filter((m) => m.role === 'student'),
)

const submittedIds = computed(() => new Set(submissions.value.map((s) => Number(s.student_id))))

const missingStudents = computed(() =>
  studentsInGroup.value.filter((m) => !submittedIds.value.has(Number(m.id))),
)

function openSubmit(item) {
  submitTarget.value = item
  submitText.value = item?.my_submission?.content || ''
  submitFile.value = null
  submitPreview.value = item?.my_submission?.file_name || ''
  showSubmit.value = true
}

function pickSubmitFile() {
  submitFileInput.value?.click()
}

function onPickSubmitFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  submitFile.value = file
  submitPreview.value = `${file.name}（${(file.size / 1024).toFixed(0)} KB）`
}

async function doSubmit() {
  if (!submitText.value.trim() && !submitFile.value) {
    return ui.error('请填写内容或选择文件')
  }
  submitting.value = true
  try {
    const form = new FormData()
    form.append('content', submitText.value.trim())
    if (submitFile.value) form.append('file', submitFile.value)
    await api.upload(`/api/group-assignments/${submitTarget.value.id}/submit`, form)
    ui.success('提交成功')
    showSubmit.value = false
    await loadGroup()
    const target = (current.value?.assignments || []).find(
      (a) => Number(a.id) === Number(submitTarget.value.id),
    )
    if (target) await openAssignment(target)
  } catch (error) {
    ui.error(error.message)
  } finally {
    submitting.value = false
  }
}

async function grade(sub) {
  const full = detail.value?.full_score || 100
  const score = window.prompt(`给 ${sub.student_name} 打分（满分 ${full}）`, sub.score ?? '')
  if (score === null) return
  const feedback = window.prompt('评语（可留空）', sub.feedback || '') || ''
  try {
    await api.post(`/api/group-submissions/${sub.id}/grade`, { score: Number(score), feedback })
    ui.success('已打分')
    await openAssignment(detail.value)
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  }
}

async function downloadSubmission(sub) {
  const token = localStorage.getItem('eduflow_token') || ''
  const res = await fetch(`/api/group-submissions/${sub.id}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) return ui.error('下载失败')
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = sub.file_name || 'file'
  a.click()
  URL.revokeObjectURL(a.href)
}

watch(() => route.params.id, (id) => {
  if (id) loadGroup().then(scrollToBottom)
})

onMounted(async () => {
  await loadGroups()
  scrollToBottom()
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>班级群</h1>
        <p>同班师生自动在一个群里，可以聊天、发作业、交作业、批改</p>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else class="group-layout">
      <aside class="group-list card">
        <div class="card-title">我的班级</div>
        <div v-if="!groups.length" class="empty" style="text-align: center; padding: 18px 0">
          <div style="margin-bottom: 10px">你还没有加入班级群</div>
          <div class="faint small" style="margin-bottom: 12px">去个人中心填上班级，就会自动进群</div>
          <button class="btn primary sm" @click="router.push({ name: 'profile' })">
            去个人中心设置班级
          </button>
        </div>
        <div
          v-for="g in groups"
          :key="g.id"
          class="group-item"
          :class="{ active: g.id === groupId }"
          @click="switchGroup(g.id)"
        >
          <div class="row between">
            <strong>{{ g.name }}</strong>
            <span class="badge gray">{{ g.member_count }} 人</span>
          </div>
        </div>
      </aside>

      <section v-if="current" class="card group-main">
        <div class="card-title">
          <span>{{ current.name }} · {{ current.members.length }} 人</span>
          <span class="badge blue">{{ isTeacher ? '老师' : '学生' }}</span>
        </div>

        <div class="tabs">
          <div class="tab" :class="{ active: tab === 'chat' }" @click="tab = 'chat'">聊天</div>
          <!-- 进行中的签到 -->
          <div v-if="activeCheckin" class="checkin-banner">
            <div class="checkin-head">
              <span class="checkin-title">📢 正在签到</span>
              <span class="badge yellow">{{ remainText(activeCheckin) }}</span>
              <span v-if="isTeacher" class="badge blue">
                {{ activeCheckin.checked_count }} / {{ activeCheckin.total_students }} 已签
              </span>
            </div>

            <div v-if="isTeacher" class="checkin-body">
              <span class="faint small">签到内容：{{ activeCheckin.mode === 'pattern' ? activeCheckin.answer : '数字 ' + activeCheckin.answer }}</span>
              <div class="row" style="gap: 8px">
                <button class="btn sm" @click="viewCheckinStatus(activeCheckin)">查看谁没签</button>
                <button class="btn sm" @click="closeCheckin(activeCheckin)">结束签到</button>
              </div>
            </div>

            <div v-else-if="activeCheckin.my_record" class="checkin-body">
              <span class="badge green">✅ 你已完成签到</span>
            </div>

            <div v-else-if="activeCheckin.mode === 'number'" class="checkin-body">
              <input
                v-model="checkinAnswer"
                class="input"
                placeholder="输入老师说的数字"
                style="max-width: 200px"
                @keyup.enter="doCheckin"
              />
              <button class="btn primary sm" :disabled="checkinBusy" @click="doCheckin">签到</button>
            </div>

            <div v-else class="checkin-body">
              <span class="faint small">选出老师指定的图案：</span>
              <div class="pattern-row">
                <button
                  v-for="p in patterns"
                  :key="p"
                  class="pattern-btn"
                  :disabled="checkinBusy"
                  @click="pickPattern(p)"
                >
                  {{ p }}
                </button>
              </div>
            </div>
          </div>

          <div class="tab" :class="{ active: tab === 'assign' }" @click="tab = 'assign'">
            作业（{{ current.assignments.length }}）
          </div>
        </div>

        <!-- 聊天 -->
        <template v-if="tab === 'chat'">
          
          <div ref="chatBox" class="chat-box">
            <div v-if="current.messages.length >= limit" style="text-align: center; margin-bottom: 8px">
              <button class="btn sm" @click="loadMore">查看更早的消息</button>
            </div>
            <div v-for="m in current.messages" :key="m.id" class="msg-row" :class="{ mine: isMine(m) }">
              <div class="msg-avatar" :class="roleBadge(m).cls">
                {{ (m.sender_name || '?').slice(0, 1) }}
              </div>
              <div class="msg-main">
                <div class="msg-head" :class="{ right: isMine(m) }">
                  <span class="msg-name">{{ m.sender_name }}</span>
                  <span class="role-pill" :class="roleBadge(m).cls">{{ roleBadge(m).text }}</span>
                  <span class="msg-time">{{ relativeTime(m.created_at) }}</span>
                </div>
                <div
                  class="bubble"
                  :class="{ mine: isMine(m), clickable: m.kind === 'assignment' }"
                  @click="m.kind === 'assignment' && openAssignmentFromMessage(m)"
                >
                  <div v-if="m.content && m.kind !== 'assignment'" class="bubble-text">{{ m.content }}</div>
                  <div v-if="m.kind === 'assignment'" class="bubble-assign">
                    <div class="assign-title">📋 {{ m.content }}</div>
                    <div class="assign-hint">点击查看作业 · 提交 · 提交情况</div>
                  </div>
                  <div v-if="m.file_name" class="bubble-file">
                    <span>{{ m.kind === 'image' ? '🖼' : '📎' }} {{ m.file_name }}</span>
                    <button class="btn sm" @click.stop="downloadMessage(m)">下载</button>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="!current.messages.length" class="empty">还没有消息，打个招呼吧</div>
          </div>

          <div class="chat-input">
            <input v-model="draft" class="input" placeholder="输入消息…" @keyup.enter="send" />
            <button class="btn" :disabled="sending" @click="fileInput.click()">图片/文件</button>
            <input ref="fileInput" type="file" style="display: none" @change="pickFile" />
            <button class="btn primary" :disabled="sending || !draft.trim()" @click="send">发送</button>
          </div>
        </template>

        <!-- 作业列表 -->
        <template v-else>
          <div class="row between" style="margin-bottom: 12px">
            <span class="muted small">共 {{ current.assignments.length }} 份作业</span>
            <div class="row" style="gap: 8px">
              <button v-if="isTeacher" class="btn sm" @click="showStartCheckin = true">发起签到</button>
              <button v-if="isTeacher" class="btn primary sm" @click="showAssign = true">发布作业</button>
            </div>
          </div>

          <div
            v-for="a in current.assignments"
            :key="a.id"
            class="assign-card"
            @click="openAssignment(a)"
          >
            <div class="assign-head">
              <div class="assign-name">{{ a.title }}</div>
              <span class="badge gray">{{ a.submission_count }} 人已交</span>
            </div>
            <div class="assign-meta">
              {{ a.teacher_name }} · 满分 {{ a.full_score }}
              <span v-if="a.deadline"> · 截止 {{ formatDate(a.deadline, true) }}</span>
            </div>
            <div class="assign-foot">
              <span v-if="!isTeacher" class="badge" :class="a.my_submission ? 'green' : 'yellow'">
                {{ a.my_submission ? (a.my_submission.score != null ? `已批改 ${a.my_submission.score} 分` : '已提交') : '未提交' }}
              </span>
              <span class="assign-link">查看详情 →</span>
            </div>
          </div>
          <div v-if="!current.assignments.length" class="empty">还没有作业</div>
        </template>
      </section>
      <section v-else class="card group-main empty">请选择一个班级群</section>
    </div>

    <!-- 发布作业 -->
    <div v-if="showAssign" class="modal-mask" @click.self="showAssign = false">
      <div class="modal" style="width: min(560px, 94vw)">
        <div class="modal-head"><h3>发布作业</h3></div>
        <div class="field">
          <label>标题</label>
          <input v-model="assignForm.title" class="input" placeholder="例如：第一次上机作业" />
        </div>
        <div class="field">
          <label>要求</label>
          <textarea v-model="assignForm.content" class="textarea" rows="4" placeholder="作业说明…" />
        </div>
        <div class="grid cols-2" style="gap: 12px">
          <div class="field">
            <label>满分</label>
            <input v-model="assignForm.full_score" class="input" type="number" />
          </div>
          <div class="field">
            <label>截止时间</label>
            <div class="row" style="gap: 8px">
              <input v-model="assignForm.date" class="input" type="date" />
              <input v-model="assignForm.time" class="input" type="time" style="width: 118px" />
            </div>
          </div>
        </div>
        <div class="row wrap" style="gap: 8px; margin-bottom: 12px">
          <span class="faint small">快捷：</span>
          <button v-for="p in presets" :key="p.label" class="btn sm" @click="applyPreset(p)">
            {{ p.label }}
          </button>
        </div>
        <div class="form-actions">
          <button class="btn" @click="showAssign = false">取消</button>
          <button class="btn primary" @click="createAssignment">发布作业</button>
        </div>
      </div>
    </div>

    <!-- 作业详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal" style="width: min(680px, 96vw)">
        <div class="modal-head">
          <h3>{{ detail.title }}</h3>
          <button class="btn sm" @click="detail = null">关闭</button>
        </div>

        <div class="detail-meta">
          满分 {{ detail.full_score || 100 }}
          <span v-if="detail.deadline"> · 截止 {{ formatDate(detail.deadline, true) }}</span>
        </div>
        <p v-if="detail.content" class="detail-content">{{ detail.content }}</p>

        <template v-if="isTeacher">
          <div v-if="detailLoading" class="loading">加载中…</div>
          <template v-else>
            <div class="grid cols-3" style="margin: 14px 0">
              <div class="stat">
                <div class="stat-label">应交</div>
                <div class="stat-value">{{ studentsInGroup.length }}</div>
              </div>
              <div class="stat">
                <div class="stat-label">已交</div>
                <div class="stat-value" style="color: var(--success)">{{ submissions.length }}</div>
              </div>
              <div class="stat">
                <div class="stat-label">未交</div>
                <div class="stat-value" style="color: var(--danger)">{{ missingStudents.length }}</div>
              </div>
            </div>

            <div class="tabs" style="margin-bottom: 8px">
              <div class="tab" :class="{ active: detailTab === 'in' }" @click="detailTab = 'in'">
                已交（{{ submissions.length }}）
              </div>
              <div class="tab" :class="{ active: detailTab === 'out' }" @click="detailTab = 'out'">
                未交（{{ missingStudents.length }}）
              </div>
            </div>

            <div v-if="detailTab === 'in'" class="list-box">
              <div v-for="s in submissions" :key="s.id" class="list-row">
                <div>
                  <strong>{{ s.student_name }}</strong>
                  <div class="faint small">{{ s.content || '（无文字内容）' }}</div>
                </div>
                <div class="row" style="gap: 8px">
                  <button v-if="s.file_name" class="btn sm" @click="downloadSubmission(s)">附件</button>
                  <span v-if="s.score != null" class="badge green">{{ s.score }} 分</span>
                  <button class="btn sm" @click="grade(s)">打分</button>
                </div>
              </div>
              <div v-if="!submissions.length" class="empty">还没有人提交</div>
            </div>

            <div v-else class="list-box">
              <div v-for="s in missingStudents" :key="s.id" class="list-row">
                <span>{{ s.real_name }} <span class="faint small">{{ s.username }}</span></span>
                <span class="badge red">未交</span>
              </div>
              <div v-if="!missingStudents.length" class="empty">全部交齐了 🎉</div>
            </div>
          </template>
        </template>

        <template v-else>
          <div v-if="detail.my_submission" class="my-submission">
            <div class="row between">
              <strong>我的提交</strong>
              <span v-if="detail.my_submission.score != null" class="badge green">
                {{ detail.my_submission.score }} 分
              </span>
              <span v-else class="badge yellow">待批改</span>
            </div>
            <div v-if="detail.my_submission.content" class="detail-content">
              {{ detail.my_submission.content }}
            </div>
            <div v-if="detail.my_submission.feedback" class="faint small">
              评语：{{ detail.my_submission.feedback }}
            </div>
          </div>
          <button class="btn primary block" style="margin-top: 14px" @click="openSubmit(detail)">
            {{ detail.my_submission ? '重新提交' : '提交作业' }}
          </button>
        </template>
      </div>
    </div>

    <!-- 提交作业 -->
    <div v-if="showSubmit" class="modal-mask" @click.self="showSubmit = false">
      <div class="modal" style="width: min(620px, 96vw)">
        <div class="modal-head">
          <h3>提交：{{ submitTarget?.title }}</h3>
          <button class="btn sm" @click="showSubmit = false">关闭</button>
        </div>

        <div class="field">
          <label>作业内容</label>
          <textarea
            v-model="submitText"
            class="textarea"
            rows="6"
            placeholder="写出你的答案、思路、遇到的问题…"
          />
        </div>

        <div class="field">
          <label>图片 / 文件（可选）</label>
          <div class="upload-box" @click="pickSubmitFile">
            <input ref="submitFileInput" type="file" style="display: none" @change="onPickSubmitFile" />
            <template v-if="submitPreview">
              <span class="upload-name">📎 {{ submitPreview }}</span>
              <button class="btn sm" @click.stop="submitFile = null; submitPreview = ''">移除</button>
            </template>
            <template v-else>
              <span class="upload-icon">＋</span>
              <span class="faint small">点击选择图片、文档或压缩包</span>
            </template>
          </div>
        </div>

        <div class="form-actions">
          <button class="btn" @click="showSubmit = false">取消</button>
          <button class="btn primary" :disabled="submitting" @click="doSubmit">
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 发起签到 -->
    <div v-if="showStartCheckin" class="modal-mask" @click.self="showStartCheckin = false">
      <div class="modal" style="width: min(520px, 94vw)">
        <div class="modal-head"><h3>发起签到</h3></div>

        <div class="field">
          <label>签到方式</label>
          <div class="row" style="gap: 12px">
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="checkinForm.mode" type="radio" value="number" /> 数字
            </label>
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="checkinForm.mode" type="radio" value="pattern" /> 图案
            </label>
          </div>
        </div>

        <div v-if="checkinForm.mode === 'number'" class="field">
          <label>签到数字</label>
          <input
            v-model="checkinForm.answer"
            class="input"
            placeholder="例如 3721，学生在群里输入同样的数字才算签到"
          />
        </div>

        <div v-else class="field">
          <label>指定图案</label>
          <div class="pattern-row" style="margin-top: 6px">
            <button
              v-for="p in patterns"
              :key="p"
              class="pattern-btn"
              :class="{ active: checkinForm.pattern === p }"
              @click="checkinForm.pattern = p"
            >
              {{ p }}
            </button>
          </div>
        </div>

        <div class="field">
          <label>持续时长（分钟）</label>
          <input v-model="checkinForm.minutes" class="input" type="number" min="1" max="60" style="max-width: 120px" />
        </div>

        <div class="form-actions">
          <button class="btn" @click="showStartCheckin = false">取消</button>
          <button class="btn primary" :disabled="checkinBusy" @click="startCheckin">开始签到</button>
        </div>
      </div>
    </div>

    <!-- 签到情况 -->
    <div v-if="checkinStatus" class="modal-mask" @click.self="checkinStatus = null">
      <div class="modal" style="width: min(620px, 96vw)">
        <div class="modal-head">
          <h3>签到情况</h3>
          <button class="btn sm" @click="checkinStatus = null">关闭</button>
        </div>

        <div class="grid cols-3" style="margin: 10px 0">
          <div class="stat"><div class="stat-label">应交</div><div class="stat-value">{{ checkinStatus.total }}</div></div>
          <div class="stat"><div class="stat-label">已签</div><div class="stat-value" style="color: var(--success)">{{ checkinStatus.checked_count }}</div></div>
          <div class="stat"><div class="stat-label">未签</div><div class="stat-value" style="color: var(--danger)">{{ checkinStatus.missing_count }}</div></div>
        </div>

        <div class="row" style="gap: 10px; align-items: flex-start">
          <div style="flex: 1">
            <div class="stat-label" style="margin-bottom: 6px">未签到（{{ checkinStatus.missing_count }}）</div>
            <div class="list-box">
              <div v-for="s in checkinStatus.missing" :key="s.student_id" class="list-row">
                <span>{{ s.real_name }} <span class="faint small">{{ s.number }}</span></span>
                <span class="badge red">未签</span>
              </div>
              <div v-if="!checkinStatus.missing.length" class="empty">全部到齐 🎉</div>
            </div>
          </div>
          <div style="flex: 1">
            <div class="stat-label" style="margin-bottom: 6px">已签到（{{ checkinStatus.checked_count }}）</div>
            <div class="list-box">
              <div v-for="s in checkinStatus.checked" :key="s.student_id" class="list-row">
                <span>{{ s.real_name }} <span class="faint small">{{ s.number }}</span></span>
                <span class="badge green">已签</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.group-layout { display: grid; grid-template-columns: 240px 1fr; gap: 16px; align-items: start; }
.group-item { padding: 10px 12px; border-radius: 10px; cursor: pointer; margin-bottom: 6px; }
.group-item:hover { background: #f3f9ff; }
.group-item.active { background: linear-gradient(135deg, rgba(255,200,87,.25), rgba(255,138,61,.18)); }

.chat-box { max-height: 52vh; overflow-y: auto; padding: 4px 6px 4px 2px; }
.msg-row { display: flex; gap: 10px; margin-bottom: 16px; align-items: flex-start; }
.msg-row.mine { flex-direction: row-reverse; }
.msg-avatar {
  width: 34px; height: 34px; border-radius: 10px; flex-shrink: 0;
  display: grid; place-items: center; font-size: 14px; font-weight: 650; color: #fff;
}
.msg-avatar.teacher { background: linear-gradient(135deg, #ffc857, #ff9f43); }
.msg-avatar.student { background: linear-gradient(135deg, #6fb6ff, #3e8ef7); }
.msg-main { max-width: 74%; min-width: 0; }
.msg-head { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.msg-head.right { justify-content: flex-end; }
.msg-name { font-size: 12.5px; color: var(--text-dim); }
.msg-time { font-size: 11px; color: var(--text-faint); }
.role-pill { font-size: 10.5px; padding: 1px 7px; border-radius: 999px; font-weight: 600; }
.role-pill.teacher { background: #fff3d6; color: #a86a00; border: 1px solid #ffd88a; }
.role-pill.student { background: #e3f0ff; color: #1a6fc4; border: 1px solid #b6d8ff; }
.bubble {
  background: #fff; border: 1px solid var(--border); border-radius: 12px;
  padding: 9px 12px; box-shadow: 0 2px 8px rgba(63,110,180,.06);
  display: inline-block; max-width: 100%; text-align: left;
}
.bubble.clickable { cursor: pointer; }
.bubble.clickable:hover { border-color: #ffb347; box-shadow: 0 6px 18px rgba(255,138,61,.18); }
.msg-row.mine .bubble { background: linear-gradient(135deg,#ffb347,#ff8a3d); border-color: transparent; color: #fff; }
.msg-row.mine .bubble .bubble-text { color: #fff; }
.bubble-text { white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.55; }
.bubble-assign { display: flex; flex-direction: column; gap: 2px; }
.assign-title { font-weight: 650; }
.assign-hint { font-size: 11.5px; opacity: .75; }
.bubble-file { display: flex; gap: 10px; align-items: center; font-size: 13px; margin-top: 4px; }

.chat-input { display: flex; gap: 8px; margin-top: 14px; }

.assign-card {
  border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; margin-bottom: 10px;
  background: #fff; cursor: pointer; transition: box-shadow .15s, transform .15s;
}
.assign-card:hover { box-shadow: 0 10px 24px rgba(63,110,180,.14); transform: translateY(-1px); border-color: #ffc857; }
.assign-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.assign-name { font-size: 15px; font-weight: 650; color: #1d3557; }
.assign-meta { font-size: 12.5px; color: var(--text-dim); margin-top: 4px; }
.assign-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; }
.assign-link { font-size: 12.5px; color: var(--primary); font-weight: 600; }

.detail-meta { font-size: 12.5px; color: var(--text-dim); margin-bottom: 8px; }
.detail-content { white-space: pre-wrap; line-height: 1.6; margin: 6px 0 10px; }
.list-box { max-height: 320px; overflow-y: auto; }
.list-row { display: flex; justify-content: space-between; align-items: center; gap: 10px;
  padding: 9px 2px; border-bottom: 1px solid var(--border); }
.my-submission { background: #f7fbff; border: 1px solid var(--border); border-radius: 12px; padding: 12px; }

.upload-box {
  border: 2px dashed var(--border-strong); border-radius: 12px; padding: 18px;
  display: flex; align-items: center; justify-content: center; gap: 10px;
  cursor: pointer; background: #fbfdff; transition: border-color .15s, background .15s;
}
.upload-box:hover { border-color: var(--primary); background: #fff8f2; }
.upload-icon { font-size: 20px; color: var(--primary); }
.upload-name { font-size: 13px; color: #1d3557; }

@media (max-width: 900px) {
  .group-layout { grid-template-columns: 1fr; }
  .chat-box { max-height: 46vh; }
  .chat-input { flex-wrap: wrap; }
  .chat-input .input { flex: 1 1 100%; }
  .chat-input .btn { flex: 1 1 auto; }
}

/* 签到 */
.checkin-banner {
  border: 1px solid #ffd88a;
  background: linear-gradient(135deg, rgba(255, 214, 102, 0.22), rgba(255, 138, 61, 0.12));
  border-radius: 12px; padding: 10px 12px; margin-bottom: 10px;
}
.checkin-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.checkin-title { font-weight: 700; color: #8a5a00; }
.checkin-body { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
.pattern-row { display: flex; gap: 8px; flex-wrap: wrap; }
.pattern-btn {
  font-size: 22px; line-height: 1; padding: 8px 10px; border-radius: 12px;
  border: 1px solid var(--border); background: #fff; cursor: pointer;
  transition: transform .12s, border-color .12s;
}
.pattern-btn:hover { transform: translateY(-2px); border-color: var(--primary); }
.pattern-btn.active { border-color: var(--primary); background: #fff4e8; }

</style>
