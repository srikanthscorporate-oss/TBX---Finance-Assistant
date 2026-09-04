#!/usr/bin/env sh
set -eu

stack_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="$stack_dir/.env"
langfuse_url=${1:-http://localhost:3001}

if [ -e "$env_file" ]; then
  echo "Refusing to overwrite existing $env_file" >&2
  exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to generate secrets." >&2
  exit 1
fi

secret() { openssl rand -hex "$1"; }

umask 077
{
  printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$(secret 32)"
  printf 'POSTGRES_PASSWORD=%s\n' "$(secret 32)"
  printf 'REDIS_PASSWORD=%s\n' "$(secret 32)"
  printf 'CLICKHOUSE_USER=langfuse\n'
  printf 'CLICKHOUSE_PASSWORD=%s\n' "$(secret 32)"
  printf 'MINIO_ROOT_USER=minioadmin\n'
  printf 'MINIO_ROOT_PASSWORD=%s\n' "$(secret 32)"
  printf 'LANGFUSE_NEXTAUTH_URL=%s\n' "$langfuse_url"
  printf 'LANGFUSE_SALT=%s\n' "$(secret 32)"
  printf 'LANGFUSE_ENCRYPTION_KEY=%s\n' "$(secret 32)"
  printf 'LANGFUSE_NEXTAUTH_SECRET=%s\n' "$(secret 32)"
} > "$env_file"

echo "Created $env_file with owner-only permissions."
echo "Start the stack with: cd $stack_dir && docker compose up -d"
