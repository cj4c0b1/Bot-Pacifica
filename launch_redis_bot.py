#!/usr/bin/env python3
"""
Redis Grid Bot Launcher
Optimized launcher for the high-performance Redis-based grid trading bot
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path
from dotenv import load_dotenv

def check_redis_connection(host='localhost', port=6379):
    """Check if Redis is running and accessible"""
    try:
        import redis
        client = redis.Redis(host=host, port=port, socket_timeout=2)
        client.ping()
        return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False

def start_redis_server():
    """Attempt to start Redis server if not running"""
    try:
        # Check if Redis is already running
        if check_redis_connection():
            print("✅ Redis server is already running")
            return True

        print("🚀 Starting Redis server...")

        # Try different Redis start methods
        try:
            # Method 1: redis-server command
            subprocess.run(['redis-server', '--daemonize', 'yes'],
                         check=True, capture_output=True)
            print("✅ Redis server started successfully")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                # Method 2: Try with full path
                subprocess.run(['/usr/local/bin/redis-server', '--daemonize', 'yes'],
                             check=True, capture_output=True)
                print("✅ Redis server started successfully")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                print("❌ Could not start Redis server automatically")
                print("💡 Please start Redis manually: redis-server")
                return False

    except Exception as e:
        print(f"❌ Error starting Redis: {e}")
        return False

def check_dependencies():
    """Check if all required dependencies are installed"""
    required_modules = ['redis', 'python-dotenv']

    missing_modules = []
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_modules.append(module)

    if missing_modules:
        print(f"❌ Missing required modules: {', '.join(missing_modules)}")
        print("💡 Install with: pip install -r requirements.txt")
        return False

    return True

def run_redis_bot(config_file=None, strategy=None, symbol=None):
    """Run the Redis grid bot with specified configuration"""

    # Load appropriate environment file
    env_file = config_file or '.env.redis'
    if os.path.exists(env_file):
        load_dotenv(env_file)
        print(f"✅ Loaded configuration: {env_file}")
    else:
        print(f"⚠️ Configuration file not found: {env_file}")
        print("💡 Using default environment variables")

    # Override settings if provided
    if strategy:
        os.environ['STRATEGY_TYPE'] = strategy
        print(f"🎯 Strategy set to: {strategy}")

    if symbol:
        os.environ['SYMBOL'] = symbol
        print(f"💰 Symbol set to: {symbol}")

    # Import and run the bot
    try:
        from grid_bot_redis import RedisGridTradingBot

        print("🚀 Starting Redis Grid Bot...")
        print("=" * 60)

        bot = RedisGridTradingBot()
        bot.show_strategy_header()
        bot.run()

    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error running bot: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True

def show_status():
    """Show current Redis and bot status"""
    print("🔍 Checking system status...")
    print("=" * 50)

    # Check Redis status
    redis_status = check_redis_connection()
    print(f"Redis Status: {'✅ Connected' if redis_status else '❌ Disconnected'}")

    if redis_status:
        try:
            import redis
            client = redis.Redis(socket_timeout=2)
            info = client.info()

            print(f"   Memory Used: {info.get('used_memory_human', 'Unknown')}")
            print(f"   Connected Clients: {info.get('connected_clients', 0)}")
            print(f"   Uptime: {info.get('uptime_in_days', 0)} days")

            # Check for bot sessions
            sessions = client.keys('session:*')
            if sessions:
                print(f"   Active Sessions: {len(sessions)}")
            else:
                print("   Active Sessions: None")

        except Exception as e:
            print(f"   Error getting Redis info: {e}")

    # Check dependencies
    deps_ok = check_dependencies()
    print(f"Dependencies: {'✅ OK' if deps_ok else '❌ Missing'}")

    print("=" * 50)

def cleanup_redis_data():
    """Clean up old Redis data"""
    if not check_redis_connection():
        print("❌ Cannot cleanup: Redis not connected")
        return False

    try:
        import redis
        client = redis.Redis(socket_timeout=5)

        # Get all keys
        all_keys = client.keys('*')

        if not all_keys:
            print("ℹ️ No data to cleanup")
            return True

        print(f"🧹 Found {len(all_keys)} keys in Redis")

        # Optional: selective cleanup (ask user)
        print("⚠️ This will delete ALL data in Redis database!")
        confirm = input("Are you sure? (type 'yes' to confirm): ")

        if confirm.lower() == 'yes':
            deleted = client.flushdb()
            print(f"✅ Cleaned up Redis database ({deleted} keys deleted)")
            return True
        else:
            print("❌ Cleanup cancelled")
            return False

    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        return False

def main():
    """Main launcher function"""
    parser = argparse.ArgumentParser(description='Redis Grid Bot Launcher')

    parser.add_argument('--config', '-c',
                       help='Configuration file to use (.env.redis, .env, etc.)')

    parser.add_argument('--strategy', '-s',
                       choices=['pure_grid', 'market_making', 'dynamic_grid', 'multi_asset', 'multi_asset_enhanced'],
                       help='Trading strategy to use')

    parser.add_argument('--symbol', '-S',
                       help='Trading symbol (BTC, ETH, SOL, etc.)')

    parser.add_argument('--status', action='store_true',
                       help='Show system status and exit')

    parser.add_argument('--start-redis', action='store_true',
                       help='Start Redis server if not running')

    parser.add_argument('--cleanup', action='store_true',
                       help='Clean up Redis database (CAUTION: deletes all data)')

    parser.add_argument('--check-deps', action='store_true',
                       help='Check if all dependencies are installed')

    args = parser.parse_args()

    # Handle different commands
    if args.status:
        show_status()
        return

    if args.cleanup:
        cleanup_redis_data()
        return

    if args.check_deps:
        deps_ok = check_dependencies()
        sys.exit(0 if deps_ok else 1)

    # Check dependencies first
    if not check_dependencies():
        print("❌ Please install missing dependencies first")
        sys.exit(1)

    # Start Redis if requested
    if args.start_redis:
        if not start_redis_server():
            print("❌ Failed to start Redis server")
            sys.exit(1)

    # Check Redis connection
    if not check_redis_connection():
        print("❌ Redis server is not running")
        print("💡 Start Redis with: redis-server")
        print("   Or use --start-redis to start automatically")
        sys.exit(1)

    print("🎯 Starting Redis Grid Bot...")
    print("=" * 60)

    # Run the bot
    success = run_redis_bot(args.config, args.strategy, args.symbol)

    if success:
        print("✅ Bot completed successfully")
    else:
        print("❌ Bot exited with errors")
        sys.exit(1)

if __name__ == "__main__":
    main()