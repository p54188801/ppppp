"""首页接入班级群数据：学生端待办、管理员群概况。"""

from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\DashboardView.vue")
t = p.read_text(encoding="utf-8")

# 1) 管理员：加一张「班级群概况」卡片（插在管理员统计卡之后）
if "群学生" not in t:
    anchor = '''          <div class="stat-value">{{ data.attendance_rate }}%</div>'''
    idx = t.find(anchor)
    if idx > 0:
        end = t.find("</div>", t.find("</div>", t.find("</div>", idx) + 6) + 6) + 6
        card = '''
        <div class="stat">
          <div class="stat-label">班级群学生</div>
          <div class="stat-value">{{ data.group?.students ?? 0 }}</div>
          <div class="stat-hint">群内学生总数</div>
        </div>
        <div class="stat">
          <div class="stat-label">群作业待批改</div>
          <div class="stat-value" :style="{ color: data.group?.ungraded ? 'var(--warning)' : '' }">
            {{ data.group?.ungraded ?? 0 }}
          </div>
          <div class="stat-hint">群内未评分提交</div>
        </div>
'''
        # 找到该行所在 stat 块的结束
        block_end = t.find("</div>\n        </div>", idx)
        if block_end < 0:
            block_end = t.find("</div>", idx)
        insert_at = t.find("</div>", t.find("</div>", block_end) ) + len("</div>")
        t = t[:insert_at] + card + t[insert_at:]
        p.write_text(t, encoding="utf-8")
        print("DashboardView: 管理员加群概况")
else:
    print("DashboardView: 管理员已含群概况")

t = p.read_text(encoding="utf-8")

# 2) 学生：待完成作业用 pending_count（兼容数字/数组）
t = t.replace(
    '<div class="stat-value">{{ data.pending_assignments }}</div>',
    '<div class="stat-value">{{ data.pending_count ?? (Array.isArray(data.pending_assignments) ? data.pending_assignments.length : data.pending_assignments) }}</div>',
)

# 3) 学生：待交作业列表加入群作业
if "pending_list" not in t:
    marker = 'v-for="item in (todos.pending_assignments || []).slice(0, 3)"'
    if marker in t:
        t = t.replace(
            marker,
            'v-for="item in [...(todos.pending_assignments || []), ...(data.pending_list || [])].slice(0, 5)"',
        )

p.write_text(t, encoding="utf-8")
print("DashboardView: 学生待办接入群作业")
