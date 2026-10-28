"""给前端补三个小功能：通知跳转、成绩单导出、用户名单导出。"""

from pathlib import Path

V = Path(r"D:\EduFlow\frontend\src\views")

# ---------- 1. 通知点击跳转 ----------
p = V / "NotificationsView.vue"
t = p.read_text(encoding="utf-8")
if "openItem" not in t:
    t = t.replace('@click="markRead(item)"', '@click="openItem(item)"')
    if "useRouter" not in t:
        t = t.replace("import { api", "import { useRouter } from 'vue-router'\nimport { api", 1)
    # 在 markRead 函数定义后插入 openItem
    marker = "async function markRead("
    idx = t.find(marker)
    if idx > 0:
        end = t.find("\n}\n", idx) + 3
        func = (
            "\nasync function openItem(item) {\n"
            "  await markRead(item)\n"
            "  if (item.link) {\n"
            "    const target = item.link.startsWith('/') ? `#${item.link}` : item.link\n"
            "    if (target.startsWith('#')) window.location.hash = target.slice(1)\n"
            "    else window.open(item.link, '_blank')\n"
            "  }\n"
            "}\n"
        )
        t = t[:end] + func + t[end:]
    p.write_text(t, encoding="utf-8")
    print("NotificationsView: 已加入点击跳转")

# ---------- 2. 成绩单导出 ----------
p = V / "TranscriptView.vue"
t = p.read_text(encoding="utf-8")
if "exportCsv" not in t:
    t = t.replace(
        "<button class=\"btn\" :disabled=\"loading\" @click=\"load\">",
        "<button class=\"btn primary\" :disabled=\"loading\" @click=\"exportCsv\">导出 CSV</button>\n      <button class=\"btn\" :disabled=\"loading\" @click=\"load\">",
        1,
    )
    idx = t.find("onMounted(load)")
    func = '''async function exportCsv() {
  try {
    const token = localStorage.getItem('eduflow_token') || ''
    const res = await fetch('/api/my/transcript/export', {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error('导出失败')
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = '我的成绩单.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (err) {
    ui.error(err.message)
  }
}

'''
    if idx > 0:
        t = t[:idx] + func + t[idx:]
    p.write_text(t, encoding="utf-8")
    print("TranscriptView: 已加入导出按钮")

# ---------- 3. 用户名单导出 ----------
p = V / "AdminUsersView.vue"
t = p.read_text(encoding="utf-8")
if "exportUsers" not in t:
    t = t.replace(
        '<button class="btn primary"',
        '<button class="btn" @click="exportUsers">导出名单</button>\n        <button class="btn primary"',
        1,
    )
    idx = t.find("async function load(")
    func = '''async function exportUsers() {
  try {
    const token = localStorage.getItem('eduflow_token') || ''
    const res = await fetch('/api/users/export', { headers: { Authorization: `Bearer ${token}` } })
    if (!res.ok) throw new Error('导出失败')
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = '用户名单.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (err) {
    ui.error(err.message)
  }
}

'''
    if idx > 0:
        t = t[:idx] + func + t[idx:]
    p.write_text(t, encoding="utf-8")
    print("AdminUsersView: 已加入导出按钮")
