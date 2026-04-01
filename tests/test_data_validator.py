# Author: @ShoumikDutta

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

import src.ingestion.data_validator as dv


# -------------------- HELPERS --------------------
def build_mock_supabase(assets, prices, macro):
    def table(name):
        mock = MagicMock()

        if name == "assets":
            mock.select().eq().execute.return_value.data = assets

        elif name == "prices":
            # completeness
            mock.select().eq().gte().execute.return_value.data = prices

            # freshness
            mock.select().eq().order().limit().execute.return_value.data = prices

            # sanity + duplicates
            mock.select().execute.return_value.data = prices

        elif name == "macro_indicators":
            mock.select().order().execute.return_value.data = macro
            mock.select().execute.return_value.data = macro

        return mock

    supabase = MagicMock()
    supabase.table.side_effect = table
    return supabase


# -------------------- TEST: STRUCTURE --------------------
@patch("src.ingestion.data_validator.supabase")
def test_output_structure(mock_db):
    mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

    result = dv.validate_data()

    assert isinstance(result, dict)
    assert "status" in result
    assert "checks" in result
    assert "timestamp" in result


# -------------------- TEST: PASS --------------------
@patch("src.ingestion.data_validator.supabase")
def test_pass_case(mock_db):
    today = datetime.utcnow().date()

    prices = [
        {
            "asset_id": 1,
            "date": (today - timedelta(days=i)).isoformat(),
            "close": 100,
            "volume": 1000,
            "daily_return": 0.01,
        }
        for i in range(3)  # ✅ ensures completeness passes
    ]

    macro = [
        {
            "indicator": "vix",
            "date": today.isoformat(),
            "value": 20,
        }
    ]

    mock_db.table = build_mock_supabase(
        assets=[{"id": 1, "ticker": "AAPL"}],
        prices=prices,
        macro=macro,
    ).table

    result = dv.validate_data()

    assert result["status"] == "pass"


# -------------------- TEST: WARN --------------------
@patch("src.ingestion.data_validator.supabase")
def test_warn_case(mock_db):
    # No recent price data → completeness warning
    mock_db.table = build_mock_supabase(
        assets=[{"id": 1, "ticker": "AAPL"}],
        prices=[],
        macro=[],
    ).table

    result = dv.validate_data()

    assert result["status"] == "warn"


# -------------------- TEST: FAIL --------------------
@patch("src.ingestion.data_validator.supabase")
def test_fail_case(mock_db):
    today = datetime.utcnow().date()

    prices = [
        {
            "asset_id": 1,
            "date": (today - timedelta(days=i)).isoformat(),
            "close": 100,
            "volume": 1000,
            "daily_return": 0.01,
        }
        for i in range(2)
    ]

    # Add invalid row → triggers sanity FAIL
    prices.append(
        {
            "asset_id": 1,
            "date": today.isoformat(),
            "close": -10,  # ❌ invalid
            "volume": 1000,
            "daily_return": 0.01,
        }
    )

    mock_db.table = build_mock_supabase(
        assets=[{"id": 1, "ticker": "AAPL"}],
        prices=prices,
        macro=[],
    ).table

    result = dv.validate_data()

    assert result["status"] == "fail"