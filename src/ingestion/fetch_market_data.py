# Author: @ShoumikDutta
from __future__ import annotations

from datetime import datetime, timedelta, UTC, date
from typing import Any

import pandas as pd
import yfinance as yf

from src.ingestion.common import (
    get_active_assets,
    get_exchange_for_ticker,
    get_logger,
    get_supabase,
    retry,
    utc_today,
)

logger = get_logger("fetch_market_data")


# -------------------- DATE / FETCH HELPERS --------------------
def get_last_expected_date_for_fetch(ticker: str) -> date:
    """
    CHANGED:
    - Simplified expected latest date logic.
    WHY:
    - The old code treated some non-US tickers as up-to-date too early.
    - This version aims to fetch up to the current available market day by using an exclusive end date.
    """
    return utc_today()


def get_fetch_window(last_date: str | None, ticker: str) -> tuple[date, date]:
    """
    Returns:
        start_date: inclusive
        fetch_end_date: exclusive for yfinance

    CHANGED:
    - Uses today+1 as exclusive yfinance end date.
    WHY:
    - yfinance daily downloads usually treat end as exclusive.
    - This prevents missing the latest available row.
    """
    today = utc_today()

    if last_date:
        start_date = datetime.fromisoformat(last_date).date() + timedelta(days=1)
    else:
        # Per requirements: if no data exists, fetch last ~5 trading days as buffer
        start_date = today - timedelta(days=7)

    fetch_end_date = today + timedelta(days=1)
    return start_date, fetch_end_date


# -------------------- DB HELPERS --------------------
def get_last_price_date(supabase, asset_id: int) -> str | None:
    response = (
        supabase.table("prices")
        .select("date")
        .eq("asset_id", asset_id)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0]["date"] if rows else None


def get_previous_close(supabase, asset_id: int, before_date: str) -> float | None:
    """
    CHANGED:
    - Pulls the most recent close before the new batch start.
    WHY:
    - The first row in a new batch needs previous DB close to compute daily_return correctly.
    """
    response = (
        supabase.table("prices")
        .select("close,date")
        .eq("asset_id", asset_id)
        .lt("date", before_date)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None

    close_val = rows[0].get("close")
    return float(close_val) if close_val is not None else None


# -------------------- FETCH --------------------
def download_ticker_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        start=start_date,
        end=end_date,
        progress=False,
        auto_adjust=False,
        threads=False,
    )

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()

    required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"{ticker}: missing columns {missing}")

    return df


# -------------------- TRANSFORM --------------------
def compute_daily_returns(df: pd.DataFrame, previous_close: float | None) -> pd.DataFrame:
    """
    CHANGED:
    - First row uses prior DB close if available.
    WHY:
    - Matches ingestion spec for incremental daily fetch.
    """
    out = df.copy()

    closes = out["Close"].astype(float).tolist()
    daily_returns: list[float | None] = []

    prev = previous_close
    for close_val in closes:
        if prev is None:
            daily_returns.append(None)
        else:
            daily_returns.append((float(close_val) - float(prev)) / float(prev))
        prev = float(close_val)

    out["daily_return"] = daily_returns
    return out


def build_rows(df: pd.DataFrame, asset_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        rows.append(
            {
                "asset_id": asset_id,
                "date": row["Date"].strftime("%Y-%m-%d"),
                "open": None if pd.isna(row["Open"]) else round(float(row["Open"]), 4),
                "high": None if pd.isna(row["High"]) else round(float(row["High"]), 4),
                "low": None if pd.isna(row["Low"]) else round(float(row["Low"]), 4),
                "close": None if pd.isna(row["Close"]) else round(float(row["Close"]), 4),
                "volume": None if pd.isna(row["Volume"]) else int(row["Volume"]),
                "daily_return": (
                    None
                    if pd.isna(row["daily_return"]) or row["daily_return"] is None
                    else round(float(row["daily_return"]), 6)
                ),
            }
        )

    return rows


# -------------------- LOAD --------------------
def upsert_rows(supabase, rows: list[dict[str, Any]], ticker: str) -> int:
    if not rows:
        return 0

    try:
        supabase.table("prices").upsert(
            rows,
            on_conflict="asset_id,date",
        ).execute()
        return len(rows)
    except Exception as exc:
        first_date = rows[0]["date"]
        last_date = rows[-1]["date"]
        raise RuntimeError(
            f"Supabase write failed for {ticker}, date_range={first_date}..{last_date}: {exc}"
        ) from exc


# -------------------- MAIN --------------------
def fetch_market_data() -> dict[str, Any]:
    supabase = get_supabase()
    assets = get_active_assets(supabase)

    logger.info(f"Found {len(assets)} active assets")

    total_rows_inserted = 0
    failures: list[str] = []

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]

        try:
            last_date_str = get_last_price_date(supabase, asset_id)
            last_expected_date = get_last_expected_date_for_fetch(ticker)

            if last_date_str:
                last_date = datetime.fromisoformat(last_date_str).date()
                if last_date >= last_expected_date:
                    logger.info(f"{ticker}: already up-to-date (last_date={last_date})")
                    continue

            start_date, fetch_end_date = get_fetch_window(last_date_str, ticker)

            if start_date >= fetch_end_date:
                logger.info(f"{ticker}: no fetch needed")
                continue

            logger.info(f"{ticker}: fetching from {start_date} to {fetch_end_date - timedelta(days=1)}")

            df = retry(
                lambda: download_ticker_data(
                    ticker,
                    start_date.isoformat(),
                    fetch_end_date.isoformat(),
                ),
                retries=3,
                delay_seconds=5,
                logger=logger,
                context=f"{ticker} download",
            )

            if df.empty:
                logger.warning(f"{ticker}: no data returned")
                continue

            previous_close = get_previous_close(supabase, asset_id, start_date.isoformat())
            df = compute_daily_returns(df, previous_close)

            rows = build_rows(df, asset_id)
            inserted = upsert_rows(supabase, rows, ticker)

            total_rows_inserted += inserted
            logger.info(f"{ticker}: inserted {inserted} rows")

        except Exception as exc:
            logger.warning(f"{ticker}: failed with error: {exc}")
            failures.append(ticker)

    logger.info(
        f"Completed: {len(assets)} tickers processed, {total_rows_inserted} rows inserted, {len(failures)} failures"
    )

    return {
        "tickers_processed": len(assets),
        "rows_inserted": total_rows_inserted,
        "failures": failures,
    }


if __name__ == "__main__":
    result = fetch_market_data()
    print(result)