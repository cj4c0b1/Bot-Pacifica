"""
Grid Strategy - Grid Trading Strategy Implementation
"""
import os
import time
import logging
import threading
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from src.performance_tracker import PerformanceTracker, Trade, GridExecution
from src.strategy_logger import create_strategy_logger
import uuid

class GridStrategy:
    def __init__(self, auth_client, calculator, position_manager):
        # Determines the specific grid strategy type
        strategy_type = os.getenv('STRATEGY_TYPE', 'market_making').lower()
        if strategy_type not in ['pure_grid', 'market_making']:
            strategy_type = 'market_making'
            
        self.logger = create_strategy_logger('PacificaBot.GridStrategy', strategy_type)
        
        self.auth = auth_client
        self.calculator = calculator
        self.position_mgr = position_manager
        
        # Configurações
        self.symbol = os.getenv('SYMBOL', 'BTC')
        self.strategy_type = os.getenv('STRATEGY_TYPE', 'market_making')
        self.grid_mode = os.getenv('GRID_MODE', 'maker')
        self.range_exit = os.getenv('RANGE_EXIT', 'true').lower() == 'true'
        
        # Estado do grid
        self.grid_center = 0
        self.active_grid = {'buy_levels': [], 'sell_levels': []}
        self.placed_orders = {}  # {price: order_id}
        self.grid_active = False
        
        # Thread safety - Locks para evitar race conditions
        self._order_lock = threading.Lock()
        self._position_lock = threading.Lock()
       
        # Sistema de métricas
        self.performance_tracker = PerformanceTracker(self.symbol)
        
        self.logger.info(f"GridStrategy inicializada - {self.strategy_type} mode com métricas ativas")
        
    
    def initialize_grid(self, current_price: float) -> bool:
        """Inicializa o grid baseado no preço atual"""
        
        try:
            self.logger.info(f"🔧 Inicializando grid em ${current_price}")
            
            # Validar parâmetros
            valid, errors = self.calculator.validate_grid_parameters()
            if not valid:
                self.logger.error(f"❌ Invalid parameters: {errors}")
                return False
            
            # VERIFICAR ORDENS EXISTENTES PRIMEIRO
            self.logger.info(f"🔍 Verificando ordens existentes para {self.symbol}...")
            existing_orders = self.auth.get_open_orders(self.symbol)
            
            if existing_orders and len(existing_orders) > 0:
                self.logger.info(f"✅ Encontradas {len(existing_orders)} ordens existentes para {self.symbol}")
                
                # Carregar ordens existentes no tracking
                for order in existing_orders:
                    # Filtrar TP/SL para não carregá-las como ordens do grid
                    order_type = order.get('type', '')
                    order_subtype = order.get('subType', '')
                    order_label = str(order.get('label', '')).lower()
                    if (order_type in ['TAKE_PROFIT', 'STOP_LOSS'] or
                        order_subtype in ['take_profit', 'stop_loss'] or
                        'tp' in order_label or 'sl' in order_label):
                        self.logger.debug(f"🔕 Pulando ordem TP/SL: {order.get('order_id')} @ {order.get('price')}")
                        continue

                    order_id = order.get('order_id')
                    price = float(order.get('price', 0))
                    side = order.get('side')
                    quantity = float(order.get('quantity', 0))
                    
                    # 🔧 NORMALIZAR side para 'buy' ou 'sell'
                    if side == 'bid':
                        side = 'buy'
                    elif side == 'ask':
                        side = 'sell'

                    # 🔧 NORMALIZAR CHAVE DE PREÇO (usar sempre _price_key)
                    price_key = self._price_key(price)

                    # Adicionar ao tracking principal (apenas ordens do grid)
                    self.placed_orders[price_key] = order_id
                    self.position_mgr.add_order(order_id, {
                        'price': price,
                        'quantity': quantity,
                        'side': side,
                        'symbol': self.symbol
                    })
                    self.logger.debug(f"  📌 Carregada: {side} @ ${price} (ID: {order_id})")
                
                # Reconstruir grid baseado nas ordens existentes
                self._reconstruct_grid_from_orders(existing_orders, current_price)
                
                self.grid_active = True
                self.grid_center = current_price
                
                self.logger.info(f"✅ Grid retomado com {len(existing_orders)} ordens existentes")
                self.logger.info(f"⏭️ Skipping new order creation - using existing orders")
                return True  # ✅ Retorna True para continuar o loop
            
            # Se não há ordens, calcular novos níveis
            self.logger.info(f"📊 No existing orders - creating new grid...")
            self.active_grid = self.calculator.calculate_grid_levels(current_price)

            # Atualizar tracker com saldo inicial
            if hasattr(self.position_mgr, 'account_balance') and self.position_mgr.account_balance > 0:
                self.performance_tracker.update_balance(self.position_mgr.account_balance)

            self.grid_center = current_price
            
            # LIMPAR ORDENS ANTERIORES COM PROTEÇÃO
            with self._order_lock:
                self.placed_orders.clear()

            # Colocar ordens iniciais
            # Durante a inicialização precisamos permitir que _place_single_order
            # execute mesmo com grid_active inicialmente False. Definimos o
            # grid_active temporariamente para True para permitir a criação
            # das ordens iniciais; se falhar, reverteremos para False.
            self.logger.debug("🔧 Temporarily activating grid for initial order creation")
            self.grid_active = True
            success = self._place_grid_orders()

            if success:
                # grid_active já está True
                self.logger.info(f"✅ Grid ativo com {len(self.placed_orders)} ordens")
                return True  # ✅ Retorna True para continuar
            else:
                # Reverter para estado inativo se falhou
                self.grid_active = False
                self.logger.error(f"❌ Failed to create grid orders")
                return False  # ❌ Retorna False para encerrar
            
        except Exception as e:
            self.logger.error(f"❌ Error initializing grid: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    def _reconstruct_grid_from_orders(self, existing_orders: List, current_price: float) -> None:
        """Reconstructs grid structure based on existing orders"""
        
        buy_levels = []
        sell_levels = []
        
        for order in existing_orders:
            price = float(order.get('price', 0))
            side = order.get('side')
            
            # 🔧 CORREÇÃO: Aceitar 'bid' OU 'buy'
            if side in ['buy', 'bid']:
                buy_levels.append(price)
            # 🔧 CORREÇÃO: Aceitar 'ask' OU 'sell'
            elif side in ['sell', 'ask']:
                sell_levels.append(price)
        
        # Ordenar níveis
        buy_levels.sort(reverse=True)  # Maiores primeiro (mais próximos)
        sell_levels.sort()  # Menores primeiro (mais próximos)
        
        # Reconstruir estrutura do grid
        self.active_grid = {
            'buy_levels': buy_levels,
            'sell_levels': sell_levels,
            'current_price': current_price
        }
        
        self.logger.info(f"📊 Grid reconstruído: {len(buy_levels)} buy levels, {len(sell_levels)} sell levels")
    
    def _place_grid_orders(self) -> bool:
        """Places grid orders"""

            # 🔍 DEBUG: Verificar estado antes de criar ordens
        self.logger.debug(f"🔍 === _place_grid_orders DEBUG ===")
        self.logger.debug(f"🔍 Active grid buy levels: {len(self.active_grid.get('buy_levels', []))}")
        self.logger.debug(f"🔍 Active grid sell levels: {len(self.active_grid.get('sell_levels', []))}")
        self.logger.debug(f"🔍 Placed orders count: {len(self.placed_orders)}")
        
        orders_placed = 0
        
        # ===== Guard: não criar mais do que o total configurado (GRID_LEVELS) =====
        total_grid_size = getattr(self.calculator, 'grid_levels', None) or int(os.getenv('GRID_LEVELS', '10'))
        
        # Buscar ordens abertas da API e contar apenas ordens "principais" (filtrando TP/SL)
        open_orders = self.auth.get_open_orders(self.symbol) or []
        api_main_count = 0
        existing_prices = {}  # inicializar aqui (usado abaixo)
        if open_orders:
            for order in open_orders:
                if order.get('symbol') != self.symbol:
                    continue
                # filtrar TP/SL
                order_type = order.get('type', '')
                order_subtype = order.get('subType', '')
                order_label = str(order.get('label', '')).lower()
                if (order_type in ['TAKE_PROFIT', 'STOP_LOSS'] or
                    order_subtype in ['take_profit', 'stop_loss'] or
                    'tp' in order_label or 'sl' in order_label):
                    continue

                api_main_count += 1

                # Também preencher mapa de preços existentes (normalizado)
                try:
                    price = float(order.get('price', 0))
                    raw_side = order.get('side')
                    if raw_side in ['bid', 'buy']:
                        side_norm = 'buy'
                    elif raw_side in ['ask', 'sell']:
                        side_norm = 'sell'
                    else:
                        side_norm = str(raw_side)
                    price_key = self._price_key(price)
                    existing_prices[f"{price_key}_{side_norm}"] = order.get('order_id')
                except Exception:
                    continue
        
        if api_main_count >= int(total_grid_size):
            self.logger.warning(f"⚠️ Já existem {api_main_count}/{total_grid_size} ordens principais na exchange - pulando criação de novas ordens")
            return False
        # ===== end guard =====
        
        # Ordens de compra
        for price in self.active_grid.get('buy_levels', []):
            price_key = self._price_key(price)
            key = f"{price_key}_buy"
            # Verificar se já existe ordem nesse preço
            if key not in existing_prices and price_key not in self.placed_orders:
                if self._place_single_order(price_key, 'buy'):
                    orders_placed += 1
            else:
                # detalhe: preferir debug para não poluir muito o log
                self.logger.debug(f"⏭️ Pulando ordem buy em ${price_key} - já existe (ID: {existing_prices.get(key) or self.placed_orders.get(price_key)})")
        
        # Ordens de venda
        for price in self.active_grid.get('sell_levels', []):
            price_key = self._price_key(price)
            key = f"{price_key}_sell"
            if key not in existing_prices and price_key not in self.placed_orders:
                if self._place_single_order(price_key, 'sell'):
                    orders_placed += 1
            else:
                self.logger.debug(f"⏭️ Pulando ordem sell em ${price_key} - já existe (ID: {existing_prices.get(key) or self.placed_orders.get(price_key)})")

        self.logger.info(f"📊 {orders_placed} new orders placed in grid")
        return orders_placed > 0

    def _place_single_order(self, price: float, side: str, quantity: float = None) -> bool:
        """Places a single order"""
        
        if not self.grid_active:
            return False

        # 🔧 VERIFICAR PREÇO VÁLIDO
        if price <= 0:
            self.logger.error(f"❌ Preço inválido recebido para ordem: ${price} - cancelando ordem")
            return False

        # 🔒 LOCK PARA EVITAR RACE CONDITIONS
        with self._order_lock:
            # Verificar se ordem já existe (race condition fix)
            key = self._price_key(price)
            if key in self.placed_orders:
                self.logger.debug(f"🔄 Ordem já existe em ${price} - pulando")
                return False

            try:
                # Calcular quantidade
                if quantity is None:
                    quantity = self.calculator.calculate_quantity(price)
                
                # 🔧 VERIFICAR SE QUANTIDADE É VÁLIDA
                if quantity <= 0:
                    self.logger.error(f"❌ Quantidade inválida calculada: {quantity} para preço ${price}")
                    return False
                
                order_value = price * quantity
                self.logger.info(f"Ordem de teste: {price} - {quantity} - {order_value}")
                # Verificar se pode colocar ordem
                can_place, reason = self.position_mgr.can_place_order(order_value)
                if not can_place:
                    if "Máximo de ordens atingido" in reason:
                        self.logger.info(f"📊 {reason} - aguardando execução de ordens existentes")
                        return False
                    
                    elif "Margem insuficiente" in reason:
                        # Log detalhado para problemas de margem
                        margin_needed = order_value / self.position_mgr.leverage
                        margin_available = self.position_mgr.margin_available
                        
                        if self.position_mgr.account_balance > 0:
                            margin_percent = (margin_available / self.position_mgr.account_balance * 100)
                        else:
                            margin_percent = 0
                        
                        self.logger.warning(f"⚠️ Margem insuficiente para ${price:.2f}")
                        self.logger.warning(f"   Necessário: ${margin_needed:.2f} | Disponível: ${margin_available:.2f}")
                        self.logger.warning(f"   Margem livre: {margin_percent:.1f}%")
                        
                        # Se margem muito baixa, ativar proteções
                        if margin_percent < 20:
                            self.logger.warning("🔧 Critical margin - checking protections...")
                            is_safe, msg = self.position_mgr.check_margin_safety()
                        
                        return False
                    else:
                        self.logger.warning(f"⚠️ Não pode colocar ordem: {reason}")
                        return False

                # Preparar ordem
                order_data = self.calculator.format_order_for_api(price, quantity, side, self.symbol)
                
                # Enviar ordem
                self.logger.debug(f"📤 Enviando ordem: {side} {quantity} {self.symbol} @ ${price}")
                
                result = self.auth.create_order(
                    symbol=order_data['symbol'],
                    side=order_data['side'],
                    amount=order_data['amount'],
                    price=order_data['price'],
                    order_type=order_data['tif'],
                    reduce_only=order_data['reduce_only']
                )
                
                if result and 'success' in result and result['success']:
                    if 'data' in result and 'order_id' in result['data']:
                        order_id = result['data']['order_id']
                    
                    # Atomicamente adicionar ao tracking
                    self.placed_orders[key] = order_id
                    self.position_mgr.add_order(order_id, {
                        'price': price,
                        'quantity': quantity,
                        'side': side,
                        'symbol': self.symbol
                    })
                    
                    # Registrar no performance tracker
                    grid_execution = GridExecution(
                        order_id=order_id,
                        symbol=self.symbol,
                        side=side,
                        price=price,
                        quantity=quantity,
                        timestamp=datetime.now(),
                        executed=False
                    )
                    self.performance_tracker.record_grid_execution(grid_execution)

                    self.logger.info(f"✅ Ordem colocada: {order_id} - {side} @ ${price}")
                    return True
                else:
                    self.logger.error(f"❌ Falha ao criar ordem em ${price}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"❌ Erro ao colocar ordem em ${price}: {e}")
                return False
    
    def check_and_rebalance(self, current_price: float) -> None:
        """Checks if needs to rebalance grid with robust price handling"""
        
        if not self.grid_active:
            self.logger.warning("⚠️ Grid is not active")
            return

        # 🔧 VERIFICAÇÃO MELHORADA DE PREÇO INVÁLIDO COM RECUPERAÇÃO
        if current_price <= 0:
            self.logger.warning(f"Preço inválido: {current_price} - tentando recuperar...")
            
            # Tentar obter preço da API com retry
            recovery_price = self._get_current_price_with_retry()
            if recovery_price > 0:
                current_price = recovery_price
                self.logger.info(f"✅ Preço recuperado: ${current_price:.2f}")
            else:
                # Usar último preço válido conhecido
                last_valid = getattr(self, '_last_valid_price', 0)
                if last_valid > 0:
                    current_price = last_valid
                    self.logger.warning(f"⚠️ Usando último preço válido: ${current_price:.2f}")
                else:
                    self.logger.error("❌ Não foi possível recuperar preço - abortando rebalanceamento")
                    return
        
        # Armazenar preço válido para recuperação futura
        self._last_valid_price = current_price
        
        # Para Pure Grid - verificar se saiu do range
        if self.strategy_type == 'pure_grid' and self.range_exit:
            if not self._check_price_in_range(current_price):
                self.logger.warning(f"⚠️ Price outside range - pausing grid")
                self.pause_grid()
                return
        
        # Verificar se precisa adicionar ordens faltantes
        self.rebalance_grid_orders(current_price)
        
        # Para Market Making - verificar se precisa deslocar grid
        if self.strategy_type == 'market_making':
            if self.calculator.should_shift_grid(current_price, self.grid_center):
                self.logger.info(f"🔄 Deslocando grid de ${self.grid_center} para ${current_price}")
                self.shift_grid(current_price)  # Função para deslocar (próximo passo)
    
    def check_filled_orders(self, current_price: float) -> None:
        """Checks filled orders and creates opposite orders WITH CORRECTION"""
        
        try:
            # 🔧 CORREÇÃO: Buscar TODAS as ordens abertas e filtrar corretamente
            all_open_orders = self.auth.get_open_orders()
            
            if all_open_orders is None:
                self.logger.warning("⚠️ Could not fetch open orders")
                return
            
            # FILTER ONLY MAIN ORDERS (not TP/SL)
            open_orders = []
            tp_sl_orders = []
            
            for order in all_open_orders:
                symbol = order.get('symbol')
                
                if symbol == self.symbol:
                    order_type = order.get('type', '')
                    order_subtype = order.get('subType', '')
                    order_label = order.get('label', '').lower()
                    
                    # Identificar ordens TP/SL
                    if (order_type in ['TAKE_PROFIT', 'STOP_LOSS'] or 
                        order_subtype in ['take_profit', 'stop_loss'] or
                        'tp' in order_label or 'sl' in order_label):
                        tp_sl_orders.append(order)
                    else:
                        open_orders.append(order)
            
            # Log da classificação
            total_symbol_orders = len([o for o in all_open_orders if o.get('symbol') == self.symbol])
            main_count = len(open_orders)
            tp_sl_count = len(tp_sl_orders)
            
            self.logger.debug(f"📋 {self.symbol}: {total_symbol_orders} total | {main_count} principais | {tp_sl_count} TP/SL")
            
            # 🔧 USE ONLY MAIN ORDERS for fill detection
            open_order_ids = set()
            for order in open_orders:
                order_id = order.get('order_id')
                if order_id:
                    open_order_ids.add(str(order_id))
            
            self.logger.debug(f"📋 {len(open_order_ids)} ordens principais abertas de {self.symbol}")
            
            # Verificar quais ordens foram executadas
            filled_orders = []
            # 🔒 LOCK PARA PROTEÇÃO DE RACE CONDITION
            with self._order_lock:
                for price, order_id in list(self.placed_orders.items()):
                    if str(order_id) not in open_order_ids:
                        filled_orders.append((price, order_id))
                        self.logger.info(f"🎯 Ordem EXECUTADA detectada: {order_id} @ ${price}")
                
                # Processar cada ordem executada
                for fill_price, order_id in filled_orders:
                    # Remover do tracking atomicamente
                    del self.placed_orders[fill_price]
            
            # Processar as ordens fora do lock para evitar deadlock
            for fill_price, order_id in filled_orders:
                order_data = self.position_mgr.remove_order(str(order_id))
                
                if order_data:
                    side = order_data.get('side', 'unknown')
                    quantity = order_data.get('quantity', 0)
                    symbol = order_data.get('symbol', self.symbol)
                    
                    self.logger.info(f"💰 Trade executado: {side.upper()} {quantity} {symbol} @ ${fill_price}")
                    
                    # Atualizar posição
                    self.position_mgr.update_position(symbol, side, quantity, fill_price)
                    
                    # Criar ordem oposta para realizar lucro
                    self._create_opposite_order(fill_price, side, quantity)
                else:
                    self.logger.warning(f"⚠️ Dados da ordem {order_id} não encontrados")
            
            if filled_orders:
                self.logger.info(f"✅ Processadas {len(filled_orders)} ordens executadas")
                
                # Atualizar resumo de posições
                summary = self.position_mgr.get_active_positions_summary()
                self.logger.info(f"📊 Posições: {summary['total_longs']} longs, {summary['total_shorts']} shorts")
            
        except Exception as e:
            self.logger.error(f"❌ Error checking fills: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())

    def rebalance_grid_orders(self, current_price: float) -> None:
        """Rebalances grid by adding missing orders WITH ROBUST CORRECTION"""
        
        try:
            # Check margin BEFORE attempting to rebalance
            self.position_mgr.update_account_state()
            
            if self.position_mgr.account_balance > 0:
                margin_percent = (self.position_mgr.margin_available / 
                                self.position_mgr.account_balance * 100)
                
                if margin_percent < 25:
                    self.logger.warning(f"⚠️ Margem baixa ({margin_percent:.1f}%) - pulando rebalanceamento")
                    self.logger.info("💡 Minimum required: 25% free margin")
                    
                    # Ativar proteções se muito baixo
                    if margin_percent < 20:
                        self.logger.warning("🔧 Activating automatic protections...")
                        is_safe, msg = self.position_mgr.check_margin_safety()
                    
                    return  # NÃO continua rebalanceamento
            
            # VERIFICAÇÃO DE PREÇO INVÁLIDO COM RECUPERAÇÃO
            if current_price <= 0:
                self.logger.warning(f"Preço inválido: {current_price} - tentando recuperar...")
                
                # Tentar obter preço da API com retry
                recovery_price = self._get_current_price_with_retry()
                if recovery_price > 0:
                    current_price = recovery_price
                    self.logger.info(f"✅ Preço recuperado: ${current_price:.2f}")
                else:
                    # Usar último preço válido conhecido
                    last_valid = getattr(self, '_last_valid_price', 0)
                    if last_valid > 0:
                        current_price = last_valid
                        self.logger.warning(f"⚠️ Usando último preço válido: ${current_price:.2f}")
                    else:
                        self.logger.error("❌ Não foi possível recuperar preço - abortando rebalanceamento")
                        return
            
            # Armazenar preço válido para recuperação futura
            self._last_valid_price = current_price
            
            self.logger.info(f"🔄 Iniciando rebalanceamento do grid...")
            
            # 1. Buscar ordens abertas atuais
            all_open_orders = self.auth.get_open_orders()
            if all_open_orders is None:
                self.logger.warning("⚠️ Could not fetch orders for rebalancing")
                return
            
            # FILTRAR APENAS ORDENS PRINCIPAIS
            main_orders = []
            
            for order in all_open_orders:
                if order.get('symbol') == self.symbol:
                    order_type = order.get('type', '')
                    order_subtype = order.get('subType', '')
                    order_label = order.get('label', '').lower()
                    
                    # Filtrar TP/SL
                    if not (order_type in ['TAKE_PROFIT', 'STOP_LOSS'] or 
                        order_subtype in ['take_profit', 'stop_loss'] or
                        'tp' in order_label or 'sl' in order_label):
                        main_orders.append(order)
            
            # 2. Separar por tipo e coletar preços existentes
            existing_buy_prices = set()
            existing_sell_prices = set()
            
            for order in main_orders:
                price = float(order.get('price', 0))
                side = order.get('side')
                order_id = order.get('order_id')
                
                # Aceitar tanto 'bid'/'buy' quanto 'ask'/'sell'
                if side in ['buy', 'bid']:
                    price_key = self._price_key(price)
                    existing_buy_prices.add(price_key)
                    # normalizar também placed_orders tracking
                    if price_key not in self.placed_orders:
                        self.placed_orders[price_key] = order_id
                elif side in ['sell', 'ask']:
                    price_key = self._price_key(price)
                    existing_sell_prices.add(price_key)
                    if price_key not in self.placed_orders:
                        self.placed_orders[price_key] = order_id
            
            total_existing = len(existing_buy_prices) + len(existing_sell_prices)
            self.logger.info(f"📊 Ordens PRINCIPAIS existentes: {len(existing_buy_prices)} buy, {len(existing_sell_prices)} sell (Total: {total_existing})")
            
            # 3. Calcular quantas ordens FALTAM para completar o grid original
            total_grid_size = self.calculator.grid_levels
            target_per_side = total_grid_size // 2
            
            buy_needed = target_per_side - len(existing_buy_prices)
            sell_needed = target_per_side - len(existing_sell_prices)
            
            self.logger.info(f"🎯 Target: {target_per_side} por lado")
            self.logger.info(f"📝 Faltam: {buy_needed} buy, {sell_needed} sell")
            
            # 4. Se não precisa criar ordens, sair
            if buy_needed <= 0 and sell_needed <= 0:
                self.logger.info(f"✅ Grid complete - no need for rebalancing")
                return
            
            # 5. Criar APENAS as ordens faltantes baseado nos níveis do grid
            orders_created = 0
            
            # Criar ordens BUY faltantes
            if buy_needed > 0:
                self.logger.info(f"➕ Criando {buy_needed} ordens BUY...")
                
                # 🔧 VERIFICAR SE SPACING É VÁLIDO
                spacing = getattr(self.calculator, 'spacing_percent', 0.5)
                if spacing <= 0:
                    self.logger.error(f"❌ Spacing inválido: {spacing}% - cancelando rebalanceamento")
                    return
                
                buy_count = 0
                level = 1
                while buy_count < buy_needed:
                    # Calcular preço do nível
                    price_offset = (spacing / 100) * level
                    price = current_price * (1 - price_offset)
                    price = self.calculator.round_price(price)
                    
                    # 🔧 VERIFICAR SE PREÇO CALCULADO É VÁLIDO
                    if price <= 0:
                        self.logger.error(f"❌ Preço BUY inválido calculado: {price} (level {level})")
                        level += 1
                        continue
                    
                    # Verificar se já existe ordem nesse preço
                    if price not in existing_buy_prices and price not in self.placed_orders:
                        if self._place_single_order(price, 'buy'):
                            orders_created += 1
                            buy_count += 1
                            existing_buy_prices.add(price)
                        time.sleep(0.3)
                    
                    level += 1
                    
                    # Segurança: não criar mais que o necessário
                    if level > target_per_side * 2:
                        break
            
            # Criar ordens SELL faltantes
            if sell_needed > 0:
                self.logger.info(f"➕ Criando {sell_needed} ordens SELL...")
                
                # 🔧 VERIFICAR SE SPACING É VÁLIDO (usar mesmo valor que BUY)
                spacing = getattr(self.calculator, 'spacing_percent', 0.5)
                if spacing <= 0:
                    self.logger.error(f"❌ Spacing inválido: {spacing}% - cancelando rebalanceamento")
                    return
                
                sell_count = 0
                level = 1
                while sell_count < sell_needed:
                    # Calcular preço do nível
                    price_offset = (spacing / 100) * level
                    price = current_price * (1 + price_offset)
                    price = self.calculator.round_price(price)
                    
                    # 🔧 VERIFICAR SE PREÇO CALCULADO É VÁLIDO
                    if price <= 0:
                        self.logger.error(f"❌ Preço SELL inválido calculado: {price} (level {level})")
                        level += 1
                        continue
                    
                    # Verificar se já existe ordem nesse preço
                    if price not in existing_sell_prices and price not in self.placed_orders:
                        if self._place_single_order(price, 'sell'):
                            orders_created += 1
                            sell_count += 1
                            existing_sell_prices.add(price)
                        time.sleep(0.3)
                    
                    level += 1
                    
                    # Segurança: não criar mais que o necessário
                    if level > target_per_side * 2:
                        break
            
            # 6. Resumo final
            final_buy = len(existing_buy_prices)
            final_sell = len(existing_sell_prices)
            
            if orders_created > 0:
                self.logger.info(f"✅ Rebalanceamento concluído: {orders_created} ordens criadas")
            else:
                self.logger.info(f"✅ Rebalancing completed: no orders created")
                
            self.logger.info(f"📊 Grid final: {final_buy} buy, {final_sell} sell (Total: {final_buy + final_sell})")
            
        except Exception as e:
            self.logger.error(f"❌ Error rebalancing grid: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())

    def _create_opposite_order(self, entry_price: float, entry_side: str, quantity: float) -> None:
        """Creates opposite order to realize profit"""
        
        # Calcular preço alvo (próximo nível do grid)
        target_price = self.calculator.calculate_profit_target(entry_price, entry_side)
        
        # Lado oposto
        opposite_side = 'sell' if entry_side == 'buy' else 'buy'
        
        self.logger.info(f"📝 Criando ordem de LUCRO: {opposite_side.upper()} @ ${target_price}")
        
        # Verificar se já existe ordem nesse preço e cancelar
        key = self._price_key(target_price)
        if key in self.placed_orders:
            self.logger.warning(f"⚠️ Já existe ordem em ${target_price} - cancelando antiga")
            old_order_id = self.placed_orders[key]
            result = self.auth.cancel_order(str(old_order_id), self.symbol)
            if result and result.get('success'):
                del self.placed_orders[key]
            time.sleep(0.5)  # Aguardar cancelamento
        
        # Criar nova ordem com mesma quantidade
        success = self._place_single_order(target_price, opposite_side, quantity)
        
        if success:

            self.logger.info(f"✅ Ordem de lucro criada: {opposite_side.upper()} {quantity} @ ${target_price}")
            
            # Calcular e mostrar lucro esperado
            if entry_side == 'buy':
                expected_profit = (target_price - entry_price) * quantity
            else:
                expected_profit = (entry_price - target_price) * quantity
            
            self.logger.info(f"💵 Lucro esperado: ${expected_profit:.2f}")
  
        else:
            self.logger.error(f"❌ Falha ao criar ordem de lucro em ${target_price}")

    def _check_price_in_range(self, price: float) -> bool:
        """Checks if price is within Pure Grid range"""
        
        range_min = float(os.getenv('RANGE_MIN', '0'))
        range_max = float(os.getenv('RANGE_MAX', '0'))
        
        if range_min > 0 and range_max > 0:
            in_range = range_min <= price <= range_max
            if not in_range:
                self.logger.warning(f"❌ Preço ${price} fora do range ${range_min}-${range_max}")
            return in_range
        
        return True
    
    def rebalance_grid(self, new_price: float) -> None:
        """Rebalances grid to new center price"""
        
        self.logger.info("🔄 Iniciando rebalanceamento do grid")
        
        # Cancelar ordens antigas
        self.cancel_all_orders()
        
        # Aguardar processamento dos cancelamentos na exchange (poll curto)
        timeout = 5.0
        poll_interval = 0.5
        elapsed = 0.0
        while elapsed < timeout:
            current_open = self.auth.get_open_orders(self.symbol)
            if not current_open or len(current_open) == 0:
                break
            time.sleep(poll_interval)
            elapsed += poll_interval
        if elapsed >= timeout:
            self.logger.warning("⚠️ Timeout aguardando cancelamentos na exchange; prosseguindo...")
        
        # Recalcular grid
        self.active_grid = self.calculator.calculate_grid_levels(new_price)
        self.grid_center = new_price
        
        # Colocar novas ordens
        self._place_grid_orders()
        
        self.logger.info(f"✅ Grid rebalanceado para ${new_price}")
    
    def handle_order_fill(self, order_id: str, fill_price: float, fill_quantity: float, side: str) -> None:
        """Processes order execution"""
        
        self.logger.info(f"🎯 Ordem executada: {order_id} - {side} {fill_quantity} @ ${fill_price}")
        
        # Atualizar posição
        self.position_mgr.update_position(self.symbol, side, fill_quantity, fill_price)
        
        # Remover ordem do tracking
        self.position_mgr.remove_order(order_id)
        
        # Remover do grid
        if fill_price in self.placed_orders:
            del self.placed_orders[fill_price]
        
        # Colocar ordem oposta (para realizar lucro)
        opposite_side = 'sell' if side == 'buy' else 'buy'
        target_price = self.calculator.calculate_profit_target(fill_price, side)
        
        self.logger.info(f"🎯 Colocando ordem oposta em ${target_price}")
        self._place_single_order(target_price, opposite_side)
    
    def cancel_all_orders(self) -> None:
        """Cancels all active orders"""
        
        self.logger.info(f"🚫 Cancelando {len(self.placed_orders)} ordens")
        
        for price, order_id in list(self.placed_orders.items()):
            try:
                # Tentar cancelar na API e garantir remoção do estado local
                try:
                    result = self.auth.cancel_order(str(order_id), self.symbol)
                    if result and result.get('success'):
                        self.logger.debug(f"✅ Ordem cancelada na API: {order_id}")
                    else:
                        self.logger.warning(f"⚠️ API cancel returned for {order_id}: {result}")
                except Exception as e:
                    self.logger.warning(f"⚠️ Falha ao cancelar na API {order_id}: {e}")
                
                # Remover do position manager (caso esteja registrado)
                removed = self.position_mgr.remove_order(str(order_id))
                if removed:
                    self.logger.debug(f"🔄 Ordem removida do position_mgr: {order_id}")
                else:
                    self.logger.debug(f"ℹ️ Ordem {order_id} não estava no position_mgr")
                
                # Remover qualquer referência em placed_orders (por segurança)
                self._remove_placed_by_order_id(order_id)
                
            except Exception as e:
                self.logger.error(f"Erro ao cancelar ordem {order_id}: {e}")
        
        self.placed_orders.clear()
    
    def pause_grid(self) -> None:
        """Pauses grid (cancels all orders)"""
        
        self.logger.warning("⏸️ Pausing grid")
        self.cancel_all_orders()
        self.grid_active = False
    
    def resume_grid(self, current_price: float) -> None:
        """Resumes grid"""
        
        self.logger.info("▶️ Resuming grid")
        self.initialize_grid(current_price)
    
    def reset_grid_completely(self, current_price: float) -> bool:
        """✨ NEW FEATURE: Completely resets grid, deleting all orders and recreating from scratch"""
        
        try:
            self.logger.info(f"🔄🔥 Iniciando reset completo do grid em ${current_price:,.2f}")
            
            # 1. Cancelar TODAS as ordens ativas
            self.logger.info("🚫 Canceling all active orders...")
            self.cancel_all_orders()
            
            # 2. Aguardar processamento dos cancelamentos com verificação robusta
            self.logger.info("⏳ Waiting for cancellations on exchange...")
            timeout = 10.0  # 10 segundos de timeout
            poll_interval = 0.5
            elapsed = 0.0
            
            while elapsed < timeout:
                current_open = self.auth.get_open_orders(self.symbol)
                if not current_open or len(current_open) == 0:
                    self.logger.info("✅ All orders canceled")
                    break
                    
                remaining = len([o for o in current_open if o.get('symbol') == self.symbol])
                self.logger.debug(f"⏳ Aguardando cancelamento de {remaining} ordens...")
                
                time.sleep(poll_interval)
                elapsed += poll_interval
                
            if elapsed >= timeout:
                remaining_orders = self.auth.get_open_orders(self.symbol)
                if remaining_orders and len(remaining_orders) > 0:
                    self.logger.warning(f"⚠️ Timeout: {len(remaining_orders)} ordens ainda ativas - prosseguindo mesmo assim")
                else:
                    self.logger.info("✅ Cancellations completed after timeout")
            
            # 3. Limpar completamente o estado interno
            self.logger.info("🧹 Clearing internal state...")
            with self._order_lock:
                self.placed_orders.clear()
            
            self.active_grid = {'buy_levels': [], 'sell_levels': []}
            self.grid_active = False
            self.grid_center = 0
            
            # 4. Aguardar um pouco mais para garantir que a exchange processou tudo
            time.sleep(2.0)
            
            # 5. Recriar o grid completamente do zero
            self.logger.info("🔧 Recreating grid completely from scratch...")
            success = self.initialize_grid(current_price)
            
            if success:
                grid_status = self.get_grid_status()
                self.logger.info(f"✅ Complete reset finished successfully!")
                self.logger.info(f"📊 Novo grid: {grid_status['active_orders']} ordens ativas")
                return True
            else:
                self.logger.error("❌ Failed to recreate grid after reset")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error during complete grid reset: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return False
    
    def get_grid_status(self) -> Dict:
        """Returns current grid status"""
        
        return {
            'active': self.grid_active,
            'center_price': self.grid_center,
            'strategy_type': self.strategy_type,
            'buy_levels': len(self.active_grid.get('buy_levels', [])),
            'sell_levels': len(self.active_grid.get('sell_levels', [])),
            'active_orders': len(self.placed_orders),
            'placed_orders': self.placed_orders
        }
    
    def _is_closing_trade(self, side: str, symbol: str) -> bool:
        """Checks if it's a closing trade (simplified)"""
        # Por enquanto, considerar que sell após buy é fechamento
        # Em implementação real, verificar posição atual
        return side == 'sell'

    def _get_entry_data(self, symbol: str, side: str) -> Optional[Dict]:
        """Gets trade entry data (simplified)"""
        # Em implementação real, buscar da base de dados de trades abertos
        # Por enquanto, simular
        return {
            'side': 'buy' if side == 'sell' else 'sell',
            'price': 50000.0,  # Preço de exemplo - implementar busca real
            'time': datetime.now() - timedelta(minutes=30)  # Tempo de exemplo
        }

    def _calculate_trade_pnl(self, entry_data: Dict, exit_price: float, quantity: float, exit_side: str) -> float:
        """Calculates trade PNL"""
        entry_price = entry_data['price']
        
        if exit_side == 'sell':  # Fechando posição long
            return (exit_price - entry_price) * quantity
        else:  # Fechando posição short
            return (entry_price - exit_price) * quantity

    def _get_grid_level(self, price: float) -> int:
        """Determines grid level based on price"""
        # Implementação simplificada
        return 1

    def get_performance_metrics(self) -> Dict:
        """Returns performance metrics"""
        # Para status regular, usar métricas básicas
        metrics = self.performance_tracker.calculate_metrics(include_advanced=False)
        
        # Adicionar métricas específicas do grid
        volatility_status = self.calculator.get_volatility_status()
        metrics.update(volatility_status)
        
        return metrics

    def print_performance_summary(self) -> None:
        """Prints performance summary"""
        # Para relatório completo, usar métricas avançadas
        summary = self.performance_tracker.get_performance_summary(include_advanced=True)
        
        # Adicionar informações específicas do grid
        volatility_status = self.calculator.get_volatility_status()
        
        grid_info = f"""
    🔧 GRID STATUS
    Current Spacing: {volatility_status.get('current_spacing', 0):.3f}%
    Volatility: {volatility_status.get('current_volatility', 0):.4f}
    Adaptive Mode: {'ON' if volatility_status.get('adaptive_mode') else 'OFF'}
    """
        
        self.logger.info(summary + grid_info)

    def get_grid_status_detailed(self) -> Dict:
        """Returns detailed grid status including limitations"""
        
        try:
            # Status básico
            status = self.get_grid_status()
            
            # Verificar se está no limite
            position_status = self.position_mgr.get_status_summary()
            orders_count = position_status.get('open_orders_count', 0)
            max_orders = position_status.get('max_orders', 20)
            
            # Calcular % de uso
            usage_percent = (orders_count / max_orders) * 100 if max_orders > 0 else 0
            
            # Adicionar informações extras
            status.update({
                'orders_usage_percent': usage_percent,
                'is_at_limit': usage_percent >= 95,
                'can_create_new_orders': usage_percent < 90,
                'pending_executions': orders_count > 0,
                'grid_health': 'healthy' if usage_percent < 80 else 'near_limit' if usage_percent < 95 else 'at_limit'
            })
            
            return status
            
        except Exception as e:
            self.logger.error(f"❌ Error getting detailed status: {e}")
            return self.get_grid_status()  # Fallback para status básico
    
    def shift_grid(self, new_center_price: float) -> None:
        """Shifts grid to new center price (Market Making)"""
        
        try:
            self.logger.info(f"🔄 Iniciando deslocamento do grid para ${new_center_price}")
            
            # 1. Cancelar ordens existentes
            cancelled_orders = 0
            for price, order_id in list(self.placed_orders.items()):
                try:
                    result = self.auth.cancel_order(str(order_id), self.symbol)
                    if result and result.get('success'):
                        cancelled_orders += 1
                        self.logger.debug(f"✅ Ordem cancelada: {order_id} @ ${price}")
                    else:
                        self.logger.warning(f"⚠️ Falha ao cancelar ordem {order_id} (API retornou: {result}")
                except Exception as e:
                    self.logger.error(f"❌ Erro ao cancelar ordem {order_id}: {e}")
                
                # Garantir remoção do estado local também
                try:
                    removed = self.position_mgr.remove_order(str(order_id))
                    if removed:
                        self.logger.debug(f"🔄 Removida do position_mgr: {order_id}")
                except Exception as e:
                    self.logger.debug(f"⚠️ Falha ao remover do position_mgr {order_id}: {e}")
                
                time.sleep(0.2)  # Delay entre cancelamentos
            
            self.logger.info(f"🚫 {cancelled_orders} orders canceled")
            
            # 2. Limpar tracking de ordens
            self.placed_orders.clear()
            
            # 3. Aguardar processamento dos cancelamentos
            time.sleep(1.0)
            
            # 4. Recalcular grid com novo centro
            self.active_grid = self.calculator.calculate_grid_levels(new_center_price)
            self.grid_center = new_center_price
            
            # 5. Colocar novas ordens
            success = self._place_grid_orders()
            
            if success:
                self.logger.info(f"✅ Grid deslocado com sucesso para ${new_center_price}")
                self.logger.info(f"📊 Novas ordens: {len(self.placed_orders)} total")
            else:
                self.logger.error(f"❌ Failed to place orders for new grid")
                
        except Exception as e:
            self.logger.error(f"❌ Error shifting grid: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())

    def _price_key(self, price: float) -> float:
        """Returns normalized price (used as key in placed_orders)"""
        try:
            return float(self.calculator.round_price(price))
        except Exception:
            return float(round(price, 8))

    def _remove_placed_by_order_id(self, order_id: str) -> None:
        """Utility to remove any placed_orders entry that references order_id"""
        with self._order_lock:
            for p, oid in list(self.placed_orders.items()):
                if str(oid) == str(order_id):
                    try:
                        del self.placed_orders[p]
                        self.logger.debug(f"🔄 Removido placed_orders entry {p} -> {order_id}")
                    except KeyError:
                        pass

    def _get_current_price_with_retry(self, max_retries: int = 3) -> float:
        """Gets price with automatic retry for greater robustness"""
        
        for attempt in range(max_retries):
            try:
                self.logger.debug(f"🔄 Tentativa {attempt + 1}/{max_retries} para obter preço de {self.symbol}")
                prices = self.auth.get_prices()
                
                if prices and prices.get('success') and 'data' in prices:
                    for item in prices['data']:
                        if item.get('symbol') == self.symbol:
                            price = item.get('mark') or item.get('mid')
                            if price:
                                price_float = float(price)
                                if price_float > 0:
                                    self.logger.debug(f"✅ Preço obtido com sucesso: ${price_float:.2f}")
                                    return price_float
                
                self.logger.debug(f"⚠️ Tentativa {attempt + 1} - preço não encontrado ou inválido")
                
                # Aguardar antes do próximo retry (exceto na última tentativa)
                if attempt < max_retries - 1:
                    time.sleep(1)
                    
            except Exception as e:
                self.logger.debug(f"⚠️ Tentativa {attempt + 1} falhou: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        self.logger.warning(f"❌ Falha ao obter preço após {max_retries} tentativas")
        return 0.0