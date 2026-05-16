"""equibles-cli — query the local Equibles ParadeDB instance from the shell."""

from __future__ import annotations

import sys

import click

from . import queries
from .db import cursor
from .output import (
    emit,
    normalize_document_type,
    normalize_rows,
    warn_if_empty,
)

_FORMAT_OPTIONS = [
    click.option(
        "--db-url",
        default=None,
        metavar="URL",
        help="Postgres URL. Falls back to $EQUIBLES_DB_URL, then "
        "postgresql://postgres:postgres@localhost:5432/equibles.",
    ),
    click.option(
        "--human",
        is_flag=True,
        help="Render as a Markdown table (good for terminals). Default is JSON.",
    ),
    click.option(
        "--compact",
        is_flag=True,
        help="Single-line JSON with null fields stripped, keys abbreviated, "
        "numerics rounded to 2dp, dates as YYYY-MM-DD. Token-efficient for LLMs.",
    ),
]


def _format_options(f):
    for opt in reversed(_FORMAT_OPTIONS):
        f = opt(f)
    return f


def _resolve_ticker_or_exit(cur, ticker: str) -> dict:
    stock = queries.resolve_ticker(cur, ticker)
    if stock:
        return stock
    similar = queries.similar_tickers(cur, ticker)
    msg = f"ERROR: ticker {ticker!r} not found in CommonStock."
    if similar:
        suggestions = ", ".join(
            f"{s['Ticker']} ({s['Name']})" for s in similar if s["Ticker"]
        )
        msg += f"\n  Did you mean: {suggestions}"
    sys.stderr.write(msg + "\n")
    sys.exit(3)


GROUP_EPILOG = """\
\b
Quick start:
  docker compose up -d                              # from the Equibles repo root
  export EQUIBLES_DB_URL=postgresql://postgres:postgres@localhost:5432/equibles
  equibles status                                   # confirm tables and row counts

\b
Output modes (apply to every subcommand):
  (default)   pretty-printed JSON to stdout
  --compact   single-line JSON, null fields stripped, keys abbreviated
  --human     Markdown table

\b
Provenance fields (when supported by the schema):
  source, source_id, source_url, as_of_date, retrieved_at

\b
Exit codes:
  0  success (possibly zero rows)
  2  database unreachable
  3  ticker / FRED series not found
  4  invalid argument combination

Full docs: docs/README-cli.md
"""


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=GROUP_EPILOG,
)
@click.version_option(package_name="equibles-cli")
def main() -> None:
    """Query the local Equibles ParadeDB. Outputs structured JSON for LLM agents."""


# ---- insider ---------------------------------------------------------------


INSIDER_HELP = """\
Insider transactions (Form 4) for a ticker.

\b
Returns Acquired/Disposed events with the insider name, role flags,
transaction code, share count, price, and an SEC EDGAR URL reconstructed
from the accession number.

\b
Examples:
  equibles insider --ticker NVDA --limit 10
  equibles insider --ticker AAPL --since 2025-01-01 --compact
  equibles insider --ticker GOOGL --human
"""


@main.command(help=INSIDER_HELP)
@click.option(
    "--ticker", required=True, metavar="SYMBOL", help="Stock ticker, e.g. AAPL."
)
@click.option(
    "--since", default=None, metavar="YYYY-MM-DD", help="Earliest transaction date."
)
@click.option(
    "--limit", default=20, show_default=True, type=int, help="Max rows to return."
)
@_format_options
def insider(
    ticker: str,
    since: str | None,
    limit: int,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    with cursor(db_url) as cur:
        stock = _resolve_ticker_or_exit(cur, ticker)
        rows = queries.insider(cur, ticker, since, limit)
    warn_if_empty(rows, what="insider transactions")
    aliases = {
        "transaction_date": "txn_date",
        "filing_date": "filed",
        "transaction_code": "code",
        "acquired_disposed": "a_d",
        "ownership_nature": "own",
        "price_per_share": "px",
        "shares": "sh",
        "shares_owned_after": "sh_after",
        "security_title": "sec",
        "accession_number": "acc",
        "is_amendment": "amend",
        "insider_name": "insider",
        "officer_title": "title",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={"ticker": stock["Ticker"], "name": stock["Name"], "cik": stock["Cik"]},
    )


# ---- holdings --------------------------------------------------------------


HOLDINGS_HELP = """\
Institutional holdings (Form 13F) for a ticker.

\b
Ranks holders by reported dollar value. Without --quarter, returns rows from
the most recent ReportDate present in the table.

\b
Examples:
  equibles holdings --ticker AAPL --top 10
  equibles holdings --ticker MSFT --quarter 2025Q1 --compact
"""


@main.command(help=HOLDINGS_HELP)
@click.option(
    "--ticker", required=True, metavar="SYMBOL", help="Stock ticker, e.g. AAPL."
)
@click.option(
    "--top",
    default=10,
    show_default=True,
    type=int,
    help="Top N holders ranked by reported value.",
)
@click.option(
    "--quarter",
    default=None,
    metavar="YYYYQn",
    help="Calendar quarter to filter by (e.g. 2025Q1). Default: latest ReportDate.",
)
@_format_options
def holdings(
    ticker: str,
    top: int,
    quarter: str | None,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    with cursor(db_url) as cur:
        stock = _resolve_ticker_or_exit(cur, ticker)
        try:
            rows = queries.holdings(cur, ticker, top, quarter)
        except ValueError as e:
            click.echo(f"ERROR: {e}", err=True)
            sys.exit(4)
    warn_if_empty(rows, what="institutional holdings")
    aliases = {
        "report_date": "as_of",
        "filing_date": "filed",
        "value": "val",
        "shares": "sh",
        "share_type": "stype",
        "option_type": "opt",
        "investment_discretion": "discr",
        "voting_auth_sole": "vts",
        "voting_auth_shared": "vtshr",
        "voting_auth_none": "vtn",
        "accession_number": "acc",
        "is_amendment": "amend",
        "holder_name": "holder",
        "holder_cik": "h_cik",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={"ticker": stock["Ticker"], "name": stock["Name"], "quarter": quarter},
    )


# ---- congress --------------------------------------------------------------


CONGRESS_HELP = """\
Congressional / Senate stock disclosures.

\b
At least one of --ticker or --member is required.

\b
Examples:
  equibles congress --ticker AAPL
  equibles congress --member Pelosi --since 2025-01-01
  equibles congress --ticker NVDA --member McConnell --compact
"""


@main.command(help=CONGRESS_HELP)
@click.option("--ticker", default=None, metavar="SYMBOL", help="Stock ticker filter.")
@click.option(
    "--member",
    default=None,
    metavar="NAME",
    help="Substring (case-insensitive) match on member name.",
)
@click.option(
    "--since", default=None, metavar="YYYY-MM-DD", help="Earliest transaction date."
)
@click.option(
    "--limit", default=50, show_default=True, type=int, help="Max rows to return."
)
@_format_options
def congress(
    ticker: str | None,
    member: str | None,
    since: str | None,
    limit: int,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    if not ticker and not member:
        click.echo("ERROR: provide --ticker or --member (or both).", err=True)
        sys.exit(4)
    with cursor(db_url) as cur:
        if ticker:
            _resolve_ticker_or_exit(cur, ticker)
        rows = queries.congress(cur, ticker, member, since, limit)
    warn_if_empty(rows, what="congressional trades")
    aliases = {
        "transaction_date": "txn_date",
        "filing_date": "filed",
        "transaction_type": "type",
        "owner_type": "owner",
        "asset_name": "asset",
        "amount_from": "amt_from",
        "amount_to": "amt_to",
        "position": "pos",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={"ticker": ticker.upper() if ticker else None, "member_filter": member},
    )


# ---- filings ---------------------------------------------------------------


FILINGS_HELP = """\
SEC filings (10-K / 10-Q / 8-K) for a ticker, with optional content search.

\b
--search filters to filings whose body contains the substring (ILIKE) and
attaches up to 3 matching snippets per filing under "matches".

\b
Examples:
  equibles filings --ticker NVDA --type 10-K --limit 3
  equibles filings --ticker AAPL --type 8-K --search "material agreement"
  equibles filings --ticker MSFT --search "revenue" --compact
"""


@main.command(help=FILINGS_HELP)
@click.option(
    "--ticker", required=True, metavar="SYMBOL", help="Stock ticker, e.g. AAPL."
)
@click.option(
    "--type",
    "doc_type",
    default=None,
    metavar="FORM",
    help='Filing form: "10-K", "10-Q", or "8-K" (case-insensitive).',
)
@click.option(
    "--search",
    default=None,
    metavar="TEXT",
    help="Case-insensitive substring to look up across filing chunks.",
)
@click.option(
    "--limit", default=5, show_default=True, type=int, help="Max filings to return."
)
@_format_options
def filings(
    ticker: str,
    doc_type: str | None,
    search: str | None,
    limit: int,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    normalized = normalize_document_type(doc_type)
    with cursor(db_url) as cur:
        stock = _resolve_ticker_or_exit(cur, ticker)
        rows = queries.filings(cur, ticker, normalized, search, limit)
    warn_if_empty(rows, what="filings")
    aliases = {
        "document_type": "type",
        "reporting_date": "report_date",
        "reporting_for_date": "for_date",
        "line_count": "lines",
        "source_url": "url",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        columns=[
            "ticker",
            "document_type",
            "reporting_date",
            "reporting_for_date",
            "line_count",
            "source_url",
        ],
        meta={
            "ticker": stock["Ticker"],
            "name": stock["Name"],
            "type_filter": normalized,
            "search": search,
        },
    )


# ---- short -----------------------------------------------------------------


SHORT_HELP = """\
FINRA short-interest, daily short volume, and SEC fail-to-deliver records.

\b
Each row has a "kind" field: "short_interest" (bimonthly),
"daily_short_volume" (daily), or "fail_to_deliver" (daily settlement).

\b
Examples:
  equibles short --ticker NVDA
  equibles short --ticker AAPL --since 2025-01-01 --compact
"""


@main.command(help=SHORT_HELP)
@click.option(
    "--ticker", required=True, metavar="SYMBOL", help="Stock ticker, e.g. AAPL."
)
@click.option(
    "--since", default=None, metavar="YYYY-MM-DD", help="Earliest date to include."
)
@_format_options
def short(
    ticker: str,
    since: str | None,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    with cursor(db_url) as cur:
        stock = _resolve_ticker_or_exit(cur, ticker)
        rows = queries.short(cur, ticker, since)
    warn_if_empty(rows, what="short data")
    aliases = {
        "as_of_date": "date",
        "current_short_position": "cur_short",
        "previous_short_position": "prev_short",
        "change_in_short_position": "chg_short",
        "average_daily_volume": "adv",
        "days_to_cover": "dtc",
        "short_volume": "short_vol",
        "short_exempt_volume": "exempt_vol",
        "total_volume": "vol",
        "quantity": "qty",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={"ticker": stock["Ticker"], "name": stock["Name"]},
    )


# ---- price -----------------------------------------------------------------


PRICE_HELP = """\
Daily OHLCV stock prices from Yahoo Finance.

\b
Examples:
  equibles price --ticker NVDA --since 2025-01-01
  equibles price --ticker AAPL --compact
"""


@main.command(help=PRICE_HELP)
@click.option(
    "--ticker", required=True, metavar="SYMBOL", help="Stock ticker, e.g. AAPL."
)
@click.option(
    "--since", default=None, metavar="YYYY-MM-DD", help="Earliest date to include."
)
@click.option(
    "--indicators",
    is_flag=True,
    help="Reserved flag for future technical indicators. Currently a no-op.",
)
@_format_options
def price(
    ticker: str,
    since: str | None,
    indicators: bool,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    if indicators:
        sys.stderr.write(
            "NOTE: --indicators not implemented in this build; ignoring.\n"
        )
    with cursor(db_url) as cur:
        stock = _resolve_ticker_or_exit(cur, ticker)
        rows = queries.price(cur, ticker, since)
    warn_if_empty(rows, what="daily prices")
    aliases = {
        "as_of_date": "date",
        "adjusted_close": "adj_close",
        "volume": "vol",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={"ticker": stock["Ticker"], "name": stock["Name"]},
    )


# ---- economy ---------------------------------------------------------------


ECONOMY_HELP = """\
FRED (Federal Reserve Economic Data) indicator observations.

\b
--indicator takes a FRED series ID (uppercase).

\b
Examples:
  equibles economy --indicator FEDFUNDS
  equibles economy --indicator UNRATE --since 2020-01-01 --human
  equibles economy --indicator T10Y2Y --compact
"""


@main.command(help=ECONOMY_HELP)
@click.option(
    "--indicator",
    required=True,
    metavar="SERIES_ID",
    help='FRED series ID, e.g. "FEDFUNDS", "UNRATE", "T10Y2Y".',
)
@click.option(
    "--since", default=None, metavar="YYYY-MM-DD", help="Earliest observation date."
)
@_format_options
def economy(
    indicator: str,
    since: str | None,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    with cursor(db_url) as cur:
        series = queries.economy_series(cur, indicator)
        if not series:
            sys.stderr.write(
                f"ERROR: FRED series {indicator!r} not found. "
                "Note: FredSeries may not be populated yet.\n"
            )
            sys.exit(3)
        rows = queries.economy(cur, indicator, since)
    warn_if_empty(rows, what="FRED observations")
    aliases = {"as_of_date": "date", "value": "v"}
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={
            "series_id": series["SeriesId"],
            "title": series["Title"],
            "units": series["Units"],
            "frequency": series["Frequency"],
        },
    )


# ---- futures ---------------------------------------------------------------


FUTURES_HELP = """\
CFTC Commitments of Traders (COT) positioning.

\b
--contract matches either the CFTC MarketCode exactly OR a case-insensitive
substring of MarketName (e.g. "Crude Oil", "Live Cattle").

\b
Examples:
  equibles futures --contract "Crude Oil"
  equibles futures --contract 067651              # MarketCode
  equibles futures --contract "S&P 500" --since 2025-01-01
"""


@main.command(help=FUTURES_HELP)
@click.option(
    "--contract",
    required=True,
    metavar="CODE_OR_NAME",
    help="CFTC MarketCode (exact) or substring of MarketName.",
)
@click.option(
    "--since", default=None, metavar="YYYY-MM-DD", help="Earliest report date."
)
@_format_options
def futures(
    contract: str,
    since: str | None,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    with cursor(db_url) as cur:
        rows = queries.futures(cur, contract, since)
    warn_if_empty(rows, what="CFTC position reports")
    aliases = {
        "as_of_date": "date",
        "market_code": "code",
        "market_name": "name",
        "open_interest": "oi",
        "non_comm_long": "ncl",
        "non_comm_short": "ncs",
        "comm_long": "cl",
        "comm_short": "cs",
        "pct_non_comm_long": "pct_ncl",
        "pct_non_comm_short": "pct_ncs",
        "pct_comm_long": "pct_cl",
        "pct_comm_short": "pct_cs",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={"contract_filter": contract},
    )


# ---- market ----------------------------------------------------------------


MARKET_HELP = """\
CBOE market indicators: VIX or put/call ratios.

\b
Examples:
  equibles market --indicator vix --since 2025-01-01
  equibles market --indicator putcall --since 2019-01-01 --compact
"""


@main.command(help=MARKET_HELP)
@click.option(
    "--indicator",
    required=True,
    type=click.Choice(["vix", "putcall"], case_sensitive=False),
    help="Which CBOE indicator to query.",
)
@click.option(
    "--since", default=None, metavar="YYYY-MM-DD", help="Earliest observation date."
)
@_format_options
def market(
    indicator: str,
    since: str | None,
    db_url: str | None,
    human: bool,
    compact: bool,
) -> None:
    with cursor(db_url) as cur:
        if indicator.lower() == "vix":
            rows = queries.market_vix(cur, since)
        else:
            rows = queries.market_putcall(cur, since)
    warn_if_empty(rows, what="CBOE market data")
    aliases = {
        "as_of_date": "date",
        "put_call_ratio": "pcr",
        "call_volume": "cv",
        "put_volume": "pv",
        "total_volume": "tv",
    }
    emit(
        normalize_rows(rows),
        human=human,
        compact=compact,
        compact_aliases=aliases,
        meta={"indicator": indicator.lower()},
    )


# ---- status ----------------------------------------------------------------


STATUS_HELP = """\
Show table row counts and the most recent retrieval timestamp per table.

\b
Useful for confirming the scrapers have populated the database and for
spotting stale tables before running a query.

\b
Example:
  equibles status --human
"""


@main.command(help=STATUS_HELP)
@_format_options
def status(db_url: str | None, human: bool, compact: bool) -> None:
    with cursor(db_url) as cur:
        rows = queries.status(cur)
    emit(normalize_rows(rows), human=human, compact=compact, meta=None)


if __name__ == "__main__":
    main()
