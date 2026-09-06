#!/bin/bash
# Runs once on an empty volume (docker-entrypoint-initdb.d). Renders 002_readonly_user.sql
# with the agent password from the environment and applies it as the admin user.
set -euo pipefail
[ -n "${CH_AGENT_PASSWORD:-}" ] || { echo "CH_AGENT_PASSWORD not set; agent user not created" >&2; exit 0; }
sed "s|{{TBX_CH_AGENT_PASSWORD}}|${CH_AGENT_PASSWORD}|" /docker-entrypoint-initdb.d/002_readonly_user.sql.tpl \
  | clickhouse-client --user "${CLICKHOUSE_USER}" --password "${CLICKHOUSE_PASSWORD}" --multiquery
