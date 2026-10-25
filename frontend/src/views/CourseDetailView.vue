<script setup>
/**
 * 课程详情页
 * 职责：展示课程基本信息、章节任务点与学习进度，并按标签页组织教学班、
 *       公告、资料与讨论区；教师可维护章节/任务点，学生逐个完成并上报进度。
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

const tabs = [
  { key: 'chapters', label: '章节' },
  { key: 'classes', label: '教学班' },
  { key: 'announcements', label: '公告' },
  { key: 'resources', label: '资料' },
  { key: 'discussions', label: '讨论' },
]
const activeTab = ref('chapters')

const loading = ref(true)
const course = ref(null)
const resources = ref([])
const threads = ref([])
const announcements = ref([])
const expandedAnn = ref({})
const expanded = ref({})
const replyDrafts = ref({})
const replyingId = ref(0)

// 章节与任务点
const chapters = ref([])
const chapterSummary = ref(null)
const chapterOptions = ref({ assignments: [], quizzes: [] })
const showChapter = ref(false)
const editingChapterId = ref(0)
const chapterForm = ref({ title: '', description: '' })
const savingChapter = ref(false)
const showTask = ref(false)
const taskChapterId = ref(0)
const editingTaskId = ref(0)
const taskForm = ref(emptyTask())
const savingTask = ref(false)
const taskActingId = ref(0)
const chapterActingId = ref(0)

// 教师端学习进度面板
const showProgress = ref(false)
const loadingProgress = ref(false)
const progressData = ref(null)

const joinCode = ref('')
const joining = ref(false)

const showClass = ref(false)
const classForm = ref({ name: '', capacity: 60, schedule: '', location: '' })
const savingClass = ref(false)

const showUpload = ref(false)
const uploadForm = ref({ title: '', description: '', category: '课件' })
const uploadFile = ref(null)
const uploading = ref(false)

// 课程公告：发布与编辑复用同一个弹窗，editingAnnId 为 0 表示新建
const showAnn = ref(false)
const editingAnnId = ref(0)
const annForm = ref({ title: '', content: '', pinned: false })
const savingAnn = ref(false)
const annActingId = ref(0)

const showThread = ref(false)
const threadForm = ref({ title: '', content: '' })
const postingThread = ref(false)

const canManage = computed(() => auth.canManageCourse(course.value))
const classes = computed(() => course.value?.classes || [])

const taskLinkOptions = computed(() => {
  const type = taskForm.value.type
  if (type === 'material') {
    return resources.value.map((item) => ({ id: item.id, label: item.title }))
  }
  if (type === 'assignment') {
    return chapterOptions.value.assignments.map((item) => ({
      id: item.id,
      label: `${item.title}（${item.class_name || '教学班'}）`,
    }))
  }
  if (type === 'quiz') {
    return chapterOptions.value.quizzes.map((item) => ({
      id: item.id,
      label: `${item.title}（${item.class_name || '教学班'}）`,
    }))
  }
  return []
})

function emptyTask() {
  return {
    type: 'material',
    title: '',
    description: '',
    duration: 30,
    required: true,
    link_id: '',
  }
}

async function load() {
  loading.value = true
  try {
    const [detail, resourceList, threadList, annList, chapterData] = await Promise.all([
      api.get(`/api/courses/${courseId.value}`),
      api.get(`/api/courses/${courseId.value}/resources`),
      api.get(`/api/courses/${courseId.value}/discussions`),
      api.get(`/api/courses/${courseId.value}/announcements`),
      api.get(`/api/courses/${courseId.value}/chapters`),
    ])
    course.value = detail
    resources.value = resourceList || []
    threads.value = threadList || []
    announcements.value = annList || []
    chapters.value = chapterData.items || []
    chapterSummary.value = chapterData.summary || null
    if (canManage.value) await loadChapterOptions()
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

/** 教师建任务点时要选关联的作业/测验，按课程下每个教学班各拉一次再合并。 */
async function loadChapterOptions() {
  const courseClasses = course.value?.classes || []
  if (!courseClasses.length) {
    chapterOptions.value = { assignments: [], quizzes: [] }
    return
  }
  try {
    const groups = await Promise.all(
      courseClasses.map(async (item) => {
        const [assignmentList, quizList] = await Promise.all([
          api.get(`/api/classes/${item.id}/assignments`),
          api.get(`/api/classes/${item.id}/quizzes`),
        ])
        return {
          assignments: assignmentList || [],
          quizzes: quizList || [],
        }
      }),
    )
    chapterOptions.value = {
      assignments: groups.flatMap((group) => group.assignments),
      quizzes: groups.flatMap((group) => group.quizzes),
    }
  } catch {
    chapterOptions.value = { assignments: [], quizzes: [] }
  }
}

async function refreshChapters() {
  const data = await api.get(`/api/courses/${courseId.value}/chapters`)
  chapters.value = data.items || []
  chapterSummary.value = data.summary || null
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

/* ---------------------------------------------------------------- 章节 */

function openChapterForm(item = null) {
  editingChapterId.value = item ? item.id : 0
  chapterForm.value = item
    ? { title: item.title || '', description: item.description || '' }
    : { title: '', description: '' }
  showChapter.value = true
}

async function submitChapter() {
  const title = chapterForm.value.title.trim()
  if (title.length < 2) {
    ui.error('章节标题至少需要 2 个字符')
    return
  }
  savingChapter.value = true
  try {
    const payload = {
      title,
      description: chapterForm.value.description.trim(),
    }
    if (editingChapterId.value) {
      await api.put(`/api/chapters/${editingChapterId.value}`, payload)
      ui.success('章节已更新')
    } else {
      await api.post(`/api/courses/${courseId.value}/chapters`, payload)
      ui.success('章节已创建')
    }
    showChapter.value = false
    await refreshChapters()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingChapter.value = false
  }
}

async function deleteChapter(item) {
  const ok = await ui.confirm({
    title: '删除章节',
    message: `确定删除「${item.title}」吗？章节下的任务点与学习进度会一并删除。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  chapterActingId.value = item.id
  try {
    await api.del(`/api/chapters/${item.id}`)
    ui.success('章节已删除')
    await refreshChapters()
  } catch (error) {
    ui.error(error.message)
  } finally {
    chapterActingId.value = 0
  }
}

function openTaskForm(chapter, task = null) {
  taskChapterId.value = chapter.id
  editingTaskId.value = task ? task.id : 0
  if (task) {
    taskForm.value = {
      type: task.type,
      title: task.title || '',
      description: task.description || '',
      duration: Number(task.duration) || 0,
      required: Boolean(task.required),
      link_id: task.resource_id || task.assignment_id || task.quiz_id || '',
    }
  } else {
    taskForm.value = emptyTask()
  }
  showTask.value = true
}

function onTaskTypeChange() {
  taskForm.value.link_id = ''
}

async function submitTask() {
  const title = taskForm.value.title.trim()
  if (title.length < 2) {
    ui.error('任务点标题至少需要 2 个字符')
    return
  }
  savingTask.value = true
  try {
    const payload = {
      type: taskForm.value.type,
      title,
      description: taskForm.value.description.trim(),
      duration: Number(taskForm.value.duration) || 0,
      required: Boolean(taskForm.value.required),
    }
    const linkId = Number(taskForm.value.link_id) || null
    if (taskForm.value.type === 'material') payload.resource_id = linkId
    if (taskForm.value.type === 'assignment') payload.assignment_id = linkId
    if (taskForm.value.type === 'quiz') payload.quiz_id = linkId

    if (editingTaskId.value) {
      await api.put(`/api/tasks/${editingTaskId.value}`, payload)
      ui.success('任务点已更新')
    } else {
      await api.post(`/api/chapters/${taskChapterId.value}/tasks`, payload)
      ui.success('任务点已创建')
    }
    showTask.value = false
    await refreshChapters()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingTask.value = false
  }
}

async function deleteTask(task) {
  const ok = await ui.confirm({
    title: '删除任务点',
    message: `确定删除任务点「${task.title}」吗？学生的完成记录也会被删除。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  taskActingId.value = task.id
  try {
    await api.del(`/api/tasks/${task.id}`)
    ui.success('任务点已删除')
    await refreshChapters()
  } catch (error) {
    ui.error(error.message)
  } finally {
    taskActingId.value = 0
  }
}

async function startTask(task) {
  await reportTask(task, { status: 'in_progress' })
}

async function completeTask(task) {
  await reportTask(task, { progress: 100 })
}

async function reportTask(task, payload) {
  taskActingId.value = task.id
  try {
    await api.post(`/api/tasks/${task.id}/progress`, payload)
    await refreshChapters()
    ui.success(payload.progress === 100 ? '任务点已完成' : '已开始学习')
  } catch (error) {
    ui.error(error.message)
  } finally {
    taskActingId.value = 0
  }
}

function openAssignment(task) {
  if (task.assignment_id) {
    router.push({ name: 'assignment-detail', params: { id: task.assignment_id } })
  }
}

function openQuiz(task) {
  if (task.quiz_id && auth.isStudent) {
    router.push({ name: 'quiz-take', params: { id: task.quiz_id } })
  }
}

function taskTypeBadge(type) {
  if (type === 'assignment') return 'purple'
  if (type === 'quiz') return 'yellow'
  if (type === 'discussion') return 'gray'
  if (type === 'material') return 'blue'
  return 'gray'
}

async function openProgress() {
  showProgress.value = true
  loadingProgress.value = true
  progressData.value = null
  try {
    progressData.value = await api.get(`/api/courses/${courseId.value}/progress`)
  } catch (error) {
    ui.error(error.message)
    showProgress.value = false
  } finally {
    loadingProgress.value = false
  }
}

/* ---------------------------------------------------------------- 资料 */

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

/* ---------------------------------------------------------------- 讨论 */

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

/* ---------------------------------------------------------------- 课程公告 */

// 正文超过这个长度（或超过 3 行）默认折叠
const ANN_PREVIEW_LENGTH = 120

async function refreshAnnouncements() {
  const list = await api.get(`/api/courses/${courseId.value}/announcements`)
  announcements.value = list || []
}

/** 打开弹窗：传公告即编辑，不传即新建 */
function openAnnForm(item = null) {
  editingAnnId.value = item ? item.id : 0
  annForm.value = item
    ? { title: item.title || '', content: item.content || '', pinned: Boolean(item.pinned) }
    : { title: '', content: '', pinned: false }
  showAnn.value = true
}

async function submitAnn() {
  const title = annForm.value.title.trim()
  if (title.length < 2) {
    ui.error('公告标题至少需要 2 个字符')
    return
  }
  savingAnn.value = true
  try {
    const payload = {
      title,
      content: annForm.value.content.trim(),
      pinned: annForm.value.pinned,
    }
    if (editingAnnId.value) {
      await api.put(`/api/announcements/${editingAnnId.value}`, payload)
      ui.success('公告已更新')
    } else {
      await api.post(`/api/courses/${courseId.value}/announcements`, payload)
      ui.success('公告已发布')
    }
    showAnn.value = false
    await refreshAnnouncements()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingAnn.value = false
  }
}

async function deleteAnn(item) {
  const ok = await ui.confirm({
    title: '删除公告',
    message: `确定删除公告「${item.title}」吗？删除后不可恢复。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  annActingId.value = item.id
  try {
    await api.del(`/api/announcements/${item.id}`)
    ui.success('公告已删除')
    await refreshAnnouncements()
  } catch (error) {
    ui.error(error.message)
  } finally {
    annActingId.value = 0
  }
}

function toggleAnn(id) {
  expandedAnn.value = { ...expandedAnn.value, [id]: !expandedAnn.value[id] }
}

/** 内容过长且未展开时需要折叠成 3 行 */
function annCollapsed(item) {
  const content = item.content || ''
  if (!content || expandedAnn.value[item.id]) return false
  return content.length > ANN_PREVIEW_LENGTH || content.split('\n').length > 3
}

/**
 * 公告正文样式：未展开时用 -webkit-line-clamp 折成 3 行。
 * 这里直接返回 CSS 字符串，避免对象写法对 -webkit- 前缀属性的兼容坑。
 */
function annStyle(item) {
  const base = 'margin: 8px 0 0; white-space: pre-wrap;'
  if (!annCollapsed(item)) return base
  return (
    base +
    ' display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;'
  )
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
          <span>章节 {{ chapterSummary ? chapterSummary.chapter_count : 0 }} 个</span>
          <span>任务点 {{ chapterSummary ? chapterSummary.task_count : 0 }} 个</span>
          <span>教学班 {{ classes.length }} 个</span>
          <span>学生 {{ course.student_count || 0 }} 人</span>
          <span>公告 {{ announcements.length }} 条</span>
          <span>资料 {{ resources.length }} 份</span>
          <span>讨论 {{ threads.length }} 条</span>
        </div>
      </div>

      <div class="tabs">
        <div
          v-for="tab in tabs"
          :key="tab.key"
          class="tab"
          :class="{ active: activeTab === tab.key }"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
          <span
            v-if="tab.key === 'chapters' && chapterSummary"
            class="badge gray"
            style="margin-left: 6px"
          >
            {{ chapterSummary.task_count }}
          </span>
        </div>
      </div>

      <!-- ================= 章节任务点 ================= -->
      <template v-if="activeTab === 'chapters'">
        <div class="card">
          <div class="card-title">
            <span>{{ auth.isStudent ? '我的学习进度' : '学习进度' }}</span>
            <div v-if="canManage" class="row" style="gap: 6px">
              <button class="btn sm ghost" @click="openProgress">完成明细</button>
              <button class="btn sm primary" @click="openChapterForm()">新建章节</button>
            </div>
          </div>
          <template v-if="chapterSummary && chapterSummary.task_count">
            <div class="row between small" style="margin-bottom: 6px">
              <span class="muted">
                <template v-if="auth.isStudent">
                  {{ chapterSummary.completed_count }} / {{ chapterSummary.task_count }} 个任务点已完成
                </template>
                <template v-else>
                  {{ chapterSummary.student_count }} 名学生 · {{ chapterSummary.task_count }} 个任务点 ·
                  已完成 {{ chapterSummary.completed_count }} 人次
                </template>
              </span>
              <span class="mono">{{ chapterSummary.progress }}%</span>
            </div>
            <div class="progress">
              <i :style="{ width: `${chapterSummary.progress}%` }" />
            </div>
          </template>
          <div v-else class="empty">
            {{ canManage ? '还没有章节，点击右上角「新建章节」开始搭建课程内容。' : '老师还没有发布章节内容。' }}
          </div>
        </div>

        <div v-if="!chapters.length && canManage" class="card">
          <div class="empty">章节为空，先建一个「第 1 章」吧。</div>
        </div>

        <div v-for="chapter in chapters" :key="chapter.id" class="card">
          <div class="card-title" style="align-items: flex-start">
            <div style="min-width: 0">
              <div class="row wrap" style="gap: 8px">
                <span class="badge blue"># {{ chapter.order_no }}</span>
                <strong>{{ chapter.title }}</strong>
                <span class="faint small">{{ chapter.task_count }} 个任务点</span>
              </div>
              <div v-if="chapter.description" class="small muted" style="margin-top: 4px">
                {{ chapter.description }}
              </div>
            </div>
            <div class="row" style="gap: 6px">
              <span v-if="chapter.task_count" class="badge" :class="chapter.progress >= 100 ? 'green' : 'gray'">
                {{ chapter.progress }}%
              </span>
              <button v-if="canManage" class="btn sm ghost" @click="openChapterForm(chapter)">编辑</button>
              <button
                v-if="canManage"
                class="btn sm danger"
                :disabled="chapterActingId === chapter.id"
                @click="deleteChapter(chapter)"
              >
                {{ chapterActingId === chapter.id ? '删除中…' : '删除' }}
              </button>
              <button v-if="canManage" class="btn sm" @click="openTaskForm(chapter)">＋ 任务点</button>
            </div>
          </div>

          <div v-if="chapter.task_count" class="progress" style="margin-bottom: 4px">
            <i :style="{ width: `${chapter.progress}%` }" />
          </div>

          <div v-if="!chapter.tasks.length" class="empty" style="padding: 18px">
            {{ canManage ? '该章节还没有任务点。' : '该章节暂无内容。' }}
          </div>

          <div
            v-for="task in chapter.tasks"
            :key="task.id"
            style="padding: 12px 0; border-bottom: 1px solid var(--border)"
          >
            <div class="row between" style="gap: 12px; align-items: flex-start">
              <div style="min-width: 0; flex: 1">
                <div class="row wrap" style="gap: 6px">
                  <span class="badge" :class="taskTypeBadge(task.type)">{{ task.type_label }}</span>
                  <strong>{{ task.title }}</strong>
                  <span v-if="!task.required" class="badge gray">选做</span>
                  <span v-if="task.duration" class="faint small">约 {{ task.duration }} 分钟</span>
                </div>
                <div v-if="task.description" class="small muted" style="margin-top: 4px">
                  {{ task.description }}
                </div>

                <div v-if="auth.isStudent" class="row wrap" style="gap: 8px; margin-top: 8px">
                  <div class="progress" style="width: 160px">
                    <i :style="{ width: `${task.progress || 0}%` }" />
                  </div>
                  <span class="small faint mono">{{ task.progress || 0 }}%</span>
                  <span v-if="task.completed" class="badge green">已完成</span>
                  <span v-else-if="task.my_progress" class="badge yellow">进行中</span>
                  <span v-else class="badge gray">未开始</span>
                </div>

                <div v-else class="row wrap" style="gap: 8px; margin-top: 8px">
                  <div class="progress" style="width: 160px">
                    <i :style="{ width: `${task.progress || 0}%` }" />
                  </div>
                  <span class="small faint">
                    {{ task.completed_count || 0 }} / {{ task.student_count || 0 }} 人完成
                  </span>
                </div>
              </div>

              <div class="row" style="gap: 6px; flex-shrink: 0">
                <button
                  v-if="task.type === 'material' && task.resource_id"
                  class="btn sm ghost"
                  @click="downloadResource({ id: task.resource_id, title: task.resource_title, filename: task.resource_filename })"
                >
                  查看资料
                </button>
                <button
                  v-if="task.type === 'assignment' && task.assignment_id"
                  class="btn sm ghost"
                  @click="openAssignment(task)"
                >
                  去作业
                </button>
                <button
                  v-if="task.type === 'quiz' && task.quiz_id && auth.isStudent"
                  class="btn sm ghost"
                  @click="openQuiz(task)"
                >
                  去测验
                </button>
                <button
                  v-if="task.type === 'discussion'"
                  class="btn sm ghost"
                  @click="activeTab = 'discussions'"
                >
                  去讨论
                </button>

                <template v-if="auth.isStudent">
                  <button
                    v-if="!task.my_progress"
                    class="btn sm"
                    :disabled="taskActingId === task.id"
                    @click="startTask(task)"
                  >
                    开始学习
                  </button>
                  <button
                    v-else-if="!task.completed"
                    class="btn sm primary"
                    :disabled="taskActingId === task.id"
                    @click="completeTask(task)"
                  >
                    {{ taskActingId === task.id ? '保存中…' : '标记完成' }}
                  </button>
                  <span v-else class="small" style="color: var(--success)">✓</span>
                </template>
                <template v-else-if="canManage">
                  <button class="btn sm ghost" @click="openTaskForm(chapter, task)">编辑</button>
                  <button
                    class="btn sm danger"
                    :disabled="taskActingId === task.id"
                    @click="deleteTask(task)"
                  >
                    删除
                  </button>
                </template>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ================= 教学班 ================= -->
      <template v-if="activeTab === 'classes'">
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
      </template>

      <!-- ================= 课程公告 ================= -->
      <div v-if="activeTab === 'announcements'" class="card">
        <div class="card-title">
          <span>课程公告</span>
          <button v-if="canManage" class="btn sm primary" @click="openAnnForm()">发布公告</button>
        </div>
        <div v-if="!announcements.length" class="empty">暂无公告</div>
        <div v-else>
          <div
            v-for="item in announcements"
            :key="item.id"
            style="padding: 12px 0; border-bottom: 1px solid var(--border)"
          >
            <div class="row between" style="gap: 12px; align-items: flex-start">
              <div style="min-width: 0; flex: 1">
                <div class="row wrap" style="gap: 6px">
                  <span v-if="item.pinned" class="badge yellow">置顶</span>
                  <strong>{{ item.title }}</strong>
                </div>
                <div class="faint small">
                  {{ item.author_name || '未知发布人' }} · {{ relativeTime(item.created_at) }}
                </div>
              </div>
              <div v-if="canManage" class="row" style="gap: 6px">
                <button class="btn sm ghost" @click="openAnnForm(item)">编辑</button>
                <button
                  class="btn sm danger"
                  :disabled="annActingId === item.id"
                  @click="deleteAnn(item)"
                >
                  {{ annActingId === item.id ? '删除中…' : '删除' }}
                </button>
              </div>
            </div>

            <p v-if="item.content" class="muted small" :style="annStyle(item)">{{ item.content }}</p>

            <button
              v-if="item.content && (item.content.length > ANN_PREVIEW_LENGTH || item.content.split('\n').length > 3)"
              class="btn ghost sm"
              style="padding: 2px 6px; margin-top: 4px"
              @click="toggleAnn(item.id)"
            >
              {{ expandedAnn[item.id] ? '收起 ▲' : '展开 ▼' }}
            </button>
          </div>
        </div>
      </div>

      <!-- ================= 课程资料 ================= -->
      <div v-if="activeTab === 'resources'" class="card">
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

      <!-- ================= 讨论区 ================= -->
      <div v-if="activeTab === 'discussions'" class="card">
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

    <!-- 新建 / 编辑章节 -->
    <div v-if="showChapter" class="modal-mask" @click.self="showChapter = false">
      <form class="modal" @submit.prevent="submitChapter">
        <div class="modal-head">
          <h3>{{ editingChapterId ? '编辑章节' : '新建章节' }}</h3>
          <button type="button" class="btn ghost sm" @click="showChapter = false">✕</button>
        </div>
        <div class="field">
          <label>章节标题</label>
          <input v-model="chapterForm.title" class="input" placeholder="如 第 1 章 绪论" maxlength="120" />
        </div>
        <div class="field">
          <label>章节说明</label>
          <textarea v-model="chapterForm.description" class="textarea" placeholder="本章的学习目标、重点（选填）" maxlength="2000" />
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showChapter = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingChapter">
            {{ savingChapter ? '保存中…' : editingChapterId ? '保存修改' : '创建章节' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 新建 / 编辑任务点 -->
    <div v-if="showTask" class="modal-mask" @click.self="showTask = false">
      <form class="modal" @submit.prevent="submitTask">
        <div class="modal-head">
          <h3>{{ editingTaskId ? '编辑任务点' : '新建任务点' }}</h3>
          <button type="button" class="btn ghost sm" @click="showTask = false">✕</button>
        </div>
        <div class="form-row">
          <div class="field">
            <label>任务点类型</label>
            <select v-model="taskForm.type" class="select" @change="onTaskTypeChange">
              <option value="material">资料</option>
              <option value="assignment">作业</option>
              <option value="quiz">测验</option>
              <option value="discussion">讨论</option>
              <option value="text">图文</option>
            </select>
          </div>
          <div class="field">
            <label>预计时长（分钟）</label>
            <input v-model="taskForm.duration" class="input" type="number" min="0" max="600" />
          </div>
        </div>
        <div class="field">
          <label>任务点标题</label>
          <input v-model="taskForm.title" class="input" placeholder="如 阅读课程大纲 / 完成第一次上机" maxlength="120" />
        </div>
        <div v-if="['material', 'assignment', 'quiz'].includes(taskForm.type)" class="field">
          <label>关联内容</label>
          <select v-model="taskForm.link_id" class="select">
            <option value="">不关联</option>
            <option v-for="option in taskLinkOptions" :key="option.id" :value="option.id">
              {{ option.label }}
            </option>
          </select>
          <div v-if="!taskLinkOptions.length" class="hint">
            暂无可选内容，可先在「资料 / 教学班」里创建，或先建一个纯图文任务点。
          </div>
        </div>
        <div class="field">
          <label>任务说明</label>
          <textarea v-model="taskForm.description" class="textarea" placeholder="学生需要做什么（选填）" maxlength="2000" />
        </div>
        <div class="field">
          <label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
            <input v-model="taskForm.required" type="checkbox" style="width: auto" />
            <span>设为必修任务点（计入进度）</span>
          </label>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showTask = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingTask">
            {{ savingTask ? '保存中…' : editingTaskId ? '保存修改' : '创建任务点' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 教师端：任务点完成明细 -->
    <div v-if="showProgress" class="modal-mask" @click.self="showProgress = false">
      <div class="modal" style="width: min(920px, 94vw); max-height: 86vh; overflow: auto">
        <div class="modal-head">
          <h3>学习进度明细</h3>
          <button type="button" class="btn ghost sm" @click="showProgress = false">✕</button>
        </div>
        <div v-if="loadingProgress" class="loading">正在统计…</div>
        <template v-else-if="progressData">
          <div class="grid cols-3" style="margin-bottom: 16px">
            <div class="stat">
              <div class="stat-label">任务点</div>
              <div class="stat-value">{{ progressData.task_count }}</div>
            </div>
            <div class="stat">
              <div class="stat-label">平均完成度</div>
              <div class="stat-value">{{ progressData.summary.avg_progress }}%</div>
            </div>
            <div class="stat">
              <div class="stat-label">全部完成</div>
              <div class="stat-value">
                {{ progressData.summary.completed_students }} / {{ progressData.summary.student_count }}
              </div>
            </div>
          </div>

          <div class="card-title" style="margin-top: 0"><span>按章节</span></div>
          <div class="table-wrap" style="margin-bottom: 16px">
            <table>
              <thead>
                <tr><th>章节</th><th>任务点</th><th>完成率</th><th>全部完成人数</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in progressData.chapters" :key="item.id">
                  <td>{{ item.title }}</td>
                  <td>{{ item.task_count }}</td>
                  <td style="min-width: 140px">
                    <div class="row" style="gap: 8px">
                      <div class="progress" style="flex: 1"><i :style="{ width: `${item.progress}%` }" /></div>
                      <span class="small mono">{{ item.progress }}%</span>
                    </div>
                  </td>
                  <td>{{ item.completed_students }} 人</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="card-title"><span>按学生</span></div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>学号</th><th>姓名</th><th>教学班</th><th>已完成</th><th>完成度</th><th>最近学习</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in progressData.students" :key="item.student_id">
                  <td class="mono small">{{ item.number || '—' }}</td>
                  <td>{{ item.real_name }}</td>
                  <td class="small muted">{{ item.class_name || '—' }}</td>
                  <td class="small">{{ item.completed_count }} / {{ item.task_count }}</td>
                  <td style="min-width: 150px">
                    <div class="row" style="gap: 8px">
                      <div class="progress" style="flex: 1"><i :style="{ width: `${item.progress}%` }" /></div>
                      <span class="small mono">{{ item.progress }}%</span>
                    </div>
                  </td>
                  <td class="small faint">{{ item.last_active_at ? relativeTime(item.last_active_at) : '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="!progressData.students.length" class="empty">还没有学生加入教学班</div>
        </template>
      </div>
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

    <!-- 发布 / 编辑公告 -->
    <div v-if="showAnn" class="modal-mask" @click.self="showAnn = false">
      <form class="modal" @submit.prevent="submitAnn">
        <div class="modal-head">
          <h3>{{ editingAnnId ? '编辑公告' : '发布公告' }}</h3>
          <button type="button" class="btn ghost sm" @click="showAnn = false">✕</button>
        </div>
        <div class="field">
          <label>公告标题</label>
          <input v-model="annForm.title" class="input" placeholder="一句话说明公告内容" maxlength="120" />
        </div>
        <div class="field">
          <label>公告正文</label>
          <textarea
            v-model="annForm.content"
            class="textarea"
            placeholder="补充详细说明（选填）"
            maxlength="20000"
          />
        </div>
        <div class="field">
          <label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
            <input v-model="annForm.pinned" type="checkbox" style="width: auto" />
            <span>置顶该公告</span>
          </label>
          <div class="hint">置顶公告会排在列表最前面</div>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showAnn = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingAnn">
            {{ savingAnn ? '保存中…' : editingAnnId ? '保存修改' : '发布公告' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
