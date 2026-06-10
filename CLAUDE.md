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

## Git workflow

Two remotes: `origin` = `daniel3303/Equibles` (upstream, **read-only** — no push access), `fork` = `intobigdata/Equibles` (my backup). My ~5 local commits (equibles-cli, status scripts, port/compose config) ride on top of upstream `main`.

`pull.rebase true` is set (local + global), so updating is just:

```bash
git pull                              # rebases my local commits onto upstream's latest
git push --force-with-lease fork main # back up to my fork after a pull rewrote my commits
```

- Use `--force-with-lease`, not plain `push`: a pull replays my commits with new hashes, so the fork needs the rewritten history. `--force-with-lease` is the safe force — it refuses if the fork has work I haven't seen.
- Upstream squash-merges everything, so `git branch --merged` lies about what's landed; check `gh pr list --repo daniel3303/Equibles` or grep `main`'s log instead.
