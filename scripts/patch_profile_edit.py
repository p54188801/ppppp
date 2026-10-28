"""个人中心：支持自助修改全部资料。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\ProfileView.vue")
t = p.read_text(encoding="utf-8")

if "saveProfile" not in t:
    # ---------- script ----------
    logic = '''
// ---------------------------------------------------------------------------
// 自助修改资料
// ---------------------------------------------------------------------------
const editing = ref(false)
const saving = ref(false)
const profileForm = ref({ real_name: '', number: '', department: '', class_name: '', email: '', phone: '' })

function startEdit() {
  const m = me.value || {}
  profileForm.value = {
    real_name: m.real_name || '',
    number: m.number || '',
    department: m.department || '',
    class_name: m.class_name || '',
    email: m.email || '',
    phone: m.phone || '',
  }
  editing.value = true
}

async function saveProfile() {
  if (!profileForm.value.real_name.trim()) {
    ui.error('姓名不能为空')
    return
  }
  saving.value = true
  try {
    const data = await api.put('/api/auth/profile', profileForm.value)
    me.value = data
    auth.user = data
    editing.value = false
    ui.success('资料已更新')
  } catch (error) {
    ui.error(error.message)
  } finally {
    saving.value = false
  }
}
'''
    t = t.replace("async function submitPassword()", logic + "\nasync function submitPassword()", 1)

    # ---------- 标题右侧加按钮 ----------
    old_title = """          <div class="card-title">
            <span>基本资料</span>"""
    new_title = """          <div class="card-title">
            <span>基本资料</span>
            <button v-if="!editing" class="btn sm" @click="startEdit">编辑资料</button>
            <span v-else class="faint small">编辑中…</span>"""
    if old_title in t:
        t = t.replace(old_title, new_title, 1)

    # ---------- 编辑表单 ----------
    form_block = '''
          <div v-if="editing" style="margin-bottom: 16px">
            <div class="grid cols-2" style="gap: 12px">
              <div class="field">
                <label>姓名</label>
                <input v-model="profileForm.real_name" class="input" placeholder="真实姓名" />
              </div>
              <div class="field">
                <label>学号 / 工号</label>
                <input v-model="profileForm.number" class="input" placeholder="学号或工号" />
              </div>
              <div class="field">
                <label>院系</label>
                <input v-model="profileForm.department" class="input" placeholder="例如：计算机学院" />
              </div>
              <div class="field">
                <label>班级</label>
                <input v-model="profileForm.class_name" class="input" placeholder="例如：大数据G231" />
                <div class="hint">修改班级会自动切换班级群</div>
              </div>
              <div class="field">
                <label>邮箱</label>
                <input v-model="profileForm.email" class="input" placeholder="name@example.com" />
              </div>
              <div class="field">
                <label>电话</label>
                <input v-model="profileForm.phone" class="input" placeholder="手机号" />
              </div>
            </div>
            <div class="row" style="gap: 10px; margin-top: 8px">
              <button class="btn primary" :disabled="saving" @click="saveProfile">
                {{ saving ? '保存中…' : '保存' }}
              </button>
              <button class="btn" :disabled="saving" @click="editing = false">取消</button>
            </div>
          </div>
'''
    # 插到「基本资料」卡片内的 grid 之前
    anchor = '''          <div class="grid cols-2" style="gap: 12px">'''
    idx = t.find(anchor)
    if idx > 0:
        t = t[:idx] + form_block + t[idx:]
    else:
        raise SystemExit("找不到资料 grid 锚点")

    p.write_text(t, encoding="utf-8")
    print("ProfileView: 已加入资料编辑")
else:
    print("ProfileView: 已存在编辑功能")
