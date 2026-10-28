"""给管理员用户管理页加上「强制下线」和「注销账号」按钮。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\AdminUsersView.vue")
text = p.read_text(encoding="utf-8")

if "kickUser" not in text:
    funcs = '''
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

'''
    marker = "async function load("
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit("找不到 load 函数")
    text = text[:idx] + funcs + text[idx:]

if "kickUser(" not in text.split("<template>")[-1]:
    # 在「禁用/启用」按钮前插入两个按钮
    import re

    pattern = re.compile(
        r'(<button[^>]*@click="toggleStatus\((\w+)\)"[^>]*>)', re.S
    )
    m = pattern.search(text)
    if not m:
        raise SystemExit("找不到 toggleStatus 按钮")
    var = m.group(2)
    extra = (
        f'<button class="btn sm" :disabled="actingId === {var}.id" '
        f'@click="kickUser({var})">下线</button>\n'
        f'            <button class="btn sm danger" :disabled="actingId === {var}.id" '
        f'@click="cancelAccount({var})">注销</button>\n            '
    )
    text = text[: m.start()] + extra + text[m.start():]

p.write_text(text, encoding="utf-8")
print("已修改 AdminUsersView.vue，行数:", len(text.splitlines()))
