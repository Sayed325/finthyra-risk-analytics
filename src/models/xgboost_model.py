"""XGBoost anomaly/risk flagging model."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report

from src.ingestion.common import get_logger, get_supabase
from src.processing.feature_engineering import build_features, build_features_for_date

logger = get_logger("xgboost_model")

FEATURE_COLS = [
    "rolling_volatility_20d",
    "rolling_return_20d",
    "return_zscore_20d",
    "drawdown",
    "drawdown_acceleration",
    "volume_zscore_20d",
    "vix_level",
    "fed_funds_rate",
    "treasury_yield_10y",
]


# -------------------- LABELLING --------------------

def _create_pseudo_labels(features_df: pd.DataFrame) -> pd.DataFrame:
    """Create binary anomaly labels from statistical thresholds per asset.

    Returns features_df with added columns: anomaly, anomaly_type.
    """
    df = features_df.copy()

    # Compute 95th percentile volatility threshold per asset
    vol_95 = (
        df.groupby("asset_id")["rolling_volatility_20d"]
        .transform(lambda x: x.quantile(0.95))
    )

    volatility_flag = df["rolling_volatility_20d"] > vol_95
    return_flag = df["return_zscore_20d"].abs() > 2.5
    drawdown_flag = (df["drawdown"] < -0.10) & (df["drawdown_acceleration"] < -0.02)
    volume_flag = df["volume_zscore_20d"] > 3.0

    def _anomaly_type(row_flags: pd.DataFrame) -> pd.Series:
        types = []
        if row_flags["volatility_flag"]:
            types.append("volatility_anomaly")
        if row_flags["return_flag"]:
            types.append("return_anomaly")
        if row_flags["drawdown_flag"]:
            types.append("drawdown_anomaly")
        if row_flags["volume_flag"]:
            types.append("volume_anomaly")
        return ",".join(types) if types else ""

    flags_df = pd.DataFrame({
        "volatility_flag": volatility_flag,
        "return_flag": return_flag,
        "drawdown_flag": drawdown_flag,
        "volume_flag": volume_flag,
    })

    df["anomaly"] = (volatility_flag | return_flag | drawdown_flag | volume_flag).astype(int)
    df["anomaly_type"] = flags_df.apply(_anomaly_type, axis=1)

    return df


# -------------------- TRAINING --------------------

def train_model(features_df: pd.DataFrame) -> xgb.XGBClassifier:
    """Train XGBClassifier with pseudo-labels on historical feature data.

    Uses walk-forward split: 70% train / 15% val / 15% test.
    Returns the trained model fit on the full training portion.
    """
    labelled = _create_pseudo_labels(features_df)
    labelled = labelled.sort_values("date").reset_index(drop=True)

    n = len(labelled)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)

    train_df = labelled.iloc[:train_end]
    val_df = labelled.iloc[train_end:val_end]
    test_df = labelled.iloc[val_end:]

    X_train = train_df[FEATURE_COLS].fillna(0)
    y_train = train_df["anomaly"]
    X_val = val_df[FEATURE_COLS].fillna(0)
    y_val = val_df["anomaly"]
    X_test = test_df[FEATURE_COLS].fillna(0)
    y_test = test_df["anomaly"]

    n_pos = int(y_train.sum())
    n_neg = int((y_train == 0).sum())

    logger.info(
        f"Training set: {len(X_train)} rows | "
        f"anomaly_rate_train={n_pos / max(len(y_train), 1):.2%} | "
        f"anomaly_rate_val={y_val.mean():.2%} | "
        f"anomaly_rate_test={y_test.mean():.2%}"
    )

    scale_pos_weight = n_neg / max(n_pos, 1)

    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )

    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    if len(X_test) > 0 and y_test.nunique() > 1:
        y_pred = model.predict(X_test)
        report = classification_report(y_test, y_pred, output_dict=True)
        logger.info(
            f"Walk-forward test metrics — "
            f"precision={report.get('1', {}).get('precision', 0):.3f} | "
            f"recall={report.get('1', {}).get('recall', 0):.3f} | "
            f"f1={report.get('1', {}).get('f1-score', 0):.3f}"
        )
    else:
        logger.warning("Test set too small or single class — skipping classification report")

    return model


# -------------------- SCORING --------------------

def score_today(
    model: xgb.XGBClassifier, features_df: pd.DataFrame
) -> list[dict[str, Any]]:
    """Score today's features and return per-asset anomaly results.

    Returns list of dicts with keys: asset_id, ticker, anomaly_flag, anomaly_score, anomaly_type.
    """
    if features_df.empty:
        logger.warning("score_today: empty features DataFrame — returning empty results")
        return []

    labelled = _create_pseudo_labels(features_df)
    X = labelled[FEATURE_COLS].fillna(0)
    proba = model.predict_proba(X)[:, 1]

    results = []
    for i, (_, row) in enumerate(labelled.iterrows()):
        score = round(float(proba[i]), 4)
        flag = bool(score > 0.5)
        anomaly_type_str = row["anomaly_type"] if row["anomaly_type"] else None

        results.append({
            "asset_id": int(row["asset_id"]),
            "ticker": str(row["ticker"]),
            "anomaly_flag": flag,
            "anomaly_score": score,
            "anomaly_type": anomaly_type_str,
        })

        logger.info(
            f"{row['ticker']}: anomaly_score={score:.4f} flag={flag}"
            + (f" type={anomaly_type_str}" if anomaly_type_str else "")
        )

    return results


# -------------------- WRITE --------------------

def write_anomaly_results(
    results: list[dict[str, Any]], portfolio_id: int, target_date: str
) -> None:
    """UPDATE existing risk_metrics row for (portfolio_id, target_date) with anomaly columns.

    Aggregates per-asset results to portfolio level:
    - anomaly_flag = ANY asset flagged
    - anomaly_score = MAX score across all assets
    - anomaly_type = comma-separated unique types from flagged assets
    """
    supabase = get_supabase()

    # Check row exists
    existing = (
        supabase.table("risk_metrics")
        .select("portfolio_id")
        .eq("portfolio_id", portfolio_id)
        .eq("date", target_date)
        .execute()
    )
    if not (existing.data or []):
        logger.error(
            f"No risk_metrics row found for portfolio_id={portfolio_id}, date={target_date}. "
            "Run risk_metrics.py first."
        )
        return

    any_flag = any(r["anomaly_flag"] for r in results)
    max_score = max((r["anomaly_score"] for r in results), default=0.0)

    type_parts: list[str] = []
    for r in results:
        if r["anomaly_flag"] and r["anomaly_type"]:
            type_parts.extend(r["anomaly_type"].split(","))
    unique_types = ",".join(sorted(set(type_parts))) if type_parts else None

    logger.info(
        f"Portfolio anomaly summary: flag={any_flag} score={max_score:.4f} type={unique_types}"
    )

    supabase.table("risk_metrics").update({
        "anomaly_flag": any_flag,
        "anomaly_score": round(max_score, 4),
        "anomaly_type": unique_types,
    }).eq("portfolio_id", portfolio_id).eq("date", target_date).execute()


# -------------------- ORCHESTRATOR --------------------

def run_anomaly_detection(portfolio_id: int | None = None) -> dict[str, Any]:
    """Full anomaly detection pipeline: load → train → score → write.

    Returns {"status": "success"|"failure", "assets_scored": int, "anomalies_found": int, "error": str|None}.
    """
    try:
        supabase = get_supabase()

        if portfolio_id is None:
            response = (
                supabase.table("portfolio_configurations")
                .select("id")
                .eq("is_default", True)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            if not rows:
                raise RuntimeError("No default portfolio found in portfolio_configurations")
            portfolio_id = rows[0]["id"]
            logger.info(f"Using default portfolio_id={portfolio_id}")

        # Load full feature history for training
        logger.info("Loading historical features for training")
        history_df = build_features()
        if history_df.empty:
            raise RuntimeError("No historical feature data available for training")

        # Train model
        logger.info(f"Training model on {len(history_df)} rows")
        model = train_model(history_df)

        # Get today's features
        target_date = date.today().isoformat()
        logger.info(f"Scoring features for date={target_date}")
        today_df = build_features_for_date(target_date=target_date)

        if today_df.empty:
            logger.warning(f"No features available for {target_date} — no scoring performed")
            return {
                "status": "success",
                "assets_scored": 0,
                "anomalies_found": 0,
                "error": None,
            }

        # Score
        results = score_today(model, today_df)
        anomalies_found = sum(1 for r in results if r["anomaly_flag"])
        logger.info(f"Scored {len(results)} assets — {anomalies_found} anomalies found")

        # Write to DB
        write_anomaly_results(results, portfolio_id, target_date)

        return {
            "status": "success",
            "assets_scored": len(results),
            "anomalies_found": anomalies_found,
            "error": None,
        }

    except Exception as exc:
        logger.error(f"run_anomaly_detection failed: {exc}")
        return {
            "status": "failure",
            "assets_scored": 0,
            "anomalies_found": 0,
            "error": str(exc),
        }


if __name__ == "__main__":
    import json
    result = run_anomaly_detection()
    print(json.dumps(result, indent=2, default=str))
