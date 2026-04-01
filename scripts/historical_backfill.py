#Author: @ShoumikDutta
import os
import time
import logging
from datetime import datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from supabase import create_client

# -------------------- CONFIG --------------------
START_DATE_DEFAULT = "2022-01-01"
MAX_RETRIES = 3
RETRY_BACKOFF = 5  # seconds

# -------------------- LOGGING --------------------
logging.basicConfig(
    level=logging.INFO,
    format="[historical_backfill] %(levelname)s: %(message)s"
)

# -------------------- ENV --------------------
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# -------------------- HELPERS --------------------
def get_active_assets():
    res = supabase.table("assets").select("id,ticker").eq("is_active", True).execute()
    return res.data


def get_existing_dates(asset_id):
    res = (
        supabase.table("prices")
        .select("date")
        .eq("asset_id", asset_id)
        .execute()
    )
    return {row["date"] for row in res.data}


def compute_returns(df: pd.DataFrame):
    df["daily_return"] = df["Close"].pct_change()
    return df


def format_rows(df, asset_id):
    rows = []
    for date, row in df.iterrows():
        rows.append({
            "asset_id": asset_id,
            "date": date.strftime("%Y-%m-%d"),
            "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
            "high": float(row["High"]) if pd.notna(row["High"]) else None,
            "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
            "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
            "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            "daily_return": float(row["daily_return"]) if pd.notna(row["daily_return"]) else None,
        })
    return rows


def upsert_rows(rows):
    if not rows:
        return 0
    supabase.table("prices").upsert(rows).execute()
    return len(rows)


# -------------------- MAIN --------------------
def run_backfill(start_date: str = START_DATE_DEFAULT) -> dict:
    today = datetime.utcnow().strftime("%Y-%m-%d")

    assets = get_active_assets()

    total_rows = 0
    failures = []
    processed = 0

    tickers = [a["ticker"] for a in assets]
    ticker_to_id = {a["ticker"]: a["id"] for a in assets}

    logging.info(f"Starting bulk download for {len(tickers)} tickers")

    # ---------- BULK DOWNLOAD ----------
    bulk_data = None
    for attempt in range(MAX_RETRIES):
        try:
            bulk_data = yf.download(
                tickers=tickers,
                start=start_date,
                end=today,
                group_by="ticker",
                auto_adjust=False,
                threads=True
            )
            break
        except Exception as e:
            logging.warning(f"Bulk fetch failed (attempt {attempt+1}): {e}")
            time.sleep(RETRY_BACKOFF)

    if bulk_data is None:
        logging.error("Bulk download failed completely")
        return {"tickers_processed": 0, "total_rows": 0, "failures": tickers}

    # ---------- VERIFY TICKERS ----------
    available_tickers = list(bulk_data.columns.levels[0]) if isinstance(bulk_data.columns, pd.MultiIndex) else tickers

    missing_tickers = [t for t in tickers if t not in available_tickers]

    if missing_tickers:
        logging.warning(f"Missing in bulk fetch: {missing_tickers}")

    # ---------- PROCESS BULK ----------
    for ticker in available_tickers:
        asset_id = ticker_to_id[ticker]

        try:
            df = bulk_data[ticker].copy()

            if df.empty:
                logging.warning(f"{ticker}: no data returned")
                continue

            df = df.dropna(subset=["Close"])
            df = compute_returns(df)

            existing_dates = get_existing_dates(asset_id)

            df = df[~df.index.strftime("%Y-%m-%d").isin(existing_dates)]

            rows = format_rows(df, asset_id)
            inserted = upsert_rows(rows)

            total_rows += inserted
            processed += 1

            if not df.empty:
                logging.info(
                    f"{ticker}: {inserted} rows "
                    f"({df.index.min().date()} → {df.index.max().date()})"
                )

        except Exception as e:
            logging.error(f"{ticker}: failed - {e}")
            failures.append(ticker)

    # ---------- REFETCH MISSING ----------
    for ticker in missing_tickers:
        asset_id = ticker_to_id[ticker]

        success = False

        for attempt in range(MAX_RETRIES):
            try:
                df = yf.download(ticker, start=start_date, end=today)

                if df.empty:
                    logging.warning(f"{ticker}: no data even after retry")
                    break

                df = df.dropna(subset=["Close"])
                df = compute_returns(df)

                existing_dates = get_existing_dates(asset_id)
                df = df[~df.index.strftime("%Y-%m-%d").isin(existing_dates)]

                rows = format_rows(df, asset_id)
                inserted = upsert_rows(rows)

                total_rows += inserted
                processed += 1

                logging.info(f"{ticker}: recovered {inserted} rows")

                success = True
                break

            except Exception as e:
                logging.warning(f"{ticker} retry {attempt+1} failed: {e}")
                time.sleep(RETRY_BACKOFF)

        if not success:
            failures.append(ticker)

    # ---------- SUMMARY ----------
    logging.info(
        f"Complete: {processed} tickers, {total_rows} total rows, {len(failures)} failures"
    )

    return {
        "tickers_processed": processed,
        "total_rows": total_rows,
        "failures": failures
    }


# -------------------- CLI --------------------
if __name__ == "__main__":
    result = run_backfill()
    print(result)
"""One-time historical data backfill (3+ years)."""
