# 后续计划（NEXT_STEPS）

> 写于 2026-10-25。当前状态与下一步都记录在这里，新会话可直接接着做。

## 当前基线

```
0ab1033  test: 新增边界与并发自测（15 项）
df23b86  feat: 补齐课程公告、全局搜索、数据备份，并修复滚动问题
```

| 项 | 值 |
|---|---|
| 仓库 | `D:\EduFlow`（唯一仓库，含完整 git 历史） |
| 接口 | 102 条 |
| 测试 | 单元 36 + 冒烟 34 + 新功能 19 + 边界 15 = 104 项全过 |
| UI 巡检 | 三角色 25 页，控制台 0 错误 |
| 单文件 | `eduflow_all.py` 与源码同步（由 `tools/build_single_file.py` 生成） |
| 工作区 | 干净 |

## 环境注意

这个月磁盘被多次整理，工具路径会变，用之前先确认：

```powershell
(Get-Command git).Source        # 最近在 D:\GIT\cmd\git.exe 和 C:\Program Files\Git\cmd\git.exe 之间变过
Get-Command node                # 当前可用：C:\Users\31775\.dsh\tools\node\node.exe
```

Python 用项目自带的：`D:\EduFlow\.venv\Scripts\python.exe`。

## 待做（按优先级）

### 1. 作业附件上传/下载
- 新接口 `POST /api/assignments/{id}/attachments`（multipart，复用 `backend/http/multipart.py`）
- 文件落 `data/uploads`，作业提交的 `attachments` 字段存文件名数组
- 下载接口要校验：任课教师 / 提交本人 / 管理员
- 前端：作业详情页支持选择文件、显示附件列表

### 2. 通知详情与跳转
- `GET /api/notifications/{id}` 返回单条 + 已读
- 前端点击通知直接跳到关联页面（作业/课程/签到）

### 3. 课程归档与恢复
- `PUT /api/courses/{id}` 已支持 `status: archived`，缺的是列表筛选与恢复入口

### 4. 全量回归
```powershell
cd D:\EduFlow
$env:PYTHONPATH='D:\EduFlow'
.\.venv\Scripts\python.exe -m unittest tests.test_core
.\.venv\Scripts\python.exe tests\smoke_test.py
# 起服务后：
.\.venv\Scripts\python.exe tests\test_new_features.py 8905
.\.venv\Scripts\python.exe tests\test_edge_cases.py 8905
.\.venv\Scripts\python.exe scripts\ui_sweep.py
```

### 5. 单文件重新生成
```powershell
.\.venv\Scripts\python.exe tools\build_single_file.py
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
