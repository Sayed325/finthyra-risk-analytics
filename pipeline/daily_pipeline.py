# Author: @ShoumikDutta
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, UTC
from typing import Any

from src.ingestion.common import get_logger
from src.ingestion.fetch_market_data import fetch_market_data
from src.ingestion.fetch_macro_data import fetch_macro_data
from src.ingestion.fetch_vix import fetch_vix
from src.ingestion.data_validator import validate_data
from src.processing.risk_metrics import compute_risk_metrics
from src.models.xgboost_model import run_anomaly_detection
from src.ai_analyst.gemini_commentary import generate_commentary

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

    # ---------- RISK METRICS ----------
    if validation["status"] == "fail":
        logger.warning("Skipping risk metrics — validation failed")
        risk_result: dict = {"status": "skipped", "error": "validation failed"}
    else:
        risk_result = compute_risk_metrics()
        logger.info(
            f"risk_metrics={risk_result.get('status')} | var_95={risk_result.get('var_95')}"
        )

    # ---------- ANOMALY DETECTION ----------
    if risk_result.get("status") != "success":
        logger.warning(
            f"Skipping anomaly detection — risk_metrics status={risk_result.get('status')!r}"
        )
        anomaly_result: dict = {"status": "skipped", "error": f"risk_metrics {risk_result.get('status')}"}
    else:
        try:
            anomaly_result = run_anomaly_detection()
            logger.info(
                f"anomaly_detection={anomaly_result.get('status')} | "
                f"anomalies_found={anomaly_result.get('anomalies_found', 0)}"
            )
        except Exception as exc:
            logger.error(f"anomaly_detection raised unexpectedly: {exc}")
            anomaly_result = {"status": "failure", "error": str(exc)}

    # ---------- GEMINI COMMENTARY ----------
    if risk_result.get("status") == "success":
        try:
            gemini_result = generate_commentary()
            logger.info(
                f"gemini_commentary={gemini_result.get('status')}"
            )
        except Exception as exc:
            logger.error(f"gemini_commentary raised unexpectedly: {exc}")
            gemini_result = {"status": "failure", "error": str(exc)}
    else:
        logger.warning(
            f"Skipping Gemini commentary — risk_metrics status={risk_result.get('status')!r}"
        )
        gemini_result: dict = {"status": "skipped", "error": "risk_metrics not successful"}

    duration_seconds = round((datetime.now(UTC) - start).total_seconds(), 2)

    result = {
        "market": market_result,
        "macro": macro_result,
        "vix": vix_result,
        "validation": validation,
        "risk_metrics": risk_result,
        "anomaly_detection": anomaly_result,
        "gemini_commentary": gemini_result,
        "duration_seconds": duration_seconds,
    }

    logger.info(
        f"Pipeline summary | "
        f"market_rows={market_result.get('rows_inserted', 0)} | "
        f"macro_rows={macro_result.get('rows_inserted', 0)} | "
        f"vix_rows={vix_result.get('rows_inserted', 0)} | "
        f"validation={validation['status']} | "
        f"risk_metrics={risk_result.get('status')} | "
        f"anomalies_found={anomaly_result.get('anomalies_found', 0)} | "
        f"gemini={gemini_result.get('status')} | "
        f"duration={duration_seconds}s"
    )

    # ---------- FAIL SAFE ----------
    if validation["status"] == "fail":
        raise RuntimeError(
            f"Pipeline stopped because validation status was '{validation['status']}'"
        )
    elif validation["status"] == "warn":
        logger.warning(
            f"Validation returned 'warn' — pipeline continuing. "
            f"Review: {validation['checks']}"
        )

    logger.info("Pipeline completed successfully")
    return result


if __name__ == "__main__":
    output = run_daily_pipeline()
    print(output)