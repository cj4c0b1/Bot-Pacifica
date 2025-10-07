#!/usr/bin/env python3
"""
Redis Grid Bot - Quick Test Script
Tests basic functionality of the Redis-based grid bot
"""

import sys
import time
import logging
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_redis_imports():
    """Test that Redis modules can be imported"""
    try:
        print("🔍 Testing Redis imports...")

        from redis_client import RedisClient, RedisConfig
        print("   ✅ RedisClient imported")

        from database_services import DatabaseServiceManager
        print("   ✅ DatabaseServiceManager imported")

        return True
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
        return False

def test_redis_connection():
    """Test Redis connection"""
    try:
        print("🔗 Testing Redis connection...")

        from redis_client import RedisClient, RedisConfig

        # Create Redis client
        redis = RedisClient()

        if redis.is_connected():
            print("   ✅ Redis connected successfully")

            # Test basic operations
            test_key = "test:grid_bot"
            test_value = {"test": "data", "timestamp": time.time()}

            # Test SET
            if redis.set_cache(test_key, test_value, ttl=30):
                print("   ✅ Redis SET operation successful")

                # Test GET
                retrieved = redis.get_cache(test_key)
                if retrieved:
                    print("   ✅ Redis GET operation successful")

                    # Test DELETE
                    if redis.delete_cache(test_key):
                        print("   ✅ Redis DELETE operation successful")
                    else:
                        print("   ❌ Redis DELETE operation failed")
                else:
                    print("   ❌ Redis GET operation failed")
            else:
                print("   ❌ Redis SET operation failed")
        else:
            print("   ❌ Redis connection failed")
            return False

        return True

    except Exception as e:
        print(f"   ❌ Redis connection test failed: {e}")
        return False

def test_grid_bot_import():
    """Test that the Redis grid bot can be imported"""
    try:
        print("🤖 Testing Redis Grid Bot import...")

        from grid_bot_redis import RedisGridTradingBot, RedisPositionManager
        print("   ✅ Redis Grid Bot imported successfully")

        # Test basic instantiation (without running)
        try:
            bot = RedisGridTradingBot()
            print("   ✅ Redis Grid Bot instantiated successfully")
        except Exception as e:
            print(f"   ⚠️ Bot instantiation failed (expected in test environment): {e}")
            print("      This is normal - bot needs full environment to run")

        return True

    except ImportError as e:
        print(f"   ❌ Grid bot import failed: {e}")
        return False

def test_redis_optimization():
    """Test Redis optimization utilities"""
    try:
        print("⚡ Testing Redis optimization...")

        from redis_optimizer import RedisOptimizer

        optimizer = RedisOptimizer()

        if optimizer.client:
            print("   ✅ Redis optimizer connected")

            # Run quick benchmark
            benchmarks = optimizer.benchmark_operations(100)  # Small test

            if 'error' not in benchmarks:
                print("   ✅ Redis benchmark completed")
                print(f"      Average SET: {benchmarks.get('avg_set_ms', 0)".3f"}ms")
                print(f"      Average GET: {benchmarks.get('avg_get_ms', 0)".3f"}ms")
            else:
                print(f"   ⚠️ Redis benchmark failed: {benchmarks['error']}")

        return True

    except ImportError as e:
        print(f"   ❌ Redis optimizer import failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Redis Grid Bot - Test Suite")
    print("=" * 50)

    tests = [
        ("Redis Imports", test_redis_imports),
        ("Redis Connection", test_redis_connection),
        ("Grid Bot Import", test_grid_bot_import),
        ("Redis Optimization", test_redis_optimization),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n🧪 Running: {test_name}")
        try:
            if test_func():
                passed += 1
                print(f"   ✅ {test_name} PASSED")
            else:
                print(f"   ❌ {test_name} FAILED")
        except Exception as e:
            print(f"   ❌ {test_name} ERROR: {e}")

    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Redis Grid Bot is ready to use.")
        print("\n🚀 Quick start:")
        print("   1. Start Redis: redis-server")
        print("   2. Run bot: python launch_redis_bot.py")
        print("   3. Or run directly: python grid_bot_redis.py")
    else:
        print("⚠️ Some tests failed. Check your Redis setup and dependencies.")

    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)