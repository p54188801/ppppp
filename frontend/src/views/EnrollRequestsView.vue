<script setup>
/**
 * 入课审批：学生凭邀请码申请后，任课老师在这里同意或拒绝。
 */
import { computed, onMounted, ref } from 'vue'
import { api, formatDate } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

const items = ref([])
const loading = ref(true)
const acting = ref(0)

const grouped = computed(() => {
  const map = new Map()
  for (const it of items.value) {
    const key = `${it.course_name} / ${it.class_name}`
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(it)
  }
  return [...map.entries()].map(([name, list]) => ({ name, list }))
})

async function load() {
  loading.value = true
  try {
    items.value = await api.get('/api/enroll/requests')
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function decide(item, approve) {
  acting.value = item.id
  try {
    await api.post(`/api/enroll/requests/${item.id}/${approve ? 'approve' : 'reject'}`)
    ui.success(approve ? `已同意 ${item.real_name} 加入` : `已拒绝 ${item.real_name}`)
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    acting.value = 0
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>入课审批</h1>
        <p>学生凭邀请码申请加入课程，同意后才会出现在你的班级名单里</p>
      </div>
      <button class="btn" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!items.length" class="card empty" style="text-align: center; padding: 30px">
      暂无待审批的申请
    </div>

    <div v-for="group in grouped" :key="group.name" class="card" style="margin-bottom: 14px">
      <div class="card-title">
        <span>{{ group.name }}</span>
        <span class="badge yellow">{{ group.list.length }} 人待审批</span>
      </div>
      <div
        v-for="item in group.list"
        :key="item.id"
        class="row between"
        style="padding: 10px 0; border-bottom: 1px solid var(--border)"
      >
        <div>
          <strong>{{ item.real_name }}</strong>
          <span class="faint small"> {{ item.number || item.username }}</span>
          <div class="faint small">申请时间 {{ formatDate(item.created_at, true) }}</div>
        </div>
        <div class="row" style="gap: 8px">
          <button class="btn sm" :disabled="acting === item.id" @click="decide(item, false)">拒绝</button>
          <button class="btn sm primary" :disabled="acting === item.id" @click="decide(item, true)">同意</button>
        </div>
      </div>
    </div>
  </div>
</template>
