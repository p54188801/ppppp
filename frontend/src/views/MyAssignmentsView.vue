<script setup>
/**
 * 我的作业（学生端）
 *
 * 按「全部 / 待提交 / 已提交 / 已批改」四个维度浏览本学期所有作业。
 * 数据来自 GET /api/my/assignments（可用 status=pending|submitted|graded 过滤），
 * 卡片上展示课程、教学班、截止时间、提交状态与我的得分，点击进入作业详情。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, deadlineText, formatDate } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const router = useRouter()

const tabs = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待提交' },
  { key: 'submitted', label: '已提交' },
  { key: 'graded', label: '已批改' },
]

const activeTab = ref('')
const loading = ref(true)
const items = ref([])

async function load() {
  loading.value = true
  try {
    const params = activeTab.value ? { status: activeTab.value } : undefined
    items.value = (await api.get('/api/my/assignments', params)) || []
  } catch (error) {
    items.value = []
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  load()
}

/** 提交状态 -> 徽章文案与颜色 */
function statusOf(item) {
  if (item.submission_status === 'graded') return { label: '已批改', tone: 'green' }
  if (item.submission_status === 'late') return { label: '迟交', tone: 'yellow' }
  if (item.submission_status === 'returned') return { label: '已退回', tone: 'red' }
  if (item.submission_status) return { label: '已提交', tone: 'blue' }
  return { label: '未提交', tone: 'gray' }
}

/** 截止时间徽章：过期红、3 小时内黄、其余灰 */
function deadlineBadge(item) {
  if (!item.deadline) return 'gray'
  const diff = new Date(item.deadline).getTime() - Date.now()
  if (Number.isNaN(diff)) return 'gray'
  if (diff < 0) return 'red'
  if (diff < 3 * 3600 * 1000) return 'yellow'
  return 'gray'
}

function openDetail(item) {
  router.push({ name: 'assignment-detail', params: { id: item.id } })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>我的作业</h1>
        <p>查看作业要求、按时提交，并跟踪批改结果</p>
      </div>
      <button class="btn" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </div>

    <div class="tabs">
      <div
        v-for="tab in tabs"
        :key="tab.key"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        @click="switchTab(tab.key)"
      >
        {{ tab.label }}
      </div>
    </div>

    <div v-if="loading" class="loading">正在加载作业…</div>

    <div v-else-if="!items.length" class="card">
      <div class="empty">这里还没有作业，去「我的课程」看看吧</div>
    </div>

    <div v-else class="grid cols-2">
      <div
        v-for="item in items"
        :key="item.id"
        class="card"
        style="cursor: pointer; margin-top: 0"
        @click="openDetail(item)"
      >
        <div class="row between" style="align-items: flex-start">
          <div style="min-width: 0">
            <div class="row wrap" style="gap: 8px">
              <strong style="font-size: 14.5px">{{ item.title }}</strong>
              <span class="badge" :class="statusOf(item).tone">{{ statusOf(item).label }}</span>
            </div>
            <div class="faint small" style="margin-top: 5px">
              {{ item.course_name }} · {{ item.class_name }}
            </div>
          </div>
          <div v-if="item.score !== null && item.score !== undefined" style="text-align: right">
            <div class="stat-value" style="font-size: 22px">{{ item.score }}</div>
            <div class="stat-hint">满分 {{ item.full_score }}</div>
          </div>
        </div>

        <div class="divider" />

        <div class="row between wrap">
          <span class="badge" :class="deadlineBadge(item)">
            {{ deadlineText(item.deadline) }}
          </span>
          <span v-if="item.submitted_at" class="faint small">
            提交于 {{ formatDate(item.submitted_at, true) }}
          </span>
          <span v-else class="faint small">满分 {{ item.full_score }} 分</span>
        </div>
      </div>
    </div>
  </div>
</template>
