# Equibles

## Local ports

Host ports are set via `.env` (`WEB_PORT`/`MCP_PORT`/`DB_PORT` in `docker-compose.yml`). On this machine:

| Service | Host port | Note |
|---|---|---|
| web | **8100** | `curl localhost:8100/healthz` → `Healthy`. Compose default 8080 is taken by Open WebUI — don't probe 8080. |
| mcp | **8101** | compose default 8081 |
| db (Postgres) | **5432** | role `postgres`, db `equibles` |

## Ops notes

- **FINRA API credential expires 2027-06-02.** On lapse, `FinraClient.GetAccessToken()` returns `400` and FINRA imports stop. Rotate at developer.finra.org, update `Finra__ClientId`/`Finra__ClientSecret` in `.env`, then `docker compose up -d worker` (recreate — `restart` won't reload env vars). See `docs/TODO.md`.
