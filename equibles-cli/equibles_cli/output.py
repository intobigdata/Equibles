"""Output formatting: JSON (default), human tables, and compact JSON."""

from __future__ import annotations

import datetime as _dt
import json
import sys
from decimal import Decimal
from typing import Any, Iterable, Sequence

from tabulate import tabulate

# Enum maps mirror the C# enum definitions. Integer values come from EF Core's
# default int-to-enum mapping (declaration order, zero-based).
TRANSACTION_CODE = {
    0: "Purchase",
    1: "Sale",
    2: "Award",
    3: "Conversion",
    4: "Exercise",
    5: "TaxPayment",
    6: "Expiration",
    7: "Gift",
    8: "Inheritance",
    9: "Discretionary",
    10: "Other",
}
ACQUIRED_DISPOSED = {0: "Acquired", 1: "Disposed"}
OWNERSHIP_NATURE = {0: "Direct", 1: "Indirect"}
CONGRESS_POSITION = {0: "Representative", 1: "Senator"}
CONGRESS_TXN_TYPE = {0: "Purchase", 1: "Sale"}
SHARE_TYPE = {0: "Shares", 1: "Principal"}
OPTION_TYPE = {0: "Put", 1: "Call"}
INVESTMENT_DISCRETION = {0: "Sole", 1: "Defined", 2: "Other"}
FRED_CATEGORY = {
    0: "InterestRates",
    1: "YieldSpreads",
    2: "CorporateBondSpreads",
    3: "Inflation",
    4: "Employment",
    5: "GdpAndOutput",
    6: "MoneySupply",
    7: "Sentiment",
    8: "Housing",
    9: "ExchangeRates",
    10: "Market",
}
CFTC_CATEGORY = {
    0: "Agriculture",
    1: "Energy",
    2: "Metals",
    3: "EquityIndices",
    4: "InterestRates",
    5: "Currencies",
    6: "Other",
}
CBOE_RATIO_TYPE = {0: "Total", 1: "Equity", 2: "Index", 3: "Vix", 4: "Etp"}

# Document type aliases for user-friendly --type filtering.
DOCUMENT_TYPE_ALIASES = {
    "10-K": "TenK",
    "10K": "TenK",
    "TENK": "TenK",
    "10-Q": "TenQ",
    "10Q": "TenQ",
    "TENQ": "TenQ",
    "8-K": "EightK",
    "8K": "EightK",
    "EIGHTK": "EightK",
}


def normalize_document_type(t: str | None) -> str | None:
    if not t:
        return None
    return DOCUMENT_TYPE_ALIASES.get(t.upper(), t)


def _coerce(v: Any) -> Any:
    """Coerce psycopg2 / Python types into JSON-safe equivalents."""
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        # Keep precision as float for analytics — caller can round in compact mode.
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return None  # never emit binary content (FileContent.Bytes)
    return v


def _strip_nulls(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _round_numerics(d: dict, decimals: int = 2) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, float):
            out[k] = round(v, decimals)
        else:
            out[k] = v
    return out


def _to_yyyymmdd(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-":
            # Trim ISO timestamps "2025-01-01T..." -> "2025-01-01"
            out[k] = v[:10]
        else:
            out[k] = v
    return out


def normalize_rows(rows: Iterable[dict]) -> list[dict]:
    return [{k: _coerce(v) for k, v in r.items()} for r in rows]


def emit(
    rows: Sequence[dict],
    *,
    human: bool,
    compact: bool,
    columns: Sequence[str] | None = None,
    compact_aliases: dict[str, str] | None = None,
    meta: dict | None = None,
) -> None:
    """Emit results to stdout in the requested format."""
    if human:
        _emit_human(rows, columns=columns, meta=meta)
        return

    if compact:
        out_rows = []
        for r in rows:
            row = _to_yyyymmdd(_round_numerics(_strip_nulls(r)))
            if compact_aliases:
                row = {compact_aliases.get(k, k): v for k, v in row.items()}
            out_rows.append(row)
        payload = {"rows": out_rows, "count": len(out_rows)}
        if meta:
            payload["meta"] = {k: v for k, v in meta.items() if v is not None}
        sys.stdout.write(json.dumps(payload, separators=(",", ":"), default=str))
        sys.stdout.write("\n")
        return

    payload = {"rows": list(rows), "count": len(rows)}
    if meta:
        payload["meta"] = meta
    sys.stdout.write(json.dumps(payload, indent=2, default=str))
    sys.stdout.write("\n")


def _emit_human(
    rows: Sequence[dict],
    *,
    columns: Sequence[str] | None,
    meta: dict | None,
) -> None:
    if meta:
        for k, v in meta.items():
            if v is not None:
                sys.stdout.write(f"# {k}: {v}\n")
    if not rows:
        sys.stdout.write("(no rows)\n")
        return
    cols = list(columns) if columns else list(rows[0].keys())
    table = [[r.get(c) for c in cols] for r in rows]
    sys.stdout.write(tabulate(table, headers=cols, tablefmt="github"))
    sys.stdout.write(f"\n\n{len(rows)} row(s)\n")


def empty(meta: dict | None = None) -> None:
    """Emit an empty result with optional metadata."""
    emit([], human=False, compact=False, meta=meta)


def warn_if_empty(rows: Sequence[dict], *, what: str) -> None:
    if not rows:
        sys.stderr.write(
            f"NOTE: no {what} found. The scrapers may not have populated this table yet.\n"
        )


# ---- SEC URL builders -------------------------------------------------------


def sec_filing_url(cik: str | None, accession: str | None) -> str | None:
    """Build a stable SEC EDGAR URL from a CIK and accession number.

    Accession format: 0001199039-26-000003 -> directory uses no-dashes form.
    """
    if not cik or not accession:
        return None
    acc_nodash = accession.replace("-", "")
    cik_int = str(int(cik))  # strip leading zeros for the path segment
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/"
