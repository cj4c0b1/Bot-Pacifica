"""
Position Manager - Position, Margin, and Risk Management
"""

import os
import time
import logging
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta

class PositionManager:
    def __init__(self, auth_client):
        self.logger = logging.getLogger('PacificaBot.PositionManager')
        self.auth = auth_client

        # ========== SYSTEM 1: Order Cancellation ==========
        self.auto_cancel_orders = os.getenv('AUTO_CANCEL_ORDERS_ON_LOW_MARGIN', 'true').lower() == 'true'
        self.cancel_orders_threshold = float(os.getenv('CANCEL_ORDERS_MARGIN_THRESHOLD', '20'))
        self.cancel_orders_percentage = float(os.getenv('CANCEL_ORDERS_PERCENTAGE', '30'))
        
        # ========== SYSTEM 2: Position Reduction (NEW) ==========
        self.auto_reduce_position = os.getenv('AUTO_REDUCE_POSITION_ON_LOW_MARGIN', 'true').lower() == 'true'
        self.reduce_position_threshold = float(os.getenv('REDUCE_POSITION_MARGIN_THRESHOLD', '10'))
        self.reduce_position_percentage = float(os.getenv('REDUCE_POSITION_PERCENTAGE', '20'))
        
        # Log settings
        if self.auto_cancel_orders:
            self.logger.info(f"🔧 Auto-cancel orders ENABLED: margin < {self.cancel_orders_threshold}%")
        
        if self.auto_reduce_position:
            self.logger.info(f"🔧 Auto-reduce position ENABLED: margin < {self.reduce_position_threshold}%")
        
        self.max_position_size = float(os.getenv('MAX_POSITION_SIZE_USD', '1000'))
        self.max_open_orders = int(os.getenv('MAX_OPEN_ORDERS', '20'))
        self.leverage = int(os.getenv('LEVERAGE', '10'))
        
        # 🆕 Auto-Close Settings
        self.auto_close_on_limit = os.getenv('AUTO_CLOSE_ON_MAX_POSITION', 'true').lower() == 'true'
        # Strategies: cancel_distant_orders, force_partial_sell, stop_buy_orders, hybrid
        self.auto_close_strategy = os.getenv('AUTO_CLOSE_STRATEGY', 'hybrid')  
        self.auto_close_percentage = float(os.getenv('AUTO_CLOSE_PERCENTAGE', '20'))  # Percentage of position to close
        
        # Internal state
        self.open_orders = {}  # {order_id: order_data}
        self.positions = {}    # {symbol: position_data}
        self.account_balance = 0
        self.margin_used = 0
        self.margin_available = 0
        
        self.logger.info(f"PositionManager initialized - Safety: {self.reduce_position_percentage}%, Max Position: ${self.max_position_size}")
        if self.auto_close_on_limit:
            self.logger.info(f"🔧 Auto-close ENABLED: {self.auto_close_strategy}, {self.auto_close_percentage}%")
    
    def get_current_exposure(self, symbol: Optional[str] = None) -> float:
        """
        Calculates CURRENT exposure based on actual API positions
        
        IMPORTANT: Pacifica API doesn't return positionValue or markPrice,
        so we calculate: amount × current_price
        
        Args:
            symbol: If provided, returns exposure only for this symbol
            
        Returns:
            float: Total exposure in USD based on current position values
        """
        try:
            # Fetch open positions from API
            positions = self.auth.get_positions()
            
            if not positions:
                self.logger.debug("📊 No open positions - exposure = $0")
                return 0.0
            
            total_exposure = 0.0
            
            for position in positions:
                pos_symbol = position.get('symbol', '')
                
                # Filter by symbol if specified
                if symbol and pos_symbol != symbol:
                    continue
                
                # ✅ FIELDS RETURNED BY API
                amount = abs(float(position.get('amount', 0)))
                entry_price = float(position.get('entry_price', position.get('entryPrice', 0)))
                side = position.get('side', 'bid')
                
                if amount == 0:
                    continue
                
                # 🎯 GET CURRENT MARKET PRICE
                current_price = self._get_current_price(pos_symbol)
                
                # If can't get current price, use entry_price as fallback
                if current_price == 0:
                    current_price = entry_price
                    self.logger.warning(
                        f"⚠️ {pos_symbol}: Using entry_price as fallback "
                        f"(failed to get current price)"
                    )
                
                # ✅ CALCULATE CURRENT POSITION VALUE
                position_value = amount * current_price
                
                total_exposure += position_value
                
                self.logger.debug(f"📊 {pos_symbol}:")
                self.logger.debug(f"   Side: {side}")
                self.logger.debug(f"   Amount: {amount:.4f}")
                self.logger.debug(f"   Entry Price: ${entry_price:.4f}")
                self.logger.debug(f"   Current Price: ${current_price:.4f}")
                self.logger.debug(f"   Position Value: ${position_value:.2f}")
            
            if total_exposure > 0:
                self.logger.info(f"💰 Total calculated exposure: ${total_exposure:.2f}")
            else:
                self.logger.debug(f"💰 Total exposure: ${total_exposure:.2f}")
            
            return total_exposure
            
        except Exception as e:
            self.logger.error(f"❌ Error calculating current exposure: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            # Fallback to legacy method
            return self._fallback_exposure_calculation()

    def _get_current_price(self, symbol: str) -> float:
        """
        Gets current price for symbol with cascading fallback
        
        Tries to get price in this order:
        1. mark (mark price - preferred)
        2. mid (mid price)
        3. last (last trade)
        4. bid (best bid)
        
        Args:
            symbol: Asset symbol (e.g., 'XRP', 'SOL')
            
        Returns:
            float: Current price or 0.0 if not found
        """
        try:
            # Fetch prices from API
            price_data = self.auth.get_prices()
            
            # Validate response
            if not price_data or 'data' not in price_data:
                self.logger.warning("⚠️ Price data not found in response")
                return 0.0
            
            # Check success flag (if it exists)
            if price_data.get('success') == False:
                self.logger.warning(f"⚠️ Price API returned success=False")
                return 0.0
            
            # Find symbol in data
            for item in price_data['data']:
                item_symbol = item.get('symbol', '')
                
                if item_symbol == symbol:
                    # ✅ CASCADING FALLBACK
                    # Try mark first (most reliable)
                    price = float(item.get('mark', 0))
                    
                    # If mark = 0, try alternatives
                    if price == 0:
                        price = float(item.get('mid', 0))
                    
                    if price == 0:
                        price = float(item.get('last', 0))
                    
                    if price == 0:
                        price = float(item.get('bid', 0))
                    
                    # Validate if valid price was found
                    if price > 0:
                        self.logger.debug(f"✅ {symbol} price: ${price:.4f}")
                        return price
                    else:
                        self.logger.warning(f"⚠️ No valid price found for {symbol}")
                        return 0.0
            
            # If symbol not found
            self.logger.warning(f"⚠️ Symbol {symbol} not found in price data")
            return 0.0
            
        except Exception as e:
            self.logger.error(f"❌ Error getting current price: {e}")
            return 0.0

    def _fallback_exposure_calculation(self) -> float:
        """
        Fallback method: calculates exposure based on open orders
        """
        total = sum(o.get('value', 0) for o in self.open_orders.values())
        self.logger.warning(f"⚠️ Using fallback calculation (orders): ${total:.2f}")
        return total

    def get_position_summary(self, symbol: Optional[str] = None) -> Dict:
        """
        Retorna resumo detalhado das posições
        
        Returns:
            Dict com informações de exposição e posições
        """
        try:
            positions = self.auth.get_positions()
            
            if not positions:
                return {
                    'total_exposure': 0.0,
                    'position_count': 0,
                    'positions': [],
                    'utilization_percent': 0.0
                }
            
            position_list = []
            total_exposure = 0.0
            
            for pos in positions:
                pos_symbol = pos.get('symbol', '')
                
                if symbol and pos_symbol != symbol:
                    continue
                
                # Dados da posição
                quantity = abs(float(pos.get('amount', 0)))

                # ✅ CORRETO: Usar 'or' para fallback
                entry_price = float(pos.get('entry_price') or pos.get('entryPrice') or 0)
                mark_price = float(pos.get('mark_price') or pos.get('markPrice') or 0)
                position_value = abs(float(pos.get('position_value') or pos.get('positionValue') or 0))

                # Calcular PnL
                pnl_value = float(pos.get('pnl', 0))
                pnl_percent = float(pos.get('pnl_percent') or pos.get('pnlPercent') or 0)
                
                position_info = {
                    'symbol': pos_symbol,
                    'size': quantity,
                    'side': pos.get('side', ''),
                    'entry_price': entry_price,
                    'mark_price': mark_price,
                    'position_value': position_value,
                    'pnl': pnl_value,
                    'pnl_percent': pnl_percent,
                    'margin': position_value / self.leverage,
                    'liquidation_price': float(pos.get('liquidationPrice', 0))
                }
                
                position_list.append(position_info)
                total_exposure += position_value
            
            utilization = (total_exposure / self.max_position_size * 100) if self.max_position_size > 0 else 0
            
            return {
                'total_exposure': total_exposure,
                'position_count': len(position_list),
                'positions': position_list,
                'utilization_percent': utilization,
                'max_position_size': self.max_position_size,
                'available_capacity': max(0, self.max_position_size - total_exposure)
            }
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao obter resumo de posições: {e}")
            return {
                'total_exposure': 0.0,
                'position_count': 0,
                'positions': [],
                'utilization_percent': 0.0,
                'error': str(e)
            }
        
    def log_exposure_status(self):
        """
        Log detalhado do status de exposição atual
        """
        try:
            summary = self.get_position_summary()
            
            self.logger.info("=" * 60)
            self.logger.info("📊 STATUS DE EXPOSIÇÃO")
            self.logger.info("=" * 60)
            self.logger.info(f"💰 Exposição Total: ${summary['total_exposure']:.2f}")
            self.logger.info(f"🎯 Limite Máximo: ${summary['max_position_size']:.2f}")
            self.logger.info(f"📈 Utilização: {summary['utilization_percent']:.1f}%")
            self.logger.info(f"✅ Capacidade Disponível: ${summary['available_capacity']:.2f}")
            self.logger.info(f"📦 Posições Abertas: {summary['position_count']}")
            
            if summary['positions']:
                self.logger.info("-" * 60)
                for pos in summary['positions']:
                    pnl_emoji = "🟢" if pos['pnl'] >= 0 else "🔴"
                    self.logger.info(
                        f"{pnl_emoji} {pos['symbol']}: "
                        f"{pos['size']} @ ${pos['mark_price']:.2f} | "
                        f"Valor: ${pos['position_value']:.2f} | "
                        f"PnL: ${pos['pnl']:.2f} ({pos['pnl_percent']:.2f}%)"
                    )
            
            self.logger.info("=" * 60)
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao logar status de exposição: {e}")
    
    def _load_positions_from_api(self):
        """Carrega posições diretamente da API usando mesma lógica de get_current_exposure"""
        try:
            self.logger.info(f"📍 Carregando detalhes das posições...")
            
            # Buscar posições pela API (mesmo método que funciona)
            positions_response = self.auth.get_positions()
            
            if not positions_response:
                self.logger.warning("Sem dados de posições")
                self.positions.clear()
                return
            
            # Limpar posições antigas
            self.positions.clear()
            
            # Processar cada posição
            for pos in positions_response:
                symbol = pos.get('symbol')
                if not symbol:
                    continue
                
                # ✅ USE CORRECT API FIELDS
                amount = abs(float(pos.get('amount', 0)))
                entry_price = float(pos.get('entry_price', pos.get('entryPrice', 0)))
                side = pos.get('side', 'bid')
                
                if amount == 0 or entry_price == 0:
                    continue
                
                # Determine if it's long or short
                # If side='bid' it's usually long, 'ask' is short
                quantity = amount if side == 'bid' else -amount
                
                self.positions[symbol] = {
                    'quantity': quantity,
                    'avg_price': entry_price,
                    'realized_pnl': float(pos.get('realized_pnl', 0)),
                    'unrealized_pnl': float(pos.get('unrealized_pnl', 0)),
                    'entry_price': entry_price,
                    'side': side,
                    'amount': amount
                }
                
                self.logger.info(f"✅ Position {symbol}: {quantity:+.4f} @ ${entry_price:.4f}")
            
            self.logger.info(f"📍 {len(self.positions)} positions loaded: {list(self.positions.keys())}")
            
        except Exception as e:
            self.logger.error(f"❌ Error loading positions: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())

    def update_account_state(self) -> bool:
        """Updates account state (balance, margin, positions)"""
        
        try:
            self.logger.info("🔄 Updating account state...")
            
            account_data = self.auth.get_account_info()
            
            if not account_data:
                self.logger.error("❌ get_account_info() returned None")
                return False
            
            self.logger.info(f"📦 Response received: success={account_data.get('success')}")
            
            if not account_data.get('success'):
                error_msg = account_data.get('error', 'Unknown error')
                self.logger.error(f"❌ success=false: {error_msg}")
                return False
            
            if 'data' not in account_data:
                self.logger.error("❌ 'data' key not found")
                return False
            
            # 🔥 SUPPORT BOTH: ARRAY OR OBJECT
            raw_data = account_data['data']
            
            self.logger.info(f"📋 Data type: {type(raw_data)}")
            
            if isinstance(raw_data, list):
                self.logger.info("   → Array format")
                if len(raw_data) == 0:
                    self.logger.error("❌ Array empty")
                    return False
                data = raw_data[0]
            elif isinstance(raw_data, dict):
                self.logger.info("   → Object format")
                data = raw_data
            else:
                self.logger.error(f"❌ Unknown format: {type(raw_data)}")
                return False
            
            # Extrair valores
            self.account_balance = float(data.get('balance', 0))
            account_equity = float(data.get('account_equity', 0))
            self.margin_available = float(data.get('available_to_spend', 0))
            self.margin_used = float(data.get('total_margin_used', 0))
            
            positions_count = int(data.get('positions_count', 0))
            orders_count = int(data.get('orders_count', 0))
            
            # Log dos valores
            self.logger.info("=" * 70)
            self.logger.info("💰 Account status:")
            self.logger.info(f"   Balance: ${self.account_balance:.2f}")
            self.logger.info(f"   Equity: ${account_equity:.2f}")
            self.logger.info(f"   Margem Used: ${self.margin_used:.2f}")
            self.logger.info(f"   Margem Available: ${self.margin_available:.2f}")
            
            if self.account_balance > 0:
                margin_percent = (self.margin_available / self.account_balance) * 100
                self.logger.info(f"   Margem Free: {margin_percent:.1f}%")
            
            self.logger.info(f"   Positions: {positions_count}")
            self.logger.info(f"   Orders: {orders_count}")
            self.logger.info("=" * 70)

            if positions_count > 0:
                self._load_positions_from_api()
        
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
            
        except Exception as e:
            self.logger.error("=" * 70)
            self.logger.error(f"❌ CRITICAL ERROR in update_account_state:")
            self.logger.error(f"   Type: {type(e).__name__}")
            self.logger.error(f"   Message: {str(e)}")
            import traceback
            self.logger.error("   Stack trace:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    self.logger.error(f"   {line}")
            self.logger.error("=" * 70)
            return False
    
    def _sync_internal_state_with_api(self):
        """Synchronizes internal state with real API - FILTERING BY SYMBOL"""
        
        try:
            # Get configured symbol
            current_symbol = os.getenv('SYMBOL', 'BTC')
            
            # Get REAL open orders from API
            real_open_orders = self.auth.get_open_orders()
            
            if real_open_orders is None:
                self.logger.warning("⚠️ Could not get orders from API for synchronization")
                return
            
            # 🔧 FILTER BY SYMBOL FIRST, THEN BY TYPE
            symbol_filtered_orders = []
            other_symbol_orders = []
            
            for order in real_open_orders:
                if order.get('symbol') == current_symbol:
                    symbol_filtered_orders.append(order)
                else:
                    other_symbol_orders.append(order)
            
            # 🔧 FILTER ONLY MAIN ORDERS (not TP/SL) FOR CURRENT SYMBOL
            main_orders = []
            tp_sl_orders = []
            
            for order in symbol_filtered_orders:
                # Identify TP/SL by API fields
                stop_price = order.get('stop_price')
                stop_parent_id = order.get('stop_parent_order_id')
                
                is_tpsl_order = (stop_price is not None) or (stop_parent_id is not None)
                
                if is_tpsl_order:
                    tp_sl_orders.append(order)
                else:
                    main_orders.append(order)
            
            # Update counters ONLY with main orders for CURRENT SYMBOL
            self.open_orders.clear()
            
            for order in main_orders:
                order_id = order.get('order_id', str(order.get('id', '')))
                
                self.open_orders[order_id] = {
                    'price': float(order.get('price', 0)),
                    'quantity': float(order.get('quantity', 0)),
                    'side': order.get('side', ''),
                    'symbol': order.get('symbol', ''),
                    'timestamp': datetime.now().isoformat(),
                    'margin': 0,  # Will be calculated if needed
                    'value': 0    # Will be calculated if needed
                }
            
            # Sync log
            total_api_orders = len(real_open_orders)
            total_symbol_orders = len(symbol_filtered_orders)
            other_symbols_orders = len(other_symbol_orders)
            main_count = len(main_orders)
            tp_sl_count = len(tp_sl_orders)
            
            self.logger.info(f"🔄 Synchronization complete:")
            self.logger.info(f"   Total API: {total_api_orders} orders")
            self.logger.info(f"   {current_symbol}: {total_symbol_orders} orders")
            self.logger.info(f"   Other symbols: {other_symbols_orders} orders (IGNORED)")
            self.logger.info(f"   {current_symbol} main: {main_count} orders")
            self.logger.info(f"   {current_symbol} TP/SL: {tp_sl_count} orders")
            self.logger.info(f"   Counted for MAX_OPEN_ORDERS limit: {main_count}")
            
            # Update margin if needed
            self._recalculate_margin_from_orders()
            
        except Exception as e:
            self.logger.error(f"❌ Synchronization error: {e}")

    def _recalculate_margin_from_orders(self):
        """Recalculates margin based on current main orders"""
        
        total_margin = 0
        
        for order_data in self.open_orders.values():
            price = order_data.get('price', 0)
            quantity = order_data.get('quantity', 0)
            
            if price > 0 and quantity > 0:
                order_value = price * quantity
                margin = order_value / self.leverage
                total_margin += margin
                
                # Update order data
                order_data['value'] = order_value
                order_data['margin'] = margin
        
        # ⚠️ DO NOT overwrite margin_used from API - it includes positions + orders
        # self.margin_used is already updated by the API in update_account_state()
        # total_margin here is only for orders, not open positions
        
        # Manter margem disponível como está da API
        # self.margin_available já foi atualizada pela API em update_account_state()
        
        self.logger.debug(f"💰 Recalculated margin: ${total_margin:.2f}")

    def can_place_order(self, order_value: float, symbol: Optional[str] = None) -> Tuple[bool, str]:
        """Checks if a new order can be placed WITH CORRECTION"""
        
        #  Sincronizar com API antes da verificação
        if hasattr(self, '_last_sync_time'):
            time_since_sync = time.time() - self._last_sync_time
            if time_since_sync > 30:  # Re-sincronizar a cada 30 segundos
                self._sync_internal_state_with_api()
        else:
            self._sync_internal_state_with_api()
        
        self._last_sync_time = time.time()
        
        # Calculate required margin
        margin_needed = order_value / self.leverage
        
        # Check available margin
        if margin_needed > self.margin_available:
            return False, f"Insufficient margin: needs ${margin_needed:.2f}, available ${self.margin_available:.2f}"
        
        # 🔧 SECOND FIX: Count ONLY main orders
        main_orders_count = len(self.open_orders)  # Already filtered in sync
        
        # Check maximum number of orders
        if main_orders_count >= self.max_open_orders:
            return False, f"Maximum orders reached: {main_orders_count}/{self.max_open_orders}"

        # Check maximum position
        current_exposure = self.get_current_exposure(symbol if 'symbol' in locals() else None)
        projected_exposure = current_exposure + order_value

        if projected_exposure > self.max_position_size:
            return False, (
                f"Maximum exposure exceeded: "
                f"${projected_exposure:.2f} > ${self.max_position_size:.2f} "
                f"(current: ${current_exposure:.2f} + new: ${order_value:.2f})"
            )

        # ✅ Pode colocar ordem
        self.logger.debug(
            f"✅ Order allowed: "
            f"exposure current ${current_exposure:.2f} + "
            f"new ${order_value:.2f} = "
            f"${projected_exposure:.2f} < ${self.max_position_size:.2f}"
        )
        
        return True, "OK"

    def add_order(self, order_id: str, order_data: Dict) -> None:
        """Adiciona ordem ao tracking COM VERIFICAÇÃO"""
        
        # 🔧 CORREÇÃO: Verificar se não é ordem TP/SL
        order_type = order_data.get('type', '')
        if order_type in ['TAKE_PROFIT', 'STOP_LOSS']:
            self.logger.debug(f"🎯 Ordem TP/SL {order_id} não contada para limite")
            return  # Não adicionar ao tracking de ordens principais
        
        self.open_orders[order_id] = {
            **order_data,
            'timestamp': datetime.now().isoformat(),
            'margin': (order_data['price'] * order_data['quantity']) / self.leverage,
            'value': order_data['price'] * order_data['quantity']
        }
        
        self.logger.info(f"📝 Ordem principal adicionada: {order_id} - {order_data['side']} {order_data['quantity']} @ ${order_data['price']}")
        
        # Atualizar margem
        self.margin_used += self.open_orders[order_id]['margin']
        self.margin_available = self.account_balance - self.margin_used
        
        # Log do status atual
        self.logger.info(f"📊 Ordens principais ativas: {len(self.open_orders)}/{self.max_open_orders}")

    """ Funcao usada para ordens scalping - estrategia diferente 
   
    def can_open_new_positions(self) -> Tuple[bool, str]:
        #Verifica se é seguro abrir novas posições (sem parar o bot)
        
        # Margem baixa para novas posições (< 15%)
        if self.account_balance > 0:
            margin_percent = (self.margin_available / self.account_balance) * 100
            if margin_percent < 15:
                return False, f"⚠️ ⚠️ Margem baixa: {margin_percent:.1f}% < 15.0%"
        
        # Saldo zero ou negativo
        if self.account_balance <= 0:
            return False, "⛔ SALDO ZERADO"
        
        # Perda total > 30% (menor que o critério de parada)
        total_pnl = sum(p.get('realized_pnl', 0) for p in self.positions.values())
        if total_pnl < -(self.account_balance * 0.3):
            return False, f"⚠️ PERDA ALTA: ${total_pnl:.2f}"
        
        return True, "OK""

        """

    def get_status_summary(self) -> Dict:
        """Retorna resumo do status atual COM CORREÇÃO"""
        
        # 🔧 CORREÇÃO: Mostrar contagem correta
        main_orders_count = len(self.open_orders)  # Só ordens principais
        
        return {
            'account_balance': self.account_balance,
            'margin_used': self.margin_used,
            'margin_available': self.margin_available,
            'margin_percent': (self.margin_available / self.account_balance * 100) if self.account_balance > 0 else 0,
            'open_orders_count': main_orders_count,  # 🔧 CORRIGIDO
            'max_orders': self.max_open_orders,
            'positions': self.positions,
            'total_exposure': sum(o.get('value', 0) for o in self.open_orders.values())
        }
    
    def get_current_balance(self) -> float:
        """Retorna saldo atual da conta"""
        return self.account_balance

    def get_balance_change_percent(self, initial_balance: float) -> float:
        """Calcula mudança percentual do saldo"""
        if initial_balance == 0:
            return 0.0
        
        return ((self.account_balance - initial_balance) / initial_balance) * 100
    
    def check_margin_safety(self) -> Tuple[bool, str]:
        """
        Verifica margem e aplica proteções em CASCATA:
        1. Margem < 20% → Cancela ordens (menos drástico)
        2. Margem < 10% → Vende posição (emergência)
        """
        
        if self.account_balance == 0:
            return False, "Saldo zero"
        
        # Calcular % de margem disponível
        margin_percent = (self.margin_available / self.account_balance) * 100
        
        # ========== NÍVEL 2: EMERGÊNCIA (Reduzir Posição) ==========
        if margin_percent < self.reduce_position_threshold:
            warning = f"🚨 MARGEM CRÍTICA: {margin_percent:.1f}% < {self.reduce_position_threshold}%"
            self.logger.error(warning)
            
            if self.auto_reduce_position:
                self.logger.warning("🔴 EMERGÊNCIA: Reduzindo posição!")
                freed = self._reduce_position_on_low_margin()
                
                if freed > 0:
                    self.logger.info(f"✅ Posição reduzida - ${freed:.2f} liberado")
                else:
                    self.logger.warning("⚠️ Não foi possível reduzir posição")
            
            return False, warning
        
        # ========== NÍVEL 1: ALERTA (Cancelar Ordens) ==========
        elif margin_percent < self.cancel_orders_threshold:
            warning = f"⚠️ Margem baixa: {margin_percent:.1f}% < {self.cancel_orders_threshold}%"
            self.logger.warning(warning)
            
            if self.auto_cancel_orders:
                self.logger.info("🔧 Cancelando ordens para liberar margem")
                cancelled = self._cancel_orders_on_low_margin()
                
                if cancelled > 0:
                    self.logger.info(f"✅ {cancelled} ordens canceladas")
                else:
                    self.logger.warning("⚠️ Nenhuma ordem para cancelar")
            
            return False, warning
        
        # ========== TUDO OK ==========
        return True, f"Margem OK: {margin_percent:.1f}%"
    
    # ========================================================================
    # SISTEMA 1: CANCELAMENTO DE ORDENS (RENOMEADO)
    # ========================================================================
    
    def _cancel_orders_on_low_margin(self) -> int:
        """
        🔧 RENOMEADA de _reduce_exposure()
        
        Cancela X% das ordens mais distantes para liberar margem.
        NÃO vende posições abertas.
        
        Returns:
            Número de ordens canceladas
        """
        
        if not self.open_orders:
            return 0
        
        symbol = os.getenv('SYMBOL', 'SOL')
        current_price = self._get_current_price(symbol)
        
        if current_price <= 0:
            self.logger.warning("⚠️ Não foi possível obter preço atual")
            return 0
        
        # Ordenar ordens por distância do preço atual
        orders_with_distance = []
        for order_id, order_data in self.open_orders.items():
            price = order_data['price']
            distance = abs(price - current_price) / current_price
            orders_with_distance.append((distance, order_id, order_data))
        
        # Ordenar: mais distantes primeiro
        orders_with_distance.sort(reverse=True)
        
        # Calcular quantas cancelar (baseado em percentual)
        cancel_count = max(1, int(len(self.open_orders) * self.cancel_orders_percentage / 100))
        cancelled_count = 0
        
        self.logger.warning(f"🔪 Cancelando {cancel_count} ordens mais distantes ({self.cancel_orders_percentage}%)")
        
        for i in range(min(cancel_count, len(orders_with_distance))):
            distance, order_id, order_data = orders_with_distance[i]
            
            try:
                # ✅ CANCELAR NA API REAL
                result = self.auth.cancel_order(str(order_id), symbol)
                
                if result:
                    self.remove_order(order_id)
                    cancelled_count += 1
                    self.logger.info(f"🗑️ Cancelada: {order_data['side']} @ ${order_data['price']:.2f} (distância: {distance*100:.1f}%)")
                    
            except Exception as e:
                self.logger.error(f"❌ Erro ao cancelar ordem {order_id}: {e}")
        
        return cancelled_count
    
    # ========================================================================
    # SISTEMA 2: REDUÇÃO DE POSIÇÃO (NOVO!)
    # ========================================================================
    
    def _reduce_position_on_low_margin(self) -> float:
        """
        🆕 NOVA FUNÇÃO
        
        Vende X% da posição aberta para liberar margem em EMERGÊNCIA.
        Usa o mesmo motor de _force_partial_sell() do AUTO_CLOSE.
        
        Returns:
            Valor em USD liberado
        """
        
        try:
            symbol = os.getenv('SYMBOL', 'SOL')
            
            # Buscar posição real da API
            api_positions = self.auth.get_positions()
            
            if not api_positions:
                self.logger.warning("⚠️ Nenhuma posição encontrada na API")
                return 0.0
            
            # Encontrar posição do símbolo
            target_position = None
            for pos in api_positions:
                if pos.get('symbol') == symbol:
                    target_position = pos
                    break
            
            if not target_position:
                self.logger.warning(f"⚠️ Nenhuma posição {symbol} encontrada")
                return 0.0
            
            # Pegar quantidade e lado da posição
            api_quantity = abs(float(target_position.get('amount', 0)))
            position_side = target_position.get('side', '').lower()
            
            if api_quantity < 0.001:
                self.logger.warning("⚠️ Posição muito pequena para reduzir")
                return 0.0
            
            # Calcular quantidade a vender
            qty_to_sell = api_quantity * (self.reduce_position_percentage / 100)
            
            # Determinar lado da ordem (oposto da posição)
            order_side = 'bid' if position_side == 'ask' else 'ask'
            
            # Obter preço atual
            current_price = self._get_current_price(symbol)
            if current_price <= 0:
                self.logger.warning(f"⚠️ Preço inválido para {symbol}")
                return 0.0
            
            # Calcular valor a liberar
            freed_value = qty_to_sell * current_price
            
            # Preparar ordem de venda
            market_price = current_price * 0.999  # -0.1% para execução rápida
            
            # Arredondar preço e quantidade
            tick_size = self.auth._get_tick_size(symbol)
            market_price = self.auth._round_to_tick_size(market_price, tick_size)

            # 🔧 USAR LOT_SIZE DINÂMICO BASEADO NO SÍMBOLO
            lot_size = self.auth._get_lot_size(symbol)
            qty_to_sell = self.auth._round_to_lot_size(qty_to_sell, lot_size)
            
            self.logger.warning(f"🔧 Quantidade ajustada para lot_size {lot_size}: {qty_to_sell} {symbol}")
            qty_to_sell = round(qty_to_sell, 2)
            
            self.logger.warning(f"🚨 VENDENDO {self.reduce_position_percentage}% da posição: {qty_to_sell:.6f} {symbol}")
            self.logger.warning(f"🚨 Preço: ${market_price:.2f} - Valor a liberar: ${freed_value:.2f}")
            
            # ✅ EXECUTAR VENDA REAL
            result = self.auth.create_order(
                symbol=symbol,
                side=order_side,
                amount=str(qty_to_sell),
                price=str(market_price),
                order_type="GTC",
                reduce_only=True
            )
            
            if result and result.get('success'):
                order_id = result.get('order_id', 'N/A')
                self.logger.warning(f"✅ Ordem de emergência criada: {order_id}")
                self.logger.warning(f"✅ Reduzindo {self.reduce_position_percentage}% da posição por MARGEM CRÍTICA")
                return freed_value
            else:
                error_msg = result.get('error', 'Erro desconhecido') if result else 'Resposta nula'
                self.logger.error(f"❌ Falha na ordem de emergência: {error_msg}")
                return 0.0
                
        except Exception as e:
            self.logger.error(f"❌ Erro na redução de emergência: {e}")
            return 0.0
    
    def remove_order(self, order_id: str) -> Optional[Dict]:
        """Remove ordem do tracking (executada ou cancelada)"""
        
        if order_id in self.open_orders:
            order = self.open_orders.pop(order_id)
            
            # Liberar margem
            self.margin_used -= order['margin']
            self.margin_available = self.account_balance - self.margin_used
            
            self.logger.info(f"✅ Ordem removida: {order_id}")
            return order
        
        return None
    
    def update_position(self, symbol: str, side: str, quantity: float, price: float) -> None:
        """Atualiza posição após execução de ordem"""
        
        if symbol not in self.positions:
            self.positions[symbol] = {
                'quantity': 0,
                'avg_price': 0,
                'realized_pnl': 0,
                'unrealized_pnl': 0
            }
        
        pos = self.positions[symbol]

        # 🔧 MODIFIED: Log antes da atualização
        self.logger.debug(f"📊 Atualizando posição {symbol}:")
        self.logger.debug(f"   Antes: qty={pos['quantity']}, avg_price={pos['avg_price']}")
        self.logger.debug(f"   Operação: {side} {quantity} @ ${price}")
        # 🔧 END MODIFIED
        
        if side == 'buy':
            # Adicionar à posição long
            total_value = (pos['quantity'] * pos['avg_price']) + (quantity * price)
            pos['quantity'] += quantity
            pos['avg_price'] = total_value / pos['quantity'] if pos['quantity'] > 0 else 0
        else:  # sell
            # Reduzir posição ou adicionar short
            if pos['quantity'] > 0:
                # Fechando long - calcular lucro realizado
                pnl = (price - pos['avg_price']) * min(quantity, pos['quantity'])
                pos['realized_pnl'] += pnl
                self.logger.info(f"💰 Lucro realizado: ${pnl:.2f}")
            
            pos['quantity'] -= quantity
        
        # 🔧 MODIFIED: Log depois da atualização
        self.logger.debug(f"   Depois: qty={pos['quantity']}, avg_price={pos['avg_price']}")
        self.logger.info(f"📊 Posição {symbol}: {pos['quantity']:.6f} @ ${pos['avg_price']:.2f}")
        # 🔧 END MODIFIED
        
        self.logger.info(f"📊 Posição {symbol}: {pos['quantity']:.4f} @ ${pos['avg_price']:.2f}")

    def get_active_positions_summary(self) -> Dict:
        """Retorna resumo simplificado das posições ativas"""
        
        longs = []
        shorts = []
        neutral = []
        
        for symbol, pos_data in self.positions.items():
            qty = pos_data.get('quantity', 0)
            
            if qty > 0.00001:  # Tolerância para arredondamento
                longs.append({
                    'symbol': symbol,
                    'quantity': qty,
                    'avg_price': pos_data.get('avg_price', 0)
                })
            elif qty < -0.00001:
                shorts.append({
                    'symbol': symbol,
                    'quantity': abs(qty),
                    'avg_price': pos_data.get('avg_price', 0)
                })
            else:
                if pos_data.get('realized_pnl', 0) != 0:
                    neutral.append({
                        'symbol': symbol,
                        'pnl': pos_data.get('realized_pnl', 0)
                    })
        
        return {
            'longs': longs,
            'shorts': shorts,
            'neutral': neutral,
            'total_longs': len(longs),
            'total_shorts': len(shorts)
        }
    
    def calculate_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """Calcula PNL não realizado"""
        
        if symbol not in self.positions:
            return 0
        
        pos = self.positions[symbol]
        
        if pos['quantity'] == 0:
            return 0
        
        pnl = (current_price - pos['avg_price']) * pos['quantity']
        pos['unrealized_pnl'] = pnl
        
        return pnl
    
    def _reduce_exposure(self) -> None:
        """Reduz exposição cancelando ordens menos importantes"""
        
        if not self.open_orders:
            return
        
        # Ordenar ordens por distância do preço atual (cancelar as mais distantes)
        # Isso é um placeholder - implementar lógica real baseada na estratégia
        
        orders_to_cancel = []
        
        # Pegar 30% das ordens mais distantes
        cancel_count = max(1, len(self.open_orders) // 3)
        
        for order_id in list(self.open_orders.keys())[:cancel_count]:
            orders_to_cancel.append(order_id)
        
        self.logger.warning(f"🔪 Reduzindo exposição: cancelando {len(orders_to_cancel)} ordens")
        
        for order_id in orders_to_cancel:
            self.remove_order(order_id)
            # Aqui você chamaria a API para cancelar de fato
            # self.auth.cancel_order(order_id)

    # New function for trade statistics
    def get_trade_summary(self) -> Dict:
        """Returns a summary of executed trades"""
        
        total_pnl = 0
        trade_count = 0
        winning_trades = 0
        losing_trades = 0
        
        for symbol, pos in self.positions.items():
            pnl = pos.get('realized_pnl', 0)
            total_pnl += pnl
            
            if pnl > 0:
                winning_trades += 1
            elif pnl < 0:
                losing_trades += 1
            
            if pnl != 0:
                trade_count += 1
        
        win_rate = (winning_trades / trade_count * 100) if trade_count > 0 else 0
        
        return {
            'total_trades': trade_count,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl
        }
    
    def apply_loss_management(self, symbol: str = None) -> Dict:
        """
        🔴 FUNÇÃO PÚBLICA: Aplica gestão de loss cancelando ordens de compra
        
        Use esta função quando:
        - Posição está em loss significativo
        - Não quer acumular mais do ativo
        - Quer manter apenas ordens de venda para reduzir exposição
        
        Args:
            symbol: Símbolo a aplicar (padrão: SOL)
            
        Returns:
            Dict com resultado da operação
        """
        
        try:
            if not symbol:
                symbol = os.getenv('SYMBOL', 'SOL')
            
            # Obter informações antes
            buy_orders_before = len([o for o in self.open_orders.values() 
                                   if o['side'] in ['buy', 'bid'] and o['symbol'] == symbol])
            sell_orders_before = len([o for o in self.open_orders.values() 
                                    if o['side'] in ['sell', 'ask'] and o['symbol'] == symbol])
            
            self.logger.info(f"🔴 INICIANDO LOSS MANAGEMENT para {symbol}")
            self.logger.info(f"📊 Estado atual: {buy_orders_before} compras, {sell_orders_before} vendas")
            
            # Aplicar cancelamento de compras
            cancelled_count = self.cancel_buy_orders_only(symbol)
            
            # Obter informações depois
            buy_orders_after = len([o for o in self.open_orders.values() 
                                  if o['side'] in ['buy', 'bid'] and o['symbol'] == symbol])
            sell_orders_after = len([o for o in self.open_orders.values() 
                                   if o['side'] in ['sell', 'ask'] and o['symbol'] == symbol])
            
            result = {
                'success': True,
                'symbol': symbol,
                'cancelled_buy_orders': cancelled_count,
                'remaining_buy_orders': buy_orders_after,
                'remaining_sell_orders': sell_orders_after,
                'message': f"Canceladas {cancelled_count} ordens de compra. Mantidas {sell_orders_after} ordens de venda."
            }
            
            self.logger.info(f"✅ LOSS MANAGEMENT concluído: {result['message']}")
            
            return result
            
        except Exception as e:
            error_msg = f"Erro no loss management: {e}"
            self.logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'symbol': symbol,
                'cancelled_buy_orders': 0
            }
    
    def should_stop_trading(self) -> Tuple[bool, str]:
        """Verifica se deve parar de operar (condições de emergência)"""
        
        # Margem crítica (< 10%)
        if self.account_balance > 0:
            margin_percent = (self.margin_available / self.account_balance) * 100
            if margin_percent < 10:
                return True, f"⛔ MARGEM CRÍTICA: {margin_percent:.1f}%"
        
        # Saldo zero ou negativo
        if self.account_balance <= 0:
            return True, "⛔ SALDO ZERADO"
        
        # Perda total > 50%
        total_pnl = sum(p.get('realized_pnl', 0) for p in self.positions.values())
        if total_pnl < -(self.account_balance * 0.5):
            return True, f"⛔ PERDA EXCESSIVA: ${total_pnl:.2f}"
        
        return False, "OK"
    
    def _check_position_size_and_auto_close(self):
        """
        ✅ CORRIGIDO: Verifica se a posição atual excede o limite usando valor REAL da API
        """
        
        if not self.auto_close_on_limit:
            return  # Auto-close desabilitado
        
        try:
            # ✅ CORREÇÃO PRINCIPAL: Usar valor real da posição da API
            symbol = os.getenv('SYMBOL', 'SOL')
            current_exposure = self.get_current_exposure(symbol)
            
            # Log comparativo (debug)
            old_calculation = self.margin_used * self.leverage
            self.logger.debug(f"📊 Comparação de cálculos:")
            self.logger.debug(f"   Método ANTIGO (margin×leverage): ${old_calculation:.2f}")
            self.logger.debug(f"   Método NOVO (posição real): ${current_exposure:.2f}")
            self.logger.debug(f"   Diferença: ${abs(current_exposure - old_calculation):.2f}")
            
            self.logger.info(f"🔍 Verificando tamanho da posição: ${current_exposure:.2f} vs limite ${self.max_position_size:.2f}")
            
            if current_exposure > self.max_position_size:
                excess_amount = current_exposure - self.max_position_size
                
                self.logger.warning(f"⚠️ Posição excede limite!")
                self.logger.warning(f"   Exposição atual: ${current_exposure:.2f}")
                self.logger.warning(f"   Limite máximo: ${self.max_position_size:.2f}")
                self.logger.warning(f"   Excesso: ${excess_amount:.2f}")
                self.logger.info("🔧 Auto-close ativado - reduzindo posição...")
                
                # Executar auto-close baseado na estratégia
                freed_amount = self._auto_close_positions(excess_amount)
                
                if freed_amount > 0:
                    self.logger.info(f"✅ Auto-close liberou ${freed_amount:.2f}")
                    
                    # Verificar se foi suficiente
                    new_exposure = self.get_current_exposure(symbol)
                    if new_exposure <= self.max_position_size:
                        self.logger.info(f"✅ Posição agora dentro do limite: ${new_exposure:.2f} <= ${self.max_position_size:.2f}")
                    else:
                        remaining_excess = new_exposure - self.max_position_size
                        self.logger.warning(f"⚠️ Ainda acima do limite em ${remaining_excess:.2f}")
                else:
                    self.logger.warning("⚠️ Não foi possível reduzir a posição automaticamente")
            else:
                # Tudo OK
                utilization = (current_exposure / self.max_position_size * 100) if self.max_position_size > 0 else 0
                self.logger.debug(f"✅ Posição OK - Utilização: {utilization:.1f}% ({current_exposure:.2f}/{self.max_position_size:.2f})")
                    
        except Exception as e:
            self.logger.error(f"❌ Erro na verificação auto-close: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def _auto_close_positions(self, target_amount: float) -> float:
        """🆕 Executa auto-close baseado na estratégia configurada"""
        
        freed_total = 0.0
        
        try:
            # 🆕 ALIASES para compatibilidade com documentação
            strategy = self.auto_close_strategy
            
            # Mapeamento de aliases da documentação para nomes internos
            strategy_aliases = {
                'cancel_orders': 'cancel_distant_orders',
                'force_sell': 'force_partial_sell', 
                'stop_buy': 'stop_buy_orders'
            }
            
            # Usar alias se existir, senão usar nome original
            internal_strategy = strategy_aliases.get(strategy, strategy)
            
            if internal_strategy == 'cancel_distant_orders':
                # Estratégia 1: Apenas cancelar ordens distantes
                freed_total = self._cancel_distant_sell_orders()
                
            elif internal_strategy == 'force_partial_sell':
                # Estratégia 2: Venda forçada de parte da posição
                freed_total = self._force_partial_sell()
                
            elif internal_strategy == 'stop_buy_orders':
                # 🆕 Estratégia 3: LOSS MANAGEMENT - Cancelar ordens de compra apenas
                self.logger.info(f"🔴 LOSS MANAGEMENT ativado - cancelando ordens de compra")
                cancelled_count = self.cancel_buy_orders_only()
                # Não liberamos margem diretamente, mas evitamos acúmulo
                freed_total = 0.0  # Não conta como margem liberada
                
            elif internal_strategy == 'hybrid':
                # Estratégia 4: Híbrida - tentar cancelar primeiro, depois vender
                freed_total = self._cancel_distant_sell_orders()
                
                if freed_total < target_amount:
                    self.logger.info(f"🔄 Ainda precisa de ${target_amount - freed_total:.2f} - vendendo posição parcial")
                    additional_freed = self._force_partial_sell()
                    freed_total += additional_freed
            
            else:
                self.logger.warning(f"⚠️ Estratégia AUTO_CLOSE desconhecida: {strategy}")
                return 0.0
            
            return freed_total
            
        except Exception as e:
            self.logger.error(f"❌ Erro no auto-close: {e}")
            return 0.0

    def _cancel_distant_sell_orders(self) -> float:
        """Cancela ordens sell muito distantes do preço atual"""
        
        try:
            symbol = os.getenv('SYMBOL', 'SOL')
            current_price = self._get_current_price(symbol)
            
            if current_price <= 0:
                self.logger.warning("⚠️ Não foi possível obter preço atual para cancelar ordens")
                return 0.0
            
            orders_to_cancel = []
            total_freed = 0
            
            # Identificar ordens sell > 2% acima do preço atual
            for order_id, order_data in self.open_orders.items():
                if (order_data['side'] == 'sell' and 
                    order_data['symbol'] == symbol):
                    
                    order_price = order_data['price']
                    distance_percent = ((order_price - current_price) / current_price) * 100
                    
                    # Cancelar sells > 2% acima do preço aproximado
                    if distance_percent > 2.0:
                        orders_to_cancel.append((order_id, order_data))
                        total_freed += order_data.get('value', 0)
            
            # Cancelar ordens identificadas
            cancelled_count = 0
            for order_id, order_data in orders_to_cancel:
                try:
                    # Cancelar na API
                    result = self.auth.cancel_order(str(order_id), symbol)
                    if result:  # cancel_order retorna True/False
                        self.remove_order(order_id)
                        cancelled_count += 1
                        self.logger.info(f"🗑️ Cancelada ordem distante: SELL @ ${order_data['price']:.2f}")
                        
                except Exception as e:
                    self.logger.error(f"❌ Erro ao cancelar ordem {order_id}: {e}")
            
            if cancelled_count > 0:
                self.logger.info(f"🗑️ {cancelled_count} ordens distantes canceladas - ${total_freed:.2f} liberado")
            
            return total_freed
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao cancelar ordens distantes: {e}")
            return 0.0

    def cancel_buy_orders_only(self, symbol: str = None) -> int:
        """
        🔴 LOSS MANAGEMENT: Cancela apenas ordens de COMPRA para evitar acumular mais posição
        Mantém ordens de VENDA para reduzir exposição
        
        Args:
            symbol: Símbolo (padrão: SOL do .env)
            
        Returns:
            int: Número de ordens canceladas
        """
        
        try:
            if not symbol:
                symbol = os.getenv('SYMBOL', 'SOL')
            
            current_price = self._get_current_price(symbol)
            
            if current_price <= 0:
                self.logger.warning("⚠️ Não foi possível obter preço atual para cancelar ordens de compra")
                return 0
            
            orders_to_cancel = []
            cancelled_count = 0
            
            # Identificar APENAS ordens de COMPRA (buy/bid)
            for order_id, order_data in self.open_orders.items():
                if (order_data['side'] in ['buy', 'bid'] and 
                    order_data['symbol'] == symbol):
                    
                    order_price = order_data['price']
                    orders_to_cancel.append((order_id, order_data))
            
            # Cancelar ordens de compra identificadas
            self.logger.info(f"🔴 LOSS MANAGEMENT: Cancelando {len(orders_to_cancel)} ordens de COMPRA para evitar acúmulo")
            
            for order_id, order_data in orders_to_cancel:
                try:
                    # Cancelar na API com símbolo
                    result = self.auth.cancel_order(str(order_id), symbol)
                    if result:  # cancel_order retorna True/False
                        self.remove_order(order_id)
                        cancelled_count += 1
                        self.logger.info(f"🗑️ Cancelada compra: BUY @ ${order_data['price']:.2f}")
                        
                except Exception as e:
                    self.logger.error(f"❌ Erro ao cancelar ordem de compra {order_id}: {e}")
            
            if cancelled_count > 0:
                self.logger.info(f"✅ LOSS MANAGEMENT: {cancelled_count} ordens de COMPRA canceladas")
                self.logger.info(f"🟢 Ordens de VENDA mantidas para reduzir exposição")
            else:
                self.logger.info(f"ℹ️ Nenhuma ordem de compra encontrada para cancelar")
            
            return cancelled_count
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao cancelar ordens de compra: {e}")
            return 0

    def _force_partial_sell(self) -> float:
        """Força venda de parte da posição para liberar espaço"""
        
        try:
            symbol = os.getenv('SYMBOL', 'SOL')
            
            # 🔧 SINCRONIZAR COM API ANTES DE TENTAR VENDA
            self.logger.info("🔄 Sincronizando posições com API antes da venda...")
            self._sync_internal_state_with_api()
            
            if symbol not in self.positions:
                self.logger.warning(f"⚠️ Nenhuma posição em {symbol} para vender")
                return 0.0
            
            pos = self.positions[symbol]
            current_qty = pos.get('quantity', 0)
            
            if current_qty <= 0:
                self.logger.warning(f"⚠️ Posição {symbol} já zerada ou short")
                return 0.0
            
            # 🔧 VERIFICAR SE REALMENTE EXISTE POSIÇÃO NA API
            self.logger.info(f"🔍 Verificando posição real na API para {symbol}...")
            api_positions = self.auth.get_positions()
            api_has_position = False
            api_quantity = 0.0
            
            if api_positions and isinstance(api_positions, list):
                for api_pos in api_positions:
                    if api_pos.get('symbol') == symbol:
                        # Usar 'amount' como quantidade, conforme documentação
                        api_amt = float(api_pos.get('amount', 0))
                        api_side = api_pos.get('side', '').lower()
                        # Aceitar tanto long (bid) quanto short (ask)
                        if abs(api_amt) > 0:
                            api_has_position = True
                            api_quantity = abs(api_amt)
                            position_side = api_side  # 'bid' (long) ou 'ask' (short)
                            break
            
            if not api_has_position or api_quantity <= 0:
                self.logger.warning(f"⚠️ API não confirma posição aberta em {symbol} (amount: {api_quantity})")
                self.logger.warning(f"⚠️ Removendo posição interna inconsistente")
                # Limpar posição interna inconsistente
                if symbol in self.positions:
                    del self.positions[symbol]
                return 0.0
            
            # 🔧 USAR QUANTIDADE REAL DA API PARA CÁLCULOS
            self.logger.info(f"✅ Posição confirmada na API: {api_quantity} {symbol}")
            
            # Calcular quantidade a vender (percentual configurado)
            sell_percentage = self.auto_close_percentage / 100
            qty_to_sell = api_quantity * sell_percentage
            # Determinar o lado da ordem para reduzir posição
            # Se posição é short (ask), ordem de compra ('bid')
            # Se posição é long (bid), ordem de venda ('ask')
            order_side = 'bid' if position_side == 'ask' else 'ask'
            if qty_to_sell < 0.001:
                self.logger.warning(f"⚠️ Quantidade a reduzir muito pequena: {qty_to_sell}")
                return 0.0
            
            # Obter preço atual do mercado (mais preciso que estimativas)
            current_price = self._get_current_price(symbol)
            if current_price <= 0:
                # Tentar usar preço da posição interna como fallback
                pos = self.positions.get(symbol, {})
                current_price = pos.get('entry_price', 0)
            
            if current_price <= 0:
                self.logger.warning(f"⚠️ Não foi possível obter preço para {symbol}")
                return 0.0
            
            freed_value = qty_to_sell * current_price
            
            # Log da operação
            self.logger.info(f"💰 Vendendo {self.auto_close_percentage}% da posição: {qty_to_sell:.6f} {symbol}")
            self.logger.info(f"💰 Preço atual: ${current_price:.2f} - Valor a liberar: ${freed_value:.2f}")
            
            # 🔥 EXECUÇÃO REAL DA VENDA (ativada)
            try:
                # Criar ordem para venda imediata  
                # Usar preço ligeiramente abaixo do mercado para garantir execução
                market_price = current_price * 0.999  # -0.1% do preço atual
                
                # 🔧 ARREDONDAR PREÇO PARA TICK_SIZE usando função do auth
                tick_size = self.auth._get_tick_size(symbol)
                market_price = self.auth._round_to_tick_size(market_price, tick_size)
                
                # 🔧 ARREDONDAR QUANTIDADE PARA LOT_SIZE  
                lot_size = self.auth._get_lot_size(symbol)
                qty_to_sell = self.auth._round_to_lot_size(qty_to_sell, lot_size)
                
                self.logger.info(f"🔧 Quantidade ajustada para lot_size {lot_size}: {qty_to_sell} {symbol}")
                qty_to_sell = round(qty_to_sell, 2)  # Máximo 2 casas decimais para exibição
                
                self.logger.info(f"📄 Criando ordem: ask {qty_to_sell} {symbol} @ ${market_price}")
                
                # 🔧 VERIFICAÇÃO FINAL ANTES DE ENVIAR ORDEM
                # Dupla verificação para evitar erro "No position found for reduce-only order"
                final_check = self.auth.get_positions()
                has_final_position = False
                if final_check and isinstance(final_check, list):
                    for pos_check in final_check:
                        if pos_check.get('symbol') == symbol:
                            amt_final = float(pos_check.get('amount', 0))
                            side_final = pos_check.get('side', '').lower()
                            # Para short, precisa de pelo menos qty_to_sell em posição 'ask'; para long, em 'bid'
                            if position_side == 'ask' and abs(amt_final) >= qty_to_sell and side_final == 'ask':
                                has_final_position = True
                                break
                            elif position_side == 'bid' and abs(amt_final) >= qty_to_sell and side_final == 'bid':
                                has_final_position = True
                                break
                if not has_final_position:
                    self.logger.warning(f"⚠️ ABORTAR: Posição insuficiente na verificação final")
                    self.logger.warning(f"⚠️ Necessário: {qty_to_sell}, mas posição pode ter mudado")
                    return 0.0
                
                result = self.auth.create_order(
                    symbol=symbol,
                    side=order_side,  # lado correto para reduzir posição
                    amount=str(qty_to_sell),
                    price=str(market_price),
                    order_type="GTC",
                    reduce_only=True  # Para reduzir posição existente
                )
                
                if result and result.get('success'):
                    order_id = result.get('order_id', 'N/A')
                    self.logger.info(f"✅ Ordem de venda parcial criada!")
                    self.logger.info(f"✅ ID: {order_id} - Preço: ${market_price:.2f}")
                else:
                    error_msg = result.get('error', 'Erro desconhecido') if result else 'Resposta nula'
                    self.logger.error(f"❌ Falha na ordem reduce_only: {error_msg}")
                    
                    # 🔧 FALLBACK: Tentar sem reduce_only se o erro for de posição não encontrada
                    if "No position found" in str(error_msg):
                        self.logger.warning(f"🔄 Tentando ordem sem reduce_only como fallback...")
                        fallback_result = self.auth.create_order(
                            symbol=symbol,
                            side='ask',
                            amount=str(qty_to_sell),
                            price=str(market_price),
                            order_type="GTC",
                            reduce_only=False  # Sem reduce_only
                        )
                        
                        if fallback_result and fallback_result.get('success'):
                            order_id = fallback_result.get('order_id', 'N/A')
                            self.logger.info(f"✅ Ordem fallback criada: {order_id}")
                        else:
                            fallback_error = fallback_result.get('error', 'Erro desconhecido') if fallback_result else 'Resposta nula'
                            self.logger.error(f"❌ Fallback também falhou: {fallback_error}")
                            return 0.0
                    else:
                        return 0.0
                        
            except Exception as e:
                self.logger.error(f"❌ Erro ao executar venda: {e}")
                return 0.0
            
            # Atualizar posição internamente
            pos['quantity'] -= qty_to_sell
            if pos['quantity'] < 0.001:
                pos['quantity'] = 0  # Zerar se muito pequeno
            
            self.logger.info(f"📊 Nova posição {symbol}: {pos['quantity']:.6f}")
            
            return freed_value
            
        except Exception as e:
            self.logger.error(f"❌ Erro na venda parcial: {e}")
            return 0.0