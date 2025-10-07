"""
Pacifica API - Authentication System with AGENT WALLET (NO PRIVATE KEY)
Based on the functional method from test_agent_wallet_withoutkey.py
🔒 SECURITY: No longer requires main wallet private key
"""

import os
import time
import json
import base58
import requests
import logging
import traceback
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from solders.keypair import Keypair

# Load environment variables
load_dotenv()

# ============================================================================
# HELPER FUNCTIONS FOR AGENT WALLET SIGNATURE
# ============================================================================

def sort_json_keys(value):
    """Sorts JSON keys recursively"""
    if isinstance(value, dict):
        return {k: sort_json_keys(value[k]) for k in sorted(value.keys())}
    elif isinstance(value, list):
        return [sort_json_keys(item) for item in value]
    else:
        return value

def prepare_message(header, payload):
    """Prepares the message for signing"""
    if not all(k in header for k in ("type", "timestamp", "expiry_window")):
        raise ValueError("Header must have type, timestamp, and expiry_window")
    data = {**header, "data": payload}
    sorted_data = sort_json_keys(data)
    return json.dumps(sorted_data, separators=(",", ":"))

def sign_message(message: str, keypair: Keypair) -> str:
    """Signs the message using the agent's private key"""
    signature = keypair.sign_message(message.encode("utf-8"))
    return base58.b58encode(bytes(signature)).decode("utf-8")

# ============================================================================
# CONFIGURAÇÃO DO SISTEMA DE LOGGING
# ============================================================================

def setup_logging() -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"pacifica_bot_{timestamp}.log"
    debug_file = log_dir / f"pacifica_debug_{timestamp}.log"

    # Nível vem do .env (default = INFO)
    env_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, env_level, logging.INFO)

    log_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger('PacificaBot')
    logger.setLevel(log_level)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_format)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    simple_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(simple_format)
    logger.addHandler(console_handler)

    debug_handler = logging.FileHandler(debug_file, encoding='utf-8')
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(log_format)

    debug_logger = logging.getLogger('PacificaBot.Debug')
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.handlers.clear()
    debug_logger.addHandler(debug_handler)
    debug_logger.propagate = False

    logger.info("=" * 80)
    logger.info("🔒 Sistema de Agent Wallet inicializado (SEM PRIVATE KEY)")
    logger.info(f"Arquivo de log principal: {log_file}")
    logger.info(f"Arquivo de debug: {debug_file}")
    logger.info(f"Nível de log: {env_level}")
    logger.info("=" * 80)

    return logger

# ============================================================================
# AGENT WALLET AUTHENTICATION CLASS
# ============================================================================

class PacificaAuth:
    """
    Handles authentication and API communication with Pacifica exchange using Agent Wallet.
    
    🔒 SECURITY: Uses Agent Wallet for signing operations, eliminating the need to expose
    the main wallet's private key.
    """
    
    def __init__(self):
        """Initialize the PacificaAuth with Agent Wallet configuration."""
        self.logger = setup_logging()
        self.debug_logger = logging.getLogger('PacificaBot.Debug')

        self.base_url = os.getenv('API_ADDRESS', 'https://api.pacifica.fi/api/v1')
        self.ws_url = os.getenv('WS_BASE_URL', 'wss://ws.pacifica.fi/ws')

        # 🔒 SETUP AGENT WALLET (for signing)
        self.setup_agent_wallet()
        
        # 🔒 SETUP MAIN WALLET (public key only)
        self.setup_main_wallet()

        # 🆕 TIMESTAMP-BASED CACHE
        self._historical_cache = {}
        self._cache_ttl_seconds = 90  # Cache valid for 90 seconds (1.5 min)
        
        # 🆕 RATE LIMIT PROTECTION - Global request control
        self._last_kline_request_time = 0
        self._min_kline_delay_seconds = 1.2  # Minimum 1.2s between /kline requests
        
        # 🆕 CIRCUIT BREAKER - Overloaded API detection
        self._consecutive_errors = 0
        self._max_consecutive_errors = 3
        self._backoff_multiplier = 1.0
        self._max_backoff_multiplier = 4.0

        self.logger.info("✅ PacificaAuth initialized with Agent Wallet (SECURE)")

    def setup_agent_wallet(self):
        """Configures Agent Wallet for signing (WITHOUT exposing main private key)"""
        key_b58 = os.getenv("AGENT_PRIVATE_KEY_B58") or os.getenv("AGENT_PRIVATE_KEY")
        if not key_b58:
            raise ValueError("🔑 AGENT_PRIVATE_KEY_B58 not found in .env")
        
        try:
            raw = base58.b58decode(key_b58)
            if len(raw) == 32:
                self.agent_keypair = Keypair.from_seed(raw)
            elif len(raw) == 64:
                self.agent_keypair = Keypair.from_bytes(raw)
            else:
                raise ValueError(f"❌ Invalid agent key length (len={len(raw)})")
            
            self.agent_public_key = str(self.agent_keypair.pubkey())
            self.logger.info(f"✅ Agent Wallet configured: {self.agent_public_key}")
            
        except Exception as e:
            self.logger.error(f"❌ Error setting up Agent Wallet: {e}")
            raise

    def setup_main_wallet(self):
        """Configures Main Wallet (public key only - NO private key)"""
        self.main_public_key = os.getenv("MAIN_PUBLIC_KEY")
        if not self.main_public_key:
            raise ValueError("🔑 MAIN_PUBLIC_KEY not found in .env")
        
        # For backward compatibility with existing code
        self.public_key = self.main_public_key
        self.wallet_address = self.main_public_key
        
        self.logger.info(f"✅ Main Wallet (public): {self.main_public_key}")

    def create_order(self, symbol: str, side: str, amount: str, price: str, 
                     order_type: str = "GTC", reduce_only: bool = False,
                     take_profit: Dict = None, stop_loss: Dict = None) -> Optional[Dict]:
        """
        Creates an order with optional TP/SL using Agent Wallet
        🔒 SECURE: Does not require main wallet private key
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC-PERP')
            side: 'buy' or 'sell'
            amount: Order size (as string to preserve precision)
            price: Order price (as string to preserve precision)
            order_type: Order type (default: 'GTC' - Good Till Cancelled)
            reduce_only: If True, order will only reduce position
            take_profit: Optional dict with 'price' and 'amount' for take profit
            stop_loss: Optional dict with 'price' and 'amount' for stop loss
            
        Returns:
            Dict with order details or error information
        """
        # Validation: don't create order with zero or negative amount
        try:
            amount_float = float(amount)
        except Exception:
            amount_float = 0.0
        if amount_float <= 0:
            self.logger.warning(f"⚠️ Order not created: invalid amount ({amount})")
            return {'success': False, 'error': f'Order amount is too low: {amount}', 'code': 0}
        
        timestamp = int(time.time() * 1_000)
        
        signature_header = {
            "timestamp": timestamp,
            "expiry_window": 30000,
            "type": "create_order",
        }

        # Construct the signature payload (base)
        signature_payload = {
            "symbol": symbol,
            "price": str(price),
            "reduce_only": reduce_only,
            "amount": str(amount),
            "side": side,  # "bid" ou "ask"
            "tif": order_type,  # "GTC", "IOC", etc
            "client_order_id": str(uuid.uuid4()),
        }
        
        # 🆕 ADICIONAR TP/SL SE FORNECIDOS
        if take_profit:
            signature_payload["take_profit"] = {
                "stop_price": str(take_profit["stop_price"]),
                "limit_price": str(take_profit["limit_price"]),
                "client_order_id": str(uuid.uuid4())
            }
            self.logger.info(f"🎯 Take Profit: stop=${take_profit['stop_price']}, limit=${take_profit['limit_price']}")
        
        if stop_loss:
            signature_payload["stop_loss"] = {
                "stop_price": str(stop_loss["stop_price"]),
                "limit_price": str(stop_loss["limit_price"]),
                "client_order_id": str(uuid.uuid4())
            }
            self.logger.info(f"🛡️ Stop Loss: stop=${stop_loss['stop_price']}, limit=${stop_loss['limit_price']}")

        # 🔒 ASSINATURA COM AGENT WALLET
        message = prepare_message(signature_header, signature_payload)
        signature = sign_message(message, self.agent_keypair)

        # 🔒 REQUEST COM AGENT WALLET
        request_data = {
            "account": self.main_public_key,           # 🔒 Main wallet (public)
            "agent_wallet": self.agent_public_key,    # 🔒 Agent wallet (public)
            "signature": signature,                   # 🔒 Assinado pelo agent
            "timestamp": signature_header["timestamp"],
            "expiry_window": signature_header["expiry_window"],
            **signature_payload,
        }

        order_desc = f"{side} {amount} {symbol} @ {price}"
        if take_profit or stop_loss:
            order_desc += " com TP/SL"
            
        self.logger.info(f"📄 Criando ordem: {order_desc}")
        self.debug_logger.debug(f"Request data: {json.dumps(request_data, indent=2)}")
        self.debug_logger.debug(f"Message: {message}")
        self.debug_logger.debug(f"Signature: {signature}")

        try:
            url = f"{self.base_url}/orders/create"
            headers = {"Content-Type": "application/json"}
            
            response = requests.post(url, json=request_data, headers=headers, timeout=15)
            self.logger.info(f"🔥 POST {url} -> {response.status_code}")
            self.debug_logger.debug(f"Response: {response.text}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    self.logger.info("✅ Ordem criada com sucesso!")
                    
                    # Log detalhado do resultado
                    if 'data' in data:
                        order_data = data['data']
                        main_order_id = order_data.get('order_id', 'N/A')
                        self.logger.info(f"📋 Ordem principal ID: {main_order_id}")
                        
                        # Log IDs de TP/SL se criados
                        if 'take_profit_order_id' in order_data:
                            tp_id = order_data['take_profit_order_id']
                            self.logger.info(f"🎯 Take Profit ID: {tp_id}")
                            
                        if 'stop_loss_order_id' in order_data:
                            sl_id = order_data['stop_loss_order_id']
                            self.logger.info(f"🛡️ Stop Loss ID: {sl_id}")
                    
                    self.debug_logger.debug(json.dumps(data, indent=2))
                    return data
                except json.JSONDecodeError:
                    self.logger.error("❌ Failed to decode JSON response")
            else:
                self.logger.error(f"❌ Failed to create order - Status: {response.status_code}")
                self.logger.error(f"Response: {response.text}")

        except Exception as e:
            self.logger.error(f"❌ Request error: {e}")
            self.debug_logger.error(traceback.format_exc())

        return None

    def create_order_with_auto_tpsl(self, symbol: str, side: str, amount: str, price: str,
                                   tp_percent: float = None, sl_percent: float = None,
                                   order_type: str = "GTC", reduce_only: bool = False) -> Optional[Dict]:
        """
        Creates an order with automatically calculated TP/SL using Agent Wallet
        🔒 SECURE: Does not require main wallet private key
        """
        
        entry_price = float(price)
        take_profit = None
        stop_loss = None
        
        # 🆕 GET TICK_SIZE FOR SYMBOL
        tick_size = self._get_tick_size(symbol)
        
        if tp_percent:
            if side == 'bid':  # Buying - TP above price
                tp_stop = entry_price * (1 + tp_percent / 100)
                tp_limit = tp_stop * 0.999
            else:  # Selling - TP below price
                tp_stop = entry_price * (1 - tp_percent / 100)
                tp_limit = tp_stop * 1.001
            
            # 🔧 ROUND TO TICK_SIZE
            tp_stop_rounded = self._round_to_tick_size(tp_stop, tick_size)
            tp_limit_rounded = self._round_to_tick_size(tp_limit, tick_size)
                
            take_profit = {
                "stop_price": f"{tp_stop_rounded}",
                "limit_price": f"{tp_limit_rounded}"
            }
            
            self.logger.debug(f"🎯 TP calculated: {tp_stop:.6f} -> {tp_stop_rounded} (tick_size: {tick_size})")
        
        if sl_percent:
            if side == 'bid':  # Buying - SL below price
                sl_stop = entry_price * (1 - sl_percent / 100)
                sl_limit = sl_stop * 0.999
            else:  # Selling - SL above price
                sl_stop = entry_price * (1 + sl_percent / 100)
                sl_limit = sl_stop * 1.001
            
            # 🔧 ROUND TO TICK_SIZE
            sl_stop_rounded = self._round_to_tick_size(sl_stop, tick_size)
            sl_limit_rounded = self._round_to_tick_size(sl_limit, tick_size)
                
            stop_loss = {
                "stop_price": f"{sl_stop_rounded}",
                "limit_price": f"{sl_limit_rounded}"
            }
            
            self.logger.debug(f"🛡️ SL calculated: {sl_stop:.6f} -> {sl_stop_rounded} (tick_size: {tick_size})")
        
        return self.create_order(
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            order_type=order_type,
            reduce_only=reduce_only,
            take_profit=take_profit,
            stop_loss=stop_loss
        )

    def cancel_order(self, order_id: str, symbol: str = None) -> dict:
        """
        Cancels a specific order following the exact official documentation
        """
        
        timestamp = int(time.time() * 1_000)
        
        # Use default symbol if not provided
        if not symbol:
            symbol = os.getenv('SYMBOL', 'BTC')
        
        # Create payload exactly as per documentation
        signature_header = {
            "timestamp": timestamp,
            "expiry_window": 30000,
            "type": "cancel_order",
        }
        
        signature_payload = {
            "symbol": symbol,
            "order_id": int(order_id)  # API expects integer
        }
        
        # 🔒 SIGN WITH AGENT WALLET
        message = prepare_message(signature_header, signature_payload)
        signature = sign_message(message, self.agent_keypair)
        
        # 🔒 REQUEST EXACTLY AS PER DOCUMENTATION
        # 🔒 REQUEST FOLLOWING SAME FORMAT AS create_order
        payload = {
            "account": self.main_public_key,           # 🔒 Main wallet (public)
            "agent_wallet": self.agent_public_key,    # 🔒 Agent wallet (public) - WAS MISSING!
            "signature": signature,                   # 🔒 Signed by agent
            "timestamp": timestamp,
            "expiry_window": 30000,                   # 🔒 Expiry window - WAS MISSING!
            "symbol": symbol,
            "order_id": int(order_id)  # As integer per documentation
        }
        
        # 🔧 DEBUG: Log payload for analysis
        self.logger.debug(f"📤 Cancellation payload: {payload}")
        
        try:
            url = f"{self.base_url}/orders/cancel"
            response = requests.post(
                url, 
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            self.logger.info(f"🚫 Cancel order {order_id} -> {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    self.logger.info(f"✅ Order {order_id} cancelled")
                    return {"success": True, "data": data}
                except ValueError:
                    # If can't parse JSON but status is 200
                    self.logger.info(f"✅ Order {order_id} cancelled (no JSON response)")
                    return {"success": True, "data": None}
            else:
                error_text = response.text
                self.logger.error(f"❌ Failed to cancel {order_id}: {error_text}")
                
                # Detailed error logging for debug
                self.logger.debug(f"🔧 Response headers: {dict(response.headers)}")
                self.logger.debug(f"🔧 Request URL: {url}")
                
                try:
                    error_data = response.json()
                    return {"success": False, "error": error_data}
                except ValueError:
                    return {"success": False, "error": error_text}
                    
        except requests.exceptions.Timeout:
            self.logger.error(f"❌ Timeout ao cancelar {order_id}")
            return {"success": False, "error": "Timeout"}
        except Exception as e:
            self.logger.error(f"❌ Erro ao cancelar {order_id}: {e}")
            return {"success": False, "error": str(e)}

    def cancel_all_orders(self, symbol: str = None) -> dict:
        """
        Cancela todas as ordens de um símbolo específico ou todas as ordens
        """
        
        try:
            # Buscar todas as ordens abertas
            all_orders = self.get_open_orders()
            
            if not all_orders:
                return {"success": True, "message": "Nenhuma ordem para cancelar", "cancelled": 0, "failed": 0}
            
            # Filtrar por símbolo se especificado
            if symbol:
                orders_to_cancel = [order for order in all_orders if order.get('symbol') == symbol]
                self.logger.info(f"🚫 Cancelando todas as ordens de {symbol}: {len(orders_to_cancel)} ordens")
            else:
                orders_to_cancel = all_orders
                self.logger.info(f"🚫 Cancelando TODAS as ordens: {len(orders_to_cancel)} ordens")
            
            if not orders_to_cancel:
                return {"success": True, "message": f"Nenhuma ordem de {symbol} para cancelar", "cancelled": 0, "failed": 0}
            
            cancelled_count = 0
            failed_count = 0
            errors = []
            
            for order in orders_to_cancel:
                order_id = order.get('order_id')
                order_symbol = order.get('symbol', symbol or 'UNKNOWN')
                
                if order_id:
                    result = self.cancel_order(str(order_id), order_symbol)
                    
                    if result and result.get('success'):
                        cancelled_count += 1
                    else:
                        failed_count += 1
                        error_msg = result.get('error', 'Erro desconhecido') if result else 'Sem resposta'
                        errors.append(f"Ordem {order_id}: {error_msg}")
                    
                    time.sleep(0.1)  # Delay entre cancelamentos
            
            self.logger.info(f"📊 Resultado: {cancelled_count} canceladas, {failed_count} falharam")
            
            return {
                "success": cancelled_count > 0 or failed_count == 0,
                "cancelled": cancelled_count,
                "failed": failed_count,
                "errors": errors
            }
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao cancelar todas as ordens: {e}")
            return {"success": False, "error": str(e)}

    def cancel_stop_orders(self, symbol: str = None) -> dict:
        """
        Cancela apenas ordens de Stop Loss e Take Profit
        """
        
        try:
            # Buscar todas as ordens abertas
            all_orders = self.get_open_orders()
            
            if not all_orders:
                return {"success": True, "message": "Nenhuma ordem para cancelar", "cancelled": 0, "failed": 0}
            
            # Filtrar ordens TP/SL
            stop_orders = []
            for order in all_orders:
                order_type = order.get('type', '')
                order_subtype = order.get('subType', '')
                order_label = str(order.get('label', '')).lower()
                order_symbol = order.get('symbol')
                
                # Verificar se é TP/SL
                is_stop_order = (
                    order_type in ['TAKE_PROFIT', 'STOP_LOSS'] or
                    order_subtype in ['take_profit', 'stop_loss'] or
                    'tp' in order_label or 'sl' in order_label
                )
                
                # Filtrar por símbolo se especificado
                if is_stop_order and (not symbol or order_symbol == symbol):
                    stop_orders.append(order)
            
            if not stop_orders:
                symbol_msg = f"de {symbol}" if symbol else ""
                return {"success": True, "message": f"Nenhuma ordem TP/SL {symbol_msg} para cancelar", "cancelled": 0, "failed": 0}
            
            self.logger.info(f"🚫 Cancelando ordens TP/SL: {len(stop_orders)} ordens")
            
            cancelled_count = 0
            failed_count = 0
            errors = []
            
            for order in stop_orders:
                order_id = order.get('order_id')
                order_symbol = order.get('symbol', symbol or 'UNKNOWN')
                
                if order_id:
                    result = self.cancel_order(str(order_id), order_symbol)
                    
                    if result and result.get('success'):
                        cancelled_count += 1
                    else:
                        failed_count += 1
                        error_msg = result.get('error', 'Erro desconhecido') if result else 'Sem resposta'
                        errors.append(f"Ordem {order_id}: {error_msg}")
                    
                    time.sleep(0.1)  # Delay entre cancelamentos
            
            self.logger.info(f"📊 Resultado TP/SL: {cancelled_count} canceladas, {failed_count} falharam")
            
            return {
                "success": cancelled_count > 0 or failed_count == 0,
                "cancelled": cancelled_count,
                "failed": failed_count,
                "errors": errors
            }
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao cancelar ordens TP/SL: {e}")
            return {"success": False, "error": str(e)}

    def get_account_info(self) -> Optional[Dict]:
        """
        Busca informações da conta (endpoint público)
        Endpoint: GET /api/v1/account?account={wallet}
        """
        
        url = f"{self.base_url}/account"
        params = {'account': self.main_public_key}
        
        try:
            self.logger.info("=" * 70)
            self.logger.info("🔍 REQUISIÇÃO GET ACCOUNT INFO")
            self.logger.info(f"   URL: {url}")
            self.logger.info(f"   Wallet: {self.main_public_key}")
            self.logger.info("=" * 70)
            
            response = requests.get(
                url, 
                params=params,
                headers={"Accept": "*/*"},
                timeout=10
            )
            
            self.logger.info(f"📥 Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Log da estrutura recebida
                self.logger.info("✅ Resposta recebida com sucesso")
                self.logger.info(f"   Success: {data.get('success')}")
                self.logger.info(f"   Error: {data.get('error')}")
                
                # 🔧 SUPORTE PARA AMBOS FORMATOS: ARRAY OU OBJETO
                if 'data' in data:
                    raw_data = data['data']
                    account_item = None
                    
                    if isinstance(raw_data, list):
                        self.logger.info(f"   Data: ARRAY com {len(raw_data)} elemento(s)")
                        if len(raw_data) > 0:
                            account_item = raw_data[0]
                        else:
                            self.logger.warning("⚠️ Array vazio - sem dados de conta")
                    
                    elif isinstance(raw_data, dict):
                        self.logger.info("   Data: OBJETO (formato direto)")
                        account_item = raw_data
                    
                    else:
                        self.logger.warning(f"⚠️ Formato inesperado: {type(raw_data)}")
                        self.logger.info(f"   Type: {type(raw_data)}")
                    
                    # Processar dados se encontrados
                    if account_item:
                        self.logger.info("   Dados da conta:")
                        self.logger.info(f"      balance: {account_item.get('balance', 'N/A')}")
                        self.logger.info(f"      account_equity: {account_item.get('account_equity', 'N/A')}")
                        self.logger.info(f"      available_to_spend: {account_item.get('available_to_spend', 'N/A')}")
                        self.logger.info(f"      total_margin_used: {account_item.get('total_margin_used', 'N/A')}")
                        self.logger.info(f"      positions_count: {account_item.get('positions_count', 'N/A')}")
                        self.logger.info(f"      orders_count: {account_item.get('orders_count', 'N/A')}")
                    else:
                        self.logger.warning("⚠️ Nenhum dado de conta encontrado")
                else:
                    self.logger.warning("⚠️ Chave 'data' não encontrada na resposta")
                
                self.logger.info("=" * 70)
                return data
                
            elif response.status_code == 401:
                self.logger.warning("🔒 Erro 401 - Não autorizado")
                self.logger.info("   Tentando método autenticado...")
                return self._get_account_info_authenticated()
                
            else:
                self.logger.error(f"❌ Erro HTTP {response.status_code}")
                self.logger.error(f"   Response: {response.text[:500]}")
                return None
                
        except requests.Timeout:
            self.logger.error("❌ Timeout na requisição (10s)")
            return None
            
        except requests.RequestException as e:
            self.logger.error(f"❌ Erro de rede: {e}")
            return None
            
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ Erro ao decodificar JSON: {e}")
            self.logger.error(f"   Response raw: {response.text[:500]}")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Erro inesperado: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    def get_open_orders(self, symbol: str = None) -> Optional[List]:
        """
        Busca ordens abertas da conta usando Agent Wallet se necessário
        🔒 SEGURO: Tenta público primeiro, depois Agent Wallet se precisar
        """
        
        # Primeiro tentar sem autenticação
        url = f"{self.base_url}/orders?account={self.main_public_key}"
        
        self.logger.debug(f"🔍 Buscando ordens abertas para account: {self.main_public_key}")
        
        try:
            response = requests.get(url, timeout=10)
            self.logger.info(f"📋 GET {url} -> {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Processar resposta
                if isinstance(data, dict) and 'data' in data:
                    orders = data.get('data', [])
                elif isinstance(data, list):
                    orders = data
                else:
                    orders = []
                
                self.logger.info(f"✅ {len(orders)} ordens abertas encontradas")
                
                # Filtrar por símbolo se especificado
                if symbol and orders:
                    filtered_orders = [o for o in orders if o.get('symbol') == symbol]
                    self.logger.info(f"📊 {len(filtered_orders)} ordens para {symbol}")
                    return filtered_orders
                
                return orders
                
            elif response.status_code == 401:
                # Se precisar de autenticação, usar Agent Wallet
                self.logger.info("🔒 Endpoint requer autenticação - usando Agent Wallet")
                return self._get_open_orders_authenticated(symbol)
            else:
                self.logger.error(f"❌ Erro {response.status_code}: {response.text[:200]}")
                return None
        
        except Exception as e:
            self.logger.error(f"❌ Erro: {e}")
            return None

    def _get_open_orders_authenticated(self, symbol: str = None) -> Optional[List]:
        """
        Busca ordens abertas com autenticação Agent Wallet
        """
        
        timestamp = int(time.time() * 1_000)
        
        signature_header = {
            "timestamp": timestamp,
            "expiry_window": 30000,
            "type": "get_orders",
        }
        
        signature_payload = {
            "account": self.main_public_key,
        }
        
        if symbol:
            signature_payload["symbol"] = symbol
        
        # 🔒 ASSINATURA COM AGENT WALLET
        message = prepare_message(signature_header, signature_payload)
        signature = sign_message(message, self.agent_keypair)
        
        # 🔒 REQUEST COM AGENT WALLET
        request_data = {
            "account": self.main_public_key,
            "agent_wallet": self.agent_public_key,
            "signature": signature,
            "timestamp": timestamp,
            "expiry_window": 30000,
        }
        
        try:
            url = f"{self.base_url}/orders"
            response = requests.post(url, json=request_data, timeout=10)
            self.logger.info(f"📋 POST /orders (auth) -> {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                orders = data.get('data', []) if isinstance(data, dict) else data
                self.logger.info(f"✅ {len(orders)} ordens obtidas (autenticado)")
                return orders
            else:
                self.logger.error(f"❌ Erro na busca autenticada: {response.text}")
                return None
        except Exception as e:
            self.logger.error(f"❌ Erro na requisição autenticada: {e}")
            return None

    # ============================================================================
    # FUNÇÕES PÚBLICAS (NÃO PRECISAM DE AUTENTICAÇÃO)
    # ============================================================================

    def test_connection(self) -> bool:
        """Testa a conexão usando get_funding_history (endpoint público)"""
        try:
            self.logger.info("🔍 Testando conexão com API...")
            
            # Usar endpoint público que funciona
            result = self.get_funding_history("BTC")
            
            if result:
                self.logger.info("✅ Conexão com API funcionando!")
                return True
            else:
                self.logger.error("❌ Falha no teste de conexão")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Erro no teste de conexão: {e}")
            return False

    def get_funding_history(self, symbol: str = "BTC", limit: int = 10, offset: int = 0) -> Optional[Dict]:
        """Busca histórico de funding rate (endpoint público)"""
        url = f"{self.base_url}/funding_rate/history"
        params = {'symbol': symbol, 'limit': limit, 'offset': offset}
        try:
            response = requests.get(url, params=params, timeout=10)
            self.logger.info(f"📊 GET /funding_rate/history -> {response.status_code}")
            self.debug_logger.debug(response.text[:500])
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            self.logger.error(f"❌ Erro ao buscar funding history: {e}")
            return None

    def get_prices(self) -> Optional[Dict]:
        """Busca preços atuais (endpoint público)"""
        url = f"{self.base_url}/info/prices"
        try:
            response = requests.get(url, timeout=10)
            self.logger.info(f"📈 GET /info/prices -> {response.status_code}")
            self.debug_logger.debug(f"Response: {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                
                # ✅ VALIDAÇÃO OPCIONAL - não quebra código existente
                if isinstance(data, dict) and 'success' in data:
                    if not data.get('success'):
                        self.logger.warning(f"⚠️ API retornou success=false: {data.get('message', 'sem mensagem')}")
                        # RETORNAR data MESMO ASSIM para compatibilidade
                        # O código que chama já valida 'data' internamente
                
                self.logger.info("✅ Preços obtidos com sucesso!")
                return data  # ✅ RETORNA SEMPRE (compatibilidade 100%)
            else:
                self.logger.error(f"❌ Erro ao buscar preços - Status: {response.status_code}")
                self.logger.error(f"Response: {response.text}")
                return None
        except Exception as e:
            self.logger.error(f"❌ Erro na requisição de preços: {e}")
            return None

    def get_symbol_info(self, symbol: str = None) -> Optional[Dict]:
        """Busca informações específicas de um símbolo (endpoint público)"""
        url = f"{self.base_url}/info"
        try:
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # API retorna {"success": true, "data": [...]}
                if isinstance(data, dict) and 'data' in data:
                    items = data['data']
                elif isinstance(data, list):
                    items = data
                else:
                    self.logger.error(f"Formato inesperado da API: {type(data)}")
                    return None
                
                if symbol and isinstance(items, list):
                    for item in items:
                        if item.get('symbol') == symbol:
                            tick = item.get('tick_size')
                            lot = item.get('lot_size')
                            self.logger.info(f"✅ {symbol} encontrado: tick_size={tick}, lot_size={lot}")
                            return item
                    
                    # Se não encontrou
                    available = [x.get('symbol') for x in items[:5]]
                    self.logger.error(f"❌ Símbolo '{symbol}' não encontrado. Primeiros: {available}")
                    return None
                
                return items if isinstance(items, list) else None
                
        except Exception as e:
            self.logger.error(f"Erro ao buscar symbol info: {e}")
            return None

    def get_market_info(self, symbol: str = "BTC") -> Optional[Dict]:
        """Busca informações do mercado (endpoint público)"""
        url = f"{self.base_url}/info"
        try:
            response = requests.get(url, timeout=10)
            self.logger.info(f"📈 GET /info -> {response.status_code}")
            self.debug_logger.debug(f"Response: {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                self.logger.info("✅ Informações do mercado obtidas com sucesso!")
                
                # Se um símbolo específico foi solicitado, filtrar apenas esse símbolo
                if symbol and isinstance(data, list):
                    for item in data:
                        if item.get('symbol') == symbol:
                            return item
                    self.logger.warning(f"❌ Símbolo {symbol} não encontrado nos dados do mercado")
                    return None
                
                return data
            else:
                self.logger.error(f"❌ Erro ao buscar informações do mercado - Status: {response.status_code}")
                self.logger.error(f"Response: {response.text}")
                return None
        except Exception as e:
            self.logger.error(f"❌ Erro na requisição de market info: {e}")
            return None

    def get_historical_data(self, symbol: str, interval: str = "1m", 
                       periods: int = 30, max_retries: int = 3) -> Optional[List[float]]:
        """
        Busca histórico de preços da API Pacifica com:
        ✅ Cache inteligente (90s TTL)
        ✅ Rate limit protection (1.2s entre requests)
        ✅ Circuit breaker (pausa quando API sobrecarregada)
        ✅ Backoff exponencial agressivo
        
        Args:
            symbol: Símbolo (ex: BTC, ETH, SOL)
            interval: Intervalo (1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 8h, 12h, 1d)
            periods: Quantidade de períodos (padrão: 30)
            max_retries: Máximo de tentativas (padrão: 3)
            
        Returns:
            Lista de preços de fechamento ou None se falhar
        """
        
        # 🆕 STEP 1: VERIFICAR CACHE PRIMEIRO (evita chamadas desnecessárias)
        cache_key = f"{symbol}_{interval}_{periods}"
        
        if cache_key in self._historical_cache:
            cached_data, cache_timestamp = self._historical_cache[cache_key]
            cache_age_seconds = time.time() - cache_timestamp
            
            if cache_age_seconds < self._cache_ttl_seconds:
                self.logger.debug(f"🎯 Cache HIT: {symbol} (idade: {cache_age_seconds:.1f}s)")
                return cached_data
            else:
                self.logger.debug(f"⏰ Cache EXPIRED: {symbol} (idade: {cache_age_seconds:.1f}s)")
        
        # 🆕 STEP 2: RATE LIMIT GLOBAL (forçar delay entre requisições)
        time_since_last_request = time.time() - self._last_kline_request_time
        
        # Aplicar backoff multiplier se houver erros consecutivos
        effective_delay = self._min_kline_delay_seconds * self._backoff_multiplier
        delay_needed = effective_delay - time_since_last_request
        
        if delay_needed > 0:
            self.logger.debug(f"⏳ Rate limit global: aguardando {delay_needed:.2f}s para {symbol}")
            time.sleep(delay_needed)
        
        # 🆕 STEP 3: CIRCUIT BREAKER (pausar se muitos erros consecutivos)
        if self._consecutive_errors >= self._max_consecutive_errors:
            circuit_pause = 5.0 * self._backoff_multiplier
            self.logger.warning(
                f"⚠️ CIRCUIT BREAKER ativo! "
                f"{self._consecutive_errors} erros consecutivos. "
                f"Pausando {circuit_pause:.1f}s antes de {symbol}"
            )
            time.sleep(circuit_pause)
        
        # 🆕 STEP 4: FAZER REQUISIÇÃO COM RETRY MELHORADO
        for attempt in range(max_retries):
            try:
                from datetime import datetime, timedelta
                
                # Converter intervalo para minutos
                interval_minutes = {
                    '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
                    '1h': 60, '2h': 120, '4h': 240, '8h': 480, 
                    '12h': 720, '1d': 1440
                }
                
                minutes = interval_minutes.get(interval, 1)
                start_time = int((datetime.now() - timedelta(minutes=periods * minutes)).timestamp() * 1000)
                
                # Endpoint público da Pacifica
                url = f"{self.base_url}/kline"
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'start_time': start_time
                }
                
                # 🆕 Marcar timestamp desta requisição
                self._last_kline_request_time = time.time()
                
                # 🆕 Timeout aumentado para 15s (API pode estar lenta)
                response = requests.get(url, params=params, timeout=15)
                
                # ============================================================
                # TRATAMENTO DE ERROS COM BACKOFF AGRESSIVO
                # ============================================================
                
                if response.status_code == 429:  # Rate limit exceeded
                    self._consecutive_errors += 1
                    self._backoff_multiplier = min(
                        self._max_backoff_multiplier, 
                        self._backoff_multiplier * 1.5
                    )
                    
                    retry_delay = 3 ** attempt  # Exponencial agressivo: 3s, 9s, 27s
                    self.logger.warning(
                        f"⚠️ Rate limit {symbol} - "
                        f"Tentativa {attempt+1}/{max_retries}, "
                        f"aguardando {retry_delay}s "
                        f"(backoff: {self._backoff_multiplier:.1f}x)"
                    )
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        self.logger.error(f"❌ Rate limit persistente: {symbol}")
                        return None
                        
                elif response.status_code == 500:  # Server error
                    self._consecutive_errors += 1
                    self._backoff_multiplier = min(
                        self._max_backoff_multiplier, 
                        self._backoff_multiplier * 1.3
                    )
                    
                    # 🆕 Delay MUITO mais agressivo para erro 500
                    retry_delay = 3.0 * (attempt + 1)  # 3s, 6s, 9s
                    self.logger.warning(
                        f"⚠️ Server error {symbol} (500) - "
                        f"Tentativa {attempt+1}/{max_retries}, "
                        f"aguardando {retry_delay}s "
                        f"(backoff: {self._backoff_multiplier:.1f}x)"
                    )
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        self.logger.error(f"❌ Server error persistente: {symbol}")
                        return None
                        
                elif response.status_code == 503:  # Service unavailable
                    self._consecutive_errors += 1
                    self._backoff_multiplier = min(
                        self._max_backoff_multiplier, 
                        self._backoff_multiplier * 1.5
                    )
                    
                    retry_delay = 4.0 * (attempt + 1)  # 4s, 8s, 12s
                    self.logger.warning(
                        f"⚠️ Service unavailable {symbol} (503) - "
                        f"Tentativa {attempt+1}/{max_retries}, "
                        f"aguardando {retry_delay}s"
                    )
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    else:
                        return None
                        
                elif response.status_code == 200:
                    # 🆕 SUCESSO - Resetar contadores de erro
                    self._consecutive_errors = 0
                    
                    # 🆕 Reduzir backoff gradualmente (recuperação suave)
                    self._backoff_multiplier = max(1.0, self._backoff_multiplier * 0.9)
                    
                    self.logger.debug(
                        f"📊 GET /kline {symbol} {interval} -> 200 "
                        f"(tentativa {attempt+1}, backoff: {self._backoff_multiplier:.1f}x)"
                    )
                    
                    data = response.json()
                    
                    if data.get('success') and 'data' in data:
                        klines = data['data']
                        
                        # Extrair preços de fechamento (campo 'c')
                        prices = []
                        for kline in klines:
                            close_price = float(kline.get('c', 0))
                            if close_price > 0:
                                prices.append(close_price)
                        
                        if len(prices) >= periods * 0.8:  # Aceitar se tiver 80%+ dos dados
                            # 🆕 ARMAZENAR NO CACHE
                            self._historical_cache[cache_key] = (prices, time.time())
                            
                            self.logger.debug(
                                f"✅ Histórico obtido: {len(prices)} preços de {symbol} "
                                f"(cache armazenado)"
                            )
                            return prices
                        else:
                            self.logger.warning(
                                f"⚠️ Dados insuficientes: {symbol} "
                                f"({len(prices)} < {int(periods * 0.8)} necessários)"
                            )
                            return None
                    else:
                        self.logger.warning(f"⚠️ Resposta sem dados: {symbol}")
                        if attempt < max_retries - 1:
                            time.sleep(2.0)  # 🆕 Delay maior antes de retry
                            continue
                        return None
                else:
                    # Outros códigos de erro
                    self._consecutive_errors += 1
                    self.logger.warning(
                        f"⚠️ Erro HTTP {response.status_code} para {symbol}: "
                        f"{response.text[:200]}"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(2.0)
                        continue
                    return None
                    
            except requests.exceptions.Timeout:
                self._consecutive_errors += 1
                retry_delay = 2.0 * (attempt + 1)  # 2s, 4s, 6s
                self.logger.warning(
                    f"⚠️ Timeout {symbol} - "
                    f"Tentativa {attempt+1}/{max_retries}, "
                    f"aguardando {retry_delay}s"
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
                
            except requests.exceptions.ConnectionError:
                self._consecutive_errors += 1
                retry_delay = 3.0 * (attempt + 1)  # 3s, 6s, 9s
                self.logger.warning(
                    f"⚠️ Connection error {symbol} - "
                    f"Tentativa {attempt+1}/{max_retries}, "
                    f"aguardando {retry_delay}s"
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
                
            except Exception as e:
                self._consecutive_errors += 1
                self.logger.error(f"❌ Erro inesperado: {symbol} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2.0)
                    continue
                return None
        
        # Se chegou aqui, todas as tentativas falharam
        self.logger.error(f"❌ Falha completa: {symbol} após {max_retries} tentativas")
        return None

    # ============================================================================
    # FUNÇÕES AUXILIARES E CACHE
    # ============================================================================

    def _get_tick_size(self, symbol: str) -> float:
        """Obtém tick_size específico do símbolo"""
        try:
            info = self.get_symbol_info(symbol)
            if info and 'tick_size' in info:
                tick_size = float(info['tick_size'])
                self.logger.debug(f"🔍 {symbol} tick_size: {tick_size}")
                return tick_size
        except Exception as e:
            self.logger.warning(f"⚠️ Erro ao obter tick_size para {symbol}: {e}")
        
        # Fallback para valores conhecidos
        tick_sizes = {
            'BTC': 0.00001,
            'ETH': 0.0001, 
            'SOL': 0.01,
            'BNB': 0.001,
            'AVAX': 0.001,
            'LTC': 0.001
        }
        fallback = tick_sizes.get(symbol, 0.00001)
        self.logger.warning(f"⚠️ Usando tick_size fallback para {symbol}: {fallback}")
        return fallback

    def _get_lot_size(self, symbol: str) -> float:
        """Obtém lot_size específico do símbolo"""
        try:
            info = self.get_symbol_info(symbol)
            if info and 'lot_size' in info:
                lot_size = float(info['lot_size'])
                self.logger.debug(f"🔍 {symbol} lot_size: {lot_size}")
                return lot_size
        except Exception as e:
            self.logger.warning(f"⚠️ Erro ao obter lot_size para {symbol}: {e}")
        
        # Fallback para valores conhecidos
        lot_sizes = {
            'BTC': 0.001,
            'ETH': 0.01,
            'SOL': 0.01,
            'BNB': 0.01,
            'AVAX': 0.01,
            'LTC': 0.01,
            'ENA': 1.0,      # ✅ ENA usa números inteiros
            'DOGE': 1.0,
            'XRP': 1.0,
            'PENGU': 1.0,
            'PUMP': 1.0,
            'FARTCOIN': 1.0
        }
        fallback = lot_sizes.get(symbol, 0.01)
        self.logger.warning(f"⚠️ Usando lot_size fallback para {symbol}: {fallback}")
        return fallback

    def _round_to_lot_size(self, quantity: float, lot_size: float) -> float:
        """
        Arredonda quantidade para múltiplo válido do lot_size
        """
        if lot_size >= 1:
            # Para lot_size >= 1, usar números inteiros
            return float(int(round(quantity / lot_size) * lot_size))
        else:
            # Para lot_size < 1, usar arredondamento decimal com melhor precisão
            from decimal import Decimal, ROUND_HALF_UP
            
            # Converter para Decimal para evitar erros de precisão
            qty_dec = Decimal(str(quantity))
            lot_dec = Decimal(str(lot_size))
            
            # Calcular múltiplos e arredondar
            multiples = (qty_dec / lot_dec).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            result = float(multiples * lot_dec)
            
            # Determinar precisão baseada no lot_size
            if lot_size == 0.01:
                return round(result, 2)
            elif lot_size == 0.001:
                return round(result, 3)
            elif lot_size == 0.0001:
                return round(result, 4)
            else:
                return round(result, 8)

    def _round_to_tick_size(self, price: float, tick_size: float) -> float:
        """
        Arredonda preço para múltiplo válido do tick_size
        🔧 BASEADO NO grid_calculator.py que já funciona
        """
        
        if tick_size >= 1:
            return float(round(price))
        
        # Usar Decimal para evitar erros de precisão
        from decimal import Decimal, ROUND_HALF_UP
        
        price_dec = Decimal(str(price))
        tick_dec = Decimal(str(tick_size))
        
        # Arredondar para múltiplo mais próximo
        multiple = (price_dec / tick_dec).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        result = float(multiple * tick_dec)
        
        # Forçar casas decimais corretas baseado no tick_size
        if tick_size == 0.01:
            return round(result, 2)
        elif tick_size == 0.001:
            return round(result, 3)
        elif tick_size == 0.0001:
            return round(result, 4)
        elif tick_size == 0.00001:
            return round(result, 5)
        else:
            return round(result, 8)  # Máximo de 8 decimais para crypto

    def clear_historical_cache(self):
        """Limpa o cache de histórico (útil para forçar refresh)"""
        cleared_count = len(self._historical_cache)
        self._historical_cache.clear()
        self.logger.info(f"🧹 Cache de histórico limpo ({cleared_count} entradas removidas)")

    def get_cache_stats(self) -> dict:
        """Retorna estatísticas do cache"""
        return {
            'cache_size': len(self._historical_cache),
            'consecutive_errors': self._consecutive_errors,
            'backoff_multiplier': self._backoff_multiplier,
            'cached_symbols': list(set(k.split('_')[0] for k in self._historical_cache.keys()))
        }

    # ============================================================================
    # FUNCIONALIDADES AVANÇADAS (TP/SL PARA POSIÇÕES EXISTENTES)
    # ============================================================================
    
    def get_positions(self, symbol: str = None) -> Optional[List]:
        """
        Busca posições abertas da conta
        Args:
            symbol: Filtrar por símbolo específico (opcional)
        Returns:
            Lista de posições ou None em caso de erro
        """
        try:
            # Primeiro tentar endpoint público (similar ao get_open_orders)
            url = f"{self.base_url}/account"
            params = {'account': self.main_public_key}
            
            response = requests.get(url, params=params, timeout=10)
            self.logger.info(f"📊 GET /account (for positions) -> {response.status_code}")
            self.debug_logger.debug(f"Response: {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                # Tentar extrair posições dos dados da conta
                positions = []
                
                if isinstance(data, dict):
                    # Verificar diferentes estruturas possíveis
                    account_data = data.get('data', {})
                    
                    # Se positions_count > 0, mas não há array de posições, 
                    # pode ser que as posições estejam em outro endpoint
                    positions_count = account_data.get('positions_count', 0)
                    
                    positions = (account_data.get('positions', []) or 
                               account_data.get('open_positions', []) or
                               data.get('positions', []))
                    
                    # Se não encontramos array de posições mas o count indica que há posições,
                    # tentar endpoint específico de posições
                    if not positions and positions_count > 0:
                        self.logger.info(f"🔍 {positions_count} posições indicadas, tentando endpoint específico")
                        return self._try_positions_endpoint(symbol)
                
                if symbol and positions:
                    # Filtrar por símbolo se especificado
                    positions = [p for p in positions if p.get('symbol') == symbol]
                
                self.logger.info(f"✅ {len(positions)} posições encontradas")
                return positions
                
            elif response.status_code == 401:
                # Se precisar de autenticação, tentar método autenticado
                self.logger.info("🔒 Endpoint requer autenticação - tentando método autenticado")
                return self._get_positions_authenticated(symbol)
            else:
                self.logger.error(f"❌ Erro {response.status_code}: {response.text[:200]}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Erro ao buscar posições: {e}")
            return []
    
    def _get_positions_authenticated(self, symbol: str = None) -> Optional[List]:
        """
        Busca posições com autenticação Agent Wallet
        """
        try:
            timestamp = int(time.time() * 1_000)
            
            signature_header = {
                "timestamp": timestamp,
                "expiry_window": 30000,
                "type": "get_account",  # Usar get_account em vez de get_positions
            }
            
            signature_payload = {
                "account": self.main_public_key,
            }
            
            message = prepare_message(signature_header, signature_payload)
            signature = sign_message(message, self.agent_keypair)
            
            request_data = {
                "account": self.main_public_key,
                "agent_wallet": self.agent_public_key,
                "signature": signature,
                "timestamp": timestamp,
                "expiry_window": 30000,
            }
            
            url = f"{self.base_url}/account"
            response = requests.post(url, json=request_data, timeout=10)
            self.logger.info(f"📊 POST /account (auth for positions) -> {response.status_code}")
            self.debug_logger.debug(f"Response: {response.text[:500]}")
            
            if response.status_code == 200:
                data = response.json()
                # Tentar extrair posições dos dados da conta
                positions = []
                
                if isinstance(data, dict):
                    positions = (data.get('positions', []) or 
                               data.get('data', {}).get('positions', []) or
                               data.get('open_positions', []))
                
                if symbol and positions:
                    positions = [p for p in positions if p.get('symbol') == symbol]
                
                self.logger.info(f"✅ {len(positions)} posições obtidas (autenticado)")
                return positions
            else:
                self.logger.error(f"❌ Erro na busca autenticada de posições: {response.text}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Erro na requisição autenticada de posições: {e}")
            return []
    
    def _try_positions_endpoint(self, symbol: str = None) -> Optional[List]:
        """
        Tenta endpoints alternativos para buscar posições
        """
        # Lista de endpoints possíveis para tentar
        endpoints_to_try = [
            "/account/positions",
            "/positions", 
            "/user/positions",
            "/trading/positions"
        ]
        
        for endpoint in endpoints_to_try:
            try:
                url = f"{self.base_url}{endpoint}"
                params = {'account': self.main_public_key}
                if symbol:
                    params['symbol'] = symbol
                
                self.logger.debug(f"🔍 Tentando endpoint: {endpoint}")
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and 'data' in data:
                        positions = data['data']
                    elif isinstance(data, list):
                        positions = data
                    else:
                        continue
                    
                    if positions:  # Se encontrou posições
                        self.logger.info(f"✅ Posições encontradas em {endpoint}: {len(positions)}")
                        return positions
                        
                elif response.status_code == 401:
                    # Se precisar de autenticação, tentar com Agent Wallet
                    auth_positions = self._try_authenticated_positions_endpoint(endpoint, symbol)
                    if auth_positions:
                        return auth_positions
                
            except Exception as e:
                self.logger.debug(f"Erro no endpoint {endpoint}: {e}")
                continue
        
        # Se chegou aqui, nenhum endpoint funcionou
        self.logger.info("ℹ️ Nenhum endpoint de posições retornou dados")
        return []
    
    def _try_authenticated_positions_endpoint(self, endpoint: str, symbol: str = None) -> Optional[List]:
        """
        Tenta endpoint de posições com autenticação
        """
        try:
            timestamp = int(time.time() * 1_000)
            
            signature_header = {
                "timestamp": timestamp,
                "expiry_window": 30000,
                "type": "get_positions",
            }
            
            signature_payload = {
                "account": self.main_public_key,
            }
            if symbol:
                signature_payload["symbol"] = symbol
            
            message = prepare_message(signature_header, signature_payload)
            signature = sign_message(message, self.agent_keypair)
            
            request_data = {
                "account": self.main_public_key,
                "agent_wallet": self.agent_public_key,
                "signature": signature,
                "timestamp": timestamp,
                "expiry_window": 30000,
            }
            
            url = f"{self.base_url}{endpoint}"
            response = requests.post(url, json=request_data, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                positions = data.get('data', []) if isinstance(data, dict) else data
                if positions:
                    self.logger.info(f"✅ Posições autenticadas encontradas em {endpoint}: {len(positions)}")
                    return positions
            
            return []
            
        except Exception as e:
            self.logger.debug(f"Erro no endpoint autenticado {endpoint}: {e}")
            return []

# ============================================================================
# FUNÇÃO PRINCIPAL DE TESTE
# ============================================================================

def main():
    print("=" * 80)
    print("🔒 PACIFICA API - AGENT WALLET (SEM PRIVATE KEY)")
    print("=" * 80)

    try:
        # Inicializar autenticação com Agent Wallet
        auth = PacificaAuth()
        
        print("\n🔍 Testando conexão...")
        if auth.test_connection():
            print("✅ Teste de conexão bem-sucedido!")
            
            print("\n📊 Buscando preços atuais...")
            prices = auth.get_prices()
            if prices:
                print("✅ Preços obtidos com sucesso!")
                print(json.dumps(prices, indent=2)[:500])
            
            print("\n📈 Buscando informações do mercado BTC...")
            market_info = auth.get_market_info("BTC")
            if market_info:
                print("✅ Informações do mercado obtidas!")
                print(json.dumps(market_info, indent=2)[:500])
            
            print("\n💰 Testando informações da conta...")
            account_info = auth.get_account_info()
            if account_info:
                print("✅ Informações da conta obtidas!")
                print(json.dumps(account_info, indent=2)[:500])
            
            print("\n📋 Testando ordens abertas...")
            orders = auth.get_open_orders()
            if orders is not None:
                print(f"✅ {len(orders)} ordens abertas encontradas!")
                
            print("\n📊 Testando posições abertas...")
            positions = auth.get_positions()
            if positions is not None:
                print(f"✅ {len(positions)} posições encontradas!")
                if positions:
                    print("Primeira posição:")
                    print(json.dumps(positions[0], indent=2))
                
        else:
            print("❌ Falha no teste de conexão")

    except Exception as e:
        print(f"❌ Erro na inicialização: {e}")
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("🔒 Teste Agent Wallet concluído!")
    print("=" * 80)

if __name__ == "__main__":
    main()