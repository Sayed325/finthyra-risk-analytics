# author: @ShoumikDutta

import pandas as pd
from pathlib import Path

REQUIRED_COLUMNS = {
    "date",
    "ticker",
    "asset_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "daily_return",
}


def validate_backfill_csv(csv_path="historical_backfill_export.csv"):
    csv_file = Path(csv_path)

    if not csv_file.exists():
        print(f"ERROR: File not found: {csv_file}")
        return {"status": "fail", "issues": [f"File not found: {csv_file}"]}

    df = pd.read_csv(csv_file)

    issues = []
    warnings = []

    # 1) Required columns
    missing_cols = REQUIRED_COLUMNS - set(df.columns)
    if missing_cols:
        issues.append(f"Missing required columns: {sorted(missing_cols)}")
        return {"status": "fail", "issues": issues, "warnings": warnings}

    # 2) Parse date
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    bad_dates = df["date"].isna().sum()
    if bad_dates > 0:
        issues.append(f"{bad_dates} rows have invalid dates")

    # 3) Duplicate ticker-date rows
    dupes = df.duplicated(subset=["ticker", "date"]).sum()
    if dupes > 0:
        issues.append(f"{dupes} duplicate (ticker, date) rows found")

    # 4) Basic numeric sanity
    numeric_cols = ["open", "high", "low", "close", "volume", "daily_return"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    bad_close = (df["close"] <= 0).sum()
    if bad_close > 0:
        issues.append(f"{bad_close} rows have close <= 0")

    bad_volume = ((df["volume"] < 0) & df["volume"].notna()).sum()
    if bad_volume > 0:
        issues.append(f"{bad_volume} rows have negative volume")

    bad_high_low = (df["high"] < df["low"]).sum()
    if bad_high_low > 0:
        issues.append(f"{bad_high_low} rows have high < low")

    bad_open_range = ((df["open"] < df["low"]) | (df["open"] > df["high"])).sum()
    if bad_open_range > 0:
        warnings.append(f"{bad_open_range} rows have open outside low-high range")

    bad_close_range = ((df["close"] < df["low"]) | (df["close"] > df["high"])).sum()
    if bad_close_range > 0:
        warnings.append(f"{bad_close_range} rows have close outside low-high range")

    # 5) Per ticker checks
    ticker_summary = []

    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("date").reset_index(drop=True)

        # dates sorted
        if not g["date"].is_monotonic_increasing:
            issues.append(f"{ticker}: dates are not sorted")

        # missing close rows
        missing_close = g["close"].isna().sum()
        if missing_close > 0:
            warnings.append(f"{ticker}: {missing_close} rows have missing close")

        # recalculate daily return after removing missing close
        g_clean = g.dropna(subset=["close"]).copy()
        g_clean["recalc_daily_return"] = g_clean["close"].pct_change()

        # count NaN daily_return
        dr_nan_count = g["daily_return"].isna().sum()
        if dr_nan_count > 1:
            warnings.append(
                f"{ticker}: daily_return has {dr_nan_count} NaN values (expected usually 1)"
            )

        # extreme returns
        extreme_returns = (
            (g_clean["recalc_daily_return"] < -0.5)
            | (g_clean["recalc_daily_return"] > 0.5)
        ).sum()
        if extreme_returns > 0:
            issues.append(
                f"{ticker}: {extreme_returns} extreme daily_return values found"
            )

        # compare saved vs recalculated daily_return
        compare = g_clean[["daily_return", "recalc_daily_return"]].dropna()
        if not compare.empty:
            mismatch = (
                (compare["daily_return"] - compare["recalc_daily_return"]).abs() > 1e-6
            ).sum()
            if mismatch > 0:
                warnings.append(
                    f"{ticker}: {mismatch} daily_return mismatches vs recalculation"
                )

        ticker_summary.append(
            {
                "ticker": ticker,
                "rows": len(g),
                "start_date": (
                    g["date"].min().date() if g["date"].notna().any() else None
                ),
                "end_date": g["date"].max().date() if g["date"].notna().any() else None,
                "missing_close": int(missing_close),
                "daily_return_nan": int(dr_nan_count),
            }
        )

    summary_df = pd.DataFrame(ticker_summary).sort_values("ticker")
    summary_file = csv_file.with_name("backfill_validation_summary.csv")
    summary_df.to_csv(summary_file, index=False)

    status = "pass"
    if issues:
        status = "fail"
    elif warnings:
        status = "warn"

    print("\n=== VALIDATION RESULT ===")
    print(f"Status: {status}")
    print(f"Summary file: {summary_file}")

    if issues:
        print("\nIssues:")
        for x in issues:
            print(f"- {x}")

    if warnings:
        print("\nWarnings:")
        for x in warnings:
            print(f"- {x}")

    print("\nPer-ticker summary:")
    print(summary_df.to_string(index=False))

    return {
        "status": status,
        "issues": issues,
        "warnings": warnings,
        "summary_file": str(summary_file),
    }


if __name__ == "__main__":
    validate_backfill_csv()
