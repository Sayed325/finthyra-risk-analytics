import pytest
from unittest.mock import MagicMock, patch

from src.ingestion.fetch_macro_data import (
    transform_rows,
    upsert_rows,
    fetch_macro_data,
)


# ---- transform_rows (pure function) ----

def test_transform_rows_builds_correct_row():
    obs = [{"date": "2026-04-24", "value": "5.25"}]
    rows = transform_rows(obs, indicator="fed_funds_rate")
    assert len(rows) == 1
    assert rows[0]["indicator"] == "fed_funds_rate"
    assert rows[0]["date"] == "2026-04-24"
    assert rows[0]["value"] == 5.25
    assert rows[0]["source"] == "fred"


def test_transform_rows_skips_fred_missing_value_dot():
    obs = [{"date": "2026-04-24", "value": "."}]
    rows = transform_rows(obs, indicator="fed_funds_rate")
    assert rows == []


def test_transform_rows_skips_row_with_no_date():
    obs = [{"date": "", "value": "5.0"}, {"date": None, "value": "5.0"}]
    rows = transform_rows(obs, indicator="fed_funds_rate")
    assert rows == []


def test_transform_rows_skips_non_numeric_value():
    obs = [{"date": "2026-04-24", "value": "N/A"}]
    rows = transform_rows(obs, indicator="fed_funds_rate")
    assert rows == []


def test_transform_rows_handles_multiple_observations():
    obs = [
        {"date": "2026-04-22", "value": "5.25"},
        {"date": "2026-04-23", "value": "."},
        {"date": "2026-04-24", "value": "5.30"},
    ]
    rows = transform_rows(obs, indicator="treasury_yield_10y")
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-04-22"
    assert rows[1]["date"] == "2026-04-24"


def test_transform_rows_converts_value_to_float():
    obs = [{"date": "2026-04-24", "value": "4.500"}]
    rows = transform_rows(obs, indicator="cpi")
    assert isinstance(rows[0]["value"], float)
    assert rows[0]["value"] == 4.5


# ---- upsert_rows ----

def test_upsert_rows_empty_returns_zero_without_db_call():
    supabase = MagicMock()
    assert upsert_rows(supabase, []) == 0
    supabase.table.assert_not_called()


def test_upsert_rows_returns_count_of_inserted():
    supabase = MagicMock()
    rows = [
        {"indicator": "fed_funds_rate", "date": "2026-04-24", "value": 5.25, "source": "fred"},
        {"indicator": "fed_funds_rate", "date": "2026-04-23", "value": 5.25, "source": "fred"},
    ]
    result = upsert_rows(supabase, rows)
    assert result == 2
    supabase.table.assert_called_once_with("macro_indicators")


def test_upsert_rows_raises_runtime_error_on_db_failure():
    supabase = MagicMock()
    supabase.table.return_value.upsert.side_effect = Exception("connection refused")
    rows = [{"indicator": "cpi", "date": "2026-04-24", "value": 310.0, "source": "fred"}]
    with pytest.raises(RuntimeError, match="Supabase write failed"):
        upsert_rows(supabase, rows)


# ---- fetch_macro_data (fully mocked) ----

@patch("src.ingestion.fetch_macro_data.upsert_rows")
@patch("src.ingestion.fetch_macro_data.fetch_fred_series")
@patch("src.ingestion.fetch_macro_data.get_last_date")
@patch("src.ingestion.fetch_macro_data.get_supabase")
def test_fetch_macro_data_success(mock_supabase, mock_last_date, mock_fred, mock_upsert):
    mock_supabase.return_value = MagicMock()
    mock_last_date.return_value = None
    mock_fred.return_value = [{"date": "2026-04-24", "value": "5.25"}]
    mock_upsert.return_value = 1

    result = fetch_macro_data()
    assert isinstance(result, dict)
    assert "indicators_processed" in result
    assert "rows_inserted" in result
    assert "failures" in result
    assert result["failures"] == []
    assert result["rows_inserted"] == 4


@patch("src.ingestion.fetch_macro_data.fetch_fred_series")
@patch("src.ingestion.fetch_macro_data.get_last_date")
@patch("src.ingestion.fetch_macro_data.get_supabase")
def test_fetch_macro_data_records_failure_on_fred_error(mock_supabase, mock_last_date, mock_fred):
    mock_supabase.return_value = MagicMock()
    mock_last_date.return_value = None
    mock_fred.side_effect = RuntimeError("FRED API down")

    result = fetch_macro_data()
    assert len(result["failures"]) == 4  # all 4 indicators fail


@patch("src.ingestion.fetch_macro_data.upsert_rows")
@patch("src.ingestion.fetch_macro_data.fetch_fred_series")
@patch("src.ingestion.fetch_macro_data.get_last_date")
@patch("src.ingestion.fetch_macro_data.get_supabase")
def test_fetch_macro_data_skips_already_up_to_date(mock_supabase, mock_last_date, mock_fred, mock_upsert):
    from datetime import date
    mock_supabase.return_value = MagicMock()
    # Return tomorrow as last date to trigger "already up-to-date" branch
    future = (date.today().replace(year=date.today().year + 1)).isoformat()
    mock_last_date.return_value = future
    mock_upsert.return_value = 0

    result = fetch_macro_data()
    mock_fred.assert_not_called()
    assert result["rows_inserted"] == 0


@patch("src.ingestion.fetch_macro_data.upsert_rows")
@patch("src.ingestion.fetch_macro_data.fetch_fred_series")
@patch("src.ingestion.fetch_macro_data.get_last_date")
@patch("src.ingestion.fetch_macro_data.get_supabase")
def test_fetch_macro_data_handles_empty_observations(mock_supabase, mock_last_date, mock_fred, mock_upsert):
    mock_supabase.return_value = MagicMock()
    mock_last_date.return_value = None
    mock_fred.return_value = [{"date": "2026-04-24", "value": "."}]  # all dots → empty after transform

    result = fetch_macro_data()
    mock_upsert.assert_not_called()
    assert result["rows_inserted"] == 0
    assert result["failures"] == []
