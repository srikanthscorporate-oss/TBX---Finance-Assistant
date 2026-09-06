#!/usr/bin/env bash
# Usage: ./scripts/deploy.sh user@vps-host [remote-dir]
# Needs Docker Compose on the VPS and a Cloudflare Tunnel token in the remote .env.
set -euo pipefail

TARGET="${1:?usage: scripts/deploy.sh user@host [remote-dir]}"
REMOTE_DIR="${2:-/opt/tbx}"
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"

echo "==> deploying ${TAG} to ${TARGET}:${REMOTE_DIR}"

# .env stays on the server.
ssh "$TARGET" "mkdir -p ${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude 'apps/api/.venv' \
  --exclude 'node_modules' --exclude '.next' \
  --exclude '.env' --exclude 'evaluation/results' \
  ./ "${TARGET}:${REMOTE_DIR}/"

# Images are tagged with the commit; roll back with IMAGE_TAG=<old-sha> docker compose up -d.
ssh "$TARGET" bash -s <<REMOTE
set -euo pipefail
cd "${REMOTE_DIR}"

if [ ! -f .env ]; then
  echo "FATAL: ${REMOTE_DIR}/.env is missing. Copy .env.example and fill it in." >&2
  exit 1
fi

export IMAGE_TAG="${TAG}"
docker compose build api web
docker compose up -d clickhouse mysql redis
timeout 120 bash -c 'until docker compose ps clickhouse | grep -q healthy; do sleep 3; done'

rows=\$(docker compose exec -T clickhouse clickhouse-client \
        --user "\${CH_ADMIN_USER}" --password "\${CH_ADMIN_PASSWORD}" \
        --query "SELECT count() FROM tbx_finance.transactions" 2>/dev/null || echo 0)
if [ "\${rows:-0}" -eq 0 ]; then
  echo "==> loading dataset"
  docker compose run --rm --entrypoint python api scripts/load_dataset.py \
    --url "http://clickhouse:8123" \
    --user "\${CH_ADMIN_USER}" --password "\${CH_ADMIN_PASSWORD}"
else
  echo "==> dataset already loaded (\${rows} transactions)"
fi

docker compose --profile prod up -d
REMOTE

echo "==> waiting for health"
for i in $(seq 1 30); do
  if ssh "$TARGET" "cd ${REMOTE_DIR} && docker compose exec -T nginx wget -qO- http://127.0.0.1/health" \
       | grep -q '"ready":true'; then
    echo "==> healthy"
    ssh "$TARGET" "cd ${REMOTE_DIR} && docker compose ps"
    echo "==> deployed ${TAG}"
    exit 0
  fi
  sleep 4
done

echo "FATAL: health check never passed. Recent logs:" >&2
ssh "$TARGET" "cd ${REMOTE_DIR} && docker compose logs --tail 60 api nginx" >&2
exit 1
