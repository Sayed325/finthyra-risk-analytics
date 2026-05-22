# ADR-005: CI/CD and Pipeline Execution Strategy — GitHub Actions Cron
Date: 2026-03-25

## Decision
Run the daily ingestion and analytics pipeline as a **GitHub Actions workflow** triggered by a weekday cron schedule (`0 14 * * 1-5` — 14:00 UTC, Mon–Fri). Secrets are injected via GitHub repository secrets. No persistent server or container orchestration platform is used.

## Context
The pipeline (`fetch_market_data → fetch_macro_data → fetch_vix → validate_data → compute_risk_metrics → run_anomaly_detection → generate_commentary`) must run once per trading day, unattended, with zero infrastructure cost. It has no real-time requirements — 14:00 UTC is chosen because US markets open at 09:30 ET (13:30 UTC), giving 30 minutes for the morning session to establish prices before the run starts. EU markets (Xetra, LSE) close at 15:30–16:30 CET; the run captures their most recent close data from the prior day.

## Reasons

**GitHub Actions over self-hosted schedulers**
- **Zero infrastructure cost:** GitHub Actions free tier provides 2,000 minutes/month on public repositories. The pipeline completes in < 5 minutes. Monthly consumption: ~5 min × 22 trading days = 110 minutes — well within the free quota.
- **Co-located with source:** The workflow definition lives in `.github/workflows/daily_pipeline.yml` alongside the application code. Version control, code review, and deployment are unified — no separate CI configuration service to maintain.
- **Secret injection:** GitHub repository secrets are injected as environment variables at runtime (`${{ secrets.SUPABASE_SECRET_KEY }}`, etc.). No secrets touch the repository history or the runner's disk beyond the process lifetime.
- **Manual trigger:** `workflow_dispatch` enables on-demand pipeline runs without a cron wait — useful for backfill testing and debugging after code changes.
- **Matrix-free simplicity:** The pipeline has no parallelism requirements. A single job on `ubuntu-latest` with Python 3.11 is sufficient.

**14:00 UTC cron timing**
- Covers EU market close data from the prior trading day (Xetra closes 15:30 CET = 14:30 UTC in winter, 13:30 UTC in summer — the cron accommodates the summer shift).
- Runs after US market open so that any pre-market corrections to prior-day data are settled in yfinance's cache.
- Avoids the 09:00–09:30 UTC window when European markets open and data providers experience higher API load.

**Fail-safe pipeline semantics**
- `validate_data()` returns `{"status": "pass" | "warn" | "fail"}`. Only `"fail"` (sanity violations or duplicates) raises `RuntimeError` and aborts the GitHub Actions run with a non-zero exit code, triggering a GitHub notification email to the repository owner.
- `"warn"` (completeness or freshness issues, e.g., a market holiday) logs a warning and allows the pipeline to continue. This was a deliberate fix: the original implementation raised on `"warn"`, causing the pipeline to abort on every EU market holiday.
- Downstream steps (risk metrics, anomaly detection, commentary) are individually gated: each step checks whether its prerequisite returned `"success"` before executing, and returns `{"status": "skipped"}` rather than raising if the prerequisite failed.

**Alternatives considered:**
- **Airflow (self-hosted):** Production-grade DAG orchestration with dependency tracking, backfill UI, and alerting. Requires a running server (minimum ~512 MB RAM on a VPS), adding monthly infrastructure cost and ops overhead. The pipeline's single linear DAG does not justify Airflow's complexity.
- **AWS EventBridge + Lambda:** Serverless, zero idle cost. But Lambda has a 15-minute timeout (acceptable), cold start latency (not an issue for a daily job), and requires IAM policy management — adding complexity without benefit over GitHub Actions for a codebase already hosted on GitHub.
- **Prefect Cloud / Dagster Cloud:** Managed orchestration with free tiers. Additional dependency and vendor account required. GitHub Actions already provides scheduling, secret management, and run history — duplication of concerns.
- **Cron on a VPS (e.g., Hetzner CX11):** Lowest latency, full control. Costs ~€4/month, requires SSH access management, and introduces a single point of failure if the VPS is down. GitHub Actions' distributed runner infrastructure is more reliable for an unattended daily job.
- **Streamlit-triggered pipeline:** Running the pipeline on dashboard load was considered and explicitly rejected. Pipelines that modify the database should never be triggered by read-only dashboard users. The dashboard is read-only by design.

## Tradeoffs
- **GitHub Actions runner cold start:** Each run provisions a fresh `ubuntu-latest` runner and installs `requirements.txt` from scratch (~30–60s). A self-hosted runner with a warm virtualenv would be faster, but the cold start is within the acceptable window for a daily batch job.
- **No DAG visualization:** Pipeline step dependencies are encoded in Python `if/else` logic, not a visual DAG. For a 7-step linear pipeline, this is maintainable. If the pipeline branches significantly (e.g., per-asset parallel steps), migrating to a DAG framework should be reconsidered.
- **No retry on pipeline failure:** If the GitHub Actions job fails (e.g., Supabase is unreachable), no automatic retry is scheduled. The `workflow_dispatch` trigger allows manual retry, and the pipeline is idempotent — upserts on `(asset_id, date)` and `(portfolio_id, date)` prevent double-writes on retry.
- **Cron drift on GitHub:** GitHub's cron scheduler may delay runs by up to 15 minutes during high-load periods. This is acceptable for a daily batch with no hard real-time requirement.

## Status
Accepted
