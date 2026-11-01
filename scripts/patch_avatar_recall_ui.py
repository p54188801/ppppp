"""品牌图标、头像上传、消息撤回菜单（前端）。"""

from pathlib import Path

ROOT = Path(r"D:\EduFlow")

# ---------------- 1. 侧边栏品牌图标换成 logo ----------------
app = ROOT / "frontend" / "src" / "App.vue"
t = app.read_text(encoding="utf-8")
if "logo.png" not in t:
    t = t.replace(
        '<div class="brand-mark">晨</div>',
        '<img class="brand-mark-img" src="/assets/logo.png" alt="晨光教务" />',
        1,
    )
    t = t.replace(
        '<div class="brand-mark" style="width: 30px; height: 30px; font-size: 13px">\n              {{ initials }}\n            </div>',
        '<img\n              v-if="auth.user?.avatar"\n              class="brand-mark-img" style="width: 30px; height: 30px"\n              :src="auth.user.avatar" alt="头像"\n            />\n            <div v-else class="brand-mark" style="width: 30px; height: 30px; font-size: 13px">\n              {{ initials }}\n            </div>',
        1,
    )
    app.write_text(t, encoding="utf-8")
    print("App.vue: 品牌图 + 顶栏头像")

# ---------------- 2. 登录/注册/找回：logo ----------------
for name in ("LoginView.vue", "RegisterView.vue", "ForgotView.vue"):
    p = ROOT / "frontend" / "src" / "views" / name
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    if "logo.png" in t:
        continue
    t = t.replace(
        '<div class="brand-mark" style="width: 42px; height: 42px; font-size: 17px">晨</div>',
        '<img class="brand-mark-img" style="width: 42px; height: 42px" src="/assets/logo.png" alt="晨光教务" />',
    )
    p.write_text(t, encoding="utf-8")
print("登录类页面: 品牌图")

# ---------------- 3. 个人中心：上传头像 ----------------
prof = ROOT / "frontend" / "src" / "views" / "ProfileView.vue"
t = prof.read_text(encoding="utf-8")
if "uploadAvatar" not in t:
    t = t.replace(
        "const myPoints = ref(null)",
        """const myPoints = ref(null)
const avatarInput = ref(null)
const uploadingAvatar = ref(false)

async function pickAvatar() {
  avatarInput.value?.click()
}

async function uploadAvatar(event) {
  const file = event.target.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) return ui.error('请选择图片文件')
  const form = new FormData()
  form.append('file', file)
  uploadingAvatar.value = true
  try {
    const data = await api.upload('/api/auth/avatar', form)
    me.value = { ...(me.value || {}), avatar: data.avatar }
    if (auth.user) auth.user = { ...auth.user, avatar: data.avatar }
    ui.success('头像已更新')
  } catch (error) {
    ui.error(error.message)
  } finally {
    uploadingAvatar.value = false
    if (avatarInput.value) avatarInput.value.value = ''
  }
}

async function removeAvatar() {
  try {
    await api.delete('/api/auth/avatar')
    me.value = { ...(me.value || {}), avatar: '' }
    if (auth.user) auth.user = { ...auth.user, avatar: '' }
    ui.success('已恢复默认头像')
  } catch (error) {
    ui.error(error.message)
  }
}""",
        1,
    )
    # 头像展示
    t = t.replace(
        '<div class="brand-mark" style="width: 52px; height: 52px; font-size: 20px">\n              {{ (me.real_name || \'U\').slice(0, 1) }}\n            </div>',
        '<img\n              v-if="me.avatar"\n              :src="me.avatar"\n              class="brand-mark-img"\n              style="width: 52px; height: 52px"\n              alt="头像"\n            />\n            <div v-else class="brand-mark" style="width: 52px; height: 52px; font-size: 20px">\n              {{ (me.real_name || \'U\').slice(0, 1) }}\n            </div>',
        1,
    )
    # 上传按钮
    t = t.replace(
        '<div class="card-title">\n            <span>基本资料</span>',
        '<div class="card-title">\n            <span>基本资料</span>\n            <div class="row" style="gap: 8px">\n              <input ref="avatarInput" type="file" accept="image/*" style="display: none" @change="uploadAvatar" />\n              <button class="btn sm" :disabled="uploadingAvatar" @click="pickAvatar">\n                {{ uploadingAvatar ? \'上传中…\' : \'换头像\' }}\n              </button>\n              <button v-if="me.avatar" class="btn sm" @click="removeAvatar">恢复默认</button>\n            </div>',
        1,
    )
    prof.write_text(t, encoding="utf-8")
    print("ProfileView: 头像上传")

# ---------------- 4. 群聊：头像 + 撤回菜单 ----------------
g = ROOT / "frontend" / "src" / "views" / "GroupView.vue"
t = g.read_text(encoding="utf-8")
if "recallMenu" not in t:
    # 头像图片
    t = t.replace(
        '''<div class="msg-avatar" :class="roleBadge(m).cls">
                {{ (m.sender_name || '?').slice(0, 1) }}
              </div>''',
        '''<img
                v-if="m.sender_avatar"
                :src="m.sender_avatar"
                class="msg-avatar-img"
                alt=""
              />
              <div v-else class="msg-avatar" :class="roleBadge(m).cls">
                {{ (m.sender_name || '?').slice(0, 1) }}
              </div>''',
        1,
    )
    # 撤回占位
    t = t.replace(
        '''<div class="bubble-text" v-if="m.content">{{ m.content }}</div>''',
        '''<div class="bubble-text" v-if="m.content">{{ m.content }}</div>''',
    )
    t = t.replace(
        '<div v-if="m.content && m.kind !== \'assignment\'" class="bubble-text">{{ m.content }}</div>',
        '''<div v-if="m.recalled" class="bubble-recalled">该消息已撤回</div>
                  <div v-else-if="m.content && m.kind !== 'assignment'" class="bubble-text">{{ m.content }}</div>''',
        1,
    )
    # 右键 / 长按
    t = t.replace(
        '''<div
                  class="bubble"
                  :class="{ mine: isMine(m), clickable: m.kind === 'assignment' }"
                  @click="m.kind === 'assignment' && openAssignmentFromMessage(m)"
                >''',
        '''<div
                  class="bubble"
                  :class="{ mine: isMine(m), clickable: m.kind === 'assignment' }"
                  @click="m.kind === 'assignment' && !m.recalled && openAssignmentFromMessage(m)"
                  @contextmenu.prevent="openMenu($event, m)"
                  @touchstart.passive="startPress($event, m)"
                  @touchend="cancelPress"
                  @touchmove="cancelPress"
                >''',
        1,
    )
    # 状态与逻辑
    logic = '''
/* ---------------------------- 撤回菜单 ---------------------------- */
const recallMenu = ref({ show: false, x: 0, y: 0, msg: null })
let pressTimer = null

function openMenu(event, msg) {
  if (msg.recalled) return
  const x = event.clientX ?? event.touches?.[0]?.clientX ?? 0
  const y = event.clientY ?? event.touches?.[0]?.clientY ?? 0
  recallMenu.value = { show: true, x, y, msg }
}

function startPress(event, msg) {
  cancelPress()
  const touch = event.touches?.[0]
  if (!touch) return
  pressTimer = setTimeout(() => {
    recallMenu.value = { show: true, x: touch.clientX, y: touch.clientY, msg }
  }, 550)
}

function cancelPress() {
  if (pressTimer) {
    clearTimeout(pressTimer)
    pressTimer = null
  }
}

function closeMenu() {
  recallMenu.value.show = false
}

async function copyMessage() {
  const msg = recallMenu.value.msg
  closeMenu()
  if (!msg?.content) return ui.error('这条消息没有文字可复制')
  try {
    await navigator.clipboard.writeText(msg.content)
    ui.success('已复制')
  } catch {
    window.prompt('复制下面的内容：', msg.content)
  }
}

async function recallMessage() {
  const msg = recallMenu.value.msg
  closeMenu()
  if (!msg) return
  try {
    await api.post(`/api/messages/${msg.id}/recall`)
    ui.success('已撤回')
    await loadGroup()
  } catch (error) {
    ui.error(error.message)
  }
}

function canRecall(m) {
  return isMine(m) || auth.isAdmin
}
'''
    t = t.replace("/* ---------------------------- 签到 ---------------------------- */", logic + "\n/* ---------------------------- 签到 ---------------------------- */", 1)

    # 菜单 DOM
    menu = '''
      <div v-if="recallMenu.show" class="msg-menu-mask" @click="closeMenu" @contextmenu.prevent="closeMenu">
        <div class="msg-menu" :style="{ left: recallMenu.x + 'px', top: recallMenu.y + 'px' }" @click.stop>
          <button class="msg-menu-item" @click="copyMessage">复制</button>
          <button v-if="canRecall(recallMenu.msg)" class="msg-menu-item danger" @click="recallMessage">撤回</button>
        </div>
      </div>
'''
    t = t.replace("    <!-- 发布作业 -->", menu + "\n    <!-- 发布作业 -->", 1)

    # 样式
    css = '''
/* 头像图片 / 撤回 */
.msg-avatar-img { width: 34px; height: 34px; border-radius: 10px; object-fit: cover; flex-shrink: 0; }
.brand-mark-img { border-radius: 10px; object-fit: cover; flex-shrink: 0; }
.bubble-recalled { color: #98a8bd; font-style: italic; font-size: 13px; }
.msg-menu-mask { position: fixed; inset: 0; z-index: 500; }
.msg-menu {
  position: fixed; min-width: 120px; background: #fff; border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 12px 30px rgba(30,58,95,.18); overflow: hidden;
}
.msg-menu-item {
  display: block; width: 100%; text-align: left; padding: 10px 16px;
  background: none; border: none; font-size: 13.5px; color: #22314a; cursor: pointer;
}
.msg-menu-item:hover { background: #f4f9ff; }
.msg-menu-item.danger { color: var(--danger); }
'''
    t = t.replace("</style>", css + "\n</style>", 1)
    g.write_text(t, encoding="utf-8")
    print("GroupView: 头像 + 撤回菜单")
