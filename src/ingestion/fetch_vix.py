# Author: @ShoumikDutta
from __future__ import annotations

from datetime import datetime, timedelta, UTC, date
from typing import Any

import pandas as pd
import yfinance as yf

from src.ingestion.common import get_logger, get_supabase, retry

logger = get_logger("fetch_vix")

VIX_TICKER = "^VIX"


# -------------------- DATE HELPERS --------------------
def get_fetch_window(last_date: str | None) -> tuple[date, date]:
    """
    Returns:
        start_date: first date we want to fetch
        fetch_end_date: exclusive end date for yfinance

    CHANGED:
    - Added exclusive-end handling for yfinance.
    WHY:
    - yfinance usually treats 'end' as exclusive for daily data.
    - Using end=today can miss the latest intended row.
    """
    today = datetime.now(UTC).date()

    if last_date:
        start_date = datetime.fromisoformat(last_date).date() + timedelta(days=1)
    else:
        start_date = today - timedelta(days=30)

    fetch_end_date = today + timedelta(days=1)
    return start_date, fetch_end_date


# -------------------- DB HELPERS --------------------
def get_last_date(supabase) -> str | None:
    response = (
        supabase.table("macro_indicators")
        .select("date")
        .eq("indicator", "vix")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0]["date"] if rows else None


# -------------------- FETCH --------------------
def download_vix_data(start_date: str, end_date: str) -> pd.DataFrame:
    df = yf.download(
        VIX_TICKER,
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

    if "Date" not in df.columns:
        raise ValueError("VIX: missing Date column")

    if "Close" not in df.columns:
        raise ValueError("VIX: missing Close column")

    return df


# -------------------- TRANSFORM --------------------
def build_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        close_value = row.get("Close")
        if pd.isna(close_value):
            continue

        rows.append(
            {
                "indicator": "vix",
                "date": row["Date"].strftime("%Y-%m-%d"),
                "value": round(float(close_value), 4),
                "source": "yfinance",
            }
        )

    return rows


# -------------------- LOAD --------------------
def upsert_rows(supabase, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    try:
        supabase.table("macro_indicators").upsert(
            rows,
            on_conflict="indicator,date",
        ).execute()
        return len(rows)
    except Exception as exc:
        first_date = rows[0]["date"]
        last_date = rows[-1]["date"]
        raise RuntimeError(
            f"Supabase write failed for vix, date_range={first_date}..{last_date}: {exc}"
        ) from exc


# -------------------- MAIN --------------------
def fetch_vix() -> dict[str, Any]:
    supabase = get_supabase()

    last_date = get_last_date(supabase)
    start_date, fetch_end_date = get_fetch_window(last_date)

    if start_date >= fetch_end_date:
        logger.info("VIX: already up-to-date")
        return {"rows_inserted": 0, "latest_value": None}

    logger.info(
        f"VIX: fetching from {start_date} to {fetch_end_date - timedelta(days=1)}"
    )

    try:
        df = retry(
            lambda: download_vix_data(
                start_date.isoformat(),
                fetch_end_date.isoformat(),
            ),
            retries=3,
            delay_seconds=5,
            logger=logger,
            context="VIX download",
        )

        # Weekend / holiday can legitimately return empty.
        if df.empty:
            logger.info("VIX: no new data returned")
            return {"rows_inserted": 0, "latest_value": None}

        rows = build_rows(df)
        if not rows:
            logger.info("VIX: no usable rows after transformation")
            return {"rows_inserted": 0, "latest_value": None}

        inserted = upsert_rows(supabase, rows)
        latest_value = rows[-1]["value"]

        logger.info(f"VIX: {inserted} new rows (latest value: {latest_value})")

        return {
            "rows_inserted": inserted,
            "latest_value": latest_value,
        }

    except Exception as exc:
        logger.error(f"VIX: failed with error: {exc}")
        return {"rows_inserted": 0, "latest_value": None}


if __name__ == "__main__":
    result = fetch_vix()
    print(result)
