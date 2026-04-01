# Author: @ShoumikDutta
from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any

import pandas as pd
import yfinance as yf

from src.ingestion.common import get_logger, get_supabase, retry
from src.ingestion.data_validator import today

logger = get_logger("fetch_vix")

VIX_TICKER = "^VIX"


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
                "value": float(close_value),
                "source": "yfinance",
            }
        )

    return rows


# -------------------- LOAD --------------------
def upsert_rows(supabase, rows: list[dict]) -> int:
    if not rows:
        return 0

    supabase.table("macro_indicators").upsert(
        rows,
        on_conflict="indicator,date",
    ).execute()

    return len(rows)


# -------------------- MAIN --------------------
def fetch_vix() -> dict:
    supabase = get_supabase()

    last_date = get_last_date(supabase)

    today = datetime.now(UTC).date()

    # ---------- Determine start ----------
    if last_date:
        start_date = datetime.fromisoformat(last_date).date() + timedelta(days=1)
    else:
        start_date = today - timedelta(days=30)

    # ---------- Skip if up-to-date ----------
    if start_date > today:
        logger.info("VIX: already up-to-date")
        return {"rows_inserted": 0, "latest_value": None}

    logger.info(f"VIX: fetching from {start_date} to {today}")

    try:
        df = retry(
            lambda: download_vix_data(
                start_date.isoformat(),
                today.isoformat(),
            ),
            retries=3,
            delay_seconds=5,
            logger=logger,
            context="VIX download",
        )

        # Weekend / holiday case → expected
        if df.empty:
            logger.info("VIX: no new data (market closed)")
            return {"rows_inserted": 0, "latest_value": None}

        rows = build_rows(df)
        inserted = upsert_rows(supabase, rows)

        latest_value = rows[-1]["value"] if rows else None

        logger.info(f"VIX: {inserted} new rows (latest: {latest_value})")

        return {
            "rows_inserted": inserted,
            "latest_value": latest_value,
        }

    except Exception as exc:
        logger.error(f"VIX: failed with error: {exc}")
        return {"rows_inserted": 0, "latest_value": None}


# -------------------- CLI --------------------
if __name__ == "__main__":
    result = fetch_vix()
    print(result)
"""VIX data fetcher via yfinance."""
