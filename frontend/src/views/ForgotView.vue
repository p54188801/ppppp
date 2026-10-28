<script setup>
/**
 * 忘记密码：用「学号/工号 + 姓名」核对身份，重置为一次性临时密码。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const router = useRouter()
const ui = useUiStore()

const number = ref('')
const realName = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)

const canSubmit = computed(() => number.value.trim() && realName.value.trim() && !loading.value)

async function submit() {
  if (!canSubmit.value) return
  loading.value = true
  error.value = ''
  try {
    result.value = await api.post('/api/auth/forgot-password', {
      number: number.value.trim(),
      real_name: realName.value.trim(),
    })
    ui.success('已生成临时密码')
  } catch (err) {
    error.value = err.message || '重置失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" style="width: min(420px, 92vw)" @submit.prevent="submit">
      <div class="login-brand">
        <div class="brand-mark" style="width: 42px; height: 42px; font-size: 17px">E</div>
        <div>
          <div style="font-size: 18px; font-weight: 650">忘记密码</div>
          <div class="small faint">用学号和姓名核对身份</div>
        </div>
      </div>

      <template v-if="result">
        <div class="badge green" style="display: block; padding: 10px 12px; margin-bottom: 14px">
          已重置成功
        </div>
        <div class="field">
          <label>登录名</label>
          <input class="input" :value="result.username" readonly />
        </div>
        <div class="field">
          <label>临时密码</label>
          <input class="input mono" :value="result.temp_password" readonly style="font-size: 18px; letter-spacing: 2px" />
          <div class="hint">请立刻记下，登录后第一件事是改成自己的密码</div>
        </div>
        <button class="btn primary block" type="button" @click="router.replace({ name: 'login', query: { name: result.username } })">
          去登录
        </button>
      </template>

      <template v-else>
        <div class="field">
          <label>学号 / 工号</label>
          <input v-model="number" class="input" placeholder="注册时填写的学号或工号" />
        </div>
        <div class="field">
          <label>姓名</label>
          <input v-model="realName" class="input" placeholder="注册时填写的姓名" />
        </div>

        <div v-if="error" class="badge red" style="display: block; margin-bottom: 12px">{{ error }}</div>

        <button class="btn primary block" type="submit" :disabled="!canSubmit">
          {{ loading ? '核验中…' : '重置密码' }}
        </button>

        <div class="row" style="justify-content: center; margin-top: 14px">
          <a href="#" class="small" @click.prevent="router.replace({ name: 'login' })">返回登录</a>
        </div>
      </template>
    </form>
  </div>
</template>
