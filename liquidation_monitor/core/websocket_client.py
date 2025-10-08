"""WebSocket client for connecting to Pacifica's real-time trade feed."""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, Callable, Optional, Any
import aiohttp
import aiohttp.client_exceptions

from liquidation_monitor.core.models import Trade
from liquidation_monitor.config.settings import settings as app_settings

logger = logging.getLogger(__name__)

class PacificaWebSocketClient:
    """WebSocket client for Pacifica's real-time trade feed."""
    
    def __init__(
        self,
        on_trade: Callable[[Trade], None],
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ):
        """Initialize the WebSocket client.
        
        Args:
            on_trade: Callback function to handle incoming trades
            on_connect: Optional callback when WebSocket connects
            on_disconnect: Optional callback when WebSocket disconnects
        """
        # Use the WebSocket URL from settings
        self.ws_url = app_settings.ws_endpoint
        logger.info(f"Initializing WebSocket client with URL: {self.ws_url}")
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.on_trade = on_trade
        self.on_connect = on_connect or (lambda: None)
        self.on_disconnect = on_disconnect or (lambda: None)
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None
        
        # Create subscription messages for each market
        self._subscribe_messages = []
        for market in app_settings.markets:
            # Clean up market symbol format
            symbol = market.upper()
            if '/' in symbol:
                symbol = symbol.split('/')[0]  # Take base asset for spot pairs
            
            # Subscribe to trades for this market
            self._subscribe_messages.append({
                "method": "subscribe",
                "params": {
                    "source": "trades",
                    "symbol": symbol
                },
                "id": int(time.time() * 1000) + len(self._subscribe_messages)
            })
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for WebSocket connection."""
        if not app_settings.api_key or not app_settings.api_secret:
            logger.warning("API key or secret not configured. Authentication will fail.")
            return {}
            
        # Generate timestamp in milliseconds
        timestamp = str(int(time.time() * 1000))
        
        # Create authentication headers based on Pacifica's requirements
        return {
            'x-api-key': app_settings.api_key,
            'x-timestamp': timestamp,
            'x-signature': self._generate_signature(timestamp, app_settings.api_secret),
            'Content-Type': 'application/json'
        }
        
    def _generate_signature(self, timestamp: str, secret: str) -> str:
        """Generate signature for authentication.
        
        This is a simplified version. You might need to adjust the signature 
        generation based on Pacifica's specific requirements.
        """
        import hmac
        import hashlib
        
        # This is a basic example - adjust according to Pacifica's API requirements
        message = f"{timestamp}{app_settings.api_key}"
        signature = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    async def connect(self) -> None:
        """Connect to the WebSocket server and start listening for messages."""
        self._running = True
        
        while self._running:
            try:
                logger.info(f"Connecting to WebSocket at {self.ws_url}")
                
                headers = self._get_auth_headers()
                
                async with aiohttp.ClientSession() as session:
                    self.session = session
                    
                    async with session.ws_connect(
                        self.ws_url,
                        headers=headers,
                        timeout=app_settings.ws_timeout,
                        heartbeat=30,
                        autoclose=True,
                        autoping=True,
                        max_msg_size=0,  # No limit
                    ) as ws:
                        self.ws = ws
                        logger.info("WebSocket connected successfully")
                        
                        # Call the on_connect callback if it exists
                        if callable(self.on_connect):
                            try:
                                if asyncio.iscoroutinefunction(self.on_connect):
                                    await self.on_connect()
                                else:
                                    # If it's not a coroutine, call it directly
                                    self.on_connect()
                            except Exception as e:
                                logger.error(f"Error in connect handler: {e}")
                        
                        # Subscribe to trade and orderbook channels
                        for msg in self._subscribe_messages:
                            await self._send_json(msg)
                        
                        # Start listening for messages
                        await self._listen()
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.error(f"WebSocket error: {e}")
            except Exception as e:
                logger.exception(f"Unexpected error in WebSocket client: {e}")
            
            # If we get here, the connection was lost
            self.ws = None
            
            # Call the disconnect handler if it exists
            if callable(self.on_disconnect):
                try:
                    if asyncio.iscoroutinefunction(self.on_disconnect):
                        await self.on_disconnect()
                    else:
                        # If it's not a coroutine, call it directly
                        self.on_disconnect()
                except Exception as e:
                    logger.error(f"Error in disconnect handler: {e}")
            
            if self._running:
                logger.info(f"Reconnecting in {app_settings.ws_reconnect_delay} seconds...")
                await asyncio.sleep(app_settings.ws_reconnect_delay)
    
    async def _log_websocket_message(self, msg: aiohttp.WSMessage) -> None:
        """Log WebSocket message if verbose mode is enabled."""
        if not app_settings.verbose_websocket:
            return
            
        try:
            if msg.type == aiohttp.WSMsgType.TEXT:
                logger.debug(f"📡 WEBSOCKET MESSAGE: {msg.data}")
            elif msg.type == aiohttp.WSMsgType.BINARY:
                logger.debug(f"📡 WEBSOCKET BINARY MESSAGE (length: {len(msg.data)} bytes)")
            elif msg.type == aiohttp.WSMsgType.PING:
                logger.debug("📡 WEBSOCKET PING")
            elif msg.type == aiohttp.WSMsgType.PONG:
                logger.debug("📡 WEBSOCKET PONG")
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                logger.debug(f"WEBSOCKET CLOSE: code={msg.data}, extra={msg.extra}")
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                logger.debug("WEBSOCKET CONNECTION CLOSED")
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.debug(f"WEBSOCKET ERROR: {msg.data}")
        except Exception as e:
            logger.warning(f"Error logging WebSocket message: {e}")

    async def _listen(self) -> None:
        """Listen for incoming WebSocket messages."""
        while self._running and self.ws and not self.ws.closed:
            try:
                msg = await self.ws.receive()
                
                # Log the raw message if verbose mode is enabled
                await self._log_websocket_message(msg)
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if app_settings.verbose_websocket:
                            logger.debug(f"📡 PARSED MESSAGE: {json.dumps(data, indent=2)}")
                        await self._handle_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse WebSocket message: {e}")
                        if app_settings.verbose_websocket:
                            logger.debug(f"📡 RAW MESSAGE: {msg.data}")
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("WebSocket connection closed by server")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    error = self.ws.exception()
                    logger.error(f"WebSocket error: {error}")
                    if app_settings.verbose_websocket and error:
                        logger.debug(f"📡 ERROR DETAILS: {str(error)}")
                    break
            except Exception as e:
                logger.error(f"Error in WebSocket listener: {e}")
                break
    
    async def _handle_message(self, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket message with detailed debugging."""
        try:
            # Always log raw message in debug mode
            if logger.isEnabledFor(logging.DEBUG):
                import pprint
                logger.debug("\n" + "="*80)
                logger.debug("📡 INCOMING WEBSOCKET MESSAGE")
                logger.debug("-"*40)
                logger.debug(f"📄 RAW DATA: {pprint.pformat(data, width=120, compact=True)}")
                
                # Log message type and structure
                logger.debug("\n🔍 MESSAGE STRUCTURE:")
                logger.debug(f"Type: {type(data).__name__}")
                if isinstance(data, dict):
                    logger.debug(f"Keys: {', '.join(data.keys())}")
                    if 'e' in data:  # Event type
                        logger.debug(f"Event Type: {data['e']}")
                    if 's' in data:  # Symbol
                        logger.debug(f"Symbol: {data['s']}")
                    if 'E' in data:  # Event time
                        from datetime import datetime
                        logger.debug(f"Event Time: {datetime.fromtimestamp(data['E']/1000).isoformat()}")
                
                logger.debug("="*80 + "\n")
            
            # Handle different message types
            if isinstance(data, dict):
                # Handle trade events
                if data.get('e') == 'trade' or 'trade' in str(data).lower():
                    logger.info(f"🔄 Processing trade for {data.get('s', 'unknown')}")
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Trade details: {json.dumps({k: v for k, v in data.items() if k not in ['e']}, indent=2)}")
                    await self._handle_trade(data)
                
                # Handle orderbook updates
                elif data.get('e') == 'depthUpdate' or 'depth' in str(data).lower():
                    logger.debug(f"📊 Orderbook update for {data.get('s', 'unknown')}")
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Bids: {len(data.get('bids', []))}, Asks: {len(data.get('asks', []))}")
                
                # Handle subscription responses
                elif 'result' in data or 'id' in data:
                    if 'result' in data and data.get('result') is None:
                        logger.info(f"✅ Subscription successful (ID: {data.get('id')})")
                    elif 'error' in data:
                        logger.error(f"❌ Subscription error (ID: {data.get('id')}): {data.get('error')}")
                
                # Handle ping/pong
                elif data.get('ping'):
                    logger.debug("🏓 Ping received")
                elif data.get('pong'):
                    logger.debug("🏓 Pong received")
                
                # Handle errors
                elif 'error' in data:
                    logger.error(f"❌ WebSocket error: {data.get('error')}")
                
                # Unknown message type
                else:
                    logger.warning(f"⚠️ Unhandled message type: {data}")
            
            # Non-dict message
            else:
                logger.warning(f"⚠️ Received non-dict message: {data}")
                
        except Exception as e:
            logger.exception(f"❌ Error handling WebSocket message: {e}")
            if logger.isEnabledFor(logging.DEBUG):
                import traceback
                logger.debug(f"🔍 Error details: {traceback.format_exc()}")
                logger.debug(f"📡 Message that caused error: {data}")
    
    async def _handle_trade(self, data: Dict[str, Any]) -> None:
        """Handle a trade message from the WebSocket."""
        try:
            # Log the raw trade data for debugging
            logger.debug(f"Raw trade message: {data}")
            
            if isinstance(data, dict) and 'data' in data and isinstance(data['data'], list):
                # Process each trade in the data array
                for trade_data in data['data']:
                    try:
                        # Log raw trade data for debugging
                        logger.debug(f"Processing trade data: {trade_data}")
                        
                        # Extract trade details
                        symbol = trade_data.get('s', '').upper()
                        price = float(trade_data.get('p', 0))
                        amount = float(trade_data.get('a', 0))
                        
                        # Log if we can't identify the market
                        if not symbol:
                            logger.warning(f"Trade with no symbol: {trade_data}")
                            continue
                        
                        # Log the raw symbol for debugging
                        logger.debug(f"Raw symbol from WebSocket: {symbol}")
                        
                        # Normalize the symbol to match our market format
                        known_markets = [m.upper() for m in app_settings.markets]
                        
                        # First, check if the symbol exactly matches any known market
                        if symbol in known_markets:
                            normalized_symbol = symbol
                            logger.debug(f"Exact match found for {symbol}")
                        else:
                            # Try to find a match by base symbol
                            base_to_market = {}
                            for market in known_markets:
                                base = market.split('-')[0].split('/')[0]
                                base_to_market[base] = market
                            
                            # Try to find a direct base match
                            if symbol in base_to_market:
                                normalized_symbol = base_to_market[symbol]
                                logger.debug(f"Matched {symbol} to {normalized_symbol} by base symbol")
                            else:
                                # Try to find a match by checking if the symbol is a substring of any market
                                matching_markets = [m for m in known_markets if symbol in m]
                                if matching_markets:
                                    # Prefer PERP over SPOT if both exist
                                    perp_markets = [m for m in matching_markets if m.endswith('-PERP')]
                                    if perp_markets:
                                        normalized_symbol = perp_markets[0]
                                    else:
                                        normalized_symbol = matching_markets[0]
                                    logger.debug(f"Matched {symbol} to {normalized_symbol} by substring")
                                else:
                                    # If still no match, log a warning and use the original symbol
                                    logger.warning(f"Unknown market {symbol} in trade data. Known markets: {known_markets}")
                                    normalized_symbol = symbol
                        
                        logger.debug(f"Using normalized symbol: {normalized_symbol}")
                        
                        # Determine the side based on the direction (d) field
                        direction = trade_data.get('d', '').lower()
                        if 'buy' in direction or 'long' in direction:
                            side = 'buy'
                        elif 'sell' in direction or 'short' in direction:
                            side = 'sell'
                        else:
                            side = 'unknown'
                        
                        # Convert timestamp from milliseconds to datetime
                        timestamp = datetime.fromtimestamp(trade_data.get('t', 0) / 1000.0)
                        
                        # Determine if this is a taker or maker trade
                        execution_type = trade_data.get('e', '').lower()
                        liquidity = 'taker' if 'taker' in execution_type else 'maker'
                        
                        # Create the trade object
                        trade = Trade(
                            timestamp=timestamp,
                            market=symbol,
                            price=price,
                            size=amount,
                            side=side,
                            liquidity=liquidity,
                            trade_id=trade_data.get('i', ''),
                            order_id=trade_data.get('u', '')  # Use the update ID as order ID if available
                        )
                        
                        # Process the trade
                        self.on_trade(trade)
                        
                    except Exception as e:
                        logger.error(f"Error processing trade {trade_data}: {e}", exc_info=True)
            
        except Exception as e:
            logger.error(f"Error in _handle_trade: {e}", exc_info=True)
    
    async def _send_json(self, data: Dict[str, Any]) -> None:
        """Send a JSON message through the WebSocket connection.
        
        Args:
            data: The data to send as JSON
            
        Raises:
            ConnectionError: If the WebSocket is not connected
            ValueError: If the data is not a dictionary
            aiohttp.ClientError: If there's an error sending the message
        """
        if not self.ws or self.ws.closed:
            logger.warning("Cannot send message: WebSocket not connected")
            return
            
        try:
            # Log the outgoing message if verbose mode is enabled
            if app_settings.verbose_websocket:
                logger.debug(f"📤 SENDING MESSAGE: {json.dumps(data, indent=2)}")
                
            # Ensure the message is properly formatted
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")
                
            # Add a timestamp if not present
            if 'ts' not in data:
                data['ts'] = int(time.time() * 1000)
                
            # Send the message
            await self.ws.send_json(data)
            
        except aiohttp.ClientError as e:
            logger.error(f"Error sending message: {e}")
            if app_settings.verbose_websocket:
                logger.debug(f"📤 MESSAGE THAT FAILED: {json.dumps(data, indent=2) if isinstance(data, dict) else str(data)}")
                logger.debug(f"📤 ERROR DETAILS: {str(e)}")
                
            # If there's a parsing error, log the exact format we're trying to send
            if "JSON" in str(e) and "parse" in str(e).lower():
                logger.error("Message format error. Attempting to send:")
                logger.error(f"Type: {type(data).__name__}")
                logger.error(f"Content: {data}")
                
            # Re-raise the exception to trigger reconnection logic
            raise
    
    async def disconnect(self) -> None:
        """Disconnect the WebSocket client."""
        self._running = False
        
        if self.ws:
            await self.ws.close()
            self.ws = None
        
        if self.session:
            await self.session.close()
            self.session = None
        
        self.on_disconnect()
        logger.info("WebSocket client disconnected")
    
    async def __aenter__(self):
        """Async context manager entry."""
        self._reconnect_task = asyncio.create_task(self.connect())
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
