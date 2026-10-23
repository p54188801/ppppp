<script setup>
/**
 * 课程详情页
 * 职责：展示课程基本信息与教学班列表，提供邀请码复制/加入、新建教学班、
 *       课程资料上传下载，以及课程讨论区（发帖 / 展开查看回复 / 回复）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatDate, getToken, relativeTime } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const courseId = computed(() => Number(route.params.id))

const loading = ref(true)
const course = ref(null)
const resources = ref([])
const threads = ref([])
const expanded = ref({})
const replyDrafts = ref({})
const replyingId = ref(0)

const joinCode = ref('')
const joining = ref(false)

const showClass = ref(false)
const classForm = ref({ name: '', capacity: 60, schedule: '', location: '' })
const savingClass = ref(false)

const showUpload = ref(false)
const uploadForm = ref({ title: '', description: '', category: '课件' })
const uploadFile = ref(null)
const uploading = ref(false)

const showThread = ref(false)
const threadForm = ref({ title: '', content: '' })
const postingThread = ref(false)

const canManage = computed(() => auth.canManageCourse(course.value))
const classes = computed(() => course.value?.classes || [])

async function load() {
  loading.value = true
  try {
    const [detail, resourceList, threadList] = await Promise.all([
      api.get(`/api/courses/${courseId.value}`),
      api.get(`/api/courses/${courseId.value}/resources`),
      api.get(`/api/courses/${courseId.value}/discussions`),
    ])
    course.value = detail
    resources.value = resourceList || []
    threads.value = threadList || []
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

function openClass(id) {
  router.push({ name: 'class-detail', params: { id } })
}

async function copyCode(code) {
  if (!code) return
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(code)
    } else {
      const input = document.createElement('input')
      input.value = code
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
    }
    ui.success(`邀请码 ${code} 已复制`)
  } catch {
    ui.error('复制失败，请手动选择邀请码')
  }
}

async function joinClass() {
  const code = joinCode.value.trim().toUpperCase()
  if (!code) {
    ui.error('请输入教学班邀请码')
    return
  }
  joining.value = true
  try {
    const data = await api.post('/api/classes/join', { code })
    ui.success('已加入教学班')
    joinCode.value = ''
    await load()
    if (data && data.id) router.push({ name: 'class-detail', params: { id: data.id } })
  } catch (error) {
    ui.error(error.message)
  } finally {
    joining.value = false
  }
}

function openCreateClass() {
  classForm.value = { name: `${course.value?.name || '课程'}-02班`, capacity: 60, schedule: '', location: '' }
  showClass.value = true
}

async function submitClass() {
  const name = classForm.value.name.trim()
  if (!name) {
    ui.error('教学班名称不能为空')
    return
  }
  savingClass.value = true
  try {
    await api.post(`/api/courses/${courseId.value}/classes`, {
      name,
      capacity: Number(classForm.value.capacity) || 60,
      schedule: classForm.value.schedule.trim(),
      location: classForm.value.location.trim(),
    })
    ui.success('教学班已创建')
    showClass.value = false
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingClass.value = false
  }
}

function formatSize(bytes) {
  const size = Number(bytes) || 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

/**
 * 带 token 的二进制下载：api.get 只能解析 JSON，这里用 fetch 取 blob 再触发保存。
 */
async function downloadFile(url, fallbackName = 'download') {
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${getToken()}` },
      credentials: 'same-origin',
    })
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
    const disposition = response.headers.get('Content-Disposition') || ''
    const matched = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition)
    const filename = matched ? decodeURIComponent(matched[1]) : fallbackName
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(href)
    ui.success('已开始下载')
  } catch (error) {
    ui.error(error.message)
  }
}

function downloadResource(resource) {
  downloadFile(`/api/resources/${resource.id}/download`, resource.filename || resource.title)
}

function onFileChange(event) {
  const files = event.target.files
  uploadFile.value = files && files.length ? files[0] : null
  if (uploadFile.value && !uploadForm.value.title.trim()) {
    uploadForm.value.title = uploadFile.value.name.replace(/\.[^.]+$/, '')
  }
}

function openUpload() {
  uploadForm.value = { title: '', description: '', category: '课件' }
  uploadFile.value = null
  showUpload.value = true
}

async function submitUpload() {
  if (!uploadFile.value) {
    ui.error('请先选择要上传的文件')
    return
  }
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', uploadFile.value)
    formData.append('title', uploadForm.value.title.trim())
    formData.append('description', uploadForm.value.description.trim())
    formData.append('category', uploadForm.value.category)
    await api.upload(`/api/courses/${courseId.value}/resources`, formData)
    ui.success('资料已上传')
    showUpload.value = false
    uploadFile.value = null
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    uploading.value = false
  }
}

async function toggleThread(thread) {
  if (expanded.value[thread.id]) {
    const next = { ...expanded.value }
    delete next[thread.id]
    expanded.value = next
    return
  }
  try {
    const detail = await api.get(`/api/discussions/${thread.id}`)
    expanded.value = { ...expanded.value, [thread.id]: detail }
  } catch (error) {
    ui.error(error.message)
  }
}

async function refreshThreads() {
  const list = await api.get(`/api/courses/${courseId.value}/discussions`)
  threads.value = list || []
}

async function sendReply(thread) {
  const content = (replyDrafts.value[thread.id] || '').trim()
  if (!content) {
    ui.error('回复内容不能为空')
    return
  }
  replyingId.value = thread.id
  try {
    await api.post(`/api/discussions/${thread.id}/replies`, { content })
    replyDrafts.value = { ...replyDrafts.value, [thread.id]: '' }
    const detail = await api.get(`/api/discussions/${thread.id}`)
    expanded.value = { ...expanded.value, [thread.id]: detail }
    await refreshThreads()
    ui.success('回复已发布')
  } catch (error) {
    ui.error(error.message)
  } finally {
    replyingId.value = 0
  }
}

function openThreadForm() {
  threadForm.value = { title: '', content: '' }
  showThread.value = true
}

async function submitThread() {
  const title = threadForm.value.title.trim()
  if (title.length < 2) {
    ui.error('话题标题至少需要 2 个字符')
    return
  }
  postingThread.value = true
  try {
    await api.post(`/api/courses/${courseId.value}/discussions`, {
      title,
      content: threadForm.value.content.trim(),
    })
    ui.success('话题已发布')
    showThread.value = false
    await refreshThreads()
  } catch (error) {
    ui.error(error.message)
  } finally {
    postingThread.value = false
  }
}

function authorBadge(role) {
  if (role === 'teacher') return 'blue'
  if (role === 'admin') return 'purple'
  return 'gray'
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
          <span class="faint">{{ course ? course.code : courseId }}</span>
        </div>
        <h1>{{ course ? course.name : '课程详情' }}</h1>
        <p v-if="course">
          {{ course.code }} · {{ course.teacher_name || '待安排教师' }} ·
          {{ course.term || '未设置学期' }} · {{ course.credits }} 学分 / {{ course.hours }} 学时
        </p>
      </div>
      <div class="row">
        <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
        <button v-if="canManage" class="btn primary" @click="openCreateClass">新建教学班</button>
      </div>
    </div>

    <div v-if="loading" class="loading">正在加载课程详情…</div>

    <template v-else-if="course">
      <!-- 课程概览 -->
      <div class="card">
        <div class="card-title">
          <span>课程概览</span>
          <span class="badge gray">{{ course.category || '未分类' }}</span>
        </div>
        <p class="muted" style="margin: 0 0 12px">
          {{ course.description || '该课程还没有填写简介。' }}
        </p>
        <div class="row wrap small faint" style="gap: 18px">
          <span>教学班 {{ classes.length }} 个</span>
          <span>学生 {{ course.student_count || 0 }} 人</span>
          <span>资料 {{ resources.length }} 份</span>
          <span>讨论 {{ threads.length }} 条</span>
        </div>
      </div>

      <!-- 学生加入 -->
      <div v-if="auth.isStudent" class="card">
        <div class="card-title"><span>加入教学班</span></div>
        <div class="row wrap">
          <input
            v-model="joinCode"
            class="input mono"
            style="width: 220px"
            placeholder="输入 6 位邀请码"
            maxlength="12"
            @keyup.enter="joinClass"
          />
          <button class="btn primary" :disabled="joining" @click="joinClass">
            {{ joining ? '加入中…' : '加入' }}
          </button>
          <span class="small faint">向任课教师索取教学班邀请码</span>
        </div>
      </div>

      <!-- 教学班 -->
      <div class="card">
        <div class="card-title">
          <span>教学班</span>
          <span class="faint small">点击卡片进入班级空间</span>
        </div>
        <div v-if="!classes.length" class="empty">还没有教学班</div>
        <div v-else class="grid cols-3">
          <div
            v-for="item in classes"
            :key="item.id"
            class="card"
            style="margin-top: 0; background: var(--surface-2); cursor: pointer"
            @click="openClass(item.id)"
          >
            <div class="row between">
              <strong>{{ item.name }}</strong>
              <span class="badge blue">{{ item.student_count || 0 }} / {{ item.capacity || 60 }} 人</span>
            </div>
            <div class="row between small muted" style="margin-top: 10px">
              <span>地点：{{ item.location || '待定' }}</span>
              <span>{{ item.schedule || '时间待定' }}</span>
            </div>
            <div class="row between" style="margin-top: 12px">
              <span class="small faint">邀请码</span>
              <span class="badge gray mono" style="cursor: copy" @click.stop="copyCode(item.join_code)">
                {{ item.join_code }} ⧉
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 课程资料 -->
      <div class="card">
        <div class="card-title">
          <span>课程资料</span>
          <button v-if="canManage" class="btn sm" @click="openUpload">上传资料</button>
        </div>
        <div v-if="!resources.length" class="empty">暂无资料</div>
        <div v-else class="table-wrap" style="border: none">
          <table>
            <thead>
              <tr>
                <th>标题</th>
                <th>分类</th>
                <th>大小</th>
                <th>上传者</th>
                <th>上传时间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in resources" :key="item.id">
                <td>
                  <div>{{ item.title }}</div>
                  <div class="faint small">{{ item.filename }}</div>
                </td>
                <td><span class="badge gray">{{ item.category }}</span></td>
                <td class="mono small">{{ formatSize(item.size) }}</td>
                <td class="small muted">{{ item.uploader_name || '—' }}</td>
                <td class="small faint">{{ formatDate(item.created_at) }}</td>
                <td style="text-align: right">
                  <button class="btn sm" @click="downloadResource(item)">下载</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 讨论区 -->
      <div class="card">
        <div class="card-title">
          <span>讨论区</span>
          <button class="btn sm" @click="openThreadForm">发起讨论</button>
        </div>
        <div v-if="!threads.length" class="empty">还没有讨论，发布第一个话题吧</div>
        <div v-else>
          <div
            v-for="thread in threads"
            :key="thread.id"
            style="padding: 12px 0; border-bottom: 1px solid var(--border)"
          >
            <div class="row between" style="cursor: pointer" @click="toggleThread(thread)">
              <div>
                <div class="row" style="gap: 6px">
                  <span v-if="thread.pinned" class="badge yellow">置顶</span>
                  <span v-if="thread.locked" class="badge red">已锁定</span>
                  <strong>{{ thread.title }}</strong>
                </div>
                <div class="faint small">
                  {{ thread.author_name }} · {{ relativeTime(thread.updated_at || thread.created_at) }} ·
                  {{ thread.reply_count || 0 }} 条回复 · {{ thread.views || 0 }} 次浏览
                </div>
              </div>
              <span class="small faint">{{ expanded[thread.id] ? '收起 ▲' : '展开 ▼' }}</span>
            </div>

            <div v-if="expanded[thread.id]" style="margin-top: 10px">
              <p class="muted" style="margin: 0 0 10px; white-space: pre-wrap">
                {{ expanded[thread.id].content || '（无正文）' }}
              </p>

              <div
                v-for="reply in expanded[thread.id].replies || []"
                :key="reply.id"
                style="padding: 8px 12px; margin-bottom: 8px; background: var(--surface-2); border-radius: var(--radius-sm)"
              >
                <div class="row between">
                  <span class="small">
                    {{ reply.author_name }}
                    <span class="badge" :class="authorBadge(reply.author_role)">
                      {{ reply.author_role === 'teacher' ? '教师' : reply.author_role === 'admin' ? '管理员' : '学生' }}
                    </span>
                  </span>
                  <span class="faint small">{{ relativeTime(reply.created_at) }}</span>
                </div>
                <div class="small" style="white-space: pre-wrap">{{ reply.content }}</div>
              </div>

              <div v-if="!expanded[thread.id].locked" class="row" style="gap: 8px; margin-top: 10px">
                <input
                  v-model="replyDrafts[thread.id]"
                  class="input"
                  placeholder="写下你的回复…"
                  maxlength="10000"
                  @keyup.enter="sendReply(thread)"
                />
                <button class="btn" :disabled="replyingId === thread.id" @click="sendReply(thread)">
                  {{ replyingId === thread.id ? '发送中…' : '回复' }}
                </button>
              </div>
              <div v-else class="small faint">该话题已锁定，不能回复</div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="empty">课程不存在或你没有访问权限</div>

    <!-- 新建教学班 -->
    <div v-if="showClass" class="modal-mask" @click.self="showClass = false">
      <form class="modal" @submit.prevent="submitClass">
        <div class="modal-head">
          <h3>新建教学班</h3>
          <button type="button" class="btn ghost sm" @click="showClass = false">✕</button>
        </div>
        <div class="field">
          <label>教学班名称</label>
          <input v-model="classForm.name" class="input" placeholder="如 数据结构-02班" maxlength="64" />
        </div>
        <div class="form-row">
          <div class="field">
            <label>人数上限</label>
            <input v-model="classForm.capacity" class="input" type="number" min="1" max="500" />
          </div>
          <div class="field">
            <label>上课地点</label>
            <input v-model="classForm.location" class="input" placeholder="如 教三-305" maxlength="64" />
          </div>
        </div>
        <div class="field">
          <label>上课时间</label>
          <input v-model="classForm.schedule" class="input" placeholder="如 周二 3-4 节" maxlength="64" />
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showClass = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingClass">
            {{ savingClass ? '创建中…' : '创建教学班' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 上传资料 -->
    <div v-if="showUpload" class="modal-mask" @click.self="showUpload = false">
      <form class="modal" @submit.prevent="submitUpload">
        <div class="modal-head">
          <h3>上传课程资料</h3>
          <button type="button" class="btn ghost sm" @click="showUpload = false">✕</button>
        </div>
        <div class="field">
          <label>选择文件</label>
          <input class="input" type="file" @change="onFileChange" />
          <div class="hint">单个文件不超过 64 MB</div>
        </div>
        <div class="field">
          <label>资料标题</label>
          <input v-model="uploadForm.title" class="input" placeholder="留空则使用文件名" maxlength="120" />
        </div>
        <div class="field">
          <label>资料分类</label>
          <select v-model="uploadForm.category" class="select">
            <option value="课件">课件</option>
            <option value="课件视频">课件视频</option>
            <option value="参考资料">参考资料</option>
            <option value="作业模板">作业模板</option>
            <option value="其他">其他</option>
          </select>
        </div>
        <div class="field">
          <label>资料说明</label>
          <textarea v-model="uploadForm.description" class="textarea" placeholder="选填" maxlength="2000" />
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showUpload = false">取消</button>
          <button type="submit" class="btn primary" :disabled="uploading">
            {{ uploading ? '上传中…' : '上传' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 发起讨论 -->
    <div v-if="showThread" class="modal-mask" @click.self="showThread = false">
      <form class="modal" @submit.prevent="submitThread">
        <div class="modal-head">
          <h3>发起讨论</h3>
          <button type="button" class="btn ghost sm" @click="showThread = false">✕</button>
        </div>
        <div class="field">
          <label>标题</label>
          <input v-model="threadForm.title" class="input" placeholder="想讨论的问题" maxlength="120" />
        </div>
        <div class="field">
          <label>正文</label>
          <textarea v-model="threadForm.content" class="textarea" placeholder="补充你的问题背景" maxlength="20000" />
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showThread = false">取消</button>
          <button type="submit" class="btn primary" :disabled="postingThread">
            {{ postingThread ? '发布中…' : '发布话题' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
