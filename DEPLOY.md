# 部署到群晖 NAS（DDNS 公网访问）

把这套「成绩 + 作业 + 档案」应用部署到群晖 NAS，常驻运行，手机/电脑在家或在外都能用。

## 访问模型一句话

- **内网**（同 WiFi）：浏览器开 `http://NAS局域网IP:8080` → **免登录**直接用。
- **外网**（在外面）：浏览器开 `https://你的域名.synology.me` → **要输密码** + 全程 HTTPS。

判定靠请求的域名：命中你配置的 `PUBLIC_HOST`（DDNS 域名）才要求登录；内网用 IP 进来不需要。路由器只把 443 转发给 NAS，8080 不对外转发，所以内网入口只在家里能到。

```
外网手机/电脑                          内网手机/电脑（同 WiFi）
  │ https://xxx.synology.me            │ http://NAS-IP:8080
  ▼                                     │
路由器 443 → NAS:443                     │
  ▼                                     │
DSM 反向代理（TLS, synology.me 证书）    │
  │ http://localhost:8080               │
  ▼                                     ▼
        Caddy 容器（发布 0.0.0.0:8080）
          ├ /api/* → backend:8000   （含 AI 聊天 SSE）
          └ /*     → frontend:3000
                     backend → /data/db.sqlite（挂载卷）
```

---

## 一、前置确认

1. 群晖型号支持 **Container Manager**（套件中心能搜到即可，绝大多数 Plus 系列都行）。
2. 安装 Docker Compose v2（命令为 `docker compose`）。官方 GHCR 镜像同时支持 `linux/amd64` 与 `linux/arm64`，NAS 无需本地编译前端。

## 二、放代码 + 数据

1. 把本项目（`成绩分析docker/` 整个目录）传到 NAS 共享文件夹，例如 `/volume1/docker/exam-tracker/`。
2. 在项目根目录下建数据目录并放入现有数据库：
   - 新建 `data/` 子目录。
   - 把 Mac 上的 `~/.exam-tracker/db.sqlite` 拷进 `data/db.sqlite`。
   - 如需保留历史导出，把 `~/.exam-tracker/homework_exports/` 一并拷进 `data/homework_exports/`。
   - 没有旧数据就跳过，应用首次启动会自动建空库。

> 小贴士：先在 Mac 上用应用里的「数据备份」生成 zip，解压后把 `db.sqlite` 放进 `data/` 最稳妥。

## 三、填密钥与密码

先复制 Compose 镜像配置：

```bash
cp compose.env.example .env
```

根目录 `.env` 默认固定 `IMAGE_TAG=2.0.1`，比 `latest` 更容易审计和回滚。然后复制 `backend/.env.example` 为 `backend/.env`，填：

```env
CHAT_PROVIDER=...            # 你现在用的（如 GLM 走 openai 兼容）
OPENAI_API_KEY=...           # 或 ANTHROPIC_API_KEY，照搬 Mac 上的 .env
OPENAI_BASE_URL=...
OPENAI_MODEL=...

APP_PASSWORD=换成你的强密码    # ← 外网登录密码，必填
PUBLIC_HOST=xxx.synology.me   # ← 你的 DDNS 域名，必填
# SESSION_SECRET 留空即可（自动生成并持久化）
```

> `backend/.env` 含密码与 key，**不要提交到任何代码仓库**（已在 .gitignore）。

## 四、首次启动（直接拉取 GHCR 镜像）

1. Container Manager → **项目** → 新增 → 选择项目根目录的 `docker-compose.yml`。
2. backend/frontend 会从公开 GHCR 直接拉取，Caddy 从 Docker Hub 拉取，不在 NAS 上编译源码。
3. 起来后，**在家**用电脑浏览器开 `http://NAS局域网IP:8080`：
   - 能看到看板、且**不需要密码** → 内网链路通。
   - 数据是你导入的那份 → 卷挂载正确。

命令行等价（SSH 到 NAS，在项目根目录）：

```bash
sudo docker compose -p grade_tracker pull
sudo docker compose -p grade_tracker up -d --remove-orphans
curl -f http://127.0.0.1:8080/api/health
sudo docker compose logs -f        # 看日志
sudo docker compose -p grade_tracker down   # 停
```

GHCR 镜像为公开包，无需 `docker login`。开发者如需包含本地源码改动，改用 `sudo docker compose -p grade_tracker up -d --build`。

## 五、DDNS + 证书（DSM）

1. **控制面板 → 外部访问 → DDNS** → 新增，服务商选 Synology，注册一个 `xxx.synology.me` 主机名（与 `.env` 里 `PUBLIC_HOST` 一致）。勾「获取 Let's Encrypt 证书」。
2. 若没自动签发：**控制面板 → 安全性 → 证书** → 新增 → 用 `xxx.synology.me` 申请。

## 六、反向代理（DSM）

**控制面板 → 登录门户 → 高级 → 反向代理 → 新增**，一条规则即可：

| 项 | 值 |
|----|----|
| 来源 协议 | HTTPS |
| 来源 主机名 | `xxx.synology.me` |
| 来源 端口 | 443 |
| 目标 协议 | HTTP |
| 目标 主机名 | `localhost` |
| 目标 端口 | `8080` |

- 「自定义标头」可加 `WebSocket`（聊天 SSE 不强制要，但加上无害）。
- 在「安全性」勾 HSTS。

## 七、路由器端口转发

把路由器（光猫/主路由）的外部 **443** 转发到 **NAS 的 443**。只开这一个端口；**8080 不要转发**。

> 家用宽带若是公网 IP 才能直连；若运营商给的是大内网 IP，DDNS 解析不到你家，需要联系运营商开公网 IP 或改用其它穿透方式。

## 八、验收

1. 内网：`http://NAS-IP:8080` → 免密、数据正确。
2. 外网：手机**关掉 WiFi 用流量**开 `https://xxx.synology.me`：
   - 浏览器锁形图标正常（HTTPS 证书有效）。
   - 出现登录页 → 输 `APP_PASSWORD` → 进入。
   - 看板 / 录入缺交 / 学生档案 / AI 聊天 / 家长会一页纸打印逐项点一遍。

---

## 日常维护

- **直接升级官方镜像**：先按下节备份，再修改根目录 `.env` 的 `IMAGE_TAG`，执行 `docker compose pull` 和 `up -d`。
- **本地改了代码**：执行 `docker compose -p grade_tracker up -d --build`，Compose 会保留同名镜像标签供本机运行。
- **数据备份**：`data/` 目录就是全部数据，纳入群晖 Hyper Backup / 快照即可；应用内「数据备份」生成的 zip 在 `data/backups/`。
- **换密码**：改 `backend/.env` 的 `APP_PASSWORD`，重启 backend 容器。

## 升级与回滚

升级不会覆盖数据库，因为 backend 的 `/data` 映射到项目目录的 `./data`。但 2.0.0 是破坏性业务升级，必须先备份：

```bash
cd /volume1/docker/exam-tracker
mkdir -p data/backups/manual
cp data/db.sqlite "data/backups/manual/db.sqlite.before-$(date +%Y%m%d-%H%M%S)"

# 拉取仓库中的最新 compose/文档；已有本地配置文件不会被覆盖
git pull --ff-only

# 编辑根目录 .env，例如 IMAGE_TAG=2.0.1
sudo docker compose -p grade_tracker pull
sudo docker compose -p grade_tracker up -d --remove-orphans
curl -f http://127.0.0.1:8080/api/health
sudo docker compose -p grade_tracker ps
```

若启动或业务验收失败：

1. 把根目录 `.env` 的 `IMAGE_TAG` 改回之前已发布的版本并重新执行 `pull`、`up -d`。
2. 若数据库需要回滚，先 `docker compose -p grade_tracker down`，再用升级前的 `db.sqlite.before-*` 覆盖 `data/db.sqlite`。
3. 2.0.x 不会主动删除旧 `TotalScore` 数据，但旧版本与 2.0.x 的业务契约不同，恢复旧镜像时应同时恢复对应时间点数据库。

## 附：离线导入镜像

NAS 无法访问 GHCR 时，可在能联网且架构相同的机器上拉取并导出：

```bash
docker pull ghcr.io/wangzuoyuan/performance-analysis-teaching-backend:2.0.1
docker pull ghcr.io/wangzuoyuan/performance-analysis-teaching-frontend:2.0.1
docker save \
  ghcr.io/wangzuoyuan/performance-analysis-teaching-backend:2.0.1 \
  ghcr.io/wangzuoyuan/performance-analysis-teaching-frontend:2.0.1 \
  -o exam-images-2.0.1.tar
# 把 exam-images.tar 传到 NAS，Container Manager → 映像 → 新增 → 从文件添加
```
