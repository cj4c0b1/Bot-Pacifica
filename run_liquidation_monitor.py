#!/usr/bin/env python3
"""Launcher script for the liquidation monitor."""
import os
import sys
import logging
from dotenv import load_dotenv

# Set up basic logging first
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG to see all messages
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('liquidation_monitor.log')
    ]
)

# Set specific log levels for noisy modules
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)

# Enable debug logging for our WebSocket client
logging.getLogger('liquidation_monitor.core.websocket_client').setLevel(logging.DEBUG)

# Load environment variables from .env.liquidation
load_dotenv('.env.liquidation')

# Set environment variables for debugging
#os.environ['LOG_LEVEL'] = 'DEBUG'  # Ensure debug logging is enabled
#os.environ['VERBOSE_WEBSOCKET'] = 'true'  # Enable verbose WebSocket logging

# Explicitly set MARKETS environment variable if not set
if 'MARKETS' not in os.environ:
    os.environ['MARKETS'] = 'BTC-PERP,ETH-PERP,SOL-PERP'  # Start with a few markets for testing

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import after setting up logging
from liquidation_monitor.main import main

if __name__ == "__main__":
    import asyncio
    
    logger = logging.getLogger(__name__)
    logger.info("Starting liquidation monitor with debug logging...")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    except Exception as e:
        logger.exception("Fatal error in main loop")
        sys.exit(1)
