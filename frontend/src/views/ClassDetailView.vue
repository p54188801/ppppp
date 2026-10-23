<script setup>
/**
 * 教学班详情页
 * 职责：一个教学班的运营空间，按「作业 / 测验 / 签到 / 学生 / 成绩」五个标签页展示数据；
 *       教师与管理员可发布作业、新建测验、发起签到、结束签到并进入成绩册，学生只读。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, deadlineText, formatDate, relativeTime } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const classId = computed(() => Number(route.params.id))

const tabs = [
  { key: 'assignments', label: '作业' },
  { key: 'quizzes', label: '测验' },
  { key: 'attendance', label: '签到' },
  { key: 'students', label: '学生' },
  { key: 'grades', label: '成绩' },
]

const activeTab = ref('assignments')
const loading = ref(true)
const info = ref(null)
const assignments = ref([])
const quizzes = ref([])
const sessions = ref([])

const showAssignment = ref(false)
const assignmentForm = ref(emptyAssignment())
const savingAssignment = ref(false)

const showQuiz = ref(false)
const quizForm = ref(emptyQuiz())
const savingQuiz = ref(false)

const showAttendance = ref(false)
const attendanceForm = ref({ title: '课堂签到', method: 'code', duration: 5 })
const savingAttendance = ref(false)
const closingId = ref(0)

const canManage = computed(() => {
  if (!info.value) return false
  if (auth.isAdmin) return true
  return auth.isTeacher && Number(info.value.teacher_id) === Number(auth.user?.id)
})

const students = computed(() => info.value?.students || [])

function emptyAssignment() {
  return { title: '', content: '', full_score: 100, deadline: '', allow_late: true }
}

/** datetime-local 的值是本地时间，转成 ISO（UTC）再提交，避免后端按 UTC 解析造成时差。 */
function localToIso(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString()
}

function newQuestion(type = 'single') {
  return {
    type,
    stem: '',
    options: ['', '', '', ''],
    answer: type === 'single' ? 'A' : '正确',
    score: 5,
  }
}

function emptyQuiz() {
  return { title: '', duration: 30, questions: [newQuestion('single')] }
}

async function load() {
  loading.value = true
  try {
    info.value = await api.get(`/api/classes/${classId.value}`)
    const [assignmentList, quizList, sessionList] = await Promise.all([
      api.get(`/api/classes/${classId.value}/assignments`),
      api.get(`/api/classes/${classId.value}/quizzes`),
      api.get(`/api/classes/${classId.value}/attendance`),
    ])
    assignments.value = assignmentList || []
    quizzes.value = quizList || []
    sessions.value = sessionList || []
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

function openAssignmentForm() {
  assignmentForm.value = emptyAssignment()
  showAssignment.value = true
}

async function submitAssignment() {
  const title = assignmentForm.value.title.trim()
  if (!title) {
    ui.error('作业标题不能为空')
    return
  }
  savingAssignment.value = true
  try {
    await api.post('/api/assignments', {
      class_id: classId.value,
      title,
      content: assignmentForm.value.content.trim(),
      full_score: Number(assignmentForm.value.full_score) || 100,
      deadline: localToIso(assignmentForm.value.deadline),
      allow_late: Boolean(assignmentForm.value.allow_late),
    })
    ui.success('作业已发布')
    showAssignment.value = false
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingAssignment.value = false
  }
}

function openQuizForm() {
  quizForm.value = emptyQuiz()
  showQuiz.value = true
}

function addQuestion() {
  quizForm.value.questions.push(newQuestion('single'))
}

function removeQuestion(index) {
  if (quizForm.value.questions.length <= 1) {
    ui.error('至少保留一道题目')
    return
  }
  quizForm.value.questions.splice(index, 1)
}

function onQuestionTypeChange(question) {
  question.answer = question.type === 'single' ? 'A' : '正确'
}

async function submitQuiz() {
  const title = quizForm.value.title.trim()
  if (!title) {
    ui.error('测验标题不能为空')
    return
  }
  const questions = []
  for (let index = 0; index < quizForm.value.questions.length; index += 1) {
    const item = quizForm.value.questions[index]
    const stem = item.stem.trim()
    if (!stem) {
      ui.error(`第 ${index + 1} 题的题干不能为空`)
      return
    }
    if (item.type === 'single') {
      const options = item.options.map((option) => option.trim()).filter(Boolean)
      if (options.length < 2) {
        ui.error(`第 ${index + 1} 题至少需要两个选项`)
        return
      }
      questions.push({
        type: 'single',
        stem,
        options,
        answer: item.answer,
        score: Number(item.score) || 5,
      })
    } else {
      questions.push({
        type: 'judge',
        stem,
        options: [],
        answer: item.answer,
        score: Number(item.score) || 5,
      })
    }
  }

  savingQuiz.value = true
  try {
    await api.post('/api/quizzes', {
      class_id: classId.value,
      title,
      duration: Number(quizForm.value.duration) || 30,
      questions,
    })
    ui.success('测验已创建')
    showQuiz.value = false
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingQuiz.value = false
  }
}

function openAttendanceForm() {
  attendanceForm.value = { title: '课堂签到', method: 'code', duration: 5 }
  showAttendance.value = true
}

async function submitAttendance() {
  savingAttendance.value = true
  try {
    await api.post('/api/attendance', {
      class_id: classId.value,
      title: attendanceForm.value.title.trim() || '课堂签到',
      method: attendanceForm.value.method,
      duration: Number(attendanceForm.value.duration) || 5,
    })
    ui.success('签到已发起')
    showAttendance.value = false
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingAttendance.value = false
  }
}

async function closeSession(session) {
  const ok = await ui.confirm({
    title: '结束签到',
    message: `确定结束「${session.title}」吗？结束后学生不能再签到。`,
    confirmText: '结束签到',
    danger: true,
  })
  if (!ok) return
  closingId.value = session.id
  try {
    await api.post(`/api/attendance/${session.id}/close`, {})
    ui.success('签到已结束')
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    closingId.value = 0
  }
}

function openAssignment(id) {
  router.push({ name: 'assignment-detail', params: { id } })
}

function startQuiz(id) {
  router.push({ name: 'quiz-take', params: { id } })
}

function openGradebook() {
  router.push({ name: 'gradebook', params: { id: classId.value } })
}

function statusBadge(status) {
  if (status === 'present') return { class: 'green', text: '正常' }
  if (status === 'late') return { class: 'yellow', text: '迟到' }
  if (status === 'absent') return { class: 'red', text: '缺勤' }
  if (status === 'leave') return { class: 'gray', text: '请假' }
  return { class: 'gray', text: '未签到' }
}

function methodLabel(method) {
  if (method === 'qr') return '扫码'
  if (method === 'location') return '定位'
  return '签到码'
}

function submissionBadge(assignment) {
  const submission = assignment.my_submission
  if (!submission) return { class: 'gray', text: '未提交' }
  if (submission.status === 'graded') {
    const score = submission.score === null || submission.score === undefined ? '—' : submission.score
    return { class: 'green', text: `已批改 ${score} 分` }
  }
  if (submission.is_late) return { class: 'yellow', text: '迟交' }
  return { class: 'blue', text: '已提交' }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <div class="row small" style="gap: 6px; margin-bottom: 4px">
          <router-link :to="{ name: 'courses' }">课程</router-link>
          <span class="faint">/</span>
          <router-link v-if="info" :to="{ name: 'course-detail', params: { id: info.course_id } }">
            {{ info.course_name }}
          </router-link>
        </div>
        <h1>{{ info ? info.name : '教学班' }}</h1>
        <p v-if="info">
          {{ info.course_name }}（{{ info.course_code }}）· {{ info.teacher_name || '—' }} ·
          {{ info.term || info.semester || '未设置学期' }}
        </p>
      </div>
      <div class="row wrap">
        <span v-if="info" class="badge blue">{{ students.length }} / {{ info.capacity || 60 }} 人</span>
        <span v-if="info" class="badge gray mono">邀请码 {{ info.join_code }}</span>
        <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
        <button v-if="canManage" class="btn" @click="openGradebook">成绩册</button>
      </div>
    </div>

    <div v-if="loading" class="loading">正在加载教学班…</div>

    <template v-else-if="info">
      <div class="tabs">
        <div
          v-for="tab in tabs"
          :key="tab.key"
          class="tab"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </div>
      </div>

      <!-- ================= 作业 ================= -->
      <div v-if="activeTab === 'assignments'" class="card">
        <div class="card-title">
          <span>作业（{{ assignments.length }}）</span>
          <button v-if="canManage" class="btn sm primary" @click="openAssignmentForm">发布作业</button>
        </div>
        <div v-if="!assignments.length" class="empty">还没有发布作业</div>
        <div v-else class="table-wrap" style="border: none">
          <table>
            <thead>
              <tr>
                <th>标题</th>
                <th>满分</th>
                <th>截止时间</th>
                <th v-if="canManage">提交</th>
                <th v-else>我的状态</th>
                <th>创建时间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in assignments" :key="item.id">
                <td>
                  <div>{{ item.title }}</div>
                  <div class="faint small">{{ item.status === 'closed' ? '已关闭' : '进行中' }}</div>
                </td>
                <td class="mono small">{{ item.full_score }}</td>
                <td>
                  <span class="badge yellow">{{ deadlineText(item.deadline) }}</span>
                </td>
                <td v-if="canManage" class="small muted">
                  {{ item.submission_count || 0 }} / {{ item.student_total || 0 }}
                </td>
                <td v-else class="small">
                  <span class="badge" :class="submissionBadge(item).class">
                    {{ submissionBadge(item).text }}
                  </span>
                </td>
                <td class="small faint">{{ formatDate(item.created_at) }}</td>
                <td style="text-align: right">
                  <button class="btn sm" @click="openAssignment(item.id)">查看</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ================= 测验 ================= -->
      <div v-else-if="activeTab === 'quizzes'" class="card">
        <div class="card-title">
          <span>测验（{{ quizzes.length }}）</span>
          <button v-if="canManage" class="btn sm primary" @click="openQuizForm">新建测验</button>
        </div>
        <div v-if="!quizzes.length" class="empty">还没有创建测验</div>
        <div v-else class="table-wrap" style="border: none">
          <table>
            <thead>
              <tr>
                <th>标题</th>
                <th>题量</th>
                <th>时长</th>
                <th>总分</th>
                <th>作答人数</th>
                <th>创建时间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in quizzes" :key="item.id">
                <td>
                  <div>{{ item.title }}</div>
                  <div class="faint small">{{ item.status === 'published' ? '已发布' : item.status }}</div>
                </td>
                <td class="mono small">{{ item.question_count || 0 }}</td>
                <td class="mono small">{{ item.duration }} 分钟</td>
                <td class="mono small">{{ item.total_score }}</td>
                <td class="mono small">{{ item.attempt_count || 0 }}</td>
                <td class="small faint">{{ formatDate(item.created_at) }}</td>
                <td style="text-align: right">
                  <button v-if="auth.isStudent" class="btn sm primary" @click="startQuiz(item.id)">开始作答</button>
                  <span v-else class="small faint">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="auth.isStudent" class="hint" style="margin-top: 10px">
          测验一旦开始会按设定时长倒计时，请在「我的测验」中查看历史成绩。
        </div>
      </div>

      <!-- ================= 签到 ================= -->
      <div v-else-if="activeTab === 'attendance'" class="card">
        <div class="card-title">
          <span>签到（{{ sessions.length }}）</span>
          <button v-if="canManage" class="btn sm primary" @click="openAttendanceForm">发起签到</button>
        </div>
        <div v-if="!sessions.length" class="empty">还没有签到记录</div>
        <div v-else class="table-wrap" style="border: none">
          <table>
            <thead>
              <tr>
                <th>标题</th>
                <th>方式</th>
                <th v-if="canManage">签到码</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th v-if="canManage">签到情况</th>
                <th v-else>我的状态</th>
                <th>状态</th>
                <th v-if="canManage"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in sessions" :key="item.id">
                <td>{{ item.title }}</td>
                <td><span class="badge gray">{{ methodLabel(item.method) }}</span></td>
                <td v-if="canManage" class="mono">{{ item.code }}</td>
                <td class="small muted">{{ formatDate(item.start_at, true) }}</td>
                <td class="small muted">{{ formatDate(item.end_at, true) }}</td>
                <td v-if="canManage" class="mono small">
                  {{ item.checked_count || 0 }} / {{ item.student_total || 0 }}
                </td>
                <td v-else class="small">
                  <span class="badge" :class="statusBadge(item.my_status).class">
                    {{ statusBadge(item.my_status).text }}
                  </span>
                </td>
                <td>
                  <span class="badge" :class="item.status === 'open' ? 'green' : 'gray'">
                    {{ item.status === 'open' ? '进行中' : '已结束' }}
                  </span>
                </td>
                <td v-if="canManage" style="text-align: right">
                  <button
                    v-if="item.status === 'open'"
                    class="btn sm danger"
                    :disabled="closingId === item.id"
                    @click="closeSession(item)"
                  >
                    结束
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="auth.isStudent" class="hint" style="margin-top: 10px">
          前往「课堂签到」页面输入教师公布的签到码即可完成签到。
        </div>
      </div>

      <!-- ================= 学生 ================= -->
      <div v-else-if="activeTab === 'students'" class="card">
        <div class="card-title"><span>学生名单（{{ students.length }}）</span></div>
        <div v-if="!students.length" class="empty">教学班还没有学生</div>
        <div v-else class="table-wrap" style="border: none">
          <table>
            <thead>
              <tr>
                <th>学号</th>
                <th>姓名</th>
                <th>院系</th>
                <th>班级</th>
                <th>加入时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="student in students" :key="student.id">
                <td class="mono small">{{ student.number || '—' }}</td>
                <td>{{ student.real_name }}</td>
                <td class="small muted">{{ student.department || '—' }}</td>
                <td class="small muted">{{ student.class_name || '—' }}</td>
                <td class="small faint">{{ relativeTime(student.enrolled_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ================= 成绩 ================= -->
      <div v-else class="card">
        <div class="card-title"><span>成绩</span></div>
        <template v-if="canManage">
          <p class="muted" style="margin-top: 0">
            成绩册按「作业 / 测验 / 出勤 / 期末」加权计算总评，可配置权重、录入期末成绩并导出 CSV。
          </p>
          <button class="btn primary" @click="openGradebook">打开成绩册</button>
        </template>
        <template v-else>
          <p class="muted" style="margin-top: 0">
            成绩由教师录入，可在「我的成绩」页面查看自己的总评与绩点。
          </p>
          <router-link class="btn" :to="{ name: 'grades' }">查看我的成绩</router-link>
        </template>
      </div>
    </template>

    <div v-else class="empty">教学班不存在或你没有访问权限</div>

    <!-- 发布作业 -->
    <div v-if="showAssignment" class="modal-mask" @click.self="showAssignment = false">
      <form class="modal" @submit.prevent="submitAssignment">
        <div class="modal-head">
          <h3>发布作业</h3>
          <button type="button" class="btn ghost sm" @click="showAssignment = false">✕</button>
        </div>
        <div class="field">
          <label>作业标题</label>
          <input v-model="assignmentForm.title" class="input" placeholder="如 第三次上机：图的最短路径" maxlength="120" />
        </div>
        <div class="field">
          <label>作业要求</label>
          <textarea v-model="assignmentForm.content" class="textarea" placeholder="提交内容、格式与评分说明" maxlength="20000" />
        </div>
        <div class="form-row">
          <div class="field">
            <label>满分</label>
            <input v-model="assignmentForm.full_score" class="input" type="number" min="1" max="1000" />
          </div>
          <div class="field">
            <label>截止时间</label>
            <input v-model="assignmentForm.deadline" class="input" type="datetime-local" />
          </div>
        </div>
        <div class="field">
          <label class="row" style="gap: 8px">
            <input v-model="assignmentForm.allow_late" type="checkbox" style="width: auto" />
            <span>允许迟交（按天扣分）</span>
          </label>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showAssignment = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingAssignment">
            {{ savingAssignment ? '发布中…' : '发布' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 新建测验 -->
    <div v-if="showQuiz" class="modal-mask" @click.self="showQuiz = false">
      <form class="modal wide" @submit.prevent="submitQuiz">
        <div class="modal-head">
          <h3>新建测验</h3>
          <button type="button" class="btn ghost sm" @click="showQuiz = false">✕</button>
        </div>
        <div class="form-row">
          <div class="field">
            <label>测验标题</label>
            <input v-model="quizForm.title" class="input" placeholder="如 第 3 章随堂测验" maxlength="120" />
          </div>
          <div class="field">
            <label>答题时长（分钟）</label>
            <input v-model="quizForm.duration" class="input" type="number" min="1" max="300" />
          </div>
        </div>

        <div class="divider" />

        <div
          v-for="(question, index) in quizForm.questions"
          :key="index"
          class="card"
          style="margin-top: 0; margin-bottom: 12px; background: var(--surface-2)"
        >
          <div class="row between">
            <strong>第 {{ index + 1 }} 题</strong>
            <button type="button" class="btn sm danger" @click="removeQuestion(index)">删除</button>
          </div>

          <div class="form-row" style="margin-top: 10px">
            <div class="field">
              <label>题型</label>
              <select v-model="question.type" class="select" @change="onQuestionTypeChange(question)">
                <option value="single">单选题</option>
                <option value="judge">判断题</option>
              </select>
            </div>
            <div class="field">
              <label>分值</label>
              <input v-model="question.score" class="input" type="number" min="0.5" max="100" step="0.5" />
            </div>
          </div>

          <div class="field">
            <label>题干</label>
            <textarea v-model="question.stem" class="textarea" style="min-height: 68px" placeholder="请输入题目内容" maxlength="2000" />
          </div>

          <template v-if="question.type === 'single'">
            <div class="field">
              <label>选项（至少两个，答案用字母 A / B / C / D 对应）</label>
              <div v-for="(option, optionIndex) in question.options" :key="optionIndex" class="row" style="margin-bottom: 8px">
                <span class="mono small faint" style="width: 18px">{{ String.fromCharCode(65 + optionIndex) }}</span>
                <input
                  v-model="question.options[optionIndex]"
                  class="input"
                  :placeholder="`选项 ${String.fromCharCode(65 + optionIndex)}`"
                  maxlength="200"
                />
              </div>
            </div>
            <div class="field">
              <label>正确答案</label>
              <select v-model="question.answer" class="select">
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="C">C</option>
                <option value="D">D</option>
              </select>
            </div>
          </template>

          <div v-else class="field">
            <label>正确答案</label>
            <select v-model="question.answer" class="select">
              <option value="正确">正确</option>
              <option value="错误">错误</option>
            </select>
          </div>
        </div>

        <button type="button" class="btn block" @click="addQuestion">+ 添加题目</button>

        <div class="form-actions">
          <button type="button" class="btn" @click="showQuiz = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingQuiz">
            {{ savingQuiz ? '创建中…' : '创建测验' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 发起签到 -->
    <div v-if="showAttendance" class="modal-mask" @click.self="showAttendance = false">
      <form class="modal" @submit.prevent="submitAttendance">
        <div class="modal-head">
          <h3>发起签到</h3>
          <button type="button" class="btn ghost sm" @click="showAttendance = false">✕</button>
        </div>
        <div class="field">
          <label>签到标题</label>
          <input v-model="attendanceForm.title" class="input" maxlength="64" />
        </div>
        <div class="form-row">
          <div class="field">
            <label>签到方式</label>
            <select v-model="attendanceForm.method" class="select">
              <option value="code">签到码</option>
              <option value="qr">扫码</option>
            </select>
          </div>
          <div class="field">
            <label>持续时长（分钟）</label>
            <input v-model="attendanceForm.duration" class="input" type="number" min="1" max="120" />
          </div>
        </div>
        <div class="hint">发起后系统会生成签到码并通知教学班学生。</div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showAttendance = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingAttendance">
            {{ savingAttendance ? '发起中…' : '发起签到' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
