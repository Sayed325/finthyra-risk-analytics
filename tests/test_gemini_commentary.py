"""Unit tests for gemini_commentary.py — fully mocked, no network/DB/API calls."""
from __future__ import annotations

import itertools
import os
from unittest.mock import MagicMock, patch, call

import pytest

import src.ai_analyst.gemini_commentary as mod
from src.ai_analyst.gemini_commentary import (
    _load_keys,
    _call_gemini,
    _build_combinations,
    _load_risk_metrics,
    _load_latest_macro,
    _load_portfolio_holdings,
    _load_worst_performer,
    _build_prompt,
    _write_briefing,
    generate_commentary,
)
from pipeline.daily_pipeline import run_daily_pipeline


# -------------------- Fixtures --------------------

@pytest.fixture(autouse=True)
def reset_key_state():
    """Reset module-level key rotation state between tests."""
    original_keys = mod._keys[:]
    original_combinations = mod._combinations[:]
    original_cycle = mod._combination_cycle
    yield
    mod._keys = original_keys
    mod._combinations = original_combinations
    mod._combination_cycle = original_cycle


# -------------------- Key rotation tests --------------------

def test_load_keys_filters_empty():
    with patch.dict(os.environ, {
        "GEMINI_KEY_1": "valid_key_1",
        "GEMINI_KEY_2": "",
        "GEMINI_KEY_3": "valid_key_3",
        "GEMINI_KEY_4": "valid_key_4",
        "GEMINI_KEY_5": "",
    }):
        result = _load_keys()
    assert len(result) == 3
    assert "valid_key_1" in result
    assert "valid_key_3" in result
    assert "valid_key_4" in result


def test_load_keys_none_available():
    with patch.dict(os.environ, {
        "GEMINI_KEY_1": "",
        "GEMINI_KEY_2": "",
        "GEMINI_KEY_3": "",
        "GEMINI_KEY_4": "",
        "GEMINI_KEY_5": "",
    }):
        result = _load_keys()
    assert result == []


def test_round_robin_cycles_through_keys():
    keys = ["key_a", "key_b", "key_c"]
    combos = _build_combinations(keys)
    mod._keys = keys[:]
    mod._combinations = combos[:]
    mod._combination_cycle = itertools.cycle(combos[:])

    configured_keys = []
    mock_response = MagicMock()
    mock_response.text = "briefing"

    def mock_client_factory(api_key):
        configured_keys.append(api_key)
        client = MagicMock()
        client.models.generate_content.return_value = mock_response
        return client

    with patch("google.genai.Client", side_effect=mock_client_factory):
        _call_gemini("prompt1")
        _call_gemini("prompt2")
        _call_gemini("prompt3")

    # First 3 calls cycle key_a → key_b → key_c (all with gemini-2.5-flash first)
    assert configured_keys == ["key_a", "key_b", "key_c"]


def test_fallback_to_next_key_on_error():
    keys = ["key_fail", "key_ok"]
    combos = _build_combinations(keys)
    mod._keys = keys[:]
    mod._combinations = combos[:]
    mod._combination_cycle = itertools.cycle(combos[:])

    configured_keys = []
    call_count = [0]

    def mock_client_factory(api_key):
        configured_keys.append(api_key)
        call_count[0] += 1
        client = MagicMock()
        if call_count[0] == 1:
            client.models.generate_content.side_effect = Exception("Rate limit exceeded")
        else:
            resp = MagicMock()
            resp.text = "briefing text"
            client.models.generate_content.return_value = resp
        return client

    with patch("google.genai.Client", side_effect=mock_client_factory):
        result = _call_gemini("test prompt")

    assert result == "briefing text"
    assert "key_fail" in configured_keys
    assert "key_ok" in configured_keys


# -------------------- Data loading tests --------------------

def test_load_risk_metrics_returns_todays_row():
    supabase = MagicMock()
    expected = {
        "portfolio_id": 1, "date": "2026-05-21",
        "var_95": -0.02, "var_99": -0.03, "sharpe_ratio": 1.5,
        "max_drawdown": -0.1, "beta_vs_benchmark": 0.95,
        "anomaly_flag": False, "anomaly_score": 0.1, "anomaly_type": None,
    }
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [expected]

    result = _load_risk_metrics(supabase, 1, "2026-05-21")

    assert result is not None
    assert result["portfolio_id"] == 1
    assert result["var_95"] == -0.02


def test_load_risk_metrics_returns_none_when_no_row():
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    result = _load_risk_metrics(supabase, 1, "2026-05-21")

    assert result is None


def test_load_latest_macro_returns_all_indicators():
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.side_effect = [
        MagicMock(data=[{"value": 5.25}]),   # fed_funds_rate
        MagicMock(data=[{"value": 310.5}]),  # cpi
        MagicMock(data=[{"value": 4.30}]),   # treasury_yield_10y
        MagicMock(data=[{"value": 18.0}]),   # vix
        MagicMock(data=[{"value": 1.08}]),   # eur_usd_rate
    ]

    result = _load_latest_macro(supabase)

    assert len(result) == 5
    assert result["fed_funds_rate"] == 5.25
    assert result["cpi"] == 310.5
    assert result["treasury_yield_10y"] == 4.30
    assert result["vix"] == 18.0
    assert result["eur_usd_rate"] == 1.08


def test_load_worst_performer_returns_correct_asset():
    supabase = MagicMock()

    # portfolio_holdings: .select.rv.eq.rv.execute
    supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"asset_id": 1}, {"asset_id": 2}
    ]
    # prices (today): .select.rv.in_.rv.eq.rv.order.rv.limit.rv.execute
    supabase.table.return_value.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"asset_id": 2, "date": "2026-05-21", "daily_return": -0.03}
    ]
    # assets: .select.rv.eq.rv.limit.rv.execute
    supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"ticker": "TLT", "name": "T-Bond ETF"}
    ]

    result = _load_worst_performer(supabase, 1, "2026-05-21")

    assert result is not None
    assert result["ticker"] == "TLT"
    assert result["daily_return"] == pytest.approx(-0.03)


# -------------------- Prompt tests --------------------

def _make_risk_metrics(**kwargs) -> dict:
    base = {
        "var_95": -0.0215, "var_99": -0.0312, "sharpe_ratio": 1.42,
        "max_drawdown": -0.1134, "beta_vs_benchmark": 0.97,
        "anomaly_flag": False, "anomaly_score": 0.12, "anomaly_type": None,
    }
    base.update(kwargs)
    return base


def _make_macro(**kwargs) -> dict:
    base = {
        "fed_funds_rate": 5.25, "cpi": 310.5, "treasury_yield_10y": 4.30,
        "vix": 18.0, "eur_usd_rate": 1.08,
    }
    base.update(kwargs)
    return base


def test_build_prompt_includes_all_metrics():
    risk = _make_risk_metrics()
    holdings = [{"ticker": "SPY", "weight": 0.6}, {"ticker": "TLT", "weight": 0.4}]
    macro = _make_macro()

    prompt = _build_prompt(risk, holdings, macro, None)

    assert "-0.0215" in prompt
    assert "-0.0312" in prompt
    assert "1.42" in prompt
    assert "-0.1134" in prompt
    assert "0.97" in prompt


def test_build_prompt_includes_macro_context():
    risk = _make_risk_metrics()
    macro = _make_macro()

    prompt = _build_prompt(risk, [], macro, None)

    assert "5.25" in prompt
    assert "310.5" in prompt
    assert "4.3" in prompt
    assert "18.0" in prompt
    assert "1.08" in prompt


def test_build_prompt_includes_anomaly_info():
    risk = _make_risk_metrics(anomaly_flag=True, anomaly_score=0.75, anomaly_type="volatility_anomaly")
    macro = _make_macro()

    prompt = _build_prompt(risk, [], macro, None)

    assert "YES" in prompt
    assert "volatility_anomaly" in prompt
    assert "0.75" in prompt


# -------------------- Write tests --------------------

def test_write_briefing_updates_existing_row():
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
        {"portfolio_id": 1}
    ]

    result = _write_briefing(supabase, 1, "2026-05-21", "Test briefing text.")

    assert result is True
    supabase.table.return_value.update.assert_called_once_with({"ai_briefing": "Test briefing text."})


def test_write_briefing_skips_when_no_row():
    supabase = MagicMock()
    supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    result = _write_briefing(supabase, 1, "2026-05-21", "briefing")

    assert result is False
    supabase.table.return_value.update.assert_not_called()


# -------------------- Orchestrator tests --------------------

@patch("src.ai_analyst.gemini_commentary._write_briefing")
@patch("src.ai_analyst.gemini_commentary._call_gemini")
@patch("src.ai_analyst.gemini_commentary._load_worst_performer")
@patch("src.ai_analyst.gemini_commentary._load_portfolio_holdings")
@patch("src.ai_analyst.gemini_commentary._load_latest_macro")
@patch("src.ai_analyst.gemini_commentary._load_risk_metrics")
@patch("src.ai_analyst.gemini_commentary.get_supabase")
@patch("src.ai_analyst.gemini_commentary.utc_today")
@patch("src.ai_analyst.gemini_commentary._load_keys")
def test_generate_commentary_success(
    mock_load_keys, mock_utc_today, mock_get_supabase,
    mock_load_risk_metrics, mock_load_latest_macro,
    mock_load_portfolio_holdings, mock_load_worst_performer,
    mock_call_gemini, mock_write_briefing,
):
    from datetime import date
    mock_load_keys.return_value = ["key1"]
    mock_utc_today.return_value = date(2026, 5, 21)

    mock_supabase = MagicMock()
    mock_get_supabase.return_value = mock_supabase
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1}
    ]

    mock_load_risk_metrics.return_value = {
        "portfolio_id": 1, "date": "2026-05-21",
        "var_95": -0.02, "var_99": -0.03, "sharpe_ratio": 1.5,
        "max_drawdown": -0.1, "beta_vs_benchmark": 0.95,
        "anomaly_flag": False, "anomaly_score": 0.1, "anomaly_type": None,
    }
    mock_load_latest_macro.return_value = _make_macro()
    mock_load_portfolio_holdings.return_value = [
        {"asset_id": 1, "ticker": "SPY", "name": "S&P 500 ETF", "weight": 0.6},
    ]
    mock_load_worst_performer.return_value = {
        "asset_id": 1, "ticker": "SPY", "name": "S&P 500 ETF",
        "daily_return": -0.01, "date": "2026-05-21",
    }
    mock_call_gemini.return_value = "  Briefing text here.  "
    mock_write_briefing.return_value = True

    result = generate_commentary()

    assert result["status"] == "success"
    assert result["briefing"] == "Briefing text here."
    assert result["error"] is None


@patch("src.ai_analyst.gemini_commentary._load_keys")
def test_generate_commentary_no_keys(mock_load_keys):
    mock_load_keys.return_value = []

    result = generate_commentary()

    assert result["status"] == "failure"
    assert "no Gemini API keys configured" in result["error"]


@patch("src.ai_analyst.gemini_commentary._load_risk_metrics")
@patch("src.ai_analyst.gemini_commentary.get_supabase")
@patch("src.ai_analyst.gemini_commentary.utc_today")
@patch("src.ai_analyst.gemini_commentary._load_keys")
def test_generate_commentary_no_risk_metrics(
    mock_load_keys, mock_utc_today, mock_get_supabase, mock_load_risk_metrics,
):
    from datetime import date
    mock_load_keys.return_value = ["key1"]
    mock_utc_today.return_value = date(2026, 5, 21)

    mock_supabase = MagicMock()
    mock_get_supabase.return_value = mock_supabase
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": 1}
    ]

    mock_load_risk_metrics.return_value = None

    result = generate_commentary()

    assert result["status"] == "skipped"
    assert "no risk metrics" in result["error"]


@patch("src.ai_analyst.gemini_commentary.get_supabase")
@patch("src.ai_analyst.gemini_commentary._load_keys")
def test_generate_commentary_catches_exception(mock_load_keys, mock_get_supabase):
    mock_load_keys.return_value = ["key1"]
    mock_get_supabase.side_effect = RuntimeError("DB connection failed")

    result = generate_commentary()

    assert result["status"] == "failure"
    assert "DB connection failed" in result["error"]


# -------------------- Pipeline tests --------------------

@patch("pipeline.daily_pipeline.generate_commentary")
@patch("pipeline.daily_pipeline.run_anomaly_detection")
@patch("pipeline.daily_pipeline.compute_risk_metrics")
@patch("pipeline.daily_pipeline.validate_data")
@patch("pipeline.daily_pipeline.fetch_vix")
@patch("pipeline.daily_pipeline.fetch_macro_data")
@patch("pipeline.daily_pipeline.fetch_market_data")
def test_pipeline_calls_gemini_after_anomaly(
    mock_market, mock_macro, mock_vix, mock_validate,
    mock_risk, mock_anomaly, mock_gemini,
):
    mock_market.return_value = {"rows_inserted": 10}
    mock_macro.return_value = {"rows_inserted": 4, "failures": []}
    mock_vix.return_value = {"rows_inserted": 1}
    mock_validate.return_value = {"status": "ok", "checks": []}
    mock_risk.return_value = {
        "status": "success", "var_95": -0.02, "var_99": -0.03,
        "sharpe_ratio": 1.5, "max_drawdown": -0.1, "beta_vs_benchmark": 0.95,
        "portfolio_id": 1, "error": None,
    }
    mock_anomaly.return_value = {
        "status": "success", "anomalies_found": 0, "assets_scored": 5, "error": None,
    }
    mock_gemini.return_value = {"status": "success", "briefing": "Test briefing.", "error": None}

    result = run_daily_pipeline()

    mock_gemini.assert_called_once()
    assert "gemini_commentary" in result
    assert result["gemini_commentary"]["status"] == "success"


@patch("pipeline.daily_pipeline.generate_commentary")
@patch("pipeline.daily_pipeline.run_anomaly_detection")
@patch("pipeline.daily_pipeline.compute_risk_metrics")
@patch("pipeline.daily_pipeline.validate_data")
@patch("pipeline.daily_pipeline.fetch_vix")
@patch("pipeline.daily_pipeline.fetch_macro_data")
@patch("pipeline.daily_pipeline.fetch_market_data")
def test_pipeline_skips_gemini_when_risk_metrics_failed(
    mock_market, mock_macro, mock_vix, mock_validate,
    mock_risk, mock_anomaly, mock_gemini,
):
    mock_market.return_value = {"rows_inserted": 0}
    mock_macro.return_value = {"rows_inserted": 0, "failures": []}
    mock_vix.return_value = {"rows_inserted": 0}
    mock_validate.return_value = {"status": "ok", "checks": []}
    mock_risk.return_value = {
        "status": "failure", "error": "no data",
        "var_95": None, "var_99": None, "sharpe_ratio": None,
        "max_drawdown": None, "beta_vs_benchmark": None, "portfolio_id": None,
    }

    result = run_daily_pipeline()

    mock_gemini.assert_not_called()
    assert result["gemini_commentary"]["status"] == "skipped"
