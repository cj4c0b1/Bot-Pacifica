"""
Redis Performance Optimizer
Utilities for optimizing Redis performance for high-frequency trading
"""

import os
import time
import redis
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class RedisOptimizationConfig:
    """Redis optimization configuration"""
    max_memory: str = "256mb"
    max_memory_policy: str = "volatile-lru"
    tcp_keepalive: int = 300
    timeout: int = 300
    save_config: bool = False

class RedisOptimizer:
    """Redis performance optimization utilities"""

    def __init__(self, host='localhost', port=6379):
        self.host = host
        self.port = port
        self.client: Optional[redis.Redis] = None
        self.logger = logging.getLogger('PacificaBot.RedisOptimizer')

        self._connect()

    def _connect(self):
        """Connect to Redis"""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                socket_timeout=5,
                socket_keepalive=True,
                socket_keepalive_options=(1, 3, 5)
            )
            self.client.ping()
        except Exception as e:
            self.logger.error(f"❌ Cannot connect to Redis: {e}")
            self.client = None

    def optimize_for_trading(self, config: Optional[RedisOptimizationConfig] = None) -> bool:
        """Apply trading-optimized Redis configuration"""
        if not self.client:
            self.logger.error("❌ No Redis connection available")
            return False

        try:
            opt_config = config or RedisOptimizationConfig()

            # Apply memory optimization
            self.client.config_set('maxmemory', opt_config.max_memory)
            self.client.config_set('maxmemory-policy', opt_config.max_memory_policy)

            # Apply connection optimization
            self.client.config_set('tcp-keepalive', opt_config.tcp_keepalive)
            self.client.config_set('timeout', opt_config.timeout)

            # Disable RDB snapshots for pure in-memory performance
            self.client.config_set('save', '')  # Disable saving

            # Apply network optimizations
            self.client.config_set('tcp-keepalive', '60')

            self.logger.info("✅ Redis optimized for high-frequency trading")
            return True

        except Exception as e:
            self.logger.error(f"❌ Error optimizing Redis: {e}")
            return False

    def benchmark_operations(self, iterations: int = 1000) -> Dict[str, float]:
        """Benchmark Redis operation performance"""
        if not self.client:
            return {'error': 'No Redis connection'}

        results = {}

        try:
            # Benchmark SET operations
            start_time = time.time()
            for i in range(iterations):
                self.client.set(f"bench:set:{i}", f"value:{i}", ex=10)
            set_time = (time.time() - start_time) / iterations
            results['avg_set_ms'] = set_time * 1000

            # Benchmark GET operations
            start_time = time.time()
            for i in range(iterations):
                self.client.get(f"bench:set:{i}")
            get_time = (time.time() - start_time) / iterations
            results['avg_get_ms'] = get_time * 1000

            # Benchmark INCR operations (atomic counters)
            start_time = time.time()
            for i in range(iterations):
                self.client.incr(f"bench:counter:{i}")
            incr_time = (time.time() - start_time) / iterations
            results['avg_incr_ms'] = incr_time * 1000

            # Benchmark pipeline operations
            start_time = time.time()
            pipe = self.client.pipeline()
            for i in range(iterations):
                pipe.set(f"bench:pipe:{i}", f"value:{i}", ex=10)
            pipe.execute()
            pipe_time = (time.time() - start_time) / iterations
            results['avg_pipeline_ms'] = pipe_time * 1000

            # Clean up benchmark data
            self.client.delete(*[f"bench:set:{i}" for i in range(iterations)])
            self.client.delete(*[f"bench:counter:{i}" for i in range(iterations)])
            self.client.delete(*[f"bench:pipe:{i}" for i in range(iterations)])

            return results

        except Exception as e:
            self.logger.error(f"❌ Error during benchmarking: {e}")
            return {'error': str(e)}

    def monitor_performance(self) -> Dict[str, Any]:
        """Monitor Redis performance metrics"""
        if not self.client:
            return {'error': 'No Redis connection'}

        try:
            info = self.client.info()

            performance = {
                'memory_used': info.get('used_memory_human', '0B'),
                'memory_peak': info.get('used_memory_peak_human', '0B'),
                'memory_fragmentation': info.get('mem_fragmentation_ratio', 0),
                'connected_clients': info.get('connected_clients', 0),
                'total_commands': info.get('total_commands_processed', 0),
                'commands_per_second': info.get('instantaneous_ops_per_sec', 0),
                'hit_rate': 0,
                'evicted_keys': info.get('evicted_keys', 0),
                'expired_keys': info.get('expired_keys', 0),
            }

            # Calculate hit rate
            hits = info.get('keyspace_hits', 0)
            misses = info.get('keyspace_misses', 0)
            total = hits + misses
            if total > 0:
                performance['hit_rate'] = (hits / total) * 100

            return performance

        except Exception as e:
            self.logger.error(f"❌ Error monitoring performance: {e}")
            return {'error': str(e)}

    def suggest_optimizations(self) -> Dict[str, Any]:
        """Suggest Redis optimizations based on current usage"""
        if not self.client:
            return {'error': 'No Redis connection'}

        try:
            info = self.client.info()
            suggestions = {
                'memory_optimizations': [],
                'performance_optimizations': [],
                'configuration_changes': []
            }

            # Memory suggestions
            used_memory = info.get('used_memory', 0)
            max_memory = info.get('maxmemory', 0)

            if max_memory > 0:
                memory_usage = used_memory / max_memory
                if memory_usage > 0.8:
                    suggestions['memory_optimizations'].append(
                        "High memory usage detected. Consider increasing maxmemory or reducing TTL values."
                    )

            # Fragmentation suggestions
            fragmentation = info.get('mem_fragmentation_ratio', 1.0)
            if fragmentation > 1.5:
                suggestions['memory_optimizations'].append(
                    "High memory fragmentation. Consider restarting Redis or adjusting memory policy."
                )

            # Performance suggestions
            ops_per_sec = info.get('instantaneous_ops_per_sec', 0)
            if ops_per_sec > 10000:  # High throughput
                suggestions['performance_optimizations'].append(
                    "High operation rate detected. Consider Redis Cluster for horizontal scaling."
                )

            # Hit rate suggestions
            hits = info.get('keyspace_hits', 0)
            misses = info.get('keyspace_misses', 0)
            if hits + misses > 0:
                hit_rate = hits / (hits + misses)
                if hit_rate < 0.8:
                    suggestions['performance_optimizations'].append(
                        "Low cache hit rate. Consider adjusting TTL values or cache strategies."
                    )

            return suggestions

        except Exception as e:
            self.logger.error(f"❌ Error generating suggestions: {e}")
            return {'error': str(e)}

    def cleanup_test_data(self):
        """Clean up test/benchmark data"""
        if not self.client:
            return 0

        try:
            # Clean up common test patterns
            patterns = ['bench:*', 'test:*', 'temp:*', 'debug:*']
            total_deleted = 0

            for pattern in patterns:
                keys = self.client.keys(pattern)
                if keys:
                    deleted = self.client.delete(*keys)
                    total_deleted += deleted
                    self.logger.debug(f"🧹 Cleaned {deleted} keys matching '{pattern}'")

            if total_deleted > 0:
                self.logger.info(f"✅ Cleaned up {total_deleted} test keys")

            return total_deleted

        except Exception as e:
            self.logger.error(f"❌ Error cleaning test data: {e}")
            return 0

def create_redis_config_file():
    """Create optimized Redis configuration file"""
    config_content = """# Redis configuration optimized for high-frequency trading
# Generated by Pacifica Bot Redis Optimizer

# Memory settings for trading bot
maxmemory 512mb
maxmemory-policy volatile-lru

# Performance settings
tcp-keepalive 60
timeout 300
tcp-keepalive 60

# Disable RDB snapshots for pure in-memory performance
save \"\"

# Logging
loglevel notice
logfile \"\"

# Network
bind 127.0.0.1
port 6379
"""

    config_path = "redis.conf.optimized"
    try:
        with open(config_path, 'w') as f:
            f.write(config_content)
        print(f"✅ Created optimized Redis config: {config_path}")
        return config_path
    except Exception as e:
        print(f"❌ Error creating config file: {e}")
        return None

def main():
    """Main optimization function"""
    print("🔧 Redis Performance Optimizer for Pacifica Bot")
    print("=" * 60)

    optimizer = RedisOptimizer()

    if not optimizer.client:
        print("❌ Cannot connect to Redis")
        print("💡 Make sure Redis is running: redis-server")
        return

    # Run benchmarks
    print("📊 Running performance benchmarks...")
    benchmarks = optimizer.benchmark_operations(1000)

    if 'error' not in benchmarks:
        print("✅ Benchmark Results:")
        for operation, time_ms in benchmarks.items():
            print(f"   {operation}: {time_ms".3f"}ms")
    else:
        print(f"❌ Benchmark failed: {benchmarks['error']}")

    # Monitor performance
    print("\n📈 Current Performance:")
    performance = optimizer.monitor_performance()

    if 'error' not in performance:
        for metric, value in performance.items():
            if isinstance(value, float) and value > 0:
                print(f"   {metric}: {value}")
            else:
                print(f"   {metric}: {value}")
    else:
        print(f"❌ Performance monitoring failed: {performance['error']}")

    # Generate suggestions
    print("\n💡 Optimization Suggestions:")
    suggestions = optimizer.suggest_optimizations()

    if 'error' not in suggestions:
        for category, items in suggestions.items():
            if items:
                print(f"   {category.replace('_', ' ').title()}:")
                for suggestion in items:
                    print(f"     • {suggestion}")
    else:
        print(f"❌ Error generating suggestions: {suggestions['error']}")

    # Cleanup test data
    print("\n🧹 Cleaning up test data...")
    cleaned = optimizer.cleanup_test_data()
    print(f"   Cleaned {cleaned} test keys")

    # Create optimized config
    print("\n⚙️ Creating optimized Redis config...")
    config_file = create_redis_config_file()

    if config_file:
        print(f"   Use this config: redis-server {config_file}")

    print("\n✅ Optimization complete!")

if __name__ == "__main__":
    main()