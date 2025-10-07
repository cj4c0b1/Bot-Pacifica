"""
Database Manager - SQLite Connection and Operations
Handles database connections, migrations, and basic operations for Pacifica Bot
"""

import os
import sqlite3
import logging
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass
from contextlib import contextmanager

@dataclass
class DatabaseConfig:
    """Database configuration settings"""
    database_path: str = "data/pacifica_bot.db"
    pool_size: int = 5
    check_same_thread: bool = False
    timeout: int = 30
    auto_migrate: bool = True

class DatabaseManager:
    """SQLite database manager with connection pooling and migrations"""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.logger = logging.getLogger('PacificaBot.DatabaseManager')
        self.config = config or DatabaseConfig()

        # Connection pool
        self._connections: List[sqlite3.Connection] = []
        self._connection_count = 0

        # Initialize database path
        self.db_path = Path(self.config.database_path)
        self.db_path.parent.mkdir(exist_ok=True)

        # Initialize database
        self._initialize_database()

    def _initialize_database(self) -> None:
        """Initialize database and create tables"""
        try:
            self.logger.info(f"🗄️ Initializing database at {self.db_path}")

            # Create tables
            self._create_tables()

            # Run migrations if enabled
            if self.config.auto_migrate:
                self._run_migrations()

            self.logger.info("✅ Database initialized successfully")

        except Exception as e:
            self.logger.error(f"❌ Error initializing database: {e}")
            raise

    def _create_tables(self) -> None:
        """Create all necessary tables"""
        tables = {
            'trades': '''
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
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
                )
            ''',

            'performance_metrics': '''
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
                    UNIQUE(date, symbol)
                )
            ''',

            'daily_balance': '''
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
                    UNIQUE(date, symbol)
                )
            ''',

            'system_logs': '''
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    level TEXT NOT NULL,
                    logger_name TEXT NOT NULL,
                    message TEXT NOT NULL,
                    symbol TEXT,
                    strategy_type TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''',

            'positions': '''
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
                )
            ''',

            'configuration': '''
                CREATE TABLE IF NOT EXISTS configuration (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    data_type TEXT DEFAULT 'string',
                    description TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            '''
        }

        with self.get_connection() as conn:
            for table_name, create_sql in tables.items():
                try:
                    conn.execute(create_sql)
                    self.logger.debug(f"✅ Created/verified table: {table_name}")
                except sqlite3.Error as e:
                    self.logger.error(f"❌ Error creating table {table_name}: {e}")
                    raise

            conn.commit()

    def _run_migrations(self) -> None:
        """Run database migrations"""
        try:
            migration_dir = Path("src/migrations")
            if not migration_dir.exists():
                self.logger.info("📁 No migrations directory found")
                return

            # Get current database version
            current_version = self._get_database_version()

            # Find migration files
            migration_files = list(migration_dir.glob("*.sql"))
            migration_files.sort()

            for migration_file in migration_files:
                migration_version = self._extract_version_from_filename(migration_file.name)

                if migration_version > current_version:
                    self.logger.info(f"🔄 Running migration: {migration_file.name}")
                    self._execute_migration(migration_file, migration_version)

        except Exception as e:
            self.logger.error(f"❌ Error running migrations: {e}")

    def _get_database_version(self) -> float:
        """Get current database version"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("SELECT value FROM configuration WHERE key = 'database_version'")
                result = cursor.fetchone()
                return float(result[0]) if result else 0.0
        except:
            return 0.0

    def _extract_version_from_filename(self, filename: str) -> float:
        """Extract version number from migration filename"""
        # Expected format: 001_initial_schema.sql
        try:
            version_str = filename.split('_')[0]
            return float(version_str)
        except:
            return 0.0

    def _execute_migration(self, migration_file: Path, version: float) -> None:
        """Execute a migration file"""
        try:
            with open(migration_file, 'r') as f:
                sql_content = f.read()

            with self.get_connection() as conn:
                conn.executescript(sql_content)
                conn.execute(
                    "INSERT OR REPLACE INTO configuration (key, value, description) VALUES (?, ?, ?)",
                    ('database_version', str(version), f'Migration {migration_file.name}')
                )
                conn.commit()

            self.logger.info(f"✅ Migration {migration_file.name} executed successfully")

        except Exception as e:
            self.logger.error(f"❌ Error executing migration {migration_file.name}: {e}")
            raise

    @contextmanager
    def get_connection(self) -> sqlite3.Connection:
        """Get a database connection from the pool"""
        conn = None
        try:
            # Try to get existing connection
            if self._connections:
                conn = self._connections.pop()
            else:
                # Create new connection
                conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=self.config.check_same_thread,
                    timeout=self.config.timeout
                )
                self._connection_count += 1

            # Enable foreign keys and set row factory
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row

            yield conn

        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            raise e

        finally:
            if conn:
                # Return connection to pool or close if pool is full
                if len(self._connections) < self.config.pool_size:
                    self._connections.append(conn)
                else:
                    try:
                        conn.close()
                        self._connection_count -= 1
                    except:
                        pass

    def save_trade(self, trade_data: Dict[str, Any]) -> bool:
        """Save a trade to the database"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO trades
                    (id, symbol, side, entry_price, exit_price, quantity, entry_time, exit_time,
                     pnl, commission, grid_level, strategy_type, session_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    trade_data['id'],
                    trade_data['symbol'],
                    trade_data['side'],
                    trade_data['entry_price'],
                    trade_data['exit_price'],
                    trade_data['quantity'],
                    trade_data['entry_time'],
                    trade_data['exit_time'],
                    trade_data['pnl'],
                    trade_data.get('commission', 0),
                    trade_data.get('grid_level', 0),
                    trade_data.get('strategy_type', 'grid'),
                    trade_data.get('session_id'),
                ))
                conn.commit()

            self.logger.debug(f"💾 Trade saved: {trade_data['id']}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error saving trade: {e}")
            return False

    def save_performance_metrics(self, metrics: Dict[str, Any], symbol: str, date: str) -> bool:
        """Save performance metrics for a specific date"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO performance_metrics
                    (date, symbol, total_trades, winning_trades, losing_trades, total_return,
                     total_return_percent, win_rate, sharpe_ratio, max_drawdown, max_drawdown_percent,
                     profit_factor, session_duration, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    date,
                    symbol,
                    metrics.get('total_trades', 0),
                    metrics.get('winning_trades', 0),
                    metrics.get('losing_trades', 0),
                    metrics.get('total_return', 0),
                    metrics.get('total_return_percent', 0),
                    metrics.get('win_rate', 0),
                    metrics.get('sharpe_ratio', 0),
                    metrics.get('max_drawdown', 0),
                    metrics.get('max_drawdown_percent', 0),
                    metrics.get('profit_factor', 1.0),
                    metrics.get('session_duration', 0),
                ))
                conn.commit()

            self.logger.debug(f"💾 Performance metrics saved for {symbol} on {date}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error saving performance metrics: {e}")
            return False

    def save_daily_balance(self, balance_data: Dict[str, Any], symbol: str, date: str) -> bool:
        """Save daily balance information"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO daily_balance
                    (date, symbol, initial_balance, final_balance, day_pnl, day_pnl_percent,
                     peak_balance, min_balance, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    date,
                    symbol,
                    balance_data.get('initial_balance', 0),
                    balance_data.get('final_balance', 0),
                    balance_data.get('day_pnl', 0),
                    balance_data.get('day_pnl_percent', 0),
                    balance_data.get('peak_balance', 0),
                    balance_data.get('min_balance', 0),
                ))
                conn.commit()

            self.logger.debug(f"💾 Daily balance saved for {symbol} on {date}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error saving daily balance: {e}")
            return False

    def save_log(self, level: str, logger_name: str, message: str,
                 symbol: Optional[str] = None, strategy_type: Optional[str] = None) -> bool:
        """Save a log entry to the database"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    INSERT INTO system_logs
                    (timestamp, level, logger_name, message, symbol, strategy_type)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    level,
                    logger_name,
                    message,
                    symbol,
                    strategy_type,
                ))
                conn.commit()

            return True

        except Exception as e:
            self.logger.error(f"❌ Error saving log: {e}")
            return False

    def save_position(self, position_data: Dict[str, Any], symbol: str,
                     session_id: Optional[str] = None) -> bool:
        """Save position snapshot"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    INSERT INTO positions
                    (symbol, quantity, avg_price, unrealized_pnl, realized_pnl, margin_used,
                     timestamp, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    symbol,
                    position_data['quantity'],
                    position_data['avg_price'],
                    position_data.get('unrealized_pnl', 0),
                    position_data.get('realized_pnl', 0),
                    position_data.get('margin_used', 0),
                    datetime.now().isoformat(),
                    session_id,
                ))
                conn.commit()

            return True

        except Exception as e:
            self.logger.error(f"❌ Error saving position: {e}")
            return False

    def get_trades(self, symbol: Optional[str] = None, limit: int = 100,
                   offset: int = 0) -> List[Dict[str, Any]]:
        """Get trades from database"""
        try:
            with self.get_connection() as conn:
                if symbol:
                    cursor = conn.execute('''
                        SELECT * FROM trades WHERE symbol = ?
                        ORDER BY exit_time DESC LIMIT ? OFFSET ?
                    ''', (symbol, limit, offset))
                else:
                    cursor = conn.execute('''
                        SELECT * FROM trades
                        ORDER BY exit_time DESC LIMIT ? OFFSET ?
                    ''', (limit, offset))

                trades = []
                for row in cursor.fetchall():
                    trades.append(dict(row))

                return trades

        except Exception as e:
            self.logger.error(f"❌ Error getting trades: {e}")
            return []

    def get_performance_metrics(self, symbol: str, days: int = 30) -> List[Dict[str, Any]]:
        """Get performance metrics for the last N days"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            with self.get_connection() as conn:
                cursor = conn.execute('''
                    SELECT * FROM performance_metrics
                    WHERE symbol = ? AND date >= ?
                    ORDER BY date DESC
                ''', (symbol, cutoff_date))

                metrics = []
                for row in cursor.fetchall():
                    metrics.append(dict(row))

                return metrics

        except Exception as e:
            self.logger.error(f"❌ Error getting performance metrics: {e}")
            return []

    def cleanup_old_data(self) -> Dict[str, int]:
        """Clean up old data based on retention policies"""
        try:
            cleanup_stats = {}

            # Clean old logs
            cutoff_date = (datetime.now() - timedelta(days=30)).isoformat()
            with self.get_connection() as conn:
                cursor = conn.execute("DELETE FROM system_logs WHERE timestamp < ?", (cutoff_date,))
                cleanup_stats['logs_deleted'] = cursor.rowcount

                # Clean old trades (keep last 50k)
                cursor = conn.execute('''
                    DELETE FROM trades
                    WHERE id NOT IN (
                        SELECT id FROM trades ORDER BY exit_time DESC LIMIT 50000
                    )
                ''')
                cleanup_stats['trades_deleted'] = cursor.rowcount

                conn.commit()

            self.logger.info(f"🧹 Cleanup completed: {cleanup_stats}")
            return cleanup_stats

        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")
            return {}

    def backup_database(self, backup_path: Optional[str] = None) -> bool:
        """Create a backup of the database"""
        try:
            if not backup_path:
                backup_dir = Path("backups")
                backup_dir.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"pacifica_bot_backup_{timestamp}.db"

            # Create backup using SQLite backup API
            with self.get_connection() as source_conn:
                backup_conn = sqlite3.connect(str(backup_path))
                source_conn.backup(backup_conn)
                backup_conn.close()

            self.logger.info(f"💾 Database backed up to: {backup_path}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error creating backup: {e}")
            return False

    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            with self.get_connection() as conn:
                stats = {}

                # Table counts
                tables = ['trades', 'performance_metrics', 'daily_balance', 'system_logs', 'positions']
                for table in tables:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[f"{table}_count"] = cursor.fetchone()[0]

                # Database size
                db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
                stats['database_size_mb'] = db_size / (1024 * 1024)

                # Connection pool stats
                stats['active_connections'] = self._connection_count
                stats['pooled_connections'] = len(self._connections)

                return stats

        except Exception as e:
            self.logger.error(f"❌ Error getting database stats: {e}")
            return {}