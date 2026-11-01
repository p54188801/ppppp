"""把应用改名为「晨光教务」，并接入新图标。"""

from pathlib import Path

ROOT = Path(r"D:\EduFlow")
NEW_CN = "晨光教务"
NEW_SHORT = "晨光教务"

# ---------------- 后端配置 ----------------
cfg = ROOT / "backend" / "config.py"
t = cfg.read_text(encoding="utf-8")
t = t.replace('APP_NAME = "EduFlow 教务系统"', f'APP_NAME = "{NEW_CN}"')
t = t.replace('APP_SHORT_NAME = "EduFlow"', f'APP_SHORT_NAME = "{NEW_SHORT}"')
t = t.replace('APP_DESCRIPTION = "高校教务与教学管理平台"', 'APP_DESCRIPTION = "晨光教务 · 高校教务与教学管理平台"')
cfg.write_text(t, encoding="utf-8")
print("config: 已改名")

# ---------------- 前端 index.html ----------------
idx = ROOT / "frontend" / "index.html"
t = idx.read_text(encoding="utf-8")
t = t.replace("<title>EduFlow 教务系统</title>", f"<title>{NEW_CN}</title>")
if 'rel="icon"' not in t:
    t = t.replace("</head>", '    <link rel="icon" href="/assets/logo.png" />\n  </head>', 1)
idx.write_text(t, encoding="utf-8")
print("index.html: 已改名 + 图标")

# ---------------- 路由标题 ----------------
r = ROOT / "frontend" / "src" / "router" / "index.js"
t = r.read_text(encoding="utf-8")
t = t.replace("`${to.meta.title} · EduFlow`", f"`${{to.meta.title}} · {NEW_CN}`")
t = t.replace(": 'EduFlow'", f": '{NEW_CN}'")
r.write_text(t, encoding="utf-8")
print("router: 已改名")

# ---------------- 侧边栏品牌 ----------------
a = ROOT / "frontend" / "src" / "App.vue"
t = a.read_text(encoding="utf-8")
t = t.replace("<div class=\"brand-mark\">E</div>", "<div class=\"brand-mark\">晨</div>")
t = t.replace("<strong>EduFlow</strong>", f"<strong>{NEW_CN}</strong>")
t = t.replace("<span>教务系统 v1.0</span>", "<span>教务与教学管理平台</span>")
t = t.replace("route.meta.title || 'EduFlow'", f"route.meta.title || '{NEW_CN}'")
a.write_text(t, encoding="utf-8")
print("App.vue: 已改名")

# ---------------- 登录/注册页品牌 ----------------
for name in ("LoginView.vue", "RegisterView.vue", "ForgotView.vue"):
    p = ROOT / "frontend" / "src" / "views" / name
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    t = t.replace("EduFlow", NEW_CN)
    t = t.replace("高校教务与教学管理平台", "晨光教务 · 高校教务与教学管理平台")
    p.write_text(t, encoding="utf-8")
print("认证页面: 已改名")

# ---------------- 启动画面 ----------------
runp = ROOT / "run.py"
t = runp.read_text(encoding="utf-8")
t = t.replace("正在启动 EduFlow…", f"正在启动 {NEW_CN}…")
runp.write_text(t, encoding="utf-8")
print("run.py: 已改名")
