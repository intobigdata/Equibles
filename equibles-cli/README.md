# equibles-cli

A small Python CLI that queries the local [Equibles](https://github.com/daniel3303/Equibles) ParadeDB instance directly and emits structured JSON to stdout — optimized for consumption by local LLM agents.

It bypasses the bundled MCP server. Read-only, parameterized SQL via `psycopg2`.

## Install

From the repo root:

```bash
cd equibles-cli
pip install -e .
```

This exposes the `equibles` console script.

## Configuration

Connection string is read from `EQUIBLES_DB_URL` (or `--db-url`). The default is `postgresql://postgres:postgres@localhost:5432/equibles`, which matches the docker-compose default.

```bash
export EQUIBLES_DB_URL="postgresql://postgres:postgres@localhost:5432/equibles"
```

### Port-5432 conflict

If you have a local Postgres on host port 5432 (e.g. from another project), the Docker container won't be reachable on `localhost:5432`. Options:

1. **Stop the conflicting Postgres** (Homebrew: `brew services stop postgresql`).
2. **Forward Docker's DB on a different host port** via a sidecar:
   ```bash
   docker run -d --rm --name eq-pgproxy --network equibles_default \
     -p 5433:5432 alpine/socat \
     tcp-listen:5432,fork,reuseaddr tcp-connect:db:5432
   export EQUIBLES_DB_URL="postgresql://postgres:postgres@localhost:5433/equibles"
   ```
3. **Connect via the container's network IP** (fragile on macOS; not recommended).

## Output modes

| Flag        | Behaviour                                                            |
| ----------- | -------------------------------------------------------------------- |
| *(default)* | Pretty-printed JSON to stdout. Best for piping into `jq` or scripts. |
| `--compact` | Single-line JSON, null fields stripped, keys abbreviated, numerics rounded to 2dp, dates as `YYYY-MM-DD`. Token-efficient for local LLMs. |
| `--human`   | Markdown table via `tabulate`. Best for eyeballing in a terminal.    |

Every record includes provenance where the schema supports it:

```
source, source_id, source_url, as_of_date, retrieved_at
```

Missing fields are emitted as `null` rather than omitted (except in `--compact` mode, which strips them).

## Commands

```bash
equibles status                                          # row counts + latest CreationTime per table
equibles insider   --ticker NVDA [--since 2025-01-01] [--limit 20]
equibles holdings  --ticker AAPL [--top 10] [--quarter 2025Q1]
equibles congress  --ticker AAPL | --member "Pelosi" [--since 2025-01-01] [--limit 50]
equibles filings   --ticker NVDA [--type 10-K] [--search "agreement"] [--limit 5]
equibles short     --ticker AAPL [--since 2025-01-01]
equibles price     --ticker AAPL [--since 2025-01-01]
equibles economy   --indicator FEDFUNDS [--since 2020-01-01]
equibles futures   --contract "Crude Oil" [--since 2025-01-01]   # matches CFTC MarketCode or substring of MarketName
equibles market    --indicator vix|putcall [--since 2025-01-01]
```

Global flags: `--db-url`, `--human`, `--compact`. `equibles -h` shows everything.

## Examples

Latest insider sells at NVIDIA, compact for LLM consumption:

```bash
equibles insider --ticker NVDA --since 2026-01-01 --compact | jq '.rows[] | select(.a_d=="Disposed")'
```

Find 8-K passages mentioning "agreement":

```bash
equibles filings --ticker NVDA --type 8-K --search agreement --compact
```

Congressional purchases by McConnell:

```bash
equibles congress --member McConnell --compact
```

CBOE VIX history since the start of 2025, as a table:

```bash
equibles market --indicator vix --since 2025-01-01 --human
```

## SEC URL reconstruction

`insider` and `holdings` build SEC EDGAR URLs from CIK + accession number:

```
https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/
```

`filings` uses `Document.SourceUrl` directly, which already points at the SEC archive.

## Notes & limitations

- The Equibles scrapers populate different tables on different cadences. If a query returns no rows, the CLI prints `NOTE: no <thing> found...` on stderr and emits an empty `rows` array on stdout.
- The `Chunk.Content` search uses `ILIKE` for portability. The table has a ParadeDB BM25 index that this CLI does not currently use — drop in `WHERE "Id" @@@ paradedb.match('Content', %s)` if you want ranked relevance.
- Form 13F / FRED / CFTC / FINRA / Yahoo tables may be empty until the worker finishes its first sync pass.
- Read-only by design. No writes, no DDL.

## Exit codes

| Code | Meaning                                          |
| ---- | ------------------------------------------------ |
| 0    | Success (possibly zero rows).                    |
| 2    | Database unreachable.                            |
| 3    | Ticker or FRED series not found.                 |
| 4    | Invalid argument combination (e.g. bad quarter). |
