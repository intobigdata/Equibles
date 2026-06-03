#!/usr/bin/env bash
# Equibles data-pipeline status monitor.
#
# Shows row counts + most-recent timestamp for every source table, plus a
# rollup of recent errors by source. Refreshes on an interval until Ctrl-C.
#
# Usage:
#   scripts/equibles-status.sh              # refresh every 10s
#   scripts/equibles-status.sh -i 5         # refresh every 5s
#   scripts/equibles-status.sh --once       # print once and exit
#   scripts/equibles-status.sh -i 30 --once # print once with custom interval (ignored)

set -euo pipefail

INTERVAL=10
ONCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--interval) INTERVAL="$2"; shift 2 ;;
    --once)        ONCE=1; shift ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# SQL: per-table row count + most recent CreationTime (or NULL if table has no
# such column). Using a fixed list lets us label rows by data source, not
# table name, which is friendlier for skimming.
read -r -d '' COUNTS_SQL <<'SQL' || true
-- CommonStock has no CreationTime column; everything else does.
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
UNION ALL SELECT 'Holdings: Institutional',     COUNT(*)::text, COALESCE(MAX("CreationTime")::timestamp(0)::text, '-') FROM "InstitutionalHolding";
SQL

read -r -d '' ERRORS_SQL <<'SQL' || true
SELECT "Source",
       COUNT(*) FILTER (WHERE "CreationTime" > NOW() - INTERVAL '5 minutes') AS last_5min,
       COUNT(*) FILTER (WHERE "CreationTime" > NOW() - INTERVAL '1 hour')    AS last_1h,
       COUNT(*)                                                              AS total,
       MAX("CreationTime")::timestamp(0)                                     AS latest
FROM "Errors"
GROUP BY "Source"
ORDER BY total DESC;
SQL

render() {
  clear
  echo "Equibles status — $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  echo "── Row counts ──────────────────────────────────────────────"
  docker compose exec -T db psql -U postgres -d equibles -c "$COUNTS_SQL" 2>&1
  echo "── Errors by source ────────────────────────────────────────"
  docker compose exec -T db psql -U postgres -d equibles -c "$ERRORS_SQL" 2>&1
}

if [[ "$ONCE" -eq 1 ]]; then
  render
  exit 0
fi

trap 'echo; echo "Stopped."; exit 0' INT
while :; do
  render
  echo
  echo "Refreshing every ${INTERVAL}s. Ctrl-C to stop."
  sleep "$INTERVAL"
done
