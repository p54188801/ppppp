# 后续计划（NEXT_STEPS）

> 更新于 2026-10-25。当前状态与下一步都记录在这里，新会话可直接接着做。

## 当前基线

```
031808a feat: 章节任务点与学习进度（教师完成率 + 学生进度卡）
f8afac7 docs: 新增功能路线图（对照学习通的模块清单与实施顺序）
f6af052 feat: 作业附件上传与下载（含越权校验）
24aa7cd docs: 新增 NEXT_STEPS 交接文档
0ab1033 test: 新增边界与并发自测（15 项）
```

| 项 | 值 |
|---|---|
| 仓库 | `D:\EduFlow`（唯一仓库，含完整 git 历史） |
| 接口 | 116 条 |
| 测试 | 单元 36 + 冒烟 39 + 新功能 19 + 边界 15 + 章节 30 = 139 项全过 |
| UI 巡检 | 桌面三角色 26 页 + 手机端 4 页，控制台 0 错误 |
| 单文件 | `eduflow_all.py` 11,485 行，routes 116，已与源码同步 |
| 数据表 | 26 张（schema v4 新增 `chapters` / `tasks` / `task_progress`） |
| 部署 | Dockerfile / docker-compose / Caddy / Render 配置已就绪 |
| 工作区 | 干净 |

## 环境注意

这个月磁盘被多次整理，工具路径会变，用之前先确认：

```powershell
(Get-Command git).Source        # 现在：D:\GIT\cmd\git.exe
Get-Command node                # 当前可用：C:\Users\31775\.dsh\tools\node\node.exe
```

Python 用项目自带的：`D:\EduFlow\.venv\Scripts\python.exe`。

> 启动开发服务前先确认 8905 端口没有旧进程（`Get-NetTCPConnection -LocalPort 8905`）。
> Qt/Windows 下 `SO_REUSEADDR` 会让两个服务同时监听同一端口，表现为「代码改了但接口 404」。

## 本次已完成：章节任务点 + 学习进度

- **数据层**：`chapters`（课程级章节）、`tasks`（5 种任务点：资料/作业/测验/讨论/图文，
  可关联 `resource_id` / `assignment_id` / `quiz_id`）、`task_progress`（学生进度，唯一约束）。
  迁移版本 v3 → v4，`schema.sql`、`migrations.py`、`reset_db()` 同步。
- **接口（10 条）**：
  - `GET/POST /api/courses/{id}/chapters`
  - `PUT/DELETE /api/chapters/{id}`
  - `POST /api/chapters/{id}/tasks`、`PUT/DELETE /api/tasks/{id}`
  - `POST /api/tasks/{id}/progress`（学生上报，0–100）
  - `GET /api/courses/{id}/progress`（教师看章节完成率 + 学生明细）
  - `GET /api/my/learning`（学生学习进度汇总）
- **权限**：教师只能维护自己的课程；学生只能给自己上报；非选课学生看不到章节；
  关联资料/作业/测验必须属于同一课程。
- **前端**：课程详情改为 5 个标签页（章节 / 教学班 / 公告 / 资料 / 讨论），
  默认「章节」；学生可开始学习、标记完成、看单任务与章节进度条；
  教师可建/改/删章节与任务点、打开「完成明细」弹窗；学生首页新增「课程学习进度」卡片。
- **演示数据**：CS101 建 3 章 7 个任务点，给前 5 名学生写入示例进度；
  启动时若已有演示库会幂等补齐（`chapters_seeded` 标记，不会反复重建）。
- **测试**：`tests/test_chapters.py` 30 项（正例 + 越权 + 非法参数 + 级联删除），
  `tests/smoke_test.py` 增加 5 项章节链路。全量 139 项通过，UI 巡检 0 控制台错误。

## 本次已完成：浏览器公网访问 + 手机端

- **手机端**：侧边栏改为抽屉（`☰` 打开、`✕` 关闭），统计卡两列、课程/章节单列、
  表格横向滚动、弹窗自适应；`scripts/mobile_sweep.py` 在 390×844 视口巡检，0 横向溢出、0 控制台错误。
- **部署**：`Dockerfile`（Node 构建前端 + Python 运行时）、`docker-compose.yml`、
  `deploy/Caddyfile`（自动 HTTPS）、`render.yaml`、`deploy/README.md`；
  `backend/config.py` 兼容平台注入的 `PORT`。
- **仍未上线**：公网网址需要用户提供服务器/域名，或直接用 GitHub Codespaces 的 8765 转发地址；
  代码侧已无阻塞。

## 待做（按优先级）

### 1. 待办中心（ROADMAP 第一批第 2 项）
- 聚合：未交作业 + 进行中签到 + 临近截止测验 + 未完成任务点
- 新接口 `GET /api/my/todos`，学生首页/侧边栏红点
- 可复用 `chapter_service.my_learning()` 的进度数据

### 2. 通知详情与跳转
- `GET /api/notifications/{id}` 返回单条 + 已读
- 前端点击通知跳到关联页面（作业 / 课程 / 签到 / 章节任务点）

### 3. 课程归档与恢复
- `PUT /api/courses/{id}` 已支持 `status: archived`
- 缺列表筛选（进行中/已归档）与恢复入口

### 4. 全量回归
```powershell
cd D:\EduFlow
$env:PYTHONPATH='D:\EduFlow'
.\.venv\Scripts\python.exe -m unittest tests.test_core
.\.venv\Scripts\python.exe tests\smoke_test.py
# 起服务后：
.\.venv\Scripts\python.exe tests\test_new_features.py 8905
.\.venv\Scripts\python.exe tests\test_edge_cases.py 8905
.\.venv\Scripts\python.exe tests\test_chapters.py 8905
.\.venv\Scripts\python.exe scripts\ui_sweep.py
```

### 5. 单文件重新生成
```powershell
.\.venv\Scripts\python.exe tools\build_single_file.py
.\.venv\Scripts\python.exe eduflow_all.py check
```

## 唯一的外部阻塞：推送到 GitHub

缺凭据（gh 被删、无 GCM、无 GH_TOKEN）。任选其一：

```powershell
winget install GitHub.cli ; gh auth login
# 或
git -c http.proxy=http://127.0.0.1:7897 push https://<TOKEN>@github.com/p54188801/ppppp.git main
```

推送前需要开代理（直连 GitHub 不通，走 `127.0.0.1:7897`）。

## 已知限制（不是 BUG）

- 位置签到依赖浏览器定位，桌面 WebView2 下可能拿不到坐标，演示优先用数字码
- 通知分页的 `total` 已修正，前端 `NotificationsView` 里"整页即认为有下一页"的兜底逻辑可简化
- 富文本目前是纯文本
- 任务点的关联作业/测验按教学班发布，课程有多个班时教师需要在任务点里选定具体那个班的内容
