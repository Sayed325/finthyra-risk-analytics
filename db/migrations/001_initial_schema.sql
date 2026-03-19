-- ============================================================
-- Finthyra — Initial Database Schema
-- Migration: 001_initial_schema.sql
-- Date: 2026-03-19
-- 
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ============================================================

-- ============================================================
-- TABLE 1: assets
-- Master registry of every ticker the system tracks.
-- Single source of truth — all other tables reference this.
-- ============================================================
CREATE TABLE assets (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL UNIQUE,     -- e.g. 'AAPL', 'SIE.DE', 'SPY'
    name            VARCHAR(100) NOT NULL,            -- e.g. 'Apple Inc.'
    asset_class     VARCHAR(20) NOT NULL,             -- 'equity', 'etf'
    region          VARCHAR(20) NOT NULL,             -- 'us', 'eu'
    currency        VARCHAR(5) NOT NULL,              -- 'USD', 'EUR'
    is_benchmark    BOOLEAN DEFAULT FALSE,            -- TRUE for SPY, DAX — used in Beta calc
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE 2: prices
-- Daily OHLCV time-series. Core data table.
-- Everything downstream reads from here.
-- ============================================================
CREATE TABLE prices (
    id              BIGSERIAL PRIMARY KEY,
    asset_id        INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    open            NUMERIC(12, 4) NOT NULL,
    high            NUMERIC(12, 4) NOT NULL,
    low             NUMERIC(12, 4) NOT NULL,
    close           NUMERIC(12, 4) NOT NULL,
    volume          BIGINT,
    daily_return    NUMERIC(8, 6),                   -- pre-computed: (close - prev_close) / prev_close
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (asset_id, date)
);

CREATE INDEX idx_prices_asset_date ON prices (asset_id, date DESC);

-- ============================================================
-- TABLE 3: macro_indicators
-- Unified macro table — FRED + yfinance in one place.
-- Flat design: adding a new indicator = inserting rows, not altering schema.
-- ============================================================
CREATE TABLE macro_indicators (
    id              BIGSERIAL PRIMARY KEY,
    indicator       VARCHAR(50) NOT NULL,             -- 'fed_funds_rate', 'cpi', 'treasury_yield_10y', 'vix'
    date            DATE NOT NULL,
    value           NUMERIC(12, 4) NOT NULL,
    source          VARCHAR(20) NOT NULL,             -- 'fred', 'yfinance'
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (indicator, date)
);

CREATE INDEX idx_macro_indicator_date ON macro_indicators (indicator, date DESC);

-- ============================================================
-- TABLE 4: portfolio_configurations
-- Defines what a portfolio is.
-- Supports fixed default + user-defined from day one.
-- ============================================================
CREATE TABLE portfolio_configurations (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    user_id         VARCHAR(100),                    -- NULL for system default portfolio
    is_default      BOOLEAN DEFAULT FALSE,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TABLE 5: portfolio_holdings
-- Assets + weights inside a portfolio.
-- Separate from config because holdings can be rebalanced independently.
-- ============================================================
CREATE TABLE portfolio_holdings (
    id              SERIAL PRIMARY KEY,
    portfolio_id    INTEGER NOT NULL REFERENCES portfolio_configurations(id) ON DELETE CASCADE,
    asset_id        INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    weight          NUMERIC(5, 4) NOT NULL,           -- e.g. 0.1000 = 10%. Weights should sum to 1.0
    added_at        TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (portfolio_id, asset_id)
);

-- ============================================================
-- TABLE 6: risk_metrics
-- Daily computed output of the processing layer.
-- One row per portfolio per day. Gemini reads from here.
-- ============================================================
CREATE TABLE risk_metrics (
    id              BIGSERIAL PRIMARY KEY,
    portfolio_id    INTEGER NOT NULL REFERENCES portfolio_configurations(id) ON DELETE CASCADE,
    date            DATE NOT NULL,

    -- Core risk metrics
    var_95          NUMERIC(8, 6),                    -- Value at Risk, 95% confidence
    var_99          NUMERIC(8, 6),                    -- Value at Risk, 99% confidence
    sharpe_ratio    NUMERIC(8, 4),
    max_drawdown    NUMERIC(8, 6),
    beta_vs_benchmark NUMERIC(8, 4),                 -- vs SPY or DAX depending on portfolio region

    -- Anomaly flagging (XGBoost output)
    anomaly_flag    BOOLEAN DEFAULT FALSE,
    anomaly_score   NUMERIC(5, 4),                    -- confidence score 0.0 to 1.0
    anomaly_type    VARCHAR(50),                      -- 'volatility_spike', 'correlation_breakdown', 'drawdown_acceleration'

    -- AI commentary (Gemini output)
    ai_briefing     TEXT,

    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (portfolio_id, date)
);

CREATE INDEX idx_risk_metrics_portfolio_date ON risk_metrics (portfolio_id, date DESC);

-- ============================================================
-- ROW LEVEL SECURITY
-- Enable RLS on all tables. Pipeline uses the service_role key
-- which bypasses RLS. Dashboard/public access is restricted.
-- ============================================================

ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro_indicators ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_configurations ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_metrics ENABLE ROW LEVEL SECURITY;

-- Read-only public access for assets, prices, macro (reference data)
CREATE POLICY "Public read access on assets"
    ON assets FOR SELECT
    USING (true);

CREATE POLICY "Public read access on prices"
    ON prices FOR SELECT
    USING (true);

CREATE POLICY "Public read access on macro_indicators"
    ON macro_indicators FOR SELECT
    USING (true);

-- Portfolio configs: users see defaults + their own
CREATE POLICY "Read default and own portfolios"
    ON portfolio_configurations FOR SELECT
    USING (is_default = true OR user_id = current_setting('request.jwt.claims', true)::json ->> 'sub');

-- Portfolio holdings: readable if the parent portfolio is readable
CREATE POLICY "Read holdings for accessible portfolios"
    ON portfolio_holdings FOR SELECT
    USING (
        portfolio_id IN (
            SELECT id FROM portfolio_configurations
            WHERE is_default = true
            OR user_id = current_setting('request.jwt.claims', true)::json ->> 'sub'
        )
    );

-- Risk metrics: same logic as holdings
CREATE POLICY "Read metrics for accessible portfolios"
    ON risk_metrics FOR SELECT
    USING (
        portfolio_id IN (
            SELECT id FROM portfolio_configurations
            WHERE is_default = true
            OR user_id = current_setting('request.jwt.claims', true)::json ->> 'sub'
        )
    );

-- ============================================================
-- SEED: Default assets
-- The 12 tickers from the agreed asset universe
-- ============================================================
INSERT INTO assets (ticker, name, asset_class, region, currency, is_benchmark) VALUES
    ('AAPL',    'Apple Inc.',                   'equity', 'us', 'USD', FALSE),
    ('MSFT',    'Microsoft Corporation',        'equity', 'us', 'USD', FALSE),
    ('NVDA',    'NVIDIA Corporation',           'equity', 'us', 'USD', FALSE),
    ('AMZN',    'Amazon.com Inc.',              'equity', 'us', 'USD', FALSE),
    ('GOOGL',   'Alphabet Inc.',                'equity', 'us', 'USD', FALSE),
    ('SAP',     'SAP SE',                       'equity', 'eu', 'EUR', FALSE),
    ('SIE.DE',  'Siemens AG',                   'equity', 'eu', 'EUR', FALSE),
    ('BAS.DE',  'BASF SE',                      'equity', 'eu', 'EUR', FALSE),
    ('ALV.DE',  'Allianz SE',                   'equity', 'eu', 'EUR', FALSE),
    ('SPY',     'SPDR S&P 500 ETF Trust',       'etf',    'us', 'USD', TRUE),
    ('QQQ',     'Invesco QQQ Trust',            'etf',    'us', 'USD', FALSE),
    ('VUSA.L',  'Vanguard S&P 500 UCITS ETF',  'etf',    'eu', 'USD', FALSE);

-- ============================================================
-- SEED: Default portfolio configuration
-- ============================================================
INSERT INTO portfolio_configurations (name, user_id, is_default, description) VALUES
    ('Finthyra Default Portfolio', NULL, TRUE, 'Balanced portfolio across US large caps, EU equities, and ETFs. System default.');

-- SEED: Default portfolio holdings (equal weight across non-benchmark assets)
-- 10 holdings at 10% each = 1.0
INSERT INTO portfolio_holdings (portfolio_id, asset_id, weight)
SELECT
    (SELECT id FROM portfolio_configurations WHERE is_default = TRUE LIMIT 1),
    a.id,
    0.1000
FROM assets a
WHERE a.is_benchmark = FALSE AND a.ticker != 'VUSA.L'
ORDER BY a.id;

-- ============================================================
-- Done. Verify in Supabase Table Editor.
-- ============================================================
