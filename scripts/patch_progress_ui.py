"""作业详情页：教师可见提交进度（已交/未交名单）与提交链接。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\AssignmentDetailView.vue")
t = p.read_text(encoding="utf-8")

if "progress" not in t:
    # ---------- script ----------
    logic = '''
// ---------------------------------------------------------------------------
// 提交进度（教师）
// ---------------------------------------------------------------------------
const progress = ref(null)
const progressTab = ref('missing')

async function loadProgress() {
  if (!(auth.isTeacher || auth.isAdmin)) return
  try {
    progress.value = await api.get(`/api/assignments/${id}/progress`)
  } catch {
    progress.value = null
  }
}

function submitLink() {
  return `${window.location.origin}${window.location.pathname}#/assignments/${id}`
}

async function copyLink() {
  const link = submitLink()
  try {
    await navigator.clipboard.writeText(link)
    ui.success('提交链接已复制，发给学生即可')
  } catch {
    window.prompt('复制下面的链接发给学生：', link)
  }
}
'''
    t = t.replace("async function load(", logic + "\nasync function load(", 1)
    t = t.replace(
        "onMounted(load)",
        "onMounted(async () => {\n  await load()\n  await loadProgress()\n})",
        1,
    )

    block = '''
    <!-- 教师：提交进度 -->
    <div v-if="progress" class="card" style="margin-bottom: 16px">
      <div class="card-title">
        <span>提交情况</span>
        <div class="row" style="gap: 8px">
          <button class="btn sm" @click="copyLink">复制提交链接</button>
          <button class="btn sm" :disabled="!progress" @click="loadProgress">刷新</button>
        </div>
      </div>

      <div class="grid cols-4" style="margin-bottom: 12px">
        <div class="stat">
          <div class="stat-label">应交</div>
          <div class="stat-value">{{ progress.total }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">已交</div>
          <div class="stat-value" style="color: var(--success)">{{ progress.submitted_count }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">未交</div>
          <div class="stat-value" style="color: var(--danger)">{{ progress.missing_count }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">已批改</div>
          <div class="stat-value">{{ progress.graded_count }}</div>
        </div>
      </div>

      <div class="tabs" style="margin-bottom: 10px">
        <div class="tab" :class="{ active: progressTab === 'missing' }" @click="progressTab = 'missing'">
          未交（{{ progress.missing_count }}）
        </div>
        <div class="tab" :class="{ active: progressTab === 'submitted' }" @click="progressTab = 'submitted'">
          已交（{{ progress.submitted_count }}）
        </div>
      </div>

      <div v-if="progressTab === 'missing'">
        <div v-if="!progress.missing.length" class="empty" style="padding: 14px">
          全部交齐了 🎉
        </div>
        <div v-for="m in progress.missing" :key="m.student_id" class="row between"
             style="padding: 8px 0; border-bottom: 1px solid var(--border)">
          <span>{{ m.real_name }} <span class="faint small">{{ m.number }}</span></span>
          <span class="badge red">未交</span>
        </div>
      </div>

      <div v-else>
        <div v-for="s in progress.submitted" :key="s.student_id" class="row between"
             style="padding: 8px 0; border-bottom: 1px solid var(--border)">
          <span>{{ s.real_name }} <span class="faint small">{{ s.number }}</span></span>
          <span class="row" style="gap: 8px">
            <span v-if="s.late" class="badge yellow">迟交</span>
            <span v-if="s.score != null" class="badge green">{{ s.score }} 分</span>
            <span v-else class="badge gray">待批改</span>
          </span>
        </div>
      </div>

      <div class="hint" style="margin-top: 10px">
        学生点开链接 <span class="mono small">{{ submitLink() }}</span> 登录后直接就能提交。
      </div>
    </div>
'''
    idx = t.find('<template>')
    marker = "</div>\n"
    pos = t.find(marker, t.find('<div class="page-head">'))
    if pos < 0:
        pos = t.find("<div", idx) + 1
    # 插入到 page-head 区块结束之后
    head_end = t.find("</div>", t.find('<div class="page-head">', idx))
    # 找到 page-head 的配对大括号结束位置：简单地在其后第一个 "\n\n" 之后
    nl = t.find("\n\n", head_end)
    t = t[: nl + 2] + block + t[nl + 2:]

    p.write_text(t, encoding="utf-8")
    print("AssignmentDetailView: 已加提交进度面板")
else:
    print("AssignmentDetailView: 已存在进度面板")
