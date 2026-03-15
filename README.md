# Finthyra

> **Under active development**

A financial intelligence platform that ingests market and macro data, computes risk metrics, runs ML-based anomaly detection, and delivers AI-generated daily briefings via a Streamlit dashboard.

## Architecture Overview

```
src/ingestion/      — pulls OHLCV, macro (FRED), and VIX data; validates on ingest
src/processing/     — feature engineering, risk metrics (VaR, Sharpe, drawdown), portfolio optimization
src/models/         — XGBoost risk/anomaly flagging, Prophet trend forecasting
src/ai_analyst/     — Gemini API commentary with round-robin key rotation
src/dashboard/      — Streamlit app wiring everything together
pipeline/           — daily orchestrator that calls the above in sequence
scripts/            — one-off utilities (historical backfill)
tests/              — pytest unit tests
.github/workflows/  — GitHub Actions for scheduled daily runs (Mon–Fri, 2pm UTC)
```

Data is persisted in Supabase (Postgres). The pipeline runs automatically on a cron schedule after US market open, covering the EU close window.

## Setup

```bash
git clone <repo-url>
cd finthyra

cp .env.example .env
# fill in your keys in .env

pip install -r requirements.txt
```

Run the dashboard locally:

```bash
streamlit run src/dashboard/app.py
```

Run the pipeline manually:

```bash
python pipeline/daily_pipeline.py
```

Run tests:

```bash
pytest
```

## Team

- Sayed — lead / architecture
- Faisal — ML models
- Shoumik — dashboard & docs
