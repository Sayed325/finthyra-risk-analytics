#author: @ShoumikDutta

import os
import pandas as pd
import yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

from src.ingestion.common import get_supabase

load_dotenv()


def export_backfill_to_csv(start_date="2022-01-01"):
    """
    Fetch historical market data from Yahoo Finance
    and save it into a CSV file.

    This does NOT write to Supabase.
    It only exports the raw API data for checking/testing.
    """

    supabase = get_supabase()

    # Get active assets from DB
    assets = (
        supabase.table("assets")
        .select("id,ticker")
        .eq("is_active", True)
        .execute()
        .data
    )

    if not assets:
        print("No active assets found.")
        return

    tickers = [a["ticker"] for a in assets]
    asset_map = {a["ticker"]: a["id"] for a in assets}

    print(f"Fetching historical data for {len(tickers)} tickers...")

    end_date = datetime.today().strftime("%Y-%m-%d")

    # Bulk download from yfinance
    data = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        group_by="ticker",
        auto_adjust=False,
        progress=True
    )

    all_rows = []

    for ticker in tickers:
        try:
            if ticker not in data.columns.levels[0]:
                print(f"WARNING: No data found for {ticker}")
                continue

            ticker_df = data[ticker].copy()
            ticker_df.reset_index(inplace=True)

            ticker_df["ticker"] = ticker
            ticker_df["asset_id"] = asset_map[ticker]

            # Keep only needed columns
            ticker_df = ticker_df[
                ["Date", "ticker", "asset_id", "Open", "High", "Low", "Close", "Volume"]
            ]

            ticker_df.columns = [
                "date",
                "ticker",
                "asset_id",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]

            # Calculate daily return
            ticker_df["daily_return"] = ticker_df["close"].pct_change()

            all_rows.append(ticker_df)

            print(f"{ticker}: {len(ticker_df)} rows")

        except Exception as e:
            print(f"ERROR processing {ticker}: {e}")

    if not all_rows:
        print("No data fetched.")
        return

    final_df = pd.concat(all_rows, ignore_index=True)

    output_file = "historical_backfill_export.csv"
    final_df.to_csv(output_file, index=False)

    print(f"\nCSV saved successfully: {output_file}")
    print(f"Total rows: {len(final_df)}")


if __name__ == "__main__":
    export_backfill_to_csv()