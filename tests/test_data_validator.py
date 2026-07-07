from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import date

import src.ingestion.data_validator as dv

# ---- pure functions (no mocking needed) ----


def test_get_exchange_for_ticker_us_default():
    assert dv.get_exchange_for_ticker("AAPL") == "NYSE"
    assert dv.get_exchange_for_ticker("SPY") == "NYSE"
    assert dv.get_exchange_for_ticker("NVDA") == "NYSE"


def test_get_exchange_for_ticker_german_xetra():
    assert dv.get_exchange_for_ticker("SIE.DE") == "XETR"
    assert dv.get_exchange_for_ticker("BAS.DE") == "XETR"


def test_get_exchange_for_ticker_london():
    assert dv.get_exchange_for_ticker("VUSA.L") == "LSE"
    assert dv.get_exchange_for_ticker("IWDA.L") == "LSE"


def test_get_exchange_for_ticker_is_case_insensitive():
    assert dv.get_exchange_for_ticker("sie.de") == "XETR"
    assert dv.get_exchange_for_ticker("vusa.l") == "LSE"


def test_parse_iso_date_returns_date_object():
    result = dv.parse_iso_date("2026-04-24")
    assert result == date(2026, 4, 24)


# ---- check_sanity (patch the page fetchers) ----


@patch("src.ingestion.data_validator.fetch_macro_page", return_value=[])
@patch("src.ingestion.data_validator.fetch_prices_page")
def test_check_sanity_passes_on_clean_data(mock_prices, mock_macro):
    mock_prices.side_effect = [
        [{"asset_id": 1, "close": 100.0, "volume": 1000, "daily_return": 0.01}],
        [],
    ]
    issues = dv.check_sanity(MagicMock())
    assert issues == []


@patch("src.ingestion.data_validator.fetch_macro_page", return_value=[])
@patch("src.ingestion.data_validator.fetch_prices_page")
def test_check_sanity_flags_negative_close(mock_prices, mock_macro):
    mock_prices.side_effect = [
        [{"asset_id": 1, "close": -5.0, "volume": 100, "daily_return": 0.01}],
        [],
    ]
    issues = dv.check_sanity(MagicMock())
    assert any("invalid close" in i for i in issues)


@patch("src.ingestion.data_validator.fetch_macro_page", return_value=[])
@patch("src.ingestion.data_validator.fetch_prices_page")
def test_check_sanity_flags_zero_close(mock_prices, mock_macro):
    mock_prices.side_effect = [
        [{"asset_id": 1, "close": 0.0, "volume": 100, "daily_return": 0.0}],
        [],
    ]
    issues = dv.check_sanity(MagicMock())
    assert any("invalid close" in i for i in issues)


@patch("src.ingestion.data_validator.fetch_macro_page", return_value=[])
@patch("src.ingestion.data_validator.fetch_prices_page")
def test_check_sanity_flags_negative_volume(mock_prices, mock_macro):
    mock_prices.side_effect = [
        [{"asset_id": 1, "close": 100.0, "volume": -1, "daily_return": 0.01}],
        [],
    ]
    issues = dv.check_sanity(MagicMock())
    assert any("invalid volume" in i for i in issues)


@patch("src.ingestion.data_validator.fetch_macro_page", return_value=[])
@patch("src.ingestion.data_validator.fetch_prices_page")
def test_check_sanity_flags_abnormal_return_above_50pct(mock_prices, mock_macro):
    mock_prices.side_effect = [
        [{"asset_id": 1, "close": 100.0, "volume": 1000, "daily_return": 0.75}],
        [],
    ]
    issues = dv.check_sanity(MagicMock())
    assert any("abnormal daily_return" in i for i in issues)


@patch("src.ingestion.data_validator.fetch_macro_page", return_value=[])
@patch("src.ingestion.data_validator.fetch_prices_page")
def test_check_sanity_flags_abnormal_return_below_minus_50pct(mock_prices, mock_macro):
    mock_prices.side_effect = [
        [{"asset_id": 1, "close": 100.0, "volume": 1000, "daily_return": -0.75}],
        [],
    ]
    issues = dv.check_sanity(MagicMock())
    assert any("abnormal daily_return" in i for i in issues)


@patch("src.ingestion.data_validator.fetch_prices_page", return_value=[])
@patch("src.ingestion.data_validator.fetch_macro_page")
def test_check_sanity_flags_vix_out_of_range(mock_macro, mock_prices):
    mock_macro.side_effect = [
        [{"indicator": "vix", "date": "2026-04-24", "value": 200.0}],
        [],
    ]
    issues = dv.check_sanity(MagicMock())
    assert any("vix" in i and "out-of-range" in i for i in issues)


# ---- check_duplicates ----


def _make_dup_supabase(prices_pages, macro_pages):
    supabase = MagicMock()
    call_count = {"n": 0}
    all_pages = prices_pages + macro_pages

    def range_side_effect(start, end):
        m = MagicMock()
        idx = call_count["n"]
        call_count["n"] += 1
        m.execute.return_value.data = all_pages[idx] if idx < len(all_pages) else []
        return m

    supabase.table.return_value.select.return_value.range.side_effect = (
        range_side_effect
    )
    return supabase


def test_check_duplicates_no_issues_on_unique_data():
    supabase = _make_dup_supabase(
        prices_pages=[
            [
                {"asset_id": 1, "date": "2026-04-20"},
                {"asset_id": 1, "date": "2026-04-21"},
            ],
            [],
        ],
        macro_pages=[[{"indicator": "vix", "date": "2026-04-20"}], []],
    )
    issues = dv.check_duplicates(supabase)
    assert issues == []


def test_check_duplicates_detects_price_duplicate():
    dup = {"asset_id": 1, "date": "2026-04-20"}
    supabase = _make_dup_supabase(
        prices_pages=[[dup, dup], []],
        macro_pages=[[], []],
    )
    issues = dv.check_duplicates(supabase)
    assert any("duplicate price row" in i for i in issues)


def test_check_duplicates_detects_macro_duplicate():
    dup = {"indicator": "vix", "date": "2026-04-20"}
    # Single empty page for prices (immediate break), then dup rows for macro
    supabase = _make_dup_supabase(
        prices_pages=[[]],
        macro_pages=[[dup, dup], []],
    )
    issues = dv.check_duplicates(supabase)
    assert any("duplicate macro row" in i for i in issues)


# ---- validate_data (patch all check functions + get_supabase) ----


@patch("src.ingestion.data_validator.get_supabase")
@patch("src.ingestion.data_validator.check_completeness", return_value=[])
@patch("src.ingestion.data_validator.check_freshness", return_value=[])
@patch("src.ingestion.data_validator.check_sanity", return_value=[])
@patch("src.ingestion.data_validator.check_duplicates", return_value=[])
def test_validate_data_returns_expected_structure(
    mock_dupes, mock_sanity, mock_fresh, mock_complete, mock_db
):
    mock_db.return_value = MagicMock()
    result = dv.validate_data()
    assert isinstance(result, dict)
    assert "status" in result
    assert "checks" in result
    assert "timestamp" in result
    assert set(result["checks"].keys()) == {
        "completeness",
        "freshness",
        "sanity",
        "duplicates",
    }


@patch("src.ingestion.data_validator.get_supabase")
@patch("src.ingestion.data_validator.check_completeness", return_value=[])
@patch("src.ingestion.data_validator.check_freshness", return_value=[])
@patch("src.ingestion.data_validator.check_sanity", return_value=[])
@patch("src.ingestion.data_validator.check_duplicates", return_value=[])
def test_validate_data_status_pass_when_all_clean(
    mock_dupes, mock_sanity, mock_fresh, mock_complete, mock_db
):
    mock_db.return_value = MagicMock()
    result = dv.validate_data()
    assert result["status"] == "pass"


@patch("src.ingestion.data_validator.get_supabase")
@patch(
    "src.ingestion.data_validator.check_completeness",
    return_value=["AAPL: missing 2026-04-22"],
)
@patch("src.ingestion.data_validator.check_freshness", return_value=[])
@patch("src.ingestion.data_validator.check_sanity", return_value=[])
@patch("src.ingestion.data_validator.check_duplicates", return_value=[])
def test_validate_data_status_warn_on_completeness_issue(
    mock_dupes, mock_sanity, mock_fresh, mock_complete, mock_db
):
    mock_db.return_value = MagicMock()
    result = dv.validate_data()
    assert result["status"] == "warn"
    assert result["checks"]["completeness"]["status"] == "warn"


@patch("src.ingestion.data_validator.get_supabase")
@patch("src.ingestion.data_validator.check_completeness", return_value=[])
@patch("src.ingestion.data_validator.check_freshness", return_value=[])
@patch(
    "src.ingestion.data_validator.check_sanity",
    return_value=["asset 1: invalid close -5"],
)
@patch("src.ingestion.data_validator.check_duplicates", return_value=[])
def test_validate_data_status_fail_on_sanity_issue(
    mock_dupes, mock_sanity, mock_fresh, mock_complete, mock_db
):
    mock_db.return_value = MagicMock()
    result = dv.validate_data()
    assert result["status"] == "fail"
    assert result["checks"]["sanity"]["status"] == "fail"


@patch("src.ingestion.data_validator.get_supabase")
@patch("src.ingestion.data_validator.check_completeness", return_value=[])
@patch("src.ingestion.data_validator.check_freshness", return_value=[])
@patch("src.ingestion.data_validator.check_sanity", return_value=[])
@patch(
    "src.ingestion.data_validator.check_duplicates",
    return_value=["duplicate price row: (1, '2026-04-20')"],
)
def test_validate_data_status_fail_on_duplicate_issue(
    mock_dupes, mock_sanity, mock_fresh, mock_complete, mock_db
):
    mock_db.return_value = MagicMock()
    result = dv.validate_data()
    assert result["status"] == "fail"
