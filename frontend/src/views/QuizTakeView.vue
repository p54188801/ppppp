<script setup>
/**
 * 在线测验答题页（学生端）
 *
 * 进入页面先调用 POST /api/quizzes/{id}/start 领取试卷（题目顺序可能被打乱），
 * 逐题作答：单选 / 多选 / 判断 / 填空 / 简答；答案每 10 秒自动暂存，
 * 顶部展示倒计时，时间到自动交卷。交卷后展示得分、满分与正确率。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatDate } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()

const quizId = Number(route.params.id)

const loading = ref(true)
const startError = ref('')
const quiz = ref(null)
const questions = ref([])
const answers = ref({})
const remaining = ref(0)
const deadline = ref('')
const submitting = ref(false)
const submitted = ref(false)
const result = ref(null)
const saveState = ref('')
const lastSavedAt = ref('')

let tickTimer = null
let saveTimer = null

const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

function letterAt(index) {
  return letters[index] || String(index + 1)
}

const answeredCount = computed(
  () => questions.value.filter((question) => String(answers.value[question.id] || '').trim()).length,
)
const progressPercent = computed(() => {
  if (!questions.value.length) return 0
  return Math.round((answeredCount.value / questions.value.length) * 100)
})
const timeText = computed(() => {
  const total = Math.max(0, remaining.value)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})
const lowTime = computed(() => remaining.value <= 60)

function multiSelected(question) {
  return String(answers.value[question.id] || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

function isMultiChecked(question, letter) {
  return multiSelected(question).includes(letter)
}

function toggleMulti(question, letter) {
  const current = multiSelected(question)
  const next = current.includes(letter)
    ? current.filter((item) => item !== letter)
    : [...current, letter].sort()
  answers.value[question.id] = next.join(',')
}

function clearTimers() {
  if (tickTimer) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
  if (saveTimer) {
    window.clearInterval(saveTimer)
    saveTimer = null
  }
}

async function start() {
  loading.value = true
  startError.value = ''
  try {
    const data = await api.post(`/api/quizzes/${quizId}/start`)
    quiz.value = data.quiz
    questions.value = data.questions || []
    answers.value = { ...(data.saved_answers || {}) }
    remaining.value = Number(data.remaining_seconds || 0)
    deadline.value = data.deadline || ''
    tickTimer = window.setInterval(tick, 1000)
    saveTimer = window.setInterval(autoSave, 10000)
  } catch (error) {
    startError.value = error.message
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

function tick() {
  if (submitted.value || submitting.value) return
  remaining.value = Math.max(0, remaining.value - 1)
  if (remaining.value === 0) {
    clearTimers()
    submit(true)
  }
}

function answerPayload() {
  const payload = {}
  Object.keys(answers.value).forEach((key) => {
    const value = answers.value[key]
    if (typeof value === 'string' && value.trim()) payload[key] = value.trim()
  })
  return payload
}

async function autoSave() {
  if (submitted.value || submitting.value || !quiz.value) return
  try {
    await api.put(`/api/quizzes/${quizId}/answers`, { answers: answerPayload() })
    saveState.value = '已自动保存'
    lastSavedAt.value = formatDate(new Date().toISOString(), true)
  } catch {
    saveState.value = '自动保存失败'
  }
}

async function submit(auto = false) {
  if (submitted.value || submitting.value) return
  if (!auto) {
    const ok = await ui.confirm({
      title: '交卷',
      message: `已作答 ${answeredCount.value} / ${questions.value.length} 题，交卷后不能修改答案，确定交卷吗？`,
    })
    if (!ok) return
  }
  if (tickTimer) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
  if (saveTimer) {
    window.clearInterval(saveTimer)
    saveTimer = null
  }
  submitting.value = true
  try {
    result.value = await api.post(`/api/quizzes/${quizId}/submit`, {
      answers: answerPayload(),
    })
    submitted.value = true
    saveState.value = ''
    ui.success(auto ? '时间到，已自动交卷' : '交卷成功')
  } catch (error) {
    ui.error(error.message)
    // 手动交卷失败时恢复计时，避免倒计时停住
    if (!auto && remaining.value > 0) {
      if (!tickTimer) tickTimer = window.setInterval(tick, 1000)
      if (!saveTimer) saveTimer = window.setInterval(autoSave, 10000)
    }
  } finally {
    submitting.value = false
  }
}

function backToDashboard() {
  router.push({ name: 'dashboard' })
}

function leaveQuiz() {
  // 答题中离开时保留进度（后端会自动暂存），这里只提示将保留已保存答案
  if (submitted.value) {
    backToDashboard()
    return
  }
  ui.confirm({
    title: '离开答题',
    message: '离开后本次答题进度会保留，但计时不会暂停，确定离开吗？',
    danger: true,
  }).then((ok) => {
    if (ok) backToDashboard()
  })
}

onMounted(start)
onUnmounted(clearTimers)
</script>

<template>
  <div>
    <div v-if="loading" class="loading">正在准备试卷…</div>

    <div v-else-if="startError" class="card">
      <div class="empty">{{ startError }}</div>
      <div class="form-actions">
        <button class="btn primary" @click="backToDashboard">返回工作台</button>
      </div>
    </div>

    <template v-else-if="quiz">
      <!-- 顶部信息与倒计时 -->
      <div class="page-head">
        <div>
          <h1>{{ quiz.title }}</h1>
          <p>
            共 {{ questions.length }} 题 · 满分 {{ quiz.total_score }} 分 · 限时
            {{ quiz.duration }} 分钟
          </p>
        </div>
        <div class="row wrap">
          <div class="stat" style="padding: 8px 14px">
            <div class="stat-label">剩余时间</div>
            <div
              class="stat-value mono"
              style="font-size: 22px"
              :style="{ color: lowTime ? 'var(--danger)' : '' }"
            >
              {{ submitted ? '已交卷' : timeText }}
            </div>
          </div>
          <button v-if="!submitted" class="btn" :disabled="submitting" @click="submit(false)">
            {{ submitting ? '交卷中…' : '交卷' }}
          </button>
          <button class="btn ghost" @click="leaveQuiz">退出</button>
        </div>
      </div>

      <!-- 交卷结果 -->
      <div v-if="submitted && result" class="card" style="margin-bottom: 16px">
        <div class="card-title">
          <span>交卷结果</span>
          <span class="badge green">已完成</span>
        </div>
        <div class="grid cols-3">
          <div class="stat">
            <div class="stat-label">我的得分</div>
            <div class="stat-value">{{ result.score }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">满分</div>
            <div class="stat-value">{{ result.total_score }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">正确率</div>
            <div class="stat-value">{{ result.rate }}%</div>
            <div class="progress" style="margin-top: 8px">
              <i :style="{ width: `${Math.min(100, result.rate || 0)}%` }" />
            </div>
          </div>
        </div>
        <div class="form-actions">
          <button class="btn primary" @click="backToDashboard">返回工作台</button>
        </div>
      </div>

      <template v-if="!submitted">
        <div class="card" style="margin-bottom: 16px">
          <div class="row between wrap">
            <span class="small muted">
              已作答 {{ answeredCount }} / {{ questions.length }} 题
            </span>
            <span class="small faint">
              {{ saveState }}
              <template v-if="lastSavedAt"> · {{ lastSavedAt }}</template>
            </span>
          </div>
          <div class="progress" style="margin-top: 8px">
            <i :style="{ width: `${progressPercent}%` }" />
          </div>
          <div class="hint">
            截止 {{ deadline ? formatDate(deadline, true) : '—' }} · 答案每 10 秒自动保存
          </div>
        </div>

        <div
          v-for="(question, index) in questions"
          :key="question.id"
          class="card"
          style="margin-bottom: 14px"
        >
          <div class="row between" style="align-items: flex-start">
            <div style="min-width: 0">
              <div class="row wrap" style="gap: 8px">
                <strong>第 {{ index + 1 }} 题</strong>
                <span class="badge blue">{{ question.type_label || question.type }}</span>
                <span class="badge gray">{{ question.score }} 分</span>
              </div>
              <div style="margin-top: 8px; white-space: pre-wrap">{{ question.stem }}</div>
            </div>
          </div>

          <!-- 单选 -->
          <div v-if="question.type === 'single'" style="margin-top: 12px">
            <label
              v-for="(option, optionIndex) in question.options"
              :key="optionIndex"
              class="row"
              style="gap: 8px; padding: 6px 0; cursor: pointer"
            >
              <input
                type="radio"
                :name="`q-${question.id}`"
                :checked="answers[question.id] === letterAt(optionIndex)"
                @change="answers[question.id] = letterAt(optionIndex)"
              />
              <span class="badge gray">{{ letterAt(optionIndex) }}</span>
              <span>{{ option }}</span>
            </label>
          </div>

          <!-- 多选 -->
          <div v-else-if="question.type === 'multi'" style="margin-top: 12px">
            <label
              v-for="(option, optionIndex) in question.options"
              :key="optionIndex"
              class="row"
              style="gap: 8px; padding: 6px 0; cursor: pointer"
            >
              <input
                type="checkbox"
                :checked="isMultiChecked(question, letterAt(optionIndex))"
                @change="toggleMulti(question, letterAt(optionIndex))"
              />
              <span class="badge gray">{{ letterAt(optionIndex) }}</span>
              <span>{{ option }}</span>
            </label>
          </div>

          <!-- 判断 -->
          <div v-else-if="question.type === 'judge'" style="margin-top: 12px">
            <label class="row" style="gap: 8px; padding: 6px 0; cursor: pointer">
              <input
                type="radio"
                :name="`q-${question.id}`"
                :checked="answers[question.id] === '对'"
                @change="answers[question.id] = '对'"
              />
              <span>正确</span>
            </label>
            <label class="row" style="gap: 8px; padding: 6px 0; cursor: pointer">
              <input
                type="radio"
                :name="`q-${question.id}`"
                :checked="answers[question.id] === '错'"
                @change="answers[question.id] = '错'"
              />
              <span>错误</span>
            </label>
          </div>

          <!-- 填空 -->
          <div v-else-if="question.type === 'fill'" style="margin-top: 12px">
            <input
              v-model="answers[question.id]"
              class="input"
              placeholder="请输入答案"
            />
          </div>

          <!-- 简答 -->
          <div v-else style="margin-top: 12px">
            <textarea
              v-model="answers[question.id]"
              class="textarea"
              rows="4"
              placeholder="请输入你的作答内容…"
            />
          </div>
        </div>

        <div class="card">
          <div class="row between wrap">
            <span class="small faint">
              交卷后不可修改；未作答的题目按 0 分计。
            </span>
            <button class="btn primary" :disabled="submitting" @click="submit(false)">
              {{ submitting ? '交卷中…' : '交卷' }}
            </button>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
