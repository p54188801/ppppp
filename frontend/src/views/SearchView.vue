<script setup>
/**
 * 全局搜索页
 * 职责：从地址栏 q 读取关键词，请求 /api/search，把结果按
 *       课程 / 作业 / 资料 / 讨论 / 公告 分组展示，点击条目跳到对应页面。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, deadlineText, relativeTime } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()

const keyword = ref('')
const loading = ref(false)
const result = ref(null)

// 地址栏里当前生效的关键词，用于空结果提示与请求参数
const activeKeyword = computed(() => String(route.query.q || '').trim())

// 五个分组固定存在，各自带条数徽章；没有命中时组内显示「暂无匹配」
const groups = computed(() => {
  const data = result.value || {}
  return [
    { key: 'courses', label: '课程', items: data.courses || [] },
    { key: 'assignments', label: '作业', items: data.assignments || [] },
    { key: 'resources', label: '资料', items: data.resources || [] },
    { key: 'discussions', label: '讨论', items: data.discussions || [] },
    { key: 'announcements', label: '公告', items: data.announcements || [] },
  ]
})

const total = computed(() => (result.value ? result.value.total || 0 : 0))

async function load() {
  const q = activeKeyword.value
  if (!q) {
    result.value = null
    loading.value = false
    return
  }
  loading.value = true
  try {
    result.value = await api.get('/api/search', { q })
  } catch (error) {
    result.value = null
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

/** 回车或点按钮触发：关键词没变就直接重查，变了先写进地址栏再由 watch 发起请求 */
function submit() {
  const q = keyword.value.trim()
  if (!q) {
    ui.error('请输入搜索关键词')
    return
  }
  if (q === activeKeyword.value) load()
  else router.push({ name: 'search', query: { q } })
}

/** 作业进作业详情，其余（课程 / 资料 / 讨论 / 公告）都落到所属课程详情 */
function openItem(groupKey, item) {
  if (groupKey === 'assignments') {
    router.push({ name: 'assignment-detail', params: { id: item.id } })
    return
  }
  router.push({ name: 'course-detail', params: { id: item.course_id || item.id } })
}

watch(
  () => route.query.q,
  (value) => {
    keyword.value = typeof value === 'string' ? value : ''
    load()
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>全局搜索</h1>
        <p>一次搜索课程、作业、资料、讨论与公告</p>
      </div>
      <div class="row wrap">
        <input
          v-model="keyword"
          class="input"
          style="width: 260px"
          placeholder="输入关键词后回车"
          maxlength="64"
          @keyup.enter="submit"
        />
        <button class="btn primary" :disabled="loading" @click="submit">
          {{ loading ? '搜索中…' : '搜索' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading">正在搜索…</div>

    <div v-else-if="!activeKeyword" class="empty">输入关键词开始搜索</div>

    <div v-else-if="!total" class="empty">没有找到与 “{{ activeKeyword }}” 相关的内容</div>

    <template v-else>
      <div class="card" style="display: flex; align-items: center; justify-content: space-between">
        <span class="small muted">
          关键词 <span class="mono">{{ activeKeyword }}</span>
        </span>
        <span class="badge blue">共 {{ total }} 条结果</span>
      </div>

      <div v-for="group in groups" :key="group.key" class="card">
        <div class="card-title">
          <span>{{ group.label }}</span>
          <span class="badge" :class="group.items.length ? 'blue' : 'gray'">
            {{ group.items.length }} 条
          </span>
        </div>

        <div v-if="!group.items.length" class="empty" style="padding: 18px 10px">暂无匹配</div>

        <div v-else>
          <div
            v-for="item in group.items"
            :key="`${group.key}-${item.id}`"
            class="row between"
            style="
              gap: 12px;
              padding: 10px 0;
              border-bottom: 1px solid var(--border);
              cursor: pointer;
            "
            @click="openItem(group.key, item)"
          >
            <!-- 课程 -->
            <template v-if="group.key === 'courses'">
              <div>
                <div class="row" style="gap: 8px">
                  <span class="badge blue mono">{{ item.code }}</span>
                  <strong>{{ item.name }}</strong>
                </div>
                <div class="small faint">
                  {{ item.teacher_name || '待安排教师' }} · {{ item.term || '未设置学期' }}
                </div>
              </div>
              <span class="small faint">课程详情 →</span>
            </template>

            <!-- 作业 -->
            <template v-else-if="group.key === 'assignments'">
              <div>
                <strong>{{ item.title }}</strong>
                <div class="small faint">
                  {{ item.course_name || '—' }} · {{ item.class_name || '—' }} ·
                  {{ deadlineText(item.deadline) }}
                </div>
              </div>
              <span class="small faint">作业详情 →</span>
            </template>

            <!-- 资料 -->
            <template v-else-if="group.key === 'resources'">
              <div>
                <strong>{{ item.title }}</strong>
                <div class="small faint">
                  {{ item.course_name || '—' }}
                  <template v-if="item.filename"> · <span class="mono">{{ item.filename }}</span></template>
                </div>
              </div>
              <span class="small faint">课程详情 →</span>
            </template>

            <!-- 讨论 -->
            <template v-else-if="group.key === 'discussions'">
              <div>
                <strong>{{ item.title }}</strong>
                <div class="small faint">
                  {{ item.course_name || '—' }} · {{ item.author_name || '匿名' }}
                </div>
              </div>
              <span class="small faint">课程详情 →</span>
            </template>

            <!-- 公告：显示所属课程 -->
            <template v-else>
              <div>
                <strong>{{ item.title }}</strong>
                <div class="small faint">
                  所属课程：{{ item.course_name || '—' }} ·
                  {{ relativeTime(item.created_at) }}
                </div>
              </div>
              <span class="small faint">课程详情 →</span>
            </template>
          </div>
        </div>
      </div>

      <div class="small faint" style="margin-top: 12px">每类最多展示 10 条最相关结果</div>
    </template>
  </div>
</template>
