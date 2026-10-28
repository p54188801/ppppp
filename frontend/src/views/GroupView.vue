<script setup>
/**
 * 班级群：同班师生在这里聊天、发作业、交作业、批改。
 * 左侧群列表，右侧聊天 + 作业两个标签页。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatDate, relativeTime } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const groups = ref([])
const current = ref(null)
const loading = ref(true)
const tab = ref('chat')
const draft = ref('')
const sending = ref(false)
const fileInput = ref(null)
const showAssign = ref(false)
const assignForm = ref({ title: '', content: '', full_score: 100, deadline: '' })
const submissions = ref([])
const grading = ref(null)

const groupId = computed(() => Number(route.params.id) || 0)

async function loadGroups() {
  groups.value = await api.get('/api/groups').catch(() => [])
  if (!groupId.value && groups.value.length) {
    const id = groups.value[0].id
    router.replace({ name: 'group', params: { id } })
    try {
      current.value = await api.get(`/api/groups/${id}`)
    } catch (error) {
      ui.error(error.message)
    }
    loading.value = false
    return
  }
  if (groupId.value) await loadGroup()
  loading.value = false
}

async function loadGroup() {
  try {
    current.value = await api.get(`/api/groups/${groupId.value}`)
  } catch (error) {
    ui.error(error.message)
  }
}

function switchGroup(id) {
  router.push({ name: 'group', params: { id } })
}

async function send() {
  if (!draft.value.trim() || sending.value) return
  sending.value = true
  try {
    await api.post(`/api/groups/${groupId.value}/messages`, { content: draft.value.trim() })
    draft.value = ''
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  } finally {
    sending.value = false
  }
}

async function pickFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  if (draft.value.trim()) form.append('content', draft.value.trim())
  sending.value = true
  try {
    await api.upload(`/api/groups/${groupId.value}/messages`, form)
    draft.value = ''
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  } finally {
    sending.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function downloadMessage(message) {
  const token = localStorage.getItem('eduflow_token') || ''
  const res = await fetch(`/api/messages/${message.id}/file`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) return ui.error('下载失败')
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = message.file_name || 'file'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function createAssignment() {
  if (!assignForm.value.title.trim()) return ui.error('请填写作业标题')
  try {
    await api.post(`/api/groups/${groupId.value}/assignments`, {
      title: assignForm.value.title.trim(),
      content: assignForm.value.content,
      full_score: Number(assignForm.value.full_score) || 100,
      deadline: assignForm.value.deadline || '',
    })
    showAssign.value = false
    assignForm.value = { title: '', content: '', full_score: 100, deadline: '' }
    await loadGroup()
    tab.value = 'assign'
    ui.success('作业已发布')
  } catch (error) {
    ui.error(error.message)
  }
}

async function submitAssignment(item) {
  const text = window.prompt(`提交「${item.title}」的作业内容（可只上传文件）`, '')
  if (text === null) return
  const form = new FormData()
  form.append('content', text || '')
  const input = document.createElement('input')
  input.type = 'file'
  input.onchange = async () => {
    if (input.files?.[0]) form.append('file', input.files[0])
    try {
      await api.upload(`/api/group-assignments/${item.id}/submit`, form)
      ui.success('已提交')
      await loadGroup()
    } catch (error) {
      ui.error(error.message)
    }
  }
  input.click()
}

async function viewSubmissions(item) {
  try {
    submissions.value = await api.get(`/api/group-assignments/${item.id}/submissions`)
  } catch (error) {
    ui.error(error.message)
  }
}

async function grade(sub) {
  const score = window.prompt(`给 ${sub.student_name} 打分（满分 100）`, sub.score ?? '')
  if (score === null) return
  const feedback = window.prompt('评语（可留空）', sub.feedback || '') || ''
  try {
    await api.post(`/api/group-submissions/${sub.id}/grade`, { score: Number(score), feedback })
    ui.success('已打分')
    await viewSubmissions({ id: sub.assignment_id })
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  }
}

watch(() => route.params.id, (id) => { if (id) loadGroup() })

onMounted(loadGroups)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>班级群</h1>
        <p>同班师生自动在一个群里，可以聊天、发作业、交作业、批改</p>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else class="group-layout">
      <aside class="group-list card">
        <div class="card-title">我的班级</div>
        <div v-if="!groups.length" class="empty" style="text-align: center; padding: 18px 0">
          <div style="margin-bottom: 10px">你还没有加入班级群</div>
          <div class="faint small" style="margin-bottom: 12px">去个人中心填上班级，就会自动进群</div>
          <button class="btn primary sm" @click="router.push({ name: 'profile' })">
            去个人中心设置班级
          </button>
        </div>
        <div
          v-for="g in groups"
          :key="g.id"
          class="group-item"
          :class="{ active: g.id === groupId }"
          @click="switchGroup(g.id)"
        >
          <div class="row between">
            <strong>{{ g.name }}</strong>
            <span class="badge gray">{{ g.member_count }} 人</span>
          </div>
        </div>
      </aside>

      <section v-if="current" class="card group-main">
        <div class="card-title">
          <span>{{ current.name }} · {{ current.members.length }} 人</span>
          <span class="badge blue">{{ current.is_teacher ? '老师' : '学生' }}</span>
        </div>

        <div class="tabs">
          <div class="tab" :class="{ active: tab === 'chat' }" @click="tab = 'chat'">聊天</div>
          <div class="tab" :class="{ active: tab === 'assign' }" @click="tab = 'assign'">
            作业（{{ current.assignments.length }}）
          </div>
        </div>

        <template v-if="tab === 'chat'">
          <div class="chat-box">
            <div v-for="m in current.messages" :key="m.id" class="msg" :class="{ mine: m.sender_id === auth.user.id }">
              <div class="msg-head">
                <span class="msg-name">{{ m.sender_name }}</span>
                <span class="faint small">{{ relativeTime(m.created_at) }}</span>
              </div>
              <div v-if="m.content" class="msg-body">{{ m.content }}</div>
              <div v-if="m.kind === 'assignment'" class="msg-assign">
                发布作业：{{ m.content }}
              </div>
              <div v-if="m.file_name" class="msg-file">
                <span>{{ m.kind === 'image' ? '🖼' : '📎' }} {{ m.file_name }}</span>
                <button class="btn sm" @click="downloadMessage(m)">下载</button>
              </div>
            </div>
            <div v-if="!current.messages.length" class="empty">还没有消息，打个招呼吧</div>
          </div>

          <div class="chat-input">
            <input v-model="draft" class="input" placeholder="输入消息…" @keyup.enter="send" />
            <button class="btn" :disabled="sending" @click="fileInput.click()">图片/文件</button>
            <input ref="fileInput" type="file" style="display: none" @change="pickFile" />
            <button class="btn primary" :disabled="sending || !draft.trim()" @click="send">发送</button>
          </div>
        </template>

        <template v-else>
          <div class="row between" style="margin-bottom: 12px">
            <span class="muted small">共 {{ current.assignments.length }} 份作业</span>
            <button v-if="current.is_teacher" class="btn primary sm" @click="showAssign = true">
              发布作业
            </button>
          </div>

          <div v-for="a in current.assignments" :key="a.id" class="assign-item">
            <div class="row between">
              <div>
                <strong>{{ a.title }}</strong>
                <div class="faint small">
                  {{ a.teacher_name }} · 满分 {{ a.full_score }}
                  <span v-if="a.deadline"> · 截止 {{ formatDate(a.deadline, true) }}</span>
                </div>
              </div>
              <div class="row" style="gap: 8px">
                <span class="badge gray">{{ a.submission_count }} 人已交</span>
                <button v-if="current.is_teacher" class="btn sm" @click="viewSubmissions(a)">查看提交</button>
                <template v-else>
                  <span v-if="a.my_submission?.score != null" class="badge green">{{ a.my_submission.score }} 分</span>
                  <button class="btn sm" @click="submitAssignment(a)">
                    {{ a.my_submission ? '重新提交' : '提交作业' }}
                  </button>
                </template>
              </div>
            </div>
            <div v-if="a.content" class="msg-body" style="margin-top: 6px">{{ a.content }}</div>
          </div>
          <div v-if="!current.assignments.length" class="empty">还没有作业</div>

          <div v-if="submissions.length" class="card" style="margin-top: 14px">
            <div class="card-title">提交列表</div>
            <div v-for="s in submissions" :key="s.id" class="row between" style="padding: 8px 0; border-bottom: 1px solid var(--border)">
              <div>
                <strong>{{ s.student_name }}</strong>
                <div class="faint small">{{ s.content || '（无文字内容）' }}</div>
              </div>
              <div class="row" style="gap: 8px">
                <span v-if="s.score != null" class="badge green">{{ s.score }} 分</span>
                <button class="btn sm" @click="grade(s)">打分</button>
              </div>
            </div>
          </div>
        </template>
      </section>
      <section v-else class="card group-main empty">请选择一个班级群</section>
    </div>

    <div v-if="showAssign" class="modal-mask" @click.self="showAssign = false">
      <div class="modal">
        <div class="modal-head"><h3>发布作业</h3></div>
        <div class="field">
          <label>标题</label>
          <input v-model="assignForm.title" class="input" placeholder="例如：第一次上机作业" />
        </div>
        <div class="field">
          <label>要求</label>
          <textarea v-model="assignForm.content" class="textarea" placeholder="作业说明…" />
        </div>
        <div class="form-row">
          <div class="field">
            <label>满分</label>
            <input v-model="assignForm.full_score" class="input" type="number" />
          </div>
          <div class="field">
            <label>截止时间</label>
            <input v-model="assignForm.deadline" class="input" type="datetime-local" />
          </div>
        </div>
        <div class="form-actions">
          <button class="btn" @click="showAssign = false">取消</button>
          <button class="btn primary" @click="createAssignment">发布</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.group-layout {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 16px;
  align-items: start;
}
.group-item {
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  margin-bottom: 6px;
}
.group-item:hover { background: #f3f9ff; }
.group-item.active { background: linear-gradient(135deg, rgba(255,200,87,.25), rgba(255,138,61,.18)); }
.chat-box { max-height: 46vh; overflow-y: auto; padding-right: 6px; }
.msg { padding: 8px 0; border-bottom: 1px dashed var(--border); }
.msg.mine .msg-name { color: var(--primary); }
.msg-head { display: flex; gap: 8px; align-items: baseline; }
.msg-name { font-size: 13px; font-weight: 600; }
.msg-body { margin-top: 4px; white-space: pre-wrap; word-break: break-word; }
.msg-assign {
  margin-top: 6px; padding: 8px 12px; border-radius: 10px;
  background: rgba(255, 200, 87, 0.18); color: #8a5a00; font-size: 13px;
}
.msg-file { margin-top: 6px; display: flex; gap: 10px; align-items: center; font-size: 13px; }
.chat-input { display: flex; gap: 8px; margin-top: 14px; }
.assign-item { padding: 12px; border: 1px solid var(--border); border-radius: 12px; margin-bottom: 10px; background: #fff; }

@media (max-width: 900px) {
  .group-layout { grid-template-columns: 1fr; }
  .chat-box { max-height: 52vh; }
  .chat-input { flex-wrap: wrap; }
  .chat-input .input { flex: 1 1 100%; }
  .chat-input .btn { flex: 1 1 auto; }
  .assign-item { padding: 10px; }
}</style>
