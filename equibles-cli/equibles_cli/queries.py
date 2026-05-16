"""Parameterized SQL queries for each domain command.

All queries return dicts shaped for downstream provenance enrichment.
"""

from __future__ import annotations

from typing import Any

from .output import (
    ACQUIRED_DISPOSED,
    CBOE_RATIO_TYPE,
    CFTC_CATEGORY,
    CONGRESS_POSITION,
    CONGRESS_TXN_TYPE,
    FRED_CATEGORY,
    INVESTMENT_DISCRETION,
    OPTION_TYPE,
    OWNERSHIP_NATURE,
    SHARE_TYPE,
    TRANSACTION_CODE,
    sec_filing_url,
)


def resolve_ticker(cur, ticker: str) -> dict | None:
    cur.execute(
        'SELECT "Id"::text, "Ticker", "Name", "Cik", "Cusip" '
        'FROM "CommonStock" WHERE "Ticker" = %s',
        (ticker.upper(),),
    )
    return cur.fetchone()


def similar_tickers(cur, ticker: str, limit: int = 5) -> list[dict]:
    cur.execute(
        'SELECT "Ticker", "Name" FROM "CommonStock" '
        'WHERE "Ticker" ILIKE %s ORDER BY "Ticker" LIMIT %s',
        (f"{ticker[:3]}%", limit),
    )
    return cur.fetchall()


# ---- insider ---------------------------------------------------------------


def insider(cur, ticker: str, since: str | None, limit: int) -> list[dict]:
    sql = """
        SELECT
            it."Id"::text AS id,
            cs."Ticker" AS ticker,
            cs."Cik" AS cik,
            io."Name" AS insider_name,
            io."OfficerTitle" AS officer_title,
            io."IsDirector" AS is_director,
            io."IsOfficer" AS is_officer,
            io."IsTenPercentOwner" AS is_ten_percent_owner,
            it."TransactionDate" AS transaction_date,
            it."FilingDate" AS filing_date,
            it."TransactionCode" AS transaction_code,
            it."AcquiredDisposed" AS acquired_disposed,
            it."OwnershipNature" AS ownership_nature,
            it."Shares" AS shares,
            it."PricePerShare" AS price_per_share,
            it."SharesOwnedAfter" AS shares_owned_after,
            it."SecurityTitle" AS security_title,
            it."AccessionNumber" AS accession_number,
            it."IsAmendment" AS is_amendment,
            it."CreationTime" AS retrieved_at
        FROM "InsiderTransaction" it
        JOIN "InsiderOwner" io ON io."Id" = it."InsiderOwnerId"
        JOIN "CommonStock" cs ON cs."Id" = it."CommonStockId"
        WHERE cs."Ticker" = %s
    """
    params: list[Any] = [ticker.upper()]
    if since:
        sql += ' AND it."TransactionDate" >= %s'
        params.append(since)
    sql += ' ORDER BY it."TransactionDate" DESC, it."TransactionOrder" ASC LIMIT %s'
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["transaction_code"] = TRANSACTION_CODE.get(
            r["transaction_code"], r["transaction_code"]
        )
        r["acquired_disposed"] = ACQUIRED_DISPOSED.get(
            r["acquired_disposed"], r["acquired_disposed"]
        )
        r["ownership_nature"] = OWNERSHIP_NATURE.get(
            r["ownership_nature"], r["ownership_nature"]
        )
        r["source"] = "SEC EDGAR"
        r["source_id"] = r["accession_number"]
        r["source_url"] = sec_filing_url(r["cik"], r["accession_number"])
        r["as_of_date"] = r["transaction_date"]
    return rows


# ---- holdings --------------------------------------------------------------


def holdings(cur, ticker: str, top: int, quarter: str | None) -> list[dict]:
    """Latest institutional holdings for a ticker, ranked by Value.

    If quarter (e.g. '2025Q1') is provided, filter by the calendar-quarter
    ReportDate matching it. Otherwise, return the most recent ReportDate's rows.
    """
    params: list[Any] = [ticker.upper()]
    quarter_clause = ""
    if quarter:
        start, end = _quarter_bounds(quarter)
        quarter_clause = ' AND ih."ReportDate" >= %s AND ih."ReportDate" < %s'
        params.extend([start, end])
    else:
        quarter_clause = (
            ' AND ih."ReportDate" = ('
            '  SELECT MAX("ReportDate") FROM "InstitutionalHolding" ih2 '
            '  WHERE ih2."CommonStockId" = ih."CommonStockId"'
            " )"
        )

    sql = f"""
        SELECT
            ih."Id"::text AS id,
            cs."Ticker" AS ticker,
            cs."Cik" AS issuer_cik,
            ih_holder."Name" AS holder_name,
            ih_holder."Cik" AS holder_cik,
            ih."ReportDate" AS report_date,
            ih."FilingDate" AS filing_date,
            ih."Value" AS value,
            ih."Shares" AS shares,
            ih."ShareType" AS share_type,
            ih."OptionType" AS option_type,
            ih."InvestmentDiscretion" AS investment_discretion,
            ih."VotingAuthSole" AS voting_auth_sole,
            ih."VotingAuthShared" AS voting_auth_shared,
            ih."VotingAuthNone" AS voting_auth_none,
            ih."AccessionNumber" AS accession_number,
            ih."IsAmendment" AS is_amendment,
            ih."CreationTime" AS retrieved_at
        FROM "InstitutionalHolding" ih
        JOIN "InstitutionalHolder" ih_holder ON ih_holder."Id" = ih."InstitutionalHolderId"
        JOIN "CommonStock" cs ON cs."Id" = ih."CommonStockId"
        WHERE cs."Ticker" = %s {quarter_clause}
        ORDER BY ih."Value" DESC NULLS LAST
        LIMIT %s
    """
    params.append(top)
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["share_type"] = SHARE_TYPE.get(r["share_type"], r["share_type"])
        r["option_type"] = OPTION_TYPE.get(r["option_type"], r["option_type"])
        r["investment_discretion"] = INVESTMENT_DISCRETION.get(
            r["investment_discretion"], r["investment_discretion"]
        )
        r["source"] = "SEC EDGAR (13F)"
        r["source_id"] = r["accession_number"]
        r["source_url"] = sec_filing_url(r["holder_cik"], r["accession_number"])
        r["as_of_date"] = r["report_date"]
    return rows


def _quarter_bounds(quarter: str) -> tuple[str, str]:
    """Parse '2025Q1' / '2025q1' / '2025-Q1' to (start_date, end_date_exclusive)."""
    q = quarter.upper().replace("-", "")
    if "Q" not in q:
        raise ValueError(f"Unrecognized quarter format: {quarter}")
    year_s, q_s = q.split("Q", 1)
    year = int(year_s)
    qn = int(q_s)
    if qn not in (1, 2, 3, 4):
        raise ValueError(f"Quarter must be 1-4: {quarter}")
    month = (qn - 1) * 3 + 1
    start = f"{year:04d}-{month:02d}-01"
    if qn == 4:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 3:02d}-01"
    return start, end


# ---- congress --------------------------------------------------------------


def congress(
    cur,
    ticker: str | None,
    member: str | None,
    since: str | None,
    limit: int,
) -> list[dict]:
    sql = """
        SELECT
            ct."Id"::text AS id,
            cs."Ticker" AS ticker,
            cm."Name" AS member,
            cm."Position" AS position,
            ct."TransactionDate" AS transaction_date,
            ct."FilingDate" AS filing_date,
            ct."TransactionType" AS transaction_type,
            ct."OwnerType" AS owner_type,
            ct."AssetName" AS asset_name,
            ct."AmountFrom" AS amount_from,
            ct."AmountTo" AS amount_to,
            ct."CreationTime" AS retrieved_at
        FROM "CongressionalTrade" ct
        JOIN "CongressMember" cm ON cm."Id" = ct."CongressMemberId"
        JOIN "CommonStock" cs ON cs."Id" = ct."CommonStockId"
        WHERE 1=1
    """
    params: list[Any] = []
    if ticker:
        sql += ' AND cs."Ticker" = %s'
        params.append(ticker.upper())
    if member:
        sql += ' AND cm."Name" ILIKE %s'
        params.append(f"%{member}%")
    if since:
        sql += ' AND ct."TransactionDate" >= %s'
        params.append(since)
    sql += ' ORDER BY ct."TransactionDate" DESC LIMIT %s'
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["position"] = CONGRESS_POSITION.get(r["position"], r["position"])
        r["transaction_type"] = CONGRESS_TXN_TYPE.get(
            r["transaction_type"], r["transaction_type"]
        )
        r["source"] = "House/Senate Disclosures"
        r["source_id"] = None
        r["source_url"] = None
        r["as_of_date"] = r["transaction_date"]
    return rows


# ---- filings ---------------------------------------------------------------


def filings(
    cur,
    ticker: str,
    doc_type: str | None,
    search: str | None,
    limit: int,
) -> list[dict]:
    sql = """
        SELECT
            d."Id"::text AS id,
            cs."Ticker" AS ticker,
            cs."Cik" AS cik,
            d."DocumentType" AS document_type,
            d."ReportingDate" AS reporting_date,
            d."ReportingForDate" AS reporting_for_date,
            d."LineCount" AS line_count,
            d."SourceUrl" AS source_url,
            d."CreationTime" AS retrieved_at
        FROM "Document" d
        JOIN "CommonStock" cs ON cs."Id" = d."CommonStockId"
        WHERE cs."Ticker" = %s
    """
    params: list[Any] = [ticker.upper()]
    if doc_type:
        sql += ' AND d."DocumentType" = %s'
        params.append(doc_type)
    sql += ' ORDER BY d."ReportingDate" DESC LIMIT %s'
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()

    # If a search term is given, look up matching chunks per document for snippets.
    if search:
        rows = _attach_search_snippets(cur, rows, search)

    for r in rows:
        r["source"] = "SEC EDGAR"
        r["source_id"] = (
            None  # accession not stored on Document; SourceUrl is canonical
        )
        r["as_of_date"] = r["reporting_date"]
    return rows


def _attach_search_snippets(cur, rows: list[dict], query: str) -> list[dict]:
    """For each row, attach up to 3 matching Chunk snippets (ILIKE-based for portability).

    Drops rows that have no matches when a search term is supplied.
    """
    out = []
    for r in rows:
        cur.execute(
            'SELECT "Index", "StartLineNumber", LEFT("Content", 280) AS snippet '
            'FROM "Chunk" '
            'WHERE "DocumentId" = %s AND "Content" ILIKE %s '
            'ORDER BY "Index" LIMIT 3',
            (r["id"], f"%{query}%"),
        )
        hits = cur.fetchall()
        if hits:
            r["matches"] = [
                {
                    "index": h["Index"],
                    "line": h["StartLineNumber"],
                    "snippet": (h["snippet"] or "").strip(),
                }
                for h in hits
            ]
            out.append(r)
    return out


# ---- short -----------------------------------------------------------------


def short(cur, ticker: str, since: str | None) -> list[dict]:
    """Combined short-interest + daily-short-volume + fail-to-deliver, ordered by date desc."""
    params_base: list[Any] = [ticker.upper()]
    si_clause = ""
    dsv_clause = ""
    ftd_clause = ""
    if since:
        si_clause = ' AND si."SettlementDate" >= %s'
        dsv_clause = ' AND dsv."Date" >= %s'
        ftd_clause = ' AND ftd."SettlementDate" >= %s'

    # Short interest (bimonthly)
    si_params: list[Any] = list(params_base) + ([since] if since else [])
    cur.execute(
        f"""
        SELECT
            'short_interest' AS kind,
            si."SettlementDate" AS as_of_date,
            si."CurrentShortPosition" AS current_short_position,
            si."PreviousShortPosition" AS previous_short_position,
            si."ChangeInShortPosition" AS change_in_short_position,
            si."AverageDailyVolume" AS average_daily_volume,
            si."DaysToCover" AS days_to_cover,
            si."CreationTime" AS retrieved_at
        FROM "ShortInterest" si
        JOIN "CommonStock" cs ON cs."Id" = si."CommonStockId"
        WHERE cs."Ticker" = %s {si_clause}
        ORDER BY si."SettlementDate" DESC
        """,
        si_params,
    )
    si_rows = [
        {**r, "source": "FINRA", "source_id": None, "source_url": None}
        for r in cur.fetchall()
    ]

    # Daily short volume
    dsv_params: list[Any] = list(params_base) + ([since] if since else [])
    cur.execute(
        f"""
        SELECT
            'daily_short_volume' AS kind,
            dsv."Date" AS as_of_date,
            dsv."ShortVolume" AS short_volume,
            dsv."ShortExemptVolume" AS short_exempt_volume,
            dsv."TotalVolume" AS total_volume,
            dsv."Market" AS market,
            dsv."CreationTime" AS retrieved_at
        FROM "DailyShortVolume" dsv
        JOIN "CommonStock" cs ON cs."Id" = dsv."CommonStockId"
        WHERE cs."Ticker" = %s {dsv_clause}
        ORDER BY dsv."Date" DESC
        """,
        dsv_params,
    )
    dsv_rows = [
        {**r, "source": "FINRA", "source_id": None, "source_url": None}
        for r in cur.fetchall()
    ]

    # Fail-to-deliver
    ftd_params: list[Any] = list(params_base) + ([since] if since else [])
    cur.execute(
        f"""
        SELECT
            'fail_to_deliver' AS kind,
            ftd."SettlementDate" AS as_of_date,
            ftd."Quantity" AS quantity,
            ftd."Price" AS price,
            ftd."CreationTime" AS retrieved_at
        FROM "FailToDeliver" ftd
        JOIN "CommonStock" cs ON cs."Id" = ftd."CommonStockId"
        WHERE cs."Ticker" = %s {ftd_clause}
        ORDER BY ftd."SettlementDate" DESC
        """,
        ftd_params,
    )
    ftd_rows = [
        {**r, "source": "SEC (Reg SHO)", "source_id": None, "source_url": None}
        for r in cur.fetchall()
    ]

    return si_rows + dsv_rows + ftd_rows


# ---- price -----------------------------------------------------------------


def price(cur, ticker: str, since: str | None) -> list[dict]:
    sql = """
        SELECT
            dsp."Date" AS as_of_date,
            dsp."Open" AS open,
            dsp."High" AS high,
            dsp."Low" AS low,
            dsp."Close" AS close,
            dsp."AdjustedClose" AS adjusted_close,
            dsp."Volume" AS volume,
            dsp."CreationTime" AS retrieved_at
        FROM "DailyStockPrice" dsp
        JOIN "CommonStock" cs ON cs."Id" = dsp."CommonStockId"
        WHERE cs."Ticker" = %s
    """
    params: list[Any] = [ticker.upper()]
    if since:
        sql += ' AND dsp."Date" >= %s'
        params.append(since)
    sql += ' ORDER BY dsp."Date" DESC'
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["source"] = "Yahoo Finance"
        r["source_id"] = None
        r["source_url"] = None
    return rows


# ---- economy ---------------------------------------------------------------


def economy_series(cur, indicator: str) -> dict | None:
    cur.execute(
        'SELECT "Id"::text, "SeriesId", "Title", "Category", "Frequency", "Units", '
        '"SeasonalAdjustment", "ObservationStart", "ObservationEnd", "LastUpdated" '
        'FROM "FredSeries" WHERE "SeriesId" = %s',
        (indicator.upper(),),
    )
    row = cur.fetchone()
    if row:
        row["Category"] = FRED_CATEGORY.get(row["Category"], row["Category"])
    return row


def economy(cur, indicator: str, since: str | None) -> list[dict]:
    sql = """
        SELECT
            fs."SeriesId" AS series_id,
            fs."Title" AS title,
            fs."Units" AS units,
            fs."Category" AS category,
            fo."Date" AS as_of_date,
            fo."Value" AS value,
            fo."CreationTime" AS retrieved_at
        FROM "FredObservation" fo
        JOIN "FredSeries" fs ON fs."Id" = fo."FredSeriesId"
        WHERE fs."SeriesId" = %s
    """
    params: list[Any] = [indicator.upper()]
    if since:
        sql += ' AND fo."Date" >= %s'
        params.append(since)
    sql += ' ORDER BY fo."Date" DESC'
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["category"] = FRED_CATEGORY.get(r["category"], r["category"])
        r["source"] = "FRED"
        r["source_id"] = r["series_id"]
        r["source_url"] = f"https://fred.stlouisfed.org/series/{r['series_id']}"
    return rows


# ---- futures ---------------------------------------------------------------


def futures(cur, contract: str, since: str | None) -> list[dict]:
    """Lookup by MarketCode OR substring match on MarketName."""
    sql = """
        SELECT
            cc."MarketCode" AS market_code,
            cc."MarketName" AS market_name,
            cc."Category" AS category,
            cpr."ReportDate" AS as_of_date,
            cpr."OpenInterest" AS open_interest,
            cpr."NonCommLong" AS non_comm_long,
            cpr."NonCommShort" AS non_comm_short,
            cpr."CommLong" AS comm_long,
            cpr."CommShort" AS comm_short,
            cpr."PctNonCommLong" AS pct_non_comm_long,
            cpr."PctNonCommShort" AS pct_non_comm_short,
            cpr."PctCommLong" AS pct_comm_long,
            cpr."PctCommShort" AS pct_comm_short,
            cpr."CreationTime" AS retrieved_at
        FROM "CftcPositionReport" cpr
        JOIN "CftcContract" cc ON cc."Id" = cpr."CftcContractId"
        WHERE (cc."MarketCode" = %s OR cc."MarketName" ILIKE %s)
    """
    params: list[Any] = [contract, f"%{contract}%"]
    if since:
        sql += ' AND cpr."ReportDate" >= %s'
        params.append(since)
    sql += ' ORDER BY cpr."ReportDate" DESC, cc."MarketName"'
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["category"] = CFTC_CATEGORY.get(r["category"], r["category"])
        r["source"] = "CFTC COT"
        r["source_id"] = f"{r['market_code']}@{r['as_of_date']}"
        r["source_url"] = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/"
    return rows


# ---- market ----------------------------------------------------------------


def market_vix(cur, since: str | None) -> list[dict]:
    sql = (
        'SELECT "Date" AS as_of_date, "Open" AS open, "High" AS high, '
        '"Low" AS low, "Close" AS close, "CreationTime" AS retrieved_at '
        'FROM "CboeVixDaily" WHERE 1=1'
    )
    params: list[Any] = []
    if since:
        sql += ' AND "Date" >= %s'
        params.append(since)
    sql += ' ORDER BY "Date" DESC'
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["source"] = "CBOE"
        r["source_id"] = None
        r["source_url"] = (
            "https://www.cboe.com/tradable_products/vix/vix_historical_data/"
        )
        r["indicator"] = "VIX"
    return rows


def market_putcall(cur, since: str | None) -> list[dict]:
    sql = (
        'SELECT "RatioType" AS ratio_type, "Date" AS as_of_date, '
        '"CallVolume" AS call_volume, "PutVolume" AS put_volume, '
        '"TotalVolume" AS total_volume, "PutCallRatio" AS put_call_ratio, '
        '"CreationTime" AS retrieved_at '
        'FROM "CboePutCallRatio" WHERE 1=1'
    )
    params: list[Any] = []
    if since:
        sql += ' AND "Date" >= %s'
        params.append(since)
    sql += ' ORDER BY "Date" DESC, "RatioType"'
    cur.execute(sql, params)
    rows = cur.fetchall()
    for r in rows:
        r["ratio_type"] = CBOE_RATIO_TYPE.get(r["ratio_type"], r["ratio_type"])
        r["source"] = "CBOE"
        r["source_id"] = None
        r["source_url"] = "https://www.cboe.com/us/options/market_statistics/"
        r["indicator"] = "put_call"
    return rows


# ---- status ----------------------------------------------------------------


STATUS_TABLES: list[tuple[str, str | None]] = [
    ("CommonStock", None),
    ("InsiderTransaction", "CreationTime"),
    ("InstitutionalHolding", "CreationTime"),
    ("CongressionalTrade", "CreationTime"),
    ("Document", "CreationTime"),
    ("Chunk", "CreationTime"),
    ("DailyStockPrice", "CreationTime"),
    ("DailyShortVolume", "CreationTime"),
    ("ShortInterest", "CreationTime"),
    ("FailToDeliver", "CreationTime"),
    ("FredObservation", "CreationTime"),
    ("FredSeries", "CreationTime"),
    ("CftcPositionReport", "CreationTime"),
    ("CboeVixDaily", "CreationTime"),
    ("CboePutCallRatio", "CreationTime"),
]


def status(cur) -> list[dict]:
    rows = []
    for table, ts_col in STATUS_TABLES:
        if ts_col:
            cur.execute(
                f'SELECT COUNT(*) AS row_count, MAX("{ts_col}") AS latest_retrieved '
                f'FROM "{table}"'
            )
        else:
            cur.execute(
                f'SELECT COUNT(*) AS row_count, NULL AS latest_retrieved FROM "{table}"'
            )
        r = cur.fetchone()
        rows.append(
            {
                "table": table,
                "row_count": r["row_count"],
                "latest_retrieved": r["latest_retrieved"],
            }
        )
    return rows
