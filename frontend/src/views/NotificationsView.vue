<script setup>
/**
 * 通知中心（全角色）
 *
 * 分页拉取 GET /api/notifications，展示标题、内容、分类与相对时间；
 * 点击某条通知标记已读，顶部提供「全部已读」与「清空已读」两个批量操作。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, relativeTime } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const loading = ref(true)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const pages = ref(1)
const acting = ref(false)

const categoryLabels = {
  system: '系统',
  assignment: '作业',
  quiz: '测验',
  attendance: '签到',
  course: '课程',
  grade: '成绩',
}

const categoryTones = {
  system: 'gray',
  assignment: 'yellow',
  quiz: 'purple',
  attendance: 'green',
  course: 'blue',
  grade: 'green',
}

/**
 * 后端返回的 pages 基于 total；通知接口的 total 只统计了当前页，
 * 因此整页返回时认为还有下一页，避免分页被卡在第 1 页。
 */
const hasNext = computed(() => page.value < pages.value || items.value.length >= pageSize)
const pageCount = computed(() => Math.max(pages.value, page.value + (hasNext.value ? 1 : 0)))
const pageNumbers = computed(() => {
  const totalPages = Math.max(1, pageCount.value)
  const start = Math.max(1, Math.min(page.value - 2, totalPages - 4))
  const end = Math.min(totalPages, start + 4)
  const list = []
  for (let index = start; index <= end; index += 1) list.push(index)
  return list
})

function categoryLabel(category) {
  return categoryLabels[category] || category || '系统'
}

function categoryTone(category) {
  return categoryTones[category] || 'gray'
}

async function load() {
  loading.value = true
  try {
    const data = await api.get('/api/notifications', { page: page.value, page_size: pageSize })
    items.value = data?.items || []
    total.value = data?.total || 0
    pages.value = data?.pages || 1
  } catch (error) {
    items.value = []
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function markRead(item) {
  if (item.is_read) return
  try {
    await api.post(`/api/notifications/${item.id}/read`)
    item.is_read = 1
  } catch (error) {
    ui.error(error.message)
  }
}

async function openItem(item) {
  await markRead(item)
  if (item.link) {
    const target = item.link.startsWith('/') ? `#${item.link}` : item.link
    if (target.startsWith('#')) window.location.hash = target.slice(1)
    else window.open(item.link, '_blank')
  }
}

async function markAllRead() {
  acting.value = true
  try {
    const data = await api.post('/api/notifications/read-all')
    ui.success(`已将 ${data?.updated ?? 0} 条通知标为已读`)
    page.value = 1
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    acting.value = false
  }
}

async function clearRead() {
  const ok = await ui.confirm({
    title: '清空已读通知',
    message: '所有已读通知将被永久删除，确定继续吗？',
    danger: true,
  })
  if (!ok) return
  acting.value = true
  try {
    const data = await api.del('/api/notifications/read')
    ui.success(`已清空 ${data?.deleted ?? 0} 条已读通知`)
    if (page.value > 1) page.value = 1
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    acting.value = false
  }
}

function goPage(target) {
  if (target < 1 || target === page.value) return
  if (target > Math.max(1, pageCount.value)) return
  page.value = target
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>通知中心</h1>
        <p>作业、测验、签到与系统消息都会汇总到这里</p>
      </div>
      <div class="row wrap">
        <button class="btn" :disabled="acting" @click="markAllRead">全部已读</button>
        <button class="btn danger" :disabled="acting" @click="clearRead">清空已读</button>
        <button class="btn" :disabled="loading" @click="load">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">正在加载通知…</div>

    <template v-else>
      <div v-if="!items.length" class="card">
        <div class="empty">暂时没有通知，新的提醒会出现在这里</div>
      </div>

      <div
        v-for="item in items"
        :key="item.id"
        class="card"
        style="cursor: pointer; padding: 14px 18px"
        @click="openItem(item)"
      >
        <div class="row between" style="align-items: flex-start; gap: 14px">
          <div class="row" style="gap: 8px; align-items: flex-start; min-width: 0">
            <span
              v-if="!item.is_read"
              title="未读"
              style="
                display: inline-block;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: var(--primary);
                margin-top: 7px;
                flex-shrink: 0;
              "
            />
            <span
              v-else
              style="display: inline-block; width: 8px; flex-shrink: 0"
            />
            <div style="min-width: 0">
              <div class="row wrap" style="gap: 8px">
                <strong :style="{ color: item.is_read ? '' : 'var(--text)' }">
                  {{ item.title }}
                </strong>
                <span class="badge" :class="categoryTone(item.category)">
                  {{ categoryLabel(item.category) }}
                </span>
              </div>
              <div v-if="item.content" class="muted small" style="margin-top: 4px">
                {{ item.content }}
              </div>
            </div>
          </div>
          <span class="faint small" style="white-space: nowrap">
            {{ relativeTime(item.created_at) }}
          </span>
        </div>
      </div>

      <div class="row between wrap" style="margin-top: 16px">
        <span class="faint small">
          共 {{ total }} 条 · 第 {{ page }} / {{ pageCount }} 页
        </span>
        <div class="row" style="gap: 6px">
          <button class="btn sm" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <button
            v-for="number in pageNumbers"
            :key="number"
            class="btn sm"
            :class="{ primary: number === page }"
            @click="goPage(number)"
          >
            {{ number }}
          </button>
          <button class="btn sm" :disabled="!hasNext" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </template>
  </div>
</template>
