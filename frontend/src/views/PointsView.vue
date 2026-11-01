<script setup>
/**
 * 学分 / 德育分：老师给学生加扣学分，管理员加扣德育分，学生收到通知。
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

const students = ref([])
const loading = ref(true)
const keyword = ref('')
const showModal = ref(false)
const target = ref(null)
const saving = ref(false)
const form = ref({ kind: 'credit', direction: 'add', amount: 1, reason: '' })

const isAdmin = computed(() => auth.isAdmin)

async function load() {
  loading.value = true
  try {
    const q = keyword.value ? `?q=${encodeURIComponent(keyword.value)}` : ''
    students.value = await api.get(`/api/points/students${q}`)
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

function openAdjust(student, kind) {
  target.value = student
  form.value = { kind, direction: 'add', amount: 1, reason: '' }
  showModal.value = true
}

async function submit() {
  if (!form.value.reason.trim()) return ui.error('请填写理由')
  const amount = Math.abs(Number(form.value.amount) || 0)
  if (!amount) return ui.error('分值不能为 0')
  const delta = form.value.direction === 'sub' ? -amount : amount
  saving.value = true
  try {
    await api.post(`/api/points/students/${target.value.id}`, {
      kind: form.value.kind,
      delta,
      reason: form.value.reason.trim(),
    })
    ui.success('已记录，学生已收到通知')
    showModal.value = false
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>学分 / 德育分</h1>
        <p>
          {{ isAdmin ? '管理员可调整德育分（初始 50 分）与学分' : '老师可调整学分（初始 0 分）' }}
          ，每次调整需填写理由，学生会收到通知
        </p>
      </div>
      <div class="row" style="gap: 8px">
        <input
          v-model="keyword"
          class="input"
          placeholder="搜索姓名 / 学号"
          style="width: 200px"
          @keyup.enter="load"
        />
        <button class="btn" @click="load">搜索</button>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>
    <div v-else-if="!students.length" class="card empty" style="text-align: center; padding: 26px">
      没有找到学生
    </div>

    <div v-else class="card" style="padding: 0">
      <table class="table">
        <thead>
          <tr>
            <th>学生</th>
            <th>学号</th>
            <th>班级</th>
            <th>学分</th>
            <th>德育分</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in students" :key="s.id">
            <td><strong>{{ s.real_name }}</strong></td>
            <td class="mono small">{{ s.number || s.username }}</td>
            <td class="small">{{ s.class_name || '—' }}</td>
            <td>
              <span class="badge" :class="s.credit > 0 ? 'green' : s.credit < 0 ? 'red' : 'gray'">
                {{ s.credit }}
              </span>
            </td>
            <td>
              <span class="badge" :class="s.moral >= 60 ? 'green' : s.moral < 50 ? 'red' : 'blue'">
                {{ s.moral }}
              </span>
            </td>
            <td style="text-align: right">
              <div class="row" style="gap: 6px; justify-content: flex-end">
                <button class="btn sm" @click="openAdjust(s, 'credit')">学分</button>
                <button v-if="isAdmin" class="btn sm" @click="openAdjust(s, 'moral')">德育分</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showModal" class="modal-mask" @click.self="showModal = false">
      <div class="modal" style="width: min(480px, 94vw)">
        <div class="modal-head">
          <h3>{{ form.kind === 'moral' ? '德育分' : '学分' }}调整 · {{ target?.real_name }}</h3>
        </div>

        <div class="field">
          <label>加分还是扣分</label>
          <div class="row" style="gap: 14px">
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="form.direction" type="radio" value="add" /> 加分
            </label>
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="form.direction" type="radio" value="sub" /> 扣分
            </label>
          </div>
        </div>

        <div class="field">
          <label>分值</label>
          <input
            v-model="form.amount"
            class="input"
            type="number"
            step="0.5"
            min="0.5"
            max="100"
            style="max-width: 140px"
          />
          <div class="hint">单次不超过 100 分</div>
        </div>

        <div class="field">
          <label>理由</label>
          <input v-model="form.reason" class="input" placeholder="例如：课堂回答优秀 / 旷课 / 参加志愿活动" />
        </div>

        <div class="form-actions">
          <button class="btn" @click="showModal = false">取消</button>
          <button class="btn primary" :disabled="saving" @click="submit">
            {{ saving ? '提交中…' : '确定' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
