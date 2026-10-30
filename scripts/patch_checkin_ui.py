"""群签到前端：发起、签到、查看未到。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\GroupView.vue")
t = p.read_text(encoding="utf-8")

if "activeCheckin" not in t:
    # ---------- 状态 ----------
    t = t.replace(
        "const submissions = ref([])",
        """const submissions = ref([])

/* 签到 */
const activeCheckin = ref(null)
const showStartCheckin = ref(false)
const checkinForm = ref({ mode: 'number', answer: '', pattern: '🍎', minutes: 5 })
const checkinStatus = ref(null)
const checkinAnswer = ref('')
const checkinBusy = ref(false)
const patterns = ['🍎', '🍊', '🍋', '🍇', '🍓', '🍉', '🥝', '🍑']""",
        1,
    )

    # ---------- 加载当前签到 ----------
    t = t.replace(
        "    current.value = await api.get(`/api/groups/${groupId.value}?limit=${limit.value}`)",
        """    current.value = await api.get(`/api/groups/${groupId.value}?limit=${limit.value}`)
    activeCheckin.value = await api
      .get(`/api/groups/${groupId.value}/checkins/active`)
      .catch(() => null)""",
        1,
    )

    # ---------- 方法 ----------
    logic = '''
/* ---------------------------- 签到 ---------------------------- */
async function startCheckin() {
  const form = checkinForm.value
  const answer = form.mode === 'pattern' ? form.pattern : form.answer.trim()
  if (!answer) return ui.error(form.mode === 'pattern' ? '请选择图案' : '请设置签到数字')
  checkinBusy.value = true
  try {
    await api.post(`/api/groups/${groupId.value}/checkins`, {
      mode: form.mode,
      answer,
      minutes: Number(form.minutes) || 5,
    })
    showStartCheckin.value = false
    checkinForm.value = { mode: 'number', answer: '', pattern: '🍎', minutes: 5 }
    ui.success('签到已开始')
    await loadGroup()
    scrollToBottom()
  } catch (error) {
    ui.error(error.message)
  } finally {
    checkinBusy.value = false
  }
}

async function doCheckin() {
  const answer = checkinForm.value.mode === 'pattern' ? checkinAnswer.value : checkinAnswer.value.trim()
  if (!answer && activeCheckin.value?.mode === 'number') return ui.error('请输入签到数字')
  checkinBusy.value = true
  try {
    await api.post(`/api/checkins/${activeCheckin.value.id}/respond`, { answer })
    ui.success('签到成功')
    checkinAnswer.value = ''
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  } finally {
    checkinBusy.value = false
  }
}

async function pickPattern(p) {
  checkinAnswer.value = p
  await doCheckin()
}

async function viewCheckinStatus(checkin) {
  try {
    checkinStatus.value = await api.get(`/api/checkins/${checkin.id}/status`)
  } catch (error) {
    ui.error(error.message)
  }
}

async function closeCheckin(checkin) {
  try {
    await api.post(`/api/checkins/${checkin.id}/close`)
    ui.success('签到已结束')
    checkinStatus.value = null
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  }
}

function remainText(c) {
  if (!c) return ''
  const left = Math.max(0, Math.round((new Date(c.ends_at) - Date.now()) / 1000))
  if (left <= 0) return '已结束'
  return `剩余 ${Math.floor(left / 60)} 分 ${left % 60} 秒`
}
'''
    t = t.replace("/* ---------------------------- 发布作业 ---------------------------- */", logic + "\n/* ---------------------------- 发布作业 ---------------------------- */", 1)

    # ---------- 聊天顶部签到条 ----------
    banner = '''
          <!-- 进行中的签到 -->
          <div v-if="activeCheckin" class="checkin-banner">
            <div class="checkin-head">
              <span class="checkin-title">📢 正在签到</span>
              <span class="badge yellow">{{ remainText(activeCheckin) }}</span>
              <span v-if="isTeacher" class="badge blue">
                {{ activeCheckin.checked_count }} / {{ activeCheckin.total_students }} 已签
              </span>
            </div>

            <div v-if="isTeacher" class="checkin-body">
              <span class="faint small">签到内容：{{ activeCheckin.mode === 'pattern' ? activeCheckin.answer : '数字 ' + activeCheckin.answer }}</span>
              <div class="row" style="gap: 8px">
                <button class="btn sm" @click="viewCheckinStatus(activeCheckin)">查看谁没签</button>
                <button class="btn sm" @click="closeCheckin(activeCheckin)">结束签到</button>
              </div>
            </div>

            <div v-else-if="activeCheckin.my_record" class="checkin-body">
              <span class="badge green">✅ 你已完成签到</span>
            </div>

            <div v-else-if="activeCheckin.mode === 'number'" class="checkin-body">
              <input
                v-model="checkinAnswer"
                class="input"
                placeholder="输入老师说的数字"
                style="max-width: 200px"
                @keyup.enter="doCheckin"
              />
              <button class="btn primary sm" :disabled="checkinBusy" @click="doCheckin">签到</button>
            </div>

            <div v-else class="checkin-body">
              <span class="faint small">选出老师指定的图案：</span>
              <div class="pattern-row">
                <button
                  v-for="p in patterns"
                  :key="p"
                  class="pattern-btn"
                  :disabled="checkinBusy"
                  @click="pickPattern(p)"
                >
                  {{ p }}
                </button>
              </div>
            </div>
          </div>
'''
    t = t.replace('<div ref="chatBox" class="chat-box">', banner + '\n          <div ref="chatBox" class="chat-box">', 1)

    # ---------- 发起签到按钮（作业标签上方工具条） ----------
    t = t.replace(
        '<button v-if="isTeacher" class="btn primary sm" @click="showAssign = true">发布作业</button>',
        '''<div class="row" style="gap: 8px">
              <button v-if="isTeacher" class="btn sm" @click="showStartCheckin = true">发起签到</button>
              <button v-if="isTeacher" class="btn primary sm" @click="showAssign = true">发布作业</button>
            </div>''',
        1,
    )

    # ---------- 发起签到弹窗 ----------
    start_modal = '''
    <!-- 发起签到 -->
    <div v-if="showStartCheckin" class="modal-mask" @click.self="showStartCheckin = false">
      <div class="modal" style="width: min(520px, 94vw)">
        <div class="modal-head"><h3>发起签到</h3></div>

        <div class="field">
          <label>签到方式</label>
          <div class="row" style="gap: 12px">
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="checkinForm.mode" type="radio" value="number" /> 数字
            </label>
            <label class="row" style="gap: 6px; cursor: pointer">
              <input v-model="checkinForm.mode" type="radio" value="pattern" /> 图案
            </label>
          </div>
        </div>

        <div v-if="checkinForm.mode === 'number'" class="field">
          <label>签到数字</label>
          <input
            v-model="checkinForm.answer"
            class="input"
            placeholder="例如 3721，学生在群里输入同样的数字才算签到"
          />
        </div>

        <div v-else class="field">
          <label>指定图案</label>
          <div class="pattern-row" style="margin-top: 6px">
            <button
              v-for="p in patterns"
              :key="p"
              class="pattern-btn"
              :class="{ active: checkinForm.pattern === p }"
              @click="checkinForm.pattern = p"
            >
              {{ p }}
            </button>
          </div>
        </div>

        <div class="field">
          <label>持续时长（分钟）</label>
          <input v-model="checkinForm.minutes" class="input" type="number" min="1" max="60" style="max-width: 120px" />
        </div>

        <div class="form-actions">
          <button class="btn" @click="showStartCheckin = false">取消</button>
          <button class="btn primary" :disabled="checkinBusy" @click="startCheckin">开始签到</button>
        </div>
      </div>
    </div>

    <!-- 签到情况 -->
    <div v-if="checkinStatus" class="modal-mask" @click.self="checkinStatus = null">
      <div class="modal" style="width: min(620px, 96vw)">
        <div class="modal-head">
          <h3>签到情况</h3>
          <button class="btn sm" @click="checkinStatus = null">关闭</button>
        </div>

        <div class="grid cols-3" style="margin: 10px 0">
          <div class="stat"><div class="stat-label">应交</div><div class="stat-value">{{ checkinStatus.total }}</div></div>
          <div class="stat"><div class="stat-label">已签</div><div class="stat-value" style="color: var(--success)">{{ checkinStatus.checked_count }}</div></div>
          <div class="stat"><div class="stat-label">未签</div><div class="stat-value" style="color: var(--danger)">{{ checkinStatus.missing_count }}</div></div>
        </div>

        <div class="row" style="gap: 10px; align-items: flex-start">
          <div style="flex: 1">
            <div class="stat-label" style="margin-bottom: 6px">未签到（{{ checkinStatus.missing_count }}）</div>
            <div class="list-box">
              <div v-for="s in checkinStatus.missing" :key="s.student_id" class="list-row">
                <span>{{ s.real_name }} <span class="faint small">{{ s.number }}</span></span>
                <span class="badge red">未签</span>
              </div>
              <div v-if="!checkinStatus.missing.length" class="empty">全部到齐 🎉</div>
            </div>
          </div>
          <div style="flex: 1">
            <div class="stat-label" style="margin-bottom: 6px">已签到（{{ checkinStatus.checked_count }}）</div>
            <div class="list-box">
              <div v-for="s in checkinStatus.checked" :key="s.student_id" class="list-row">
                <span>{{ s.real_name }} <span class="faint small">{{ s.number }}</span></span>
                <span class="badge green">已签</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
'''
    t = t.replace("  </div>\n</template>", start_modal + "  </div>\n</template>", 1)

    # ---------- 样式 ----------
    css = '''
/* 签到 */
.checkin-banner {
  border: 1px solid #ffd88a;
  background: linear-gradient(135deg, rgba(255, 214, 102, 0.22), rgba(255, 138, 61, 0.12));
  border-radius: 12px; padding: 10px 12px; margin-bottom: 10px;
}
.checkin-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.checkin-title { font-weight: 700; color: #8a5a00; }
.checkin-body { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
.pattern-row { display: flex; gap: 8px; flex-wrap: wrap; }
.pattern-btn {
  font-size: 22px; line-height: 1; padding: 8px 10px; border-radius: 12px;
  border: 1px solid var(--border); background: #fff; cursor: pointer;
  transition: transform .12s, border-color .12s;
}
.pattern-btn:hover { transform: translateY(-2px); border-color: var(--primary); }
.pattern-btn.active { border-color: var(--primary); background: #fff4e8; }
'''
    t = t.replace("</style>", css + "\n</style>", 1)

    p.write_text(t, encoding="utf-8")
    print("GroupView: 已加入签到")
else:
    print("GroupView: 已存在签到")
