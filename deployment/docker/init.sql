-- PROJECT TITAN-X Database Initialization
-- Author: Shantanu Waykar

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Market Data
CREATE TABLE IF NOT EXISTS ohlcv (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(18,6) NOT NULL,
    high DECIMAL(18,6) NOT NULL,
    low DECIMAL(18,6) NOT NULL,
    close DECIMAL(18,6) NOT NULL,
    volume BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, timeframe, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_ts ON ohlcv(symbol, timeframe, timestamp DESC);

-- Trader Knowledge
CREATE TABLE IF NOT EXISTS trader_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL,
    biography TEXT,
    philosophy JSONB DEFAULT '{}',
    frameworks JSONB DEFAULT '{}',
    success_patterns JSONB DEFAULT '{}',
    failure_patterns JSONB DEFAULT '{}',
    regime_suitability JSONB DEFAULT '{}',
    embedding_id VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strategies
CREATE TABLE IF NOT EXISTS strategies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    description TEXT,
    parameters JSONB DEFAULT '{}',
    best_regime VARCHAR(50),
    worst_regime VARCHAR(50),
    status VARCHAR(20) DEFAULT 'research',
    sharpe_backtest DECIMAL(6,3),
    sharpe_live DECIMAL(6,3),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, version)
);

-- Signals
CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    strategy_id INT REFERENCES strategies(id),
    asset VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entry_price DECIMAL(18,6),
    stop_loss DECIMAL(18,6),
    take_profit_1 DECIMAL(18,6),
    take_profit_2 DECIMAL(18,6),
    risk_percent DECIMAL(5,2),
    confidence_score INT,
    expected_value DECIMAL(6,3),
    regime VARCHAR(50),
    evidence JSONB DEFAULT '[]',
    invalidation TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trades
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT REFERENCES signals(id),
    symbol VARCHAR(20),
    direction VARCHAR(10),
    strategy_name VARCHAR(64) DEFAULT 'unspecified',
    confidence_at_entry INT,
    session_tag VARCHAR(32),
    notes TEXT,
    entry_price DECIMAL(18,6),
    exit_price DECIMAL(18,6),
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ,
    pnl_r DECIMAL(8,4),
    pnl_percent DECIMAL(8,4),
    regime_at_entry VARCHAR(50),
    execution_cost DECIMAL(8,4),
    attribution JSONB DEFAULT '{}',
    lessons JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Macro Regime
CREATE TABLE IF NOT EXISTS macro_regimes (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    regime VARCHAR(50) NOT NULL,
    risk_on_off DECIMAL(3,2),
    liquidity_score DECIMAL(3,2),
    currency_strength JSONB DEFAULT '{}',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Research Hypotheses
CREATE TABLE IF NOT EXISTS alpha_hypotheses (
    id SERIAL PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'idea',
    sharpe_result DECIMAL(6,3),
    win_rate DECIMAL(5,4),
    test_results JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    validated_at TIMESTAMPTZ
);

-- Risk Events (CRO audit log)
CREATE TABLE IF NOT EXISTS risk_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    veto_applied BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Audit Log
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    action VARCHAR(100) NOT NULL,
    resource VARCHAR(100),
    details JSONB DEFAULT '{}',
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
