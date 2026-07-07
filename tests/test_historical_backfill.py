import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from scripts.historical_backfill import (
    normalize_downloaded_frame,
    compute_returns,
    format_rows,
    upsert_rows,
    run_backfill,
)

# ---- normalize_downloaded_frame ----


def test_normalize_returns_empty_for_none():
    result = normalize_downloaded_frame(None)
    assert result.empty


def test_normalize_returns_empty_for_empty_df():
    result = normalize_downloaded_frame(pd.DataFrame())
    assert result.empty


def test_normalize_raises_if_close_column_missing():
    df = pd.DataFrame({"Open": [100.0], "High": [105.0]})
    with pytest.raises(ValueError, match="missing Close column"):
        normalize_downloaded_frame(df)


def test_normalize_flattens_multiindex_columns():
    # yfinance single-ticker MultiIndex has field as level 0, ticker as level 1
    arrays = [["Close", "Open"], ["^VIX", "^VIX"]]
    tuples = list(zip(*arrays))
    index = pd.MultiIndex.from_tuples(tuples)
    df = pd.DataFrame([[100.0, 99.0]], columns=index)
    result = normalize_downloaded_frame(df)
    assert not isinstance(result.columns, pd.MultiIndex)
    assert "Close" in result.columns


def test_normalize_passes_through_normal_df():
    df = pd.DataFrame({"Close": [100.0, 101.0], "Open": [99.0, 100.0]})
    result = normalize_downloaded_frame(df)
    assert "Close" in result.columns
    assert len(result) == 2


# ---- compute_returns ----


def test_compute_returns_adds_daily_return_column():
    idx = pd.to_datetime(["2026-04-21", "2026-04-22", "2026-04-23"])
    df = pd.DataFrame({"Close": [100.0, 110.0, 99.0]}, index=idx)
    result = compute_returns(df)
    assert "daily_return" in result.columns


def test_compute_returns_first_row_is_nan():
    idx = pd.to_datetime(["2026-04-21", "2026-04-22"])
    df = pd.DataFrame({"Close": [100.0, 110.0]}, index=idx)
    result = compute_returns(df)
    assert pd.isna(result["daily_return"].iloc[0])


def test_compute_returns_correct_value():
    idx = pd.to_datetime(["2026-04-21", "2026-04-22"])
    df = pd.DataFrame({"Close": [100.0, 110.0]}, index=idx)
    result = compute_returns(df)
    assert round(result["daily_return"].iloc[1], 6) == round((110.0 - 100.0) / 100.0, 6)


def test_compute_returns_does_not_mutate_original():
    idx = pd.to_datetime(["2026-04-21", "2026-04-22"])
    df = pd.DataFrame({"Close": [100.0, 110.0]}, index=idx)
    _ = compute_returns(df)
    assert "daily_return" not in df.columns


# ---- format_rows ----


def test_format_rows_basic_structure():
    idx = pd.to_datetime(["2026-04-22"])
    df = pd.DataFrame(
        {
            "Open": [99.0],
            "High": [102.0],
            "Low": [98.0],
            "Close": [101.0],
            "Volume": [5000],
            "daily_return": [0.01],
        },
        index=idx,
    )
    rows = format_rows(df, asset_id=3)
    assert len(rows) == 1
    r = rows[0]
    assert r["asset_id"] == 3
    assert r["date"] == "2026-04-22"
    assert r["close"] == 101.0
    assert r["volume"] == 5000
    assert r["daily_return"] == 0.01


def test_format_rows_nan_values_become_none():
    idx = pd.to_datetime(["2026-04-22"])
    df = pd.DataFrame(
        {
            "Open": [float("nan")],
            "High": [float("nan")],
            "Low": [float("nan")],
            "Close": [float("nan")],
            "Volume": [float("nan")],
            "daily_return": [float("nan")],
        },
        index=idx,
    )
    rows = format_rows(df, asset_id=1)
    r = rows[0]
    assert r["close"] is None
    assert r["open"] is None
    assert r["daily_return"] is None


def test_format_rows_rounds_close_to_4_decimals():
    idx = pd.to_datetime(["2026-04-22"])
    df = pd.DataFrame(
        {
            "Close": [101.123456789],
            "daily_return": [0.0],
            "Open": [100.0],
            "High": [102.0],
            "Low": [99.0],
            "Volume": [1000],
        },
        index=idx,
    )
    rows = format_rows(df, asset_id=1)
    assert rows[0]["close"] == round(101.123456789, 4)


def test_format_rows_volume_is_int():
    idx = pd.to_datetime(["2026-04-22"])
    df = pd.DataFrame(
        {
            "Close": [100.0],
            "Open": [99.0],
            "High": [101.0],
            "Low": [98.0],
            "Volume": [123456.0],
            "daily_return": [0.0],
        },
        index=idx,
    )
    rows = format_rows(df, asset_id=1)
    assert isinstance(rows[0]["volume"], int)


# ---- upsert_rows ----


def test_upsert_rows_empty_returns_zero_without_db_call():
    supabase = MagicMock()
    assert upsert_rows(supabase, []) == 0
    supabase.table.assert_not_called()


def test_upsert_rows_returns_count():
    supabase = MagicMock()
    rows = [{"asset_id": 1, "date": "2026-04-22", "close": 100.0}]
    result = upsert_rows(supabase, rows)
    assert result == 1
    supabase.table.assert_called_once_with("prices")


# ---- run_backfill (fully mocked) ----


def _make_bulk_df(tickers):
    idx = pd.to_datetime(["2026-04-22", "2026-04-23"])
    arrays = []
    names = []
    for t in tickers:
        for col in ["Close", "Open", "High", "Low", "Volume"]:
            arrays.append([100.0, 101.0] if col != "Volume" else [1000, 1100])
            names.append((t, col))
    return pd.DataFrame(dict(zip(names, arrays)), index=idx)


@patch("scripts.historical_backfill.upsert_rows")
@patch("scripts.historical_backfill.get_existing_dates")
@patch("scripts.historical_backfill.download_bulk")
@patch("scripts.historical_backfill.get_active_assets")
@patch("scripts.historical_backfill.get_supabase")
def test_run_backfill_success(
    mock_supabase, mock_assets, mock_bulk, mock_existing, mock_upsert
):
    mock_supabase.return_value = MagicMock()
    mock_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_existing.return_value = set()
    mock_bulk.return_value = _make_bulk_df(["AAPL"])
    mock_upsert.return_value = 2

    result = run_backfill(start_date="2026-04-22")
    assert result["tickers_processed"] == 1
    assert result["total_rows"] == 2
    assert result["failures"] == []


@patch("scripts.historical_backfill.download_bulk")
@patch("scripts.historical_backfill.get_active_assets")
@patch("scripts.historical_backfill.get_supabase")
def test_run_backfill_empty_bulk_returns_failures(
    mock_supabase, mock_assets, mock_bulk
):
    mock_supabase.return_value = MagicMock()
    mock_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    mock_bulk.return_value = pd.DataFrame()

    result = run_backfill(start_date="2026-04-22")
    assert result["tickers_processed"] == 0
    assert result["total_rows"] == 0
    assert "AAPL" in result["failures"]


@patch("scripts.historical_backfill.upsert_rows")
@patch("scripts.historical_backfill.get_existing_dates")
@patch("scripts.historical_backfill.download_bulk")
@patch("scripts.historical_backfill.get_active_assets")
@patch("scripts.historical_backfill.get_supabase")
def test_run_backfill_skips_already_existing_dates(
    mock_supabase, mock_assets, mock_bulk, mock_existing, mock_upsert
):
    mock_supabase.return_value = MagicMock()
    mock_assets.return_value = [{"id": 1, "ticker": "AAPL"}]
    # All dates already exist
    mock_existing.return_value = {"2026-04-22", "2026-04-23"}
    mock_bulk.return_value = _make_bulk_df(["AAPL"])
    mock_upsert.return_value = 0

    result = run_backfill(start_date="2026-04-22")
    assert result["total_rows"] == 0
    assert result["failures"] == []
