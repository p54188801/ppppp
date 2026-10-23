<script setup>
/**
 * 个人中心页（全角色）
 * 职责：展示当前登录用户的资料卡，提供修改密码（带强度提示，成功后强制重新登录）
 *       以及查看本账号在线会话记录。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, formatDate } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()

const loading = ref(true)
const me = ref(null)
const sessions = ref([])

const passwordForm = ref({ old_password: '', new_password: '', confirm: '' })
const strength = ref(null)
const changing = ref(false)
let strengthTimer = null

const strengthPercent = computed(() => {
  if (!strength.value) return 0
  return Math.min(100, (Number(strength.value.score) || 0) * 20)
})

const strengthColor = computed(() => {
  const score = Number(strength.value?.score) || 0
  if (score <= 1) return 'var(--danger)'
  if (score === 2) return 'var(--warning)'
  if (score === 3) return 'var(--primary)'
  return 'var(--success)'
})

const canSubmit = computed(
  () =>
    Boolean(passwordForm.value.old_password) &&
    passwordForm.value.new_password.length >= 6 &&
    passwordForm.value.confirm.length >= 6 &&
    !changing.value,
)

function roleLabel(value) {
  if (value === 'student') return '学生'
  if (value === 'teacher') return '教师'
  if (value === 'admin') return '管理员'
  return value || '—'
}

async function load() {
  loading.value = true
  try {
    const [profile, sessionList] = await Promise.all([
      api.get('/api/auth/me'),
      api.get('/api/auth/sessions'),
    ])
    me.value = profile
    sessions.value = sessionList || []
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

function onPasswordInput() {
  const value = passwordForm.value.new_password
  if (strengthTimer) window.clearTimeout(strengthTimer)
  if (!value) {
    strength.value = null
    return
  }
  strengthTimer = window.setTimeout(async () => {
    try {
      strength.value = await api.post('/api/auth/password/strength', { password: value })
    } catch {
      strength.value = null
    }
  }, 280)
}

async function submitPassword() {
  const { old_password: oldPassword, new_password: newPassword, confirm } = passwordForm.value
  if (!oldPassword) {
    ui.error('请输入当前密码')
    return
  }
  if (newPassword.length < 6) {
    ui.error('新密码至少需要 6 个字符')
    return
  }
  if (newPassword !== confirm) {
    ui.error('两次输入的新密码不一致')
    return
  }
  if (newPassword === oldPassword) {
    ui.error('新密码不能与当前密码相同')
    return
  }
  changing.value = true
  try {
    await api.post('/api/auth/password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
    ui.success('密码已修改，请使用新密码重新登录')
    passwordForm.value = { old_password: '', new_password: '', confirm: '' }
    strength.value = null
    await auth.logout()
    router.replace({ name: 'login' })
  } catch (error) {
    ui.error(error.message)
  } finally {
    changing.value = false
  }
}

function deviceText(userAgent) {
  if (!userAgent) return '未知设备'
  const text = String(userAgent)
  return text.length > 64 ? `${text.slice(0, 64)}…` : text
}

onMounted(load)

onUnmounted(() => {
  if (strengthTimer) window.clearTimeout(strengthTimer)
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>{{ me ? me.real_name : '个人中心' }}</h1>
        <p>{{ me ? `${roleLabel(me.role)} · ${me.username}` : '查看资料、修改密码与在线会话' }}</p>
      </div>
      <button class="btn ghost" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="loading">正在加载个人资料…</div>

    <template v-else-if="me">
      <div class="grid cols-2">
        <!-- 资料卡 -->
        <div class="card" style="margin-top: 0">
          <div class="card-title">
            <span>基本资料</span>
            <span class="badge" :class="me.role === 'admin' ? 'purple' : me.role === 'teacher' ? 'blue' : 'gray'">
              {{ roleLabel(me.role) }}
            </span>
          </div>

          <div class="row" style="gap: 14px; margin-bottom: 16px">
            <div class="brand-mark" style="width: 52px; height: 52px; font-size: 20px">
              {{ (me.real_name || 'U').slice(0, 1) }}
            </div>
            <div>
              <div style="font-size: 16px; font-weight: 650">{{ me.real_name }}</div>
              <div class="small faint">{{ me.username }}</div>
            </div>
          </div>

          <div class="grid cols-2" style="gap: 12px">
            <div>
              <div class="stat-label">学号 / 工号</div>
              <div class="mono small">{{ me.number || '—' }}</div>
            </div>
            <div>
              <div class="stat-label">院系</div>
              <div class="small">{{ me.department || '—' }}</div>
            </div>
            <div>
              <div class="stat-label">班级</div>
              <div class="small">{{ me.class_name || '—' }}</div>
            </div>
            <div>
              <div class="stat-label">邮箱</div>
              <div class="small">{{ me.email || '—' }}</div>
            </div>
            <div>
              <div class="stat-label">电话</div>
              <div class="small">{{ me.phone || '—' }}</div>
            </div>
            <div>
              <div class="stat-label">账号状态</div>
              <span class="badge" :class="me.status === 'active' ? 'green' : 'red'">
                {{ me.status === 'active' ? '正常' : '已禁用' }}
              </span>
            </div>
            <div>
              <div class="stat-label">注册时间</div>
              <div class="small faint">{{ formatDate(me.created_at) }}</div>
            </div>
            <div>
              <div class="stat-label">最后登录</div>
              <div class="small faint">{{ me.last_login_at ? formatDate(me.last_login_at, true) : '—' }}</div>
            </div>
          </div>

          <div v-if="me.must_change_password" class="hint" style="margin-top: 14px; color: var(--warning)">
            当前仍在使用初始密码，建议立即修改。
          </div>
        </div>

        <!-- 修改密码 -->
        <div class="card" style="margin-top: 0">
          <div class="card-title"><span>修改密码</span></div>
          <form @submit.prevent="submitPassword">
            <div class="field">
              <label>当前密码</label>
              <input
                v-model="passwordForm.old_password"
                class="input"
                type="password"
                autocomplete="current-password"
                placeholder="请输入当前密码"
              />
            </div>
            <div class="field">
              <label>新密码</label>
              <input
                v-model="passwordForm.new_password"
                class="input"
                type="password"
                autocomplete="new-password"
                placeholder="至少 6 位，建议包含大小写与符号"
                @input="onPasswordInput"
              />
              <div v-if="strength" style="margin-top: 8px">
                <div class="progress">
                  <i :style="{ width: `${strengthPercent}%`, background: strengthColor }" />
                </div>
                <div class="row between" style="margin-top: 4px">
                  <span class="small" :style="{ color: strengthColor }">强度：{{ strength.label }}</span>
                  <span class="small faint">{{ strengthPercent }}%</span>
                </div>
                <div v-if="(strength.issues || []).length" class="hint">
                  {{ (strength.issues || []).join('；') }}
                </div>
              </div>
            </div>
            <div class="field">
              <label>确认新密码</label>
              <input
                v-model="passwordForm.confirm"
                class="input"
                type="password"
                autocomplete="new-password"
                placeholder="再次输入新密码"
              />
              <div
                v-if="passwordForm.confirm && passwordForm.confirm !== passwordForm.new_password"
                class="hint"
                style="color: var(--danger)"
              >
                两次输入的新密码不一致
              </div>
            </div>
            <div class="hint">修改成功后当前登录状态会失效，需要使用新密码重新登录。</div>
            <div class="form-actions">
              <button type="submit" class="btn primary" :disabled="!canSubmit">
                {{ changing ? '提交中…' : '修改密码' }}
              </button>
            </div>
          </form>
        </div>
      </div>

      <!-- 在线会话 -->
      <div class="card">
        <div class="card-title">
          <span>在线会话</span>
          <span class="faint small">共 {{ sessions.length }} 条有效会话</span>
        </div>
        <div v-if="!sessions.length" class="empty">暂无在线会话记录</div>
        <div v-else class="table-wrap" style="border: none">
          <table>
            <thead>
              <tr>
                <th>IP 地址</th>
                <th>设备 / 浏览器</th>
                <th>登录时间</th>
                <th>过期时间</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="session in sessions" :key="session.id">
                <td class="mono small">{{ session.ip || '—' }}</td>
                <td class="small muted">{{ deviceText(session.user_agent) }}</td>
                <td class="small faint">{{ formatDate(session.created_at, true) }}</td>
                <td class="small faint">{{ formatDate(session.expires_at, true) }}</td>
                <td><span class="badge green">有效</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-else class="empty">无法获取个人资料，请刷新页面重试</div>
  </div>
</template>
