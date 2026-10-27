<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref('')
const showDemo = ref(false)

const canSubmit = computed(() => username.value.trim() && password.value && !auth.loading)

const demoAccounts = [
  { label: '管理员', user: 'admin', desc: '全局管理、用户与设置' },
  { label: '教师', user: 't1001', desc: '建课、发作业、批改' },
  { label: '学生', user: 's2001', desc: '选课、交作业、测验签到' },
]

function fill(user) {
  username.value = user
  password.value = 'Eduflow@2026'
  showDemo.value = false
}

async function submit() {
  if (!canSubmit.value) return
  error.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    ui.success(`欢迎回来，${auth.displayName}`)
    const redirect = route.query.redirect
    router.replace(typeof redirect === 'string' ? redirect : { name: 'dashboard' })
  } catch (err) {
    error.value = err.message || '登录失败'
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-brand">
        <div class="brand-mark" style="width: 42px; height: 42px; font-size: 17px">E</div>
        <div>
          <div style="font-size: 18px; font-weight: 650">EduFlow</div>
          <div class="small faint">高校教务与教学管理平台</div>
        </div>
      </div>

      <div class="field">
        <label>账号 / 学号</label>
        <input
          v-model="username"
          class="input"
          placeholder="请输入用户名"
          autocomplete="username"
          autofocus
        />
      </div>

      <div class="field">
        <label>密码</label>
        <input
          v-model="password"
          class="input"
          type="password"
          placeholder="请输入密码"
          autocomplete="current-password"
        />
      </div>

      <div v-if="error" class="badge red" style="margin-bottom: 12px">{{ error }}</div>

      <button class="btn primary block" type="submit" :disabled="!canSubmit">
        {{ auth.loading ? '登录中…' : '登 录' }}
      </button>

      <div class="row" style="justify-content: center; margin-top: 14px">
        <router-link class="small" :to="{ name: 'register' }">没有账号？立即注册</router-link>
      </div>

      <div class="demo-accounts">
        <div class="row between">
          <b>演示账号（密码均为 Eduflow@2026）</b>
          <a href="#" class="small" @click.prevent="showDemo = !showDemo">
            {{ showDemo ? '收起' : '填入' }}
          </a>
        </div>
        <div v-if="showDemo" style="margin-top: 8px">
          <div
            v-for="item in demoAccounts"
            :key="item.user"
            class="row between"
            style="cursor: pointer"
            @click="fill(item.user)"
          >
            <span><b>{{ item.label }}</b> {{ item.user }}</span>
            <span class="faint small">{{ item.desc }}</span>
          </div>
        </div>
      </div>
    </form>
  </div>
</template>
