"""
Pacifica Grid Trading Bot - Main System
Implements Grid Trading strategies (Pure Grid and Market Making)
"""

import os
import sys
import time
import signal
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Importar módulos do bot (assumindo que estão no mesmo diretório)
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

class GridTradingBot:
    def __init__(self):
        # Load configurations
        load_dotenv()
        
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
        
        # Set up logging
        self.setup_logging()
        
        # Create strategy-specific logger
        self.logger = create_strategy_logger('PacificaBot.Main', self.strategy_type)
        
        # Bot state
        self.running = False
        self.start_time = None
        
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
    
    def show_strategy_header(self):
        """Show strategy-specific header"""
        
        self.logger.info("=" * 80, force=True)
        self.logger.info("🤖 PACIFICA TRADING BOT", force=True)
        self.logger.info("=" * 80, force=True)
        
        if self.strategy_type == 'grid':
            grid_type = getattr(self, 'grid_type', 'market_making').upper()
            if grid_type == 'DYNAMIC_GRID':
                self.logger.info(f"Strategy: 🎯 DYNAMIC GRID TRADING", force=True)
                # Show Dynamic Grid specific settings
                threshold = os.getenv('DYNAMIC_THRESHOLD_PERCENT', '1.0')
                max_distance = os.getenv('MAX_ADJUSTMENT_DISTANCE_PERCENT', '5.0')
                self.logger.info(f"Adjustment Threshold: {threshold}%", force=True)
                self.logger.info(f"Maximum Distance: {max_distance}%", force=True)
            else:
                self.logger.info(f"Strategy: GRID TRADING ({grid_type})", force=True)
            self.logger.info(f"Symbol: {self.symbol}", force=True)
        elif self.strategy_type == 'multi_asset_enhanced':
            self.logger.info(f"Strategy: 🧠 ENHANCED MULTI-ASSET", force=True)
            symbols = os.getenv('SYMBOLS', 'BTC,ETH,SOL')
            quality = os.getenv('ENHANCED_MIN_SIGNAL_QUALITY', '65')
            confidence = os.getenv('ENHANCED_MIN_CONFIDENCE', '75')
            self.logger.info(f"Symbols: {symbols}", force=True)
            self.logger.info(f"Algorithm: Quality≥{quality}, Confidence≥{confidence}", force=True)
        else:  # multi_asset
            self.logger.info(f"Strategy: MULTI-ASSET SCALPING", force=True)
            symbols = os.getenv('SYMBOLS', 'BTC,ETH,SOL')
            self.logger.info(f"Symbols: {symbols}", force=True)
            
        self.logger.info(f"Rebalancing Interval: {self.rebalance_interval}s", force=True)
        
        # ✨ Show periodic reset configuration
        if self.enable_periodic_reset:
            reset_minutes = self.grid_reset_interval // 60
            self.logger.info(f"🔄 Periodic Reset: Every {reset_minutes} minutes", force=True)
        else:
            self.logger.info("🔄 Periodic Reset: Disabled", force=True)
            
        self.logger.info("=" * 80, force=True)
        
        # 🔧 VALIDATION SYSTEM (NEW)
        self._run_config_validations()
         
    def setup_logging(self):
        """Configure logging system"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"grid_bot_{timestamp}.log"
        
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
    
    def _run_config_validations(self):
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
    
    def _clean_old_orders(self):
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
                self.logger.info(f"⏳ Processing cancellations...")
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
        """Gets the current market price"""
        
        try:
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
    
    def run(self):
        """Main bot loop"""
        
        self.logger.info("🚀 Starting Grid Trading Bot...")
        
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
            
            self.logger.info(f"💰 Initial price {self.symbol}: ${current_price:,.2f}")
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
            self.logger.info(f"   Total Balance: ${self.position_mgr.account_balance:.2f}")
            self.logger.info(f"   Used Margin: ${self.position_mgr.margin_used:.2f}")
            self.logger.info(f"   Available Margin: ${self.position_mgr.margin_available:.2f}")
            
            if self.position_mgr.account_balance > 0:
                margin_percent = (self.position_mgr.margin_available / 
                                self.position_mgr.account_balance * 100)
                self.logger.info(f"   Free Margin: {margin_percent:.1f}%")
            
            self.logger.info("=" * 60)
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
                self.logger.warning(f"⚠️ Could not initialize Grid now (insufficient margin)")
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

               # ===== CHECK POSITION RISK (LEVEL 1) =====
                if self.risk_manager and self.strategy_type == 'grid':
                    should_close, reason = self.risk_manager.check_position_risk(self.symbol, current_price)
                    
                    if should_close:
                        self.logger.warning(f"🛑 Closing position due to: {reason}")
                        
                        # Close position
                        try:
                            position = self.position_mgr.positions.get(self.symbol, {})
                            quantity = position.get('quantity', 0)
                            
                            if quantity != 0:
                                # Determine closing order side
                                close_side = 'ask' if quantity > 0 else 'bid'
                                close_qty = abs(quantity)
                                
                                self.logger.info(f"📤 Creating closing order: {close_side} {close_qty} @ MARKET")
                                
                                # 🔥 ACTUAL CLOSING ORDER IMPLEMENTATION
                                try:
                                    # Create MARKET order to close position
                                    close_order = self.auth.create_order(
                                        symbol=self.symbol,
                                        side=close_side,
                                        amount=close_qty,
                                        price=current_price,
                                        order_type='IOC',
                                        reduce_only=True
                                    )
                                    
                                    if close_order and close_order.get('success'):
                                        self.logger.info(f"✅ Position closed successfully: {close_order.get('order_id')}")
                                        
                                        # Calculate realized PNL
                                        avg_price = position.get('avg_price', 0)
                                        pnl_usd = (current_price - avg_price) * quantity
                                        
                                        # Record cycle close
                                        self.risk_manager.record_cycle_close(self.symbol, pnl_usd, reason)
                                        
                                        # Cancel all grid orders
                                        self.logger.info("🚫 Canceling grid orders...")
                                        if hasattr(self.strategy, 'cancel_all_orders'):
                                            self.strategy.cancel_all_orders()
                                        
                                        # Wait for cancellations
                                        time.sleep(2)
                                        
                                        # Reset position
                                        self.position_mgr.positions[self.symbol] = {
                                            'quantity': 0,
                                            'avg_price': 0,
                                            'realized_pnl': position.get('realized_pnl', 0) + pnl_usd,
                                            'unrealized_pnl': 0
                                        }
                                        
                                        # Reset grid
                                        self.logger.info("♻️ Resetting grid...")
                                        self.risk_manager.reset_cycle()
                                        
                                        # Wait before recreating grid
                                        time.sleep(3)
                                        
                                        if self.strategy.initialize_grid(current_price):
                                            self.logger.info("✅ Grid reset successfully!")
                                        else:
                                            self.logger.warning("⚠️ Waiting for conditions to recreate grid...")
                                    else:
                                        error_msg = close_order.get('error', 'Unknown error') if close_order else 'No API response'
                                        self.logger.error(f"❌ Failed to create closing order: {error_msg}")
                                        
                                        # Try again in the next iteration
                                        self.logger.warning("⚠️ Will attempt to close position again in next check")
                                        
                                except Exception as order_error:
                                    self.logger.error(f"❌ Error executing closing order: {order_error}")
                                    import traceback
                                    self.logger.error(traceback.format_exc())
                                    
                                    # Notify via Telegram
                                    if self.telegram:
                                        try:
                                            self.telegram.send_error_alert(
                                                error_message=f"Failed to close position: {order_error}",
                                                traceback_info=traceback.format_exc()
                                            )
                                        except:
                                            pass
                                            
                        except Exception as e:
                            self.logger.error(f"❌ Error closing position: {e}")
                            import traceback
                            self.logger.error(traceback.format_exc())
                
                # ===== CHECK SESSION LIMITS (LEVEL 2) =====
                if self.risk_manager:
                    should_stop, reason = self.risk_manager.check_session_limits()
                    
                    if should_stop:
                        self.logger.error(f"🚨 SESSION LIMIT REACHED: {reason}")
                        
                        # Close position if it exists
                        position = self.position_mgr.positions.get(self.symbol, {})
                        if position.get('quantity', 0) != 0:
                            self.logger.warning("🛑 Closing position due to session limit...")
                            # Implement closing logic here
                        
                        # Cancel all orders
                        if hasattr(self.strategy, 'cancel_all_orders'):
                            self.strategy.cancel_all_orders()
                        
                        # Check configured action
                        action = self.risk_manager.get_action_on_limit()
                        
                        if action == 'shutdown':
                            self.logger.error("🛑 Stopping bot due to session limit...")
                            self.running = False
                            break
                        # If 'pause', the bot was already paused by risk_manager 
                
                # Strategy-specific heartbeat log
                if iteration % 10 == 0:
                    uptime = datetime.now() - self.start_time
                    if self.strategy_type == 'grid':
                        self.logger.info(f"💓 Heartbeat #{iteration} - Uptime: {uptime} | Price: ${current_price:,.2f}", force=True)
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
                    else:
                        # Margin OK - debug log only
                        self.logger.debug(f"✅ {msg}")
                
                # Check filled orders every 10 seconds
                if iteration % 10 == 0:
                    self.logger.debug(f"🔍 Checking filled orders...")
                    self.strategy.check_filled_orders(current_price)

                # Check stop conditions
                # should_stop, reason = self.position_mgr.should_stop_trading()
                # if should_stop:
                #     self.logger.error(f"🛑 Stopping trading: {reason}")
                #     self.stop()
                #     break
                
                # Rebalance strategy if needed
                if current_time - last_rebalance >= self.rebalance_interval:
                    
                    # Check margin BEFORE rebalancing
                    self.position_mgr.update_account_state()
                    
                    if self.position_mgr.account_balance > 0:
                        margin_percent = (self.position_mgr.margin_available / 
                                        self.position_mgr.account_balance * 100)
                        
                        if margin_percent < 20:
                            self.logger.warning(f"⚠️ Low margin ({margin_percent:.1f}%) - skipping rebalance")
                            
                            # Check safety measures
                            is_safe, msg = self.position_mgr.check_margin_safety()
                            if not is_safe:
                                self.logger.warning(f"🔧 {msg}")
                            
                            last_rebalance = current_time  # Update timer
                            continue  # Skip to next iteration
                    
                    if self.strategy_type == 'grid':
                        self.logger.info(f"🔄 Checking rebalance at ${current_price:,.2f}")
                        if self.risk_manager and iteration % 30 == 0:  # Every 30 iterations
                            self.risk_manager.log_periodic_status()
                    else:
                        self.logger.info("🔄 Checking Multi-Asset signals")
                    
                    try:
                        self.strategy.check_and_rebalance(current_price)
                        
                        # 🆕 If no active orders, try to recreate grid
                        grid_status = self.strategy.get_grid_status()
                        if grid_status['active_orders'] == 0:
                            self.logger.info("🔄 No active orders - attempting to recreate grid...")
                            if self.strategy.initialize_grid(current_price):
                                self.logger.info("✅ Grid recreated successfully!")
                            else:
                                self.logger.info("⚠️ Still not enough margin - continuing monitoring...")
                        
                    except Exception as e:
                        self.logger.warning(f"⚠️ Rebalancing error: {e}")
                        # Don't stop the bot - just continue
                    last_rebalance = current_time 
                
                # ✨ NEW FEATURE: Periodic grid reset
                if (self.enable_periodic_reset and 
                    self.strategy_type == 'grid' and 
                    current_time - last_grid_reset >= self.grid_reset_interval):
                    
                    try:
                        reset_minutes = self.grid_reset_interval // 60
                        self.logger.info(f"🔄🔥 PERIODIC RESET: Rebuilding complete grid after {reset_minutes} minutes")
                        
                        # Perform complete grid reset
                        if hasattr(self.strategy, 'reset_grid_completely'):
                            success = self.strategy.reset_grid_completely(current_price)
                            if success:
                                self.logger.info("✅ Grid reset and recreated successfully!")
                            else:
                                self.logger.warning("⚠️ Reset failed - keeping current grid")
                        else:
                            # Fallback: use traditional method
                            self.logger.info("🔄 Using traditional reset method...")
                            self.strategy.cancel_all_orders()
                            time.sleep(2)  # Wait for cancellations
                            if self.strategy.initialize_grid(current_price):
                                self.logger.info("✅ Grid reset and recreated successfully!")
                            else:
                                self.logger.warning("⚠️ Reset failed - will try again next cycle")
                        
                    except Exception as e:
                        self.logger.error(f"❌ Error in periodic reset: {e}")
                        # Continue normal operation even if reset fails
                    
                    last_grid_reset = current_time 
                        
                # Periodic status
                if iteration % 60 == 0:  # 🔧 Every 60 iterations (1 minute)
                    self.print_status()

                # Detailed report every 10 minutes
                if iteration % 600 == 0:
                    self.print_detailed_performance()
                
                # Wait for next iteration
                time.sleep(1)

            except KeyboardInterrupt:
                self.logger.info("🛑 Keyboard interrupt")
                break  # Exit while loop

            except Exception as e:
                self.logger.error(f"❌ Error in main loop: {e}")
                import traceback
                traceback_str = traceback.format_exc()
                self.logger.error(traceback_str)

                # Notify error via Telegram (with protection)
                try:
                    if hasattr(self, 'telegram') and self.telegram:
                        self.telegram.send_error_alert(
                            error_message=str(e),
                            traceback_info=traceback_str
                        )
                except Exception as telegram_error:
                    self.logger.warning(f"⚠️ Failed to send error via Telegram: {telegram_error}")
                
                # Wait before continuing
                time.sleep(5)

        # FINAL CLEANUP (outside while loop)
        try:
            if hasattr(self, 'risk_manager') and self.risk_manager:
                self.risk_manager.close_session()
        except Exception as rm_error:
            self.logger.warning(f"⚠️ Error closing risk manager: {rm_error}")
        
        self.logger.info("🏁 Stopping bot...")
        
        # Protected shutdown
        try:
            self.shutdown()
        except Exception as shutdown_error:
            self.logger.error(f"❌ Error during shutdown: {shutdown_error}")
            # Try manual shutdown of critical components
            self.running = False
    
    def print_status(self):
        """Print current bot status with advanced metrics"""
        
        self.logger.info("=" * 80)
        self.logger.info("📊 BOT STATUS")
        self.logger.info("=" * 80)
        
        # Grid/strategy status
        grid_status = self.strategy.get_grid_status()
        strategy_name = "Multi-Asset" if self.strategy_type == 'multi_asset' else "Grid"
        self.logger.info(f"{strategy_name} Active: {grid_status['active']}")
        
        if self.strategy_type == 'grid':
            self.logger.info(f"Center Price: ${grid_status['center_price']:,.2f}")
            self.logger.info(f"Active Orders: {grid_status['active_orders']}")
        else:
            self.logger.info(f"Active Positions: {grid_status['active_orders']}")  # For multi-asset, these are positions
        
        # 🆕 ADD: Performance metrics
        try:
            performance_metrics = self.strategy.get_performance_metrics()
            
            self.logger.info("💹 PERFORMANCE:")
            self.logger.info(f"  Total Trades: {performance_metrics.get('total_trades', 0)}")
            self.logger.info(f"  Win Rate: {performance_metrics.get('win_rate', 0):.1f}%")
            self.logger.info(f"  Total Return: ${performance_metrics.get('total_return', 0):.2f}")
            self.logger.info(f"  Sharpe Ratio: {performance_metrics.get('sharpe_ratio', 0):.2f}")
            self.logger.info(f"  Max Drawdown: {performance_metrics.get('max_drawdown_percent', 0):.1f}%")
            
            self.logger.info("🔧 ADAPTIVE GRID:")
            self.logger.info(f"  Mode: {'ACTIVE' if performance_metrics.get('adaptive_mode') else 'INACTIVE'}")
            self.logger.info(f"  Volatility: {performance_metrics.get('current_volatility', 0):.4f}")
            self.logger.info(f"  Current Spacing: {performance_metrics.get('current_spacing', 0):.3f}%")
            self.logger.info(f"  Grid Efficiency: {performance_metrics.get('grid_efficiency', 0):.1f}%")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error getting metrics: {e}")
        
        # Position status (keep existing code if desired)
        # pos_status = self.position_mgr.get_status_summary()
        # self.logger.info(f"Balance: ${pos_status['account_balance']:,.2f}")
        
        self.logger.info("=" * 80)
    
    def print_detailed_performance(self):
        """Print detailed performance report"""
        
        if self.strategy and hasattr(self.strategy, 'performance_tracker'):
            self.strategy.print_performance_summary()
            
            # 🆕 ENHANCED VERSION SPECIFIC STATISTICS
            if self.strategy_type == 'multi_asset_enhanced' and hasattr(self.strategy, 'get_enhanced_statistics'):
                self.strategy.log_performance_summary()
                
        else:
            self.logger.warning("⚠️ Performance tracker not available")
    
    def shutdown(self):
        """Shut down the bot gracefully"""
        
        self.logger.info("🔄 Starting shutdown...")
        
        # Cancel all open orders
        if self.position_mgr:
            self.logger.info("🚫 Canceling all open orders...")
            try:
                # Get all open orders
                open_orders = self.auth.get_open_orders()
                if open_orders:
                    # Filter orders for our symbol
                    symbol_orders = [o for o in open_orders if o.get('symbol') == self.symbol]
                    if symbol_orders:
                        self.logger.info(f"🔍 Found {len(symbol_orders)} open orders for {self.symbol}")
                        self._clean_old_orders()  # Use the existing method to cancel orders
                    else:
                        self.logger.info(f"ℹ️ No open orders found for {self.symbol}")
                else:
                    self.logger.info("ℹ️ No open orders found in the account")
            except Exception as e:
                self.logger.error(f"❌ Error canceling orders during shutdown: {e}")
                import traceback
                self.logger.debug(f"Stack trace: {traceback.format_exc()}")
        
        # Print final report
        if self.start_time:
            uptime = datetime.now() - self.start_time
            self.logger.info(f"⏱️ Uptime: {uptime}")
        
        # Print final balance
        if self.position_mgr:
            try:
                if self.position_mgr.update_account_state():
                    self.logger.info("=" * 60)
                    self.logger.info("💰 FINAL ACCOUNT STATUS:")
                    self.logger.info(f"   Total Balance: ${self.position_mgr.account_balance:,.2f}")
                    self.logger.info(f"   Used Margin: ${self.position_mgr.margin_used:,.2f}")
                    self.logger.info(f"   Available Margin: ${self.position_mgr.margin_available:,.2f}")
                    
                    if hasattr(self.position_mgr, 'get_open_positions'):
                        positions = self.position_mgr.get_open_positions()
                        if positions:
                            self.logger.info("\n📊 OPEN POSITIONS:")
                            for pos in positions:
                                pnl = pos.get('unrealized_pnl', 0)
                                self.logger.info(f"   {pos.get('symbol')}: {pos.get('size', 0):.4f} @ ${pos.get('entry_price', 0):.2f} | PnL: ${pnl:,.2f}")
            except Exception as e:
                self.logger.error(f"❌ Error getting final account status: {e}")
        
        self.logger.info("=" * 80)
        self.logger.info("✅ Bot stopped successfully")
        self.logger.info("=" * 80)
    
    def stop(self):
        """Stop the bot"""
        self.running = False
    
    def signal_handler(self, signum, frame):
        """Handler for system signals"""
        self.logger.info(f"🛑 Signal received: {signum}")
        self.stop()


def main():
    """Main function"""
    
    print("=" * 80)
    print("🤖 PACIFICA GRID TRADING BOT")
    print("=" * 80)
    print()
    
    # Check for .env file
    if not Path('.env').exists():
        print("❌ .env file not found!")
        print("📝 Please create a .env file with the required configurations")
        return
    
    # Create and run bot
    bot = GridTradingBot()
    
    try:
        bot.run()
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()