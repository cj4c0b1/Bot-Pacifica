"""Redis client for storing and querying liquidation events."""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import redis.asyncio as redis
from liquidation_monitor.core.models import DetectedLiquidation
from liquidation_monitor.config.settings import settings as app_settings

logger = logging.getLogger(__name__)

class RedisClient:
    """Redis client for storing and querying liquidation events."""
    
    def __init__(self):
        """Initialize the Redis client."""
        self.redis: Optional[redis.Redis] = None
        self.connection_url = f"redis://{app_settings.redis_host}:{app_settings.redis_port}/{app_settings.redis_db}"
    
    async def connect(self) -> None:
        """Connect to the Redis server."""
        try:
            self.redis = redis.from_url(
                self.connection_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis.ping()  # Test the connection
            logger.info("Connected to Redis server")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self.redis:
            await self.redis.close()
            await self.redis.connection_pool.disconnect()
            logger.info("Disconnected from Redis server")
    
    async def save_liquidation(self, liquidation: DetectedLiquidation) -> None:
        """Save a liquidation event to Redis.
        
        Args:
            liquidation: The liquidation event to save
        """
        if not self.redis:
            await self.connect()
        
        try:
            # Create a unique key for the liquidation
            key = f"liquidation:{liquidation.market}:{liquidation.id}"
            
            # Convert the liquidation to a dictionary
            liquidation_dict = liquidation.dict()
            
            # Store the liquidation in a hash
            await self.redis.hset(key, mapping=liquidation_dict)
            
            # Add to sorted sets for time-based queries
            timestamp = int(datetime.now().timestamp() * 1000)  # ms precision
            
            # Add to market-specific sorted set
            market_key = f"liquidations:market:{liquidation.market}"
            await self.redis.zadd(market_key, {key: timestamp})
            
            # Add to global liquidations sorted set
            await self.redis.zadd("liquidations:all", {key: timestamp})
            
            # Add to side-specific sorted set
            side_key = f"liquidations:side:{liquidation.side}"
            await self.redis.zadd(side_key, {key: timestamp})
            
            # Set TTL for automatic cleanup (7 days)
            ttl = 60 * 60 * 24 * 7  # 7 days in seconds
            await self.redis.expire(key, ttl)
            await self.redis.expire(market_key, ttl)
            await self.redis.expire("liquidations:all", ttl)
            await self.redis.expire(side_key, ttl)
            
            logger.debug(f"Saved liquidation {liquidation.id} to Redis")
            
        except Exception as e:
            logger.error(f"Failed to save liquidation to Redis: {e}")
            raise
    
    async def get_recent_liquidations(
        self,
        limit: int = 100,
        market: Optional[str] = None,
        side: Optional[str] = None,
        min_size_usd: float = 0.0,
        min_confidence: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Get recent liquidation events.
        
        Args:
            limit: Maximum number of liquidations to return
            market: Filter by market (e.g., "BTC-PERP")
            side: Filter by side ("long_liquidation" or "short_liquidation")
            min_size_usd: Minimum liquidation size in USD
            min_confidence: Minimum confidence score (0-100)
            
        Returns:
            List of liquidation events, most recent first
        """
        if not self.redis:
            await self.connect()
        
        try:
            # Determine which sorted set to query
            if market and side:
                key = f"liquidations:market:{market}"
                # Need to intersect with side in application code
                results = await self.redis.zrevrange(key, 0, limit * 2)  # Get extra to filter by side
            elif market:
                key = f"liquidations:market:{market}"
                results = await self.redis.zrevrange(key, 0, limit - 1)
            elif side:
                key = f"liquidations:side:{side}"
                results = await self.redis.zrevrange(key, 0, limit - 1)
            else:
                results = await self.redis.zrevrange("liquidations:all", 0, limit - 1)
            
            # Get the liquidation details
            liquidations = []
            for key in results:
                try:
                    data = await self.redis.hgetall(key)
                    if not data:
                        continue
                        
                    # Filter by side if needed
                    if side and data.get("side") != side:
                        continue
                        
                    # Convert numeric fields
                    data["estimated_size_usd"] = float(data.get("estimated_size_usd", 0))
                    data["confidence_score"] = float(data.get("confidence_score", 0))
                    data["liquidation_price"] = float(data.get("liquidation_price", 0))
                    data["mark_price"] = float(data.get("mark_price", 0))
                    
                    # Apply filters
                    if data["estimated_size_usd"] < min_size_usd:
                        continue
                    if data["confidence_score"] < min_confidence:
                        continue
                    
                    # Parse trades if present
                    if "trades" in data and isinstance(data["trades"], str):
                        data["trades"] = json.loads(data["trades"])
                    
                    liquidations.append(data)
                    
                    # Stop if we've reached the limit
                    if len(liquidations) >= limit:
                        break
                        
                except (ValueError, json.JSONDecodeError) as e:
                    logger.warning(f"Error parsing liquidation data: {e}")
                    continue
            
            return liquidations
            
        except Exception as e:
            logger.error(f"Failed to get liquidations from Redis: {e}")
            raise
    
    async def get_market_stats(self, market: str) -> Dict[str, Any]:
        """Get statistics for a specific market.
        
        Args:
            market: The market to get statistics for (e.g., "BTC-PERP")
            
        Returns:
            Dictionary containing market statistics
        """
        if not self.redis:
            await self.connect()
        
        try:
            # Get all liquidations for this market
            key = f"liquidations:market:{market}"
            liquidation_keys = await self.redis.zrevrange(key, 0, -1)
            
            if not liquidation_keys:
                return {
                    "market": market,
                    "total_liquidations": 0,
                    "total_volume_usd": 0,
                    "long_liquidations": 0,
                    "short_liquidations": 0,
                    "avg_size_usd": 0,
                    "largest_liquidation_usd": 0,
                    "last_24h_count": 0,
                    "last_24h_volume_usd": 0
                }
            
            # Get liquidation details
            liquidations = []
            for lkey in liquidation_keys:
                data = await self.redis.hgetall(lkey)
                if data:
                    try:
                        data["estimated_size_usd"] = float(data.get("estimated_size_usd", 0))
                        data["confidence_score"] = float(data.get("confidence_score", 0))
                        liquidations.append(data)
                    except (ValueError, TypeError):
                        continue
            
            if not liquidations:
                return {
                    "market": market,
                    "total_liquidations": 0,
                    "total_volume_usd": 0,
                    "long_liquidations": 0,
                    "short_liquidations": 0,
                    "avg_size_usd": 0,
                    "largest_liquidation_usd": 0,
                    "last_24h_count": 0,
                    "last_24h_volume_usd": 0
                }
            
            # Calculate statistics
            total_liquidations = len(liquidations)
            total_volume = sum(l["estimated_size_usd"] for l in liquidations)
            long_count = sum(1 for l in liquidations if l.get("side") == "long_liquidation")
            short_count = total_liquidations - long_count
            avg_size = total_volume / total_liquidations if total_liquidations > 0 else 0
            largest = max((l["estimated_size_usd"] for l in liquidations), default=0)
            
            # Get 24h stats
            now = datetime.now()
            day_ago = now - timedelta(days=1)
            day_ago_ts = int(day_ago.timestamp() * 1000)
            
            recent_liquidations = [
                l for l in liquidations 
                if datetime.fromisoformat(l.get("timestamp", "1970-01-01")).timestamp() * 1000 >= day_ago_ts
            ]
            
            last_24h_count = len(recent_liquidations)
            last_24h_volume = sum(l["estimated_size_usd"] for l in recent_liquidations)
            
            return {
                "market": market,
                "total_liquidations": total_liquidations,
                "total_volume_usd": total_volume,
                "long_liquidations": long_count,
                "short_liquidations": short_count,
                "avg_size_usd": avg_size,
                "largest_liquidation_usd": largest,
                "last_24h_count": last_24h_count,
                "last_24h_volume_usd": last_24h_volume
            }
            
        except Exception as e:
            logger.error(f"Failed to get market stats: {e}")
            raise
    
    async def get_liquidation_heatmap(
        self,
        market: str,
        price_bucket_size: float = 100.0,
        side: Optional[str] = None,
        time_window_hours: int = 24
    ) -> Dict[float, int]:
        """Get a heatmap of liquidations by price level.
        
        Args:
            market: The market to get the heatmap for
            price_bucket_size: Size of each price bucket
            side: Filter by side ("long_liquidation" or "short_liquidation")
            time_window_hours: Time window in hours to consider
            
        Returns:
            Dictionary mapping price buckets to liquidation counts
        """
        if not self.redis:
            await self.connect()
        
        try:
            # Get all liquidations for this market
            key = f"liquidations:market:{market}"
            liquidation_keys = await self.redis.zrevrange(key, 0, -1)
            
            # Filter by time window
            now = datetime.now()
            time_threshold = now - timedelta(hours=time_window_hours)
            time_threshold_ts = int(time_threshold.timestamp() * 1000)
            
            heatmap = {}
            
            for lkey in liquidation_keys:
                data = await self.redis.hgetall(lkey)
                if not data:
                    continue
                
                # Filter by side if specified
                if side and data.get("side") != side:
                    continue
                
                # Filter by time window
                try:
                    timestamp = datetime.fromisoformat(data.get("timestamp", "1970-01-01")).timestamp() * 1000
                    if timestamp < time_threshold_ts:
                        continue
                except (ValueError, TypeError):
                    continue
                
                # Get price and calculate bucket
                try:
                    price = float(data.get("liquidation_price", 0))
                    if price <= 0:
                        continue
                        
                    bucket = round(price / price_bucket_size) * price_bucket_size
                    heatmap[bucket] = heatmap.get(bucket, 0) + 1
                except (ValueError, TypeError):
                    continue
            
            return dict(sorted(heatmap.items()))
            
        except Exception as e:
            logger.error(f"Failed to get liquidation heatmap: {e}")
            raise
    
    async def get_largest_liquidations(
        self,
        limit: int = 10,
        market: Optional[str] = None,
        side: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get the largest liquidations by size.
        
        Args:
            limit: Maximum number of liquidations to return
            market: Filter by market
            side: Filter by side ("long_liquidation" or "short_liquidation")
            
        Returns:
            List of liquidations, largest first
        """
        if not self.redis:
            await self.connect()
        
        try:
            # Get all relevant liquidations
            liquidations = await self.get_recent_liquidations(
                limit=1000,  # Get enough to find the largest
                market=market,
                side=side
            )
            
            # Sort by size (descending) and take the top N
            liquidations.sort(key=lambda x: x.get("estimated_size_usd", 0), reverse=True)
            return liquidations[:limit]
            
        except Exception as e:
            logger.error(f"Failed to get largest liquidations: {e}")
            raise
