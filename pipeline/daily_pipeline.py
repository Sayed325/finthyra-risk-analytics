# Author: @ShoumikDutta
from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from src.ingestion.common import get_logger
from src.ingestion.fetch_market_data import fetch_market_data
from src.ingestion.fetch_macro_data import fetch_macro_data
from src.ingestion.fetch_vix import fetch_vix
from src.ingestion.data_validator import validate_data

logger = get_logger("daily_pipeline")


def run_daily_pipeline() -> dict[str, Any]:
    """
    CHANGED:
    - Replaced print-heavy orchestration with logging + structured return.
    WHY:
    - Easier to debug, test, and use later in CI or automation.
    """
    start = datetime.now(UTC)

    logger.info("Starting Finthyra daily pipeline")

    # ---------- INGESTION ----------
    logger.info("Running market data ingestion")
    market_result = fetch_market_data()

    logger.info("Running macro data ingestion")
    macro_result = fetch_macro_data()

    logger.info("Running VIX ingestion")
    vix_result = fetch_vix()

    # ---------- VALIDATION ----------
    logger.info("Running data validation")
    validation = validate_data()

    duration_seconds = round((datetime.now(UTC) - start).total_seconds(), 2)

    result = {
        "market": market_result,
        "macro": macro_result,
        "vix": vix_result,
        "validation": validation,
        "duration_seconds": duration_seconds,
    }

    logger.info(
        f"Pipeline summary | "
        f"market_rows={market_result.get('rows_inserted', 0)} | "
        f"macro_rows={macro_result.get('rows_inserted', 0)} | "
        f"vix_rows={vix_result.get('rows_inserted', 0)} | "
        f"validation={validation['status']} | "
        f"duration={duration_seconds}s"
    )

    # ---------- FAIL SAFE ----------
    if validation["status"] != "pass":
        """
        CHANGED:
        - Pipeline still fails if validation is not pass.
        WHY:
        - This protects downstream risk metrics / ML training from bad or incomplete data.
        """
        raise RuntimeError(
            f"Pipeline stopped because validation status was '{validation['status']}'"
        )

    logger.info("Pipeline completed successfully")
    return result


if __name__ == "__main__":
    output = run_daily_pipeline()
    print(output)