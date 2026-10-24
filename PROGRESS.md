# 开发进度快照（2026-10-24 完成）

> 目标：类似"学习通"的教务系统桌面应用 —— pywebview(WebView2) + Vue3 + Python 后端，
> 自写后端业务逻辑 ≥5000 行，带完整 git 提交历史。

---

## 一、当前状态：已完成 ✅

| 验收项 | 结果 | 证据 |
|---|---|---|
| 后端自写代码量 | **7797 行**（远超 5000 要求） | `backend/` 6785 行 + `tests/` 900+ 行 + schema 302 行 |
| 前端 Vue3 | 6040 行，15 个页面 | `frontend/src/` |
| 单元测试 | **36 项通过** | `python -m unittest tests.test_core` |
| 端到端测试 | **34 项通过** | `python tests/smoke_test.py` |
| 浏览器视觉验收 | **15 张截图，控制台零错误** | `docs/screenshots/` |
| 桌面窗口验收 | **WebView2 正常渲染并可登录** | `docs/screenshots/00-window.png` |
| 打包 | **通过**，产物 0.6 MB | `dist/EduFlow/` |
| git 提交历史 | **5 次提交**，分阶段可追溯 | `git log` |

---

## 二、验收过程记录

### 1. 浏览器逐页截图（playwright + 系统 Edge）

脚本 `scripts/screenshot.py`，自动登录三种角色逐页截图：

```
01-login  02-admin-dashboard  03-admin-users  04-teacher-dashboard  05-teacher-courses
06-course-detail  07-class-detail  08-gradebook  09-attendance-teacher
10-student-dashboard  11-my-assignments  11b-assignment-detail
12-transcript  13-attendance-student  14-notifications
```

结果：**控制台无错误**。首轮发现并修复三处问题：

- 资料是 0 字节死链 → 种子数据改为真实写入文件（含课程大纲内容）
- favicon 404 → 用内联 SVG data URI 解决
- 学生首页「最近通知」是占位文案 → 改为真实拉取通知列表

### 2. 桌面窗口验收（关键）

WebView2 窗口标题 `EduFlow 教务系统 v1.0.0`，进程正常，37 个 msedgewebview2 子进程。

验收中发现并解决的问题：

- **抓图假象**：用 `CopyFromScreen` 抓最小化/未绘制的窗口会得到一片底色，
  改用 `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` 后确认页面渲染完全正常
  （脚本：`scripts/capture_window.ps1`）。
- **DPI 缩放**：进程声明 `SetProcessDpiAwareness(2)`，避免 125% 缩放下窗口内容被裁切。
- **首帧竞态**：窗口先显示占位页，0.6 秒后再 `load_url`，规避 WebView2 偶发首帧不绘制。
- 通过 CDP（`--remote-debugging-port=9222`）注入登录，确认 **WebView2 内可正常登录并渲染工作台**。

### 3. 打包

`scripts/package.ps1` 一键完成：构建前端 → 收集后端 → 清理缓存 → 生成 `启动.bat`。
产物 `dist/EduFlow/`（0.6 MB，不含依赖），在产物目录内执行 `backend.cli check` 通过：
`database: true, frontend_built: true, routes: 91`。

---

## 三、已知限制 / 后续可做

1. **位置签到**：桌面 WebView2 下浏览器定位依赖系统设置，演示优先用数字码签到。
2. **通知分页**：后端 `total` 已修正为精确值，前端 `NotificationsView` 里的"整页兜底"逻辑可简化。
3. **`--browser` 模式**：用 `while True` 阻塞，Ctrl+C 退出，可用但不优雅。
4. **富文本**：作业与讨论目前是纯文本，可扩展 Markdown 渲染。
5. **多学期切换**：已按 term 字段存储，未做学期切换 UI。

---

## 四、命令速查

```powershell
# 开发运行
.\.venv\Scripts\python.exe run.py

# 只起服务
.\.venv\Scripts\python.exe -m backend.cli serve --port 8765

# 测试
.\.venv\Scripts\python.exe -m unittest tests.test_core
.\.venv\Scripts\python.exe tests\smoke_test.py

# 视觉验收（需先起服务）
.\.venv\Scripts\python.exe scripts\screenshot.py

# 打包
powershell -ExecutionPolicy Bypass -File scripts\package.ps1
```

---

## 五、Git 记录

```
<本次> docs: 视觉验收、桌面窗口验证与打包
e2d3532 feat: 全部 15 个前端页面 + 进度快照
3ad825d feat: 前端骨架、登录与工作台，补齐单元测试与文档
8f79f7a feat: 完成后端业务闭环与端到端测试
8891924 chore: 初始化项目骨架与基础配置
```
