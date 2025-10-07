"""
Redis Client - Cache and Real-time Data Management
Handles Redis connections, caching, and pub/sub functionality for Pacifica Bot
"""

import os
import json
import redis
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import pickle

class RedisConfig:
    """Redis configuration settings"""

    def __init__(self):
        self.host = os.getenv('REDIS_HOST', 'localhost')
        self.port = int(os.getenv('REDIS_PORT', '6379'))
        self.db = int(os.getenv('REDIS_DB', '0'))
        self.password = os.getenv('REDIS_PASSWORD')
        self.connection_pool_size = int(os.getenv('REDIS_CONNECTION_POOL_SIZE', '10'))
        self.socket_timeout = int(os.getenv('REDIS_CONNECTION_TIMEOUT', '5'))
        self.retry_on_timeout = os.getenv('REDIS_RETRY_ON_TIMEOUT', 'true').lower() == 'true'

        # Cache TTL settings
        self.cache_ttl = {
            'prices': int(os.getenv('REDIS_CACHE_TTL_PRICES', '300')),
            'positions': int(os.getenv('REDIS_CACHE_TTL_POSITIONS', '60')),
            'balance': int(os.getenv('REDIS_CACHE_TTL_BALANCE', '30')),
            'session': int(os.getenv('REDIS_CACHE_TTL_SESSION', '3600')),
        }

class RedisClient:
    """Redis client for caching and real-time data"""

    def __init__(self, config: Optional[RedisConfig] = None):
        self.logger = logging.getLogger('PacificaBot.RedisClient')
        self.config = config or RedisConfig()
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None

        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Redis client"""
        try:
            self.logger.info(f"🔗 Connecting to Redis at {self.config.host}:{self.config.port}")

            # Create connection pool
            connection_pool = redis.ConnectionPool(
                host=self.config.host,
                port=self.config.port,
                db=self.config.db,
                password=self.config.password,
                max_connections=self.config.connection_pool_size,
                socket_timeout=self.config.socket_timeout,
                retry_on_timeout=self.config.retry_on_timeout,
                decode_responses=True
            )

            # Create Redis client
            self.redis_client = redis.Redis(
                connection_pool=connection_pool,
                socket_timeout=self.config.socket_timeout
            )

            # Test connection
            self.redis_client.ping()
            self.logger.info("✅ Redis connected successfully")

            # Initialize pub/sub
            self.pubsub = self.redis_client.pubsub()

        except redis.ConnectionError as e:
            self.logger.error(f"❌ Redis connection failed: {e}")
            self.redis_client = None
        except Exception as e:
            self.logger.error(f"❌ Error initializing Redis client: {e}")
            self.redis_client = None

    def is_connected(self) -> bool:
        """Check if Redis is connected"""
        if not self.redis_client:
            return False

        try:
            self.redis_client.ping()
            return True
        except:
            return False

    # ========== CACHE OPERATIONS ==========

    def set_cache(self, key: str, value: Any, ttl: Optional[int] = None,
                  category: str = 'general') -> bool:
        """Set a value in cache with optional TTL"""
        if not self.is_connected():
            self.logger.warning("⚠️ Redis not connected - cache operation skipped")
            return False

        try:
            # Serialize value
            if isinstance(value, (dict, list)):
                serialized_value = json.dumps(value)
            else:
                serialized_value = str(value)

            # Use category-specific TTL if not provided
            if ttl is None:
                ttl = self.config.cache_ttl.get(category, 300)

            # Set in cache
            self.redis_client.setex(key, ttl, serialized_value)
            self.logger.debug(f"💾 Cached: {key} (TTL: {ttl}s)")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error setting cache for {key}: {e}")
            return False

    def get_cache(self, key: str) -> Optional[Any]:
        """Get a value from cache"""
        if not self.is_connected():
            return None

        try:
            value = self.redis_client.get(key)
            if value is None:
                return None

            # Try to deserialize as JSON first
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Return as string if not JSON
                return value

        except Exception as e:
            self.logger.error(f"❌ Error getting cache for {key}: {e}")
            return None

    def delete_cache(self, key: str) -> bool:
        """Delete a value from cache"""
        if not self.is_connected():
            return False

        try:
            result = self.redis_client.delete(key)
            if result:
                self.logger.debug(f"🗑️ Cache deleted: {key}")
            return bool(result)
        except Exception as e:
            self.logger.error(f"❌ Error deleting cache for {key}: {e}")
            return False

    def clear_cache_pattern(self, pattern: str) -> int:
        """Clear cache entries matching a pattern"""
        if not self.is_connected():
            return 0

        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                deleted = self.redis_client.delete(*keys)
                self.logger.debug(f"🧹 Cleared {deleted} cache entries matching: {pattern}")
                return deleted
            return 0
        except Exception as e:
            self.logger.error(f"❌ Error clearing cache pattern {pattern}: {e}")
            return 0

    # ========== PRICE CACHING ==========

    def cache_price(self, symbol: str, price_data: Dict[str, Any]) -> bool:
        """Cache price data for a symbol"""
        key = f"price:{symbol}"
        return self.set_cache(key, price_data, category='prices')

    def get_cached_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached price data for a symbol"""
        key = f"price:{symbol}"
        return self.get_cache(key)

    def cache_prices(self, prices_data: Dict[str, Dict[str, Any]]) -> bool:
        """Cache multiple prices at once"""
        if not self.is_connected():
            return False

        try:
            pipe = self.redis_client.pipeline()

            for symbol, price_data in prices_data.items():
                key = f"price:{symbol}"
                serialized_value = json.dumps(price_data)
                pipe.setex(key, self.config.cache_ttl['prices'], serialized_value)

            pipe.execute()
            self.logger.debug(f"💾 Cached prices for {len(prices_data)} symbols")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error caching multiple prices: {e}")
            return False

    # ========== POSITION CACHING ==========

    def cache_position(self, symbol: str, position_data: Dict[str, Any]) -> bool:
        """Cache position data for a symbol"""
        key = f"position:{symbol}"
        return self.set_cache(key, position_data, category='positions')

    def get_cached_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached position data for a symbol"""
        key = f"position:{symbol}"
        return self.get_cache(key)

    def cache_positions(self, positions_data: Dict[str, Dict[str, Any]]) -> bool:
        """Cache multiple positions at once"""
        if not self.is_connected():
            return False

        try:
            pipe = self.redis_client.pipeline()

            for symbol, position_data in positions_data.items():
                key = f"position:{symbol}"
                serialized_value = json.dumps(position_data)
                pipe.setex(key, self.config.cache_ttl['positions'], serialized_value)

            pipe.execute()
            self.logger.debug(f"💾 Cached positions for {len(positions_data)} symbols")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error caching multiple positions: {e}")
            return False

    # ========== BALANCE CACHING ==========

    def cache_balance(self, balance_data: Dict[str, Any]) -> bool:
        """Cache account balance data"""
        key = "balance:account"
        return self.set_cache(key, balance_data, category='balance')

    def get_cached_balance(self) -> Optional[Dict[str, Any]]:
        """Get cached account balance data"""
        key = "balance:account"
        return self.get_cache(key)

    # ========== SESSION MANAGEMENT ==========

    def cache_session_data(self, session_id: str, session_data: Dict[str, Any]) -> bool:
        """Cache session data"""
        key = f"session:{session_id}"
        return self.set_cache(key, session_data, category='session')

    def get_cached_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get cached session data"""
        key = f"session:{session_id}"
        return self.get_cache(key)

    def update_session_activity(self, session_id: str) -> bool:
        """Update session last activity timestamp"""
        try:
            key = f"session:{session_id}:activity"
            activity_data = {
                'last_activity': datetime.now().isoformat(),
                'session_id': session_id
            }
            return self.set_cache(key, activity_data, category='session')
        except Exception as e:
            self.logger.error(f"❌ Error updating session activity: {e}")
            return False

    # ========== PUB/SUB FUNCTIONALITY ==========

    def publish_trade_signal(self, symbol: str, signal_data: Dict[str, Any]) -> bool:
        """Publish a trading signal"""
        if not self.is_connected():
            return False

        try:
            channel = f"signals:{symbol}"
            message = json.dumps({
                'type': 'trade_signal',
                'symbol': symbol,
                'data': signal_data,
                'timestamp': datetime.now().isoformat()
            })

            result = self.redis_client.publish(channel, message)
            self.logger.debug(f"📡 Published signal for {symbol}: {result} subscribers")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error publishing trade signal: {e}")
            return False

    def publish_price_update(self, symbol: str, price_data: Dict[str, Any]) -> bool:
        """Publish price update"""
        if not self.is_connected():
            return False

        try:
            channel = f"prices:{symbol}"
            message = json.dumps({
                'type': 'price_update',
                'symbol': symbol,
                'data': price_data,
                'timestamp': datetime.now().isoformat()
            })

            result = self.redis_client.publish(channel, message)
            self.logger.debug(f"📡 Published price update for {symbol}")
            return bool(result)

        except Exception as e:
            self.logger.error(f"❌ Error publishing price update: {e}")
            return False

    def subscribe_to_signals(self, symbols: List[str]) -> Optional[redis.client.PubSub]:
        """Subscribe to trading signals for given symbols"""
        if not self.is_connected():
            return None

        try:
            channels = [f"signals:{symbol}" for symbol in symbols]
            self.pubsub.subscribe(*channels)
            self.logger.info(f"📡 Subscribed to signals for: {symbols}")
            return self.pubsub

        except Exception as e:
            self.logger.error(f"❌ Error subscribing to signals: {e}")
            return None

    def subscribe_to_prices(self, symbols: List[str]) -> Optional[redis.client.PubSub]:
        """Subscribe to price updates for given symbols"""
        if not self.is_connected():
            return None

        try:
            channels = [f"prices:{symbol}" for symbol in symbols]
            self.pubsub.subscribe(*channels)
            self.logger.info(f"📡 Subscribed to price updates for: {symbols}")
            return self.pubsub

        except Exception as e:
            self.logger.error(f"❌ Error subscribing to price updates: {e}")
            return None

    # ========== UTILITY METHODS ==========

    def get_cache_info(self) -> Dict[str, Any]:
        """Get Redis cache information"""
        if not self.is_connected():
            return {'connected': False}

        try:
            info = self.redis_client.info()
            return {
                'connected': True,
                'memory_used': info.get('used_memory_human', '0B'),
                'connected_clients': info.get('connected_clients', 0),
                'uptime_days': info.get('uptime_in_days', 0),
                'keyspace_hits': info.get('keyspace_hits', 0),
                'keyspace_misses': info.get('keyspace_misses', 0),
            }
        except Exception as e:
            self.logger.error(f"❌ Error getting cache info: {e}")
            return {'connected': False, 'error': str(e)}

    def cleanup_expired_sessions(self) -> int:
        """Clean up expired session data"""
        if not self.is_connected():
            return 0

        try:
            # Find all session keys
            session_keys = self.redis_client.keys("session:*:activity")

            expired_count = 0
            for key in session_keys:
                activity_data = self.get_cache(key)
                if activity_data:
                    last_activity = datetime.fromisoformat(activity_data['last_activity'])
                    # Expire sessions after 24 hours of inactivity
                    if datetime.now() - last_activity > timedelta(hours=24):
                        session_id = activity_data['session_id']
                        # Delete all session-related keys
                        pattern = f"session:{session_id}:*"
                        deleted = self.clear_cache_pattern(pattern)
                        expired_count += deleted

            if expired_count > 0:
                self.logger.info(f"🧹 Cleaned up {expired_count} expired session entries")

            return expired_count

        except Exception as e:
            self.logger.error(f"❌ Error cleaning up expired sessions: {e}")
            return 0

    def flush_all_cache(self) -> bool:
        """Flush all cache data (use with caution)"""
        if not self.is_connected():
            return False

        try:
            self.redis_client.flushdb()
            self.logger.warning("💥 All cache data flushed")
            return True
        except Exception as e:
            self.logger.error(f"❌ Error flushing cache: {e}")
            return False

    def health_check(self) -> Dict[str, Any]:
        """Perform a comprehensive health check"""
        health = {
            'redis_connected': self.is_connected(),
            'timestamp': datetime.now().isoformat(),
        }

        if self.is_connected():
            try:
                # Basic operations test
                test_key = "health_check:test"
                test_value = {"test": "data", "timestamp": datetime.now().isoformat()}

                # Test write
                write_success = self.set_cache(test_key, test_value, ttl=10)

                # Test read
                read_value = self.get_cache(test_key) if write_success else None

                # Test delete
                delete_success = self.delete_cache(test_key) if read_value else False

                health.update({
                    'write_test': write_success,
                    'read_test': read_value is not None,
                    'delete_test': delete_success,
                    'cache_info': self.get_cache_info(),
                })

            except Exception as e:
                health['error'] = str(e)

        return health