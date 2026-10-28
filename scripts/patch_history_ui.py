"""作业详情：导出未交名单 + 催交记录面板。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\AssignmentDetailView.vue")
t = p.read_text(encoding="utf-8")

if "exportMissing" not in t:
    logic = '''
// ---------------------------------------------------------------------------
// 未交名单导出 + 催交记录
// ---------------------------------------------------------------------------
const history = ref(null)
const showHistory = ref(false)

async function exportMissing() {
  try {
    const token = localStorage.getItem('eduflow_token') || ''
    const res = await fetch(`/api/assignments/${id}/missing/export`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error('导出失败')
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = '未交名单.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (error) {
    ui.error(error.message)
  }
}

async function toggleHistory() {
  showHistory.value = !showHistory.value
  if (!showHistory.value) return
  try {
    history.value = await api.get(`/api/assignments/${id}/remind-history`)
  } catch (error) {
    ui.error(error.message)
  }
}
'''
    t = t.replace("async function remindMissing() {", logic + "\nasync function remindMissing() {", 1)

    t = t.replace(
        '<button class="btn sm" @click="copyLink">复制提交链接</button>',
        '''<button class="btn sm" @click="exportMissing">导出未交名单</button>
          <button class="btn sm" @click="toggleHistory">{{ showHistory ? '收起记录' : '催交记录' }}</button>
          <button class="btn sm" @click="copyLink">复制提交链接</button>''',
        1,
    )

    t = t.replace(
        '      <div class="hint" style="margin-top: 10px">',
        '''      <div v-if="showHistory && history" class="card" style="margin-top: 12px; box-shadow: none">
        <div class="card-title">
          <span>催交记录 · 累计 {{ history.total_reminded }} 次</span>
        </div>
        <div v-if="!history.batches.length" class="empty" style="padding: 10px">还没有催交过</div>
        <div v-for="(b, i) in history.batches" :key="i" style="padding: 8px 0; border-bottom: 1px solid var(--border)">
          <div class="row between">
            <span class="small">{{ b.created_at }} · {{ b.operator_name }}</span>
            <span class="badge gray">{{ b.students.length }} 人</span>
          </div>
          <div class="faint small" style="margin-top: 3px">{{ b.students.join('、') }}</div>
        </div>
        <div v-if="history.per_student.length" style="margin-top: 10px">
          <div class="stat-label" style="margin-bottom: 6px">按学生统计</div>
          <div class="row wrap" style="gap: 8px">
            <span v-for="s in history.per_student" :key="s.student_id" class="badge yellow">
              {{ s.name }} × {{ s.times }}
            </span>
          </div>
        </div>
      </div>

      <div class="hint" style="margin-top: 10px">''',
        1,
    )
    p.write_text(t, encoding="utf-8")
    print("AssignmentDetailView: 已加导出与催交记录")
