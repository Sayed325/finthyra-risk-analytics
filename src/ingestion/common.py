#Author: @ShoumikDutta
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv
from supabase import Client, create_client

T = TypeVar("T")

load_dotenv()


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(f"[{name}] %(levelname)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.propagate = False
    return logger


def get_supabase() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SECRET_KEY"]
    return create_client(url, key)


def today_iso() -> str:
    return date.today().isoformat()


def to_iso_date(value: Any) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def retry(
    fn: Callable[[], T],
    retries: int = 3,
    delay_seconds: int = 5,
    logger: logging.Logger | None = None,
    context: str = "",
) -> T:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if logger:
                logger.warning(
                    f"{context} failed on attempt {attempt}/{retries}: {exc}"
                )
            if attempt < retries:
                time.sleep(delay_seconds)

    raise last_error