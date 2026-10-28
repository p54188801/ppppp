<script setup>
/**
 * 课表：按学期 + 周次查看，课程按科目配色。
 * 学生看自己班；教师可按班级筛选；管理员可编辑。
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
const semester = ref('')
const week = ref(1)
const classes = ref([])
const editing = ref(false)
const showModal = ref(false)
const saving = ref(false)
const form = ref({
  id: 0, class_name: '', weekday: 1, period: 1, course_name: '',
  teacher_name: '', room: '', note: '', semester: '', weeks: '1-20',
})

const isAdmin = computed(() => auth.isAdmin)
const isTeacher = computed(() => auth.isTeacher)
const periods = computed(() => data.value?.periods || {})
const weekdays = computed(() => data.value?.weekdays || {})
const semesters = computed(() => data.value?.semesters || [])
const maxWeek = 20

/** 课程配色：按课程名固定映射到一个颜色 */
const PALETTE = [
  '#7ed3c0', '#8fd39a', '#a5c8ff', '#ffd166',
  '#ff9f9f', '#c3a6ff', '#7fc8f8', '#f7b267',
]
function colorOf(name) {
  let hash = 0
  for (const ch of String(name || '')) hash = (hash * 31 + ch.charCodeAt(0)) % 997
  return PALETTE[hash % PALETTE.length]
}

/** 判断该课程在第几周上（weeks 支持 "1-16" / "1,3,5" / "1-8,10-16"） */
function inWeek(slot, w) {
  const spec = String(slot.weeks || '1-20')
  if (!spec.trim()) return true
  for (const part of spec.split(',')) {
    const [a, b] = part.split('-').map((x) => Number(x.trim()))
    if (Number.isFinite(b) && w >= a && w <= b) return true
    if (!Number.isFinite(b) && w === a) return true
  }
  return false
}

const slots = computed(() => (data.value?.slots || []).filter((s) => inWeek(s, week.value)))

function cell(weekday, period) {
  return slots.value.find((s) => Number(s.weekday) === weekday && Number(s.period) === period)
}

async function load() {
  loading.value = true
  try {
    const q = new URLSearchParams()
    if (className.value) q.set('class_name', className.value)
    if (semester.value) q.set('semester', semester.value)
    const qs = q.toString()
    data.value = await api.get(`/api/timetable${qs ? '?' + qs : ''}`)
    if (!semester.value && data.value.semester) semester.value = data.value.semester
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
      weekday, period, course_name: '', teacher_name: '', room: '', note: '',
      semester: semester.value || '2026-2027-1', weeks: '1-20',
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
      semester: form.value.semester || semester.value || '2026-2027-1',
      weeks: form.value.weeks || '1-20',
    }
    if (form.value.id) await api.put(`/api/timetable/${form.value.id}`, payload)
    else await api.post('/api/timetable', payload)
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

watch([className, semester], load)
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
          <template v-if="isAdmin">全部班级课表 · 点格子即可添加或修改</template>
          <template v-else-if="isTeacher">按班级查看课表</template>
          <template v-else>{{ data?.class_name || '我的班级' }} 的每周课表</template>
        </p>
      </div>
      <div class="row wrap" style="gap: 10px">
        <select v-if="isAdmin || isTeacher" v-model="className" class="select" style="width: 170px">
          <option value="">全部班级</option>
          <option v-for="c in classes" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-if="semesters.length" v-model="semester" class="select" style="width: 170px">
          <option v-for="s in semesters" :key="s" :value="s">{{ s }} 学期</option>
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

    <!-- 周次选择 -->
    <div class="card" style="margin-bottom: 14px; padding: 12px">
      <div class="row between" style="margin-bottom: 8px">
        <span class="small muted">选择周次</span>
        <span class="badge blue">第 {{ week }} 周</span>
      </div>
      <div class="week-grid">
        <button
          v-for="w in maxWeek"
          :key="w"
          class="week-chip"
          :class="{ active: w === week }"
          @click="week = w"
        >
          第{{ w }}周
        </button>
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
              <div class="period-no">{{ p }}</div>
              <div class="period-time">{{ time.split(' - ')[0] }}</div>
              <div class="period-time">{{ time.split(' - ')[1] }}</div>
            </th>
            <td
              v-for="(label, d) in weekdays"
              :key="d"
              :class="{ editable: editing, filled: cell(Number(d), Number(p)) }"
              @click="openCell(Number(d), Number(p))"
            >
              <template v-if="cell(Number(d), Number(p))">
                <div
                  class="slot"
                  :style="{ background: colorOf(cell(Number(d), Number(p)).course_name) }"
                >
                  <div class="slot-course">{{ cell(Number(d), Number(p)).course_name }}</div>
                  <div class="slot-meta">
                    <span v-if="cell(Number(d), Number(p)).teacher_name">{{ cell(Number(d), Number(p)).teacher_name }}</span>
                    <span v-if="cell(Number(d), Number(p)).room"> · {{ cell(Number(d), Number(p)).room }}</span>
                  </div>
                  <div v-if="(isAdmin || isTeacher) && cell(Number(d), Number(p)).class_name" class="slot-meta">
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
          <div class="field">
            <label>学期</label>
            <input v-model="form.semester" class="input" placeholder="2026-2027-1" />
          </div>
          <div class="field">
            <label>周次</label>
            <input v-model="form.weeks" class="input" placeholder="1-16 或 1,3,5" />
          </div>
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
.week-grid {
  display: grid;
  grid-template-columns: repeat(10, minmax(0, 1fr));
  gap: 6px;
}
.week-chip {
  border: 1px solid var(--border);
  background: #fbfdff;
  border-radius: 8px;
  padding: 6px 0;
  font-size: 12px;
  color: var(--text-dim);
  cursor: pointer;
}
.week-chip:hover { background: #eff7ff; }
.week-chip.active {
  background: linear-gradient(135deg, #ffb347, #ff8a3d);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
}
@media (max-width: 820px) {
  .week-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}

.timetable-wrap { padding: 10px; overflow-x: auto; }
.timetable { width: 100%; border-collapse: separate; border-spacing: 5px; min-width: 760px; }
.timetable th { font-size: 12.5px; font-weight: 600; color: var(--text-dim); padding: 6px; }
.timetable th.corner { width: 70px; }
.timetable th.period {
  width: 70px; background: #f5faff; border-radius: 10px; padding: 6px 4px; text-align: center;
}
.period-no { font-size: 14px; font-weight: 650; color: #33506f; }
.period-time { font-size: 10.5px; color: var(--text-faint); }
.timetable td {
  height: 92px; background: #fbfdff; border: 1px dashed var(--border);
  border-radius: 10px; vertical-align: top; padding: 4px; cursor: default;
}
.timetable td.editable { cursor: pointer; }
.timetable td.editable:hover { background: #eff7ff; }
.slot {
  height: 100%; border-radius: 9px; padding: 7px 8px; color: #14324f;
  display: flex; flex-direction: column; gap: 3px;
}
.slot-course { font-size: 13px; font-weight: 700; line-height: 1.25; }
.slot-meta { font-size: 11px; opacity: 0.85; }
.slot-empty { color: #c3d4e6; font-size: 20px; text-align: center; line-height: 78px; }
</style>
