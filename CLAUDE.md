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

### Contributing a fix upstream

Fork-PR flow (CLA already signed). **Branch off `origin/main`, not local `main`** — local `main` carries my personal commits that must not enter the PR: `git stash` → `git checkout -b fix/... origin/main` → `git stash pop` → commit → `git push -u fork <branch>` → `gh pr create --repo daniel3303/Equibles --base main --head intobigdata:<branch>`.

⚠️ **Run `dotnet csharpier format .` before pushing** (`dotnet tool restore` first if needed) — CI's `lint` job runs `csharpier check` tree-wide and fails the PR on any unformatted C#.

## Open upstream PRs (check status later)

Track with `gh pr view <#> --repo daniel3303/Equibles --json state,mergeable` and `gh pr checks <#> --repo daniel3303/Equibles`.

- **PR #3620** (issue #3619) — `fix(financial-facts)`: exclude dimensional XBRL facts from consolidated statement reads. The web Financials tab + MCP statement tools could non-deterministically show a segment value (e.g. iPhone revenue) in place of the consolidated total once the XBRL dimensional-facts worker populates rows. Opened 2026-06-10, CLA passed, mergeable, CI running. When merged: `git pull` brings it home; the fix only matters after a `docker compose up --build` deploys the dimensional-facts feature it guards.
- **PR #3290** (issue #3288) — FINRA short-volume CommonStock FK guard. ✅ MERGED 2026-06-03.
