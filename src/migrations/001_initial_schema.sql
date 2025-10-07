-- ============================================================================
-- 🚀 PACIFICA BOT - INITIAL DATABASE SCHEMA
-- ============================================================================
-- Migration: 001_initial_schema.sql
-- Version: 1.0
-- Description: Creates initial database schema for Pacifica Bot trading system
-- ============================================================================

-- ============================================================================
-- CORE TRADING TABLES
-- ============================================================================

-- Trades table - stores all executed trades
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    quantity REAL NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    pnl REAL NOT NULL,
    commission REAL DEFAULT 0,
    grid_level INTEGER DEFAULT 0,
    strategy_type TEXT DEFAULT 'grid',
    session_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Performance metrics table - daily performance statistics
CREATE TABLE IF NOT EXISTS performance_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_return REAL DEFAULT 0,
    total_return_percent REAL DEFAULT 0,
    win_rate REAL DEFAULT 0,
    sharpe_ratio REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    max_drawdown_percent REAL DEFAULT 0,
    profit_factor REAL DEFAULT 1.0,
    session_duration REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, symbol)
);

-- Daily balance tracking
CREATE TABLE IF NOT EXISTS daily_balance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    initial_balance REAL DEFAULT 0,
    final_balance REAL DEFAULT 0,
    day_pnl REAL DEFAULT 0,
    day_pnl_percent REAL DEFAULT 0,
    peak_balance REAL DEFAULT 0,
    min_balance REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, symbol)
);

-- System logs for debugging and monitoring
CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    logger_name TEXT NOT NULL,
    message TEXT NOT NULL,
    symbol TEXT,
    strategy_type TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Position snapshots for risk management
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_price REAL NOT NULL,
    unrealized_pnl REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    margin_used REAL DEFAULT 0,
    timestamp TEXT NOT NULL,
    session_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timestamp)
);

-- System configuration storage
CREATE TABLE IF NOT EXISTS configuration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    data_type TEXT DEFAULT 'string',
    description TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Indexes for trades table
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_type ON trades(strategy_type);
CREATE INDEX IF NOT EXISTS idx_trades_session_id ON trades(session_id);

-- Indexes for performance metrics
CREATE INDEX IF NOT EXISTS idx_performance_symbol ON performance_metrics(symbol);
CREATE INDEX IF NOT EXISTS idx_performance_date ON performance_metrics(date);

-- Indexes for system logs
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON system_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level ON system_logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_symbol ON system_logs(symbol);

-- Indexes for positions
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_timestamp ON positions(timestamp);

-- ============================================================================
-- INITIAL CONFIGURATION DATA
-- ============================================================================

-- Insert database version
INSERT OR REPLACE INTO configuration (key, value, description)
VALUES ('database_version', '1.0', 'Current database schema version');

-- Insert default configuration values
INSERT OR REPLACE INTO configuration (key, value, description)
VALUES ('max_trades_history', '50000', 'Maximum number of trades to keep in database');

INSERT OR REPLACE INTO configuration (key, value, description)
VALUES ('log_retention_days', '30', 'Number of days to keep system logs');

INSERT OR REPLACE INTO configuration (key, value, description)
VALUES ('backup_enabled', 'true', 'Whether automatic backups are enabled');

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Daily performance summary view
CREATE VIEW IF NOT EXISTS daily_performance_summary AS
SELECT
    pm.date,
    pm.symbol,
    pm.total_trades,
    pm.winning_trades,
    pm.losing_trades,
    pm.win_rate,
    pm.total_return,
    pm.total_return_percent,
    db.initial_balance,
    db.final_balance,
    db.day_pnl,
    db.day_pnl_percent
FROM performance_metrics pm
LEFT JOIN daily_balance db ON pm.date = db.date AND pm.symbol = db.symbol;

-- Recent trades view (last 1000 trades)
CREATE VIEW IF NOT EXISTS recent_trades AS
SELECT * FROM trades
ORDER BY exit_time DESC
LIMIT 1000;

-- ============================================================================
-- TRIGGERS FOR AUTOMATIC UPDATES
-- ============================================================================

-- Update timestamp trigger for trades
CREATE TRIGGER IF NOT EXISTS update_trades_timestamp
    AFTER UPDATE ON trades
    FOR EACH ROW
BEGIN
    UPDATE trades SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Update timestamp trigger for performance metrics
CREATE TRIGGER IF NOT EXISTS update_performance_timestamp
    AFTER UPDATE ON performance_metrics
    FOR EACH ROW
BEGIN
    UPDATE performance_metrics SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- Update timestamp trigger for daily balance
CREATE TRIGGER IF NOT EXISTS update_balance_timestamp
    AFTER UPDATE ON daily_balance
    FOR EACH ROW
BEGIN
    UPDATE daily_balance SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- Update timestamp trigger for configuration
CREATE TRIGGER IF NOT EXISTS update_config_timestamp
    AFTER UPDATE ON configuration
    FOR EACH ROW
BEGIN
    UPDATE configuration SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- ============================================================================
-- MIGRATION METADATA
-- ============================================================================

-- Record this migration
INSERT OR REPLACE INTO configuration (key, value, description)
VALUES ('migration_001_applied', CURRENT_TIMESTAMP, 'Initial schema migration applied');

-- ============================================================================
-- PERFORMANCE OPTIMIZATION
-- ============================================================================

-- Analyze tables for query optimization
ANALYZE trades;
ANALYZE performance_metrics;
ANALYZE daily_balance;
ANALYZE system_logs;
ANALYZE positions;
ANALYZE configuration;

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

-- This migration creates the complete initial schema for Pacifica Bot
-- Database is now ready for trading operations!