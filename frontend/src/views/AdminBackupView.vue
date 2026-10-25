<script setup>
/**
 * 数据备份页（仅管理员）
 * 职责：展示备份数量 / 占用空间 / 最近备份时间，创建新备份，
 *       并支持下载、恢复（二次确认 + 强制重新登录）与删除备份文件。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, formatDate, getToken, relativeTime } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()

const loading = ref(true)
const items = ref([])
const stats = ref({ count: 0, total_kb: 0, latest: null })
const note = ref('')
const creating = ref(false)
const actingFile = ref('')

const latest = computed(() => stats.value.latest)

/** 后端给的是 KB，超过 1024 KB 换成 MB 更直观 */
function sizeText(kb) {
  const value = Number(kb) || 0
  if (value < 1024) return `${value.toFixed(1)} KB`
  return `${(value / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  try {
    const data = await api.get('/api/system/backups')
    items.value = data.items || []
    stats.value = data.stats || { count: 0, total_kb: 0, latest: null }
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function createBackup() {
  creating.value = true
  try {
    const data = await api.post('/api/system/backup', { note: note.value.trim() })
    ui.success(`备份已创建：${data.filename}`)
    note.value = ''
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    creating.value = false
  }
}

/**
 * 带 token 的二进制下载：api.get 只解析 JSON，这里用 fetch 取 blob 再触发保存。
 */
async function downloadBackup(item) {
  actingFile.value = item.filename
  try {
    const response = await fetch(
      `/api/system/backups/${encodeURIComponent(item.filename)}/download`,
      {
        headers: { Authorization: `Bearer ${getToken()}` },
        credentials: 'same-origin',
      },
    )
    if (!response.ok) {
      let message = `下载失败（HTTP ${response.status}）`
      try {
        const payload = await response.json()
        if (payload && payload.error && payload.error.message) message = payload.error.message
      } catch {
        /* 响应体不是 JSON，保留默认提示 */
      }
      throw new Error(message)
    }
    const blob = await response.blob()
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = item.filename
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(href)
    ui.success('备份文件已开始下载')
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingFile.value = ''
  }
}

async function deleteBackup(item) {
  const ok = await ui.confirm({
    title: '删除备份',
    message: `确定删除备份文件 ${item.filename} 吗？删除后无法恢复该快照。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  actingFile.value = item.filename
  try {
    await api.del(`/api/system/backups/${encodeURIComponent(item.filename)}`)
    ui.success('备份已删除')
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingFile.value = ''
  }
}

async function restoreBackup(item) {
  // 第一步：说明后果
  const first = await ui.confirm({
    title: '恢复数据',
    message: `即将用 ${item.filename} 覆盖当前数据库，创建该备份之后的所有改动都会丢失。`,
    confirmText: '继续',
    danger: true,
  })
  if (!first) return
  // 第二步：真正动手前的再次确认
  const second = await ui.confirm({
    title: '再次确认恢复',
    message: `请再次确认：用 ${item.filename} 恢复数据？恢复完成后需要重新登录。`,
    confirmText: '确认恢复',
    danger: true,
  })
  if (!second) return

  actingFile.value = item.filename
  try {
    await api.post(`/api/system/backups/${encodeURIComponent(item.filename)}/restore`, {
      confirm: true,
    })
    ui.success('数据已恢复，请重新登录')
    await auth.logout()
    router.replace({ name: 'login' })
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingFile.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>数据备份</h1>
        <p>备份整库快照，可下载留存、恢复历史数据或删除不再需要的文件</p>
      </div>
      <div class="row wrap">
        <input
          v-model="note"
          class="input"
          style="width: 180px"
          placeholder="备份备注（选填）"
          maxlength="40"
          @keyup.enter="createBackup"
        />
        <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
        <button class="btn primary" :disabled="creating" @click="createBackup">
          {{ creating ? '备份中…' : '立即备份' }}
        </button>
      </div>
    </div>

    <div class="grid cols-3">
      <div class="stat">
        <div class="stat-label">备份数量</div>
        <div class="stat-value">{{ stats.count || 0 }}</div>
        <div class="stat-hint">data/backups 目录下的快照文件</div>
      </div>
      <div class="stat">
        <div class="stat-label">占用空间</div>
        <div class="stat-value">{{ sizeText(stats.total_kb) }}</div>
        <div class="stat-hint">所有备份文件合计</div>
      </div>
      <div class="stat">
        <div class="stat-label">最近备份时间</div>
        <div class="stat-value" style="font-size: 20px">
          {{ latest ? relativeTime(latest.created_at) : '暂无备份' }}
        </div>
        <div class="stat-hint">
          {{ latest ? formatDate(latest.created_at, true) : '点击右上角「立即备份」创建第一份' }}
        </div>
      </div>
    </div>

    <div class="card" style="margin-top: 16px">
      <div class="card-title">
        <span>备份文件</span>
        <span class="badge gray">共 {{ items.length }} 个</span>
      </div>

      <div v-if="loading" class="loading">正在加载备份列表…</div>

      <div v-else-if="!items.length" class="empty">还没有备份文件</div>

      <div v-else class="table-wrap" style="border: none">
        <table>
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>创建时间</th>
              <th style="text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.filename">
              <td class="mono small">{{ item.filename }}</td>
              <td class="mono small">{{ sizeText(item.size_kb) }}</td>
              <td class="small faint">{{ formatDate(item.created_at, true) }}</td>
              <td>
                <div class="row" style="gap: 6px; justify-content: flex-end">
                  <button
                    class="btn sm"
                    :disabled="actingFile === item.filename"
                    @click="downloadBackup(item)"
                  >
                    下载
                  </button>
                  <button
                    class="btn sm danger"
                    :disabled="actingFile === item.filename"
                    @click="restoreBackup(item)"
                  >
                    恢复
                  </button>
                  <button
                    class="btn sm ghost"
                    :disabled="actingFile === item.filename"
                    @click="deleteBackup(item)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="hint" style="margin-top: 12px">
        恢复操作会用备份覆盖当前数据库，属于危险操作，请确认已在低峰期执行；恢复后所有用户需重新登录。
      </div>
    </div>
  </div>
</template>
