"""Core liquidation detection logic."""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque, Tuple
from collections import deque, defaultdict
import logging

from liquidation_monitor.core.models import Trade, DetectedLiquidation, LiquidationSide
from liquidation_monitor.config.settings import settings as app_settings

logger = logging.getLogger(__name__)

@dataclass
class TradeWindow:
    """Sliding window of recent trades for a market."""
    market: str
    window_size: int = 100
    trades: Deque[Trade] = field(default_factory=deque)
    volume_by_side: Dict[str, float] = field(default_factory=lambda: {"buy": 0.0, "sell": 0.0})
    
    def add_trade(self, trade: Trade):
        """Add a trade to the window and maintain the sliding window."""
        self.trades.append(trade)
        self.volume_by_side[trade.side] += trade.size * trade.price
        
        # Remove old trades if window size exceeded
        while len(self.trades) > self.window_size:
            old_trade = self.trades.popleft()
            self.volume_by_side[old_trade.side] -= old_trade.size * old_trade.price
    
    def get_volume_imbalance(self) -> float:
        """Calculate the volume imbalance between buy and sell."""
        total_volume = sum(self.volume_by_side.values())
        if total_volume == 0:
            return 0.0
        return (self.volume_by_side["sell"] - self.volume_by_side["buy"]) / total_volume
    
    def get_average_trade_size(self) -> float:
        """Calculate the average trade size in the window."""
        if not self.trades:
            return 0.0
        return sum(t.size * t.price for t in self.trades) / len(self.trades)

class LiquidationDetector:
    """Detects potential liquidations based on trade patterns."""
    
    def __init__(self):
        self.trade_windows: Dict[str, TradeWindow] = {}
        self.potential_liquidations: Dict[str, List[Dict]] = defaultdict(list)
        self.last_chunk_time: Dict[str, float] = {}
        
        # Initialize trade windows for each market
        for market in app_settings.markets:
            self.trade_windows[market] = TradeWindow(market=market)
    
    async def process_trade(self, trade: Trade) -> Optional[DetectedLiquidation]:
        """Process a new trade and detect potential liquidations."""
        market = trade.market
        trade_window = self.trade_windows[market]
        trade_window.add_trade(trade)
        
        # Check for potential liquidation
        return await self._check_liquidation(trade, trade_window)
    
    async def _check_liquidation(
        self, 
        trade: Trade, 
        trade_window: TradeWindow
    ) -> Optional[DetectedLiquidation]:
        """Check if a trade indicates a potential liquidation."""
        market = trade.market
        current_time = time.time()
        
        # Check for chunked execution pattern
        is_chunked = self._check_chunked_execution(trade, current_time)
        
        # Check volume anomaly
        is_volume_anomaly = self._check_volume_anomaly(trade, trade_window)
        
        # Check volume imbalance
        is_imbalance = abs(volume_imbalance) > 0.7  # 70% imbalance
        
        # Calculate confidence score
        confidence = self._calculate_confidence(
            is_chunked=is_chunked,
            is_volume_anomaly=is_volume_anomaly,
            is_imbalance=is_imbalance,
            trade=trade,
            trade_window=trade_window
        )
        
        # Debug logging
        logger.debug(
            f"Liquidation check - Market: {market}, "
            f"Size: {trade.size * trade.price:.2f} USD, "
            f"Price: {trade.price}, "
            f"Chunked: {is_chunked}, "
            f"Volume Anomaly: {is_volume_anomaly}, "
            f"Imbalance: {volume_imbalance:.2%}, "
            f"Confidence: {confidence:.1f}/100"
        )
        
        if confidence < app_settings.confidence_threshold:
            if confidence > 50:  # Only log if we're somewhat close to threshold
                logger.debug(
                    f"Liquidation not detected - Confidence {confidence:.1f} "
                    f"< Threshold {app_settings.confidence_threshold}"
                )
            return None
            
        return DetectedLiquidation(
            market=market,
            side=LiquidationSide.LONG if trade.side == "sell" else LiquidationSide.SHORT,
            confidence_score=confidence,
            num_chunks=1,  # Will be updated if chunked
            liquidation_price=trade.price,
            mark_price=trade.price,
            trades=[trade.dict()],
            metadata={"is_chunked": is_chunked, "is_volume_anomaly": is_volume_anomaly, "is_imbalance": is_imbalance}
        )
    
    def _check_volume_anomaly(self, trade: Trade, trade_window: TradeWindow) -> bool:
        """Check if trade volume is significantly larger than average."""
        avg_size = trade_window.get_average_trade_size()
        if avg_size == 0:
            return True
        
        # Calculate volume ratio
        current_volume = trade.size * trade.price
        volume_ratio = current_volume / avg_size if avg_size > 0 else float('inf')
        
        # Check if this is a large enough trade to be a liquidation
        if current_volume < app_settings.min_liquidation_usd:
            return False
            
        return volume_ratio > app_settings.liquidation_volume_multiplier
    
    def _calculate_confidence(
        self,
        is_chunked: bool,
        is_volume_anomaly: bool,
        is_imbalance: bool,
        trade: Trade,
        trade_window: TradeWindow
    ) -> float:
        """Calculate confidence score (0-100) that this is a liquidation."""
        confidence = 0.0
        
        # Base confidence on volume anomaly
        if is_volume_anomaly:
            confidence += 40.0
            
        # If it's a chunked execution, increase confidence
        if is_chunked:
            confidence += 30.0
            
        # If there's a volume imbalance, increase confidence
        if is_imbalance:
            confidence += 30.0
            
        # Ensure confidence is capped at 100
        return min(100.0, confidence)
    
    def _check_chunked_execution(self, trade: Trade, current_time: float) -> bool:
        """Check if this trade is part of a chunked execution."""
        market = trade.market
        
        # If this is the first trade for this market, initialize the timestamp
        if market not in self.last_chunk_time:
            self.last_chunk_time[market] = current_time
            return False
            
        # Check if this trade is part of a chunked execution
        time_since_last = current_time - self.last_chunk_time[market]
        self.last_chunk_time[market] = current_time
        
        # If trades are coming in too quickly, they might be part of a chunked execution
        return time_since_last < (app_settings.max_chunk_interval_ms / 1000)
    
    def _handle_chunked_liquidation(
        self,
        liquidation: DetectedLiquidation,
        market: str
    ) -> Optional[DetectedLiquidation]:
        """Handle chunked liquidation execution."""
        # Store the potential liquidation
        self.potential_liquidations[market].append({
            "time": time.time(),
            "liquidation": liquidation
        })
        
        # Group chunks that are close in time
        chunks = []
        current_time = time.time()
        
        for chunk in list(self.potential_liquidations[market]):
            if current_time - chunk["time"] <= (app_settings.max_chunk_interval_ms / 1000) * 5:  # 5x max interval
                chunks.append(chunk["liquidation"])
            else:
                self.potential_liquidations[market].remove(chunk)
        
        # If we have multiple chunks, combine them
        if len(chunks) > 1:
            # Take the first liquidation and update it with combined data
            combined = chunks[0].copy(update={
                "num_chunks": len(chunks),
                "trades": [t for liq in chunks for t in liq.trades],
                "estimated_size_usd": sum(liq.estimated_size_usd for liq in chunks)
            })
            return combined
            
        return None
        
        return liquidation
