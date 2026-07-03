"""Gemini round-robin key rotation + briefing generation."""
from __future__ import annotations

import itertools
import os
from typing import Any

from src.ingestion.common import get_logger, get_supabase, utc_today

logger = get_logger("gemini_commentary")

# -------------------- KEY ROTATION --------------------

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

_keys: list[str] = []
_combinations: list[tuple[str, str]] = []  # (api_key, model_name)
_combination_cycle: itertools.cycle | None = None


def _load_keys() -> list[str]:
    """Load Gemini API keys from env vars GEMINI_KEY_1..5, filtering empty/None."""
    result = []
    for i in range(1, 6):
        key = os.environ.get(f"GEMINI_KEY_{i}", "") or ""
        if key:
            result.append(key)
    return result


def _build_combinations(keys: list[str]) -> list[tuple[str, str]]:
    """Build (api_key, model_name) rotation: all keys for each model in order."""
    return [(key, model) for model in GEMINI_MODELS for key in keys]


def _call_gemini(prompt: str) -> str:
    """Call Gemini cycling through (key, model) combinations; falls back on any error."""
    from google import genai
    from google.genai import types

    global _keys, _combinations, _combination_cycle
    if not _keys:
        _keys = _load_keys()
        if _keys:
            _combinations = _build_combinations(_keys)
            _combination_cycle = itertools.cycle(_combinations)

    if not _combinations or _combination_cycle is None:
        raise RuntimeError("No Gemini API keys configured")

    n = len(_combinations)
    last_error: Exception | None = None

    for _ in range(n):
        key, model_name = next(_combination_cycle)
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.3),
            )
            return response.text
        except Exception as exc:
            logger.warning(f"Gemini {model_name} call failed: {exc}")
            last_error = exc

    raise RuntimeError(f"All {n} Gemini combinations exhausted. Last error: {last_error}")


# -------------------- DATA LOADING --------------------

def _load_risk_metrics(supabase, portfolio_id: int, today: str) -> dict | None:
    response = (
        supabase.table("risk_metrics")
        .select("*")
        .eq("portfolio_id", portfolio_id)
        .eq("date", today)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def _load_latest_macro(supabase) -> dict[str, float | None]:
    indicators = ["fed_funds_rate", "cpi", "treasury_yield_10y", "vix", "eur_usd_rate"]
    result: dict[str, float | None] = {}
    for indicator in indicators:
        response = (
            supabase.table("macro_indicators")
            .select("value")
            .eq("indicator", indicator)
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        result[indicator] = float(rows[0]["value"]) if rows else None
    return result


def _load_portfolio_holdings(supabase, portfolio_id: int) -> list[dict]:
    response = (
        supabase.table("portfolio_holdings")
        .select("asset_id, weight")
        .eq("portfolio_id", portfolio_id)
        .execute()
    )
    holdings = response.data or []
    if not holdings:
        return []

    asset_ids = [h["asset_id"] for h in holdings]
    response = (
        supabase.table("assets")
        .select("id, ticker, name")
        .in_("id", asset_ids)
        .execute()
    )
    asset_map = {row["id"]: row for row in (response.data or [])}

    result = []
    for h in holdings:
        asset = asset_map.get(h["asset_id"], {})
        result.append({
            "asset_id": h["asset_id"],
            "weight": float(h["weight"]),
            "ticker": asset.get("ticker", "UNKNOWN"),
            "name": asset.get("name", "Unknown"),
        })
    return result


def _load_worst_performer(supabase, portfolio_id: int, today: str) -> dict | None:
    holdings_resp = (
        supabase.table("portfolio_holdings")
        .select("asset_id")
        .eq("portfolio_id", portfolio_id)
        .execute()
    )
    asset_ids = [row["asset_id"] for row in (holdings_resp.data or [])]
    if not asset_ids:
        return None

    # Try today's date first
    response = (
        supabase.table("prices")
        .select("asset_id, date, daily_return")
        .in_("asset_id", asset_ids)
        .eq("date", today)
        .order("daily_return", desc=False)
        .limit(1)
        .execute()
    )
    rows = response.data or []

    # Fall back to most recent trading day if no data today
    if not rows:
        response = (
            supabase.table("prices")
            .select("asset_id, date, daily_return")
            .in_("asset_id", asset_ids)
            .order("daily_return", desc=False)
            .limit(1)
            .execute()
        )
        rows = response.data or []

    if not rows:
        return None

    worst = rows[0]
    asset_resp = (
        supabase.table("assets")
        .select("ticker, name")
        .eq("id", worst["asset_id"])
        .limit(1)
        .execute()
    )
    asset_rows = asset_resp.data or []
    asset = asset_rows[0] if asset_rows else {}
    return {
        "asset_id": worst["asset_id"],
        "ticker": asset.get("ticker", "UNKNOWN"),
        "name": asset.get("name", "Unknown"),
        "daily_return": float(worst["daily_return"]) if worst.get("daily_return") is not None else 0.0,
        "date": worst.get("date", today),
    }


# -------------------- PROMPT --------------------

def _build_prompt(
    risk_metrics: dict,
    holdings: list[dict],
    macro: dict[str, float | None],
    worst_performer: dict | None,
) -> str:
    holdings_str = ", ".join(
        f"{h['ticker']} ({float(h['weight']):.1%})" for h in holdings
    ) if holdings else "N/A"

    anomaly_flag = "YES" if risk_metrics.get("anomaly_flag") else "NO"
    anomaly_type = risk_metrics.get("anomaly_type") or "N/A"

    worst_str = "N/A"
    if worst_performer:
        ret = worst_performer.get("daily_return", 0.0)
        worst_str = f"{worst_performer.get('ticker', 'N/A')} ({ret:+.2%})"

    def _fmt(val: Any, suffix: str = "") -> str:
        return f"{val}{suffix}" if val is not None else "N/A"

    return (
        "Write a 3-sentence daily portfolio summary for a reader who is smart but has never studied finance "
        "and does not know terms like Beta, Sharpe Ratio, or Value at Risk. "
        "Rules: "
        "Sentence 1 is the headline — state whether the portfolio is up or down overall and whether risk is currently high or low. "
        "Every number must be immediately followed by its meaning in plain everyday words; never leave a number unexplained. "
        "One sentence must name the single biggest risk in terms anyone can understand. "
        "Never use these words — give the plain meaning instead: Beta, Sharpe Ratio, Sharpe, VaR, Value at Risk, risk-adjusted, basis points. "
        "No bullet points, no greeting, no sign-off, no preamble, no markdown. "
        "Translation examples to anchor your register: "
        "Beta 1.32 → write 'moves harder than the market — when the market falls 1%, this tends to fall about 1.3%'; "
        "VaR 95% of -2.26% → write 'on a typical bad day you could lose around 2.3%; worse days happen but are rarer'; "
        "Sharpe 1.07 → write 'the returns are solid for the amount of risk taken'; "
        "tech concentration → write 'your holdings move together, so one bad day in tech hits the whole portfolio'.\n\n"
        f"Portfolio holdings: {holdings_str}\n\n"
        "Risk metrics for today:\n"
        f"- VaR (95%): {_fmt(risk_metrics.get('var_95'))}\n"
        f"- VaR (99%): {_fmt(risk_metrics.get('var_99'))}\n"
        f"- Sharpe Ratio: {_fmt(risk_metrics.get('sharpe_ratio'))}\n"
        f"- Max Drawdown: {_fmt(risk_metrics.get('max_drawdown'))}\n"
        f"- Beta vs Benchmark: {_fmt(risk_metrics.get('beta_vs_benchmark'))}\n"
        f"- Anomaly Detected: {anomaly_flag}\n"
        f"- Anomaly Score: {_fmt(risk_metrics.get('anomaly_score'))}\n"
        f"- Anomaly Type: {anomaly_type}\n\n"
        f"Worst performing asset today: {worst_str}\n\n"
        "Macro environment:\n"
        f"- Fed Funds Rate: {_fmt(macro.get('fed_funds_rate'), '%')}\n"
        f"- CPI: {_fmt(macro.get('cpi'))}\n"
        f"- 10Y Treasury Yield: {_fmt(macro.get('treasury_yield_10y'), '%')}\n"
        f"- VIX: {_fmt(macro.get('vix'))}\n"
        f"- EUR/USD: {_fmt(macro.get('eur_usd_rate'))}\n\n"
        "Output ONLY the 3-sentence briefing in plain English. "
        "No jargon, no preamble, no sign-off, no formatting."
    )


# -------------------- WRITE --------------------

def _write_briefing(supabase, portfolio_id: int, today: str, briefing: str) -> bool:
    """UPDATE existing risk_metrics row with ai_briefing. Returns True on success."""
    existing = (
        supabase.table("risk_metrics")
        .select("portfolio_id")
        .eq("portfolio_id", portfolio_id)
        .eq("date", today)
        .execute()
    )
    if not (existing.data or []):
        logger.error(
            f"No risk_metrics row for portfolio_id={portfolio_id}, date={today}. "
            "Cannot write ai_briefing."
        )
        return False

    supabase.table("risk_metrics").update({
        "ai_briefing": briefing,
    }).eq("portfolio_id", portfolio_id).eq("date", today).execute()

    return True


# -------------------- ORCHESTRATOR --------------------

def generate_commentary(portfolio_id: int | None = None) -> dict:
    """
    Generate AI portfolio briefing and write to risk_metrics table.
    Returns: {"status": "success"|"failure"|"skipped", "briefing": str|None, "error": str|None}
    """
    try:
        keys = _load_keys()
        if not keys:
            logger.error("No Gemini API keys configured")
            return {"status": "failure", "briefing": None, "error": "no Gemini API keys configured"}

        global _keys, _combinations, _combination_cycle
        if not _keys:
            _keys = keys
            _combinations = _build_combinations(_keys)
            _combination_cycle = itertools.cycle(_combinations)

        supabase = get_supabase()
        today = utc_today().isoformat()

        if portfolio_id is None:
            response = (
                supabase.table("portfolio_configurations")
                .select("id")
                .eq("is_default", True)
                .limit(1)
                .execute()
            )
            rows = response.data or []
            if not rows:
                raise RuntimeError("No default portfolio found in portfolio_configurations")
            portfolio_id = rows[0]["id"]
            logger.info(f"Using default portfolio_id={portfolio_id}")

        risk_metrics = _load_risk_metrics(supabase, portfolio_id, today)
        if risk_metrics is None:
            return {"status": "skipped", "briefing": None, "error": "no risk metrics for today"}

        macro = _load_latest_macro(supabase)
        holdings = _load_portfolio_holdings(supabase, portfolio_id)
        worst_performer = _load_worst_performer(supabase, portfolio_id, today)

        prompt = _build_prompt(risk_metrics, holdings, macro, worst_performer)
        briefing_text = _call_gemini(prompt)

        if not briefing_text or not briefing_text.strip():
            logger.error("Received empty response from Gemini")
            return {"status": "failure", "briefing": None, "error": "empty Gemini response"}

        briefing_text = briefing_text.strip()
        logger.info(f"Generated briefing: {briefing_text}")

        success = _write_briefing(supabase, portfolio_id, today, briefing_text)
        if not success:
            return {"status": "failure", "briefing": None, "error": "no risk_metrics row to update"}

        return {"status": "success", "briefing": briefing_text, "error": None}

    except Exception as exc:
        logger.error(f"generate_commentary failed: {exc}")
        return {"status": "failure", "briefing": None, "error": str(exc)}


if __name__ == "__main__":
    result = generate_commentary()
    print(result)
