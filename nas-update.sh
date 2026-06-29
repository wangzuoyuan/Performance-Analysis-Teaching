#!/bin/sh
# 群晖 NAS 一键更新：拉取 GitHub 最新代码 → 重建容器 → 重启 caddy → 健康检查。
#
# 用法（在 NAS 上，普通用户即可，docker 步骤会自动 sudo 提权，按提示输密码）：
#   sh /volume1/docker/成绩分析docker/nas-update.sh
# 或先 chmod +x 后：
#   /volume1/docker/成绩分析docker/nas-update.sh
#
# 前提：该目录已是本仓库的 git 检出（origin=GitHub，分支 main）。

set -e

PROJECT_DIR="/volume1/docker/成绩分析docker"
PROJECT_NAME="grade_tracker"
DOCKER="/usr/local/bin/docker"

cd "$PROJECT_DIR"

echo "==> [1/4] 拉取最新代码 (git pull)"
# 透明代理环境下强制 HTTP/1.1，否则 git over HTTP/2 会无限挂死
git config http.version HTTP/1.1
git pull --ff-only origin main

echo "==> [2/4] 重建并启动容器（需 sudo，docker 守护进程要 root）"
sudo "$DOCKER" compose -p "$PROJECT_NAME" up -d --build

echo "==> [3/4] 重启 caddy（让它重新解析到新前端容器）"
sudo "$DOCKER" compose -p "$PROJECT_NAME" restart caddy

echo "==> [4/4] 健康检查"
sleep 3
if sudo "$DOCKER" exec "${PROJECT_NAME}-caddy-1" wget -qO- http://localhost:8080/api/health >/dev/null 2>&1; then
  echo "✅ 更新完成，服务健康。外网访问 https://meng5638.asuscomm.com:9500"
else
  echo "⚠️ 健康检查未通过，请查看容器日志：sudo $DOCKER compose -p $PROJECT_NAME logs --tail 50"
  exit 1
fi
