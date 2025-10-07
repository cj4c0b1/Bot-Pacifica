"""
Database Integration Example - How to use the new database tech stack
This file demonstrates how to integrate the database services with existing bot components
"""

import os
import logging
from datetime import datetime
from typing import Optional

from .database_manager import DatabaseManager, DatabaseConfig
from .redis_client import RedisClient, RedisConfig
from .database_services import DatabaseServiceManager, TradeRecord, PerformanceMetrics, BalanceRecord

class DatabaseIntegration:
    """Example integration class showing how to use database services"""

    def __init__(self):
        self.logger = logging.getLogger('PacificaBot.DatabaseIntegration')
        self.db_manager: Optional[DatabaseServiceManager] = None
        self._initialize_database()

    def _initialize_database(self):
        """Initialize database connections"""
        try:
            # Load configuration from environment
            db_config = DatabaseConfig(
                database_path=os.getenv('SQLITE_DATABASE_PATH', 'data/pacifica_bot.db'),
                pool_size=int(os.getenv('SQLITE_POOL_SIZE', '5')),
                check_same_thread=os.getenv('SQLITE_CHECK_SAME_THREAD', 'false').lower() == 'true'
            )

            redis_config = RedisConfig()

            # Initialize database service manager
            self.db_manager = DatabaseServiceManager(db_config, redis_config)

            self.logger.info("✅ Database integration initialized")

        except Exception as e:
            self.logger.error(f"❌ Error initializing database integration: {e}")
            self.db_manager = None

    def record_trade_example(self, symbol: str = "BTC"):
        """Example: Record a trade in the database"""
        if not self.db_manager:
            self.logger.error("❌ Database not initialized")
            return False

        try:
            # Create a sample trade record
            trade = TradeRecord(
                id=f"trade_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                symbol=symbol,
                side="buy",
                entry_price=50000.0,
                exit_price=51000.0,
                quantity=0.1,
                entry_time=datetime.now(),
                exit_time=datetime.now(),
                pnl=100.0,
                commission=1.0,
                grid_level=5,
                strategy_type="grid",
                session_id="session_001"
            )

            # Save the trade
            success = self.db_manager.trades.save_trade(trade)

            if success:
                self.logger.info(f"✅ Trade recorded: {trade.id}")
            else:
                self.logger.error("❌ Failed to record trade")

            return success

        except Exception as e:
            self.logger.error(f"❌ Error recording trade: {e}")
            return False

    def record_performance_example(self, symbol: str = "BTC"):
        """Example: Record performance metrics"""
        if not self.db_manager:
            return False

        try:
            # Create sample performance metrics
            today = datetime.now().date()
            metrics = PerformanceMetrics(
                date=today,
                symbol=symbol,
                total_trades=100,
                winning_trades=60,
                losing_trades=40,
                total_return=500.0,
                total_return_percent=10.0,
                win_rate=60.0,
                sharpe_ratio=1.5,
                max_drawdown=100.0,
                max_drawdown_percent=2.0,
                profit_factor=1.5,
                session_duration=24.0
            )

            success = self.db_manager.performance.save_performance_metrics(metrics)

            if success:
                self.logger.info(f"✅ Performance metrics recorded for {symbol}")
            else:
                self.logger.error("❌ Failed to record performance metrics")

            return success

        except Exception as e:
            self.logger.error(f"❌ Error recording performance: {e}")
            return False

    def record_balance_example(self, symbol: str = "BTC"):
        """Example: Record daily balance"""
        if not self.db_manager:
            return False

        try:
            today = datetime.now().date()
            balance = BalanceRecord(
                date=today,
                symbol=symbol,
                initial_balance=10000.0,
                final_balance=10500.0,
                day_pnl=500.0,
                day_pnl_percent=5.0,
                peak_balance=10600.0,
                min_balance=9900.0
            )

            success = self.db_manager.balance.save_daily_balance(balance)

            if success:
                self.logger.info(f"✅ Daily balance recorded for {symbol}")
            else:
                self.logger.error("❌ Failed to record daily balance")

            return success

        except Exception as e:
            self.logger.error(f"❌ Error recording balance: {e}")
            return False

    def query_data_example(self, symbol: str = "BTC"):
        """Example: Query data from database"""
        if not self.db_manager:
            return

        try:
            # Get recent trades
            trades = self.db_manager.trades.get_trades(symbol=symbol, limit=10)
            self.logger.info(f"📊 Recent trades for {symbol}: {len(trades)}")

            for trade in trades[:3]:  # Show first 3
                self.logger.info(f"   {trade.id}: {trade.side} {trade.quantity} @ {trade.entry_price} → PnL: ${trade.pnl:.2f}")

            # Get performance metrics
            metrics = self.db_manager.performance.get_performance_metrics(symbol, days=7)
            self.logger.info(f"📈 Performance metrics for {symbol}: {len(metrics)} days")

        except Exception as e:
            self.logger.error(f"❌ Error querying data: {e}")

    def cache_example(self):
        """Example: Use Redis caching"""
        if not self.db_manager or not self.db_manager.redis_client:
            self.logger.warning("⚠️ Redis not available for caching example")
            return

        try:
            # Cache some data
            test_data = {"test": "data", "timestamp": datetime.now().isoformat()}
            success = self.db_manager.redis_client.set_cache("test:example", test_data, ttl=300)

            if success:
                # Retrieve cached data
                cached_data = self.db_manager.redis_client.get_cache("test:example")
                self.logger.info(f"💾 Cache test successful: {cached_data}")

                # Clean up
                self.db_manager.redis_client.delete_cache("test:example")
            else:
                self.logger.error("❌ Cache test failed")

        except Exception as e:
            self.logger.error(f"❌ Error in cache example: {e}")

    def run_all_examples(self):
        """Run all integration examples"""
        self.logger.info("🚀 Running database integration examples...")

        # Record sample data
        self.record_trade_example("BTC")
        self.record_performance_example("BTC")
        self.record_balance_example("BTC")

        # Query data
        self.query_data_example("BTC")

        # Cache example
        self.cache_example()

        # Health check
        if self.db_manager:
            health = self.db_manager.health_check()
            self.logger.info(f"🏥 Database health: {health}")

        self.logger.info("✅ All examples completed")

# Example usage in existing bot components
def integrate_with_position_manager(position_manager, db_services: DatabaseServiceManager):
    """Example: Integrate database with PositionManager"""

    try:
        # Save current position to database
        for symbol, position in position_manager.positions.items():
            position_data = {
                'quantity': position['quantity'],
                'avg_price': position['avg_price'],
                'unrealized_pnl': position.get('unrealized_pnl', 0),
                'realized_pnl': position.get('realized_pnl', 0),
                'margin_used': 0,  # Calculate based on position value
            }

            db_services.db_manager.save_position(position_data, symbol)

        print(f"💾 Positions saved to database: {list(position_manager.positions.keys())}")

    except Exception as e:
        print(f"❌ Error integrating with PositionManager: {e}")

def integrate_with_performance_tracker(performance_tracker, db_services: DatabaseServiceManager):
    """Example: Integrate database with PerformanceTracker"""

    try:
        # Save current metrics to database
        metrics = performance_tracker.calculate_metrics()

        today = datetime.now().date()
        perf_metrics = PerformanceMetrics(
            date=today,
            symbol=performance_tracker.symbol,
            **metrics
        )

        success = db_services.performance.save_performance_metrics(perf_metrics)

        if success:
            print(f"💾 Performance metrics saved for {performance_tracker.symbol}")
        else:
            print("❌ Failed to save performance metrics")

    except Exception as e:
        print(f"❌ Error integrating with PerformanceTracker: {e}")

# ============================================================================
# INTEGRATION GUIDE
# ============================================================================
"""
Para integrar o novo sistema de banco de dados com os componentes existentes:

1. POSITION MANAGER:
   - Salvar posições atuais periodicamente
   - Registrar mudanças de posição
   - Fazer backup de estado crítico

2. PERFORMANCE TRACKER:
   - Salvar métricas diárias automaticamente
   - Manter histórico de performance
   - Gerar relatórios consolidados

3. GRID BOT MAIN LOOP:
   - Registrar todas as operações
   - Salvar logs importantes
   - Fazer backup automático

4. CACHE REDIS:
   - Preços em tempo real
   - Saldos atualizados
   - Sessões ativas

Exemplo de uso básico:

    from src.database_services import DatabaseServiceManager

    # Inicializar serviços
    db_services = DatabaseServiceManager()

    # Registrar um trade
    trade = TradeRecord(
        id="unique_trade_id",
        symbol="BTC",
        side="buy",
        entry_price=50000,
        exit_price=51000,
        quantity=0.1,
        entry_time=datetime.now(),
        exit_time=datetime.now(),
        pnl=100.0
    )

    db_services.trades.save_trade(trade)

    # Consultar dados
    trades = db_services.trades.get_trades(symbol="BTC", limit=10)

    # Verificar saúde do sistema
    health = db_services.health_check()
"""