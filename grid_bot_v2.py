"""
Pacifica Grid Trading Bot - Database Integrated Version
Enhanced version with SQLite database and Redis cache integration
Implements Grid Trading strategies with persistent data storage
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime, date
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

# Import bot modules (assuming they're in the same directory)
from src.pacifica_auth import PacificaAuth
from src.grid_calculator import GridCalculator
from src.position_manager import PositionManager
from src.grid_strategy import GridStrategy
from src.dynamic_grid_strategy import DynamicGridStrategy
from src.multi_asset_strategy import MultiAssetStrategy
from src.multi_asset_enhanced_strategy import MultiAssetEnhancedStrategy
from src.performance_tracker import PerformanceTracker
from src.strategy_logger import create_strategy_logger, get_strategy_specific_messages
from src.telegram_notifier import TelegramNotifier
from src.grid_risk_manager import GridRiskManager

# Import new database tech stack
from src.database_manager import DatabaseManager, DatabaseConfig
from src.redis_client import RedisClient, RedisConfig
from src.database_services import DatabaseServiceManager, TradeRecord, PerformanceMetrics, BalanceRecord

class GridTradingBotV2:
    """
    Enhanced Grid Trading Bot with Database Integration

    This version adds:
    - SQLite database for persistent storage
    - Redis caching for real-time data
    - Enhanced logging and monitoring
    - Automatic backups and cleanup
    """

    def __init__(self):
        # Load configurations
        load_dotenv()

        # Load database configuration
        load_dotenv('.env.database', override=True)

        # Determine strategy type - ONLY ONE VARIABLE: STRATEGY_TYPE
        strategy_type_env = os.getenv('STRATEGY_TYPE', 'market_making').lower()

        # Map all strategies via STRATEGY_TYPE
        if strategy_type_env == 'multi_asset':
            self.strategy_type = 'multi_asset'
        elif strategy_type_env == 'multi_asset_enhanced':
            self.strategy_type = 'multi_asset_enhanced'
        elif strategy_type_env in ['pure_grid', 'market_making', 'dynamic_grid']:
            self.strategy_type = 'grid'
            self.grid_type = strategy_type_env  # Save specific grid type
        else:
            # Fallback to market_making if invalid value
            self.strategy_type = 'grid'
            self.grid_type = 'market_making'

        # Initialize database services FIRST
        self._initialize_database_services()

        # Set up logging
        self.setup_logging()

        # Create strategy-specific logger
        self.logger = create_strategy_logger('PacificaBot.Main', self.strategy_type)

        # Bot state
        self.running = False
        self.start_time = None

        # Session ID for tracking
        self.session_id = f"session_{int(time.time())}"

        # Settings
        self.symbol = os.getenv('SYMBOL', 'BTC')
        self.rebalance_interval = int(os.getenv('REBALANCE_INTERVAL_SECONDS', '60'))
        self.check_balance = os.getenv('CHECK_BALANCE_BEFORE_ORDER', 'true').lower() == 'true'

        # ✨ NEW FEATURE: Periodic grid reset
        self.enable_periodic_reset = os.getenv('ENABLE_PERIODIC_GRID_RESET', 'false').lower() == 'true'
        self.grid_reset_interval = int(os.getenv('GRID_RESET_INTERVAL_MINUTES', '60')) * 60  # Convert to seconds

        # Session control settings
        self.session_stop_loss = float(os.getenv('SESSION_STOP_LOSS_USD', '100'))
        self.session_take_profit = float(os.getenv('SESSION_TAKE_PROFIT_USD', '200'))
        self.session_max_loss = float(os.getenv('SESSION_MAX_LOSS_USD', '150'))

        # Session state
        self.session_start_balance = 0.0
        self.session_realized_pnl = 0.0
        self.is_paused = False

        # Declare components as None - will be initialized in initialize_components()
        self.auth = None
        self.calculator = None
        self.position_mgr = None
        self.telegram = None
        self.risk_manager = None
        self.strategy = None

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def _initialize_database_services(self) -> None:
        """Initialize database services"""
        try:
            self.logger.info("🗄️ Initializing database services...")

            # Database configuration
            db_config = DatabaseConfig(
                database_path=os.getenv('SQLITE_DATABASE_PATH', 'data/pacifica_bot.db'),
                pool_size=int(os.getenv('SQLITE_POOL_SIZE', '5')),
                check_same_thread=os.getenv('SQLITE_CHECK_SAME_THREAD', 'false').lower() == 'true'
            )

            # Redis configuration
            redis_config = RedisConfig()

            # Initialize database service manager
            self.db_services = DatabaseServiceManager(db_config, redis_config)

            # Test database connectivity
            health = self.db_services.health_check()
            if not health.get('database', {}).get('active_connections', 0) > 0:
                raise Exception("Database connection failed")

            self.logger.info("✅ Database services initialized successfully")

        except Exception as e:
            self.logger.error(f"❌ Error initializing database services: {e}")
            # Continue without database for backward compatibility
            self.db_services = None

    def show_strategy_header(self) -> None:
        """Show strategy-specific header"""

        self.logger.info("=" * 80, force=True)
        self.logger.info("🤖 PACIFICA TRADING BOT - DATABASE EDITION", force=True)
        self.logger.info("=" * 80, force=True)

        if self.strategy_type == 'grid':
            grid_type = getattr(self, 'grid_type', 'market_making').upper()
            if grid_type == 'DYNAMIC_GRID':
                self.logger.info("Strategy: 🎯 DYNAMIC GRID TRADING", force=True)
                # Show Dynamic Grid specific settings
                threshold = os.getenv('DYNAMIC_THRESHOLD_PERCENT', '1.0')
                max_distance = os.getenv('MAX_ADJUSTMENT_DISTANCE_PERCENT', '5.0')
                self.logger.info(f"Adjustment Threshold: {threshold}%", force=True)
                self.logger.info(f"Maximum Distance: {max_distance}%", force=True)
            else:
                self.logger.info(f"Strategy: GRID TRADING ({grid_type})", force=True)
            self.logger.info(f"Symbol: {self.symbol}", force=True)
        elif self.strategy_type == 'multi_asset_enhanced':
            self.logger.info("Strategy: 🧠 ENHANCED MULTI-ASSET", force=True)
            symbols = os.getenv('SYMBOLS', 'BTC,ETH,SOL')
            quality = os.getenv('ENHANCED_MIN_SIGNAL_QUALITY', '65')
            confidence = os.getenv('ENHANCED_MIN_CONFIDENCE', '75')
            self.logger.info(f"Symbols: {symbols}", force=True)
            self.logger.info(f"Algorithm: Quality≥{quality}, Confidence≥{confidence}", force=True)
        else:  # multi_asset
            self.logger.info("Strategy: MULTI-ASSET SCALPING", force=True)
            symbols = os.getenv('SYMBOLS', 'BTC,ETH,SOL')
            self.logger.info(f"Symbols: {symbols}", force=True)

        self.logger.info(f"Rebalancing Interval: {self.rebalance_interval}s", force=True)

        # ✨ Show periodic reset configuration
        if self.enable_periodic_reset:
            reset_minutes = self.grid_reset_interval // 60
            self.logger.info(f"🔄 Periodic Reset: Every {reset_minutes} minutes", force=True)
        else:
            self.logger.info("🔄 Periodic Reset: Disabled", force=True)

        # Show database status
        if self.db_services:
            db_health = self.db_services.health_check()
            db_connected = db_health.get('database', {}).get('active_connections', 0) > 0
            redis_connected = db_health.get('redis', {}).get('connected', False)

            self.logger.info(f"🗄️ Database: {'✅ Connected' if db_connected else '❌ Disconnected'}", force=True)
            self.logger.info(f"🔗 Redis Cache: {'✅ Connected' if redis_connected else '❌ Disconnected'}", force=True)
        else:
            self.logger.info("🗄️ Database: ❌ Not Available", force=True)

        self.logger.info("=" * 80, force=True)

        # 🔧 VALIDATION SYSTEM (NEW)
        self._run_config_validations()

    def setup_logging(self) -> None:
        """Configure logging system"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"grid_bot_v2_{timestamp}.log"

        log_level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper())

        log_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Root logger
        root_logger = logging.getLogger('PacificaBot')
        root_logger.setLevel(log_level)
        root_logger.handlers.clear()

        # File handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(log_format)
        root_logger.addHandler(console_handler)

        # Enhanced logging to database if available
        if hasattr(self, 'db_services') and self.db_services:
            # Add database logging handler
            class DatabaseLogHandler(logging.Handler):
                def __init__(self, db_services, bot_instance):
                    super().__init__()
                    self.db_services = db_services
                    self.bot = bot_instance

                def emit(self, record):
                    try:
                        if record.levelno >= logging.WARNING:  # Only log warnings and above
                            self.db_services.logs.save_log(
                                level=record.levelname,
                                logger_name=record.name,
                                message=record.getMessage(),
                                symbol=getattr(self.bot, 'symbol', None),
                                strategy_type=getattr(self.bot, 'strategy_type', None)
                            )
                    except:
                        pass  # Don't let logging errors break the bot

            db_handler = DatabaseLogHandler(self.db_services, self)
            db_handler.setLevel(logging.WARNING)
            db_handler.setFormatter(log_format)
            root_logger.addHandler(db_handler)

    def _run_config_validations(self) -> None:
        """Run configuration validations without affecting main functionality"""
        try:
            from src.config_validator import run_all_validations

            self.logger.info("🔧 Running configuration validations...")
            validation_result = run_all_validations(self.strategy_type)

            if validation_result['warnings']:
                self.logger.warning("⚠️ CONFIGURATION WARNINGS:")
                for warning in validation_result['warnings']:
                    self.logger.warning(f"  • {warning}")

            if validation_result['errors']:
                self.logger.error("❌ CRITICAL CONFIGURATION ISSUES:")
                for error in validation_result['errors']:
                    self.logger.error(f"  • {error}")
                self.logger.error("⚠️ Bot may not work correctly - please check the settings above")
            else:
                self.logger.info("✅ All validations passed successfully")

        except ImportError:
            self.logger.debug("📋 Config validator not found, skipping validations")
        except Exception as e:
            self.logger.debug(f"⚠️ Error during validations: {e}")

    def initialize_components(self) -> bool:
        """Initialize all bot components"""

        try:
            self.logger.info("🔧 Initializing components...")

            # 1. Authentication
            self.auth = PacificaAuth()
            self.logger.info("✅ Auth Client initialized")

            # 2. Telegram Notifier (before Risk Manager)
            self.telegram = TelegramNotifier()
            self.logger.info("✅ Telegram Notifier initialized")

            # 3. Clean up old orders (if configured)
            clean_on_start = os.getenv('CLEAN_ORDERS_ON_START', 'false').lower() == 'true'
            if clean_on_start:
                self.logger.warning("🧹 Cleaning up old orders...")
                self._clean_old_orders()

            # 4. Grid Calculator (with auth to fetch market info)
            self.calculator = GridCalculator(auth_client=self.auth)
            self.logger.info("✅ Grid Calculator initialized")

            # 5. Position Manager
            self.position_mgr = PositionManager(self.auth)
            self.logger.info("✅ Position Manager initialized")

            # 6. Grid Risk Manager (only for grid strategies)
            self.risk_manager = None
            if self.strategy_type == 'grid':
                self.risk_manager = GridRiskManager(
                    auth_client=self.auth,
                    position_manager=self.position_mgr,
                    telegram_notifier=self.telegram,
                    logger=self.logger
                )
                self.logger.info("✅ Grid Risk Manager initialized")

            # 7. Initialize strategy based on configured type
            if self.strategy_type == 'multi_asset':
                self.logger.info("🎯 Initializing Multi-Asset Scalping strategy...")
                self.strategy = MultiAssetStrategy(self.auth, self.calculator, self.position_mgr)
            elif self.strategy_type == 'multi_asset_enhanced':
                self.logger.info("🧠 Initializing Enhanced Multi-Asset strategy...")
                self.strategy = MultiAssetEnhancedStrategy(self.auth, self.calculator, self.position_mgr)
            else:
                # Check if should use dynamic strategy
                if hasattr(self, 'grid_type') and self.grid_type == 'dynamic_grid':
                    self.logger.info("🎯 Initializing Dynamic Grid Trading strategy...")
                    self.strategy = DynamicGridStrategy(self.auth, self.calculator, self.position_mgr)
                else:
                    self.logger.info("📊 Initializing Grid Trading strategy...")
                    self.strategy = GridStrategy(self.auth, self.calculator, self.position_mgr)

            self.logger.info("✅ Components initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error initializing components: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _clean_old_orders(self) -> None:
        """Cancel all open orders for the symbol with robust verification"""
        try:
            self.logger.info(f"🔍 Checking existing orders for {self.symbol}...")

            # Fetch all open orders
            all_open_orders = self.auth.get_open_orders()

            if not all_open_orders:
                self.logger.info("ℹ️ No orders found in the account")
                return

            # Filter orders for the specific symbol
            symbol_orders = []
            for order in all_open_orders:
                if order.get('symbol') == self.symbol:
                    symbol_orders.append(order)

            if not symbol_orders:
                self.logger.info(f"ℹ️ No orders found for {self.symbol}")
                return

            self.logger.info(f"🚫 Canceling {len(symbol_orders)} orders for {self.symbol}...")

            cancelled_count = 0
            failed_count = 0

            for order in symbol_orders:
                order_id = order.get('order_id')
                price = order.get('price', 'N/A')
                side = order.get('side', 'N/A')
                order_type = order.get('type', 'LIMIT')

                if order_id:
                    try:
                        self.logger.debug(f"   Canceling: {side} @ {price} (ID: {order_id})")

                        # Pass the symbol for cancellation
                        result = self.auth.cancel_order(str(order_id), self.symbol)

                        if result and result.get('success'):
                            cancelled_count += 1
                            self.logger.debug(f"   ✅ Canceled: {order_id}")
                        else:
                            failed_count += 1
                            error_msg = result.get('error', 'Unknown error') if result else 'No response'
                            self.logger.warning(f"   ⚠️ Failed to cancel {order_id}: {error_msg}")

                        time.sleep(0.15)  # Delay between cancellations to avoid rate limiting

                    except Exception as cancel_error:
                        failed_count += 1
                        self.logger.error(f"   ❌ Error canceling {order_id}: {cancel_error}")
                else:
                    self.logger.warning(f"   ⚠️ Order without valid ID: {order}")

            # Wait for cancellations to process
            if cancelled_count > 0:
                self.logger.info("⏳ Processing cancellations...")
                time.sleep(2.0)

                # Verify if orders were actually canceled
                remaining_orders = self.auth.get_open_orders(self.symbol)
                remaining_count = len(remaining_orders) if remaining_orders else 0

                if remaining_count == 0:
                    self.logger.info(f"✅ Successfully canceled all {cancelled_count} orders")
                else:
                    self.logger.warning(f"⚠️ {remaining_count} orders still remain after cancellation")

            if failed_count > 0:
                self.logger.warning(f"⚠️ Failed to cancel {failed_count} orders")

            self.logger.info("🧹 Order cleanup completed")

        except Exception as e:
            self.logger.error(f"❌ Error cleaning up orders: {e}")
            import traceback
            self.logger.debug(f"Stack trace: {traceback.format_exc()}")

    def get_current_price(self) -> float:
        """Gets the current market price with Redis caching"""
        try:
            # Try Redis cache first if available
            if self.db_services and self.db_services.redis_client:
                cached_price = self.db_services.redis_client.get_cached_price(self.symbol)
                if cached_price:
                    price_data = cached_price
                    if isinstance(price_data, dict) and 'price' in price_data:
                        self.logger.debug(f"💾 Using cached price for {self.symbol}: ${price_data['price']}")
                        return float(price_data['price'])

            # Use the real API method
            prices = self.auth.get_prices()

            if not prices:
                self.logger.warning("⚠️ API returned empty price data")
                return 0

            if not isinstance(prices, dict):
                self.logger.warning(f"⚠️ API returned invalid format: {type(prices)}")
                return 0

            # API returns {"success": true, "data": [...]}
            if not prices.get('success'):
                self.logger.warning(f"⚠️ API returned error: {prices}")
                return 0

            data = prices.get('data')
            if not data:
                self.logger.warning("⚠️ API did not return price data")
                return 0

            if not isinstance(data, list):
                self.logger.warning(f"⚠️ Price data in invalid format: {type(data)}")
                return 0

            # Search for the specific symbol
            for item in data:
                if item.get('symbol') == self.symbol:
                    # Price is in 'mark' or 'mid'
                    price = item.get('mark') or item.get('mid')
                    if price:
                        price_float = float(price)
                        if price_float > 0:
                            # Cache the price if Redis is available
                            if self.db_services and self.db_services.redis_client:
                                self.db_services.redis_client.cache_price(self.symbol, {
                                    'price': price_float,
                                    'timestamp': datetime.now().isoformat(),
                                    'source': 'api'
                                })
                            return price_float
                        else:
                            self.logger.warning(f"⚠️ Invalid price received for {self.symbol}: {price}")

            self.logger.warning(f"⚠️ Symbol {self.symbol} not found in API data")
            self.logger.debug(f"Available symbols: {[item.get('symbol') for item in data[:5]]}")
            return 0

        except Exception as e:
            self.logger.error(f"❌ Error getting price: {e}")
            import traceback
            self.logger.debug(f"Stack trace: {traceback.format_exc()}")
            return 0

    def run(self) -> None:
        """Main bot loop with database integration"""

        self.logger.info("🚀 Starting Grid Trading Bot V2 with Database Integration...")

        # Initialize components
        if not self.initialize_components():
            self.logger.error("❌ Initialization failed - aborting")
            return

        # Initialize symbol info test (only for grid strategy)
        if self.strategy_type == 'grid':
            self.logger.info(f"🔍 Testing market info for {self.symbol}...")
            test_info = self.auth.get_symbol_info(self.symbol)
            if test_info:
                self.logger.info(f"✅ tick_size={test_info.get('tick_size')}, lot_size={test_info.get('lot_size')}")
        else:
            self.logger.info("🔍 Testing connection with multiple symbols...")

        # Get initial price (only for grid strategy)
        if self.strategy_type == 'grid':
            current_price = self.get_current_price()
            if current_price == 0:
                self.logger.warning("⚠️ Initial price not obtained - attempting to recover...")
                # Retry with delays
                for attempt in range(3):
                    time.sleep(2)  # Wait 2 seconds
                    current_price = self.get_current_price()
                    if current_price > 0:
                        self.logger.info(f"✅ Price recovered on attempt {attempt + 1}")
                        break

                if current_price == 0:
                    self.logger.error("❌ Could not get initial price after 3 attempts")
                    return

            self.logger.info(f"💰 Initial price {self.symbol}: ${current_price",.2f"}")
        else:
            current_price = 0  # Multi-asset manages its own prices
            self.logger.info("💰 Multi-Asset Strategy: prices managed internally")

        # Check balance if configured
        if self.check_balance:
            self.logger.info("💳 Checking account balance...")
            if not self.position_mgr.update_account_state():
                self.logger.error("❌ Failed to check balance")
                return

        # Account verification
        self.logger.info("💳 Loading account information...")
        if self.position_mgr.update_account_state():
            self.logger.info("=" * 60)
            self.logger.info("💰 ACCOUNT STATUS:")
            self.logger.info(f"   Total Balance: ${self.position_mgr.account_balance".2f"}")
            self.logger.info(f"   Used Margin: ${self.position_mgr.margin_used".2f"}")
            self.logger.info(f"   Available Margin: ${self.position_mgr.margin_available".2f"}")

            if self.position_mgr.account_balance > 0:
                margin_percent = (self.position_mgr.margin_available /
                                self.position_mgr.account_balance * 100)
                self.logger.info(f"   Free Margin: {margin_percent".1f"}%")

            self.logger.info("=" * 60)

            # Save initial balance to database
            if self.db_services:
                try:
                    today = date.today()
                    initial_balance_record = BalanceRecord(
                        date=today,
                        symbol=self.symbol,
                        initial_balance=self.position_mgr.account_balance,
                        final_balance=self.position_mgr.account_balance,  # Will be updated later
                        day_pnl=0.0,
                        day_pnl_percent=0.0,
                        peak_balance=self.position_mgr.account_balance,
                        min_balance=self.position_mgr.account_balance
                    )
                    self.db_services.balance.save_daily_balance(initial_balance_record)
                    self.logger.info("💾 Initial balance saved to database")
                except Exception as e:
                    self.logger.warning(f"⚠️ Could not save initial balance to database: {e}")
        else:
            self.logger.error("❌ Failed to load account information")

        # Initialize strategy with specific messages
        messages = get_strategy_specific_messages(self.strategy_type)
        self.logger.strategy_info(messages['initialization'])

        grid_initialized = self.strategy.initialize_grid(current_price)
        if not grid_initialized:
            if self.strategy_type == 'multi_asset':
                self.logger.warning("⚠️ Could not initialize Multi-Asset at this time")
            else:
                self.logger.warning("⚠️ Could not initialize Grid now (insufficient margin)")
            self.logger.info("🔄 Bot will keep monitoring and try again...")

        # Check if strategy was initialized
        grid_status = self.strategy.get_grid_status()
        messages = get_strategy_specific_messages(self.strategy_type)

        if self.strategy_type == 'grid':
            if grid_status['active_orders'] > 0:
                self.logger.strategy_info(f"Resumed with {grid_status['active_orders']} existing orders")
            elif grid_initialized:
                self.logger.strategy_info(f"New grid created with {grid_status['active_orders']} orders")
            else:
                self.logger.strategy_info("Waiting for conditions to create grid...")
        else:
            if grid_initialized:
                self.logger.strategy_info(messages['ready'])
            else:
                self.logger.strategy_info("Waiting for market conditions...")

        self.running = True
        self.start_time = datetime.now()

        self.logger.info("✅ Bot is running!", force=True)
        self.logger.info("=" * 80)

        # 🎯 INITIAL TP/SL CHECK for Multi-Asset strategies
        if self.strategy_type in ['multi_asset', 'multi_asset_enhanced']:
            self.logger.info("🔍 Running initial TP/SL check...")
            try:
                if hasattr(self.strategy, '_check_all_tp_sl'):
                    self.strategy._check_all_tp_sl()
                    self.logger.info("✅ Initial TP/SL check completed")
                else:
                    self.logger.warning("⚠️ _check_all_tp_sl method not found in strategy")
            except Exception as e:
                self.logger.error(f"❌ Error in initial TP/SL check: {e}")

        # Main loop
        iteration = 0
        last_rebalance = time.time()
        last_price_check = time.time()
        last_grid_reset = time.time()  # ✨ NEW: Periodic reset control
        last_daily_report = datetime.now().date()  # Daily report control

        # Initialize current_price based on strategy
        if self.strategy_type == 'grid':
            current_price = self.get_current_price()  # Grid uses single price
        else:
            current_price = 0  # Multi-asset doesn't use single price

        # Set initial balance in risk manager
        if self.risk_manager:
            initial_balance = self.position_mgr.account_balance
            self.risk_manager.set_initial_balance(initial_balance)

        while self.running:
            try:
                iteration += 1
                current_time = time.time()

                # ===== CHECK IF BOT IS PAUSED =====
                if self.risk_manager and self.risk_manager.check_if_paused():
                    if iteration % 10 == 0:  # Log every 10 iterations
                        self.logger.info("⏸️ Bot paused - waiting to resume...")
                    time.sleep(10)  # Wait 10 seconds
                    continue  # Skip the rest of the loop

                # DEBUG: Send Risk Manager status (only in debug mode)
                debug_mode = os.getenv('DEBUG_MODE', 'false').lower() == 'true'
                if self.risk_manager and debug_mode and iteration % 20 == 0:
                    self.risk_manager.send_periodic_debug_status()

                # 🔧 Get price only for grid strategy with robust error handling
                if self.strategy_type == 'grid' and current_time - last_price_check >= 30:
                    new_price = self.get_current_price()
                    if new_price > 0:
                        current_price = new_price
                    else:
                        self.logger.warning("⚠️ Failed to update price - keeping previous price")
                    last_price_check = current_time

                # Strategy-specific heartbeat log
                if iteration % 10 == 0:
                    uptime = datetime.now() - self.start_time
                    if self.strategy_type == 'grid':
                        self.logger.info(f"💓 Heartbeat #{iteration} - Uptime: {uptime} | Price: ${current_price",.2f"}", force=True)
                    else:
                        active_positions = len(getattr(self.strategy, 'active_positions', []))
                        self.logger.info(f"💓 Heartbeat #{iteration} - Uptime: {uptime} | Positions: {active_positions}", force=True)

                # ENABLE MARGIN CHECK (EVERY 5 ITERATIONS = ~5 SECONDS)
                if self.check_balance and iteration % 5 == 0:
                    # 1. Update account state
                    self.position_mgr.update_account_state()

                    # 2. ✅ ENABLE MARGIN CHECK (UNCOMMENTED)
                    is_safe, msg = self.position_mgr.check_margin_safety()

                    if not is_safe:
                        # Log the detected issue
                        self.logger.warning(f"⚠️ {msg}")

                        # 🔥 THE FUNCTION ALREADY EXECUTED ACTIONS AUTOMATICALLY:
                        # - If margin < 20% → Canceled orders
                        # - If margin < 10% → Sold position

                        # Bot CONTINUES OPERATING (does not stop)

                # Periodic database operations
                if self.db_services and iteration % 60 == 0:  # Every minute
                    try:
                        # Update session activity in Redis
                        if self.db_services.redis_client:
                            self.db_services.redis_client.update_session_activity(self.session_id)

                        # Save position snapshots (every 5 minutes)
                        if iteration % 300 == 0:
                            self._save_position_snapshot()

                    except Exception as e:
                        self.logger.debug(f"⚠️ Database operation failed: {e}")

                # Daily database operations
                current_date = datetime.now().date()
                if current_date != last_daily_report:
                    try:
                        self._generate_daily_report(last_daily_report)
                        last_daily_report = current_date
                    except Exception as e:
                        self.logger.error(f"❌ Error generating daily report: {e}")

                time.sleep(1)  # 1 second delay per iteration

            except KeyboardInterrupt:
                self.logger.info("🛑 Received interrupt signal - shutting down gracefully...")
                break
            except Exception as e:
                self.logger.error(f"❌ Error in main loop: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                time.sleep(5)  # Wait 5 seconds before continuing

        # Cleanup and save final state
        self._shutdown_gracefully()

    def _save_position_snapshot(self) -> None:
        """Save current position snapshot to database"""
        if not self.db_services:
            return

        try:
            for symbol, position in self.position_mgr.positions.items():
                position_data = {
                    'quantity': position['quantity'],
                    'avg_price': position['avg_price'],
                    'unrealized_pnl': position.get('unrealized_pnl', 0),
                    'realized_pnl': position.get('realized_pnl', 0),
                    'margin_used': 0,  # Calculate based on position value
                }

                self.db_services.db_manager.save_position(position_data, symbol, self.session_id)

        except Exception as e:
            self.logger.debug(f"⚠️ Could not save position snapshot: {e}")

    def _generate_daily_report(self, report_date: date) -> None:
        """Generate and save daily performance report"""
        if not self.db_services:
            return

        try:
            # Get today's trades
            today_trades = self.db_services.trades.get_trades_by_date_range(
                report_date, report_date, self.symbol
            )

            # Calculate metrics
            total_trades = len(today_trades)
            winning_trades = sum(1 for t in today_trades if t.pnl > 0)
            losing_trades = total_trades - winning_trades
            total_pnl = sum(t.pnl for t in today_trades)
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

            # Create performance metrics record
            metrics = PerformanceMetrics(
                date=report_date,
                symbol=self.symbol,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                total_return=total_pnl,
                total_return_percent=0,  # Would need initial balance
                win_rate=win_rate,
                sharpe_ratio=0,  # Would need more complex calculation
                max_drawdown=0,  # Would need position tracking
                max_drawdown_percent=0,
                profit_factor=0,  # Would need gross profit/loss calculation
                session_duration=0  # Would need session tracking
            )

            self.db_services.performance.save_performance_metrics(metrics)
            self.logger.info(f"💾 Daily report saved for {report_date}")

        except Exception as e:
            self.logger.error(f"❌ Error generating daily report: {e}")

    def _shutdown_gracefully(self) -> None:
        """Graceful shutdown with database cleanup"""
        self.logger.info("🛑 Shutting down gracefully...")

        try:
            # Save final state to database
            if self.db_services:
                # Save final balance
                today = date.today()
                final_balance_record = BalanceRecord(
                    date=today,
                    symbol=self.symbol,
                    initial_balance=self.session_start_balance,
                    final_balance=self.position_mgr.account_balance if self.position_mgr else 0,
                    day_pnl=self.session_realized_pnl,
                    day_pnl_percent=0,  # Calculate if needed
                    peak_balance=self.position_mgr.account_balance if self.position_mgr else 0,
                    min_balance=self.position_mgr.account_balance if self.position_mgr else 0
                )
                self.db_services.balance.save_daily_balance(final_balance_record)

                # Cleanup old data
                self.db_services.cleanup_old_data()

                # Create backup if configured
                backup_enabled = os.getenv('SQLITE_BACKUP_ENABLED', 'false').lower() == 'true'
                if backup_enabled:
                    self.db_services.backup_database()

            self.logger.info("✅ Shutdown completed successfully")

        except Exception as e:
            self.logger.error(f"❌ Error during shutdown: {e}")

    def signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals"""
        self.logger.info(f"🛑 Received signal {signum} - initiating shutdown...")
        self.running = False

# ============================================================================
# INTEGRATION NOTES
# ============================================================================
"""
This enhanced version integrates with the database tech stack:

1. DATABASE SERVICES:
   - Automatic initialization of SQLite and Redis
   - Persistent storage of trades, performance, and balance data
   - Daily reports and position snapshots

2. REDIS CACHING:
   - Price caching for improved performance
   - Session tracking and activity monitoring
   - Real-time data sharing between components

3. ENHANCED LOGGING:
   - Database logging for important events
   - Structured log storage for analysis
   - Automatic cleanup of old logs

4. BACKWARD COMPATIBILITY:
   - All existing functionality preserved
   - Database features are optional (graceful fallback)
   - Same interface and configuration options

Usage:
    bot = GridTradingBotV2()
    bot.run()

Configuration:
    - Use .env for basic settings
    - Use .env.database for database-specific settings
    - Redis configuration in environment variables
"""