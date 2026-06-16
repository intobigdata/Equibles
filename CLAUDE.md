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
- **Web tabs clamp history to `Worker__MinSyncDate` (default `2020-01-01`).** Upstream PRs #3638/#3639/#3640 (merged 2026-06-10) made the price, short-data, holdings, insider, and congressional tabs hide anything *displayed* before the configured minimum sync date. ⚠️ **This is display-only — the data is still in the DB.** So if a stock's web history looks like it starts in 2020 but you know we ingested deeper (SEC docs back to ~2000, the pre-2002 dot-com archive, etc.), that's the clamp, not missing data. To surface the full depth in the UI, set `Worker__MinSyncDate=2000-01-01` in `.env` and recreate web (`docker compose up -d web`). MCP/DB reads are **not** clamped — only the web tabs.
- **XBRL dimensional-facts backfill is forced ON locally** via `XbrlCapture__BackfillEnabled=true` in `.env` (2026-06-11). Upstream #3622 defaults it OFF (their historical sweep drained); this machine never ran the sweep, so it's on to populate `FinancialFactDimension` for the back-catalogue (powers MCP `GetRevenueBreakdown`). Once it drains here (every doc `Captured`/`NotPresent`, cycle selects 0), it's safe to flip back off and recreate the worker. **Drained 2026-06-16 at ~48.7M `FinancialFactDimension` rows** (DB now ~359 GB). Note: while the backfill + a 13F parser-bump reconciliation run concurrently, the SEC `DocumentProcessorWorker` chunking query can hit Postgres read timeouts (`TimeoutException: Timeout during reading attempt` in `DocumentManager.ChunkDocumentBatch`) — **load contention, non-fatal, self-retries**; clears once the grind drains. Not a regression.
- **Stealth browser enabled locally** (2026-06-16) for the IR-discovery + FDA-calendar scrapers (upstream stealth work #3700-3705/#3716/#3719). Enabled by setting `InvestorRelationsDiscovery__StealthFetch__SidecarUrl=http://cloakbrowser:9222` in `.env` on the **main worker** + running the sidecar with `docker compose --profile stealth up -d cloakbrowser`. ⚠️ Deliberately **not** using the compose `worker-stealth` profile service — it's a *second* worker that would run alongside `worker` and double-process every timer-based scraper. Caveats: CloakBrowser image is `linux/amd64` so it runs under **emulation** on this arm64 Mac (works, slower); it's an opaque 3rd-party binary kept isolated (internal-only `:9222`, pinned by digest). Disable: remove the `.env` line, `docker compose up -d worker`, then `docker compose --profile stealth down`.

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

- **PR #3620** (issue #3619) — `fix(financial-facts)`: exclude dimensional XBRL facts from consolidated statement reads. The web Financials tab + MCP statement tools could non-deterministically show a segment value (e.g. iPhone revenue) in place of the consolidated total once the XBRL dimensional-facts worker populates rows. ✅ MERGED 2026-06-10 as `f6929c8d` (squash). The feature it guards is now live upstream too (#3614 XbrlFactExtractionService, #3615 envelope sweep, #3621 GetRevenueBreakdown). `git pull` brings the fix home; it only takes effect after a `docker compose up --build` deploys the dimensional-facts pipeline.
- **PR #3290** (issue #3288) — FINRA short-volume CommonStock FK guard. ✅ MERGED 2026-06-03.
