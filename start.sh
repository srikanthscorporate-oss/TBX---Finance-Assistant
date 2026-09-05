#!/usr/bin/env bash
# Usage:
#   ./start.sh            start (installs Docker if missing, loads data if empty)
#   ./start.sh --prod     also start the Cloudflare tunnel (needs CLOUDFLARE_TUNNEL_TOKEN)
#   ./start.sh --stop     stop all services (data volumes are kept)
#   ./start.sh --logs     follow api + web logs
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
  --stop) say "stopping services (volumes kept)"; docker compose --profile prod stop; exit 0 ;;
  --logs) exec docker compose logs -f api web ;;
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

say "starting ClickHouse, MySQL, Redis"
docker compose up -d clickhouse mysql redis
say "waiting for ClickHouse"
for _ in $(seq 1 60); do
  docker compose exec -T clickhouse wget -qO- http://127.0.0.1:8123/ping 2>/dev/null | grep -q Ok && break
  sleep 3
done
docker compose exec -T clickhouse wget -qO- http://127.0.0.1:8123/ping 2>/dev/null | grep -q Ok || die "ClickHouse did not become healthy"

# Dataset scripts run in a container on the compose network; the host needs no Python.
NET="$(docker network ls --format '{{.Name}}' | grep -E '_data$' | head -1)"
PYRUN() { docker run --rm --network "$NET" -e TBX_DATA_KEY -v "${HOSTROOT}:/w" -w /w python:3.12-slim sh -c 'pip install -q "cryptography>=43" >/dev/null && exec python "$@"' -- "$@"; }

if [ ! -f data/raw/transaction.csv ]; then
  say "no dataset in data/raw; generating a stand-in"
  PYRUN scripts/generate_bank_dataset.py --out data/raw
fi
CH_USER="$(grep -E '^CH_ADMIN_USER=' .env | cut -d= -f2)"; CH_PASS="$(grep -E '^CH_ADMIN_PASSWORD=' .env | cut -d= -f2)"
ROWS="$(docker compose exec -T clickhouse clickhouse-client --user "${CH_USER:-tbx_admin}" --password "${CH_PASS:-change-me-admin}" -q 'SELECT count() FROM tbx_finance.transaction' 2>/dev/null || echo 0)"
if [ "${ROWS:-0}" -eq 0 ]; then
  say "loading the dataset into ClickHouse"
  DATA_KEY="$(grep -E '^TBX_DATA_KEY=' .env | cut -d= -f2)"
  [ -n "$DATA_KEY" ] || die "TBX_DATA_KEY missing from .env; generate one with: python3 -c 'import os;print(os.urandom(32).hex())'"
  TBX_DATA_KEY="$DATA_KEY" PYRUN scripts/load_dataset.py --raw data/raw --url http://clickhouse:8123 --user "${CH_USER:-tbx_admin}" --password "${CH_PASS:-change-me-admin}"
else
  say "dataset already loaded (${ROWS} transactions)"
fi

say "building and starting api, web, nginx"
docker compose up -d --build api web nginx
if [ "$MODE" = "--prod" ]; then
  say "starting the Cloudflare tunnel"
  docker compose --profile prod up -d cloudflared
fi

say "waiting for the API"
for _ in $(seq 1 60); do
  docker compose exec -T nginx wget -qO- http://127.0.0.1/health 2>/dev/null | grep -q '"ready":true' && break
  sleep 3
done
docker compose exec -T nginx wget -qO- http://127.0.0.1/health 2>/dev/null | grep -q '"ready":true' || {
  docker compose logs --tail 40 api; die "the API never reported ready"; }

docker compose ps --format 'table {{.Service}}\t{{.Status}}'
say "ready"
echo "   chat:           http://localhost:8080"
echo "   observability:  http://localhost:8080/observability"
[ "$MODE" = "--prod" ] && echo "   production:     https://$(grep -E '^TBX_DOMAIN=' .env | cut -d= -f2)"
echo "   stop:           ./start.sh --stop     logs: ./start.sh --logs"
