#Author: @ShoumikDutta
"""
Daily pipeline orchestrator.
Runs full ingestion + validation in correct order.
"""

from datetime import datetime

from src.ingestion.fetch_market_data import fetch_market_data
from src.ingestion.fetch_macro_data import fetch_macro_data
from src.ingestion.fetch_vix import fetch_vix
from src.ingestion.data_validator import validate_data


def run_daily_pipeline():
    print("\n==============================")
    print("🚀 FINTHYRA DAILY PIPELINE")
    print("==============================\n")

    start = datetime.now()

    # ---------- INGESTION ----------
    print("📥 Running market data ingestion...")
    market_result = fetch_market_data()

    print("📥 Running macro data ingestion...")
    macro_result = fetch_macro_data()

    print("📥 Running VIX ingestion...")
    vix_result = fetch_vix()

    # ---------- VALIDATION ----------
    print("\n🔍 Running validation...")
    validation = validate_data()

    # ---------- SUMMARY ----------
    print("\n==============================")
    print("📊 PIPELINE SUMMARY")
    print("==============================")

    print(f"Market: {market_result}")
    print(f"Macro: {macro_result}")
    print(f"VIX: {vix_result}")
    print(f"Validation: {validation['status']}")

    duration = datetime.now() - start
    print(f"\n⏱ Completed in: {duration}")

    # ---------- FAIL SAFE ----------
    if validation["status"] != "pass":
        raise RuntimeError("❌ Pipeline failed validation check")

    print("\n✅ Pipeline completed successfully!")


if __name__ == "__main__":
    run_daily_pipeline()

