# TODO

## Make container host ports configurable via `.env`

**Why:** Docker Compose currently hardcodes host-side ports (`5432`, `8080`, `8081`, `11434`). Users running other services on those ports (OpenWebUI on 8080, local Postgres on 5432, etc.) have to either stop the conflicting service or hand-edit `docker-compose.yml`. The author already uses `${VAR:-default}` syntax for other env vars, so this fits existing style.

**Change:** Wrap each host port in a `${VAR:-default}` placeholder.

In `docker-compose.yml`:
```yaml
db:
  ports: ["${DB_PORT:-5432}:5432"]
web:
  ports: ["${WEB_PORT:-8080}:8080"]
mcp:
  ports: ["${MCP_PORT:-8081}:8080"]
embedding:
  ports: ["${EMBEDDING_PORT:-11434}:11434"]
```

In `.env.example`, add a commented section:
```bash
# --- Host port overrides (optional — defaults shown) ---
# DB_PORT=5432
# WEB_PORT=8080
# MCP_PORT=8081
# EMBEDDING_PORT=11434
```

**Notes:**
- `equibles-cli` already reads `EQUIBLES_DB_URL` from env, so it follows along automatically when `DB_PORT` is remapped.
- Update README port table to mention these overrides exist.
- Consider PR upstream — small, surgical, follows existing conventions.

**Workaround until done:** Drop a `docker-compose.override.yml` with the desired host port mappings. Compose merges it automatically; no repo edits.

## Renew FINRA API credential before 2027-06-02

The local FINRA API credential (`Finra__ClientId` / `Finra__ClientSecret` in `.env`) expires **2027-06-02**. When it lapses, `FinraClient.GetAccessToken()` returns `400 (Bad Request)` and all FINRA imports (DailyShortVolume, ShortInterest) stop.

**To rotate:** create a new credential at developer.finra.org, set the Client Secret (a password you choose on their "Create API Client Secret" page), update both values in `.env`, then **`docker compose up -d worker`** — `restart` does NOT reload env vars, so it must be a recreate.
