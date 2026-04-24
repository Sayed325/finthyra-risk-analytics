import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

from src.ingestion.fetch_vix import (
    get_fetch_window,
    build_rows,
    upsert_rows,
    fetch_vix,
)


# ---- get_fetch_window ----

def test_get_fetch_window_with_last_date_starts_day_after():
    start, _ = get_fetch_window("2026-04-20")
    assert start == date(2026, 4, 21)


def test_get_fetch_window_without_last_date_starts_30_days_ago():
    start, _ = get_fetch_window(None)
    assert start == date.today() - timedelta(days=30)


def test_get_fetch_window_end_is_always_tomorrow():
    _, end = get_fetch_window("2026-04-20")
    assert end == date.today() + timedelta(days=1)


# ---- build_rows ----

def test_build_rows_creates_correct_structure():
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-04-22", "2026-04-23"]),
        "Close": [18.5, 19.0],
    })
    rows = build_rows(df)
    assert len(rows) == 2
    assert rows[0]["indicator"] == "vix"
    assert rows[0]["date"] == "2026-04-22"
    assert rows[0]["value"] == 18.5
    assert rows[0]["source"] == "yfinance"


def test_build_rows_skips_nan_close():
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-04-22", "2026-04-23"]),
        "Close": [float("nan"), 19.0],
    })
    rows = build_rows(df)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-04-23"


def test_build_rows_rounds_value_to_4_decimals():
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-04-22"]),
        "Close": [18.123456789],
    })
    rows = build_rows(df)
    assert rows[0]["value"] == round(18.123456789, 4)


def test_build_rows_empty_df_returns_empty_list():
    rows = build_rows(pd.DataFrame({"Date": [], "Close": []}))
    assert rows == []


# ---- upsert_rows ----

def test_upsert_rows_empty_returns_zero_without_db_call():
    supabase = MagicMock()
    assert upsert_rows(supabase, []) == 0
    supabase.table.assert_not_called()


def test_upsert_rows_returns_count():
    supabase = MagicMock()
    rows = [
        {"indicator": "vix", "date": "2026-04-22", "value": 18.5, "source": "yfinance"},
        {"indicator": "vix", "date": "2026-04-23", "value": 19.0, "source": "yfinance"},
    ]
    result = upsert_rows(supabase, rows)
    assert result == 2
    supabase.table.assert_called_once_with("macro_indicators")


def test_upsert_rows_raises_runtime_error_on_failure():
    supabase = MagicMock()
    supabase.table.return_value.upsert.side_effect = Exception("DB error")
    rows = [{"indicator": "vix", "date": "2026-04-22", "value": 18.5, "source": "yfinance"}]
    with pytest.raises(RuntimeError, match="Supabase write failed"):
        upsert_rows(supabase, rows)


# ---- fetch_vix (fully mocked) ----

@patch("src.ingestion.fetch_vix.upsert_rows")
@patch("src.ingestion.fetch_vix.download_vix_data")
@patch("src.ingestion.fetch_vix.get_last_date")
@patch("src.ingestion.fetch_vix.get_supabase")
def test_fetch_vix_success(mock_supabase, mock_last_date, mock_download, mock_upsert):
    mock_supabase.return_value = MagicMock()
    mock_last_date.return_value = "2026-04-21"
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-04-22"]),
        "Close": [18.75],
    })
    mock_download.return_value = df
    mock_upsert.return_value = 1

    result = fetch_vix()
    assert result["rows_inserted"] == 1
    assert result["latest_value"] == 18.75


@patch("src.ingestion.fetch_vix.download_vix_data")
@patch("src.ingestion.fetch_vix.get_last_date")
@patch("src.ingestion.fetch_vix.get_supabase")
def test_fetch_vix_empty_download_returns_zero(mock_supabase, mock_last_date, mock_download):
    mock_supabase.return_value = MagicMock()
    mock_last_date.return_value = "2026-04-21"
    mock_download.return_value = pd.DataFrame()

    result = fetch_vix()
    assert result["rows_inserted"] == 0
    assert result["latest_value"] is None


@patch("src.ingestion.fetch_vix.download_vix_data")
@patch("src.ingestion.fetch_vix.get_last_date")
@patch("src.ingestion.fetch_vix.get_supabase")
def test_fetch_vix_download_error_returns_zero(mock_supabase, mock_last_date, mock_download):
    mock_supabase.return_value = MagicMock()
    mock_last_date.return_value = "2026-04-21"
    mock_download.side_effect = Exception("yfinance timeout")

    result = fetch_vix()
    assert result["rows_inserted"] == 0
    assert result["latest_value"] is None


@patch("src.ingestion.fetch_vix.download_vix_data")
@patch("src.ingestion.fetch_vix.get_last_date")
@patch("src.ingestion.fetch_vix.get_supabase")
def test_fetch_vix_all_nan_rows_returns_zero(mock_supabase, mock_last_date, mock_download):
    mock_supabase.return_value = MagicMock()
    mock_last_date.return_value = "2026-04-21"
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-04-22"]),
        "Close": [float("nan")],
    })
    mock_download.return_value = df

    result = fetch_vix()
    assert result["rows_inserted"] == 0
    assert result["latest_value"] is None
