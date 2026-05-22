"""Lag variables, rolling stats, returns."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.ingestion.common import get_logger, get_supabase

logger = get_logger("feature_engineering")

MACRO_INDICATORS = ["vix_level", "fed_funds_rate", "treasury_yield_10y"]

# Mapping from macro_indicators.indicator names to DataFrame column names
MACRO_COLUMN_MAP = {
    "vix": "vix_level",
    "fed_funds_rate": "fed_funds_rate",
    "treasury_yield_10y": "treasury_yield_10y",
}


def _load_active_assets(supabase) -> list[dict[str, Any]]:
    response = (
        supabase.table("assets")
        .select("id,ticker,is_benchmark")
        .eq("is_active", True)
        .execute()
    )
    return response.data or []


def _load_prices_for_asset(supabase, asset_id: int, lookback_days: int) -> pd.DataFrame:
    response = (
        supabase.table("prices")
        .select("date,open,high,low,close,volume,daily_return")
        .eq("asset_id", asset_id)
        .order("date")
        .limit(lookback_days + 60)  # extra buffer for rolling windows
        .execute()
    )
    rows = response.data or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["close", "volume", "daily_return"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def _load_macro_data(supabase) -> pd.DataFrame:
    """Load VIX, fed funds rate, and 10Y treasury from macro_indicators."""
    indicators = ["vix", "fed_funds_rate", "treasury_yield_10y"]
    frames = []
    for indicator in indicators:
        response = (
            supabase.table("macro_indicators")
            .select("date,value")
            .eq("indicator", indicator)
            .order("date")
            .execute()
        )
        rows = response.data or []
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        col_name = MACRO_COLUMN_MAP.get(indicator, indicator)
        df = df.rename(columns={"value": col_name})[["date", col_name]]
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["date"] + MACRO_INDICATORS)

    macro = frames[0]
    for f in frames[1:]:
        macro = macro.merge(f, on="date", how="outer")
    macro = macro.sort_values("date").reset_index(drop=True)
    # Ensure all expected columns exist
    for col in MACRO_INDICATORS:
        if col not in macro.columns:
            macro[col] = np.nan
    return macro


def _compute_asset_features(df: pd.DataFrame, asset_id: int, ticker: str) -> pd.DataFrame:
    """Compute per-asset rolling features. Returns DataFrame with all feature columns."""
    df = df.copy()

    # rolling_volatility_20d
    df["rolling_volatility_20d"] = df["daily_return"].rolling(20).std()

    # rolling_return_20d: cumulative product of (1+r) over trailing 20 days, minus 1
    df["rolling_return_20d"] = (
        df["daily_return"]
        .add(1)
        .rolling(20)
        .apply(lambda x: x.prod() - 1, raw=True)
    )

    # return_zscore_20d — 0 when std is 0 (constant return series means no deviation)
    rolling_mean_20d = df["daily_return"].rolling(20).mean()
    rolling_std_20d = df["daily_return"].rolling(20).std()
    with np.errstate(divide="ignore", invalid="ignore"):
        zscore_raw = (df["daily_return"] - rolling_mean_20d) / rolling_std_20d
    df["return_zscore_20d"] = zscore_raw.fillna(0)

    # drawdown: (close - rolling_max_close) / rolling_max_close
    rolling_max_close = df["close"].expanding().max()
    df["drawdown"] = (df["close"] - rolling_max_close) / rolling_max_close

    # drawdown_acceleration: today's drawdown minus drawdown 5 days ago
    df["drawdown_acceleration"] = df["drawdown"] - df["drawdown"].shift(5)

    # volume_zscore_20d — 0 when std is 0 (constant volume means no spike)
    rolling_mean_vol = df["volume"].rolling(20).mean()
    rolling_std_vol = df["volume"].rolling(20).std()
    with np.errstate(divide="ignore", invalid="ignore"):
        vol_zscore_raw = (df["volume"] - rolling_mean_vol) / rolling_std_vol
    df["volume_zscore_20d"] = vol_zscore_raw.fillna(0)

    df["asset_id"] = asset_id
    df["ticker"] = ticker

    return df


def build_features(lookback_days: int = 252) -> pd.DataFrame:
    """Compute per-asset features for all active assets.

    Returns a DataFrame with one row per (asset, date), sorted by (date, asset_id).
    Rows with any NaN feature are dropped (first ~20 rows per asset due to rolling windows).
    """
    supabase = get_supabase()

    assets = _load_active_assets(supabase)
    logger.info(f"Loaded {len(assets)} active assets")

    macro_df = _load_macro_data(supabase)
    if macro_df.empty or all(macro_df[c].isna().all() for c in MACRO_INDICATORS if c in macro_df.columns):
        logger.warning("Macro data missing or empty — macro columns will be NaN")

    feature_frames = []
    skipped = 0

    for asset in assets:
        asset_id = asset["id"]
        ticker = asset["ticker"]

        prices = _load_prices_for_asset(supabase, asset_id, lookback_days)

        if prices.empty or len(prices) < 30:
            logger.warning(f"Skipping {ticker} (asset_id={asset_id}): only {len(prices)} rows of price data")
            skipped += 1
            continue

        feat = _compute_asset_features(prices, asset_id, ticker)
        feature_frames.append(feat)

    if skipped:
        logger.info(f"Skipped {skipped} assets with insufficient price data")

    if not feature_frames:
        logger.warning("No feature data computed — returning empty DataFrame")
        return pd.DataFrame()

    all_features = pd.concat(feature_frames, ignore_index=True)

    # Merge macro context — forward-fill for weekends/holidays
    if not macro_df.empty:
        all_dates = all_features[["date"]].drop_duplicates().sort_values("date")
        macro_filled = (
            all_dates
            .merge(macro_df, on="date", how="left")
            .sort_values("date")
        )
        # Forward-fill macro values for missing dates
        for col in MACRO_INDICATORS:
            if col in macro_filled.columns:
                macro_filled[col] = macro_filled[col].ffill()

        all_features = all_features.merge(macro_filled, on="date", how="left")
    else:
        for col in MACRO_INDICATORS:
            all_features[col] = np.nan

    feature_cols = [
        "rolling_volatility_20d",
        "rolling_return_20d",
        "return_zscore_20d",
        "drawdown",
        "drawdown_acceleration",
        "volume_zscore_20d",
        "vix_level",
        "fed_funds_rate",
        "treasury_yield_10y",
    ]

    # Drop rows where any per-asset rolling feature is NaN (first ~20 rows per asset).
    # Macro columns may be NaN when data is missing — model handles that gracefully.
    per_asset_cols = [
        "rolling_volatility_20d",
        "rolling_return_20d",
        "return_zscore_20d",
        "drawdown",
        "drawdown_acceleration",
        "volume_zscore_20d",
    ]
    all_features = all_features.dropna(subset=per_asset_cols)

    # Select and order columns
    output_cols = ["asset_id", "ticker", "date"] + feature_cols
    all_features = all_features[output_cols].copy()
    all_features = all_features.sort_values(["date", "asset_id"]).reset_index(drop=True)

    date_min = all_features["date"].min()
    date_max = all_features["date"].max()
    logger.info(
        f"Feature build complete: {len(all_features)} rows, "
        f"{all_features['asset_id'].nunique()} assets, "
        f"date range {date_min} to {date_max}"
    )

    return all_features


def build_features_for_date(target_date: str | None = None) -> pd.DataFrame:
    """Return features for all assets on a single date (default: today)."""
    if target_date is None:
        target_date = date.today().isoformat()

    all_features = build_features()

    if all_features.empty:
        return pd.DataFrame()

    target_dt = pd.Timestamp(target_date)
    result = all_features[all_features["date"] == target_dt].copy()

    if result.empty:
        logger.warning(f"No feature data available for date={target_date}")

    return result.reset_index(drop=True)


if __name__ == "__main__":
    df = build_features()
    print("Shape:", df.shape)
    print("Columns:", df.columns.tolist())
    print(df.tail(5).to_string())
