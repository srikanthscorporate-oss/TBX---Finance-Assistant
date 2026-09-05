# Local Docker Compose observability and LLM platform

One Docker Compose project for Grafana, Prometheus, Loki, Tempo, OpenTelemetry Collector, MySQL, Redis, ClickHouse, MinIO, TBX, and an Nginx gateway. Stateful data is retained in local Docker volumes; TLS material is retained in the local `nginx/certs/` directory and is never committed.

## What is exposed

Nginx publishes HTTP (`80`) and HTTPS (`443`); HTTP redirects to HTTPS. MySQL additionally publishes port `3306` for explicitly authorised external database clients. The cache, telemetry, and observability services remain private to the Docker network.

| Hostname | Service |
| --- | --- |
| `grafana.your-domain.com` | Grafana |
| `minio.your-domain.com` | MinIO Console |
| `tbx-web.your-domain.com` | TBX web application (opt-in) |
| `tbx-api.your-domain.com` | TBX API (opt-in) |

MySQL is published on port `3306` for external database clients. Do not expose Redis, ClickHouse, Prometheus, Loki, Tempo, or the OTLP Collector to the public internet. Restrict port 3306 in the VM firewall to known client IP addresses whenever possible. `langfuse.your-domain.com` returns HTTP 410 because monitoring is provided by Langfuse Cloud rather than a self-hosted Langfuse container.

TBX uses the pinned AMD64-compatible `v1` Docker Hub tags: `web` serves on container port 3000 and `api` on 8000. The API diagnostic port is bound only to `127.0.0.1:18000`; public traffic is routed exclusively through Nginx. The current API `v1` image does not include `app.worker`, so the worker is held behind the `tbx-worker` profile until a worker-capable image is published.

Before the API reports healthy, provision and populate the ClickHouse `tbx_finance` schema. The API requires `tbx_finance.transactions`, `tbx_finance.vendors`, and `tbx_finance.dataset_versions`; it intentionally returns HTTP 503 until the financial dataset is loaded. Run the project’s dataset migration/loader with the ClickHouse credentials configured for this host—do not create placeholder financial data in production.

## Langfuse Cloud monitoring

The TBX API sends Langfuse traces only when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are configured in `.env`. Create a Langfuse Cloud project, then copy its host, public key, and secret key into the matching environment variables. The self-hosted Langfuse and PostgreSQL services are deliberately excluded from this stack.

## Run it locally

1. Install and start Docker Desktop.
2. Open a terminal in the `observability` directory.
3. Generate the local secret file:

```sh
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

4. Create a local development certificate. Your browser will show a certificate warning for this self-signed certificate; that is expected for local development.

```sh
mkdir -p nginx/certs
openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 365 \
  -keyout nginx/certs/privkey.pem \
  -out nginx/certs/fullchain.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:langfuse.localhost,DNS:grafana.localhost,DNS:minio.localhost"
```

5. Download and start the containers:

```sh
docker compose pull
docker compose up -d
docker compose ps
```

Open [https://localhost](https://localhost) for TBX web (when the image is configured), [https://grafana.localhost](https://grafana.localhost) for Grafana, and [https://minio.localhost](https://minio.localhost) for MinIO. Grafana's user is `admin`; its password is in `.env` under `GRAFANA_ADMIN_PASSWORD`.

## Application connection settings

Applications in this Compose network use service names, not `localhost`:

```text
MySQL:      mysql://${MYSQL_USER}:${MYSQL_PASSWORD}@mysql:3306/${MYSQL_DATABASE}
Redis:      redis://:${REDIS_PASSWORD}@redis:6379
OTLP gRPC:  otel-collector:4317
OTLP HTTP:  http://otel-collector:4318
```

`.env` contains generated passwords and secrets. Keep it private and never commit it. Docker named volumes hold database and observability data; `nginx/certs/` holds the host-local TLS certificate and key.

## Deploy behind Cloudflare (Full strict)

Use a publicly trusted certificate at the Nginx origin when Cloudflare SSL/TLS mode is **Full (strict)**. This project expects these two files on the Docker host:

```text
nginx/certs/fullchain.pem
nginx/certs/privkey.pem
```

For a VPS, create a certificate with Certbot after the DNS records point to the server. Replace `your-domain.com` and use your three subdomains:

```sh
sudo apt-get update
sudo apt-get install -y certbot
docker compose stop nginx
sudo certbot certonly --standalone \
  -d grafana.your-domain.com \
  -d minio.your-domain.com \
  -d tbx-web.your-domain.com \
  -d tbx-api.your-domain.com
sudo install -d -m 700 nginx/certs
sudo install -m 644 /etc/letsencrypt/live/grafana.your-domain.com/fullchain.pem nginx/certs/fullchain.pem
sudo install -m 600 /etc/letsencrypt/live/grafana.your-domain.com/privkey.pem nginx/certs/privkey.pem
docker compose up -d nginx
```

In Cloudflare DNS, create proxied `A`/`AAAA` records for the service hostnames. Set this value in `.env`, then restart Nginx:

```text
NGINX_ACCESS_POLICY=nginx/cloudflare-allowlist.conf
```

The local default policy permits browser access. The Cloudflare policy only permits HTTPS requests from Cloudflare's published proxy IP ranges, then passes the client IP from `CF-Connecting-IP` to the application.

After each certificate renewal, copy the refreshed certificate and key into `nginx/certs/` and restart Nginx. On the deployed Hostinger VM, Certbot hooks already do this automatically.

### Cloudflare Tunnel alternative

If you do not want to open ports 80 and 443 on the VPS, configure a Cloudflare Tunnel to forward the three hostnames to `http://nginx:80`, set `CLOUDFLARE_TUNNEL_TOKEN` in `.env`, and run:

```sh
docker compose --profile cloudflare up -d
```

## Everyday commands

```sh
docker compose ps
docker compose logs -f nginx mysql grafana otel-collector
docker compose up -d
docker compose down
```

Use `docker compose down -v` only when you deliberately want to erase all local data.
