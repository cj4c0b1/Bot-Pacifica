"""Data models for the liquidation monitoring system."""
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
import uuid

class LiquidationSide(str, Enum):
    LONG = "long_liquidation"
    SHORT = "short_liquidation"

class Trade(BaseModel):
    """Represents a single trade from the WebSocket feed."""
    timestamp: datetime
    market: str
    price: float
    size: float  # Absolute size in base currency
    side: str  # 'buy' or 'sell'
    order_id: str
    liquidity: str = "taker"  # 'maker' or 'taker'
    trade_type: str = "normal"  # 'normal', 'liquidation', etc.
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class DetectedLiquidation(BaseModel):
    """Represents a detected liquidation event."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    market: str
    side: LiquidationSide
    estimated_size_usd: float
    confidence_score: float = Field(..., ge=0, le=100)
    num_chunks: int = 1
    liquidation_price: float
    mark_price: float
    trades: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('trades', pre=True)
    def convert_trades_to_dict(cls, v):
        if v and isinstance(v[0], Trade):
            return [trade.dict() for trade in v]
        return v
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "timestamp": "2025-10-08T09:28:00.123456",
                "market": "BTC-PERP",
                "side": "long_liquidation",
                "estimated_size_usd": 125000.0,
                "confidence_score": 87.5,
                "num_chunks": 5,
                "liquidation_price": 62450.50,
                "mark_price": 62448.20,
                "trades": [
                    {"timestamp": "2025-10-08T09:28:00.100000", "price": 62450.50, "size": 0.2, "side": "sell"}
                ]
            }
        }
