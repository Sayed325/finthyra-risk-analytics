# Author: @ShoumikDutta
from __future__ import annotations

from datetime import datetime, timedelta, UTC, date
from typing import Any

import pandas_market_calendars as mcal

from src.ingestion.common import (
    get_active_assets,
    get_exchange_for_ticker,
    get_logger,
    get_supabase,
    utc_today,
)

logger = get_logger("data_validator")


# -------------------- DATE HELPERS --------------------
def parse_iso_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def get_recent_expected_trading_days(
    exchange: str, lookback_days: int = 5
) -> list[str]:
    """
    CHANGED:
    - Uses exchange-specific market calendar.
    WHY:
    - Required for correct completeness/freshness logic.
    """
    today = utc_today()
    start = today - timedelta(days=20)
    end = today

    cal = mcal.get_calendar(exchange)
    schedule = cal.schedule(start_date=start.isoformat(), end_date=end.isoformat())

    if schedule.empty:
        return []

    trading_days = [idx.date().isoformat() for idx in schedule.index]
    return trading_days[-lookback_days:]


def trading_days_old(last_date: date, exchange: str) -> int:
    """
    CHANGED:
    - Freshness is now exchange-aware.
    WHY:
    - Different exchanges have different holidays / schedules.
    """
    today = utc_today()

    if last_date >= today:
        return 0

    cal = mcal.get_calendar(exchange)
    schedule = cal.schedule(
        start_date=last_date.isoformat(),
        end_date=today.isoformat(),
    )

    trading_days = [idx.date() for idx in schedule.index]
    if not trading_days:
        return 0

    return sum(1 for d in trading_days if d > last_date)


# -------------------- DB HELPERS --------------------
def get_asset_recent_dates(supabase, asset_id: int, min_date: str) -> list[str]:
    response = (
        supabase.table("prices")
        .select("date")
        .eq("asset_id", asset_id)
        .gte("date", min_date)
        .order("date")
        .execute()
    )
    rows = response.data or []
    return [r["date"] for r in rows if r.get("date")]


def get_asset_last_date(supabase, asset_id: int) -> str | None:
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


def get_latest_macro_dates(supabase) -> dict[str, str]:
    response = (
        supabase.table("macro_indicators")
        .select("indicator,date")
        .order("date", desc=True)
        .execute()
    )
    rows = response.data or []

    latest: dict[str, str] = {}
    for row in rows:
        indicator = row.get("indicator")
        dt = row.get("date")
        if indicator and dt and indicator not in latest:
            latest[indicator] = dt

    return latest


def fetch_prices_page(supabase, start: int, end: int) -> list[dict[str, Any]]:
    response = (
        supabase.table("prices")
        .select("asset_id,date,close,volume,daily_return")
        .range(start, end)
        .execute()
    )
    return response.data or []


def fetch_macro_page(supabase, start: int, end: int) -> list[dict[str, Any]]:
    response = (
        supabase.table("macro_indicators")
        .select("indicator,date,value")
        .range(start, end)
        .execute()
    )
    return response.data or []


# -------------------- CHECK 1: COMPLETENESS --------------------
def check_completeness(supabase) -> list[str]:
    """
    CHANGED:
    - Each asset now uses its own exchange calendar based on ticker suffix.
    WHY:
    - Prevents false warnings for non-US tickers.
    """
    issues: list[str] = []
    assets = get_active_assets(supabase)

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]
        exchange = get_exchange_for_ticker(ticker)

        expected_days = get_recent_expected_trading_days(exchange, lookback_days=5)
        if not expected_days:
            issues.append(
                f"{ticker}: could not determine trading calendar for {exchange}"
            )
            continue

        min_date = expected_days[0]
        actual_dates = set(get_asset_recent_dates(supabase, asset_id, min_date))
        missing = [d for d in expected_days if d not in actual_dates]

        if missing:
            issues.append(f"{ticker}: missing trading days {missing}")

    return issues


# -------------------- CHECK 2: FRESHNESS --------------------
def check_freshness(supabase) -> list[str]:
    """
    CHANGED:
    - Asset freshness now also uses the asset's exchange calendar.
    WHY:
    - Avoids false stale flags on local exchange holidays.
    """
    issues: list[str] = []
    assets = get_active_assets(supabase)

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]
        exchange = get_exchange_for_ticker(ticker)

        last_date_str = get_asset_last_date(supabase, asset_id)
        if not last_date_str:
            issues.append(f"{ticker}: no data at all")
            continue

        last_date = parse_iso_date(last_date_str)
        td_old = trading_days_old(last_date, exchange)

        if td_old > 3:
            issues.append(
                f"{ticker}: last data {last_date} ({td_old} trading days old)"
            )

    latest_macro = get_latest_macro_dates(supabase)
    required_indicators = {"fed_funds_rate", "cpi", "treasury_yield_10y", "vix"}

    for indicator in required_indicators:
        if indicator not in latest_macro:
            issues.append(f"{indicator}: no data at all")
            continue

        last_date = parse_iso_date(latest_macro[indicator])

        if indicator == "cpi":
            if (utc_today() - last_date).days > 45:
                issues.append(
                    f"{indicator}: last data {last_date} (>45 calendar days old)"
                )
        else:
            td_old = trading_days_old(last_date, "NYSE")
            if td_old > 3:
                issues.append(
                    f"{indicator}: last data {last_date} ({td_old} trading days old)"
                )

    return issues


# -------------------- CHECK 3: SANITY --------------------
def check_sanity(supabase) -> list[str]:
    issues: list[str] = []

    page_size = 1000
    start = 0

    while True:
        rows = fetch_prices_page(supabase, start, start + page_size - 1)
        if not rows:
            break

        for row in rows:
            asset_id = row["asset_id"]
            close_val = row.get("close")
            volume_val = row.get("volume")
            return_val = row.get("daily_return")

            if close_val is not None and float(close_val) <= 0:
                issues.append(f"asset {asset_id}: invalid close {close_val}")

            if volume_val is not None and int(volume_val) < 0:
                issues.append(f"asset {asset_id}: invalid volume {volume_val}")

            if return_val is not None:
                rv = float(return_val)
                if rv < -0.5 or rv > 0.5:
                    issues.append(f"asset {asset_id}: abnormal daily_return {rv}")

        start += page_size

    start = 0
    while True:
        rows = fetch_macro_page(supabase, start, start + page_size - 1)
        if not rows:
            break

        for row in rows:
            indicator = row["indicator"]
            value = row.get("value")

            if value is None:
                continue

            val = float(value)

            if indicator == "vix":
                if val < 5 or val > 100:
                    issues.append(f"vix: out-of-range value {val}")
            else:
                if val <= 0:
                    issues.append(f"{indicator}: invalid value {val}")

        start += page_size

    return issues


# -------------------- CHECK 4: DUPLICATES --------------------
def check_duplicates(supabase) -> list[str]:
    issues: list[str] = []

    seen_prices: set[tuple[int, str]] = set()
    seen_macro: set[tuple[str, str]] = set()

    page_size = 1000

    start = 0
    while True:
        rows = (
            supabase.table("prices")
            .select("asset_id,date")
            .range(start, start + page_size - 1)
            .execute()
            .data
            or []
        )
        if not rows:
            break

        for row in rows:
            key = (row["asset_id"], row["date"])
            if key in seen_prices:
                issues.append(f"duplicate price row: {key}")
            else:
                seen_prices.add(key)

        start += page_size

    start = 0
    while True:
        rows = (
            supabase.table("macro_indicators")
            .select("indicator,date")
            .range(start, start + page_size - 1)
            .execute()
            .data
            or []
        )
        if not rows:
            break

        for row in rows:
            key = (row["indicator"], row["date"])
            if key in seen_macro:
                issues.append(f"duplicate macro row: {key}")
            else:
                seen_macro.add(key)

        start += page_size

    return issues


# -------------------- MAIN --------------------
def validate_data() -> dict[str, Any]:
    supabase = get_supabase()

    completeness_issues = check_completeness(supabase)
    freshness_issues = check_freshness(supabase)
    sanity_issues = check_sanity(supabase)
    duplicate_issues = check_duplicates(supabase)

    status = "pass"
    if sanity_issues or duplicate_issues:
        status = "fail"
    elif completeness_issues or freshness_issues:
        status = "warn"

    report = {
        "status": status,
        "checks": {
            "completeness": {
                "status": "pass" if not completeness_issues else "warn",
                "details": completeness_issues,
            },
            "freshness": {
                "status": "pass" if not freshness_issues else "warn",
                "details": freshness_issues,
            },
            "sanity": {
                "status": "pass" if not sanity_issues else "fail",
                "details": sanity_issues,
            },
            "duplicates": {
                "status": "pass" if not duplicate_issues else "fail",
                "details": duplicate_issues,
            },
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }

    logger.info(report)
    return report


if __name__ == "__main__":
    result = validate_data()
    print(result)
