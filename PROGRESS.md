# 开发进度快照（2026-10-23 23:30）

> 明天从这里继续。本文档记录：做到了哪一步、怎么跑起来、还剩什么。

---

## 一、一句话状态

**后端已完整可用（7087 行、91 接口、70 项测试全绿），前端 15 个页面已写完并构建成功，
只差最后的真机视觉验收与打包。** 代码全部已提交，共 3 个提交。

---

## 二、当前完成度

| 模块 | 状态 | 证据 |
|---|---|---|
| 后端（表/仓储/服务/接口） | ✅ 完成 | `python -m backend.cli check` |
| 演示数据 | ✅ 完成 | 16 账号 / 3 课 / 4 班 / 作业成绩签到齐全 |
| 单元测试（36 项） | ✅ 全过 | `python -m unittest tests.test_core` |
| 端到端测试（34 项） | ✅ 全过 | `python tests/smoke_test.py` |
| 前端工程 + 15 页面 | ✅ 完成 | `npm run build` 成功，47 modules |
| 视觉/交互验收 | ⏳ **未做** | 需截图逐页检查 |
| pywebview 桌面窗口验收 | ⏳ **未做** | 未真正打开过窗口 |
| 打包（`scripts/package.ps1`） | ⏳ **未跑过** | — |

### 页面清单（`frontend/src/views/`）

| 文件 | 行数 | 对应路由 |
|---|---:|---|
| LoginView.vue | 94 | /login |
| DashboardView.vue | 280 | / |
| CourseListView.vue | 251 | /courses |
| CourseDetailView.vue | 552 | /courses/:id |
| ClassDetailView.vue | 644 | /classes/:id |
| GradebookView.vue | 354 | /classes/:id/gradebook |
| MyAssignmentsView.vue | 122 | /my/assignments |
| AssignmentDetailView.vue | 517 | /assignments/:id |
| QuizTakeView.vue | 355 | /quizzes/:id/take |
| AttendanceView.vue | 527 | /attendance |
| TranscriptView.vue | 146 | /grades |
| NotificationsView.vue | 198 | /notifications |
| AdminUsersView.vue | 531 | /admin/users |
| ProfileView.vue | 282 | /profile |
| NotFoundView.vue | 27 | /:pathMatch |

---

## 三、明天怎么跑起来

```powershell
cd D:\deepseek\projects\eduflow

# 1. 起后端（会自动用已有的 data/eduflow.db）
.\.venv\Scripts\python.exe -m backend.cli serve --port 8765

# 2. 浏览器打开 http://127.0.0.1:8765
#    账号：admin / t1001 / s2001，密码统一 Eduflow@2026
```

桌面窗口模式：

```powershell
.\.venv\Scripts\python.exe run.py
```

前端改完要重新构建（改了 .vue 必须 build，否则后端还托管旧的 dist）：

```powershell
cd frontend
$env:Path = 'D:\deepseek\Node;' + $env:Path
& 'D:\deepseek\Node\npm.cmd' run build
```

---

## 四、明天要做的四件事（按顺序）

### 1. 真机视觉验收（最重要）
已装好 `playwright`（在 `.venv` 里，用系统自带的 Edge，不用下载浏览器）。
写一个脚本自动登录三种角色，逐页截图，检查：

- 登录页 → 管理员工作台 → 用户管理
- 教师：课程列表 → 课程详情（传资料/发讨论）→ 教学班 → 成绩册
- 学生：我的作业 → 作业详情提交 → 在线测验 → 签到 → 成绩单

要点：截图存到 `docs/screenshots/`，发现排版/文案问题就地修，改完重新 `npm run build`。

### 2. 桌面窗口验收
真实跑一次 `run.py`，确认：
- WebView2 窗口能正常打开、无白屏
- 窗口标题/尺寸正常
- 关闭窗口后后台 Python 进程能退出（run.py 里有 watchdog，需实测）

### 3. 打包
```powershell
powershell -ExecutionPolicy Bypass -File scripts/package.ps1
```
产物在 `dist/EduFlow/`，含 `启动.bat`。确认打包目录里 `frontend/dist` 存在。

### 4. 收尾提交
- 截图放进 README
- 补一次提交：`docs: 视觉验收与打包`

---

## 五、已知待办 / 可能的坑

1. **通知分页**：已修（新增 `count_for_user`），但前端 `NotificationsView` 里写了个
   "整页即认为有下一页"的兜底逻辑，现在后端 total 准确了，可以简化，不急。
2. **`--browser` 模式**：`run.py` 里用一个 `while True` 阻塞，Ctrl+C 才退出，可用但不优雅。
3. **签到位置校验**：需要浏览器授权定位，桌面 WebView2 下可能拿不到坐标，
   测试时优先用「数字码」方式，位置签到只是功能完整度。
4. **多选答案格式**：前后端约定是 `"A,B"` 字符串，改的时候两边都要动。
5. **`frontend/package-lock.json` 已提交**，换机器 `npm ci` 即可复现。

---

## 六、关键约定（改代码前先看）

- 响应信封：`{ok:true,data}` / `{ok:false,error:{code,message}}`
- 鉴权：`Authorization: Bearer <token>`，令牌存 `sessions` 表，72 小时
- 时间：数据库一律 UTC ISO（`...Z`），前端负责转本地
- 权限：`backend/core/permissions.py`，课程相关一律走 `assert_can_manage_course`
- 分层：API 只搬参数，Service 写规则，Repository 只写 SQL
- 提交前跑：`python -m unittest tests.test_core` 和 `python tests/smoke_test.py`

---

## 七、Git 记录

```
3ad825d feat: 前端骨架、登录与工作台，补齐单元测试与文档
8f79f7a feat: 完成后端业务闭环与端到端测试
8891924 chore: 初始化项目骨架与基础配置
```

（明天还会追加：前端全部页面、视觉验收、打包）
