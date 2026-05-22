# Author: @ShoumikDutta
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta, UTC, date
from typing import Any

import pandas as pd
import yfinance as yf

from src.ingestion.common import get_active_assets, get_logger, get_supabase, retry

logger = get_logger("historical_backfill")

START_DATE_DEFAULT = "2022-01-01"


# -------------------- DB HELPERS --------------------
def get_existing_dates(supabase, asset_id: int) -> set[str]:
    """
    CHANGED:
    - Kept existing-date lookup as a set of ISO strings.
    WHY:
    - Makes the backfill idempotent and easy to re-run safely.
    """
    response = (
        supabase.table("prices")
        .select("date")
        .eq("asset_id", asset_id)
        .execute()
    )
    rows = response.data or []
    return {row["date"] for row in rows if row.get("date")}


# -------------------- FETCH HELPERS --------------------
def get_bulk_fetch_end_date() -> str:
    """
    CHANGED:
    - Uses exclusive-end date for yfinance.
    WHY:
    - Same reason as daily market/VIX fetch: safer for daily downloads.
    """
    today = datetime.now(UTC).date()
    return (today + timedelta(days=1)).isoformat()


def normalize_downloaded_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if "Close" not in df.columns:
        raise ValueError("Downloaded frame missing Close column")

    return df


def compute_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    CHANGED:
    - Explicitly copies frame before mutation.
    WHY:
    - Avoids pandas chained-assignment surprises.
    """
    out = df.copy()
    out["daily_return"] = out["Close"].pct_change()
    return out


def format_rows(df: pd.DataFrame, asset_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for idx, row in df.iterrows():
        rows.append(
            {
                "asset_id": asset_id,
                "date": idx.strftime("%Y-%m-%d"),
                "open": None if pd.isna(row.get("Open")) else round(float(row["Open"]), 4),
                "high": None if pd.isna(row.get("High")) else round(float(row["High"]), 4),
                "low": None if pd.isna(row.get("Low")) else round(float(row["Low"]), 4),
                "close": None if pd.isna(row.get("Close")) else round(float(row["Close"]), 4),
                "volume": None if pd.isna(row.get("Volume")) else int(row["Volume"]),
                "daily_return": (
                    None
                    if pd.isna(row.get("daily_return"))
                    else round(float(row["daily_return"]), 6)
                ),
            }
        )

    return rows


def upsert_rows(supabase, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    """
    CHANGED:
    - Added explicit on_conflict.
    WHY:
    - Makes idempotency behavior clearer and matches the requirements better.
    """
    supabase.table("prices").upsert(
        rows,
        on_conflict="asset_id,date",
    ).execute()
    return len(rows)


def download_bulk(tickers: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    return yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )


def download_single(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    return yf.download(
        ticker,
        start=start_date,
        end=end_date,
        auto_adjust=False,
        progress=False,
        threads=False,
    )


# -------------------- MAIN --------------------
def run_backfill(start_date: str = START_DATE_DEFAULT) -> dict[str, Any]:
    supabase = get_supabase()
    assets = get_active_assets(supabase)

    tickers = [a["ticker"] for a in assets]
    ticker_to_id = {a["ticker"]: a["id"] for a in assets}
    end_date = get_bulk_fetch_end_date()

    total_rows = 0
    failures: list[str] = []
    processed = 0

    logger.info(f"Starting bulk backfill for {len(tickers)} tickers")

    # ---------- BULK DOWNLOAD ----------
    bulk_data = retry(
        lambda: download_bulk(tickers, start_date, end_date),
        retries=3,
        delay_seconds=5,
        logger=logger,
        context="bulk backfill download",
    )

    if bulk_data is None or bulk_data.empty:
        logger.error("Bulk download failed completely")
        return {
            "tickers_processed": 0,
            "total_rows": 0,
            "failures": tickers,
        }

    available_tickers: list[str]
    if isinstance(bulk_data.columns, pd.MultiIndex):
        available_tickers = list(bulk_data.columns.levels[0])
    else:
        # If only one ticker somehow comes back in flat format, keep safe fallback.
        available_tickers = tickers

    missing_tickers = [t for t in tickers if t not in available_tickers]
    if missing_tickers:
        logger.warning(f"Missing in bulk fetch: {missing_tickers}")

    # ---------- PROCESS BULK ----------
    for ticker in available_tickers:
        if ticker not in ticker_to_id:
            continue

        asset_id = ticker_to_id[ticker]

        try:
            df = bulk_data[ticker].copy() if isinstance(bulk_data.columns, pd.MultiIndex) else bulk_data.copy()
            df = normalize_downloaded_frame(df)

            if df.empty:
                logger.warning(f"{ticker}: no data returned")
                continue

            df = df.dropna(subset=["Close"])
            if df.empty:
                logger.warning(f"{ticker}: no usable rows after dropping null Close")
                continue

            df = compute_returns(df)

            existing_dates = get_existing_dates(supabase, asset_id)
            df = df[~df.index.strftime("%Y-%m-%d").isin(existing_dates)]

            rows = format_rows(df, asset_id)
            inserted = upsert_rows(supabase, rows)

            total_rows += inserted
            processed += 1

            if not df.empty:
                logger.info(
                    f"{ticker}: {inserted} rows "
                    f"({df.index.min().date()} to {df.index.max().date()})"
                )

        except Exception as exc:
            logger.error(f"{ticker}: failed - {exc}")
            failures.append(ticker)

    # ---------- REFETCH MISSING TICKERS ----------
    for ticker in missing_tickers:
        asset_id = ticker_to_id[ticker]

        try:
            df = retry(
                lambda: download_single(ticker, start_date, end_date),
                retries=3,
                delay_seconds=5,
                logger=logger,
                context=f"{ticker} single backfill download",
            )

            df = normalize_downloaded_frame(df)

            if df.empty:
                logger.warning(f"{ticker}: no data even after retry")
                failures.append(ticker)
                continue

            df = df.dropna(subset=["Close"])
            if df.empty:
                logger.warning(f"{ticker}: no usable rows after retry")
                failures.append(ticker)
                continue

            df = compute_returns(df)

            existing_dates = get_existing_dates(supabase, asset_id)
            df = df[~df.index.strftime("%Y-%m-%d").isin(existing_dates)]

            rows = format_rows(df, asset_id)
            inserted = upsert_rows(supabase, rows)

            total_rows += inserted
            processed += 1

            if not df.empty:
                logger.info(
                    f"{ticker}: recovered {inserted} rows "
                    f"({df.index.min().date()} to {df.index.max().date()})"
                )

        except Exception as exc:
            logger.error(f"{ticker}: retry failed - {exc}")
            failures.append(ticker)

    logger.info(
        f"Complete: {processed} tickers, {total_rows} total rows, {len(failures)} failures"
    )

    return {
        "tickers_processed": processed,
        "total_rows": total_rows,
        "failures": failures,
    }


if __name__ == "__main__":
    result = run_backfill()
    print(result)