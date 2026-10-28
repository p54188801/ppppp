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

const canSubmit = computed(() => username.value.trim() && password.value && !auth.loading)

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
      <div class="row" style="justify-content: center; margin-top: 8px">
        <router-link class="small" :to="{ name: 'forgot' }">忘记密码？</router-link>
      </div>
    </form>
  </div>
</template>
