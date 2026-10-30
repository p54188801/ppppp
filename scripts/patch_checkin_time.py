"""签到：老师自定义结束时间（时长 / 指定时间 / 手动结束）。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\GroupView.vue")
t = p.read_text(encoding="utf-8")

if "endMode" not in t:
    # 1) 表单字段
    t = t.replace(
        "const checkinForm = ref({ mode: 'number', answer: '', pattern: '🍎', minutes: 5 })",
        "const checkinForm = ref({ mode: 'number', answer: '', pattern: '🍎', minutes: 5, endMode: 'minutes', endsAt: '' })",
        1,
    )
    # 2) 提交逻辑
    old_start = """async function startCheckin() {
  const form = checkinForm.value
  const answer = form.mode === 'pattern' ? form.pattern : form.answer.trim()
  if (!answer) return ui.error(form.mode === 'pattern' ? '请选择图案' : '请设置签到数字')
  checkinBusy.value = true
  try {
    await api.post(`/api/groups/${groupId.value}/checkins`, {
      mode: form.mode,
      answer,
      minutes: Number(form.minutes) || 5,
    })"""
    new_start = """async function startCheckin() {
  const form = checkinForm.value
  const answer = form.mode === 'pattern' ? form.pattern : form.answer.trim()
  if (!answer) return ui.error(form.mode === 'pattern' ? '请选择图案' : '请设置签到数字')
  if (form.endMode === 'time' && !form.endsAt) return ui.error('请选择结束时间')

  const payload = { mode: form.mode, answer }
  if (form.endMode === 'manual') {
    payload.manual = true
  } else if (form.endMode === 'time') {
    payload.ends_at = new Date(form.endsAt).toISOString()
  } else {
    payload.minutes = Number(form.minutes) || 5
  }

  checkinBusy.value = true
  try {
    await api.post(`/api/groups/${groupId.value}/checkins`, payload)"""
    if old_start in t:
        t = t.replace(old_start, new_start, 1)

    t = t.replace(
        "checkinForm.value = { mode: 'number', answer: '', pattern: '🍎', minutes: 5 }",
        "checkinForm.value = { mode: 'number', answer: '', pattern: '🍎', minutes: 5, endMode: 'minutes', endsAt: '' }",
    )

    # 3) 模板：替换时长输入
    old_block = """        <div class="field">
          <label>持续时长（分钟）</label>
          <input v-model="checkinForm.minutes" class="input" type="number" min="1" max="60" style="max-width: 120px" />
        </div>"""
    new_block = """        <div class="field">
          <label>结束方式</label>
          <div class="row wrap" style="gap: 12px">
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="checkinForm.endMode" type="radio" value="minutes" /> 按时长
            </label>
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="checkinForm.endMode" type="radio" value="time" /> 指定结束时间
            </label>
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="checkinForm.endMode" type="radio" value="manual" /> 手动结束
            </label>
          </div>
        </div>

        <div v-if="checkinForm.endMode === 'minutes'" class="field">
          <label>持续时长</label>
          <div class="row wrap" style="gap: 8px; margin-bottom: 8px">
            <button
              v-for="m in [3, 5, 10, 15, 30, 60]"
              :key="m"
              class="btn sm"
              :class="{ primary: Number(checkinForm.minutes) === m }"
              @click="checkinForm.minutes = m"
            >
              {{ m }} 分钟
            </button>
          </div>
          <input v-model="checkinForm.minutes" class="input" type="number" min="1" max="1440" style="max-width: 140px" />
          <div class="hint">支持 1–1440 分钟（最长 24 小时）</div>
        </div>

        <div v-else-if="checkinForm.endMode === 'time'" class="field">
          <label>结束时间</label>
          <input v-model="checkinForm.endsAt" class="input" type="datetime-local" />
          <div class="hint">到点自动结束，最长 24 小时</div>
        </div>

        <div v-else class="field">
          <div class="hint">不自动结束，由老师点「结束签到」收尾。</div>
        </div>"""
    if old_block in t:
        t = t.replace(old_block, new_block, 1)
    else:
        print("未匹配时长输入块")

    p.write_text(t, encoding="utf-8")
    print("GroupView: 已支持自定义签到时间")
else:
    print("GroupView: 已存在")
