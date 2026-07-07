"""VaR, Sharpe, Max Drawdown, Beta, Correlation."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from src.ingestion.common import get_logger, get_supabase

logger = get_logger("risk_metrics")


# -------------------- DATA LOADING --------------------


def load_prices(
    supabase, asset_ids: list[int], lookback_days: int = 756
) -> pd.DataFrame:
    frames = []
    for asset_id in asset_ids:
        response = (
            supabase.table("prices")
            .select("asset_id,date,close,daily_return")
            .eq("asset_id", asset_id)
            .order("date", desc=True)
            .limit(lookback_days)
            .execute()
        )
        rows = response.data or []
        if rows:
            frames.append(pd.DataFrame(rows))

    if not frames:
        return pd.DataFrame(columns=["asset_id", "date", "close", "daily_return"])

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    df = df.dropna(subset=["daily_return"])
    df = df.sort_values(["asset_id", "date"]).reset_index(drop=True)
    return df


def load_benchmark_returns(supabase) -> pd.Series:
    response = (
        supabase.table("assets")
        .select("id")
        .eq("is_benchmark", True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        logger.warning("No benchmark asset found in assets table")
        return pd.Series(dtype=float)

    benchmark_id = rows[0]["id"]

    response = (
        supabase.table("prices")
        .select("date,daily_return")
        .eq("asset_id", benchmark_id)
        .order("date", desc=True)
        .limit(756)
        .execute()
    )
    rows = response.data or []
    if not rows:
        logger.warning(f"No price data found for benchmark asset_id={benchmark_id}")
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    df = df.dropna(subset=["daily_return"])
    df = df.sort_values("date").set_index("date")
    return df["daily_return"].astype(float)


def load_risk_free_rate(supabase) -> float:
    response = (
        supabase.table("macro_indicators")
        .select("value")
        .eq("indicator", "treasury_yield_10y")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        logger.warning("No treasury_yield_10y data found — using 0.0 as risk-free rate")
        return 0.0
    annual_rate = float(rows[0]["value"])
    return annual_rate / 100 / 252


def load_portfolio_holdings(supabase, portfolio_id: int) -> dict[int, float]:
    response = (
        supabase.table("portfolio_holdings")
        .select("asset_id,weight")
        .eq("portfolio_id", portfolio_id)
        .execute()
    )
    rows = response.data or []
    return {row["asset_id"]: float(row["weight"]) for row in rows}


# -------------------- CALCULATIONS --------------------


def compute_portfolio_returns(
    returns_df: pd.DataFrame, weights: dict[int, float]
) -> pd.Series:
    wide = returns_df.pivot(index="date", columns="asset_id", values="daily_return")
    valid_cols = [c for c in wide.columns if c in weights]
    wide = wide[valid_cols].copy()
    wide = wide.dropna()
    for col in valid_cols:
        wide[col] = wide[col].astype(float) * weights[col]
    return wide.sum(axis=1)


def compute_var(returns: pd.Series, confidence: float = 0.95) -> float:
    return float(np.percentile(returns, (1 - confidence) * 100))


def compute_sharpe(returns: pd.Series, daily_risk_free: float) -> float:
    std = float(returns.std())
    # Guard against near-zero std (constant return series or floating-point noise)
    if std < 1e-10:
        return 0.0
    sharpe = (returns.mean() - daily_risk_free) / std * np.sqrt(252)
    return round(float(sharpe), 4)


def compute_max_drawdown(returns: pd.Series) -> float:
    wealth = (1 + returns).cumprod()
    rolling_max = wealth.cummax()
    drawdown = (wealth - rolling_max) / rolling_max
    return float(drawdown.min())


def compute_beta(
    portfolio_returns: pd.Series, benchmark_returns: pd.Series
) -> float | None:
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join="inner")
    aligned.columns = ["portfolio", "benchmark"]
    aligned = aligned.dropna()

    if len(aligned) < 30:
        logger.warning(f"Insufficient overlapping dates for beta ({len(aligned)} < 30)")
        return None

    bench_var = aligned["benchmark"].var()
    if bench_var == 0:
        logger.warning("Benchmark variance is 0 — cannot compute beta")
        return None

    beta = aligned["portfolio"].cov(aligned["benchmark"]) / bench_var
    return round(float(beta), 4)


def compute_correlation_matrix(
    returns_df: pd.DataFrame, asset_map: dict[int, str]
) -> dict:
    wide = returns_df.pivot(index="date", columns="asset_id", values="daily_return")
    corr = wide.corr()
    rename_map = {k: v for k, v in asset_map.items() if k in corr.columns}
    corr = corr.rename(columns=rename_map, index=rename_map)

    result: dict[str, dict[str, Any]] = {}
    for ticker_row in corr.index:
        result[str(ticker_row)] = {}
        for ticker_col in corr.columns:
            val = corr.loc[ticker_row, ticker_col]
            result[str(ticker_row)][str(ticker_col)] = (
                round(float(val), 4) if not pd.isna(val) else None
            )
    return result


# -------------------- WRITE --------------------


def write_risk_metrics(supabase, portfolio_id: int, metrics: dict) -> None:
    row = {
        "portfolio_id": portfolio_id,
        "date": date.today().isoformat(),
        "var_95": metrics.get("var_95"),
        "var_99": metrics.get("var_99"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "max_drawdown": metrics.get("max_drawdown"),
        "beta_vs_benchmark": metrics.get("beta_vs_benchmark"),
        "anomaly_flag": False,
        "anomaly_score": None,
        "anomaly_type": None,
        "ai_briefing": None,
    }

    try:
        supabase.table("risk_metrics").upsert(
            row,
            on_conflict="portfolio_id,date",
        ).execute()
    except Exception as exc:
        raise RuntimeError(
            f"Supabase write failed for risk_metrics portfolio_id={portfolio_id}: {exc}"
        ) from exc


# -------------------- ORCHESTRATOR --------------------


def compute_risk_metrics() -> dict[str, Any]:
    try:
        supabase = get_supabase()

        # Load default portfolio
        response = (
            supabase.table("portfolio_configurations")
            .select("id")
            .eq("is_default", True)
            .limit(1)
            .execute()
        )
        portfolio_rows = response.data or []
        if not portfolio_rows:
            raise RuntimeError("No default portfolio found in portfolio_configurations")

        portfolio_id = portfolio_rows[0]["id"]
        logger.info(f"Using default portfolio_id={portfolio_id}")

        # Load holdings
        weights = load_portfolio_holdings(supabase, portfolio_id)
        if not weights:
            raise RuntimeError(f"No holdings found for portfolio_id={portfolio_id}")

        asset_ids = list(weights.keys())
        logger.info(f"Portfolio has {len(asset_ids)} assets")

        # Load price data
        prices_df = load_prices(supabase, asset_ids)
        if prices_df.empty:
            raise RuntimeError("No price data loaded for portfolio assets")

        # Load benchmark returns
        benchmark_returns = load_benchmark_returns(supabase)

        # Load risk-free rate
        daily_rf = load_risk_free_rate(supabase)
        logger.info(f"Daily risk-free rate: {daily_rf:.8f}")

        # Compute portfolio returns
        portfolio_returns = compute_portfolio_returns(prices_df, weights)
        logger.info(f"Portfolio return series: {len(portfolio_returns)} days")

        # Compute metrics
        var_95 = compute_var(portfolio_returns, confidence=0.95)
        var_99 = compute_var(portfolio_returns, confidence=0.99)
        sharpe = compute_sharpe(portfolio_returns, daily_rf)
        max_dd = compute_max_drawdown(portfolio_returns)
        beta = compute_beta(portfolio_returns, benchmark_returns)

        logger.info(
            f"Metrics — VaR(95)={var_95:.6f} | VaR(99)={var_99:.6f} | "
            f"Sharpe={sharpe} | MaxDD={max_dd:.6f} | Beta={beta}"
        )

        # Compute correlation matrix (log only — no DB column yet)
        response = (
            supabase.table("assets").select("id,ticker").in_("id", asset_ids).execute()
        )
        asset_map = {row["id"]: row["ticker"] for row in (response.data or [])}
        corr_matrix = compute_correlation_matrix(prices_df, asset_map)
        logger.info(f"Correlation matrix computed for {len(corr_matrix)} assets")

        # Write to DB
        metrics = {
            "var_95": round(var_95, 6),
            "var_99": round(var_99, 6),
            "sharpe_ratio": sharpe,
            "max_drawdown": round(max_dd, 6),
            "beta_vs_benchmark": beta,
        }

        write_risk_metrics(supabase, portfolio_id, metrics)
        logger.info(
            f"Risk metrics written to DB for portfolio_id={portfolio_id}, "
            f"date={date.today().isoformat()}"
        )

        return {
            "portfolio_id": portfolio_id,
            "var_95": metrics["var_95"],
            "var_99": metrics["var_99"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "max_drawdown": metrics["max_drawdown"],
            "beta_vs_benchmark": metrics["beta_vs_benchmark"],
            "status": "success",
            "error": None,
        }

    except Exception as exc:
        logger.error(f"compute_risk_metrics failed: {exc}")
        return {
            "portfolio_id": None,
            "var_95": None,
            "var_99": None,
            "sharpe_ratio": None,
            "max_drawdown": None,
            "beta_vs_benchmark": None,
            "status": "failure",
            "error": str(exc),
        }


if __name__ == "__main__":
    import json

    result = compute_risk_metrics()
    print(json.dumps(result, indent=2, default=str))
