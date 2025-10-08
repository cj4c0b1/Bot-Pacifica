"""Configuration settings for the liquidation monitor."""
import os
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class Settings(BaseModel):
    # WebSocket Configuration
    ws_endpoint: str = os.getenv("WS_ENDPOINT", "wss://ws.pacifica.fi/ws")
    ws_reconnect_delay: int = 5  # seconds
    ws_timeout: int = 30  # seconds
    verbose_websocket: bool = os.getenv("VERBOSE_WEBSOCKET", "false").lower() == "true"  # Log all WebSocket messages
    api_key: str = os.getenv("API_KEY", "")  # Load from environment
    api_secret: str = os.getenv("API_SECRET", "")  # Load from environment
    
    # Markets to monitor (loaded from environment or use defaults)
    @property
    def markets(self) -> List[str]:
        markets_env = os.getenv("MARKETS")
        if markets_env:
            return [m.strip() for m in markets_env.split(",") if m.strip()]
        return [
            # Default markets if not specified in environment
            "BTC-PERP", "ETH-PERP", "SOL-PERP", "XRP-PERP", "ADA-PERP",
            "DOT-PERP", "DOGE-PERP", "AVAX-PERP", "LINK-PERP", "MATIC-PERP",
            "BTC/USDC", "ETH/USDC", "SOL/USDC"
        ]
    
    # Redis Configuration
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    
    # Detection Parameters
    liquidation_volume_multiplier: float = float(os.getenv("LIQUIDATION_VOLUME_MULTIPLIER", "5.0"))  # x times average volume
    max_chunk_interval_ms: int = int(os.getenv("MAX_CHUNK_INTERVAL_MS", "1000"))  # 1 second between chunks
    min_liquidation_usd: float = float(os.getenv("MIN_LIQUIDATION_USD", "1000.0"))  # Minimum size to consider
    confidence_threshold: int = int(os.getenv("CONFIDENCE_THRESHOLD", "70"))  # Minimum confidence score (0-100)
    
    # Notification Settings
    notification_channels: List[str] = ["console"]  # console, telegram, discord
    min_notification_size_usd: float = 50000.0  # Min size for notifications
    
    # API Settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = os.path.abspath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
        "logs", 
        "liquidation_monitor.log"
    ))
    
    # Ensure logs directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

# Create settings instance with environment variables
settings = Settings()
