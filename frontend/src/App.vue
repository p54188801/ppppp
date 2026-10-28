<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { api } from '@/api/client'

const auth = useAuthStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const unread = ref(0)
const sidebarOpen = ref(false)
let timer = null

// 顶栏全局搜索关键词
const topSearch = ref('')

const contentRef = ref(null)

const isLoginPage = computed(() => route.meta.public === true)

// ---------------------------------------------------------------------------
// 滚动：滚轮走浏览器原生行为，这里补上键盘控制
// ---------------------------------------------------------------------------

const TYPING_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT'])

function isTyping(target) {
  if (!target) return false
  if (TYPING_TAGS.has(target.tagName)) return true
  return target.isContentEditable === true
}

function scrollContent(delta) {
  const el = contentRef.value
  if (!el) return
  el.scrollBy({ top: delta, behavior: 'smooth' })
}

function onKeydown(event) {
  if (event.ctrlKey || event.altKey || event.metaKey) return
  if (isTyping(event.target)) return
  // 焦点在按钮/链接上时，空格和回车应该触发它们自己的行为
  const tag = event.target?.tagName
  if ((tag === 'BUTTON' || tag === 'A') && (event.key === ' ' || event.key === 'Enter')) return

  const el = contentRef.value
  if (!el) return
  const page = el.clientHeight * 0.85

  switch (event.key) {
    case 'ArrowDown':
      scrollContent(80)
      break
    case 'ArrowUp':
      scrollContent(-80)
      break
    case 'PageDown':
      scrollContent(page)
      break
    case 'PageUp':
      scrollContent(-page)
      break
    case ' ':
      scrollContent(event.shiftKey ? -page : page)
      break
    case 'Home':
      el.scrollTo({ top: 0, behavior: 'smooth' })
      break
    case 'End':
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
      break
    default:
      return
  }
  event.preventDefault()
}

const navItems = computed(() => {
  const role = auth.user?.role
  const items = [{ name: 'dashboard', label: '工作台', icon: '◈', group: '概览' }]
  items.push({ name: 'group', label: '班级群', icon: '👥', group: '学习' })
  items.push({ name: 'timetable', label: '课表', icon: '🗓', group: '学习' })
  if (!role) return items

  if (role === 'student') {
    items.push(
      { name: 'courses', label: '我的课程', icon: '▤', group: '学习' },
      { name: 'my-assignments', label: '我的作业', icon: '✎', group: '学习' },
      { name: 'attendance', label: '课堂签到', icon: '◉', group: '学习' },
      { name: 'grades', label: '我的成绩', icon: '★', group: '学习' },
    )
  } else if (role === 'teacher') {
    items.push(
      { name: 'courses', label: '我的课程', icon: '▤', group: '教学' },
      { name: 'attendance', label: '签到管理', icon: '◉', group: '教学' },
    )
  } else {
    items.push(
      { name: 'courses', label: '课程管理', icon: '▤', group: '管理' },
      { name: 'admin-users', label: '用户管理', icon: '☷', group: '管理' },
      { name: 'admin-backup', label: '数据备份', icon: '⛁', group: '管理' },
    )
  }
  items.push({ name: 'notifications', label: '通知', icon: '✦', group: '其他' })
  items.push({ name: 'profile', label: '个人中心', icon: '☺', group: '其他' })
  return items
})

const groupedNav = computed(() => {
  const groups = new Map()
  navItems.value.forEach((item) => {
    const key = item.group || '导航'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(item)
  })
  return Array.from(groups.entries()).map(([title, items]) => ({ title, items }))
})

const pageTitle = computed(() => route.meta.title || 'EduFlow')
const initials = computed(() => (auth.displayName || 'U').slice(0, 1))

async function refreshUnread() {
  if (!auth.token || isLoginPage.value) return
  try {
    const data = await api.get('/api/notifications/unread-count')
    unread.value = data.count || 0
  } catch {
    /* 静默失败，不打扰用户 */
  }
}

async function handleLogout() {
  const ok = await ui.confirm({ title: '退出登录', message: '确定要退出当前账号吗？' })
  if (!ok) return
  await auth.logout()
  router.replace({ name: 'login' })
}

function go(name) {
  router.push({ name })
}

/** 顶栏搜索：回车跳转搜索页，关键词放在 query 里便于分享与回退 */
function handleTopSearch() {
  const keyword = topSearch.value.trim()
  if (!keyword) {
    ui.error('请输入搜索关键词')
    return
  }
  router.push({ name: 'search', query: { q: keyword } })
}

// 站在搜索页时，让顶栏输入框与地址栏关键词保持一致
watch(
  () => route.query.q,
  (value) => {
    if (route.name === 'search' && typeof value === 'string') topSearch.value = value
  },
)

// 手机端：切页后自动收起侧边栏
watch(
  () => route.fullPath,
  () => {
    sidebarOpen.value = false
  },
)


// ---------------------------------------------------------------------------
// 悬停 2 秒显示功能说明
// ---------------------------------------------------------------------------
const hoverTip = ref({ show: false, text: '', x: 0, y: 0 })
let hoverTimer = null

const TIP_TEXT = {
  登录: '输入账号密码进入系统',
  注册: '新用户登记，学生和老师都能注册',
  立即注册: '第一次使用请先注册账号',
}

function tipLabel(el) {
  const explicit = el.getAttribute('data-tip')
  if (explicit) return explicit
  const text = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ')
  if (!text) return ''
  if (text.length > 18) return ''
  return TIP_TEXT[text] || `点击「${text}」`
}

function onHoverIn(event) {
  const el = event.target.closest && event.target.closest('button, a, .nav-item')
  if (!el) return
  const label = tipLabel(el)
  if (!label) return
  const rect = el.getBoundingClientRect()
  clearTimeout(hoverTimer)
  hoverTimer = setTimeout(() => {
    hoverTip.value = {
      show: true,
      text: label,
      x: Math.min(rect.left, window.innerWidth - 260),
      y: rect.bottom + 8,
    }
  }, 2000)
}

function onHoverOut() {
  clearTimeout(hoverTimer)
  hoverTip.value.show = false
}

onMounted(() => {
  refreshUnread()
  // 直接刷新/回退到搜索页时，顶栏也要带上当前关键词
  if (route.name === 'search' && typeof route.query.q === 'string') topSearch.value = route.query.q
  timer = window.setInterval(refreshUnread, 30000)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('mouseover', onHoverIn)
  window.addEventListener('mouseout', onHoverOut)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('mouseover', onHoverIn)
  window.removeEventListener('mouseout', onHoverOut)
})
</script>

<template>
  <router-view v-if="isLoginPage" />

  <div v-else class="shell" :class="{ 'sidebar-open': sidebarOpen }">
    <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false" />
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="brand">
        <div class="brand-mark">E</div>
        <div class="brand-text">
          <strong>EduFlow</strong>
          <span>教务系统 v1.0</span>
        </div>
        <button
          type="button"
          class="sidebar-close"
          aria-label="关闭导航菜单"
          @click="sidebarOpen = false"
        >
          ✕
        </button>
      </div>

      <template v-for="group in groupedNav" :key="group.title">
        <div class="nav-group-title">{{ group.title }}</div>
        <router-link
          v-for="item in group.items"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav-item"
          :class="{ active: route.name === item.name }"
          @click="sidebarOpen = false"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </router-link>
      </template>

      <div class="spacer" />
      <div class="nav-group-title" style="padding-bottom: 4px">
        {{ auth.roleLabel }} · {{ auth.displayName }}
      </div>
      <div class="nav-item" @click="handleLogout">
        <span class="nav-icon">⏻</span>
        <span>退出登录</span>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="row" style="gap: 8px; min-width: 0">
          <button
            type="button"
            class="mobile-menu"
            aria-label="打开导航菜单"
            @click="sidebarOpen = !sidebarOpen"
          >
            ☰
          </button>
          <div class="topbar-title">{{ pageTitle }}</div>
        </div>
        <div class="topbar-right">
          <input
            v-model="topSearch"
            class="input topbar-search"
            style="width: 220px; background: var(--bg-soft)"
            placeholder="搜索课程 / 作业 / 资料…"
            maxlength="64"
            aria-label="全局搜索"
            @keyup.enter="handleTopSearch"
          />
          <div class="nav-item topbar-action" style="padding: 6px 10px" @click="go('notifications')">
            <span class="nav-icon">✦</span>
            <span class="topbar-action-label">通知</span>
            <span v-if="unread" class="badge red">{{ unread }}</span>
          </div>
          <div
            class="row"
            style="gap: 8px; cursor: pointer"
            @click="go('profile')"
            title="个人中心"
          >
            <div class="brand-mark" style="width: 30px; height: 30px; font-size: 13px">
              {{ initials }}
            </div>
            <div class="small muted user-name">{{ auth.displayName }}</div>
          </div>
        </div>
      </header>

      <section class="content" ref="contentRef" tabindex="0">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </section>
    </div>
  </div>

  <!-- 悬停说明 -->
  <div
    v-if="hoverTip.show"
    class="hover-tip"
    :style="{ left: hoverTip.x + 'px', top: hoverTip.y + 'px' }"
  >
    {{ hoverTip.text }}
  </div>

  <!-- 全局提示 -->
  <div class="toast-wrap">
    <div v-for="item in ui.toasts" :key="item.id" class="toast" :class="item.type">
      {{ item.message }}
    </div>
  </div>

  <!-- 全局确认框 -->
  <div v-if="ui.confirmState" class="modal-mask" @click.self="ui.resolveConfirm(false)">
    <div class="modal" style="width: min(420px, 92vw)">
      <div class="modal-head">
        <h3>{{ ui.confirmState.title }}</h3>
      </div>
      <p class="muted" style="margin-top: 0">{{ ui.confirmState.message }}</p>
      <div class="form-actions">
        <button class="btn" @click="ui.resolveConfirm(false)">取消</button>
        <button
          class="btn"
          :class="ui.confirmState.danger ? 'danger' : 'primary'"
          @click="ui.resolveConfirm(true)"
        >
          {{ ui.confirmState.confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>
