"""
Database Services - High-level CRUD Operations
Provides service layer for database operations with business logic for Pacifica Bot
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date
from dataclasses import dataclass
from .database_manager import DatabaseManager, DatabaseConfig
from .redis_client import RedisClient, RedisConfig

@dataclass
class TradeRecord:
    """Trade record data structure"""
    id: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    commission: float = 0.0
    grid_level: int = 0
    strategy_type: str = 'grid'
    session_id: Optional[str] = None

class TradeService:
    """Service for trade-related database operations"""

    def __init__(self, db_manager: DatabaseManager, redis_client: Optional[RedisClient] = None):
        self.db = db_manager
        self.redis = redis_client
        self.logger = logging.getLogger('PacificaBot.TradeService')

    def save_trade(self, trade: TradeRecord) -> bool:
        """Save a trade record"""
        try:
            # Prepare trade data
            trade_data = {
                'id': trade.id,
                'symbol': trade.symbol,
                'side': trade.side,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'quantity': trade.quantity,
                'entry_time': trade.entry_time.isoformat(),
                'exit_time': trade.exit_time.isoformat(),
                'pnl': trade.pnl,
                'commission': trade.commission,
                'grid_level': trade.grid_level,
                'strategy_type': trade.strategy_type,
                'session_id': trade.session_id,
            }

            # Save to database
            if not self.db.save_trade(trade_data):
                return False

            # Cache in Redis if available
            if self.redis:
                cache_key = f"trade:{trade.id}"
                self.redis.set_cache(cache_key, trade_data, ttl=3600)  # 1 hour

            self.logger.info(f"💾 Trade saved: {trade.id} - {trade.symbol} {trade.side} ${trade.pnl:.2f}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error saving trade {trade.id}: {e}")
            return False

    def get_trades(self, symbol: Optional[str] = None, limit: int = 100,
                   offset: int = 0) -> List[TradeRecord]:
        """Get trades from database"""
        try:
            # Try cache first if Redis is available
            if self.redis:
                cache_key = f"trades:{symbol or 'all'}:{limit}:{offset}"
                cached_data = self.redis.get_cache(cache_key)
                if cached_data:
                    return [TradeRecord(**trade_data) for trade_data in cached_data]

            # Get from database
            trades_data = self.db.get_trades(symbol, limit, offset)

            # Convert to TradeRecord objects
            trades = []
            for trade_data in trades_data:
                try:
                    trade = TradeRecord(
                        id=trade_data['id'],
                        symbol=trade_data['symbol'],
                        side=trade_data['side'],
                        entry_price=trade_data['entry_price'],
                        exit_price=trade_data['exit_price'],
                        quantity=trade_data['quantity'],
                        entry_time=datetime.fromisoformat(trade_data['entry_time']),
                        exit_time=datetime.fromisoformat(trade_data['exit_time']),
                        pnl=trade_data['pnl'],
                        commission=trade_data.get('commission', 0),
                        grid_level=trade_data.get('grid_level', 0),
                        strategy_type=trade_data.get('strategy_type', 'grid'),
                        session_id=trade_data.get('session_id'),
                    )
                    trades.append(trade)
                except Exception as e:
                    self.logger.warning(f"⚠️ Error parsing trade data: {e}")

            # Cache results if Redis is available
            if self.redis and trades:
                self.redis.set_cache(cache_key, [trade.__dict__ for trade in trades], ttl=300)

            return trades

        except Exception as e:
            self.logger.error(f"❌ Error getting trades: {e}")
            return []

    def get_trade_by_id(self, trade_id: str) -> Optional[TradeRecord]:
        """Get a specific trade by ID"""
        try:
            # Try cache first
            if self.redis:
                cache_key = f"trade:{trade_id}"
                cached_data = self.redis.get_cache(cache_key)
                if cached_data:
                    return TradeRecord(**cached_data)

            # Get from database
            trades = self.get_trades(limit=1, offset=0)
            for trade in trades:
                if trade.id == trade_id:
                    return trade

            return None

        except Exception as e:
            self.logger.error(f"❌ Error getting trade {trade_id}: {e}")
            return None

    def get_trades_by_date_range(self, start_date: date, end_date: date,
                                symbol: Optional[str] = None) -> List[TradeRecord]:
        """Get trades within a date range"""
        try:
            # This would require a more complex query with date filtering
            # For now, get all trades and filter in Python
            all_trades = self.get_trades(symbol=symbol, limit=10000)

            filtered_trades = []
            for trade in all_trades:
                trade_date = trade.exit_time.date()
                if start_date <= trade_date <= end_date:
                    filtered_trades.append(trade)

            return filtered_trades

        except Exception as e:
            self.logger.error(f"❌ Error getting trades by date range: {e}")
            return []

@dataclass
class PerformanceMetrics:
    """Performance metrics data structure"""
    date: date
    symbol: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_return: float = 0.0
    total_return_percent: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_percent: float = 0.0
    profit_factor: float = 1.0
    session_duration: float = 0.0

class PerformanceService:
    """Service for performance metrics operations"""

    def __init__(self, db_manager: DatabaseManager, redis_client: Optional[RedisClient] = None):
        self.db = db_manager
        self.redis = redis_client
        self.logger = logging.getLogger('PacificaBot.PerformanceService')

    def save_performance_metrics(self, metrics: PerformanceMetrics) -> bool:
        """Save performance metrics"""
        try:
            metrics_data = {
                'total_trades': metrics.total_trades,
                'winning_trades': metrics.winning_trades,
                'losing_trades': metrics.losing_trades,
                'total_return': metrics.total_return,
                'total_return_percent': metrics.total_return_percent,
                'win_rate': metrics.win_rate,
                'sharpe_ratio': metrics.sharpe_ratio,
                'max_drawdown': metrics.max_drawdown,
                'max_drawdown_percent': metrics.max_drawdown_percent,
                'profit_factor': metrics.profit_factor,
                'session_duration': metrics.session_duration,
            }

            success = self.db.save_performance_metrics(metrics_data, metrics.symbol, str(metrics.date))

            if success and self.redis:
                # Cache for quick access
                cache_key = f"performance:{metrics.symbol}:{metrics.date}"
                self.redis.set_cache(cache_key, metrics.__dict__, ttl=86400)  # 24 hours

            return success

        except Exception as e:
            self.logger.error(f"❌ Error saving performance metrics: {e}")
            return False

    def get_performance_metrics(self, symbol: str, days: int = 30) -> List[PerformanceMetrics]:
        """Get performance metrics for the last N days"""
        try:
            # Try cache first
            if self.redis:
                cache_key = f"performance_history:{symbol}:{days}"
                cached_data = self.redis.get_cache(cache_key)
                if cached_data:
                    return [PerformanceMetrics(**data) for data in cached_data]

            # Get from database
            metrics_data = self.db.get_performance_metrics(symbol, days)

            metrics = []
            for data in metrics_data:
                try:
                    metric = PerformanceMetrics(
                        date=datetime.fromisoformat(data['date']).date(),
                        symbol=data['symbol'],
                        total_trades=data['total_trades'],
                        winning_trades=data['winning_trades'],
                        losing_trades=data['losing_trades'],
                        total_return=data['total_return'],
                        total_return_percent=data['total_return_percent'],
                        win_rate=data['win_rate'],
                        sharpe_ratio=data['sharpe_ratio'],
                        max_drawdown=data['max_drawdown'],
                        max_drawdown_percent=data['max_drawdown_percent'],
                        profit_factor=data['profit_factor'],
                        session_duration=data['session_duration'],
                    )
                    metrics.append(metric)
                except Exception as e:
                    self.logger.warning(f"⚠️ Error parsing performance data: {e}")

            # Cache results
            if self.redis and metrics:
                self.redis.set_cache(cache_key, [m.__dict__ for m in metrics], ttl=3600)

            return metrics

        except Exception as e:
            self.logger.error(f"❌ Error getting performance metrics: {e}")
            return []

@dataclass
class BalanceRecord:
    """Daily balance record"""
    date: date
    symbol: str
    initial_balance: float = 0.0
    final_balance: float = 0.0
    day_pnl: float = 0.0
    day_pnl_percent: float = 0.0
    peak_balance: float = 0.0
    min_balance: float = 0.0

class BalanceService:
    """Service for balance tracking operations"""

    def __init__(self, db_manager: DatabaseManager, redis_client: Optional[RedisClient] = None):
        self.db = db_manager
        self.redis = redis_client
        self.logger = logging.getLogger('PacificaBot.BalanceService')

    def save_daily_balance(self, balance: BalanceRecord) -> bool:
        """Save daily balance record"""
        try:
            balance_data = {
                'initial_balance': balance.initial_balance,
                'final_balance': balance.final_balance,
                'day_pnl': balance.day_pnl,
                'day_pnl_percent': balance.day_pnl_percent,
                'peak_balance': balance.peak_balance,
                'min_balance': balance.min_balance,
            }

            success = self.db.save_daily_balance(balance_data, balance.symbol, str(balance.date))

            if success and self.redis:
                cache_key = f"balance:{balance.symbol}:{balance.date}"
                self.redis.set_cache(cache_key, balance.__dict__, ttl=86400)

            return success

        except Exception as e:
            self.logger.error(f"❌ Error saving daily balance: {e}")
            return False

    def get_daily_balance(self, symbol: str, days: int = 30) -> List[BalanceRecord]:
        """Get daily balance records"""
        try:
            # For now, return empty list as we need to implement this query
            # This would require adding a method to DatabaseManager
            return []

        except Exception as e:
            self.logger.error(f"❌ Error getting daily balance: {e}")
            return []

class LogService:
    """Service for system logging operations"""

    def __init__(self, db_manager: DatabaseManager, redis_client: Optional[RedisClient] = None):
        self.db = db_manager
        self.redis = redis_client
        self.logger = logging.getLogger('PacificaBot.LogService')

    def save_log(self, level: str, logger_name: str, message: str,
                 symbol: Optional[str] = None, strategy_type: Optional[str] = None) -> bool:
        """Save a log entry"""
        try:
            return self.db.save_log(level, logger_name, message, symbol, strategy_type)
        except Exception as e:
            self.logger.error(f"❌ Error saving log: {e}")
            return False

class DatabaseServiceManager:
    """Central manager for all database services"""

    def __init__(self, db_config: Optional[DatabaseConfig] = None,
                 redis_config: Optional[RedisConfig] = None):
        self.logger = logging.getLogger('PacificaBot.DatabaseServiceManager')

        # Initialize database manager
        self.db_manager = DatabaseManager(db_config)

        # Initialize Redis client (optional)
        self.redis_client = None
        if redis_config:
            self.redis_client = RedisClient(redis_config)

        # Initialize services
        self.trades = TradeService(self.db_manager, self.redis_client)
        self.performance = PerformanceService(self.db_manager, self.redis_client)
        self.balance = BalanceService(self.db_manager, self.redis_client)
        self.logs = LogService(self.db_manager, self.redis_client)

        self.logger.info("✅ Database services initialized")

    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        health = {
            'database': self.db_manager.get_database_stats(),
            'redis': self.redis_client.health_check() if self.redis_client else {'connected': False},
            'services': {
                'trades': True,
                'performance': True,
                'balance': True,
                'logs': True,
            }
        }

        return health

    def cleanup_old_data(self) -> Dict[str, int]:
        """Clean up old data across all services"""
        return self.db_manager.cleanup_old_data()

    def backup_database(self, backup_path: Optional[str] = None) -> bool:
        """Create a backup of the database"""
        return self.db_manager.backup_database(backup_path)