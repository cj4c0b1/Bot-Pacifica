"""
Pacifica DEX Liquidation Monitor

A real-time monitoring system for detecting and tracking liquidations on Pacifica DEX.
"""
import asyncio
import logging
import signal
import sys
from typing import Dict, Any, Optional

from liquidation_monitor.core.websocket_client import PacificaWebSocketClient
from liquidation_monitor.core.detector import LiquidationDetector
from liquidation_monitor.storage.redis_client import RedisClient
from liquidation_monitor.utils.notifications import notification_manager
from liquidation_monitor.config.settings import settings as app_settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, app_settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(app_settings.log_file)
    ]
)
logger = logging.getLogger(__name__)

class LiquidationMonitor:
    """Main class for the liquidation monitoring system."""
    
    def __init__(self):
        """Initialize the liquidation monitor."""
        self.detector = LiquidationDetector()
        self.redis_client = RedisClient()
        self.ws_client: Optional[PacificaWebSocketClient] = None
        self.running = False
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    async def initialize(self) -> None:
        """Initialize the monitor and its components."""
        logger.info("Initializing liquidation monitor...")
        
        # Connect to Redis
        try:
            await self.redis_client.connect()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        
        # Initialize WebSocket client
        self.ws_client = PacificaWebSocketClient(
            on_trade=self.handle_trade,
            on_connect=self.on_ws_connect,
            on_disconnect=self.on_ws_disconnect
        )
        
        logger.info("Liquidation monitor initialized")
    
    async def start(self) -> None:
        """Start the liquidation monitor."""
        if not self.ws_client:
            raise RuntimeError("Monitor not initialized. Call initialize() first.")
        
        self.running = True
        logger.info("Starting liquidation monitor...")
        
        try:
            # Start the WebSocket client
            await self.ws_client.connect()
        except Exception as e:
            logger.error(f"Error in WebSocket client: {e}")
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the liquidation monitor."""
        logger.info("Stopping liquidation monitor...")
        self.running = False
        
        # Disconnect WebSocket client
        if self.ws_client:
            await self.ws_client.disconnect()
        
        # Close Redis connection
        await self.redis_client.disconnect()
        
        logger.info("Liquidation monitor stopped")
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle termination signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(self.stop())
    
    async def on_ws_connect(self) -> None:
        """Handle WebSocket connection established."""
        logger.info("WebSocket connected")
        
        # Send a notification that we're online
        await notification_manager.send_market_alert(
            market="SYSTEM",
            message="Liquidation monitor connected and running",
            level="info"
        )
    
    async def on_ws_disconnect(self) -> None:
        """Handle WebSocket disconnection."""
        logger.warning("WebSocket disconnected")
        
        # Only send notification if we're not shutting down
        if self.running:
            await notification_manager.send_market_alert(
                market="SYSTEM",
                message="WebSocket disconnected, attempting to reconnect...",
                level="warning"
            )
    
    async def handle_trade(self, trade: Dict[str, Any]) -> None:
        """Process a new trade from the WebSocket.
        
        Args:
            trade: The trade data
        """
        try:
            # Detect potential liquidations
            liquidation = await self.detector.process_trade(trade)
            
            if liquidation:
                logger.info(
                    f"Detected potential {liquidation.side} liquidation: "
                    f"{liquidation.market} ${liquidation.estimated_size_usd:,.2f} "
                    f"at {liquidation.liquidation_price} "
                    f"(confidence: {liquidation.confidence_score:.1f}%)"
                )
                
                # Save to Redis
                await self.redis_client.save_liquidation(liquidation)
                
                # Send notification
                await notification_manager.send_notification(liquidation)
                
        except Exception as e:
            logger.error(f"Error processing trade: {e}", exc_info=True)

async def main():
    """Main entry point for the liquidation monitor."""
    monitor = LiquidationMonitor()
    
    try:
        await monitor.initialize()
        await monitor.start()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        await monitor.stop()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
