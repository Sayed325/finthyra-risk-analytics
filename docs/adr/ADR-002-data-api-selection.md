# ADR-002: Market & Macro Data API Selection — yfinance + FRED
Date: 2026-03-19

## Decision
Use **yfinance** for all OHLCV equity/ETF prices and VIX, and the **FRED REST API** (via `fredapi`) for macro indicators (Fed Funds Rate, CPI, 10Y Treasury Yield, EUR/USD).

## Context
Finthyra requires daily time-series data across two distinct domains: equity market prices for 17 assets (US and EU-listed) and macro-economic indicators. The data layer runs unattended in GitHub Actions on a weekday cron. It must be free, reliable enough for a daily batch job, and require no licensing negotiation. EU-listed tickers (`.DE`, `.L` suffixes) must be supported alongside US listings.

## Reasons

**yfinance (market data + VIX)**
- **Free and anonymous:** No API key required. Rate limits are generous for a daily batch over 17 tickers.
- **Exchange coverage:** Supports NYSE, XETR (Frankfurt), and LSE — all three exchanges used by Finthyra's asset universe. Ticker suffix (`.DE`, `.L`) is sufficient for routing.
- **Bulk download:** `yf.download(tickers, group_by="ticker")` fetches all assets in one HTTP round-trip for the historical backfill, dramatically reducing runtime and risk of partial failure.
- **VIX via `^VIX`:** Fear index is available at no cost alongside equities — no separate data contract needed.
- **MultiIndex handling:** yfinance bulk format returns a MultiIndex DataFrame. Finthyra normalises this at the ingestion boundary (`df.columns.get_level_values(0)`), isolating the quirk in one place.

**FRED REST API (macro indicators)**
- **Authoritative source:** Federal Reserve Bank of St. Louis publishes DFF, CPIAUCSL, DGS10, and DEXUSEU — the primary sources institutional research teams use.
- **Free with API key:** 120,000 requests/day per key. Daily incremental fetch uses < 10 requests.
- **Structured JSON with explicit missing values:** FRED returns `"."` for unreleased data points (e.g., CPI months not yet published). Finthyra filters these at ingestion, avoiding null propagation into risk calculations.
- **CPI release cadence:** CPI is monthly. The data validator uses a 45-day calendar window (vs. 3 trading days for daily series) to avoid false-positive freshness alerts on a monthly-release indicator.

**Alternatives considered:**
- **Alpha Vantage:** Free tier is 25 requests/day — insufficient for 17 tickers in a single run without sleep loops. Premium tiers add cost.
- **Polygon.io:** High data quality and official API, but the free tier excludes real-time data and has strict rate limits. EU-listed equities require a paid plan.
- **Quandl / Nasdaq Data Link:** Macro data quality is high, but many financial datasets moved behind a paywall after the Nasdaq acquisition. FRED is a more stable free source for the 4 indicators needed.
- **ECB Data Portal (for EUR/USD):** More authoritative for EUR/USD than FRED, but requires a different client library and adds a second macro data source. FRED's DEXUSEU series is sufficiently accurate for daily risk calculations.

## Tradeoffs
- **yfinance is unofficial:** The library reverse-engineers Yahoo Finance's internal API. It has broken on Yahoo-side changes multiple times historically. Mitigation: `retry()` with 3 attempts + 5s delay wraps every download call. If yfinance breaks, the pipeline logs failures per-ticker and continues; validation then catches missing data.
- **FRED data lag:** Macro series are not real-time. DFF and DGS10 lag by 1 business day; CPI by ~2 weeks after the reference month ends. This is acceptable — Finthyra uses macro data as context for daily risk commentary, not for intraday trading signals.
- **No historical tick data:** yfinance provides OHLCV at daily granularity. Sub-daily resolution would require a paid provider. Daily granularity is sufficient for VaR, Sharpe, and drawdown calculations over 252-day windows.
- **EUR/USD from FRED:** DEXUSEU is a noon buying rate, not a mid-market rate. For portfolio risk purposes at daily granularity, this distinction is immaterial.

## Status
Accepted
