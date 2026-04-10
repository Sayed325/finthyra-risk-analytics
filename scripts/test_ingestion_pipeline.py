# Author: @ShoumikDutta
"""
Pipeline health check for Finthyra.

Purpose:
- Run ingestion scripts end to end
- Run data validation
- Perform extra safety checks before model training
- Print a dashboard-style preview
- Fail fast if critical issues are found
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from src.ingestion.fetch_market_data import fetch_market_data
from src.ingestion.fetch_macro_data import fetch_macro_data
from src.ingestion.fetch_vix import fetch_vix
from src.ingestion.data_validator import validate_data
from src.ingestion.common import get_supabase

REQUIRED_MACRO_INDICATORS = {
    "fed_funds_rate",
    "cpi",
    "treasury_yield_10y",
    "vix",
}


# -------------------- PRINT HELPERS --------------------
def print_header() -> None:
    print("\n" + "=" * 70)
    print("FINTHYRA PIPELINE HEALTH CHECK")
    print("=" * 70)


def print_section(title: str) -> None:
    print(f"\n--- {title} ---")


def print_success(message: str) -> None:
    print(f"[OK] {message}")


def print_warning(message: str) -> None:
    print(f"[WARN] {message}")


def print_error(message: str) -> None:
    print(f"[ERROR] {message}")


# -------------------- DB HELPERS --------------------
def get_active_assets(supabase) -> list[dict[str, Any]]:
    rows = (
        supabase.table("assets")
        .select("id,ticker")
        .eq("is_active", True)
        .execute()
        .data
    )
    return rows or []


def asset_has_price_data(supabase, asset_id: int) -> bool:
    """
    CHANGED:
    - Replaced the old whole-table scan with a per-asset existence check.
    Why:
    - The previous version queried all rows from prices and could give false
      negatives because of response limits/pagination.
    - This version asks a simpler and more reliable question:
      "Does this asset have at least one row in prices?"
    """
    rows = (
        supabase.table("prices")
        .select("date")
        .eq("asset_id", asset_id)
        .limit(1)
        .execute()
        .data
    )
    return bool(rows)


def get_latest_prices(supabase, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        supabase.table("prices")
        .select("date,close,daily_return,asset_id")
        .order("date", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    return rows or []


def get_macro_snapshot(supabase) -> dict[str, dict[str, Any]]:
    rows = (
        supabase.table("macro_indicators")
        .select("indicator,value,date")
        .order("date", desc=True)
        .execute()
        .data
    ) or []

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        indicator = row["indicator"]
        if indicator not in latest:
            latest[indicator] = row

    return latest


def get_price_row_count(supabase) -> int:
    """
    CHANGED:
    - Keep this only as a coarse empty-table check.
    Why:
    - For this script we only need to know whether prices is empty or not.
    - We no longer use this to infer per-asset coverage.
    """
    rows = (
        supabase.table("prices")
        .select("asset_id")
        .limit(1)
        .execute()
        .data
    )
    return len(rows or [])


def get_macro_row_count(supabase) -> int:
    """
    CHANGED:
    - Keep this only as a coarse empty-table check.
    """
    rows = (
        supabase.table("macro_indicators")
        .select("indicator")
        .limit(1)
        .execute()
        .data
    )
    return len(rows or [])


# -------------------- CHECK HELPERS --------------------
def check_ingestion_results(
    market_result: dict[str, Any],
    macro_result: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    market_failures = market_result.get("failures", [])
    macro_failures = macro_result.get("failures", [])

    if market_failures:
        errors.append(f"Market data fetch failures: {market_failures}")

    if macro_failures:
        errors.append(f"Macro data fetch failures: {macro_failures}")

    return errors


def check_active_assets_have_prices(supabase) -> list[str]:
    issues: list[str] = []

    active_assets = get_active_assets(supabase)
    if not active_assets:
        issues.append("No active assets found in assets table")
        return issues

    missing_assets = []

    for asset in active_assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]

        if not asset_has_price_data(supabase, asset_id):
            missing_assets.append(ticker)

    if missing_assets:
        issues.append(
            f"Active assets missing price data: {', '.join(sorted(missing_assets))}"
        )

    return issues


def check_required_macro_indicators(supabase) -> list[str]:
    issues: list[str] = []

    snapshot = get_macro_snapshot(supabase)
    found = set(snapshot.keys())
    missing = REQUIRED_MACRO_INDICATORS - found

    if missing:
        issues.append(
            f"Missing required macro indicators: {', '.join(sorted(missing))}"
        )

    return issues


def check_minimum_row_counts(supabase) -> list[str]:
    issues: list[str] = []

    price_count = get_price_row_count(supabase)
    macro_count = get_macro_row_count(supabase)

    if price_count == 0:
        issues.append("Prices table is empty")

    if macro_count == 0:
        issues.append("Macro indicators table is empty")

    return issues


def summarize_validation(validation: dict[str, Any]) -> None:
    print_section("DATA QUALITY STATUS")
    print(f"Overall Status: {validation['status'].upper()}")

    for check_name, details in validation.get("checks", {}).items():
        check_status = details.get("status", "unknown").upper()
        print(f"- {check_name}: {check_status}")

        issues = details.get("details", [])
        if issues:
            for issue in issues[:5]:
                print(f"    - {issue}")

            if len(issues) > 5:
                print(f"    ... and {len(issues) - 5} more")


def print_ingestion_summary(
    market_result: dict[str, Any],
    macro_result: dict[str, Any],
    vix_result: dict[str, Any],
) -> None:
    print_section("INGESTION STATUS")

    print(
        f"Market Data  -> "
        f"{market_result.get('tickers_processed', 0)} tickers | "
        f"{market_result.get('rows_inserted', 0)} rows | "
        f"{len(market_result.get('failures', []))} failures"
    )

    print(
        f"Macro Data   -> "
        f"{macro_result.get('indicators_processed', 0)} indicators | "
        f"{macro_result.get('rows_inserted', 0)} rows | "
        f"{len(macro_result.get('failures', []))} failures"
    )

    print(
        f"VIX          -> "
        f"{vix_result.get('rows_inserted', 0)} rows | "
        f"Latest: {vix_result.get('latest_value')}"
    )


def print_sample_market_data(supabase) -> None:
    print_section("SAMPLE MARKET DATA")
    prices = get_latest_prices(supabase, limit=10)

    if not prices:
        print("No price data available")
        return

    for row in prices[:5]:
        print(
            f"{row['date']} | "
            f"asset_id={row['asset_id']} | "
            f"Close={row['close']} | "
            f"Return={row['daily_return']}"
        )


def print_macro_snapshot(supabase) -> None:
    print_section("MACRO SNAPSHOT")
    macro = get_macro_snapshot(supabase)

    if not macro:
        print("No macro data available")
        return

    for indicator in sorted(macro.keys()):
        row = macro[indicator]
        print(f"{indicator}: {row['value']} (date: {row['date']})")


# -------------------- MAIN --------------------
def run_pipeline_health_check() -> None:
    print_header()
    start_time = datetime.now()

    # ---------- Run ingestion ----------
    print_section("RUNNING INGESTION")
    market_result = fetch_market_data()
    macro_result = fetch_macro_data()
    vix_result = fetch_vix()

    # ---------- Run validation ----------
    print_section("RUNNING VALIDATION")
    validation = validate_data()

    # ---------- Print summaries ----------
    print_ingestion_summary(market_result, macro_result, vix_result)
    summarize_validation(validation)

    # ---------- Extra database checks ----------
    supabase = get_supabase()

    print_section("EXTRA SAFETY CHECKS")
    issues: list[str] = []
    issues.extend(check_ingestion_results(market_result, macro_result))
    issues.extend(check_active_assets_have_prices(supabase))
    issues.extend(check_required_macro_indicators(supabase))
    issues.extend(check_minimum_row_counts(supabase))

    if validation.get("status") == "fail":
        issues.append("Validator returned FAIL status")
    elif validation.get("status") == "warn":
        issues.append("Validator returned WARN status; investigate before training")

    if issues:
        for issue in issues:
            if "WARN" in issue or "warn" in issue:
                print_warning(issue)
            else:
                print_error(issue)
    else:
        print_success("All extra safety checks passed")

    # ---------- Preview data ----------
    print_sample_market_data(supabase)
    print_macro_snapshot(supabase)

    # ---------- Final result ----------
    duration = datetime.now() - start_time

    print("\n" + "=" * 70)
    if issues:
        print("PIPELINE HEALTH CHECK FAILED")
        print(f"Completed in: {duration}")
        print("=" * 70)
        raise RuntimeError(
            "Pipeline is not safe enough for model training. Review the issues above."
        )
    else:
        print("PIPELINE HEALTH CHECK PASSED")
        print(f"Completed in: {duration}")
        print("=" * 70)


# -------------------- CLI --------------------
if __name__ == "__main__":
    try:
        run_pipeline_health_check()
    except Exception as exc:
        print_error(str(exc))
        sys.exit(1)