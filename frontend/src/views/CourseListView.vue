<script setup>
/**
 * 课程列表页（全角色可见）
 * 职责：按关键词分页拉取课程，用卡片网格展示课程代码/教师/学期/学分/教学班与学生数量；
 *       教师与管理员可新建课程，管理员可归档课程。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()

const PAGE_SIZE = 12

const loading = ref(true)
const courses = ref([])
const total = ref(0)
const page = ref(1)
const keyword = ref('')
const actingId = ref(0)

const showCreate = ref(false)
const saving = ref(false)
const form = ref(emptyForm())

const canManage = computed(() => Boolean(auth.isTeacher || auth.isAdmin))
const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function emptyForm() {
  return {
    code: '',
    name: '',
    credits: 2,
    hours: 32,
    category: '必修',
    term: '',
    description: '',
  }
}

async function load() {
  loading.value = true
  try {
    const data = await api.get('/api/courses', {
      keyword: keyword.value.trim(),
      page: page.value,
      page_size: PAGE_SIZE,
    })
    courses.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function goPage(next) {
  if (next < 1 || next > pages.value || next === page.value) return
  page.value = next
  load()
}

function openCourse(id) {
  router.push({ name: 'course-detail', params: { id } })
}

function openCreate() {
  form.value = emptyForm()
  showCreate.value = true
}

async function submitCreate() {
  const code = form.value.code.trim()
  const name = form.value.name.trim()
  if (!code || !name) {
    ui.error('课程代码与课程名称不能为空')
    return
  }
  saving.value = true
  try {
    await api.post('/api/courses', {
      code,
      name,
      credits: Number(form.value.credits) || 2,
      hours: Number(form.value.hours) || 32,
      category: form.value.category,
      term: form.value.term.trim(),
      description: form.value.description.trim(),
    })
    ui.success('课程已创建')
    showCreate.value = false
    page.value = 1
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    saving.value = false
  }
}

async function archiveCourse(course) {
  const ok = await ui.confirm({
    title: '归档课程',
    message: `确定归档《${course.name}》吗？归档后课程将从进行中列表移除。`,
    confirmText: '归档',
    danger: true,
  })
  if (!ok) return
  actingId.value = course.id
  try {
    await api.put(`/api/courses/${course.id}`, { status: 'archived' })
    ui.success('课程已归档')
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingId.value = 0
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>{{ auth.isStudent ? '我的课程' : '课程管理' }}</h1>
        <p>
          共 {{ total }} 门课程
          <template v-if="auth.isStudent">，点击卡片可查看教学班、资料与讨论</template>
          <template v-else>，点击卡片可管理教学班与课程资料</template>
        </p>
      </div>
      <div class="row wrap">
        <input
          v-model="keyword"
          class="input"
          style="width: 220px"
          placeholder="搜索课程名称 / 代码"
          @keyup.enter="search"
        />
        <button class="btn" :disabled="loading" @click="search">搜索</button>
        <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
        <button v-if="canManage" class="btn primary" @click="openCreate">新建课程</button>
      </div>
    </div>

    <div v-if="loading" class="loading">正在加载课程…</div>

    <div v-else-if="!courses.length" class="empty">
      {{ keyword ? '没有匹配的课程，换个关键词试试' : '暂无课程数据' }}
    </div>

    <div v-else class="grid cols-3">
      <div
        v-for="course in courses"
        :key="course.id"
        class="card"
        style="margin-top: 0; cursor: pointer"
        @click="openCourse(course.id)"
      >
        <div class="row between">
          <span class="badge blue mono">{{ course.code }}</span>
          <span class="badge" :class="course.status === 'archived' ? 'gray' : 'green'">
            {{ course.status === 'archived' ? '已归档' : '进行中' }}
          </span>
        </div>

        <div style="font-size: 16px; font-weight: 650; margin: 10px 0 6px">{{ course.name }}</div>

        <div class="row wrap small muted" style="gap: 6px">
          <span>{{ course.teacher_name || '待安排教师' }}</span>
          <span class="faint">·</span>
          <span>{{ course.term || '未设置学期' }}</span>
          <span class="faint">·</span>
          <span>{{ course.credits }} 学分 / {{ course.hours }} 学时</span>
        </div>

        <div class="tag-list" style="margin-top: 12px">
          <span class="badge gray">{{ course.category || '未分类' }}</span>
          <span v-if="course.class_count !== undefined && course.class_count !== null" class="badge gray">
            {{ course.class_count }} 个教学班
          </span>
          <span v-if="course.student_count !== undefined && course.student_count !== null" class="badge gray">
            {{ course.student_count }} 名学生
          </span>
          <span v-else-if="course.class_name" class="badge purple">{{ course.class_name }}</span>
        </div>

        <div class="row between" style="margin-top: 14px">
          <span class="small faint">查看详情 →</span>
          <button
            v-if="auth.isAdmin && course.status !== 'archived'"
            class="btn sm danger"
            :disabled="actingId === course.id"
            @click.stop="archiveCourse(course)"
          >
            {{ actingId === course.id ? '归档中…' : '归档' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="!loading && pages > 1" class="row between" style="margin-top: 16px">
      <span class="small faint">第 {{ page }} / {{ pages }} 页 · 共 {{ total }} 条</span>
      <div class="row">
        <button class="btn sm" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button class="btn sm" :disabled="page >= pages" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>

    <!-- 新建课程 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <form class="modal" @submit.prevent="submitCreate">
        <div class="modal-head">
          <h3>新建课程</h3>
          <button type="button" class="btn ghost sm" @click="showCreate = false">✕</button>
        </div>

        <div class="form-row">
          <div class="field">
            <label>课程代码</label>
            <input v-model="form.code" class="input" placeholder="如 CS101" maxlength="32" />
            <div class="hint">代码会转为大写且不可重复</div>
          </div>
          <div class="field">
            <label>课程名称</label>
            <input v-model="form.name" class="input" placeholder="如 数据结构" maxlength="64" />
          </div>
        </div>

        <div class="form-row">
          <div class="field">
            <label>学分</label>
            <input v-model="form.credits" class="input" type="number" step="0.5" min="0.5" max="20" />
          </div>
          <div class="field">
            <label>学时</label>
            <input v-model="form.hours" class="input" type="number" min="1" max="200" />
          </div>
        </div>

        <div class="form-row">
          <div class="field">
            <label>课程类别</label>
            <select v-model="form.category" class="select">
              <option value="必修">必修</option>
              <option value="选修">选修</option>
              <option value="公共课">公共课</option>
              <option value="实践">实践</option>
            </select>
          </div>
          <div class="field">
            <label>学期</label>
            <input v-model="form.term" class="input" placeholder="留空自动取当前学期" maxlength="16" />
          </div>
        </div>

        <div class="field">
          <label>课程简介</label>
          <textarea v-model="form.description" class="textarea" placeholder="课程目标、考核方式等" maxlength="2000" />
        </div>

        <div class="form-actions">
          <button type="button" class="btn" @click="showCreate = false">取消</button>
          <button type="submit" class="btn primary" :disabled="saving">
            {{ saving ? '创建中…' : '创建课程' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
