# 部署成公网网址

目标：任何人（包括手机）打开一个网址就能用，不需要装 Python、Node 或桌面窗口。

## 先选一条路

| 方式 | 网址 | 手机 | 适合 | 代价 |
|---|---|---|---|---|
| GitHub Codespaces | `https://<codespace>-8765.app.github.dev` | ✅ | 马上演示、答辩 | 会休眠，数据随容器删除；国内访问可能慢 |
| Docker + 云服务器 | `https://你的域名` | ✅ | 长期使用、全班访问 | 需要服务器/域名；大陆服务器要备案 |
| Render / Railway / Fly | 平台分配域名 | ✅ | 不想自己运维 | 需要持久化磁盘，免费额度有限 |
| 本机 + 内网穿透 | 临时公网域名 | ✅ | 临时给几个人看 | 电脑必须一直开机 |

> “全国所有人都能打开”指的是**公网可达**，不是“无限并发”。当前是单进程 Python + SQLite，
> 适合一个班/几个班同时用；如果真要上千人并发，需要换 PostgreSQL、多进程和对象存储。

## 方式一：Docker（推荐长期用）

服务器要求：Linux，1 核 1G 起，装好 Docker 和 Docker Compose。

```bash
git clone https://github.com/p54188801/ppppp.git
cd pppp
docker compose up -d --build
# 老版本 Docker 用：docker-compose up -d --build
```

打开：

```
http://服务器公网IP:8765
```

数据存在 Docker 命名卷 `eduflow_eduflow_data` 里，重启/升级容器不会丢（名字以 `docker volume ls` 为准）。

查看日志：

```bash
docker compose logs -f eduflow
```

升级：

```bash
git pull
docker compose up -d --build
```

### 加域名和 HTTPS（Caddy，自动证书）

1. 域名 DNS 添加 A 记录，指向服务器公网 IP
2. 安装 Caddy
3. 修改 [Caddyfile](Caddyfile) 里的域名，复制到服务器 `/etc/caddy/Caddyfile`
4. `sudo systemctl reload caddy`

Caddy 会自动申请 Let's Encrypt 证书，之后访问 `https://你的域名`。

> 大陆服务器 + 大陆域名需要 ICP 备案；不想备案可以用香港/新加坡节点，代价是国内延迟略高。

## 方式二：Render / Railway / Fly.io

仓库已带 `Dockerfile`，平台会直接构建。关键配置：

- 端口：平台注入 `PORT`，`backend/config.py` 已兼容
- 数据目录：挂载持久化磁盘到 `/data`，并设置 `EDUFLOW_DATA_DIR=/data`
- 健康检查：`/api/health`

Render 示例 `render.yaml` 已放在仓库根目录（需要付费 starter 才支持磁盘）。

## 方式三：GitHub Codespaces（最快）

1. 打开仓库 → **Code → Codespaces**
2. 等容器初始化（会自动执行 `scripts/codespace_start.sh`）
3. 底部 **Ports** 面板找到 **8765 / EduFlow Web**
4. 点地球图标，得到 `https://<codespace>-8765.app.github.dev`
5. 手机浏览器直接打开这个网址

如果没自动启动：

```bash
bash scripts/codespace_start.sh
```

## 上线前必须做

1. **改密码**：默认 `admin` / `Eduflow@2026` 是公开的，公网部署前先在「个人中心」改掉；演示账号 `t1001` / `s2001` 也建议改掉或删除。
2. **开 HTTPS**：用 Caddy/Nginx 或平台自带证书，不要长期用裸 HTTP。
3. **备份**：管理员 → 数据备份，定期下载 `.db` 快照；或备份 Docker 卷。
4. **限制端口可见性**：Codespaces 的 8765 默认 public，敏感场景改成 Private。
5. **别把 `data/` 提交到 Git**：数据库、上传文件、备份都已在 `.gitignore` 里。

## 手机端

前端已做窄屏适配：

- 侧边栏变成抽屉，左上角 `☰` 打开
- 统计卡、课程卡、章节任务点自动单列
- 表格横向滚动，弹窗宽度自适应
- 登录页本身就是响应式

手机访问同一个网址即可，不需要单独的 App 或小程序。
