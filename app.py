import streamlit as st
import pandas as pd
import plotly.express as px

from src.ingestion.common import get_supabase
from src.ingestion.data_validator import validate_data

# ---------- PAGE CONFIG ----------
st.set_page_config(
    page_title="Finthyra Dashboard",
    layout="wide"
)

st.title("📊 Finthyra Dashboard")

# ---------- LOAD DB ----------
supabase = get_supabase()

# ---------- VALIDATION ----------
validation = validate_data()

if validation["status"] == "fail":
    st.error("❌ Data quality issues detected")
elif validation["status"] == "warn":
    st.warning("⚠ Data has minor issues")
else:
    st.success("✅ Data is clean")

# ---------- FETCH ASSETS ----------
assets = (
    supabase.table("assets")
    .select("id,ticker")
    .eq("is_active", True)
    .execute()
    .data
)

asset_map = {a["ticker"]: a["id"] for a in assets}
tickers = list(asset_map.keys())

# ---------- ASSET SELECTOR ----------
st.sidebar.header("📌 Controls")
selected_ticker = st.sidebar.selectbox("Select Asset", tickers)

asset_id = asset_map[selected_ticker]

# ---------- FETCH PRICE DATA ----------
prices = (
    supabase.table("prices")
    .select("date,close,daily_return")
    .eq("asset_id", asset_id)
    .order("date", desc=False)
    .execute()
    .data
)

# ---------- PRICE DATAFRAME ----------
st.subheader(f"📈 Price Chart — {selected_ticker}")

if prices:
    df = pd.DataFrame(prices)
    df["date"] = pd.to_datetime(df["date"])

    # ---------- KPI CARDS ----------
    latest_price = df["close"].iloc[-1]
    latest_return = df["daily_return"].iloc[-1]

    col1, col2 = st.columns(2)
    col1.metric("Latest Price", round(latest_price, 2))
    col2.metric("Daily Return", f"{round(latest_return * 100, 2)}%")

    # ---------- PLOTLY CHART ----------
    fig = px.line(df, x="date", y="close", title=f"{selected_ticker} Price")
    st.plotly_chart(fig, use_container_width=True)

    # ---------- TABLE ----------
    with st.expander("Show Raw Data"):
        st.dataframe(df.tail(20))

else:
    st.warning("No price data available")

# ---------- MACRO DATA ----------
st.subheader("🌍 Macro Indicators")

macro = (
    supabase.table("macro_indicators")
    .select("indicator,value,date")
    .order("date", desc=True)
    .execute()
    .data
)

latest_macro = {}
for row in macro:
    if row["indicator"] not in latest_macro:
        latest_macro[row["indicator"]] = row

# ---------- KPI CARDS FOR MACRO ----------
cols = st.columns(len(latest_macro))

for i, (k, v) in enumerate(latest_macro.items()):
    cols[i].metric(
        label=k.upper(),
        value=round(v["value"], 2),
        delta=f"Date: {v['date']}"
    )

# ---------- STATIC KPI EXAMPLE ----------
st.subheader("📊 Portfolio Metrics (Demo)")

col1, col2 = st.columns(2)
col1.metric("VIX (Example)", 18.4)
col2.metric("Sharpe Ratio (Example)", 1.2)

# ---------- FOOTER ----------
st.markdown("---")
st.caption("Finthyra • Financial Intelligence Platform")