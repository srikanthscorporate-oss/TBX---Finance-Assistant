# Local Docker Compose observability and LLM platform

This project runs Grafana, Prometheus, Loki, Tempo, OpenTelemetry Collector, PostgreSQL, Redis, ClickHouse, MinIO, and Langfuse on one Docker host.

## Start locally

1. Install and start Docker Desktop.
2. Open a terminal in this directory.
3. Generate local credentials and start the stack:

```sh
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
docker compose pull
docker compose up -d
docker compose ps
```

Open Langfuse at http://localhost and Grafana at http://grafana.localhost. Grafana's user is `admin`; its password is in `.env` under `GRAFANA_ADMIN_PASSWORD`. Create the first Langfuse user in the Langfuse UI.

## Application settings

```text
PostgreSQL: postgresql://app:${POSTGRES_PASSWORD}@postgres:5432/app
Redis:      redis://:${REDIS_PASSWORD}@redis:6379
OTLP gRPC:  otel-collector:4317
OTLP HTTP:  http://otel-collector:4318
```

All data persists in local named Docker volumes. `.env` contains generated secrets and must never be committed.

## Cloudflare routing

Nginx is the only public gateway. Configure Cloudflare Tunnel hostnames to forward to `http://nginx:80` and use these subdomains:

- `langfuse.your-domain.com` -> Langfuse
- `grafana.your-domain.com` -> Grafana
- `minio.your-domain.com` -> MinIO console

Set `LANGFUSE_NEXTAUTH_URL=https://langfuse.your-domain.com` in `.env`, add `CLOUDFLARE_TUNNEL_TOKEN`, then start the tunnel:

```sh
docker compose --profile cloudflare up -d
```

Do not proxy PostgreSQL, Redis, ClickHouse, Prometheus, Loki, Tempo, or OTLP publicly.

## Everyday commands

```sh
docker compose ps
docker compose logs -f langfuse grafana otel-collector
docker compose down
docker compose up -d
```

Use `docker compose down -v` only if you deliberately want to erase all local data.
