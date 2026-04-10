# Author: @ShoumikDutta
from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Any

import pandas as pd
import yfinance as yf

from src.ingestion.common import get_logger, get_supabase, retry, to_iso_date

logger = get_logger("fetch_market_data")


# -------------------- DB HELPERS --------------------
def get_active_assets(supabase) -> list[dict[str, Any]]:
    response = (
        supabase.table("assets")
        .select("id,ticker")
        .eq("is_active", True)
        .execute()
    )
    return response.data or []


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


def get_previous_close(supabase, asset_id: int) -> float | None:
    response = (
        supabase.table("prices")
        .select("close")
        .eq("asset_id", asset_id)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None

    close_value = rows[0].get("close")
    return float(close_value) if close_value is not None else None


# -------------------- DATE HELPERS --------------------
def get_fetch_window(last_date: str | None) -> tuple[date, date, date]:
    """
    Returns:
        start_date: first date we want to fetch
        last_expected_date: latest market day we want in DB
        fetch_end_date: exclusive end date passed to yfinance

    CHANGED:
    - Added a dedicated helper for date handling.
    Why:
    - Keeps the main loop cleaner.
    - Makes it explicit that yfinance 'end' should be exclusive.
    """

    # CHANGED:
    # Still use yesterday as the latest expected day to reduce timezone issues.
    # Why:
    # If the script runs before the market/API is fully updated for the current day,
    # using today's date can create incomplete or empty fetches.
    last_expected_date = datetime.utcnow().date() - timedelta(days=1)

    if last_date:
        # CHANGED:
        # Convert to date first, then add 1 day.
        # Why:
        # Keeps types consistent and avoids datetime/date confusion.
        start_date = datetime.fromisoformat(last_date).date() + timedelta(days=1)
    else:
        # CHANGED:
        # Use date directly rather than datetime -> .date() later.
        # Why:
        # Cleaner and more consistent.
        start_date = last_expected_date - timedelta(days=7)

    # CHANGED:
    # yfinance daily download behaves as if 'end' is exclusive.
    # To fetch data through last_expected_date, pass end = last_expected_date + 1 day.
    # Why:
    # Old behavior used start=end for one-day fetches and returned empty data.
    fetch_end_date = last_expected_date + timedelta(days=1)

    return start_date, last_expected_date, fetch_end_date


# -------------------- DATA FETCH --------------------
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

    # Handle MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()

    if "Date" not in df.columns:
        raise ValueError(f"{ticker}: yfinance response missing Date column")

    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"{ticker}: missing expected columns: {sorted(missing)}")

    return df


# -------------------- TRANSFORM --------------------
def build_price_rows(
    df: pd.DataFrame,
    asset_id: int,
    previous_close: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prev_close = previous_close

    for _, row in df.iterrows():
        close_value = row.get("Close")
        if pd.isna(close_value):
            continue

        open_value = row.get("Open")
        high_value = row.get("High")
        low_value = row.get("Low")
        volume_value = row.get("Volume")

        daily_return = None
        if prev_close is not None and prev_close != 0:
            daily_return = (float(close_value) - prev_close) / prev_close

        rows.append(
            {
                "asset_id": asset_id,
                "date": to_iso_date(row["Date"]),
                "open": None if pd.isna(open_value) else round(float(open_value), 4),
                "high": None if pd.isna(high_value) else round(float(high_value), 4),
                "low": None if pd.isna(low_value) else round(float(low_value), 4),
                "close": round(float(close_value), 4),
                "volume": None if pd.isna(volume_value) else int(volume_value),
                "daily_return": None if daily_return is None else round(daily_return, 6),
            }
        )

        prev_close = float(close_value)

    return rows


# -------------------- LOAD --------------------
def upsert_prices(supabase, rows: list[dict[str, Any]]) -> int:
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
        asset_id = rows[0]["asset_id"]
        raise RuntimeError(
            f"Supabase write failed for asset_id={asset_id}, "
            f"date_range={first_date}..{last_date}: {exc}"
        ) from exc


# -------------------- MAIN --------------------
def fetch_market_data() -> dict[str, Any]:
    supabase = get_supabase()
    assets = get_active_assets(supabase)

    tickers_processed = 0
    total_rows_inserted = 0
    failures: list[str] = []

    logger.info(f"Found {len(assets)} active assets")

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]

        try:
            last_date = get_last_price_date(supabase, asset_id)

            if last_date:
                previous_close = get_previous_close(supabase, asset_id)
            else:
                previous_close = None

            # CHANGED:
            # Centralized fetch-window logic.
            # Why:
            # Avoids the old same-day start/end bug and keeps dates consistent.
            start_date, last_expected_date, fetch_end_date = get_fetch_window(last_date)

            # CHANGED:
            # Compare against last_expected_date, not fetch_end_date.
            # Why:
            # fetch_end_date is only for yfinance's exclusive end parameter.
            if start_date > last_expected_date:
                logger.info(f"{ticker}: already up-to-date (last_date={last_date})")
                tickers_processed += 1
                continue

            logger.info(
                f"{ticker}: fetching from {start_date} to {last_expected_date}"
            )

            # ---------- Fetch ----------
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
                tickers_processed += 1
                continue

            # CHANGED:
            # Filter out any rows beyond last_expected_date just in case.
            # Why:
            # Keeps DB data aligned with the intended date window.
            df = df[df["Date"].dt.date <= last_expected_date]

            if df.empty:
                logger.warning(f"{ticker}: no usable rows after date filtering")
                tickers_processed += 1
                continue

            # ---------- Transform ----------
            rows = build_price_rows(df, asset_id, previous_close)

            if not rows:
                logger.warning(f"{ticker}: no rows built after transformation")
                tickers_processed += 1
                continue

            # ---------- Load ----------
            inserted = upsert_prices(supabase, rows)

            logger.info(f"{ticker}: upserted {inserted} rows")

            total_rows_inserted += inserted
            tickers_processed += 1

        except Exception as exc:
            logger.warning(f"{ticker}: failed with error: {exc}")
            failures.append(ticker)
            tickers_processed += 1

    logger.info(
        f"Completed: {tickers_processed} tickers processed, "
        f"{total_rows_inserted} rows inserted, {len(failures)} failures"
    )

    return {
        "tickers_processed": tickers_processed,
        "rows_inserted": total_rows_inserted,
        "failures": failures,
    }


# -------------------- CLI --------------------
if __name__ == "__main__":
    result = fetch_market_data()
    print(result)