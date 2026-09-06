#!/usr/bin/env bash
# Usage:
#   ./start.sh            start (installs Docker if missing, loads data if empty)
#   ./start.sh --prod     also start the Cloudflare tunnel (needs CLOUDFLARE_TUNNEL_TOKEN)
#   ./start.sh --stop     stop the local api/web processes and the docker services (volumes kept)
#   ./start.sh --logs     follow the local api + web logs
#
# The API (uvicorn) and the web app (Next.js) run as local processes; Redis, the
# optional local MySQL copy and nginx run in Docker. nginx on :8080 proxies to them.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$(pwd)"
MODE="${1:-start}"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

OS="unknown"
case "$(uname -s)" in
  Linux*)
    if grep -qi microsoft /proc/version 2>/dev/null; then OS="wsl"; else OS="linux"; fi ;;
  Darwin*)  OS="mac" ;;
  MINGW*|MSYS*|CYGWIN*) OS="gitbash" ;;
esac
ARCH="$(uname -m)"
say "platform: $OS ($ARCH)"

SUDO=""
if [ "$OS" = "linux" ] || [ "$OS" = "wsl" ]; then
  [ "$(id -u)" -eq 0 ] || SUDO="sudo"
fi

install_docker() {
  case "$OS" in
    linux|wsl)
      say "installing Docker Engine + Compose plugin (official convenience script)"
      have curl || { $SUDO apt-get update -qq && $SUDO apt-get install -y -qq curl ca-certificates git; }
      curl -fsSL https://get.docker.com | $SUDO sh
      if [ -n "$SUDO" ]; then
        $SUDO usermod -aG docker "$USER" || true
        warn "added $USER to the docker group; log out and back in (or run: newgrp docker) if 'docker ps' is denied"
      fi
      $SUDO systemctl enable --now docker 2>/dev/null || $SUDO service docker start 2>/dev/null || true
      ;;
    mac)
      if ! have brew; then
        say "installing Homebrew"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
      fi
      say "installing Docker Desktop via Homebrew"
      brew install --cask docker
      ;;
    gitbash)
      if have winget; then
        say "installing Docker Desktop via winget"
        winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements || true
      fi
      die "Docker Desktop must be installed and running on Windows. Start it, then re-run this script from Git Bash or WSL."
      ;;
    *) die "unsupported platform; install Docker manually and re-run" ;;
  esac
}

if ! have docker; then install_docker; fi
have docker || die "docker not found after install; open a new shell and re-run"

if ! docker info >/dev/null 2>&1; then
  case "$OS" in
    mac)     say "starting Docker Desktop"; open -a Docker ;;
    gitbash) say "starting Docker Desktop"; ( "/c/Program Files/Docker/Docker/Docker Desktop.exe" >/dev/null 2>&1 & ) || true ;;
    linux|wsl) $SUDO systemctl start docker 2>/dev/null || $SUDO service docker start 2>/dev/null || true ;;
  esac
  say "waiting for the Docker daemon"
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 3; done
  docker info >/dev/null 2>&1 || die "Docker daemon is not reachable"
fi
docker compose version >/dev/null 2>&1 || die "the Docker Compose plugin is missing (docker compose version)"

case "$MODE" in
  --stop)
    say "stopping local api/web and docker services (volumes kept)"
    for f in .run/api.pid .run/web.pid; do
      [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null && rm -f "$f"
    done
    docker compose --profile prod --profile local-mysql stop; exit 0 ;;
  --logs) exec tail -f .run/api.log .run/web.log ;;
  --prod|start) ;;
  *) die "unknown option: $MODE (use --prod, --stop, --logs)" ;;
esac

if [ ! -f .env ]; then
  cp .env.example .env
  say "created .env from .env.example"
fi
if ! grep -qE '^GROQ_API_KEY=.+' .env; then
  if ! grep -qE '^TBX_USE_STUB_LLM=1' .env; then
    printf '\n# No model key present: run the offline planner so the demo still works.\nTBX_USE_STUB_LLM=1\n' >> .env
  fi
  warn "GROQ_API_KEY is empty in .env; running with the offline stub planner. Add the key and re-run to use a real model."
fi
if [ "$MODE" = "--prod" ] && ! grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=.+' .env; then
  die "--prod needs CLOUDFLARE_TUNNEL_TOKEN in .env"
fi

# Git Bash mounts need Windows-style paths without MSYS path mangling.
if [ "$OS" = "gitbash" ]; then
  export MSYS_NO_PATHCONV=1
  HOSTROOT="$(pwd -W)"
else
  HOSTROOT="$ROOT"
fi

say "starting Redis"
docker compose up -d redis

# The assistant answers live from the MySQL endpoint in .env (MYSQL_*); nothing is
# loaded locally. Check it is reachable before building so a bad endpoint fails fast.
MYSQL_HOST_V="$(grep -E '^MYSQL_HOST=' .env | cut -d= -f2)"; MYSQL_PORT_V="$(grep -E '^MYSQL_PORT=' .env | cut -d= -f2)"
[ -n "$MYSQL_HOST_V" ] || die "MYSQL_HOST missing from .env; the assistant needs a live MySQL source"
if [ "$MYSQL_HOST_V" = "mysql" ]; then
  say "starting the local MySQL copy"
  docker compose --profile local-mysql up -d mysql
  for _ in $(seq 1 60); do
    docker compose exec -T mysql mysqladmin ping -h127.0.0.1 --silent 2>/dev/null && break
    sleep 2
  done
elif command -v nc >/dev/null 2>&1; then
  say "checking the MySQL source at ${MYSQL_HOST_V}:${MYSQL_PORT_V:-3306}"
  nc -z -w 5 "$MYSQL_HOST_V" "${MYSQL_PORT_V:-3306}" || die "MySQL source ${MYSQL_HOST_V}:${MYSQL_PORT_V:-3306} is not reachable"
fi

say "starting nginx"
docker compose up -d nginx
if [ "$MODE" = "--prod" ]; then
  say "starting the Cloudflare tunnel"
  docker compose --profile prod up -d cloudflared
fi

# ---- local processes -------------------------------------------------------
mkdir -p .run
set -a; . ./.env; set +a
export REDIS_URL="redis://127.0.0.1:16379/0"
# The compose MySQL is published on the loopback for host processes.
if [ "$MYSQL_HOST" = "mysql" ]; then export MYSQL_HOST=127.0.0.1 MYSQL_PORT=13306; fi

say "starting the API on :8010 (uv)"
command -v uv >/dev/null 2>&1 || die "uv is required: https://docs.astral.sh/uv/"
( cd apps/api && uv sync -q && \
  nohup uv run uvicorn app.main:app --host 127.0.0.1 --port 8010 > ../../.run/api.log 2>&1 &
  echo $! > ../../.run/api.pid )

say "starting the web app on :3000 (npm)"
command -v npm >/dev/null 2>&1 || die "npm is required"
( cd apps/web && [ -d node_modules ] || npm ci --silent
  if [ "$MODE" = "--prod" ]; then npm run build --silent; WEB_CMD="npm run start"; else WEB_CMD="npm run dev"; fi
  INTERNAL_API_BASE=http://127.0.0.1:8010 API_PROXY_TARGET=http://127.0.0.1:8010 \
    nohup sh -c "$WEB_CMD" > ../../.run/web.log 2>&1 &
  echo $! > ../../.run/web.pid )

say "waiting for the API"
for _ in $(seq 1 60); do
  curl -sf http://127.0.0.1:8010/health 2>/dev/null | grep -q '"ready":true' && break
  sleep 2
done
curl -sf http://127.0.0.1:8010/health 2>/dev/null | grep -q '"ready":true' || {
  tail -40 .run/api.log; die "the API never reported ready"; }

docker compose ps --format 'table {{.Service}}\t{{.Status}}'
say "ready"
echo "   chat:           http://localhost:8080"
echo "   observability:  http://localhost:8080/observability"
[ "$MODE" = "--prod" ] && echo "   production:     https://$(grep -E '^TBX_DOMAIN=' .env | cut -d= -f2)"
echo "   api (local):    http://127.0.0.1:8010    web (local): http://localhost:3000"
echo "   stop:           ./start.sh --stop     logs: ./start.sh --logs"
