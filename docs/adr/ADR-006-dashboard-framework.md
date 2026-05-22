# ADR-006: Dashboard Framework — Streamlit
Date: 2026-03-19

## Decision
Use **Streamlit** as the sole frontend framework for the Finthyra dashboard. The dashboard is a read-only, single-page application deployed on Streamlit Community Cloud. It queries Supabase via the `anon` key (RLS-enforced) and contains no pipeline logic.

## Context
The dashboard must surface 7 panels of financial data — AI briefing, risk metrics, price charts, portfolio holdings, correlation heatmap, macro indicators, and risk trends — to non-technical users without requiring any local setup. It must be deployable at zero cost, maintainable by a team of three with Python backgrounds (not frontend engineers), and serve data from Supabase with no intermediate backend service.

## Reasons

**Streamlit over traditional web frameworks**
- **Python-native:** The entire team writes Python. Streamlit components (`st.metric`, `st.plotly_chart`, `st.dataframe`) map directly to data science workflow idioms. No JavaScript, no React, no build step.
- **Zero deployment friction:** Streamlit Community Cloud deploys directly from a GitHub repository. A `requirements.txt` and `app.py` are sufficient. No Dockerfile, no reverse proxy, no server provisioning.
- **Plotly integration:** `st.plotly_chart()` renders interactive Plotly figures (line charts, heatmaps, pie charts) with hover, zoom, and pan — meeting the dashboard's interactivity requirements out of the box.
- **`st.cache_resource` for connection pooling:** The Supabase client is instantiated once per deployment via `@st.cache_resource`, not once per request. This avoids connection exhaustion on the Supabase free tier.
- **Sidebar multiselect for asset filtering:** `st.sidebar.multiselect()` provides asset selection with no custom state management. The selected tickers drive which assets are queried in Panel 3 (price charts).
- **Graceful error handling:** Every panel is wrapped in `try/except`. A Supabase connection error surfaces as `st.error()` + `st.stop()` rather than an unhandled exception. Empty query results show `st.info()` with a human-readable message.

**Read-only constraint**
The dashboard issues no `INSERT`, `UPDATE`, or `DELETE` statements. All writes (prices, macro indicators, risk metrics, AI briefings) are performed exclusively by the pipeline running in GitHub Actions under the `service_role` key. The dashboard uses the `anon` key, which is governed by RLS policies that grant `SELECT` only. This separation prevents any dashboard interaction from corrupting pipeline-managed data.

**Supabase REST API (no direct PostgreSQL connection)**
The Supabase Python client (`supabase-py`) queries data via Supabase's auto-generated REST API (PostgREST), not via a direct `psycopg2` connection. This means:
- No connection string with a PostgreSQL port exposed in environment variables.
- PostgREST enforces RLS automatically — the `anon` key cannot bypass row-level policies regardless of query construction.
- The Streamlit Community Cloud runner does not need network access to a PostgreSQL port; only HTTPS to the Supabase project URL.

**Alternatives considered:**
- **Dash (Plotly):** Python-native, more flexible than Streamlit for custom layouts and multi-page apps. However, Dash requires callback registration for interactivity — significantly more boilerplate for panels that simply read from a database and render a chart. Streamlit's top-to-bottom execution model is simpler for this use case.
- **Grafana:** Purpose-built for time-series dashboards with native PostgreSQL and Supabase support. Rejected because: (1) the AI briefing panel (free-text LLM output) does not fit Grafana's metric-oriented panel model; (2) Grafana Cloud's free tier requires a separate account and infrastructure setup; (3) custom plugin development would be needed for the holdings pie chart.
- **React + FastAPI backend:** Maximum flexibility and performance. Requires a running FastAPI server (additional infrastructure), frontend build tooling, and JavaScript expertise the team does not have. Overengineered for a read-only daily-refresh dashboard.
- **Retool / Metabase:** No-code dashboard tools with Supabase connectors. Rejected because: (1) the AI briefing panel requires custom rendering logic (markdown display, conditional anomaly warning); (2) vendor lock-in for dashboard layout; (3) self-hosting adds infrastructure cost.
- **Jupyter Notebook (Voilà):** Familiar to data scientists, but Voilà deployments are stateful and do not handle concurrent users cleanly. Streamlit's stateless execution model is more robust for a shared-access dashboard.

## Tradeoffs
- **Full re-render on interaction:** Streamlit re-runs the entire `app.py` script on every user interaction (sidebar multiselect change, etc.). For 7 panels with 10+ Supabase queries, this can produce noticeable latency (~2–5s). Mitigation: `@st.cache_resource` for the Supabase client; Supabase queries use `.limit()` to bound response size; price history is capped at 252 days per asset.
- **Single-page only:** The 7-panel layout is a single scrollable page. Navigation between views requires scrolling. A multi-page Streamlit app (`st.Page`) was considered but rejected at this stage — the current panel count is manageable on one page.
- **No user authentication:** The dashboard is publicly accessible. All data is readable by anyone with the URL. This is acceptable because the portfolio data is a demo/university project, not real personal financial data. If real user portfolios are added, Streamlit's native auth or a Supabase Auth integration would be required.
- **Streamlit Community Cloud uptime:** The free tier may sleep inactive apps after 7 days without a visitor. The daily pipeline run does not wake the app. A paid Streamlit plan or a scheduled uptime ping would address this.

## Status
Accepted
