"""把签到与作业拆成两个独立标签页。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\GroupView.vue")
text = p.read_text(encoding="utf-8")
lines = text.splitlines()


def find(pred, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    return -1


i_tabs = find(lambda s: 'class="tabs"' in s)
i_banner = find(lambda s: 'class="checkin-banner"' in s)
i_assign_tab = find(lambda s: "tab === 'assign'" in s and '<div class="tab"' in s)
i_tabs_close = find(lambda s: s.strip() == "</div>", i_assign_tab)

if min(i_tabs, i_banner, i_assign_tab, i_tabs_close) < 0:
    raise SystemExit(f"锚点未找到 {i_tabs} {i_banner} {i_assign_tab} {i_tabs_close}")

banner_block = lines[i_banner - 1: i_assign_tab]  # 含注释行
indent = "          "

new_tabs = [
    '        <div class="tabs">',
    '          <div class="tab" :class="{ active: tab === \'chat\' }" @click="tab = \'chat\'">聊天</div>',
    '          <div class="tab" :class="{ active: tab === \'assign\' }" @click="tab = \'assign\'">',
    '            作业（{{ current.assignments.length }}）',
    '          </div>',
    '          <div class="tab" :class="{ active: tab === \'checkin\' }" @click="tab = \'checkin\'">',
    '            签到（{{ checkins.length }}）',
    '          </div>',
    '        </div>',
    '',
]

lines[i_tabs: i_tabs_close + 1] = new_tabs + banner_block

text = "\n".join(lines)

# 作业块改成 v-else-if
text = text.replace('<template v-else>\n          <div class="row between" style="margin-bottom: 12px">',
                    '<template v-else-if="tab === \'assign\'">\n          <div class="row between" style="margin-bottom: 12px">', 1)

# 去掉作业工具栏里的「发起签到」
text = text.replace('''              <button v-if="isTeacher" class="btn sm" @click="showStartCheckin = true">发起签到</button>
''', "", 1)

# 在 group-main 结束前插入签到标签内容
lines = text.splitlines()
idx_section_end = -1
for i in range(len(lines) - 1):
    if lines[i].strip() == "</section>" and "<section v-else" in lines[i + 1]:
        idx_section_end = i
        break

checkin_tab = '''
        <!-- 签到 -->
        <template v-else>
          <div class="row between" style="margin-bottom: 12px">
            <span class="muted small">共 {{ checkins.length }} 次签到</span>
            <button v-if="isTeacher" class="btn primary sm" @click="showStartCheckin = true">发起签到</button>
          </div>

          <div v-if="!checkins.length" class="empty" style="padding: 20px">
            还没有签到记录{{ isTeacher ? '，点右上角「发起签到」开始' : '，等老师发起' }}
          </div>

          <div v-for="c in checkins" :key="c.id" class="checkin-card">
            <div class="row between">
              <div>
                <div class="checkin-card-title">
                  {{ c.mode === 'pattern' ? '图案签到 ' + c.answer : '数字签到' }}
                  <span class="badge" :class="c.status === 'open' ? 'green' : 'gray'">
                    {{ c.status === 'open' ? '进行中' : '已结束' }}
                  </span>
                </div>
                <div class="faint small">
                  {{ c.started_at }} 开始 · {{ c.minutes ? c.minutes + ' 分钟' : '手动结束' }}
                </div>
              </div>
              <div class="row" style="gap: 8px">
                <span class="badge blue">{{ c.checked_count }} / {{ current.members.filter(m => m.role === 'student').length }} 已签</span>
                <button v-if="isTeacher" class="btn sm" @click="viewCheckinStatus(c)">查看谁没签</button>
                <button v-if="isTeacher && c.status === 'open'" class="btn sm" @click="closeCheckin(c)">结束</button>
              </div>
            </div>
          </div>
        </template>
'''

if idx_section_end > 0:
    lines[idx_section_end:idx_section_end] = checkin_tab.splitlines()
    text = "\n".join(lines)
else:
    print("未找到 group-main 结束位置")

# 状态变量 + 加载历史
if "const checkins = ref([])" not in text:
    text = text.replace("const activeCheckin = ref(null)",
                        "const activeCheckin = ref(null)\nconst checkins = ref([])", 1)
    text = text.replace("""    activeCheckin.value = await api
      .get(`/api/groups/${groupId.value}/checkins/active`)
      .catch(() => null)""",
                        """    activeCheckin.value = await api
      .get(`/api/groups/${groupId.value}/checkins/active`)
      .catch(() => null)
    checkins.value = await api
      .get(`/api/groups/${groupId.value}/checkins`)
      .catch(() => [])""", 1)

# 样式
if "checkin-card" not in text:
    text = text.replace("</style>", """/* 签到卡片 */
.checkin-card {
  border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px;
  margin-bottom: 10px; background: #fff;
}
.checkin-card-title { font-weight: 650; color: #1d3557; display: flex; align-items: center; gap: 8px; }
</style>""", 1)

p.write_text(text, encoding="utf-8")
print("GroupView: 签到已拆成独立标签")
