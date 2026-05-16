# equibles-cli — usage guide

A small Python CLI that queries the local Equibles ParadeDB instance directly
and emits structured JSON to stdout, optimized for consumption by local LLM
agents. It is independent of (and bypasses) the bundled MCP server.

The CLI itself lives at [`equibles-cli/`](../equibles-cli/). This document is
the user-facing reference. For implementation notes, see
[`equibles-cli/README.md`](../equibles-cli/README.md).

---

## 1. Prerequisites

- Docker + Docker Compose (for the Equibles stack itself).
- Python ≥ 3.10 with `pip`.

## 2. Start the Equibles stack

From the repository root:

```bash
docker compose up -d
```

This brings up:

| Service              | Port  | Purpose                                |
| -------------------- | ----- | -------------------------------------- |
| `equibles-db-1`      | 5432  | ParadeDB (Postgres) — the data store.  |
| `equibles-web-1`     | 8080  | Web admin / API.                       |
| `equibles-mcp-1`     | 8081  | MCP server (not used by this CLI).     |
| `equibles-worker-1`  | —     | Background scraper.                    |

The worker populates tables on its own cadence; some (FRED, CFTC, prices, FINRA)
may be empty for the first sync cycle. Run `equibles status` to see what is
populated before querying.

### Port-5432 conflict

If you already have a Postgres running locally (e.g. from another project), it
will shadow the Docker container on `localhost:5432`. Confirm with:

```bash
lsof -nP -iTCP:5432 -sTCP:LISTEN
```

Pick one workaround:

1. **Stop the local Postgres.** Homebrew: `brew services stop postgresql`.
2. **Run a sidecar proxy on an alternate host port** (no changes to
   `docker-compose.yml`):
   ```bash
   docker run -d --rm --name eq-pgproxy --network equibles_default \
     -p 5433:5432 alpine/socat \
     tcp-listen:5432,fork,reuseaddr tcp-connect:db:5432
   export EQUIBLES_DB_URL=postgresql://postgres:postgres@localhost:5433/equibles
   ```
   Stop the proxy with `docker stop eq-pgproxy`.

## 3. Install the CLI

```bash
cd equibles-cli
pip install -e .
```

That installs the `equibles` console script.

## 4. Configure

The CLI reads its connection string from `--db-url` first, then
`$EQUIBLES_DB_URL`, and finally falls back to
`postgresql://postgres:postgres@localhost:5432/equibles`.

```bash
export EQUIBLES_DB_URL="postgresql://postgres:postgres@localhost:5432/equibles"
equibles status
```

## 5. Output modes

Every subcommand accepts the same three formatting flags.

| Flag        | Behaviour                                                                                          |
| ----------- | -------------------------------------------------------------------------------------------------- |
| *(default)* | Pretty-printed JSON. Best for piping to `jq` or feeding into a script.                             |
| `--compact` | Single-line JSON with null fields stripped, keys abbreviated, numerics rounded to 2dp, dates as YYYY-MM-DD. Token-efficient for local LLMs. |
| `--human`   | GitHub-flavoured Markdown table via `tabulate`. Best for eyeballing.                               |

Every record carries provenance when the schema supports it:

```
source, source_id, source_url, as_of_date, retrieved_at
```

In default JSON these are emitted as `null` when unknown; `--compact` strips
them entirely.

## 6. Commands

`equibles --help` shows the command list. Each subcommand also has its own
`--help` with examples and option descriptions:

```bash
equibles --help
equibles insider --help
equibles filings --help
```

### 6.1 `equibles status`

Row counts and most-recent retrieval timestamp per table.

```bash
equibles status
equibles status --human
```

### 6.2 `equibles insider`

Insider transactions (SEC Form 4) for a ticker.

```bash
equibles insider --ticker NVDA --limit 10
equibles insider --ticker AAPL --since 2025-01-01 --compact
equibles insider --ticker GOOGL --human
```

| Option     | Description                       |
| ---------- | --------------------------------- |
| `--ticker` | **Required.** Stock symbol.       |
| `--since`  | Earliest transaction date.        |
| `--limit`  | Max rows to return (default 20).  |

Enum fields are decoded: `transaction_code` ("Purchase", "Sale", "Award", …),
`acquired_disposed` ("Acquired", "Disposed"), `ownership_nature` ("Direct",
"Indirect"). SEC URLs are reconstructed from CIK + accession number.

### 6.3 `equibles holdings`

Institutional holdings (Form 13F) for a ticker, ranked by reported value.

```bash
equibles holdings --ticker AAPL --top 10
equibles holdings --ticker MSFT --quarter 2025Q1 --compact
```

| Option      | Description                                                       |
| ----------- | ----------------------------------------------------------------- |
| `--ticker`  | **Required.** Stock symbol.                                       |
| `--top`     | Top N holders by value (default 10).                              |
| `--quarter` | Calendar quarter, e.g. `2025Q1`. Default: latest `ReportDate`.    |

### 6.4 `equibles congress`

Congressional / Senate stock disclosures. At least one of `--ticker` or
`--member` is required.

```bash
equibles congress --ticker AAPL
equibles congress --member Pelosi --since 2025-01-01
equibles congress --ticker NVDA --member McConnell --compact
```

| Option     | Description                                                  |
| ---------- | ------------------------------------------------------------ |
| `--ticker` | Stock symbol filter.                                         |
| `--member` | Case-insensitive substring on member name.                   |
| `--since`  | Earliest transaction date.                                   |
| `--limit`  | Max rows to return (default 50).                             |

### 6.5 `equibles filings`

SEC filings (10-K / 10-Q / 8-K) with optional content search. The `--type`
filter accepts `10-K`, `10K`, `tenk` etc. — it normalises to the database's
`TenK`/`TenQ`/`EightK` discriminator.

```bash
equibles filings --ticker NVDA --type 10-K --limit 3
equibles filings --ticker AAPL --type 8-K --search "material agreement"
equibles filings --ticker MSFT --search "revenue" --compact
```

| Option     | Description                                                                |
| ---------- | -------------------------------------------------------------------------- |
| `--ticker` | **Required.** Stock symbol.                                                |
| `--type`   | `10-K`, `10-Q`, or `8-K` (case-insensitive).                               |
| `--search` | Case-insensitive substring to look up across filing chunks (`ILIKE`).      |
| `--limit`  | Max filings to return (default 5).                                         |

When `--search` is given, only filings with matching chunks are returned, each
with up to 3 snippet excerpts attached as a `matches` array.

### 6.6 `equibles short`

FINRA short-interest, daily short volume, and SEC Reg-SHO fail-to-deliver in
one combined response. Each row carries a `kind` discriminator:
`short_interest`, `daily_short_volume`, or `fail_to_deliver`.

```bash
equibles short --ticker NVDA
equibles short --ticker AAPL --since 2025-01-01 --compact
```

### 6.7 `equibles price`

Daily OHLCV stock prices from Yahoo Finance.

```bash
equibles price --ticker NVDA --since 2025-01-01
equibles price --ticker AAPL --compact
```

`--indicators` is reserved for future technical indicators and is currently a
no-op (the CLI prints a notice and continues).

### 6.8 `equibles economy`

FRED (Federal Reserve Economic Data) indicator observations.

```bash
equibles economy --indicator FEDFUNDS
equibles economy --indicator UNRATE --since 2020-01-01 --human
equibles economy --indicator T10Y2Y --compact
```

| Option        | Description                                                |
| ------------- | ---------------------------------------------------------- |
| `--indicator` | **Required.** FRED series ID, uppercase.                   |
| `--since`     | Earliest observation date.                                 |

### 6.9 `equibles futures`

CFTC Commitments of Traders (COT) positioning. The `--contract` argument
matches either an exact `MarketCode` (e.g. `067651`) or a case-insensitive
substring of `MarketName` (e.g. `"Crude Oil"`).

```bash
equibles futures --contract "Crude Oil"
equibles futures --contract "S&P 500" --since 2025-01-01
equibles futures --contract 067651
```

### 6.10 `equibles market`

CBOE market indicators: VIX or put/call ratios.

```bash
equibles market --indicator vix --since 2025-01-01
equibles market --indicator putcall --since 2019-01-01 --compact
```

| Option        | Description                       |
| ------------- | --------------------------------- |
| `--indicator` | `vix` or `putcall` (required).    |
| `--since`     | Earliest observation date.        |

## 7. Provenance and SEC URL reconstruction

For `insider` and `holdings`, the CLI rebuilds the canonical EDGAR archive URL
from `CommonStock.Cik` (or `InstitutionalHolder.Cik`) and the accession number:

```
https://www.sec.gov/Archives/edgar/data/{cik_without_leading_zeros}/{accession_no_dashes}/
```

`filings` uses `Document.SourceUrl`, which the scraper already stores as an
EDGAR archive URL.

`congress` records have no source URL stored upstream — the field is emitted
as `null`.

## 8. Exit codes

| Code | Meaning                                          |
| ---- | ------------------------------------------------ |
| 0    | Success (possibly zero rows).                    |
| 2    | Database unreachable.                            |
| 3    | Ticker or FRED series not found.                 |
| 4    | Invalid argument combination (e.g. bad quarter). |

## 9. Common patterns

Pipe JSON through `jq`:

```bash
equibles insider --ticker NVDA --since 2025-01-01 --compact \
  | jq '.rows[] | select(.a_d == "Disposed") | {date: .txn_date, sh, px}'
```

Feed a compact dump into a local model:

```bash
equibles filings --ticker AAPL --type 10-K --search "revenue" --compact \
  | ollama run llama3.1 "Summarise the revenue commentary in this filing data:"
```

Check what tables are populated before running a long query:

```bash
equibles status --human
```

## 10. Troubleshooting

- **`ERROR: Could not connect to Equibles database`** — see §2 for the port-5432
  conflict. Confirm the stack is up: `docker compose ps`.
- **`NOTE: no <thing> found`** on stderr with an empty `rows` array — the table
  is empty or the filters returned nothing. `equibles status` shows row counts.
- **`ERROR: ticker 'XYZ' not found in CommonStock`** — the CLI suggests similar
  tickers that share the first three characters.
- **`FRED series 'X' not found`** — `FredSeries` is populated only when the
  FRED API key is configured (`Fred__ApiKey` in `.env`) and the worker has run.
