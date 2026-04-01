# Author: @ShoumikDutta
"""
Test script to simulate Streamlit dashboard output.
Runs ingestion + validation + prints structured output.
"""

from datetime import datetime
from pprint import pprint

from src.ingestion.fetch_market_data import fetch_market_data
from src.ingestion.fetch_macro_data import fetch_macro_data
from src.ingestion.fetch_vix import fetch_vix
from src.ingestion.data_validator import validate_data
from src.ingestion.common import get_supabase


# -------------------- HELPERS --------------------
def print_header():
    print("\n" + "=" * 65)
    print("📊 FINTHYRA DASHBOARD (PREVIEW)")
    print("=" * 65)


def print_section(title):
    print(f"\n--- {title} ---")


# -------------------- SAMPLE DATA FETCH --------------------
def get_sample_prices(supabase):
    rows = (
        supabase.table("prices")
        .select("date,close,daily_return,asset_id")
        .order("date", desc=True)
        .limit(10)
        .execute()
        .data
    )
    return rows


def get_macro_snapshot(supabase):
    rows = (
        supabase.table("macro_indicators")
        .select("indicator,value,date")
        .order("date", desc=True)
        .execute()
        .data
    )

    latest = {}
    for r in rows:
        if r["indicator"] not in latest:
            latest[r["indicator"]] = r

    return latest


# -------------------- MAIN --------------------
def run_pipeline_test():
    print_header()

    # ---------- Run ingestion ----------
    print_section("🚀 RUNNING INGESTION")

    market_result = fetch_market_data()
    macro_result = fetch_macro_data()
    vix_result = fetch_vix()

    # ---------- Run validation ----------
    print_section("🧪 DATA VALIDATION")
    validation = validate_data()

    # ---------- Print ingestion summary ----------
    print_section("📊 INGESTION STATUS")

    print(
        f"Market Data  -> {market_result['tickers_processed']} tickers | "
        f"{market_result['rows_inserted']} rows | "
        f"{len(market_result['failures'])} failures"
    )

    print(
        f"Macro Data   -> {macro_result['indicators_processed']} indicators | "
        f"{macro_result['rows_inserted']} rows"
    )

    print(
        f"VIX          -> {vix_result['rows_inserted']} rows | "
        f"Latest: {vix_result['latest_value']}"
    )

    # ---------- Validation ----------
    print_section("🧪 DATA QUALITY STATUS")
    print(f"Status: {validation['status'].upper()}")

    for check, details in validation["checks"].items():
        if details["details"]:
            print(f"\n⚠ {check.upper()}:")
            for issue in details["details"][:5]:
                print(f" - {issue}")

    # ---------- Fetch sample data ----------
    supabase = get_supabase()

    # ---------- Prices ----------
    print_section("📈 SAMPLE MARKET DATA")
    prices = get_sample_prices(supabase)

    if prices:
        for r in prices[:5]:
            print(
                f"{r['date']} | Close: {r['close']} | Return: {r['daily_return']}"
            )
    else:
        print("No price data available")

    # ---------- Macro ----------
    print_section("🌍 MACRO SNAPSHOT")
    macro = get_macro_snapshot(supabase)

    for k, v in macro.items():
        print(f"{k}: {v['value']} (date: {v['date']})")

    print("\n" + "=" * 65)
    print("✅ PIPELINE TEST COMPLETE")
    print("=" * 65)


# -------------------- CLI --------------------
if __name__ == "__main__":
    run_pipeline_test()