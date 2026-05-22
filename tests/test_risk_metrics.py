"""Unit tests for risk metric calculations."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.processing.risk_metrics import (
    compute_beta,
    compute_max_drawdown,
    compute_portfolio_returns,
    compute_risk_metrics,
    compute_sharpe,
    compute_var,
    write_risk_metrics,
)


def make_returns(values: list, freq: str = "B") -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=len(values), freq=freq)
    return pd.Series(values, index=dates)


# -------------------- VaR --------------------

def test_compute_var_95():
    returns = pd.Series(np.linspace(-0.10, 0.10, 100))
    expected = float(np.percentile(returns, 5.0))
    assert compute_var(returns, confidence=0.95) == pytest.approx(expected, rel=1e-6)


def test_compute_var_99():
    returns = pd.Series(np.linspace(-0.10, 0.10, 100))
    expected = float(np.percentile(returns, 1.0))
    assert compute_var(returns, confidence=0.99) == pytest.approx(expected, rel=1e-6)


# -------------------- Sharpe --------------------

def test_compute_sharpe_positive():
    # Alternating values give mean=0.002 with non-zero std
    returns = pd.Series([0.001, 0.003] * 126)
    result = compute_sharpe(returns, daily_risk_free=0.0001)
    assert result > 0


def test_compute_sharpe_zero_std():
    returns = make_returns([0.001] * 100)
    result = compute_sharpe(returns, daily_risk_free=0.0)
    assert result == 0.0


# -------------------- Max Drawdown --------------------

def test_compute_max_drawdown_flat():
    returns = make_returns([0.0] * 100)
    result = compute_max_drawdown(returns)
    assert result == pytest.approx(0.0, abs=1e-9)


def test_compute_max_drawdown_decline():
    returns = make_returns([-0.01] * 100)
    result = compute_max_drawdown(returns)
    assert result < 0


# -------------------- Beta --------------------

def test_compute_beta_aligned():
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=100, freq="B")
    values = rng.normal(0, 0.01, 100)
    portfolio = pd.Series(values, index=dates)
    benchmark = pd.Series(values, index=dates)
    result = compute_beta(portfolio, benchmark)
    assert result is not None
    assert result == pytest.approx(1.0, rel=1e-4)


def test_compute_beta_insufficient_data():
    dates = pd.date_range("2024-01-01", periods=20, freq="B")
    portfolio = pd.Series(np.full(20, 0.01), index=dates)
    benchmark = pd.Series(np.full(20, 0.01), index=dates)
    result = compute_beta(portfolio, benchmark)
    assert result is None


# -------------------- Portfolio Returns --------------------

def test_compute_portfolio_returns_weighted():
    dates = pd.date_range("2024-01-01", periods=3, freq="B")
    df = pd.DataFrame({
        "date": list(dates) * 2,
        "asset_id": [1, 1, 1, 2, 2, 2],
        "daily_return": [0.04, 0.08, 0.02, 0.02, 0.06, 0.10],
    })
    weights = {1: 0.5, 2: 0.5}
    result = compute_portfolio_returns(df, weights)
    expected = np.array([0.03, 0.07, 0.06])
    np.testing.assert_allclose(result.values, expected, atol=1e-9)


# -------------------- Write --------------------

def test_write_risk_metrics_upsert_called():
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    metrics = {
        "var_95": -0.02,
        "var_99": -0.04,
        "sharpe_ratio": 1.2,
        "max_drawdown": -0.15,
        "beta_vs_benchmark": 0.9,
    }
    write_risk_metrics(mock_supabase, portfolio_id=1, metrics=metrics)
    mock_supabase.table.assert_called_with("risk_metrics")
    mock_supabase.table.return_value.upsert.assert_called_once()


def test_write_risk_metrics_raises_on_db_failure():
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.upsert.return_value.execute.side_effect = Exception(
        "connection refused"
    )
    with pytest.raises(RuntimeError, match="Supabase write failed"):
        write_risk_metrics(mock_supabase, portfolio_id=1, metrics={})


# -------------------- Orchestrator --------------------

def test_compute_risk_metrics_returns_failure_on_exception():
    with patch("src.processing.risk_metrics.get_supabase") as mock_get_supabase:
        mock_supabase = MagicMock()
        mock_get_supabase.return_value = mock_supabase

        # Mock portfolio_configurations query to return a valid portfolio
        mock_execute_result = MagicMock()
        mock_execute_result.data = [{"id": 1}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            mock_execute_result
        )

        with patch(
            "src.processing.risk_metrics.load_portfolio_holdings",
            return_value={1: 1.0},
        ):
            with patch(
                "src.processing.risk_metrics.load_prices",
                side_effect=Exception("DB down"),
            ):
                result = compute_risk_metrics()

    assert result["status"] == "failure"
    assert result["error"] is not None
    assert "DB down" in result["error"]
