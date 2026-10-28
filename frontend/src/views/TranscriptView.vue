<script setup>
/**
 * 我的成绩单（学生端）
 *
 * 通过 GET /api/my/transcript 拉取已选课程的加权成绩：
 * 顶部展示总学分、GPA、平均分，表格按教学班列出作业、测验、出勤、期末、
 * 总评与绩点，总评用颜色区分（90 分以上绿色，60-89 蓝色，60 以下红色）。
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const loading = ref(true)
const transcript = ref(null)

const rows = computed(() => transcript.value?.rows || [])
const totalCredits = computed(() => transcript.value?.total_credits ?? 0)
const gpa = computed(() => transcript.value?.gpa ?? 0)
const average = computed(() => transcript.value?.average ?? 0)
const passedCount = computed(() => rows.value.filter((row) => row.passed).length)

function scoreColor(score) {
  const value = Number(score)
  if (Number.isNaN(value)) return 'var(--text-dim)'
  if (value >= 90) return 'var(--success)'
  if (value >= 60) return 'var(--primary)'
  return 'var(--danger)'
}

function scoreTone(score) {
  const value = Number(score)
  if (Number.isNaN(value)) return 'gray'
  if (value >= 90) return 'green'
  if (value >= 60) return 'blue'
  return 'red'
}

function displayScore(value) {
  if (value === null || value === undefined) return '—'
  return value
}

async function load() {
  loading.value = true
  try {
    transcript.value = await api.get('/api/my/transcript')
  } catch (error) {
    transcript.value = null
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function exportCsv() {
  try {
    const token = localStorage.getItem('eduflow_token') || ''
    const res = await fetch('/api/my/transcript/export', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error('导出失败')
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = '我的成绩单.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (err) {
    ui.error(err.message)
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>我的成绩</h1>
        <p>按教学班汇总作业、测验、出勤与期末成绩，生成加权总评与绩点</p>
      </div>
      <button class="btn primary" :disabled="loading" @click="exportCsv">导出 CSV</button>
      <button class="btn" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新成绩' }}
      </button>
    </div>

    <div v-if="loading" class="loading">正在计算成绩…</div>

    <template v-else>
      <div class="grid cols-3">
        <div class="stat">
          <div class="stat-label">总学分</div>
          <div class="stat-value">{{ totalCredits }}</div>
          <div class="stat-hint">{{ rows.length }} 个教学班</div>
        </div>
        <div class="stat">
          <div class="stat-label">GPA</div>
          <div class="stat-value" :style="{ color: scoreColor(gpa * 25) }">{{ gpa }}</div>
          <div class="stat-hint">按学分加权，4.0 制</div>
        </div>
        <div class="stat">
          <div class="stat-label">平均分</div>
          <div class="stat-value" :style="{ color: scoreColor(average) }">{{ average }}</div>
          <div class="stat-hint">通过 {{ passedCount }} / {{ rows.length }} 门</div>
        </div>
      </div>

      <div class="card" style="margin-top: 18px">
        <div class="card-title">
          <span>成绩明细</span>
          <span class="faint small">总评 = 作业 / 测验 / 出勤 / 期末加权</span>
        </div>

        <div v-if="!rows.length" class="empty">还没有成绩记录，先去选课吧</div>

        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>课程</th>
                <th>班级</th>
                <th>学分</th>
                <th>作业</th>
                <th>测验</th>
                <th>出勤</th>
                <th>期末</th>
                <th style="min-width: 140px">总评</th>
                <th>绩点</th>
                <th>是否通过</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.class_id">
                <td>{{ row.course_name || '—' }}</td>
                <td class="small">{{ row.class_name || '—' }}</td>
                <td>{{ row.credits }}</td>
                <td>{{ displayScore(row.assignment_score) }}</td>
                <td>{{ displayScore(row.quiz_score) }}</td>
                <td>{{ displayScore(row.attendance_score) }}</td>
                <td>{{ displayScore(row.final_score) }}</td>
                <td>
                  <div class="row between" style="gap: 8px">
                    <span class="mono" :style="{ color: scoreColor(row.total) }">
                      {{ row.total }}
                    </span>
                    <span class="badge" :class="scoreTone(row.total)">
                      {{ row.total >= 90 ? '优秀' : row.total >= 60 ? '及格' : '不及格' }}
                    </span>
                  </div>
                  <div class="progress" style="margin-top: 5px">
                    <i
                      :style="{
                        width: `${Math.min(100, Math.max(0, row.total))}%`,
                        background: scoreColor(row.total),
                      }"
                    />
                  </div>
                </td>
                <td :style="{ color: scoreColor(row.grade_point * 25) }">{{ row.grade_point }}</td>
                <td>
                  <span class="badge" :class="row.passed ? 'green' : 'red'">
                    {{ row.passed ? '通过' : '未通过' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="rows.some((row) => row.remark)" class="divider" />
        <div v-for="row in rows" :key="`remark-${row.class_id}`">
          <div v-if="row.remark" class="small faint">
            {{ row.course_name }}：{{ row.remark }}
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
