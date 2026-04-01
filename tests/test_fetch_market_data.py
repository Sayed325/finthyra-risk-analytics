#Author: @ShoumikDutta
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from src.ingestion.fetch_market_data import (
    build_price_rows,
    upsert_prices,
    fetch_market_data,
)


def test_build_price_rows_with_previous_close():
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-03-18", "2026-03-19"]),
            "Open": [100.0, 102.0],
            "High": [103.0, 104.0],
            "Low": [99.0, 101.0],
            "Close": [102.0, 103.0],
            "Volume": [1000, 1200],
        }
    )

    rows = build_price_rows(df=df, asset_id=1, previous_close=100.0)

    assert len(rows) == 2

    assert rows[0]["asset_id"] == 1
    assert rows[0]["date"] == "2026-03-18"
    assert rows[0]["open"] == 100.0
    assert rows[0]["high"] == 103.0
    assert rows[0]["low"] == 99.0
    assert rows[0]["close"] == 102.0
    assert rows[0]["volume"] == 1000
    assert rows[0]["daily_return"] == 0.02

    assert rows[1]["date"] == "2026-03-19"
    assert rows[1]["daily_return"] == round((103.0 - 102.0) / 102.0, 6)


def test_build_price_rows_without_previous_close():
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-03-18"]),
            "Open": [100.0],
            "High": [103.0],
            "Low": [99.0],
            "Close": [102.0],
            "Volume": [1000],
        }
    )

    rows = build_price_rows(df=df, asset_id=2, previous_close=None)

    assert len(rows) == 1
    assert rows[0]["daily_return"] is None


def test_build_price_rows_skips_nan_close():
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-03-18", "2026-03-19"]),
            "Open": [100.0, 102.0],
            "High": [103.0, 104.0],
            "Low": [99.0, 101.0],
            "Close": [None, 103.0],
            "Volume": [1000, 1200],
        }
    )

    rows = build_price_rows(df=df, asset_id=3, previous_close=100.0)

    assert len(rows) == 1
    assert rows[0]["date"] == "2026-03-19"


def test_upsert_prices_returns_zero_for_empty_rows():
    supabase = MagicMock()

    inserted = upsert_prices(supabase, [])

    assert inserted == 0
    supabase.table.assert_not_called()


def test_upsert_prices_success():
    supabase = MagicMock()
    table_mock = MagicMock()
    supabase.table.return_value = table_mock
    table_mock.upsert.return_value.execute.return_value = MagicMock()

    rows = [
        {
            "asset_id": 1,
            "date": "2026-03-18",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000,
            "daily_return": 0.005,
        }
    ]

    inserted = upsert_prices(supabase, rows)

    assert inserted == 1
    supabase.table.assert_called_once_with("prices")
    table_mock.upsert.assert_called_once()


def test_upsert_prices_raises_runtime_error_on_failure():
    supabase = MagicMock()
    table_mock = MagicMock()
    supabase.table.return_value = table_mock
    table_mock.upsert.side_effect = Exception("DB write failed")

    rows = [
        {
            "asset_id": 1,
            "date": "2026-03-18",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000,
            "daily_return": 0.005,
        }
    ]

    with pytest.raises(RuntimeError) as exc_info:
        upsert_prices(supabase, rows)

    assert "Supabase write failed" in str(exc_info.value)


@patch("src.ingestion.fetch_market_data.upsert_prices")
@patch("src.ingestion.fetch_market_data.build_price_rows")
@patch("src.ingestion.fetch_market_data.download_ticker_data")
@patch("src.ingestion.fetch_market_data.get_previous_close")
@patch("src.ingestion.fetch_market_data.get_last_price_date")
@patch("src.ingestion.fetch_market_data.get_active_assets")
@patch("src.ingestion.fetch_market_data.get_supabase")
def test_fetch_market_data_success(
    mock_get_supabase,
    mock_get_active_assets,
    mock_get_last_price_date,
    mock_get_previous_close,
    mock_download_ticker_data,
    mock_build_price_rows,
    mock_upsert_prices,
):
    supabase = MagicMock()
    mock_get_supabase.return_value = supabase
    mock_get_active_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_get_last_price_date.return_value = "2026-03-18"
    mock_get_previous_close.return_value = 100.0

    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-03-19"]),
            "Open": [101.0],
            "High": [102.0],
            "Low": [100.0],
            "Close": [101.5],
            "Volume": [1500],
        }
    )
    mock_download_ticker_data.return_value = df

    mock_build_price_rows.return_value = [
        {
            "asset_id": 1,
            "date": "2026-03-19",
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": 101.5,
            "volume": 1500,
            "daily_return": 0.015,
        }
    ]
    mock_upsert_prices.return_value = 1

    result = fetch_market_data()

    assert result["tickers_processed"] == 1
    assert result["rows_inserted"] == 1
    assert result["failures"] == []


@patch("src.ingestion.fetch_market_data.download_ticker_data")
@patch("src.ingestion.fetch_market_data.get_previous_close")
@patch("src.ingestion.fetch_market_data.get_last_price_date")
@patch("src.ingestion.fetch_market_data.get_active_assets")
@patch("src.ingestion.fetch_market_data.get_supabase")
def test_fetch_market_data_handles_empty_download(
    mock_get_supabase,
    mock_get_active_assets,
    mock_get_last_price_date,
    mock_get_previous_close,
    mock_download_ticker_data,
):
    supabase = MagicMock()
    mock_get_supabase.return_value = supabase
    mock_get_active_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_get_last_price_date.return_value = "2026-03-18"
    mock_get_previous_close.return_value = 100.0
    mock_download_ticker_data.return_value = pd.DataFrame()

    result = fetch_market_data()

    assert result["tickers_processed"] == 1
    assert result["rows_inserted"] == 0
    assert result["failures"] == []


@patch("src.ingestion.fetch_market_data.download_ticker_data")
@patch("src.ingestion.fetch_market_data.get_previous_close")
@patch("src.ingestion.fetch_market_data.get_last_price_date")
@patch("src.ingestion.fetch_market_data.get_active_assets")
@patch("src.ingestion.fetch_market_data.get_supabase")
def test_fetch_market_data_records_failure(
    mock_get_supabase,
    mock_get_active_assets,
    mock_get_last_price_date,
    mock_get_previous_close,
    mock_download_ticker_data,
):
    supabase = MagicMock()
    mock_get_supabase.return_value = supabase
    mock_get_active_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_get_last_price_date.return_value = "2026-03-18"
    mock_get_previous_close.return_value = 100.0
    mock_download_ticker_data.side_effect = Exception("API error")

    result = fetch_market_data()

    assert result["tickers_processed"] == 1
    assert result["rows_inserted"] == 0
    assert result["failures"] == ["AAPL"]