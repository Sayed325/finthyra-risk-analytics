-- ============================================================
-- Finthyra — RLS policies for dashboard read access
-- Allows anon key to read portfolio and risk data (read-only)
-- ============================================================

CREATE POLICY "Public read access on portfolio_configurations"
    ON portfolio_configurations FOR SELECT USING (true);

CREATE POLICY "Public read access on portfolio_holdings"
    ON portfolio_holdings FOR SELECT USING (true);

CREATE POLICY "Public read access on risk_metrics"
    ON risk_metrics FOR SELECT USING (true);
