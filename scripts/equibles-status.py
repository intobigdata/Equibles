#!/usr/bin/env python3
"""Equibles data-pipeline status monitor.

Shows row counts + most-recent timestamp for every source table, plus a delta
vs. the previous refresh and a rollup of recent errors. Refreshes on an
interval until Ctrl-C.

Usage:
    scripts/equibles-status.py              # refresh every 10s
    scripts/equibles-status.py -i 5         # refresh every 5s
    scripts/equibles-status.py --once       # print once and exit
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("/tmp/equibles-status.prev.json")

# CommonStock has no CreationTime; everything else does.
COUNTS_SQL = """
SELECT 'SEC: CommonStock'           AS source, COUNT(*)::text AS rows, '-' AS latest FROM "CommonStock"
UNION ALL SELECT 'SEC: Document (10-K/Q/8-K)',  COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "Document"
UNION ALL SELECT 'SEC: InsiderTransaction',     COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "InsiderTransaction"
UNION ALL SELECT 'SEC: InsiderOwner',           COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "InsiderOwner"
UNION ALL SELECT 'SEC: FailToDeliver',          COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "FailToDeliver"
UNION ALL SELECT 'Yahoo: DailyStockPrice',      COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "DailyStockPrice"
UNION ALL SELECT 'CBOE: VixDaily',              COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "CboeVixDaily"
UNION ALL SELECT 'CBOE: PutCallRatio',          COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "CboePutCallRatio"
UNION ALL SELECT 'FINRA: DailyShortVolume',     COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "DailyShortVolume"
UNION ALL SELECT 'FINRA: ShortInterest',        COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "ShortInterest"
UNION ALL SELECT 'FRED: Series',                COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "FredSeries"
UNION ALL SELECT 'FRED: Observation',           COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "FredObservation"
UNION ALL SELECT 'CFTC: PositionReport',        COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "CftcPositionReport"
UNION ALL SELECT 'Congress: Trade',             COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "CongressionalTrade"
UNION ALL SELECT 'Holdings: Institutional',     COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "InstitutionalHolding"
ORDER BY source;
"""

ERRORS_SQL = """
SELECT "Source",
       COUNT(*) FILTER (WHERE "CreationTime" > NOW() - INTERVAL '5 minutes') AS last_5min,
       COUNT(*) FILTER (WHERE "CreationTime" > NOW() - INTERVAL '1 hour')    AS last_1h,
       COUNT(*)                                                              AS total,
       COALESCE(MAX("CreationTime")::timestamp(0)::text, '-')                AS latest
FROM "Errors"
GROUP BY "Source"
ORDER BY total DESC;
"""

# ANSI: dim, green, red, reset
DIM, GREEN, RED, RESET = "\033[2m", "\033[32m", "\033[31m", "\033[0m"


def run_psql(sql: str) -> list[list[str]]:
    """Run SQL via docker compose exec and return parsed TSV rows."""
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "db",
            "psql", "-U", "postgres", "-d", "equibles",
            "-A", "-t", "-F", "\t", "-c", sql,
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"psql error: {result.stderr.strip()}", file=sys.stderr)
        return []
    return [line.split("\t") for line in result.stdout.strip().splitlines() if line]


def fmt_int(n: int) -> str:
    return f"{n:,}"


def fmt_delta(current: int, previous: int | None) -> str:
    if previous is None:
        return f"{DIM}-{RESET}"
    delta = current - previous
    if delta == 0:
        return ""
    if delta > 0:
        return f"{GREEN}+{delta:,}{RESET}"
    return f"{RED}{delta:,}{RESET}"


def load_state() -> dict[str, int]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(counts: dict[str, int]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(counts))
    except OSError:
        pass


def render(prev: dict[str, int]) -> dict[str, int]:
    print("\033[H\033[2J\033[3J", end="")  # clear screen + scrollback
    print(f"Equibles status — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print()
    print("── Row counts " + "─" * 60)

    counts_rows = run_psql(COUNTS_SQL)
    current: dict[str, int] = {}

    header = f"  {'Source':<32} {'Rows':>14} {'Change':>16} {'Latest':<22}"
    print(header)
    print("  " + "─" * (len(header) - 2))

    for row in counts_rows:
        if len(row) < 3:
            continue
        source, rows_str, latest = row[0], row[1], row[2]
        try:
            n = int(rows_str)
        except ValueError:
            continue
        current[source] = n
        delta_str = fmt_delta(n, prev.get(source))
        # Account for ANSI escapes in width calculation.
        pad = 16 + (len(delta_str) - len(_strip_ansi(delta_str)))
        print(f"  {source:<32} {fmt_int(n):>14} {delta_str:>{pad}} {latest:<22}")

    print()
    print("── Errors by source " + "─" * 54)

    err_rows = run_psql(ERRORS_SQL)
    if not err_rows:
        print(f"  {DIM}(no errors recorded){RESET}")
    else:
        eheader = f"  {'Source':<24} {'5min':>8} {'1h':>8} {'Total':>10} {'Latest':<22}"
        print(eheader)
        print("  " + "─" * (len(eheader) - 2))
        for row in err_rows:
            if len(row) < 5:
                continue
            src, m5, h1, total, latest = row[0], row[1], row[2], row[3], row[4]
            try:
                m5_i, h1_i, total_i = int(m5), int(h1), int(total)
            except ValueError:
                continue
            # Highlight recent errors in red.
            m5_str = f"{RED}{m5_i:,}{RESET}" if m5_i > 0 else "0"
            m5_pad = 8 + (len(m5_str) - len(_strip_ansi(m5_str)))
            print(f"  {src:<24} {m5_str:>{m5_pad}} {h1_i:>8,} {total_i:>10,} {latest:<22}")

    return current


def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*m", "", s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--interval", type=int, default=10, help="Refresh interval in seconds (default: 10)")
    ap.add_argument("--once", action="store_true", help="Print once and exit")
    args = ap.parse_args()

    prev = load_state()

    try:
        while True:
            current = render(prev)
            save_state(current)
            prev = current
            if args.once:
                return 0
            print()
            print(f"{DIM}Refreshing every {args.interval}s. Ctrl-C to stop.{RESET}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
