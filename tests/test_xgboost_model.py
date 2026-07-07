"""Unit tests for xgboost_model.py — fully mocked, no network/DB/real training."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import xgboost as xgb

from src.models.xgboost_model import (
    _create_pseudo_labels,
    score_today,
    train_model,
    write_anomaly_results,
    run_anomaly_detection,
)

# -------------------- Helpers --------------------


def make_features_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Create a synthetic features DataFrame for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "asset_id": [1] * n,
            "ticker": ["SPY"] * n,
            "date": dates,
            "rolling_volatility_20d": rng.uniform(0.005, 0.03, n),
            "rolling_return_20d": rng.uniform(-0.05, 0.05, n),
            "return_zscore_20d": rng.normal(0, 1, n),
            "drawdown": rng.uniform(-0.15, 0, n),
            "drawdown_acceleration": rng.uniform(-0.05, 0.05, n),
            "volume_zscore_20d": rng.normal(0, 1, n),
            "vix_level": rng.uniform(15, 35, n),
            "fed_funds_rate": rng.uniform(4.0, 5.5, n),
            "treasury_yield_10y": rng.uniform(3.5, 5.0, n),
        }
    )


def make_normal_row() -> pd.DataFrame:
    """Single row representing a completely normal trading day."""
    return pd.DataFrame(
        [
            {
                "asset_id": 1,
                "ticker": "SPY",
                "date": pd.Timestamp("2024-06-01"),
                "rolling_volatility_20d": 0.010,  # normal
                "rolling_return_20d": 0.005,
                "return_zscore_20d": 0.5,  # within normal range
                "drawdown": -0.02,  # shallow drawdown
                "drawdown_acceleration": 0.001,  # not worsening
                "volume_zscore_20d": 0.8,  # normal volume
                "vix_level": 18.0,
                "fed_funds_rate": 5.0,
                "treasury_yield_10y": 4.0,
            }
        ]
    )


def make_anomaly_row(
    volatility: float = 0.10,
    zscore: float = 0.0,
    drawdown: float = -0.02,
    dd_acc: float = 0.0,
    vol_z: float = 0.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "asset_id": 1,
                "ticker": "SPY",
                "date": pd.Timestamp("2024-06-01"),
                "rolling_volatility_20d": volatility,
                "rolling_return_20d": 0.005,
                "return_zscore_20d": zscore,
                "drawdown": drawdown,
                "drawdown_acceleration": dd_acc,
                "volume_zscore_20d": vol_z,
                "vix_level": 18.0,
                "fed_funds_rate": 5.0,
                "treasury_yield_10y": 4.0,
            }
        ]
    )


# -------------------- Pseudo-label tests --------------------


def test_pseudo_label_high_volatility_triggers_anomaly():
    df = make_features_df(80)
    # Force last row to have extreme volatility far above 95th percentile
    df.loc[df.index[-1], "rolling_volatility_20d"] = 1.0  # clearly above 95th pct
    labelled = _create_pseudo_labels(df)
    assert labelled.iloc[-1]["anomaly"] == 1
    assert "volatility_anomaly" in labelled.iloc[-1]["anomaly_type"]


def test_pseudo_label_normal_row_is_non_anomaly():
    # Build a homogeneous dataset where the "normal" row doesn't stand out
    n = 60
    df = pd.DataFrame(
        {
            "asset_id": [1] * n,
            "ticker": ["TST"] * n,
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "rolling_volatility_20d": [0.010] * n,  # all equal → 95th pct = 0.010
            "rolling_return_20d": [0.001] * n,
            "return_zscore_20d": [0.5] * n,  # < 2.5
            "drawdown": [-0.02] * n,  # > -0.10
            "drawdown_acceleration": [0.001] * n,  # > -0.02
            "volume_zscore_20d": [0.5] * n,  # < 3.0
            "vix_level": [18.0] * n,
            "fed_funds_rate": [5.0] * n,
            "treasury_yield_10y": [4.0] * n,
        }
    )
    labelled = _create_pseudo_labels(df)
    # When all rows have the same volatility, 95th pct == that value → NOT strictly greater
    assert labelled["anomaly"].sum() == 0


def test_pseudo_label_extreme_return_zscore_triggers_return_anomaly():
    df = make_normal_row()
    df["return_zscore_20d"] = 3.5  # > 2.5
    labelled = _create_pseudo_labels(df)
    assert labelled.iloc[0]["anomaly"] == 1
    assert "return_anomaly" in labelled.iloc[0]["anomaly_type"]


def test_pseudo_label_negative_return_zscore_triggers_return_anomaly():
    df = make_normal_row()
    df["return_zscore_20d"] = -3.0  # abs > 2.5
    labelled = _create_pseudo_labels(df)
    assert labelled.iloc[0]["anomaly"] == 1
    assert "return_anomaly" in labelled.iloc[0]["anomaly_type"]


def test_pseudo_label_deep_accelerating_drawdown_triggers_drawdown_anomaly():
    df = make_normal_row()
    df["drawdown"] = -0.15  # < -0.10
    df["drawdown_acceleration"] = -0.03  # < -0.02
    labelled = _create_pseudo_labels(df)
    assert labelled.iloc[0]["anomaly"] == 1
    assert "drawdown_anomaly" in labelled.iloc[0]["anomaly_type"]


def test_pseudo_label_volume_spike_triggers_volume_anomaly():
    df = make_normal_row()
    df["volume_zscore_20d"] = 4.0  # > 3.0
    labelled = _create_pseudo_labels(df)
    assert labelled.iloc[0]["anomaly"] == 1
    assert "volume_anomaly" in labelled.iloc[0]["anomaly_type"]


def test_pseudo_label_anomaly_type_contains_correct_trigger_names():
    df = make_normal_row()
    df["return_zscore_20d"] = 3.5
    df["volume_zscore_20d"] = 4.0
    labelled = _create_pseudo_labels(df)
    atype = labelled.iloc[0]["anomaly_type"]
    assert "return_anomaly" in atype
    assert "volume_anomaly" in atype


# -------------------- train_model --------------------


def test_train_model_returns_xgboost_classifier():
    df = make_features_df(200)
    model = train_model(df)
    assert isinstance(model, xgb.XGBClassifier)


def test_train_model_scale_pos_weight_is_set():
    df = make_features_df(200)
    # Force some anomalies so scale_pos_weight > 1
    df.loc[df.index[:10], "return_zscore_20d"] = 5.0
    model = train_model(df)
    assert model.get_params()["scale_pos_weight"] >= 1.0


# -------------------- score_today --------------------


def test_score_today_returns_correct_dict_structure():
    df = make_features_df(200)
    model = train_model(df)
    today = make_normal_row()
    results = score_today(model, today)
    assert len(results) == 1
    result = results[0]
    assert "asset_id" in result
    assert "ticker" in result
    assert "anomaly_flag" in result
    assert "anomaly_score" in result
    assert "anomaly_type" in result
    assert isinstance(result["anomaly_flag"], bool)


def test_score_today_anomaly_score_is_between_0_and_1():
    df = make_features_df(200)
    model = train_model(df)
    today = make_normal_row()
    results = score_today(model, today)
    score = results[0]["anomaly_score"]
    assert 0.0 <= score <= 1.0


def test_score_today_empty_features_returns_empty_list():
    df = make_features_df(200)
    model = train_model(df)
    results = score_today(model, pd.DataFrame())
    assert results == []


# -------------------- write_anomaly_results --------------------


def test_write_anomaly_results_calls_update_not_insert():
    with patch("src.models.xgboost_model.get_supabase") as mock_get_supabase:
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        # Mock the SELECT to confirm row exists
        existing_mock = MagicMock()
        existing_mock.data = [{"portfolio_id": 1}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            existing_mock
        )

        results = [
            {
                "anomaly_flag": True,
                "anomaly_score": 0.75,
                "anomaly_type": "return_anomaly",
                "asset_id": 1,
                "ticker": "SPY",
            }
        ]
        write_anomaly_results(results, portfolio_id=1, target_date="2024-06-01")

        # Verify update was called, not insert or upsert
        mock_supabase.table.return_value.update.assert_called_once()
        mock_supabase.table.return_value.insert.assert_not_called()
        mock_supabase.table.return_value.upsert.assert_not_called()


def test_write_anomaly_results_skips_when_no_existing_row():
    with patch("src.models.xgboost_model.get_supabase") as mock_get_supabase:
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        # No existing row
        existing_mock = MagicMock()
        existing_mock.data = []
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            existing_mock
        )

        results = [
            {
                "anomaly_flag": True,
                "anomaly_score": 0.75,
                "anomaly_type": "return_anomaly",
                "asset_id": 1,
                "ticker": "SPY",
            }
        ]
        write_anomaly_results(results, portfolio_id=99, target_date="2024-06-01")

        # update should NOT have been called
        mock_supabase.table.return_value.update.assert_not_called()


# -------------------- run_anomaly_detection --------------------


def test_run_anomaly_detection_returns_success_dict_on_happy_path():
    hist_df = make_features_df(300)
    today_df = make_features_df(1, seed=99)
    today_df["date"] = pd.Timestamp("2024-06-01")

    with (
        patch("src.models.xgboost_model.get_supabase") as mock_get_supabase,
        patch("src.models.xgboost_model.build_features", return_value=hist_df),
        patch(
            "src.models.xgboost_model.build_features_for_date", return_value=today_df
        ),
        patch("src.models.xgboost_model.write_anomaly_results"),
    ):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        portfolio_mock = MagicMock()
        portfolio_mock.data = [{"id": 1}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            portfolio_mock
        )

        result = run_anomaly_detection()

    assert result["status"] == "success"
    assert "assets_scored" in result
    assert "anomalies_found" in result
    assert result["error"] is None


def test_run_anomaly_detection_returns_failure_dict_on_exception():
    with (
        patch("src.models.xgboost_model.get_supabase") as mock_get_supabase,
        patch(
            "src.models.xgboost_model.build_features",
            side_effect=RuntimeError("DB down"),
        ),
    ):
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        portfolio_mock = MagicMock()
        portfolio_mock.data = [{"id": 1}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            portfolio_mock
        )

        result = run_anomaly_detection()

    assert result["status"] == "failure"
    assert result["error"] is not None
    assert "DB down" in result["error"]
    assert result["assets_scored"] == 0
