# Docker Compose

## Development

```bash
docker compose --env-file .env.development -f docker-compose.yml -f docker-compose.dev.yml up --build
````

Run in the background:

```bash
docker compose --env-file .env.development -f docker-compose.yml -f docker-compose.dev.yml up --build -d
```

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## Production

```bash
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml up --build
```

Run in the background:

```bash
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```
