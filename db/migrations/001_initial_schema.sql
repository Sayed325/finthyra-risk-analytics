-- ============================================================
-- Finthyra — Initial Database Schema (UPDATED WITH ETFs)
-- ============================================================

-- =========================
-- TABLE 1: assets
-- =========================
CREATE TABLE assets (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL UNIQUE,
    name            VARCHAR(100) NOT NULL,
    asset_class     VARCHAR(20) NOT NULL,
    region          VARCHAR(20) NOT NULL,
    currency        VARCHAR(5) NOT NULL,
    is_benchmark    BOOLEAN DEFAULT FALSE,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =========================
-- TABLE 2: prices
-- =========================
CREATE TABLE prices (
    id              BIGSERIAL PRIMARY KEY,
    asset_id        INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    date            DATE NOT NULL,
    open            NUMERIC(12, 4) NOT NULL,
    high            NUMERIC(12, 4) NOT NULL,
    low             NUMERIC(12, 4) NOT NULL,
    close           NUMERIC(12, 4) NOT NULL,
    volume          BIGINT,
    daily_return    NUMERIC(8, 6),
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (asset_id, date)
);

CREATE INDEX idx_prices_asset_date ON prices (asset_id, date DESC);

-- =========================
-- TABLE 3: macro_indicators
-- =========================
CREATE TABLE macro_indicators (
    id              BIGSERIAL PRIMARY KEY,
    indicator       VARCHAR(50) NOT NULL,
    date            DATE NOT NULL,
    value           NUMERIC(12, 4) NOT NULL,
    source          VARCHAR(20) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (indicator, date)
);

CREATE INDEX idx_macro_indicator_date ON macro_indicators (indicator, date DESC);

-- =========================
-- TABLE 4: portfolio_configurations
-- =========================
CREATE TABLE portfolio_configurations (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    user_id         VARCHAR(100),
    is_default      BOOLEAN DEFAULT FALSE,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- =========================
-- TABLE 5: portfolio_holdings
-- =========================
CREATE TABLE portfolio_holdings (
    id              SERIAL PRIMARY KEY,
    portfolio_id    INTEGER NOT NULL REFERENCES portfolio_configurations(id) ON DELETE CASCADE,
    asset_id        INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    weight          NUMERIC(5, 4) NOT NULL,
    added_at        TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (portfolio_id, asset_id)
);

-- =========================
-- TABLE 6: risk_metrics
-- =========================
CREATE TABLE risk_metrics (
    id              BIGSERIAL PRIMARY KEY,
    portfolio_id    INTEGER NOT NULL REFERENCES portfolio_configurations(id) ON DELETE CASCADE,
    date            DATE NOT NULL,

    var_95          NUMERIC(8, 6),
    var_99          NUMERIC(8, 6),
    sharpe_ratio    NUMERIC(8, 4),
    max_drawdown    NUMERIC(8, 6),
    beta_vs_benchmark NUMERIC(8, 4),

    anomaly_flag    BOOLEAN DEFAULT FALSE,
    anomaly_score   NUMERIC(5, 4),
    anomaly_type    VARCHAR(50),

    ai_briefing     TEXT,

    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (portfolio_id, date)
);

CREATE INDEX idx_risk_metrics_portfolio_date ON risk_metrics (portfolio_id, date DESC);

-- =========================
-- RLS
-- =========================
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro_indicators ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_configurations ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_metrics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read access on assets" ON assets FOR SELECT USING (true);
CREATE POLICY "Public read access on prices" ON prices FOR SELECT USING (true);
CREATE POLICY "Public read access on macro_indicators" ON macro_indicators FOR SELECT USING (true);

-- =========================
-- SEED: Assets (UPDATED)
-- =========================
INSERT INTO assets (ticker, name, asset_class, region, currency, is_benchmark) VALUES

-- US equities
('AAPL',    'Apple Inc.',                   'equity', 'us', 'USD', FALSE),
('MSFT',    'Microsoft Corporation',        'equity', 'us', 'USD', FALSE),
('NVDA',    'NVIDIA Corporation',           'equity', 'us', 'USD', FALSE),
('AMZN',    'Amazon.com Inc.',              'equity', 'us', 'USD', FALSE),
('GOOGL',   'Alphabet Inc.',                'equity', 'us', 'USD', FALSE),

-- EU equities
('SAP',     'SAP SE',                       'equity', 'eu', 'EUR', FALSE),
('SIE.DE',  'Siemens AG',                   'equity', 'eu', 'EUR', FALSE),
('BAS.DE',  'BASF SE',                      'equity', 'eu', 'EUR', FALSE),
('ALV.DE',  'Allianz SE',                   'equity', 'eu', 'EUR', FALSE),

-- Core ETFs
('SPY',     'SPDR S&P 500 ETF Trust',       'etf', 'us', 'USD', TRUE),
('QQQ',     'Invesco QQQ Trust',            'etf', 'us', 'USD', FALSE),
('VUSA.L',  'Vanguard S&P 500 UCITS ETF',   'etf', 'eu', 'USD', FALSE),

-- NEW ETFs (ADDED)
('IVV',     'iShares Core S&P 500 ETF',     'etf', 'us', 'USD', FALSE),
('VTI',     'Vanguard Total Stock Market',  'etf', 'us', 'USD', FALSE),
('VEA',     'Vanguard FTSE Developed',      'etf', 'us', 'USD', FALSE),
('EUNL.DE', 'iShares Core MSCI World',      'etf', 'eu', 'EUR', FALSE),
('IWDA.L',  'iShares MSCI World UCITS',     'etf', 'eu', 'USD', FALSE);

-- =========================
-- SEED: Portfolio
-- =========================
INSERT INTO portfolio_configurations (name, user_id, is_default, description) VALUES
('Finthyra Default Portfolio', NULL, TRUE, 'Balanced portfolio across equities and ETFs.');

-- =========================
-- SEED: Portfolio Holdings (AUTO BALANCED)
-- =========================
INSERT INTO portfolio_holdings (portfolio_id, asset_id, weight)
SELECT
    (SELECT id FROM portfolio_configurations WHERE is_default = TRUE LIMIT 1),
    a.id,
    ROUND(1.0 / COUNT(*) OVER (), 4)
FROM assets a
WHERE a.is_benchmark = FALSE;

-- ============================================================
-- DONE
-- ============================================================