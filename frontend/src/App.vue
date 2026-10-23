<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import { api } from '@/api/client'

const auth = useAuthStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const unread = ref(0)
let timer = null

const isLoginPage = computed(() => route.meta.public === true)

const navItems = computed(() => {
  const role = auth.user?.role
  const items = [{ name: 'dashboard', label: '工作台', icon: '◈', group: '概览' }]
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

onMounted(() => {
  refreshUnread()
  timer = window.setInterval(refreshUnread, 30000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <router-view v-if="isLoginPage" />

  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">E</div>
        <div class="brand-text">
          <strong>EduFlow</strong>
          <span>教务系统 v1.0</span>
        </div>
      </div>

      <template v-for="group in groupedNav" :key="group.title">
        <div class="nav-group-title">{{ group.title }}</div>
        <router-link
          v-for="item in group.items"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav-item"
          :class="{ active: route.name === item.name }"
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
        <div class="topbar-title">{{ pageTitle }}</div>
        <div class="topbar-right">
          <div class="nav-item" style="padding: 6px 10px" @click="go('notifications')">
            <span class="nav-icon">✦</span>
            <span>通知</span>
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
            <div class="small muted">{{ auth.displayName }}</div>
          </div>
        </div>
      </header>

      <section class="content">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </section>
    </div>
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
