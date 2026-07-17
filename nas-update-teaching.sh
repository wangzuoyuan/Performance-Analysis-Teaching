#!/bin/sh
# Synology NAS update script for the performance_teaching deployment on port 8081.

set -eu

PROJECT_DIR="/volume1/docker/performance-analysis-teaching"
PROJECT_NAME="performance_teaching"
COMPOSE_FILE="docker-compose.nas.yml"
DOCKER="/usr/local/bin/docker"
DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="$DATA_DIR/backups/updates"

cd "$PROJECT_DIR"

echo "==> [1/5] Backup current database"
if [ -f "$DATA_DIR/db.sqlite" ]; then
  mkdir -p "$BACKUP_DIR"
  stamp=$(date +%Y%m%d-%H%M%S)
  cp -p "$DATA_DIR/db.sqlite" "$BACKUP_DIR/db.sqlite.before-update-$stamp"
  echo "    $BACKUP_DIR/db.sqlite.before-update-$stamp"
else
  echo "    No existing database; skipping backup"
fi

echo "==> [2/5] Pull latest code"
git config http.version HTTP/1.1
git pull --ff-only origin main

echo "==> [3/5] Build and update containers"
sudo "$DOCKER" compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d --build --remove-orphans

echo "==> [4/5] Recreate proxy with current service addresses"
sudo "$DOCKER" compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d --force-recreate --no-deps caddy

echo "==> [5/5] Health check"
attempt=1
while [ "$attempt" -le 12 ]; do
  if env \
    http_proxy= https_proxy= HTTP_PROXY= HTTPS_PROXY= \
    no_proxy=127.0.0.1,localhost NO_PROXY=127.0.0.1,localhost \
    wget -qO- -T 10 -t 1 http://127.0.0.1:8081/api/health 2>/dev/null \
    | grep -q '"ok":true'; then
    echo "Update complete: http://192.168.50.78:8081"
    exit 0
  fi
  sleep 5
  attempt=$((attempt + 1))
done

echo "Health check failed. Inspect logs with:"
echo "sudo $DOCKER compose -f $PROJECT_DIR/$COMPOSE_FILE -p $PROJECT_NAME logs --tail 100"
exit 1
