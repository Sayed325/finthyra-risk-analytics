# 📊 Finthyra — Financial Intelligence Platform

> Portfolio risk analysis that costs $24,000/year on Bloomberg Terminal — built on open data, modern data engineering, and AI. Free. Always live.

## What It Does

You open the dashboard. It shows your portfolio, today's risk metrics, and a 3-sentence AI briefing:

> *"Your portfolio VaR at 95% confidence is -1.63%, indicating moderate daily risk. The Sharpe ratio of 1.36 suggests returns are adequately compensating for volatility, though NVDA's -2.1% daily drop warrants attention. With the Fed Funds Rate steady at 5.33% and VIX at 18.4, macro conditions remain stable but watch for rate decision impacts on tech-heavy positions."*

No finance degree needed. No Bloomberg subscription. No manual work.

## Architecture

```
Data Sources (yfinance, FRED API)
    → Ingestion Pipeline (Python, GitHub Actions cron)
        → Storage (Supabase PostgreSQL, EU)
            → Risk Metrics (VaR, Sharpe, Drawdown, Beta)
                → ML Anomaly Detection (XGBoost, walk-forward)
                    → AI Commentary (Gemini 2.5, key rotation)
                        → Dashboard (Streamlit, live)
```

Six-layer pipeline. Each layer has a single responsibility. The AI reads computed metrics — never raw data.

## Risk Metrics

| Metric | What It Tells You |
|---|---|
| **Value at Risk (95%, 99%)** | "On a bad day, I could lose X%" |
| **Sharpe Ratio** | Return per unit of risk — are you being compensated? |
| **Max Drawdown** | Worst peak-to-trough loss in the period |
| **Beta vs S&P 500** | How much your portfolio moves with the market |
| **Correlation Matrix** | Are your assets actually diversified? |

## Anomaly Detection

XGBoost classifier trained on pseudo-labelled historical data using walk-forward backtesting. Flags:
- Abnormal volatility (>95th percentile)
- Extreme return z-scores (|z| > 2.5)
- Accelerating drawdowns (>10% and worsening)
- Volume spikes (z > 3.0)

## AI Briefing

Gemini 2.5 Flash reads the computed risk metrics, anomaly flags, and macro context — then writes a 3-sentence portfolio briefing in plain English. Round-robin rotation across 5 API keys × 2 models for resilience.

## Tech Stack

| Layer | Technology |
|---|---|
| Data Sources | yfinance, FRED API |
| Ingestion | Python ETL, incremental fetch, retry logic |
| Storage | Supabase PostgreSQL (EU, RLS enabled) |
| Risk Engine | pandas, numpy — VaR, Sharpe, Drawdown, Beta, Correlation |
| ML | XGBoost (anomaly detection), scikit-learn |
| AI | Gemini 2.5 Flash + Flash Lite (google-genai SDK) |
| Dashboard | Streamlit, Plotly |
| CI/CD | GitHub Actions (weekday cron), automated pipeline |
| Tests | pytest (158 tests, fully mocked) |

## Dashboard Panels

1. **AI Briefing** — Gemini-generated 3-sentence portfolio briefing
2. **Risk Metrics** — VaR, Sharpe, Drawdown, Beta metric cards
3. **Price Charts** — Normalized multi-asset overlay + daily returns
4. **Portfolio Holdings** — Allocation table + pie chart
5. **Correlation Heatmap** — Asset diversification check
6. **Macro Environment** — Fed Funds, CPI, Treasury Yield, VIX, EUR/USD
7. **Risk Trends** — VaR and Sharpe over the last 90 days

## Pipeline

Runs automatically every weekday at 14:00 UTC via GitHub Actions:

```
fetch_market_data → fetch_macro_data → fetch_vix → validate_data
    → compute_risk_metrics → run_anomaly_detection → generate_commentary
```

## Project Structure

```
finthyra/
├── app.py                          # Streamlit dashboard (7 panels)
├── pipeline/daily_pipeline.py      # Pipeline orchestrator
├── src/
│   ├── ingestion/                  # Data fetching + validation
│   ├── processing/                 # Risk metrics + feature engineering
│   ├── models/                     # XGBoost anomaly detection
│   └── ai_analyst/                 # Gemini commentary generation
├── tests/                          # 158 tests (fully mocked)
├── db/migrations/                  # SQL schema + RLS policies
├── docs/adr/                       # Architecture Decision Records
└── .github/workflows/              # GitHub Actions cron pipeline
```

## Setup

```bash
# Clone
git clone https://github.com/Sayed325/finthyra.git
cd finthyra

# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_SECRET_KEY, FRED_API_KEY, GEMINI_KEY_1..5

# Backfill historical data (one-time)
python scripts/historical_backfill.py

# Run pipeline
python pipeline/daily_pipeline.py

# Launch dashboard
streamlit run app.py
```

## Architecture Decision Records

- [ADR-001: Database Choice — Supabase PostgreSQL](docs/adr/ADR-001-database-choice.md)

## Team

| Person | Role |
|---|---|
| **Sayed Hossen** | Project lead — architecture, pipeline, risk metrics, ML, AI layer, test suite |
| **Shoumik** | Project structure, ingestion pipeline, daily orchestrator |
| **Faisal** | ML engineering |

## License

University project — HAW Hamburg, Information Engineering. Supervised by Prof. Ulrike Herster.

---

*Built with data from Yahoo Finance and the Federal Reserve Economic Data (FRED) API.*
