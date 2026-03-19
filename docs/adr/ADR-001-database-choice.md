# ADR-001: Database Choice — Supabase PostgreSQL
Date: 2026-03-19

## Decision
Supabase (hosted PostgreSQL, free tier, EU West — Ireland, eu-west-1) as the sole persistent data store for all market data, macro indicators, portfolio configurations, and computed risk metrics.

## Context
Finthyra requires a database that supports daily time-series ingestion via automated pipelines (GitHub Actions), serves queries to a Streamlit dashboard, and remains accessible at zero cost indefinitely. The database must be reachable from both CI/CD environments and a publicly deployed frontend without infrastructure management.

## Reasons
- **Hosted PostgreSQL with zero ops:** No server provisioning, no backup configuration, no connection pooling setup. Supabase handles all of this on the free tier.
- **Row Level Security (RLS):** Native PostgreSQL RLS enables per-user portfolio isolation without application-level auth logic. The pipeline writes via `service_role` key (bypasses RLS); the dashboard reads through the public `anon` key (respects RLS policies).
- **REST API included:** Supabase auto-generates a REST API from the schema. The Streamlit dashboard can query data without a direct database connection — reducing attack surface and simplifying deployment on Streamlit Community Cloud.
- **Free tier never expires:** 500 MB storage, unlimited API requests, 2 projects. More than sufficient for daily OHLCV across 12 assets over 3+ years.
- **EU region (Ireland, eu-west-1):** Data residency within the EU. Frankfurt was preferred but region is locked at project creation. Ireland is equally GDPR-compliant and latency is negligible for a daily batch pipeline.

**Alternatives considered:**
- **SQLite (local file):** Zero cost, zero setup, but not accessible from GitHub Actions or Streamlit Cloud without file syncing hacks. No RLS. Dead end for multi-user portfolio support.
- **Neon / PlanetScale:** Viable hosted alternatives, but Supabase's built-in RLS, auto-generated REST API, and dashboard UI provide more out-of-the-box value for this project's needs.
- **Self-hosted PostgreSQL (Railway, Render):** Adds infrastructure management and cost risk. Free tiers on these platforms are less generous and have historically been deprecated.

## Tradeoffs
- **Vendor dependency:** Schema and RLS policies are standard PostgreSQL — migration to any other PostgreSQL host requires only a `pg_dump`. No Supabase-specific lock-in beyond the REST API convenience layer.
- **Free tier limits:** 500 MB storage cap. At ~12 assets × 252 trading days × 3 years, the prices table stays well under 5 MB. Risk metrics and macro data add negligible overhead. Not a concern for the project's scope.
- **No local development database:** All development queries hit the hosted instance. Acceptable for a team of three with low write contention. If this becomes an issue, the Supabase CLI can spin up a local instance.

## Status
Accepted
