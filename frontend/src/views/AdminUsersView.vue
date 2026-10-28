<script setup>
/**
 * 用户管理页（仅管理员）
 * 职责：按角色与关键词分页检索账号，支持新建用户、编辑资料、启用/禁用、重置密码，
 *       以及用 CSV 文本批量导入账号并查看成功/失败明细。
 */
import { computed, onMounted, ref } from 'vue'
import { api, relativeTime } from '@/api/client'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const PAGE_SIZE = 15
const CSV_SAMPLE = [
  'username,real_name,role,number,department,class_name',
  's3001,张三,student,20230001,计算机学院,计科2301',
  's3002,李四,student,20230002,计算机学院,计科2302',
  't1002,王老师,teacher,T2010002,计算机学院,',
].join('\n')

const roleOptions = [
  { value: '', label: '全部角色' },
  { value: 'student', label: '学生' },
  { value: 'teacher', label: '教师' },
  { value: 'admin', label: '管理员' },
]

const loading = ref(true)
const users = ref([])
const total = ref(0)
const page = ref(1)
const role = ref('')
const keyword = ref('')

const showCreate = ref(false)
const createForm = ref(emptyCreateForm())
const creating = ref(false)

const showEdit = ref(false)
const editId = ref(0)
const editForm = ref({ real_name: '', number: '', department: '', class_name: '', email: '' })
const savingEdit = ref(false)

const credential = ref(null)
const actingId = ref(0)

const showImport = ref(false)
const importForm = ref({ csv: '', default_role: 'student' })
const importing = ref(false)
const importResult = ref(null)

const pages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function emptyCreateForm() {
  return {
    username: '',
    real_name: '',
    role: 'student',
    number: '',
    department: '',
    class_name: '',
    email: '',
  }
}

function roleLabel(value) {
  if (value === 'student') return '学生'
  if (value === 'teacher') return '教师'
  if (value === 'admin') return '管理员'
  return value || '—'
}

function roleBadge(value) {
  if (value === 'admin') return 'purple'
  if (value === 'teacher') return 'blue'
  return 'gray'
}


async function kickUser(user) {
  const ok = await ui.confirm({
    title: '强制下线',
    message: `确定把 ${user.real_name}（${user.username}）踢下线吗？对方需要重新登录。`,
    confirmText: '踢下线',
  })
  if (!ok) return
  actingId.value = user.id
  try {
    const data = await api.post(`/api/users/${user.id}/kick`)
    ui.success(`已下线，吊销 ${data.revoked} 个会话`)
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingId.value = 0
  }
}

async function cancelAccount(user) {
  const ok = await ui.confirm({
    title: '注销账号',
    message: `确定注销 ${user.real_name}（${user.username}）吗？注销后该账号无法登录，数据仍保留。`,
    confirmText: '确认注销',
    danger: true,
  })
  if (!ok) return
  actingId.value = user.id
  try {
    await api.post(`/api/users/${user.id}/cancel`)
    ui.success('账号已注销')
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingId.value = 0
  }
}

async function load() {
  loading.value = true
  try {
    const data = await api.get('/api/users', {
      role: role.value,
      keyword: keyword.value.trim(),
      page: page.value,
      page_size: PAGE_SIZE,
    })
    users.value = data.items || []
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

function openCreate() {
  createForm.value = emptyCreateForm()
  showCreate.value = true
}

async function submitCreate() {
  const form = createForm.value
  const username = form.username.trim()
  const realName = form.real_name.trim()
  if (username.length < 3) {
    ui.error('用户名至少需要 3 个字符')
    return
  }
  if (!realName) {
    ui.error('姓名不能为空')
    return
  }
  creating.value = true
  try {
    const data = await api.post('/api/users', {
      username,
      real_name: realName,
      role: form.role,
      number: form.number.trim(),
      department: form.department.trim(),
      class_name: form.class_name.trim(),
      email: form.email.trim(),
    })
    showCreate.value = false
    credential.value = {
      title: '用户创建成功',
      username: data.username,
      password: data.initial_password,
      hint: '请把初始密码转告该用户，首次登录后需自行修改密码。',
    }
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    creating.value = false
  }
}

function openEdit(user) {
  editId.value = user.id
  editForm.value = {
    real_name: user.real_name || '',
    number: user.number || '',
    department: user.department || '',
    class_name: user.class_name || '',
    email: user.email || '',
  }
  showEdit.value = true
}

async function submitEdit() {
  if (!editForm.value.real_name.trim()) {
    ui.error('姓名不能为空')
    return
  }
  savingEdit.value = true
  try {
    await api.put(`/api/users/${editId.value}`, {
      real_name: editForm.value.real_name.trim(),
      number: editForm.value.number.trim(),
      department: editForm.value.department.trim(),
      class_name: editForm.value.class_name.trim(),
      email: editForm.value.email.trim(),
    })
    ui.success('用户资料已更新')
    showEdit.value = false
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    savingEdit.value = false
  }
}

async function toggleStatus(user) {
  const next = user.status === 'active' ? 'disabled' : 'active'
  const ok = await ui.confirm({
    title: next === 'disabled' ? '禁用账号' : '启用账号',
    message:
      next === 'disabled'
        ? `确定禁用 ${user.real_name}（${user.username}）吗？禁用后该账号会被强制下线。`
        : `确定启用 ${user.real_name}（${user.username}）吗？`,
    confirmText: next === 'disabled' ? '禁用' : '启用',
    danger: next === 'disabled',
  })
  if (!ok) return
  actingId.value = user.id
  try {
    await api.post(`/api/users/${user.id}/status`, { status: next })
    ui.success(next === 'disabled' ? '账号已禁用' : '账号已启用')
    await load()
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingId.value = 0
  }
}

async function resetPassword(user) {
  const ok = await ui.confirm({
    title: '重置密码',
    message: `确定为 ${user.real_name}（${user.username}）生成新的初始密码吗？原密码将立即失效。`,
    confirmText: '重置密码',
    danger: true,
  })
  if (!ok) return
  actingId.value = user.id
  try {
    const data = await api.post(`/api/users/${user.id}/reset-password`, {})
    credential.value = {
      title: '密码已重置',
      username: data.username,
      password: data.initial_password,
      hint: '请把新的初始密码转告该用户。',
    }
  } catch (error) {
    ui.error(error.message)
  } finally {
    actingId.value = 0
  }
}

function openImport() {
  importForm.value = { csv: '', default_role: 'student' }
  importResult.value = null
  showImport.value = true
}

function fillSample() {
  importForm.value.csv = CSV_SAMPLE
}

async function submitImport() {
  const csv = importForm.value.csv.trim()
  if (!csv) {
    ui.error('请粘贴 CSV 内容')
    return
  }
  importing.value = true
  try {
    const data = await api.post('/api/users/import', {
      csv,
      default_role: importForm.value.default_role,
    })
    importResult.value = data
    if (data.created > 0) await load()
    if (data.failed > 0) ui.error(`导入完成：成功 ${data.created} 条，失败 ${data.failed} 条`)
    else ui.success(`导入完成：成功 ${data.created} 条`)
  } catch (error) {
    ui.error(error.message)
  } finally {
    importing.value = false
  }
}

function copyCredential() {
  if (!credential.value) return
  const text = `账号：${credential.value.username}\n初始密码：${credential.value.password}`
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(
      () => ui.success('账号与密码已复制'),
      () => ui.error('复制失败，请手动记录'),
    )
  } else {
    ui.error('当前环境不支持自动复制，请手动记录')
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>用户管理</h1>
        <p>共 {{ total }} 个账号，可新建、编辑、启停与重置密码</p>
      </div>
      <div class="row wrap">
        <select v-model="role" class="select" style="width: 130px" @change="search">
          <option v-for="item in roleOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <input
          v-model="keyword"
          class="input"
          style="width: 200px"
          placeholder="用户名 / 姓名 / 学号"
          @keyup.enter="search"
        />
        <button class="btn" :disabled="loading" @click="search">搜索</button>
        <button class="btn" @click="openCreate">新建用户</button>
        <button class="btn primary" @click="openImport">批量导入</button>
      </div>
    </div>

    <div v-if="loading" class="loading">正在加载用户…</div>

    <div v-else-if="!users.length" class="empty">没有符合条件的用户</div>

    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>用户名</th>
            <th>姓名</th>
            <th>角色</th>
            <th>学号 / 工号</th>
            <th>院系</th>
            <th>状态</th>
            <th>最后登录</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td class="mono small">{{ user.username }}</td>
            <td>{{ user.real_name }}</td>
            <td><span class="badge" :class="roleBadge(user.role)">{{ roleLabel(user.role) }}</span></td>
            <td class="mono small">{{ user.number || '—' }}</td>
            <td class="small muted">{{ user.department || '—' }}</td>
            <td>
              <span class="badge" :class="user.status === 'active' ? 'green' : 'red'">
                {{ user.status === 'active' ? '正常' : '已禁用' }}
              </span>
            </td>
            <td class="small faint">
              {{ user.last_login_at ? relativeTime(user.last_login_at) : '从未登录' }}
            </td>
            <td>
              <div class="row" style="gap: 6px">
                <button class="btn sm ghost" @click="openEdit(user)">编辑</button>
                <button class="btn sm" :disabled="actingId === user.id" @click="kickUser(user)">下线</button>
            <button class="btn sm danger" :disabled="actingId === user.id" @click="cancelAccount(user)">注销</button>
            <button
                  class="btn sm"
                  :class="user.status === 'active' ? 'danger' : ''"
                  :disabled="actingId === user.id"
                  @click="toggleStatus(user)"
                >
                  {{ user.status === 'active' ? '禁用' : '启用' }}
                </button>
                <button class="btn sm ghost" :disabled="actingId === user.id" @click="resetPassword(user)">
                  重置密码
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!loading && pages > 1" class="row between" style="margin-top: 16px">
      <span class="small faint">第 {{ page }} / {{ pages }} 页 · 共 {{ total }} 条</span>
      <div class="row">
        <button class="btn sm" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <button class="btn sm" :disabled="page >= pages" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>

    <!-- 新建用户 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <form class="modal" @submit.prevent="submitCreate">
        <div class="modal-head">
          <h3>新建用户</h3>
          <button type="button" class="btn ghost sm" @click="showCreate = false">✕</button>
        </div>
        <div class="form-row">
          <div class="field">
            <label>用户名</label>
            <input v-model="createForm.username" class="input" placeholder="登录账号，至少 3 位" maxlength="32" />
          </div>
          <div class="field">
            <label>姓名</label>
            <input v-model="createForm.real_name" class="input" maxlength="32" />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label>角色</label>
            <select v-model="createForm.role" class="select">
              <option value="student">学生</option>
              <option value="teacher">教师</option>
              <option value="admin">管理员</option>
            </select>
          </div>
          <div class="field">
            <label>学号 / 工号</label>
            <input v-model="createForm.number" class="input" maxlength="32" />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label>院系</label>
            <input v-model="createForm.department" class="input" maxlength="64" />
          </div>
          <div class="field">
            <label>班级</label>
            <input v-model="createForm.class_name" class="input" maxlength="64" />
          </div>
        </div>
        <div class="field">
          <label>邮箱</label>
          <input v-model="createForm.email" class="input" type="email" maxlength="128" />
        </div>
        <div class="hint">初始密码由系统随机生成，创建成功后会展示一次。</div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showCreate = false">取消</button>
          <button type="submit" class="btn primary" :disabled="creating">
            {{ creating ? '创建中…' : '创建用户' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 编辑用户 -->
    <div v-if="showEdit" class="modal-mask" @click.self="showEdit = false">
      <form class="modal" @submit.prevent="submitEdit">
        <div class="modal-head">
          <h3>编辑用户资料</h3>
          <button type="button" class="btn ghost sm" @click="showEdit = false">✕</button>
        </div>
        <div class="form-row">
          <div class="field">
            <label>姓名</label>
            <input v-model="editForm.real_name" class="input" maxlength="32" />
          </div>
          <div class="field">
            <label>学号 / 工号</label>
            <input v-model="editForm.number" class="input" maxlength="32" />
          </div>
        </div>
        <div class="form-row">
          <div class="field">
            <label>院系</label>
            <input v-model="editForm.department" class="input" maxlength="64" />
          </div>
          <div class="field">
            <label>班级</label>
            <input v-model="editForm.class_name" class="input" maxlength="64" />
          </div>
        </div>
        <div class="field">
          <label>邮箱</label>
          <input v-model="editForm.email" class="input" type="email" maxlength="128" />
        </div>
        <div class="form-actions">
          <button type="button" class="btn" @click="showEdit = false">取消</button>
          <button type="submit" class="btn primary" :disabled="savingEdit">
            {{ savingEdit ? '保存中…' : '保存' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 初始密码展示 -->
    <div v-if="credential" class="modal-mask" @click.self="credential = null">
      <div class="modal" style="width: min(440px, 92vw)">
        <div class="modal-head">
          <h3>{{ credential.title }}</h3>
          <button type="button" class="btn ghost sm" @click="credential = null">✕</button>
        </div>
        <div class="field">
          <label>登录账号</label>
          <div class="input mono">{{ credential.username }}</div>
        </div>
        <div class="field">
          <label>初始密码</label>
          <div class="input mono" style="color: var(--warning); font-weight: 600">
            {{ credential.password }}
          </div>
        </div>
        <div class="hint">{{ credential.hint }}</div>
        <div class="form-actions">
          <button type="button" class="btn" @click="copyCredential">复制账号密码</button>
          <button type="button" class="btn primary" @click="credential = null">我已记录</button>
        </div>
      </div>
    </div>

    <!-- 批量导入 -->
    <div v-if="showImport" class="modal-mask" @click.self="showImport = false">
      <form class="modal wide" @submit.prevent="submitImport">
        <div class="modal-head">
          <h3>批量导入用户</h3>
          <button type="button" class="btn ghost sm" @click="showImport = false">✕</button>
        </div>
        <div class="field">
          <label>CSV 内容</label>
          <textarea
            v-model="importForm.csv"
            class="textarea mono"
            style="min-height: 160px"
            :placeholder="CSV_SAMPLE"
            spellcheck="false"
          />
          <div class="hint">
            表头需包含 username,real_name,role,number,department,class_name；role 为空时使用下方默认角色。
          </div>
        </div>
        <div class="row between">
          <div class="field" style="width: 200px; margin-bottom: 0">
            <label>默认角色</label>
            <select v-model="importForm.default_role" class="select">
              <option value="student">学生</option>
              <option value="teacher">教师</option>
            </select>
          </div>
          <button type="button" class="btn ghost sm" @click="fillSample">填入示例</button>
        </div>

        <div v-if="importResult" class="card" style="margin-top: 16px; background: var(--surface-2)">
          <div class="row wrap" style="gap: 16px">
            <span class="badge green">成功 {{ importResult.created }} 条</span>
            <span class="badge" :class="importResult.failed ? 'red' : 'gray'">
              失败 {{ importResult.failed }} 条
            </span>
          </div>
          <div v-if="(importResult.details || []).length" style="margin-top: 12px">
            <div class="small faint" style="margin-bottom: 6px">新建账号与初始密码：</div>
            <div class="table-wrap" style="max-height: 220px; overflow-y: auto">
              <table>
                <thead>
                  <tr>
                    <th>行号</th>
                    <th>用户名</th>
                    <th>初始密码</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in importResult.details" :key="item.line">
                    <td class="mono small">{{ item.line }}</td>
                    <td class="mono small">{{ item.username }}</td>
                    <td class="mono small">{{ item.initial_password }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-if="(importResult.errors || []).length" style="margin-top: 12px">
            <div class="small faint" style="margin-bottom: 6px">失败明细：</div>
            <div
              v-for="(item, index) in importResult.errors"
              :key="index"
              class="row between"
              style="padding: 4px 0"
            >
              <span class="small">第 {{ item.line }} 行 · {{ item.username || '（空）' }}</span>
              <span class="badge red">{{ item.error }}</span>
            </div>
          </div>
        </div>

        <div class="form-actions">
          <button type="button" class="btn" @click="showImport = false">关闭</button>
          <button type="submit" class="btn primary" :disabled="importing">
            {{ importing ? '导入中…' : '开始导入' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
