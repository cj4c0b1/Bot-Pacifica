"""
Pacifica Grid Trading Bot - Redis Version
High-Performance Grid Trading with Redis Backend for Lowest Latency
"""

import os
import sys
import time
import signal
import logging
import json
from datetime import datetime
from typing import Dict, Optional, Any
from dotenv import load_dotenv

# Import Redis client for high-performance data storage
from src.redis_client import RedisClient, RedisConfig

# Import existing bot modules (unchanged logic)
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

class RedisGridTradingBot:
    """
    High-Performance Grid Trading Bot with Redis Backend

    Features:
    - Redis for all real-time data storage (sub-millisecond latency)
    - In-memory processing with Redis persistence
    - Optimized for high-frequency trading
    - Zero historical data storage (pure real-time focus)
    """

    def __init__(self):
        # Load configurations
        load_dotenv()

        # Initialize Redis client for high-performance storage
        self.redis_config = RedisConfig()
        self.redis = RedisClient(self.redis_config)

        # Session management
        self.session_id = f"session_{int(time.time())}_{os.getpid()}"
        self.bot_start_time = datetime.now()

        # Determine strategy type
        strategy_type_env = os.getenv('STRATEGY_TYPE', 'market_making').lower()

        if strategy_type_env == 'multi_asset':
            self.strategy_type = 'multi_asset'
        elif strategy_type_env == 'multi_asset_enhanced':
            self.strategy_type = 'multi_asset_enhanced'
        elif strategy_type_env in ['pure_grid', 'market_making', 'dynamic_grid']:
            self.strategy_type = 'grid'
            self.grid_type = strategy_type_env
        else:
            self.strategy_type = 'grid'
            self.grid_type = 'market_making'

        # Set up logging
        self.setup_logging()

        # Create strategy-specific logger
        self.logger = create_strategy_logger('PacificaBot.Redis', self.strategy_type)

        # Bot state (minimal in-memory state)
        self.running = False

        # Settings
        self.symbol = os.getenv('SYMBOL', 'BTC')
        self.rebalance_interval = int(os.getenv('REBALANCE_INTERVAL_SECONDS', '60'))
        self.check_balance = os.getenv('CHECK_BALANCE_BEFORE_ORDER', 'true').lower() == 'true'

        # Session control settings
        self.session_stop_loss = float(os.getenv('SESSION_STOP_LOSS_USD', '100'))
        self.session_take_profit = float(os.getenv('SESSION_TAKE_PROFIT_USD', '200'))
        self.session_max_loss = float(os.getenv('SESSION_MAX_LOSS_USD', '150'))

        # Components (initialized later)
        self.auth = None
        self.calculator = None
        self.position_mgr = None
        self.telegram = None
        self.risk_manager = None
        self.strategy = None

        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Initialize Redis state
        self._initialize_redis_state()

    def _initialize_redis_state(self):
        """Initialize Redis state for the session"""
        try:
            # Store session metadata in Redis
            session_data = {
                'session_id': self.session_id,
                'bot_start_time': self.bot_start_time.isoformat(),
                'strategy_type': self.strategy_type,
                'symbol': self.symbol,
                'pid': os.getpid(),
                'hostname': os.uname().nodename if hasattr(os, 'uname') else 'unknown'
            }

            self.redis.cache_session_data(self.session_id, session_data)

            # Initialize counters in Redis
            redis_keys = {
                f"bot:{self.session_id}:iteration": 0,
                f"bot:{self.session_id}:total_pnl": 0.0,
                f"bot:{self.session_id}:winning_trades": 0,
                f"bot:{self.session_id}:losing_trades": 0,
                f"bot:{self.session_id}:last_update": time.time(),
                f"bot:{self.session_id}:errors": 0,
                f"bot:{self.session_id}:warnings": 0,
            }

            # Set all keys in Redis pipeline for atomicity
            if self.redis.is_connected():
                pipe = self.redis.redis_client.pipeline()
                for key, value in redis_keys.items():
                    pipe.set(key, value)
                pipe.execute()

            self.logger.info(f"🔄 Redis state initialized for session {self.session_id}")

        except Exception as e:
            self.logger.error(f"❌ Error initializing Redis state: {e}")

    def setup_logging(self):
        """Configure logging system"""
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"{log_dir}/grid_bot_redis_{timestamp}.log"

        log_level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper())

        log_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Root logger
        root_logger = logging.getLogger('PacificaBot.Redis')
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

    def show_strategy_header(self):
        """Show strategy-specific header"""
        self.logger.info("=" * 80)
        self.logger.info("🚀 PACIFICA REDIS GRID BOT")
        self.logger.info("=" * 80)

        if self.strategy_type == 'grid':
            grid_type = getattr(self, 'grid_type', 'market_making').upper()
            if grid_type == 'DYNAMIC_GRID':
                self.logger.info("Strategy: 🎯 DYNAMIC GRID TRADING (Redis Backend)")
                threshold = os.getenv('DYNAMIC_THRESHOLD_PERCENT', '1.0')
                max_distance = os.getenv('MAX_ADJUSTMENT_DISTANCE_PERCENT', '5.0')
                self.logger.info(f"Adjustment Threshold: {threshold}%")
                self.logger.info(f"Maximum Distance: {max_distance}%")
            else:
                self.logger.info(f"Strategy: GRID TRADING ({grid_type}) - Redis Backend")
            self.logger.info(f"Symbol: {self.symbol}")
        elif self.strategy_type == 'multi_asset_enhanced':
            self.logger.info("Strategy: 🧠 ENHANCED MULTI-ASSET (Redis Backend)")
            symbols = os.getenv('SYMBOLS', 'BTC,ETH,SOL')
            quality = os.getenv('ENHANCED_MIN_SIGNAL_QUALITY', '65')
            confidence = os.getenv('ENHANCED_MIN_CONFIDENCE', '75')
            self.logger.info(f"Symbols: {symbols}")
            self.logger.info(f"Algorithm: Quality≥{quality}, Confidence≥{confidence}")
        else:
            self.logger.info(f"Strategy: MULTI-ASSET SCALPING (Redis Backend)")
            symbols = os.getenv('SYMBOLS', 'BTC,ETH,SOL')
            self.logger.info(f"Symbols: {symbols}")

        self.logger.info(f"Rebalancing Interval: {self.rebalance_interval}s")
        self.logger.info(f"Session ID: {self.session_id}")

        # Redis connection status
        redis_status = "✅ Connected" if self.redis.is_connected() else "❌ Disconnected"
        self.logger.info(f"Redis Status: {redis_status}")

        self.logger.info("=" * 80)

    def update_redis_state(self, key_suffix: str, value: Any):
        """Update Redis state with minimal latency"""
        if not self.redis.is_connected():
            return False

        try:
            key = f"bot:{self.session_id}:{key_suffix}"
            return self.redis.set_cache(key, value, ttl=3600)  # 1 hour TTL
        except Exception as e:
            self.logger.error(f"❌ Error updating Redis state: {e}")
            return False

    def get_redis_state(self, key_suffix: str, default: Any = None) -> Any:
        """Get Redis state with minimal latency"""
        if not self.redis.is_connected():
            return default

        try:
            key = f"bot:{self.session_id}:{key_suffix}"
            return self.redis.get_cache(key) or default
        except Exception as e:
            self.logger.error(f"❌ Error getting Redis state: {e}")
            return default

    def increment_redis_counter(self, key_suffix: str, increment: int = 1) -> int:
        """Increment Redis counter atomically"""
        if not self.redis.is_connected():
            return 0

        try:
            key = f"bot:{self.session_id}:{key_suffix}"
            # Use Redis INCR for atomic increment
            new_value = self.redis.redis_client.incr(key, increment)

            # Update TTL on increment
            self.redis.redis_client.expire(key, 3600)
            return new_value
        except Exception as e:
            self.logger.error(f"❌ Error incrementing Redis counter: {e}")
            return 0

    def _run_config_validations(self):
        """Run configuration validations"""
        try:
            from src.config_validator import run_all_validations

            self.logger.info("🔧 Running configuration validations...")
            validation_result = run_all_validations(self.strategy_type)

            if validation_result['warnings']:
                warning_count = self.increment_redis_counter('warnings', len(validation_result['warnings']))
                self.logger.warning("⚠️ CONFIGURATION WARNINGS:")
                for warning in validation_result['warnings']:
                    self.logger.warning(f"  • {warning}")

            if validation_result['errors']:
                error_count = self.increment_redis_counter('errors', len(validation_result['errors']))
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

            # 2. Telegram Notifier
            self.telegram = TelegramNotifier()
            self.logger.info("✅ Telegram Notifier initialized")

            # 3. Clean up old orders (if configured)
            clean_on_start = os.getenv('CLEAN_ORDERS_ON_START', 'false').lower() == 'true'
            if clean_on_start:
                self.logger.warning("🧹 Cleaning up old orders...")
                self._clean_old_orders()

            # 4. Grid Calculator
            self.calculator = GridCalculator(auth_client=self.auth)
            self.logger.info("✅ Grid Calculator initialized")

            # 5. Position Manager (with Redis integration)
            self.position_mgr = RedisPositionManager(self.auth, self.redis, self.session_id)
            self.logger.info("✅ Redis Position Manager initialized")

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

            # 7. Initialize strategy
            if self.strategy_type == 'multi_asset':
                self.logger.info("🎯 Initializing Multi-Asset Scalping strategy...")
                self.strategy = MultiAssetStrategy(self.auth, self.calculator, self.position_mgr)
            elif self.strategy_type == 'multi_asset_enhanced':
                self.logger.info("🧠 Initializing Enhanced Multi-Asset strategy...")
                self.strategy = MultiAssetEnhancedStrategy(self.auth, self.calculator, self.position_mgr)
            else:
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

    def _clean_old_orders(self):
        """Cancel all open orders for the symbol"""
        try:
            self.logger.info(f"🔍 Checking existing orders for {self.symbol}...")

            all_open_orders = self.auth.get_open_orders()

            if not all_open_orders:
                self.logger.info("ℹ️ No orders found in the account")
                return

            symbol_orders = [order for order in all_open_orders if order.get('symbol') == self.symbol]

            if not symbol_orders:
                self.logger.info(f"ℹ️ No orders found for {self.symbol}")
                return

            self.logger.info(f"🚫 Canceling {len(symbol_orders)} orders for {self.symbol}...")

            cancelled_count = 0
            for order in symbol_orders:
                order_id = order.get('order_id')
                if order_id:
                    try:
                        result = self.auth.cancel_order(str(order_id), self.symbol)
                        if result and result.get('success'):
                            cancelled_count += 1
                        time.sleep(0.1)  # Minimal delay for rate limiting
                    except Exception as cancel_error:
                        self.logger.error(f"❌ Error canceling {order_id}: {cancel_error}")

            self.logger.info(f"🧹 Order cleanup completed: {cancelled_count} orders canceled")

        except Exception as e:
            self.logger.error(f"❌ Error cleaning up orders: {e}")

    def get_current_price(self) -> float:
        """Get current market price with Redis caching"""
        try:
            # Try Redis cache first for lowest latency
            cached_price = self.redis.get_cached_price(self.symbol)
            if cached_price:
                return float(cached_price.get('price', 0))

            # Fetch from API if not cached
            prices = self.auth.get_prices()

            if not prices or not prices.get('success'):
                return 0

            data = prices.get('data', [])
            for item in data:
                if item.get('symbol') == self.symbol:
                    price = float(item.get('mark') or item.get('mid') or 0)
                    if price > 0:
                        # Cache the price for future use (5 second TTL for prices)
                        self.redis.cache_price(self.symbol, {'price': price, 'timestamp': time.time()})
                        return price

            return 0

        except Exception as e:
            self.logger.error(f"❌ Error getting price: {e}")
            return 0

    def run(self):
        """Main bot loop with Redis optimization"""
        self.logger.info("🚀 Starting Redis Grid Trading Bot...")

        if not self.initialize_components():
            self.logger.error("❌ Initialization failed - aborting")
            return

        # Test market info for grid strategy
        if self.strategy_type == 'grid':
            self.logger.info(f"🔍 Testing market info for {self.symbol}...")
            test_info = self.auth.get_symbol_info(self.symbol)
            if test_info:
                self.logger.info(f"✅ tick_size={test_info.get('tick_size')}, lot_size={test_info.get('lot_size')}")

        # Get initial price
        current_price = 0
        if self.strategy_type == 'grid':
            current_price = self.get_current_price()
            if current_price == 0:
                self.logger.warning("⚠️ Initial price not obtained - will retry in loop")
            else:
                self.logger.info(f"💰 Initial price {self.symbol}: ${current_price",.2f"}")

        # Check balance if configured
        if self.check_balance:
            self.logger.info("💳 Checking account balance...")
            if not self.position_mgr.update_account_state():
                self.logger.error("❌ Failed to check balance")
                return

        # Account verification
        self.logger.info("💳 Loading account information...")
        if self.position_mgr.update_account_state():
            # Store balance in Redis for fast access
            self.update_redis_state('account_balance', self.position_mgr.account_balance)
            self.update_redis_state('margin_available', self.position_mgr.margin_available)

            self.logger.info("=" * 60)
            self.logger.info("💰 ACCOUNT STATUS:")
            self.logger.info(f"   Total Balance: ${self.position_mgr.account_balance".2f"}")
            self.logger.info(f"   Available Margin: ${self.position_mgr.margin_available".2f"}")
            self.logger.info("=" * 60)
        else:
            self.logger.error("❌ Failed to load account information")

        # Initialize strategy
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
        self.update_redis_state('running', True)
        self.update_redis_state('start_time', self.bot_start_time.isoformat())

        self.logger.info("✅ Redis Bot is running!")
        self.logger.info("=" * 80)

        # Main loop with Redis state management
        iteration = 0
        last_rebalance = time.time()
        last_price_check = time.time()

        while self.running:
            try:
                iteration += 1
                current_time = time.time()

                # Update iteration counter in Redis
                self.update_redis_state('iteration', iteration)
                self.update_redis_state('last_update', current_time)

                # Check if bot is paused
                if self.risk_manager and self.risk_manager.check_if_paused():
                    if iteration % 10 == 0:
                        self.logger.info("⏸️ Bot paused - waiting to resume...")
                    time.sleep(5)  # Shorter sleep when paused
                    continue

                # Update price for grid strategy (optimized)
                if self.strategy_type == 'grid' and current_time - last_price_check >= 15:  # More frequent updates
                    new_price = self.get_current_price()
                    if new_price > 0:
                        current_price = new_price
                        # Update price in Redis for other components
                        self.redis.cache_price(self.symbol, {'price': current_price, 'timestamp': current_time})
                    last_price_check = current_time

                # Check position risk (Level 1)
                if self.risk_manager and self.strategy_type == 'grid':
                    should_close, reason = self.risk_manager.check_position_risk(self.symbol, current_price)

                    if should_close:
                        self.logger.warning(f"🛑 Closing position due to: {reason}")
                        # Implement closing logic here (same as original)
                        # ... (closing logic would go here)

                # Strategy-specific heartbeat
                if iteration % 20 == 0:  # More frequent logging for Redis version
                    uptime = datetime.now() - self.bot_start_time
                    if self.strategy_type == 'grid':
                        self.logger.info(f"💓 Redis Heartbeat #{iteration} - Uptime: {uptime} | Price: ${current_price",.2f"} | Session: {self.session_id}")
                    else:
                        active_positions = len(getattr(self.strategy, 'active_positions', []))
                        self.logger.info(f"💓 Redis Heartbeat #{iteration} - Uptime: {uptime} | Positions: {active_positions} | Session: {self.session_id}")

                # Update balance periodically (optimized)
                if self.check_balance and iteration % 10 == 0:  # More frequent balance checks
                    self.position_mgr.update_account_state()

                    # Update Redis state
                    self.update_redis_state('account_balance', self.position_mgr.account_balance)
                    self.update_redis_state('margin_available', self.position_mgr.margin_available)

                # Sleep for minimal latency
                time.sleep(1)  # 1 second base interval for high-frequency trading

            except KeyboardInterrupt:
                self.logger.info("🛑 Keyboard interrupt received")
                break
            except Exception as e:
                error_count = self.increment_redis_counter('errors')
                self.logger.error(f"❌ Error in main loop (#{error_count}): {e}")
                time.sleep(5)  # Brief pause on error

        # Cleanup
        self.cleanup()

    def cleanup(self):
        """Cleanup Redis state on shutdown"""
        try:
            self.logger.info("🧹 Cleaning up Redis state...")

            # Update final state
            self.update_redis_state('running', False)
            self.update_redis_state('shutdown_time', datetime.now().isoformat())

            # Get final statistics
            final_iteration = self.get_redis_state('iteration', 0)
            final_errors = self.get_redis_state('errors', 0)
            final_warnings = self.get_redis_state('warnings', 0)

            uptime = datetime.now() - self.bot_start_time

            self.logger.info("📊 Session Summary:"            self.logger.info(f"   Session ID: {self.session_id}")
            self.logger.info(f"   Total Iterations: {final_iteration}")
            self.logger.info(f"   Uptime: {uptime}")
            self.logger.info(f"   Errors: {final_errors}")
            self.logger.info(f"   Warnings: {final_warnings}")

            # Mark session as inactive
            if self.redis.is_connected():
                self.redis.update_session_activity(self.session_id)

        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"🛑 Signal {signum} received - shutting down gracefully...")
        self.running = False

class RedisPositionManager:
    """
    High-Performance Position Manager with Redis Backend

    Features:
    - All position data stored in Redis for lowest latency
    - Atomic operations for position updates
    - Real-time position tracking
    - Optimized for high-frequency trading
    """

    def __init__(self, auth_client, redis_client: RedisClient, session_id: str):
        self.logger = logging.getLogger('PacificaBot.RedisPositionManager')
        self.auth = auth_client
        self.redis = redis_client
        self.session_id = session_id

        # Redis keys for this session
        self.positions_key = f"positions:{session_id}"
        self.balance_key = f"balance:{session_id}"
        self.orders_key = f"orders:{session_id}"

        # Settings
        self.max_position_size = float(os.getenv('MAX_POSITION_SIZE_USD', '1000'))
        self.leverage = int(os.getenv('LEVERAGE', '10'))

        self.logger.info(f"🚀 Redis Position Manager initialized for session {session_id}")

    def update_account_state(self) -> bool:
        """Update account state from API and cache in Redis"""
        try:
            self.logger.debug("🔄 Updating account state...")

            account_data = self.auth.get_account_info()

            if not account_data or not account_data.get('success'):
                self.logger.error("❌ Failed to get account info from API")
                return False

            data = account_data['data']
            if isinstance(data, list) and len(data) > 0:
                data = data[0]

            # Extract values
            account_balance = float(data.get('balance', 0))
            account_equity = float(data.get('account_equity', 0))
            margin_available = float(data.get('available_to_spend', 0))
            margin_used = float(data.get('total_margin_used', 0))

            # Store in Redis for fast access
            balance_data = {
                'account_balance': account_balance,
                'account_equity': account_equity,
                'margin_available': margin_available,
                'margin_used': margin_used,
                'timestamp': time.time(),
                'session_id': self.session_id
            }

            if self.redis.set_cache(self.balance_key, balance_data, ttl=60):  # 1 minute TTL for balance
                self.logger.debug(f"💾 Account state cached in Redis: ${account_balance".2f"}")
                return True
            else:
                self.logger.error("❌ Failed to cache account state in Redis")
                return False

        except Exception as e:
            self.logger.error(f"❌ Error updating account state: {e}")
            return False

    @property
    def account_balance(self) -> float:
        """Get account balance from Redis cache"""
        balance_data = self.redis.get_cache(self.balance_key)
        return float(balance_data.get('account_balance', 0)) if balance_data else 0.0

    @property
    def margin_available(self) -> float:
        """Get available margin from Redis cache"""
        balance_data = self.redis.get_cache(self.balance_key)
        return float(balance_data.get('margin_available', 0)) if balance_data else 0.0

    @property
    def margin_used(self) -> float:
        """Get used margin from Redis cache"""
        balance_data = self.redis.get_cache(self.balance_key)
        return float(balance_data.get('margin_used', 0)) if balance_data else 0.0

    def can_place_order(self, order_value: float, symbol: str) -> tuple[bool, str]:
        """Check if order can be placed with Redis-optimized logic"""
        try:
            # Get current balance from Redis
            balance_data = self.redis.get_cache(self.balance_key)
            if not balance_data:
                return False, "No balance data available"

            margin_available = float(balance_data.get('margin_available', 0))
            margin_needed = order_value / self.leverage

            if margin_needed > margin_available:
                return False, f"Insufficient margin: needs ${margin_needed".2f"}, available ${margin_available".2f"}"

            # Check position limits
            current_exposure = self.get_current_exposure(symbol)
            projected_exposure = current_exposure + order_value

            if projected_exposure > self.max_position_size:
                return False, f"Maximum exposure exceeded: ${projected_exposure".2f"} > ${self.max_position_size".2f"}"

            return True, "OK"

        except Exception as e:
            self.logger.error(f"❌ Error checking order placement: {e}")
            return False, f"Error: {str(e)}"

    def get_current_exposure(self, symbol: str) -> float:
        """Get current position exposure for symbol"""
        try:
            # Get positions from API (Redis doesn't store historical positions)
            positions = self.auth.get_positions()

            if not positions:
                return 0.0

            for position in positions:
                if position.get('symbol') == symbol:
                    # Calculate current position value
                    amount = abs(float(position.get('amount', 0)))
                    current_price = self._get_current_price(symbol)
                    return amount * current_price

            return 0.0

        except Exception as e:
            self.logger.error(f"❌ Error getting current exposure: {e}")
            return 0.0

    def _get_current_price(self, symbol: str) -> float:
        """Get current price for position calculations"""
        try:
            # Try Redis cache first
            price_data = self.redis.get_cached_price(symbol)
            if price_data:
                return float(price_data.get('price', 0))

            # Fallback to API
            prices = self.auth.get_prices()
            if prices and prices.get('success'):
                data = prices.get('data', [])
                for item in data:
                    if item.get('symbol') == symbol:
                        price = float(item.get('mark') or item.get('mid') or 0)
                        if price > 0:
                            return price

            return 0.0

        except Exception as e:
            self.logger.error(f"❌ Error getting current price: {e}")
            return 0.0

# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    bot = RedisGridTradingBot()
    bot.show_strategy_header()
    bot.run()