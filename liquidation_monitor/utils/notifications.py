"""Notification system for liquidation alerts."""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
import aiohttp
import json

from liquidation_monitor.core.models import DetectedLiquidation
from liquidation_monitor.config.settings import settings as app_settings
from .sound_notifier import sound_notifier

logger = logging.getLogger(__name__)

class NotificationManager:
    """Manages sending notifications for liquidation events."""
    
    def __init__(self):
        """Initialize the notification manager."""
        self.telegram_chat_id: Optional[str] = None
        self.telegram_bot_token: Optional[str] = None
        self.discord_webhook_url: Optional[str] = None
        self.enabled_channels = set(app_settings.notification_channels)
        self.min_notification_size = app_settings.min_notification_size_usd
        
        # Load notification settings from environment
        self._load_notification_settings()
    
    def _load_notification_settings(self) -> None:
        """Load notification settings from environment variables."""
        import os
        
        # Telegram settings
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        # Discord settings
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        
        # Enable/disable channels based on configuration
        if "telegram" in self.enabled_channels and not (self.telegram_bot_token and self.telegram_chat_id):
            logger.warning("Telegram notifications enabled but missing required configuration"
                         " (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")
            self.enabled_channels.discard("telegram")
            
        if "discord" in self.enabled_channels and not self.discord_webhook_url:
            logger.warning("Discord notifications enabled but missing required configuration"
                         " (DISCORD_WEBHOOK_URL)")
            self.enabled_channels.discard("discord")
    
    async def send_notification(self, liquidation: DetectedLiquidation) -> None:
        """Send a notification for a liquidation event.
        
        Args:
            liquidation: The liquidation event to notify about
        """
        # Skip if below minimum size threshold
        if liquidation.estimated_size_usd < self.min_notification_size:
            return
        
        # Format the message
        message = self._format_liquidation_message(liquidation)
        
        # Play sound notification
        if "sound" in self.enabled_channels:
            try:
                from .sound_notifier import play_liquidation_sound
                play_liquidation_sound()
            except Exception as e:
                logger.warning(f"Failed to play sound notification: {e}")
        
        # Send to all enabled channels
        tasks = []
        
        if "console" in self.enabled_channels:
            tasks.append(self._send_console_notification(message))
            
        if "telegram" in self.enabled_channels and self.telegram_bot_token and self.telegram_chat_id:
            tasks.append(self._send_telegram_message(message))
            
        if "discord" in self.enabled_channels and self.discord_webhook_url:
            tasks.append(self._send_discord_message(message, liquidation))
        
        # Run all notifications concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def _format_liquidation_message(self, liquidation: DetectedLiquidation) -> str:
        """Format a liquidation event as a human-readable message.
        
        Args:
            liquidation: The liquidation event
            
        Returns:
            Formatted message string
        """
        side_emoji = "🔴" if liquidation.side == "long_liquidation" else "🟢"
        side_text = "LONG LIQUIDATION" if liquidation.side == "long_liquidation" else "SHORT LIQUIDATION"
        
        message = (
            f"{side_emoji} *{liquidation.market} {side_text}* {side_emoji}\n"
            f"💵 *Size:* ${liquidation.estimated_size_usd:,.2f}\n"
            f"💰 *Price:* ${liquidation.liquidation_price:,.2f}\n"
            f"📊 *Mark Price:* ${liquidation.mark_price:,.2f}\n"
            f"📈 *Chunks:* {liquidation.num_chunks}\n"
            f"🛡️ *Confidence:* {liquidation.confidence_score:.1f}%\n"
            f"⏰ *Time:* {liquidation.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        
        return message
    
    async def _send_console_notification(self, message: str) -> None:
        """Send a notification to the console.
        
        Args:
            message: The message to send
        """
        print("\n" + "=" * 80)
        print("LIQUIDATION ALERT")
        print("=" * 80)
        print(message)
        print("=" * 80 + "\n")
    
    async def _send_telegram_message(self, message: str) -> None:
        """Send a message via Telegram bot.
        
        Args:
            message: The message to send
        """
        if not self.telegram_bot_token or not self.telegram_chat_id:
            return
            
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        logger.error(f"Failed to send Telegram message: {response.status} - {response_text}")
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
    
    async def _send_discord_message(self, message: str, liquidation: DetectedLiquidation) -> None:
        """Send a message to Discord webhook.
        
        Args:
            message: The message to send
            liquidation: The liquidation event
        """
        if not self.discord_webhook_url:
            return
        
        # Determine color based on liquidation side (red for long liquidations, green for short)
        color = 0xFF0000 if liquidation.side == "long_liquidation" else 0x00FF00
        
        # Create embed
        embed = {
            "title": f"🚨 {liquidation.market} {'LONG' if liquidation.side == 'long_liquidation' else 'SHORT'} LIQUIDATION",
            "color": color,
            "fields": [
                {"name": "Size", "value": f"${liquidation.estimated_size_usd:,.2f}", "inline": True},
                {"name": "Price", "value": f"${liquidation.liquidation_price:,.2f}", "inline": True},
                {"name": "Mark Price", "value": f"${liquidation.mark_price:,.2f}", "inline": True},
                {"name": "Confidence", "value": f"{liquidation.confidence_score:.1f}%", "inline": True},
                {"name": "Chunks", "value": str(liquidation.num_chunks), "inline": True},
                {"name": "Time", "value": liquidation.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": True}
            ],
            "footer": {
                "text": "Pacifica DEX Liquidation Monitor"
            }
        }
        
        payload = {
            "embeds": [embed],
            "username": "Pacifica Liquidation Alerts",
            "avatar_url": "https://pacifica.finance/logo.png"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.discord_webhook_url, json=payload, timeout=10) as response:
                    if response.status != 204:
                        response_text = await response.text()
                        logger.error(f"Failed to send Discord message: {response.status} - {response_text}")
        except Exception as e:
            logger.error(f"Error sending Discord message: {e}")
    
    async def send_market_alert(
        self,
        market: str,
        message: str,
        level: str = "info",
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Send a market alert notification.
        
        Args:
            market: The market the alert is for
            message: The alert message
            level: Alert level (info, warning, critical)
            data: Additional data to include in the alert
        """
        formatted_message = f"🚨 *{market.upper()} {level.upper()}* 🚨\n{message}"
        
        if data:
            formatted_message += "\n\n*Details:*\n"
            for key, value in data.items():
                formatted_message += f"- *{key}:* {value}\n"
        
        tasks = []
        
        if "console" in self.enabled_channels:
            tasks.append(self._send_console_notification(formatted_message))
            
        if "telegram" in self.enabled_channels and self.telegram_bot_token and self.telegram_chat_id:
            tasks.append(self._send_telegram_message(formatted_message))
            
        if "discord" in self.enabled_channels and self.discord_webhook_url:
            # For Discord, use a simpler format for non-liquidation alerts
            embed = {
                "title": f"{market.upper()} {level.upper()}",
                "description": message,
                "color": 0xFFA500 if level == "warning" else (0xFF0000 if level == "critical" else 0x3498DB),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            if data:
                embed["fields"] = [
                    {"name": key, "value": str(value), "inline": True}
                    for key, value in data.items()
                ]
            
            payload = {
                "embeds": [embed],
                "username": f"Pacifica {level.capitalize()} Alerts"
            }
            
            tasks.append(self._send_discord_webhook(payload))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_discord_webhook(self, payload: Dict[str, Any]) -> None:
        """Send a generic webhook payload to Discord.
        
        Args:
            payload: The webhook payload
        """
        if not self.discord_webhook_url:
            return
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.discord_webhook_url, json=payload, timeout=10) as response:
                    if response.status != 204:
                        response_text = await response.text()
                        logger.error(f"Failed to send Discord webhook: {response.status} - {response_text}")
        except Exception as e:
            logger.error(f"Error sending Discord webhook: {e}")

# Global notification manager instance
notification_manager = NotificationManager()
