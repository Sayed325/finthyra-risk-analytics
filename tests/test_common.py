from unittest.mock import MagicMock, patch
from datetime import date, datetime
import pytest

from src.ingestion.common import retry, get_logger, today_iso, to_iso_date


# ---- retry ----

def test_retry_succeeds_on_first_try():
    fn = MagicMock(return_value=42)
    result = retry(fn, retries=3, delay_seconds=0)
    assert result == 42
    assert fn.call_count == 1


def test_retry_retries_then_succeeds():
    fn = MagicMock(side_effect=[ValueError("first"), ValueError("second"), "ok"])
    with patch("src.ingestion.common.time.sleep"):
        result = retry(fn, retries=3, delay_seconds=1)
    assert result == "ok"
    assert fn.call_count == 3


def test_retry_raises_after_exhausting_retries():
    fn = MagicMock(side_effect=RuntimeError("always fails"))
    with patch("src.ingestion.common.time.sleep"):
        with pytest.raises(RuntimeError, match="always fails"):
            retry(fn, retries=3, delay_seconds=1)
    assert fn.call_count == 3


def test_retry_logs_warning_on_each_failure():
    logger = MagicMock()
    fn = MagicMock(side_effect=[ValueError("boom"), "ok"])
    with patch("src.ingestion.common.time.sleep"):
        retry(fn, retries=3, delay_seconds=1, logger=logger, context="test op")
    logger.warning.assert_called_once()
    assert "test op" in logger.warning.call_args[0][0]


def test_retry_does_not_sleep_after_last_attempt():
    fn = MagicMock(side_effect=ValueError("fail"))
    with patch("src.ingestion.common.time.sleep") as mock_sleep:
        with pytest.raises(ValueError):
            retry(fn, retries=2, delay_seconds=5)
    assert mock_sleep.call_count == 1  # sleeps between attempt 1 and 2, not after 2


# ---- get_logger ----

def test_get_logger_returns_logger_with_correct_name():
    logger = get_logger("my_test_module")
    assert logger.name == "my_test_module"


def test_get_logger_does_not_add_duplicate_handlers():
    get_logger("dedup_test")
    logger = get_logger("dedup_test")
    assert len(logger.handlers) == 1


def test_get_logger_does_not_propagate():
    logger = get_logger("no_propagate_test")
    assert logger.propagate is False


# ---- today_iso ----

def test_today_iso_returns_valid_iso_string():
    result = today_iso()
    assert isinstance(result, str)
    date.fromisoformat(result)  # raises ValueError if invalid


def test_today_iso_matches_todays_date():
    result = today_iso()
    assert result == date.today().isoformat()


# ---- to_iso_date ----

def test_to_iso_date_from_datetime():
    dt = datetime(2026, 4, 24, 15, 30, 0)
    assert to_iso_date(dt) == "2026-04-24"


def test_to_iso_date_from_date():
    d = date(2026, 4, 24)
    assert to_iso_date(d) == "2026-04-24"


def test_to_iso_date_from_string_passthrough():
    assert to_iso_date("2026-04-24") == "2026-04-24"


def test_to_iso_date_from_object_with_date_method():
    class FakeDatetime:
        def date(self):
            return date(2026, 1, 15)

    assert to_iso_date(FakeDatetime()) == "2026-01-15"
