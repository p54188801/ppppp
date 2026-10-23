<script setup>
/**
 * 成绩册页（仅教师 / 管理员）
 * 职责：展示教学班成绩统计与明细，配置四项权重与及格线，行内录入期末成绩与加分，
 *       并把整份成绩册导出为 CSV（带 token 的二进制下载）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, getToken, percent } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()

const classId = computed(() => Number(route.params.id))

const loading = ref(true)
const book = ref(null)
const ruleForm = ref({
  assignment_weight: 0.4,
  quiz_weight: 0.2,
  attendance_weight: 0.1,
  final_weight: 0.3,
  pass_score: 60,
})
const inputs = ref({})
const savingRule = ref(false)
const savingRowId = ref(0)
const exporting = ref(false)

const stats = computed(() => book.value?.stats || {})
const rows = computed(() => book.value?.rows || [])

const weightSum = computed(() => {
  const form = ruleForm.value
  return (
    (Number(form.assignment_weight) || 0) +
    (Number(form.quiz_weight) || 0) +
    (Number(form.attendance_weight) || 0) +
    (Number(form.final_weight) || 0)
  )
})

const weightValid = computed(() => Math.abs(weightSum.value - 1) <= 0.001)

function numberText(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return number.toFixed(digits)
}

function syncInputs() {
  const next = {}
  rows.value.forEach((row) => {
    next[row.student_id] = {
      final_score: row.final_score === null || row.final_score === undefined ? '' : String(row.final_score),
      bonus: row.bonus === null || row.bonus === undefined ? '' : String(row.bonus),
    }
  })
  inputs.value = next
}

function syncRule() {
  const rule = book.value?.rule
  if (!rule) return
  ruleForm.value = {
    assignment_weight: Number(rule.assignment_weight ?? 0.4),
    quiz_weight: Number(rule.quiz_weight ?? 0.2),
    attendance_weight: Number(rule.attendance_weight ?? 0.1),
    final_weight: Number(rule.final_weight ?? 0.3),
    pass_score: Number(rule.pass_score ?? 60),
  }
}

async function load() {
  loading.value = true
  try {
    book.value = await api.get(`/api/classes/${classId.value}/gradebook`)
    syncRule()
    syncInputs()
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function saveRule() {
  if (!weightValid.value) {
    ui.error(`四项权重之和必须为 1，当前为 ${weightSum.value.toFixed(2)}`)
    return
  }
  savingRule.value = true
  try {
    await api.put(`/api/classes/${classId.value}/grade-rule`, {
      assignment_weight: Number(ruleForm.value.assignment_weight) || 0,
      quiz_weight: Number(ruleForm.value.quiz_weight) || 0,
      attendance_weight: Number(ruleForm.value.attendance_weight) || 0,
      final_weight: Number(ruleForm.value.final_weight) || 0,
      pass_score: Number(ruleForm.value.pass_score) || 60,
    })
    ui.success('权重已保存')
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingRule.value = false
  }
}

async function saveRow(row) {
  const input = inputs.value[row.student_id] || {}
  const finalText = String(input.final_score ?? '').trim()
  const bonusText = String(input.bonus ?? '').trim()
  if (finalText !== '' && (Number.isNaN(Number(finalText)) || Number(finalText) < 0 || Number(finalText) > 100)) {
    ui.error('期末成绩必须是 0 ~ 100 之间的数字')
    return
  }
  if (bonusText !== '' && Number.isNaN(Number(bonusText))) {
    ui.error('加分必须是数字')
    return
  }
  savingRowId.value = row.student_id
  try {
    await api.post(`/api/classes/${classId.value}/grades`, {
      student_id: row.student_id,
      final_score: finalText === '' ? null : Number(finalText),
      bonus: bonusText === '' ? 0 : Number(bonusText),
    })
    ui.success(`已保存 ${row.real_name} 的成绩`)
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingRowId.value = 0
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    const response = await fetch(`/api/classes/${classId.value}/grades/export`, {
      headers: { Authorization: `Bearer ${getToken()}` },
      credentials: 'same-origin',
    })
    if (!response.ok) {
      let message = `导出失败（HTTP ${response.status}）`
      try {
        const payload = await response.json()
        if (payload && payload.error && payload.error.message) message = payload.error.message
      } catch {
        /* 响应体不是 JSON */
      }
      throw new Error(message)
    }
    const blob = await response.blob()
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = `gradebook_${classId.value}.csv`
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(href)
    ui.success('成绩册已导出')
  } catch (error) {
    ui.error(error.message)
  } finally {
    exporting.value = false
  }
}

function goBack() {
  router.push({ name: 'class-detail', params: { id: classId.value } })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <div class="row small" style="gap: 6px; margin-bottom: 4px">
          <a href="#" @click.prevent="goBack">教学班</a>
          <span class="faint">/</span>
          <span class="faint">成绩册</span>
        </div>
        <h1>{{ book ? `${book.class.course_name} · ${book.class.name}` : '成绩册' }}</h1>
        <p v-if="book">
          教师 {{ book.class.teacher_name || '—' }} · 及格线 {{ book.rule.pass_score }} 分 ·
          权重 作业 {{ book.rule.assignment_weight }} / 测验 {{ book.rule.quiz_weight }} / 出勤
          {{ book.rule.attendance_weight }} / 期末 {{ book.rule.final_weight }}
        </p>
      </div>
      <div class="row">
        <button class="btn" :disabled="loading" @click="load">刷新</button>
        <button class="btn primary" :disabled="exporting || !rows.length" @click="exportCsv">
          {{ exporting ? '导出中…' : '导出 CSV' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">正在计算成绩…</div>

    <template v-else-if="book">
      <div class="grid cols-3">
        <div class="stat">
          <div class="stat-label">学生人数</div>
          <div class="stat-value">{{ stats.count || 0 }}</div>
          <div class="stat-hint">教学班在册学生</div>
        </div>
        <div class="stat">
          <div class="stat-label">平均分</div>
          <div class="stat-value">{{ numberText(stats.average) }}</div>
          <div class="stat-hint">按当前权重计算</div>
        </div>
        <div class="stat">
          <div class="stat-label">最高分 / 最低分</div>
          <div class="stat-value">{{ numberText(stats.max) }} / {{ numberText(stats.min) }}</div>
          <div class="stat-hint">总评区间</div>
        </div>
        <div class="stat">
          <div class="stat-label">及格率</div>
          <div class="stat-value">{{ percent(stats.pass_rate) }}</div>
          <div class="stat-hint">及格 {{ stats.pass_count || 0 }} 人</div>
          <div class="progress" style="margin-top: 10px">
            <i :style="{ width: `${Math.min(100, Number(stats.pass_rate) || 0)}%` }" />
          </div>
        </div>
        <div class="stat">
          <div class="stat-label">优秀率</div>
          <div class="stat-value">{{ percent(stats.excellent_rate) }}</div>
          <div class="stat-hint">90 分及以上 {{ stats.excellent_count || 0 }} 人</div>
          <div class="progress" style="margin-top: 10px">
            <i
              :style="{
                width: `${Math.min(100, Number(stats.excellent_rate) || 0)}%`,
                background: 'var(--success)',
              }"
            />
          </div>
        </div>
        <div class="stat">
          <div class="stat-label">当前权重合计</div>
          <div
            class="stat-value"
            :style="{ color: weightValid ? 'var(--success)' : 'var(--danger)' }"
          >
            {{ weightSum.toFixed(2) }}
          </div>
          <div class="stat-hint">必须等于 1.00</div>
        </div>
      </div>

      <!-- 权重配置 -->
      <div class="card">
        <div class="card-title">
          <span>成绩权重配置</span>
          <span class="faint small">总评 = 作业 × w1 + 测验 × w2 + 出勤 × w3 + 期末 × w4 + 加分</span>
        </div>
        <div class="grid cols-3">
          <div class="field">
            <label>作业权重</label>
            <input v-model.number="ruleForm.assignment_weight" class="input" type="number" step="0.05" min="0" max="1" />
          </div>
          <div class="field">
            <label>测验权重</label>
            <input v-model.number="ruleForm.quiz_weight" class="input" type="number" step="0.05" min="0" max="1" />
          </div>
          <div class="field">
            <label>出勤权重</label>
            <input v-model.number="ruleForm.attendance_weight" class="input" type="number" step="0.05" min="0" max="1" />
          </div>
          <div class="field">
            <label>期末权重</label>
            <input v-model.number="ruleForm.final_weight" class="input" type="number" step="0.05" min="0" max="1" />
          </div>
          <div class="field">
            <label>及格线</label>
            <input v-model.number="ruleForm.pass_score" class="input" type="number" min="0" max="100" />
          </div>
          <div class="field">
            <label>权重合计</label>
            <div class="input mono" :style="{ color: weightValid ? 'var(--success)' : 'var(--danger)' }">
              {{ weightSum.toFixed(2) }}{{ weightValid ? ' ✓' : ' ✗ 必须为 1' }}
            </div>
          </div>
        </div>
        <div class="form-actions">
          <button class="btn primary" :disabled="savingRule || !weightValid" @click="saveRule">
            {{ savingRule ? '保存中…' : '保存权重' }}
          </button>
        </div>
      </div>

      <!-- 成绩明细 -->
      <div class="card">
        <div class="card-title">
          <span>成绩明细</span>
          <span class="faint small">期末与加分可直接在表格中修改，保存后自动重算总评</span>
        </div>
        <div v-if="!rows.length" class="empty">教学班还没有学生</div>
        <div v-else class="table-wrap" style="border: none">
          <table>
            <thead>
              <tr>
                <th>学号</th>
                <th>姓名</th>
                <th>作业</th>
                <th>测验</th>
                <th>出勤</th>
                <th>期末</th>
                <th>加分</th>
                <th>总评</th>
                <th>绩点</th>
                <th>状态</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.student_id">
                <td class="mono small">{{ row.number || '—' }}</td>
                <td>{{ row.real_name }}</td>
                <td class="mono small">{{ numberText(row.assignment_score, 1) }}</td>
                <td class="mono small">{{ numberText(row.quiz_score, 1) }}</td>
                <td class="mono small">{{ numberText(row.attendance_score, 1) }}</td>
                <td>
                  <input
                    v-model="inputs[row.student_id].final_score"
                    class="input mono"
                    style="width: 84px"
                    type="number"
                    min="0"
                    max="100"
                    step="0.5"
                    placeholder="未录入"
                  />
                </td>
                <td>
                  <input
                    v-model="inputs[row.student_id].bonus"
                    class="input mono"
                    style="width: 72px"
                    type="number"
                    min="-20"
                    max="20"
                    step="1"
                    placeholder="0"
                  />
                </td>
                <td class="mono">
                  <strong>{{ numberText(row.total, 1) }}</strong>
                </td>
                <td class="mono small">{{ numberText(row.grade_point, 1) }}</td>
                <td>
                  <span class="badge" :class="row.passed ? 'green' : 'red'">
                    {{ row.passed ? '通过' : '未通过' }}
                  </span>
                </td>
                <td style="text-align: right">
                  <button class="btn sm" :disabled="savingRowId === row.student_id" @click="saveRow(row)">
                    {{ savingRowId === row.student_id ? '保存中…' : '保存' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-else class="empty">暂无成绩册数据</div>
  </div>
</template>
