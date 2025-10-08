"""Test script for the sound notification system."""
import sys
import os
import asyncio
from pathlib import Path

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent))

from liquidation_monitor.core.models import DetectedLiquidation, LiquidationSide
from liquidation_monitor.utils.notifications import notification_manager

async def test_sound_notification():
    """Test the sound notification system with a mock liquidation event."""
    print("Testing sound notification...")
    
    # Create a mock liquidation event
    liquidation = DetectedLiquidation(
        market="BTC-PERP",
        side=LiquidationSide.LONG,
        estimated_size_usd=100000.0,
        confidence_score=85.0,
        liquidation_price=50000.0,
        mark_price=50123.45,
        num_chunks=3
    )
    
    print("Sending test notification...")
    await notification_manager.send_notification(liquidation)
    print("Notification sent. You should have heard a sound.")
    print("If you didn't hear anything, check your system volume and sound settings.")

if __name__ == "__main__":
    # Enable sound notifications
    notification_manager.enabled_channels.add("sound")
    
    # Run the test
    asyncio.run(test_sound_notification())
