# Author: @ShoumikDutta
from __future__ import annotations

import os
from datetime import datetime, timedelta, UTC, date
from typing import Any

import requests
from dotenv import load_dotenv

from src.ingestion.common import get_logger, get_supabase, retry

logger = get_logger("fetch_macro_data")

# -------------------- ENV --------------------
load_dotenv()
FRED_API_KEY = os.environ["FRED_API_KEY"]

# -------------------- CONFIG --------------------
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

INDICATORS = {
    "fed_funds_rate": "DFF",
    "cpi": "CPIAUCSL",
    "treasury_yield_10y": "DGS10",
    "eur_usd_rate": "DEXUSEU",
}


# -------------------- HELPERS --------------------
def get_last_date(supabase, indicator: str) -> str | None:
    response = (
        supabase.table("macro_indicators")
        .select("date")
        .eq("indicator", indicator)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0]["date"] if rows else None


def fetch_fred_series(series_id: str, start_date: str) -> list[dict[str, Any]]:
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start_date,
    }

    response = requests.get(FRED_BASE_URL, params=params, timeout=10)

    # CHANGED:
    # Added clearer error reporting with status code.
    # Why:
    # Easier debugging if FRED rejects the request or the API key is wrong.
    if response.status_code != 200:
        raise RuntimeError(
            f"FRED API error ({response.status_code}): {response.text}"
        )

    data = response.json()

    if "observations" not in data:
        raise ValueError("Invalid FRED response format: 'observations' missing")

    return data["observations"]


def transform_rows(observations: list[dict[str, Any]], indicator: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for obs in observations:
        value = obs.get("value")
        obs_date = obs.get("date")

        # CHANGED:
        # Added check for missing date.
        # Why:
        # Prevents inserting malformed rows if API response is incomplete.
        if not obs_date:
            continue

        # Skip missing values (FRED returns ".")
        if value == ".":
            continue

        try:
            value_float = float(value)
        except (ValueError, TypeError):
            continue

        rows.append(
            {
                "indicator": indicator,
                "date": obs_date,
                "value": value_float,
                "source": "fred",
            }
        )

    return rows


def upsert_rows(supabase, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    # CHANGED:
    # Wrapped DB write in try/except with clearer context.
    # Why:
    # Makes it easier to see which indicator failed during upsert.
    try:
        supabase.table("macro_indicators").upsert(
            rows,
            on_conflict="indicator,date",
        ).execute()
    except Exception as exc:
        first_date = rows[0]["date"]
        last_date = rows[-1]["date"]
        indicator = rows[0]["indicator"]
        raise RuntimeError(
            f"Supabase write failed for indicator={indicator}, "
            f"date_range={first_date}..{last_date}: {exc}"
        ) from exc

    return len(rows)


# -------------------- MAIN --------------------
def fetch_macro_data() -> dict[str, Any]:
    supabase = get_supabase()

    indicators_processed = 0
    total_rows_inserted = 0
    failures: list[str] = []

    today = datetime.now(UTC).date()

    for indicator, series_id in INDICATORS.items():
        try:
            last_date = get_last_date(supabase, indicator)

            # ---------- Determine start date ----------
            # CHANGED:
            # Made start_date always a date object.
            # Why:
            # Previously one branch returned datetime and the other returned date.
            # Then calling .date() on an existing date caused:
            # 'datetime.date' object has no attribute 'date'
            if last_date:
                start_date = datetime.fromisoformat(last_date).date() + timedelta(days=1)
            else:
                start_date = today - timedelta(days=30)

            # Skip if up-to-date
            if start_date > today:
                logger.info(f"{indicator}: already up-to-date")
                indicators_processed += 1
                continue

            logger.info(f"{indicator}: fetching from {start_date}")

            # ---------- Fetch ----------
            observations = retry(
                lambda: fetch_fred_series(series_id, start_date.isoformat()),
                retries=3,
                delay_seconds=5,
                logger=logger,
                context=f"{indicator} fetch",
            )

            # ---------- Transform ----------
            rows = transform_rows(observations, indicator)

            # CHANGED:
            # Added explicit log when no new valid rows exist.
            # Why:
            # For monthly indicators like CPI, 0 new rows can be normal.
            if not rows:
                logger.info(f"{indicator}: no new valid observations")
                indicators_processed += 1
                continue

            # ---------- Load ----------
            inserted = upsert_rows(supabase, rows)

            logger.info(f"{indicator}: {inserted} new rows")

            total_rows_inserted += inserted
            indicators_processed += 1

        except Exception as exc:
            logger.warning(f"{indicator}: failed with error: {exc}")
            failures.append(indicator)
            indicators_processed += 1

    logger.info(
        f"Completed: {indicators_processed} indicators, "
        f"{total_rows_inserted} rows inserted, {len(failures)} failures"
    )

    return {
        "indicators_processed": indicators_processed,
        "rows_inserted": total_rows_inserted,
        "failures": failures,
    }


# -------------------- CLI --------------------
if __name__ == "__main__":
    result = fetch_macro_data()
    print(result)