import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

from src.ingestion.fetch_market_data import (
    compute_daily_returns,
    build_rows,
    upsert_rows,
    get_fetch_window,
    fetch_market_data,
)


def make_df(dates, closes, opens=None, highs=None, lows=None, volumes=None):
    n = len(dates)
    return pd.DataFrame({
        "Date": pd.to_datetime(dates),
        "Open": opens or [100.0] * n,
        "High": highs or [105.0] * n,
        "Low": lows or [95.0] * n,
        "Close": closes,
        "Volume": volumes or [1000] * n,
    })


# ---- compute_daily_returns ----

def test_compute_daily_returns_with_previous_close():
    df = make_df(["2026-03-18", "2026-03-19"], [102.0, 103.0])
    result = compute_daily_returns(df, previous_close=100.0)
    assert round(result["daily_return"].iloc[0], 6) == round((102.0 - 100.0) / 100.0, 6)
    assert round(result["daily_return"].iloc[1], 6) == round((103.0 - 102.0) / 102.0, 6)


def test_compute_daily_returns_without_previous_close_first_row_is_none():
    df = make_df(["2026-03-18", "2026-03-19"], [102.0, 103.0])
    result = compute_daily_returns(df, previous_close=None)
    # The function appends None but pandas coerces it to NaN in a float column
    assert pd.isna(result["daily_return"].iloc[0])
    assert round(result["daily_return"].iloc[1], 6) == round((103.0 - 102.0) / 102.0, 6)


def test_compute_daily_returns_does_not_mutate_original():
    df = make_df(["2026-03-18"], [100.0])
    _ = compute_daily_returns(df, previous_close=90.0)
    assert "daily_return" not in df.columns


def test_compute_daily_returns_chains_correctly_across_rows():
    df = make_df(["2026-03-18", "2026-03-19", "2026-03-20"], [100.0, 110.0, 99.0])
    result = compute_daily_returns(df, previous_close=100.0)
    assert result["daily_return"].iloc[0] == 0.0
    assert round(result["daily_return"].iloc[1], 6) == round((110.0 - 100.0) / 100.0, 6)
    assert round(result["daily_return"].iloc[2], 6) == round((99.0 - 110.0) / 110.0, 6)


# ---- build_rows ----

def test_build_rows_basic_structure():
    df = make_df(["2026-03-18"], [102.0])
    df["daily_return"] = [0.02]
    rows = build_rows(df, asset_id=5)
    assert len(rows) == 1
    r = rows[0]
    assert r["asset_id"] == 5
    assert r["date"] == "2026-03-18"
    assert r["close"] == 102.0
    assert r["daily_return"] == 0.02


def test_build_rows_nan_close_becomes_none():
    df = make_df(["2026-03-18"], [None])
    df["daily_return"] = [None]
    rows = build_rows(df, asset_id=1)
    assert rows[0]["close"] is None


def test_build_rows_rounds_close_to_4_decimals():
    df = make_df(["2026-03-18"], [102.123456789])
    df["daily_return"] = [0.0]
    rows = build_rows(df, asset_id=1)
    assert rows[0]["close"] == round(102.123456789, 4)


def test_build_rows_rounds_daily_return_to_6_decimals():
    df = make_df(["2026-03-18"], [100.0])
    df["daily_return"] = [0.0123456789]
    rows = build_rows(df, asset_id=1)
    assert rows[0]["daily_return"] == round(0.0123456789, 6)


def test_build_rows_volume_is_int():
    df = make_df(["2026-03-18"], [100.0], volumes=[12345])
    df["daily_return"] = [0.0]
    rows = build_rows(df, asset_id=1)
    assert isinstance(rows[0]["volume"], int)
    assert rows[0]["volume"] == 12345


def test_build_rows_multiple_rows_preserves_order():
    df = make_df(["2026-03-18", "2026-03-19"], [100.0, 101.0])
    df["daily_return"] = [None, 0.01]
    rows = build_rows(df, asset_id=2)
    assert rows[0]["date"] == "2026-03-18"
    assert rows[1]["date"] == "2026-03-19"


# ---- upsert_rows ----

def test_upsert_rows_empty_returns_zero_without_db_call():
    supabase = MagicMock()
    assert upsert_rows(supabase, [], "AAPL") == 0
    supabase.table.assert_not_called()


def test_upsert_rows_returns_count_of_inserted_rows():
    supabase = MagicMock()
    rows = [{"asset_id": 1, "date": "2026-03-18", "close": 100.0}]
    result = upsert_rows(supabase, rows, "AAPL")
    assert result == 1
    supabase.table.assert_called_once_with("prices")


def test_upsert_rows_raises_runtime_error_on_db_failure():
    supabase = MagicMock()
    supabase.table.return_value.upsert.side_effect = Exception("DB write failed")
    rows = [{"asset_id": 1, "date": "2026-03-18", "close": 100.0}]
    with pytest.raises(RuntimeError, match="Supabase write failed"):
        upsert_rows(supabase, rows, "AAPL")


# ---- get_fetch_window ----

def test_get_fetch_window_with_last_date_starts_day_after():
    start, _ = get_fetch_window("2026-04-20", "AAPL")
    assert start == date(2026, 4, 21)


def test_get_fetch_window_without_last_date_starts_7_days_ago():
    start, _ = get_fetch_window(None, "AAPL")
    assert start == date.today() - timedelta(days=7)


def test_get_fetch_window_end_is_always_tomorrow():
    _, end = get_fetch_window("2026-04-20", "AAPL")
    assert end == date.today() + timedelta(days=1)


# ---- fetch_market_data (integration, fully mocked) ----

@patch("src.ingestion.fetch_market_data.upsert_rows")
@patch("src.ingestion.fetch_market_data.build_rows")
@patch("src.ingestion.fetch_market_data.compute_daily_returns")
@patch("src.ingestion.fetch_market_data.download_ticker_data")
@patch("src.ingestion.fetch_market_data.get_previous_close")
@patch("src.ingestion.fetch_market_data.get_last_price_date")
@patch("src.ingestion.fetch_market_data.get_active_assets")
@patch("src.ingestion.fetch_market_data.get_supabase")
def test_fetch_market_data_success(
    mock_supabase, mock_assets, mock_last_date, mock_prev_close,
    mock_download, mock_compute, mock_build, mock_upsert,
):
    mock_supabase.return_value = MagicMock()
    mock_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_last_date.return_value = "2026-04-19"
    mock_prev_close.return_value = 100.0
    df = make_df(["2026-04-20"], [101.0])
    mock_download.return_value = df
    mock_compute.return_value = df
    mock_build.return_value = [{"asset_id": 1, "date": "2026-04-20", "close": 101.0}]
    mock_upsert.return_value = 1

    result = fetch_market_data()
    assert result["rows_inserted"] == 1
    assert result["failures"] == []
    assert result["tickers_processed"] == 1


@patch("src.ingestion.fetch_market_data.download_ticker_data")
@patch("src.ingestion.fetch_market_data.get_previous_close")
@patch("src.ingestion.fetch_market_data.get_last_price_date")
@patch("src.ingestion.fetch_market_data.get_active_assets")
@patch("src.ingestion.fetch_market_data.get_supabase")
def test_fetch_market_data_empty_download_not_a_failure(
    mock_supabase, mock_assets, mock_last_date, mock_prev_close, mock_download,
):
    mock_supabase.return_value = MagicMock()
    mock_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_last_date.return_value = "2026-04-19"
    mock_prev_close.return_value = 100.0
    mock_download.return_value = pd.DataFrame()

    result = fetch_market_data()
    assert result["rows_inserted"] == 0
    assert result["failures"] == []


@patch("src.ingestion.fetch_market_data.download_ticker_data")
@patch("src.ingestion.fetch_market_data.get_previous_close")
@patch("src.ingestion.fetch_market_data.get_last_price_date")
@patch("src.ingestion.fetch_market_data.get_active_assets")
@patch("src.ingestion.fetch_market_data.get_supabase")
def test_fetch_market_data_download_exception_records_failure(
    mock_supabase, mock_assets, mock_last_date, mock_prev_close, mock_download,
):
    mock_supabase.return_value = MagicMock()
    mock_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_last_date.return_value = "2026-04-19"
    mock_prev_close.return_value = 100.0
    mock_download.side_effect = Exception("yfinance exploded")

    result = fetch_market_data()
    assert "AAPL" in result["failures"]
    assert result["rows_inserted"] == 0


@patch("src.ingestion.fetch_market_data.get_active_assets")
@patch("src.ingestion.fetch_market_data.get_supabase")
def test_fetch_market_data_no_assets_returns_zeros(mock_supabase, mock_assets):
    mock_supabase.return_value = MagicMock()
    mock_assets.return_value = []

    result = fetch_market_data()
    assert result["tickers_processed"] == 0
    assert result["rows_inserted"] == 0
    assert result["failures"] == []
