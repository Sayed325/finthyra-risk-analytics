"""Finthyra Dashboard — full 7-panel Streamlit implementation."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, UTC

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="Finthyra", layout="wide")
st.markdown(
    """<style>
  header[data-testid="stHeader"] { background: transparent !important; border: none !important; }
  div.block-container { padding-top: 0 !important; }
  section[data-testid="stSidebar"] > div { padding-top: 1rem; }
</style>""",
    unsafe_allow_html=True,
)

_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="90" viewBox="0 0 260 80">
  <defs>
    <linearGradient id="fog" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0D9488"/><stop offset="100%" stop-color="#1E3A5F"/>
    </linearGradient>
    <linearGradient id="fig" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#5EEAD4"/><stop offset="100%" stop-color="#0D9488"/>
    </linearGradient>
  </defs>
  <polygon points="40,8 67.7,24 67.7,56 40,72 12.3,56 12.3,24" fill="url(#fog)"/>
  <polygon points="40,18.6 58.5,29.3 58.5,50.7 40,61.4 21.5,50.7 21.5,29.3" fill="none" stroke="url(#fig)" stroke-width="1.8"/>
  <line x1="40" y1="18.6" x2="40" y2="8" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="58.5" y1="29.3" x2="67.7" y2="24" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="58.5" y1="50.7" x2="67.7" y2="56" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="40" y1="61.4" x2="40" y2="72" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="21.5" y1="50.7" x2="12.3" y2="56" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="21.5" y1="29.3" x2="12.3" y2="24" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <circle cx="40" cy="40" r="4.5" fill="#5EEAD4"/>
  <text x="88" y="39" font-family="Trebuchet MS,Segoe UI,sans-serif" font-size="28" font-weight="700" fill="#FFFFFF" letter-spacing="-0.5">Finthyra</text>
  <text x="89" y="57" font-family="Trebuchet MS,Segoe UI,sans-serif" font-size="10" font-weight="600" fill="#5EEAD4" letter-spacing="3">RISK &#xB7; ANALYTICS &#xB7; AI</text>
</svg>"""

_LOGO_SVG_SMALL = """<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="52" viewBox="0 0 260 80">
  <defs>
    <linearGradient id="fog2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0D9488"/><stop offset="100%" stop-color="#1E3A5F"/>
    </linearGradient>
    <linearGradient id="fig2" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#5EEAD4"/><stop offset="100%" stop-color="#0D9488"/>
    </linearGradient>
  </defs>
  <polygon points="40,8 67.7,24 67.7,56 40,72 12.3,56 12.3,24" fill="url(#fog2)"/>
  <polygon points="40,18.6 58.5,29.3 58.5,50.7 40,61.4 21.5,50.7 21.5,29.3" fill="none" stroke="url(#fig2)" stroke-width="1.8"/>
  <line x1="40" y1="18.6" x2="40" y2="8" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="58.5" y1="29.3" x2="67.7" y2="24" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="58.5" y1="50.7" x2="67.7" y2="56" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="40" y1="61.4" x2="40" y2="72" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="21.5" y1="50.7" x2="12.3" y2="56" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <line x1="21.5" y1="29.3" x2="12.3" y2="24" stroke="#5EEAD4" stroke-width="1.8" stroke-linecap="round"/>
  <circle cx="40" cy="40" r="4.5" fill="#5EEAD4"/>
  <text x="88" y="39" font-family="Trebuchet MS,Segoe UI,sans-serif" font-size="28" font-weight="700" fill="#FFFFFF" letter-spacing="-0.5">Finthyra</text>
  <text x="89" y="57" font-family="Trebuchet MS,Segoe UI,sans-serif" font-size="10" font-weight="600" fill="#5EEAD4" letter-spacing="3">RISK &#xB7; ANALYTICS &#xB7; AI</text>
</svg>"""

_today = datetime.now(UTC).strftime("%a %d %b %Y")
st.markdown(
    f"""
<div style="background:#0A1628;padding:20px 32px;border-bottom:2px solid #0D9488;
  border-radius:0 0 10px 10px;display:flex;justify-content:space-between;
  align-items:center;margin-bottom:20px">
  <div style="width:320px">{_LOGO_SVG}</div>
  <div style="text-align:right">
    <div style="font-size:12px;color:#94A3B8;font-family:monospace">{_today}</div>
    <div style="font-size:11px;color:#5EEAD4;margin-top:4px">&#x25CF; Live</div>
  </div>
</div>
<p style="color:#64748B;font-size:12px;font-style:italic;padding-left:4px;
  margin-top:-12px;margin-bottom:24px">
  Portfolio risk analysis powered by open data, modern data engineering, and AI.
</p>
""",
    unsafe_allow_html=True,
)

# ── DB CONNECTION ─────────────────────────────────────────────────────────────


@st.cache_resource
def get_dashboard_supabase():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get(
        "SUPABASE_PUBLISHABLE_KEY", os.environ.get("SUPABASE_SECRET_KEY")
    )
    return create_client(url, key)


try:
    supabase = get_dashboard_supabase()
except Exception:
    st.error(
        "Could not connect to database. Check SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY."
    )
    st.stop()

# ── DEFAULT PORTFOLIO ─────────────────────────────────────────────────────────

portfolio_id: int | None = None
try:
    p_resp = (
        supabase.table("portfolio_configurations")
        .select("id")
        .eq("is_default", True)
        .limit(1)
        .execute()
    )
    p_rows = p_resp.data or []
    if p_rows:
        portfolio_id = p_rows[0]["id"]
except Exception:
    pass

# ── LOAD ACTIVE ASSETS ────────────────────────────────────────────────────────

all_assets: list[dict] = []
ticker_to_id: dict[str, int] = {}
active_tickers: list[str] = []

try:
    a_resp = (
        supabase.table("assets")
        .select("id,ticker,name,is_benchmark,is_active")
        .eq("is_active", True)
        .execute()
    )
    all_assets = a_resp.data or []
    ticker_to_id = {a["ticker"]: a["id"] for a in all_assets}
    active_tickers = [
        a["ticker"] for a in all_assets if not a.get("is_benchmark", False)
    ]
except Exception:
    pass

# ── SIDEBAR ───────────────────────────────────────────────────────────────────

st.sidebar.markdown(
    f'<div style="padding:4px 0 12px">{_LOGO_SVG_SMALL}</div>'
    '<hr style="border:none;border-top:1px solid #0D9488;margin:0 0 12px"/>',
    unsafe_allow_html=True,
)
st.sidebar.header("Controls")


def _reset_assets():
    st.session_state["asset_select"] = active_tickers


if active_tickers:
    if "asset_select" not in st.session_state:
        st.session_state["asset_select"] = active_tickers
    selected_tickers: list[str] = st.sidebar.multiselect(
        "Select Assets",
        options=active_tickers,
        key="asset_select",
    )
    st.sidebar.button(
        "Reset selection", use_container_width=True, on_click=_reset_assets
    )
else:
    selected_tickers = []

st.sidebar.markdown("---")
st.sidebar.subheader("Data Info")
try:
    last_resp = (
        supabase.table("prices")
        .select("date")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    last_rows = last_resp.data or []
    last_run = last_rows[0]["date"] if last_rows else "N/A"

    count_resp = supabase.table("prices").select("id", count="exact").limit(1).execute()
    total_price_rows = count_resp.count if count_resp.count is not None else "N/A"

    st.sidebar.write(f"Last pipeline run: **{last_run}**")
    st.sidebar.write(f"Active assets: **{len(all_assets)}**")
    st.sidebar.write(f"Total price rows: **{total_price_rows}**")
except Exception:
    st.sidebar.write("Data info unavailable.")

# ── PRE-LOAD LATEST RISK METRICS ROW (panels 1 + 2) ──────────────────────────

risk_latest: dict | None = None
if portfolio_id is not None:
    try:
        rm_resp = (
            supabase.table("risk_metrics")
            .select("*")
            .eq("portfolio_id", portfolio_id)
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        rm_rows = rm_resp.data or []
        if rm_rows:
            risk_latest = rm_rows[0]
    except Exception:
        pass

# ════════════════════════════════════════════════════════════════════════════
# PANEL 1 — AI BRIEFING
# ════════════════════════════════════════════════════════════════════════════

st.subheader("🤖 AI Portfolio Briefing")

if portfolio_id is None:
    st.info("No default portfolio configured.")
elif risk_latest is None:
    st.info("AI briefing not yet generated. Run the daily pipeline to generate.")
else:
    briefing_date = risk_latest.get("date", "")
    ai_briefing = risk_latest.get("ai_briefing")

    if ai_briefing:
        st.info(f"**🤖 AI Portfolio Briefing — {briefing_date}**\n\n{ai_briefing}")
    else:
        st.info("AI briefing not yet generated. Run the daily pipeline to generate.")

    if risk_latest.get("anomaly_flag"):
        anomaly_type = risk_latest.get("anomaly_type") or "Unknown"
        anomaly_score = risk_latest.get("anomaly_score") or 0.0
        st.warning(
            f"⚠️ Anomaly detected: {anomaly_type} (score: {float(anomaly_score):.2f})"
        )

# ════════════════════════════════════════════════════════════════════════════
# PANEL 2 — RISK METRICS SUMMARY
# ════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📊 Risk Metrics Summary")

if risk_latest is None:
    st.info("Risk metrics not yet computed. Run the daily pipeline.")
else:
    var_95 = risk_latest.get("var_95")
    var_99 = risk_latest.get("var_99")
    sharpe = risk_latest.get("sharpe_ratio")
    max_dd = risk_latest.get("max_drawdown")
    beta = risk_latest.get("beta_vs_benchmark")

    cols = st.columns(5)
    cols[0].metric("VaR (95%)", f"{float(var_95):.2%}" if var_95 is not None else "N/A")
    cols[1].metric("VaR (99%)", f"{float(var_99):.2%}" if var_99 is not None else "N/A")
    cols[2].metric(
        "Sharpe Ratio", f"{float(sharpe):.2f}" if sharpe is not None else "N/A"
    )
    cols[3].metric(
        "Max Drawdown", f"{float(max_dd):.2%}" if max_dd is not None else "N/A"
    )
    cols[4].metric("Beta", f"{float(beta):.2f}" if beta is not None else "N/A")

# ════════════════════════════════════════════════════════════════════════════
# PANEL 3 — PRICE CHARTS
# ════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📈 Price Charts")

if not selected_tickers:
    st.info("Select at least one asset from the sidebar.")
else:
    try:
        price_frames: list[pd.DataFrame] = []
        for ticker in selected_tickers:
            asset_id = ticker_to_id.get(ticker)
            if asset_id is None:
                continue
            pr_resp = (
                supabase.table("prices")
                .select("date,close,daily_return")
                .eq("asset_id", asset_id)
                .order("date", desc=True)
                .limit(252)
                .execute()
            )
            rows = pr_resp.data or []
            if not rows:
                continue
            df_t = pd.DataFrame(rows)
            df_t["date"] = pd.to_datetime(df_t["date"])
            df_t = df_t.sort_values("date").reset_index(drop=True)
            df_t["ticker"] = ticker
            price_frames.append(df_t)

        if price_frames:
            norm_frames: list[pd.DataFrame] = []
            for df_t in price_frames:
                df_n = df_t.copy()
                first_close = float(df_n["close"].iloc[0])
                df_n["normalized_close"] = (
                    df_n["close"].astype(float) / first_close * 100
                    if first_close != 0
                    else df_n["close"].astype(float)
                )
                norm_frames.append(df_n)

            combined = pd.concat(norm_frames, ignore_index=True)

            if not combined.empty:
                fig_price = px.line(
                    combined,
                    x="date",
                    y="normalized_close",
                    color="ticker",
                    title="Price Performance (Normalized)",
                    labels={
                        "normalized_close": "Normalized Price (100 = start)",
                        "date": "Date",
                    },
                )
                st.plotly_chart(fig_price, use_container_width=True)

                returns_df = combined.dropna(subset=["daily_return"])
                if not returns_df.empty:
                    fig_ret = px.line(
                        returns_df,
                        x="date",
                        y="daily_return",
                        color="ticker",
                        title="Daily Returns",
                        labels={"daily_return": "Daily Return", "date": "Date"},
                    )
                    st.plotly_chart(fig_ret, use_container_width=True)
        else:
            st.info("No price data available for selected assets.")

    except Exception:
        st.info("No data available for Price Charts.")

# ════════════════════════════════════════════════════════════════════════════
# PANEL 4 — PORTFOLIO HOLDINGS
# ════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🏦 Portfolio Holdings")

if portfolio_id is None:
    st.info("No default portfolio configured.")
else:
    try:
        h_resp = (
            supabase.table("portfolio_holdings")
            .select("asset_id,weight")
            .eq("portfolio_id", portfolio_id)
            .execute()
        )
        h_rows = h_resp.data or []

        if not h_rows:
            st.info("No data available for Portfolio Holdings.")
        else:
            h_asset_ids = [h["asset_id"] for h in h_rows]
            ha_resp = (
                supabase.table("assets")
                .select("id,ticker,name")
                .in_("id", h_asset_ids)
                .execute()
            )
            asset_info = {a["id"]: a for a in (ha_resp.data or [])}

            holdings_data = []
            for h in h_rows:
                asset = asset_info.get(h["asset_id"], {})
                holdings_data.append(
                    {
                        "Ticker": asset.get("ticker", "UNKNOWN"),
                        "Name": asset.get("name", "Unknown"),
                        "Weight": f"{float(h['weight']):.1%}",
                        "_weight": float(h["weight"]),
                    }
                )

            holdings_df = pd.DataFrame(holdings_data)
            if not holdings_df.empty:
                col_tbl, col_pie = st.columns(2)
                with col_tbl:
                    st.dataframe(
                        holdings_df[["Ticker", "Name", "Weight"]],
                        use_container_width=True,
                    )
                with col_pie:
                    fig_pie = px.pie(
                        holdings_df,
                        names="Ticker",
                        values="_weight",
                        title="Portfolio Allocation",
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)

    except Exception:
        st.info("No data available for Portfolio Holdings.")

# ════════════════════════════════════════════════════════════════════════════
# PANEL 5 — CORRELATION HEATMAP
# ════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🔗 Asset Correlation Matrix")

try:
    corr_frames: list[pd.DataFrame] = []
    for asset in all_assets:
        if asset.get("is_benchmark"):
            continue
        cr_resp = (
            supabase.table("prices")
            .select("date,daily_return")
            .eq("asset_id", asset["id"])
            .order("date", desc=True)
            .limit(252)
            .execute()
        )
        rows = cr_resp.data or []
        if not rows:
            continue
        df_c = pd.DataFrame(rows)
        df_c["date"] = pd.to_datetime(df_c["date"])
        df_c = df_c.sort_values("date").set_index("date")
        df_c = df_c.rename(columns={"daily_return": asset["ticker"]})
        corr_frames.append(df_c[[asset["ticker"]]])

    if len(corr_frames) >= 2:
        combined_returns = pd.concat(corr_frames, axis=1)
        corr_matrix = combined_returns.corr()
        if not corr_matrix.empty:
            fig_corr = px.imshow(
                corr_matrix,
                title="Asset Correlation Matrix",
                color_continuous_scale="RdBu_r",
                zmin=-1,
                zmax=1,
                text_auto=".2f",
                labels={"color": "Correlation"},
            )
            st.plotly_chart(fig_corr, use_container_width=True)
        else:
            st.info("No data available for Correlation Heatmap.")
    else:
        st.info("Not enough asset data for Correlation Heatmap.")

except Exception:
    st.info("No data available for Correlation Heatmap.")

# ════════════════════════════════════════════════════════════════════════════
# PANEL 6 — MACRO ENVIRONMENT
# ════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("🌍 Macro Environment")

_MACRO_INDICATORS = [
    "fed_funds_rate",
    "cpi",
    "treasury_yield_10y",
    "vix",
    "eur_usd_rate",
]
_MACRO_LABELS = {
    "fed_funds_rate": "Fed Funds Rate",
    "cpi": "CPI",
    "treasury_yield_10y": "10Y Treasury Yield",
    "vix": "VIX",
    "eur_usd_rate": "EUR/USD",
}

try:
    latest_macro: dict[str, dict] = {}
    for indicator in _MACRO_INDICATORS:
        mi_resp = (
            supabase.table("macro_indicators")
            .select("indicator,value,date")
            .eq("indicator", indicator)
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        mi_rows = mi_resp.data or []
        if mi_rows:
            latest_macro[indicator] = mi_rows[0]

    present = [ind for ind in _MACRO_INDICATORS if ind in latest_macro]
    if present:
        macro_cols = st.columns(len(present))
        for i, indicator in enumerate(present):
            row = latest_macro[indicator]
            val = float(row["value"])
            label = _MACRO_LABELS.get(indicator, indicator)
            if indicator in ("fed_funds_rate", "treasury_yield_10y"):
                formatted = f"{val:.2f}%"
            elif indicator == "eur_usd_rate":
                formatted = f"{val:.4f}"
            else:
                formatted = f"{val:.2f}"
            macro_cols[i].metric(label, formatted)
    else:
        st.info("No macro data available.")

    # VIX trend chart
    try:
        vix_resp = (
            supabase.table("macro_indicators")
            .select("date,value")
            .eq("indicator", "vix")
            .order("date", desc=True)
            .limit(252)
            .execute()
        )
        vix_rows = vix_resp.data or []
        if vix_rows:
            vix_df = pd.DataFrame(vix_rows)
            vix_df["date"] = pd.to_datetime(vix_df["date"])
            vix_df = vix_df.sort_values("date").reset_index(drop=True)
            vix_df["value"] = vix_df["value"].astype(float)
            if not vix_df.empty:
                fig_vix = px.line(
                    vix_df,
                    x="date",
                    y="value",
                    title="VIX — Market Volatility Index",
                    labels={"value": "VIX", "date": "Date"},
                )
                st.plotly_chart(fig_vix, use_container_width=True)
    except Exception:
        pass

except Exception:
    st.info("No data available for Macro Environment.")

# ════════════════════════════════════════════════════════════════════════════
# PANEL 7 — RISK METRICS HISTORY
# ════════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.subheader("📉 Risk Metrics Trend")

if portfolio_id is None:
    st.info("No default portfolio configured.")
else:
    try:
        ninety_days_ago = (datetime.now(UTC).date() - timedelta(days=90)).isoformat()
        rh_resp = (
            supabase.table("risk_metrics")
            .select("date,var_95,sharpe_ratio")
            .eq("portfolio_id", portfolio_id)
            .gte("date", ninety_days_ago)
            .order("date", desc=False)
            .execute()
        )
        rh_rows = rh_resp.data or []

        if len(rh_rows) > 1:
            rh_df = pd.DataFrame(rh_rows)
            rh_df["date"] = pd.to_datetime(rh_df["date"])
            rh_df["var_95"] = pd.to_numeric(rh_df["var_95"], errors="coerce")
            rh_df["sharpe_ratio"] = pd.to_numeric(
                rh_df["sharpe_ratio"], errors="coerce"
            )

            col_var, col_sharpe = st.columns(2)
            with col_var:
                fig_var = px.line(
                    rh_df,
                    x="date",
                    y="var_95",
                    title="VaR (95%) Trend",
                    labels={"var_95": "VaR (95%)", "date": "Date"},
                )
                st.plotly_chart(fig_var, use_container_width=True)
            with col_sharpe:
                fig_sharpe = px.line(
                    rh_df,
                    x="date",
                    y="sharpe_ratio",
                    title="Sharpe Ratio Trend",
                    labels={"sharpe_ratio": "Sharpe Ratio", "date": "Date"},
                )
                st.plotly_chart(fig_sharpe, use_container_width=True)
        # 0 or 1 rows → not enough history for a trend, skip silently

    except Exception:
        st.info("No data available for Risk Metrics Trend.")

# ── FOOTER ───────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption("Finthyra • Financial Intelligence Platform • Built by Sayed Hossen")
