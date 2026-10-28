<script setup>
/**
 * 课表：学生看自己班，老师可切换班级，管理员可增删改。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()

const data = ref(null)
const loading = ref(true)
const className = ref('')
const classes = ref([])
const editing = ref(false)
const showModal = ref(false)
const saving = ref(false)
const form = ref({ id: 0, class_name: '', weekday: 1, period: 1, course_name: '', teacher_name: '', room: '', note: '' })

const isAdmin = computed(() => auth.isAdmin)
const isTeacher = computed(() => auth.isTeacher)

const periods = computed(() => data.value?.periods || {})
const weekdays = computed(() => data.value?.weekdays || {})
const slots = computed(() => data.value?.slots || [])

function cell(weekday, period) {
  return slots.value.find((s) => Number(s.weekday) === weekday && Number(s.period) === period)
}

async function load() {
  loading.value = true
  try {
    const q = className.value ? `?class_name=${encodeURIComponent(className.value)}` : ''
    data.value = await api.get(`/api/timetable${q}`)
  } catch (error) {
    ui.error(error.message)
  } finally {
    loading.value = false
  }
}

async function loadClasses() {
  if (!auth.isAdmin && !auth.isTeacher) return
  try {
    classes.value = await api.get('/api/timetable/classes')
  } catch {
    classes.value = []
  }
}

function openCell(weekday, period) {
  if (!editing.value) return
  const exist = cell(weekday, period)
  if (exist) {
    form.value = { ...exist }
  } else {
    form.value = {
      id: 0,
      class_name: className.value || data.value?.class_name || '',
      weekday,
      period,
      course_name: '',
      teacher_name: '',
      room: '',
      note: '',
    }
  }
  showModal.value = true
}

async function save() {
  if (!form.value.course_name.trim()) return ui.error('请填写课程名称')
  if (!form.value.class_name.trim()) return ui.error('请填写班级')
  saving.value = true
  try {
    const payload = {
      class_name: form.value.class_name.trim(),
      weekday: Number(form.value.weekday),
      period: Number(form.value.period),
      course_name: form.value.course_name.trim(),
      teacher_name: form.value.teacher_name || '',
      room: form.value.room || '',
      note: form.value.note || '',
    }
    if (form.value.id) {
      await api.put(`/api/timetable/${form.value.id}`, payload)
    } else {
      await api.post('/api/timetable', payload)
    }
    showModal.value = false
    ui.success('已保存')
    await load()
    await loadClasses()
  } catch (error) {
    ui.error(error.message)
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!form.value.id) return
  const okConfirm = await ui.confirm({
    title: '删除课程',
    message: `删除「${form.value.course_name}」这节课吗？`,
    confirmText: '删除',
    danger: true,
  })
  if (!okConfirm) return
  try {
    await api.delete(`/api/timetable/${form.value.id}`)
    showModal.value = false
    ui.success('已删除')
    await load()
  } catch (error) {
    ui.error(error.message)
  }
}

watch(className, load)
onMounted(async () => {
  await load()
  await loadClasses()
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>课表</h1>
        <p>
          <template v-if="isAdmin">全部班级课表，点格子即可添加或修改</template>
          <template v-else-if="isTeacher">按班级查看课表</template>
          <template v-else>{{ data?.class_name || '我的班级' }} 的每周课表</template>
        </p>
      </div>
      <div class="row wrap" style="gap: 10px">
        <select v-if="isAdmin || isTeacher" v-model="className" class="select" style="width: 180px">
          <option value="">全部班级</option>
          <option v-for="c in classes" :key="c" :value="c">{{ c }}</option>
        </select>
        <button
          v-if="isAdmin"
          class="btn"
          :class="{ primary: editing }"
          @click="editing = !editing"
        >
          {{ editing ? '退出编辑' : '编辑课表' }}
        </button>
        <button class="btn" :disabled="loading" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="data.scope === 'none'" class="card empty" style="text-align: center; padding: 26px">
      你还没有填写班级，去个人中心补上就能看到课表
    </div>

    <div v-else class="card timetable-wrap">
      <table class="timetable">
        <thead>
          <tr>
            <th class="corner">节次</th>
            <th v-for="(label, d) in weekdays" :key="d">{{ label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(time, p) in periods" :key="p">
            <th class="period">
              <div class="period-no">第 {{ p }} 节</div>
              <div class="period-time">{{ time }}</div>
            </th>
            <td
              v-for="(label, d) in weekdays"
              :key="d"
              :class="{ editable: editing, filled: cell(Number(d), Number(p)) }"
              @click="openCell(Number(d), Number(p))"
            >
              <template v-if="cell(Number(d), Number(p))">
                <div class="slot">
                  <div class="slot-course">{{ cell(Number(d), Number(p)).course_name }}</div>
                  <div class="slot-meta">
                    <span v-if="cell(Number(d), Number(p)).teacher_name">{{ cell(Number(d), Number(p)).teacher_name }}</span>
                    <span v-if="cell(Number(d), Number(p)).room">· {{ cell(Number(d), Number(p)).room }}</span>
                  </div>
                  <div v-if="cell(Number(d), Number(p)).class_name && (isAdmin || isTeacher)" class="slot-meta faint">
                    {{ cell(Number(d), Number(p)).class_name }}
                  </div>
                </div>
              </template>
              <div v-else-if="editing" class="slot-empty">＋</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showModal" class="modal-mask" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-head"><h3>{{ form.id ? '修改课程' : '添加课程' }}</h3></div>
        <div class="grid cols-2" style="gap: 12px">
          <div class="field">
            <label>班级</label>
            <input v-model="form.class_name" class="input" placeholder="例如：大数据G231" />
          </div>
          <div class="field">
            <label>课程</label>
            <input v-model="form.course_name" class="input" placeholder="例如：数据结构" />
          </div>
          <div class="field">
            <label>星期</label>
            <select v-model.number="form.weekday" class="select">
              <option v-for="(label, d) in weekdays" :key="d" :value="Number(d)">{{ label }}</option>
            </select>
          </div>
          <div class="field">
            <label>节次</label>
            <select v-model.number="form.period" class="select">
              <option v-for="(time, p) in periods" :key="p" :value="Number(p)">第 {{ p }} 节（{{ time }}）</option>
            </select>
          </div>
          <div class="field">
            <label>老师</label>
            <input v-model="form.teacher_name" class="input" placeholder="授课老师" />
          </div>
          <div class="field">
            <label>教室</label>
            <input v-model="form.room" class="input" placeholder="上课地点" />
          </div>
        </div>
        <div class="field">
          <label>备注</label>
          <input v-model="form.note" class="input" placeholder="可选" />
        </div>
        <div class="form-actions">
          <button v-if="form.id" class="btn danger" @click="remove">删除</button>
          <div style="flex: 1"></div>
          <button class="btn" @click="showModal = false">取消</button>
          <button class="btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timetable-wrap { padding: 10px; overflow-x: auto; }
.timetable { width: 100%; border-collapse: separate; border-spacing: 6px; min-width: 720px; }
.timetable th { font-size: 12.5px; font-weight: 600; color: var(--text-dim); padding: 6px; }
.timetable th.corner { width: 96px; }
.timetable th.period {
  width: 96px; background: #f5faff; border-radius: 10px; padding: 8px 6px; text-align: center;
}
.period-no { font-size: 12.5px; color: #33506f; }
.period-time { font-size: 11px; color: var(--text-faint); margin-top: 2px; }
.timetable td {
  height: 74px; background: #fbfdff; border: 1px dashed var(--border);
  border-radius: 10px; vertical-align: top; padding: 8px; cursor: default;
  transition: background 0.15s;
}
.timetable td.filled {
  background: linear-gradient(150deg, rgba(255, 200, 87, 0.18), rgba(62, 168, 255, 0.14));
  border: 1px solid rgba(255, 138, 61, 0.35);
}
.timetable td.editable { cursor: pointer; }
.timetable td.editable:hover { background: rgba(62, 168, 255, 0.12); }
.slot-course { font-size: 13.5px; font-weight: 650; color: #1d3557; line-height: 1.3; }
.slot-meta { font-size: 11.5px; color: var(--text-dim); margin-top: 3px; }
.slot-empty { color: #c3d4e6; font-size: 20px; text-align: center; line-height: 58px; }
</style>
