<script setup>
/**
 * 自助注册页：只要姓名、学号/工号、密码。
 * 用户名自动取姓名（重名会自动加序号，注册成功后会提示实际登录名）。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const router = useRouter()
const ui = useUiStore()

const realName = ref('')
const number = ref('')
const password = ref('')
const confirm = ref('')
const role = ref('student')
const loading = ref(false)
const error = ref('')
const done = ref(null)

const canSubmit = computed(() => {
  return realName.value.trim() && number.value.trim() &&
    password.value.length >= 6 && password.value === confirm.value && !loading.value
})

async function submit() {
  if (!canSubmit.value) {
    error.value = password.value !== confirm.value ? '两次输入的密码不一致' : '请完整填写'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await api.post('/api/auth/register', {
      real_name: realName.value.trim(),
      number: number.value.trim(),
      password: password.value,
      role: role.value,
    })
    done.value = data
    ui.success('注册成功')
  } catch (err) {
    error.value = err.message || '注册失败'
  } finally {
    loading.value = false
  }
}

function goLogin() {
  router.replace({ name: 'login', query: { name: done.value?.user?.username || '' } })
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" style="width: min(420px, 92vw)" @submit.prevent="submit">
      <div class="login-brand">
        <div class="brand-mark" style="width: 42px; height: 42px; font-size: 17px">E</div>
        <div>
          <div style="font-size: 18px; font-weight: 650">注册账号</div>
          <div class="small faint">学生 / 教师均可注册</div>
        </div>
      </div>

      <!-- 注册成功 -->
      <template v-if="done">
        <div class="badge green" style="display: block; padding: 10px 12px; margin-bottom: 14px">
          注册成功
        </div>
        <div class="field">
          <label>你的登录名</label>
          <input class="input" :value="done.user.username" readonly />
          <div class="hint">用户名就是你的姓名{{ done.user.username !== done.user.real_name ? '（重名，已自动加序号）' : '' }}</div>
        </div>
        <div class="field">
          <label>身份</label>
          <input class="input" :value="done.user.role === 'teacher' ? '教师' : '学生'" readonly />
        </div>
        <button class="btn primary block" type="button" @click="goLogin">去登录</button>
      </template>

      <!-- 注册表单 -->
      <template v-else>
        <div class="field">
          <label>身份</label>
          <div class="row" style="gap: 10px">
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="role" type="radio" value="student" /> 学生
            </label>
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="role" type="radio" value="teacher" /> 教师
            </label>
          </div>
        </div>

        <div class="field">
          <label>姓名</label>
          <input v-model="realName" class="input" placeholder="请输入真实姓名" autocomplete="name" />
        </div>

        <div class="field">
          <label>{{ role === 'teacher' ? '工号' : '学号' }}</label>
          <input v-model="number" class="input" :placeholder="role === 'teacher' ? '请输入工号' : '请输入学号'" />
        </div>

        <div class="field">
          <label>密码</label>
          <input v-model="password" class="input" type="password" placeholder="至少 6 位" autocomplete="new-password" />
        </div>

        <div class="field">
          <label>确认密码</label>
          <input v-model="confirm" class="input" type="password" placeholder="再输入一次" autocomplete="new-password" />
        </div>

        <div v-if="error" class="badge red" style="margin-bottom: 12px">{{ error }}</div>

        <button class="btn primary block" type="submit" :disabled="!canSubmit">
          {{ loading ? '注册中…' : '注 册' }}
        </button>

        <div class="demo-accounts" style="text-align: center">
          <a href="#" @click.prevent="router.replace({ name: 'login' })">已有账号？返回登录</a>
        </div>
      </template>
    </form>
  </div>
</template>
