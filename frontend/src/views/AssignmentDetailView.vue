<script setup>
/**
 * 作业详情（学生 / 教师共用）
 *
 * 学生：查看作业要求与附件；未提交或已退回时可以填写内容并提交；
 *       已提交时展示提交内容、时间、迟交标记，批改后展示得分与评语。
 * 教师：查看提交统计（已交 / 已批改 / 均分），拉取提交名单做行内打分，
 *       并支持按「学号,分数」批量批改。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, deadlineText, formatDate } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const id = Number(route.params.id)
const loading = ref(true)
const failed = ref('')
const assignment = ref(null)

/* ---------------- 学生 ---------------- */
const content = ref('')
const submitting = ref(false)

/* ---------------- 教师 ---------------- */
const showSubmissions = ref(false)
const submissionsLoading = ref(false)
const submissions = ref([])
const notSubmitted = ref([])
const drafts = ref({})
const batchOpen = ref(false)
const batchText = ref('')
const batchBusy = ref(false)

const mySubmission = computed(() => assignment.value?.my_submission || null)
const attachments = computed(() => parseAttachments(assignment.value?.attachments))
const submissionAttachments = computed(() =>
  parseAttachments(mySubmission.value?.attachments),
)
const stats = computed(() => assignment.value?.stats || null)

const overdue = computed(() => {
  const deadline = assignment.value?.deadline
  if (!deadline) return false
  return new Date(deadline).getTime() < Date.now()
})

const canSubmit = computed(() => {
  if (submitting.value) return false
  if (!content.value.trim()) return false
  if (overdue.value && !assignment.value?.allow_late) return false
  return true
})

function parseAttachments(raw) {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function attachmentName(file) {
  if (!file) return '附件'
  if (typeof file === 'string') return file
  return file.name || file.filename || file.url || '附件'
}

function attachmentUrl(file) {
  if (!file || typeof file === 'string') return ''
  return file.url || file.path || ''
}

function submissionStatus(submission) {
  if (!submission) return { label: '未提交', tone: 'gray' }
  if (submission.status === 'graded') return { label: '已批改', tone: 'green' }
  if (submission.status === 'late') return { label: '迟交', tone: 'yellow' }
  if (submission.status === 'returned') return { label: '已退回', tone: 'red' }
  return { label: '已提交', tone: 'blue' }
}


// ---------------------------------------------------------------------------
// 提交进度（教师）
// ---------------------------------------------------------------------------
const progress = ref(null)
const progressTab = ref('missing')

async function loadProgress() {
  if (!(auth.isTeacher || auth.isAdmin)) return
  try {
    progress.value = await api.get(`/api/assignments/${id}/progress`)
  } catch {
    progress.value = null
  }
}

function submitLink() {
  return `${window.location.origin}${window.location.pathname}#/assignments/${id}`
}

async function copyLink() {
  const link = submitLink()
  try {
    await navigator.clipboard.writeText(link)
    ui.success('提交链接已复制，发给学生即可')
  } catch {
    window.prompt('复制下面的链接发给学生：', link)
  }
}

async function load() {
  loading.value = true
  failed.value = ''
  try {
    assignment.value = await api.get(`/api/assignments/${id}`)
  } catch (error) {
    assignment.value = null
    failed.value = error.message
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function submitWork() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    await api.post(`/api/assignments/${id}/submit`, {
      content: content.value,
      attachments: [],
    })
    ui.success('作业已提交')
    content.value = ''
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    submitting.value = false
  }
}

/* ---------------- 教师：提交名单与批改 ---------------- */

async function loadSubmissions() {
  submissionsLoading.value = true
  try {
    const data = await api.get(`/api/assignments/${id}/submissions`)
    submissions.value = data.submissions || []
    notSubmitted.value = data.not_submitted || []
    const next = {}
    submissions.value.forEach((row) => {
      next[row.id] = {
        score: row.score === null || row.score === undefined ? '' : row.score,
        feedback: row.feedback || '',
      }
    })
    drafts.value = next
  } catch (error) {
    ui.error(error.message)
  } finally {
    submissionsLoading.value = false
  }
}

function draftFor(row) {
  if (!drafts.value[row.id]) {
    drafts.value[row.id] = {
      score: row.score === null || row.score === undefined ? '' : row.score,
      feedback: row.feedback || '',
    }
  }
  return drafts.value[row.id]
}

async function toggleSubmissions() {
  showSubmissions.value = !showSubmissions.value
  if (showSubmissions.value) await loadSubmissions()
}

async function openBatch() {
  if (!submissions.value.length) await loadSubmissions()
  batchOpen.value = true
}

async function saveGrade(row) {
  const draft = draftFor(row)
  const fullScore = Number(assignment.value?.full_score || 100)
  const score = Number(draft.score)
  if (draft.score === '' || Number.isNaN(score)) {
    ui.error('请填写有效分数')
    return
  }
  if (score < 0 || score > fullScore) {
    ui.error(`分数需在 0 - ${fullScore} 之间`)
    return
  }
  row.grading = true
  try {
    await api.post(`/api/submissions/${row.id}/grade`, {
      score,
      feedback: draft.feedback || '',
    })
    ui.success(`已给 ${row.student_name || row.number} 打分`)
    await loadSubmissions()
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    row.grading = false
  }
}

function parseBatchRows() {
  const rows = []
  const errors = []
  const byNumber = new Map()
  submissions.value.forEach((row) => byNumber.set(String(row.number || ''), row))
  batchText.value.split(/\r?\n/).forEach((line, index) => {
    const text = line.trim()
    if (!text) return
    const parts = text.split(/[,，\t\s]+/).map((part) => part.trim()).filter(Boolean)
    if (parts.length < 2) {
      errors.push(`第 ${index + 1} 行格式不正确`)
      return
    }
    const [number, scoreText] = parts
    const target = byNumber.get(number)
    if (!target) {
      errors.push(`${number} 不在提交名单中`)
      return
    }
    const score = Number(scoreText)
    if (Number.isNaN(score)) {
      errors.push(`${number} 的分数无效`)
      return
    }
    rows.push({ submission_id: target.id, score, feedback: '' })
  })
  return { rows, errors }
}

async function submitBatch() {
  const { rows, errors } = parseBatchRows()
  if (!rows.length) {
    ui.error(errors[0] || '没有可提交的批改记录')
    return
  }
  if (errors.length) {
    const shown = errors.slice(0, 5).join('；')
    const ok = await ui.confirm({
      title: '部分行无法识别',
      message: `${shown}${errors.length > 5 ? ` 等 ${errors.length} 条` : ''}。仍要提交已识别的 ${rows.length} 条吗？`,
    })
    if (!ok) return
  }
  batchBusy.value = true
  try {
    const result = await api.post(`/api/assignments/${id}/batch-grade`, { rows })
    const updated = result?.updated || 0
    const failedRows = result?.failed || []
    ui.success(`已批改 ${updated} 份`)
    if (failedRows.length) ui.error(`有 ${failedRows.length} 条批改失败`)
    batchOpen.value = false
    batchText.value = ''
    showSubmissions.value = true
    await loadSubmissions()
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    batchBusy.value = false
  }
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push({ name: 'dashboard' })
}

onMounted(async () => {
  await load()
  await loadProgress()
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>{{ assignment ? assignment.title : '作业详情' }}</h1>
        <p v-if="assignment">
          {{ assignment.course_name }} · {{ assignment.class_name }}
        </p>
        <p v-else>查看作业要求与提交情况</p>
      </div>
      <div class="row wrap">
        <template v-if="auth.isTeacher && assignment">
          <button class="btn" :disabled="submissionsLoading" @click="toggleSubmissions">
            {{ showSubmissions ? '收起提交' : '查看提交' }}
          </button>
          <button class="btn" @click="openBatch">批量批改</button>
        </template>
        <button class="btn" @click="goBack">返回</button>
      </div>
    </div>


    <!-- 教师：提交进度 -->
    <div v-if="progress" class="card" style="margin-bottom: 16px">
      <div class="card-title">
        <span>提交情况</span>
        <div class="row" style="gap: 8px">
          <button class="btn sm" @click="copyLink">复制提交链接</button>
          <button class="btn sm" :disabled="!progress" @click="loadProgress">刷新</button>
        </div>
      </div>

      <div class="grid cols-4" style="margin-bottom: 12px">
        <div class="stat">
          <div class="stat-label">应交</div>
          <div class="stat-value">{{ progress.total }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">已交</div>
          <div class="stat-value" style="color: var(--success)">{{ progress.submitted_count }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">未交</div>
          <div class="stat-value" style="color: var(--danger)">{{ progress.missing_count }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">已批改</div>
          <div class="stat-value">{{ progress.graded_count }}</div>
        </div>
      </div>

      <div class="tabs" style="margin-bottom: 10px">
        <div class="tab" :class="{ active: progressTab === 'missing' }" @click="progressTab = 'missing'">
          未交（{{ progress.missing_count }}）
        </div>
        <div class="tab" :class="{ active: progressTab === 'submitted' }" @click="progressTab = 'submitted'">
          已交（{{ progress.submitted_count }}）
        </div>
      </div>

      <div v-if="progressTab === 'missing'">
        <div v-if="!progress.missing.length" class="empty" style="padding: 14px">
          全部交齐了 🎉
        </div>
        <div v-for="m in progress.missing" :key="m.student_id" class="row between"
             style="padding: 8px 0; border-bottom: 1px solid var(--border)">
          <span>{{ m.real_name }} <span class="faint small">{{ m.number }}</span></span>
          <span class="badge red">未交</span>
        </div>
      </div>

      <div v-else>
        <div v-for="s in progress.submitted" :key="s.student_id" class="row between"
             style="padding: 8px 0; border-bottom: 1px solid var(--border)">
          <span>{{ s.real_name }} <span class="faint small">{{ s.number }}</span></span>
          <span class="row" style="gap: 8px">
            <span v-if="s.late" class="badge yellow">迟交</span>
            <span v-if="s.score != null" class="badge green">{{ s.score }} 分</span>
            <span v-else class="badge gray">待批改</span>
          </span>
        </div>
      </div>

      <div class="hint" style="margin-top: 10px">
        学生点开链接 <span class="mono small">{{ submitLink() }}</span> 登录后直接就能提交。
      </div>
    </div>
    <div v-if="loading" class="loading">正在加载作业…</div>

    <div v-else-if="failed" class="card">
      <div class="empty">{{ failed }}</div>
    </div>

    <template v-else-if="assignment">
      <!-- 概览 -->
      <div class="grid cols-4">
        <div class="stat">
          <div class="stat-label">截止时间</div>
          <div class="stat-value" style="font-size: 18px">
            {{ assignment.deadline ? formatDate(assignment.deadline, true) : '长期有效' }}
          </div>
          <div class="stat-hint">{{ deadlineText(assignment.deadline) }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">满分</div>
          <div class="stat-value">{{ assignment.full_score }}</div>
          <div class="stat-hint">迟交 {{ assignment.allow_late ? '允许' : '不允许' }}</div>
        </div>

        <template v-if="auth.isTeacher && stats">
          <div class="stat">
            <div class="stat-label">已提交 / 已批改</div>
            <div class="stat-value">{{ stats.total }} / {{ stats.graded }}</div>
            <div class="stat-hint">共 {{ assignment.student_total }} 名学生</div>
          </div>
          <div class="stat">
            <div class="stat-label">提交平均分</div>
            <div class="stat-value">{{ stats.avg_score }}</div>
            <div class="stat-hint">最高 {{ stats.max_score }} · 最低 {{ stats.min_score }}</div>
          </div>
        </template>

        <template v-else>
          <div class="stat">
            <div class="stat-label">我的状态</div>
            <div class="stat-value" style="font-size: 20px">
              <span class="badge" :class="submissionStatus(mySubmission).tone">
                {{ submissionStatus(mySubmission).label }}
              </span>
            </div>
            <div class="stat-hint">
              {{ mySubmission?.submitted_at ? formatDate(mySubmission.submitted_at, true) : '尚未提交' }}
            </div>
          </div>
          <div class="stat">
            <div class="stat-label">我的得分</div>
            <div class="stat-value">
              {{ mySubmission?.score !== null && mySubmission?.score !== undefined ? mySubmission.score : '—' }}
            </div>
            <div class="stat-hint">满分 {{ assignment.full_score }}</div>
          </div>
        </template>
      </div>

      <!-- 作业正文 -->
      <div class="card" style="margin-top: 16px">
        <div class="card-title"><span>作业要求</span></div>
        <div style="white-space: pre-wrap">{{ assignment.content || '老师没有填写作业说明。' }}</div>

        <template v-if="attachments.length">
          <div class="divider" />
          <div class="small muted" style="margin-bottom: 6px">附件</div>
          <div class="tag-list">
            <template v-for="(file, index) in attachments" :key="index">
              <a
                v-if="attachmentUrl(file)"
                class="badge blue"
                :href="attachmentUrl(file)"
                target="_blank"
                rel="noreferrer"
              >
                {{ attachmentName(file) }}
              </a>
              <span v-else class="badge gray">{{ attachmentName(file) }}</span>
            </template>
          </div>
        </template>
      </div>

      <!-- ================= 学生：提交区 ================= -->
      <template v-if="auth.isStudent">
        <div
          v-if="!mySubmission || mySubmission.status === 'returned'"
          class="card"
          style="margin-top: 16px"
        >
          <div class="card-title">
            <span>{{ mySubmission?.status === 'returned' ? '重新提交' : '提交作业' }}</span>
            <span v-if="overdue && !assignment.allow_late" class="badge red">已截止，不可提交</span>
          </div>
          <div class="field">
            <label>作业内容</label>
            <textarea
              v-model="content"
              class="textarea"
              rows="8"
              placeholder="请输入作业内容，支持多行文本…"
            />
          </div>
          <div v-if="overdue && !assignment.allow_late" class="hint" style="color: var(--danger)">
            已过截止时间，且该作业不允许迟交。
          </div>
          <div class="form-actions">
            <button class="btn primary" :disabled="!canSubmit" @click="submitWork">
              {{ submitting ? '提交中…' : '提交作业' }}
            </button>
          </div>
        </div>

        <div v-else class="card" style="margin-top: 16px">
          <div class="card-title">
            <span>我的提交</span>
            <span class="badge" :class="submissionStatus(mySubmission).tone">
              {{ submissionStatus(mySubmission).label }}
            </span>
          </div>
          <div class="row wrap small muted" style="gap: 16px; margin-bottom: 10px">
            <span>提交时间：{{ formatDate(mySubmission.submitted_at, true) }}</span>
            <span v-if="mySubmission.is_late" style="color: var(--warning)">迟交</span>
          </div>
          <div style="white-space: pre-wrap">{{ mySubmission.content || '（未填写文字内容）' }}</div>

          <template v-if="submissionAttachments.length">
            <div class="divider" />
            <div class="tag-list">
              <span
                v-for="(file, index) in submissionAttachments"
                :key="index"
                class="badge gray"
              >
                {{ attachmentName(file) }}
              </span>
            </div>
          </template>

          <template v-if="mySubmission.status === 'graded'">
            <div class="divider" />
            <div class="row between wrap">
              <div class="row" style="gap: 10px">
                <span class="muted">得分</span>
                <span class="stat-value" style="font-size: 24px">
                  {{ mySubmission.score }}
                </span>
                <span class="faint">/ {{ assignment.full_score }}</span>
              </div>
              <span class="badge green">已批改</span>
            </div>
            <div class="small muted" style="margin-top: 8px">
              评语：{{ mySubmission.feedback || '老师没有留下评语' }}
            </div>
            <div class="hint" style="color: var(--warning)">作业已批改，不能再提交。</div>
            <div class="form-actions">
              <button class="btn" disabled>不可再次提交</button>
            </div>
          </template>

          <div v-else class="hint">老师批改后可以在这里看到得分与评语。</div>
        </div>
      </template>

      <!-- ================= 教师：提交名单 ================= -->
      <template v-if="auth.isTeacher">
        <div v-if="showSubmissions" class="card" style="margin-top: 16px">
          <div class="card-title">
            <span>提交名单（{{ submissions.length }}）</span>
            <button class="btn sm" :disabled="submissionsLoading" @click="loadSubmissions">
              {{ submissionsLoading ? '刷新中…' : '刷新' }}
            </button>
          </div>

          <div v-if="submissionsLoading" class="loading">正在加载提交…</div>
          <div v-else-if="!submissions.length" class="empty">还没有学生提交</div>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>学号</th>
                  <th>姓名</th>
                  <th>状态</th>
                  <th>提交时间</th>
                  <th>迟交</th>
                  <th>当前得分</th>
                  <th>打分</th>
                  <th>评语</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in submissions" :key="row.id">
                  <td class="mono small">{{ row.number || '—' }}</td>
                  <td>{{ row.student_name || '—' }}</td>
                  <td>
                    <span class="badge" :class="submissionStatus(row).tone">
                      {{ submissionStatus(row).label }}
                    </span>
                  </td>
                  <td class="small">{{ formatDate(row.submitted_at, true) }}</td>
                  <td>
                    <span v-if="row.is_late" class="badge yellow">迟交</span>
                    <span v-else class="faint small">—</span>
                  </td>
                  <td>{{ row.score === null || row.score === undefined ? '—' : row.score }}</td>
                  <td style="min-width: 92px">
                    <input
                      v-model="draftFor(row).score"
                      class="input"
                      type="number"
                      min="0"
                      :max="assignment.full_score"
                      style="padding: 5px 8px"
                    />
                  </td>
                  <td style="min-width: 160px">
                    <input
                      v-model="draftFor(row).feedback"
                      class="input"
                      placeholder="评语（可选）"
                      style="padding: 5px 8px"
                    />
                  </td>
                  <td>
                    <button
                      class="btn sm primary"
                      :disabled="row.grading"
                      @click="saveGrade(row)"
                    >
                      {{ row.grading ? '保存中…' : '保存' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <template v-if="notSubmitted.length">
            <div class="divider" />
            <div class="small muted" style="margin-bottom: 6px">
              未提交（{{ notSubmitted.length }}）
            </div>
            <div class="tag-list">
              <span v-for="student in notSubmitted" :key="student.id" class="badge gray">
                {{ student.number }} {{ student.real_name }}
              </span>
            </div>
          </template>
        </div>
      </template>
    </template>

    <!-- 批量批改弹窗 -->
    <div v-if="batchOpen" class="modal-mask" @click.self="batchOpen = false">
      <div class="modal">
        <div class="modal-head">
          <h3>批量批改</h3>
          <button class="btn ghost sm" @click="batchOpen = false">关闭</button>
        </div>
        <div class="field">
          <label>每行一条：学号,分数</label>
          <textarea
            v-model="batchText"
            class="textarea mono"
            rows="9"
            placeholder="20230001,88&#10;20230002,92&#10;20230003,76"
          />
          <div class="hint">只识别已提交且学号匹配的记录；分数需在 0 - {{ assignment?.full_score }} 之间。</div>
        </div>
        <div class="form-actions">
          <button class="btn" @click="batchOpen = false">取消</button>
          <button class="btn primary" :disabled="batchBusy" @click="submitBatch">
            {{ batchBusy ? '提交中…' : '提交批改' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
