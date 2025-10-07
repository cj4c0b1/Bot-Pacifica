"""
Redis Monitoring Dashboard - Grafana-style Real-time Redis Data Streaming
Advanced dashboard for monitoring Redis data, bot performance, and system metrics
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
import json
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from typing import Dict, List, Optional, Any
import redis
import threading
import queue

# Import Redis client
try:
    from src.redis_client import RedisClient
except ImportError:
    st.warning("Redis client not found, using direct Redis connection")

# Configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

# Custom CSS for Grafana-style theme
def add_grafana_css():
    st.markdown("""
    <style>
    .grafana-header {
        background: linear-gradient(135deg, #3274d9 0%, #1f5f8b 100%);
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        color: white;
    }
    .grafana-title {
        font-size: 2.5em;
        font-weight: bold;
        text-align: center;
        margin-bottom: 10px;
    }
    .redis-heartbeat {
        display: inline-block;
        font-size: 1.5em;
        animation: redis-pulse 2s ease-in-out infinite both;
        color: #ff6b6b;
    }
    @keyframes redis-pulse {
        0%, 100% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.1); opacity: 0.7; }
    }
    .status-indicator {
        display: inline-block;
        width: 16px;
        height: 16px;
        border-radius: 50%;
        margin-right: 8px;
    }
    .status-connected { background-color: #4CAF50; box-shadow: 0 0 10px #4CAF50; }
    .status-disconnected { background-color: #f44336; box-shadow: 0 0 10px #f44336; }
    .status-warning { background-color: #ff9800; box-shadow: 0 0 10px #ff9800; }
    .metric-panel {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .metric-title {
        font-size: 0.9em;
        color: #888;
        margin-bottom: 5px;
    }
    .metric-value {
        font-size: 2em;
        font-weight: bold;
        color: #fff;
    }
    .metric-delta {
        font-size: 0.8em;
        color: #4CAF50;
    }
    .metric-delta.negative {
        color: #f44336;
    }
    .chart-container {
        background: rgba(255, 255, 255, 0.02);
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .redis-key {
        font-family: 'Courier New', monospace;
        background: rgba(0, 0, 0, 0.3);
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 0.8em;
    }
    .alert-panel {
        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
        color: white;
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
        border-left: 4px solid #ff4444;
    }
    .warning-panel {
        background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
        color: white;
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
        border-left: 4px solid #ff8800;
    }
    .info-panel {
        background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%);
        color: white;
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
        border-left: 4px solid #1976d2;
    }
    </style>
    """, unsafe_allow_html=True)

# Redis Monitor Class
class RedisMonitor:
    def __init__(self):
        self.redis_client = None
        self.connected = False
        self.last_ping = None
        self.connection_errors = 0

    def check_connection(self):
        try:
            if not self.redis_client:
                self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

            # Test connection
            self.redis_client.ping()
            self.connected = True
            self.last_ping = datetime.now()
            self.connection_errors = 0
        except redis.ConnectionError as e:
            self.connected = False
            self.connection_errors += 1
            self.logger.error(f"Redis connection error: {e}")
        except Exception as e:
            self.connected = False
            self.connection_errors += 1

    def get_status(self):
        return {
            'connected': self.connected,
            'last_ping': self.last_ping,
            'connection_errors': self.connection_errors,
            'status_color': 'status-connected' if self.connected else 'status-disconnected'
        }

    def get_redis_info(self):
        """Get comprehensive Redis information"""
        if not self.connected:
            return {}

        try:
            info = self.redis_client.info()
            return {
                'connected_clients': info.get('connected_clients', 0),
                'used_memory': info.get('used_memory_human', '0B'),
                'uptime_days': info.get('uptime_in_days', 0),
                'total_commands_processed': info.get('total_commands_processed', 0),
                'keyspace_hits': info.get('keyspace_hits', 0),
                'keyspace_misses': info.get('keyspace_misses', 0),
                'evicted_keys': info.get('evicted_keys', 0),
                'expired_keys': info.get('expired_keys', 0),
            }
        except Exception as e:
            self.logger.error(f"Error getting Redis info: {e}")
            return {}

    def get_keys_by_pattern(self, pattern="*"):
        """Get Redis keys matching pattern"""
        if not self.connected:
            return []

        try:
            keys = self.redis_client.keys(pattern)
            return [key.decode('utf-8') if isinstance(key, bytes) else key for key in keys]
        except Exception as e:
            self.logger.error(f"Error getting keys: {e}")
            return []

    def get_key_value(self, key):
        """Get value of a specific Redis key"""
        if not self.connected:
            return None

        try:
            value = self.redis_client.get(key)
            if value:
                try:
                    # Try to parse as JSON
                    return json.loads(value.decode('utf-8') if isinstance(value, bytes) else value)
                except:
                    # Return as string if not JSON
                    return value.decode('utf-8') if isinstance(value, bytes) else str(value)
            return None
        except Exception as e:
            self.logger.error(f"Error getting key {key}: {e}")
            return None

# Data Streaming Class
class RedisDataStreamer:
    def __init__(self, redis_monitor):
        self.redis_monitor = redis_monitor
        self.metrics_data = []
        self.performance_data = []
        self.bot_status_data = []
        self.running = False
        self.data_queue = queue.Queue()

    def start_streaming(self):
        self.running = True
        threading.Thread(target=self._stream_data, daemon=True).start()

    def stop_streaming(self):
        self.running = False

    def _stream_data(self):
        while self.running:
            try:
                timestamp = datetime.now()

                # Collect Redis metrics
                if self.redis_monitor.connected:
                    redis_info = self.redis_monitor.get_redis_info()

                    # Stream Redis performance metrics
                    metrics = {
                        'timestamp': timestamp,
                        'connected_clients': redis_info.get('connected_clients', 0),
                        'memory_used': redis_info.get('used_memory', '0B'),
                        'commands_processed': redis_info.get('total_commands_processed', 0),
                        'keyspace_hits': redis_info.get('keyspace_hits', 0),
                        'keyspace_misses': redis_info.get('keyspace_misses', 0),
                    }
                    self.metrics_data.append(metrics)

                    # Stream bot performance data
                    performance = self._get_bot_performance_data()
                    if performance:
                        performance['timestamp'] = timestamp
                        self.performance_data.append(performance)

                    # Stream bot status
                    bot_status = self._get_bot_status_data()
                    if bot_status:
                        bot_status['timestamp'] = timestamp
                        self.bot_status_data.append(bot_status)

                # Keep only last 100 data points
                for data_list in [self.metrics_data, self.performance_data, self.bot_status_data]:
                    if len(data_list) > 100:
                        data_list.pop(0)

                time.sleep(2)  # Update every 2 seconds

            except Exception as e:
                st.error(f"Streaming error: {e}")
                time.sleep(5)

    def _get_bot_performance_data(self):
        """Get bot performance data from Redis"""
        try:
            # Look for performance-related keys
            perf_keys = self.redis_monitor.get_keys_by_pattern("perf:*")
            if perf_keys:
                # Get latest performance data
                latest_key = max(perf_keys)  # Get most recent
                data = self.redis_monitor.get_key_value(latest_key)
                if data:
                    return {
                        'total_trades': data.get('total_trades', 0),
                        'winning_trades': data.get('winning_trades', 0),
                        'losing_trades': data.get('losing_trades', 0),
                        'total_pnl': data.get('total_pnl', 0),
                        'win_rate': data.get('win_rate', 0),
                        'avg_trade_duration': data.get('avg_trade_duration', 0),
                    }
        except Exception as e:
            pass
        return None

    def _get_bot_status_data(self):
        """Get bot status from Redis"""
        try:
            # Look for bot status keys
            status_keys = self.redis_monitor.get_keys_by_pattern("bot:status*")
            if status_keys:
                latest_key = max(status_keys)
                data = self.redis_monitor.get_key_value(latest_key)
                if data:
                    return {
                        'status': data.get('status', 'unknown'),
                        'last_activity': data.get('last_activity', ''),
                        'active_positions': data.get('active_positions', 0),
                        'open_orders': data.get('open_orders', 0),
                    }
        except Exception as e:
            pass
        return None

# Main Dashboard Class
class RedisMonitoringDashboard:
    def __init__(self):
        self.redis_monitor = RedisMonitor()
        self.data_streamer = RedisDataStreamer(self.redis_monitor)

    def run(self):
        # Page configuration
        st.set_page_config(
            page_title="Redis Monitoring Dashboard",
            page_icon="📊",
            layout="wide",
            initial_sidebar_state="expanded"
        )

        add_grafana_css()

        # Header
        st.markdown("""
        <div class="grafana-header">
            <div class="grafana-title">📊 Redis Monitoring Dashboard</div>
            <p style="text-align: center; margin: 0;">Grafana-style Real-time Redis Data Streaming</p>
        </div>
        """, unsafe_allow_html=True)

        # Sidebar
        with st.sidebar:
            st.header("🔧 Controls")
            if st.button("🔄 Refresh Data"):
                st.rerun()

            st.subheader("Redis Connection")
            status = self.redis_monitor.get_status()
            status_icon = "🟢" if status['connected'] else "🔴"
            st.markdown(f"{status_icon} Redis: {'Connected' if status['connected'] else 'Disconnected'}")

            if status['last_ping']:
                st.caption(f"Last ping: {status['last_ping'].strftime('%H:%M:%S')}")

            if status['connection_errors'] > 0:
                st.warning(f"Connection errors: {status['connection_errors']}")

        # Check Redis connection
        self.redis_monitor.check_connection()

        # Start data streaming if not running
        if not self.data_streamer.running:
            self.data_streamer.start_streaming()

        # Main content tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🔍 Redis Keys", "📈 Performance", "🤖 Bot Status"])

        with tab1:
            self._render_overview_tab()

        with tab2:
            self._render_redis_keys_tab()

        with tab3:
            self._render_performance_tab()

        with tab4:
            self._render_bot_status_tab()

        # Auto-refresh every 3 seconds
        time.sleep(3)
        st.rerun()

    def _render_overview_tab(self):
        st.header("📊 Real-time Redis Overview")

        # Redis Heartbeat
        col1, col2, col3 = st.columns([1, 2, 1])

        with col1:
            st.markdown("### 💓 Redis Heartbeat")
            status = self.redis_monitor.get_status()
            heartbeat_html = f"""
            <div style="text-align: center;">
                <span class="status-indicator {status['status_color']}"></span>
                <span class="redis-heartbeat">{'🔴' if not status['connected'] else '💚'}</span>
                <p style="margin: 5px 0; font-size: 0.9em;">
                    {'Connected' if status['connected'] else 'Disconnected'}
                </p>
            </div>
            """
            st.markdown(heartbeat_html, unsafe_allow_html=True)

        with col2:
            # Redis Metrics Grid
            st.markdown("### 📊 Redis Metrics")
            if self.redis_monitor.connected:
                redis_info = self.redis_monitor.get_redis_info()

                metric_cols = st.columns(2)
                with metric_cols[0]:
                    st.metric("Connected Clients", redis_info.get('connected_clients', 0))
                    st.metric("Memory Used", redis_info.get('used_memory', '0B'))
                    st.metric("Uptime (days)", redis_info.get('uptime_days', 0))

                with metric_cols[1]:
                    st.metric("Commands Processed", f"{redis_info.get('total_commands_processed', 0):,}")
                    hit_rate = "N/A"
                    hits = redis_info.get('keyspace_hits', 0)
                    misses = redis_info.get('keyspace_misses', 0)
                    if hits + misses > 0:
                        hit_rate = f"{(hits / (hits + misses) * 100):.1f}%"
                    st.metric("Cache Hit Rate", hit_rate)
                    st.metric("Evicted Keys", redis_info.get('evicted_keys', 0))
            else:
                st.error("❌ Redis not connected")

        with col3:
            # Real-time Charts
            st.markdown("### 📈 Real-time Metrics")

            if self.data_streamer.metrics_data:
                recent_data = self.data_streamer.metrics_data[-20:]

                # Memory usage over time
                timestamps = [d['timestamp'] for d in recent_data]
                memory_values = []
                for d in recent_data:
                    memory_str = d.get('memory_used', '0B')
                    # Convert memory string to numeric value
                    try:
                        if 'GB' in memory_str:
                            memory_values.append(float(memory_str.replace('GB', '')) * 1024)
                        elif 'MB' in memory_str:
                            memory_values.append(float(memory_str.replace('MB', '')))
                        else:
                            memory_values.append(0)
                    except:
                        memory_values.append(0)

                fig = go.Figure()
                fig.add_trace(go.Scatter(x=timestamps, y=memory_values, mode='lines+markers', name='Memory (MB)'))
                fig.update_layout(title="Redis Memory Usage", height=200)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("📊 Collecting Redis metrics...")

    def _render_redis_keys_tab(self):
        st.header("🔍 Redis Keys Explorer")

        if not self.redis_monitor.connected:
            st.error("❌ Redis not connected")
            return

        # Key pattern search
        col1, col2 = st.columns([3, 1])
        with col1:
            pattern = st.text_input("Key Pattern", value="*", help="Use wildcards: * for any, ? for single char")
        with col2:
            if st.button("🔍 Search Keys"):
                st.rerun()

        # Get and display keys
        keys = self.redis_monitor.get_keys_by_pattern(pattern)

        if keys:
            st.success(f"✅ Found {len(keys)} keys matching pattern: `{pattern}`")

            # Show keys in expandable sections
            for key in keys[:50]:  # Limit to first 50 for performance
                with st.expander(f"🔑 {key}"):
                    value = self.redis_monitor.get_key_value(key)

                    col_a, col_b = st.columns([1, 3])
                    with col_a:
                        st.markdown(f"**Type:** `{type(value).__name__}`")
                        st.markdown(f"**Key:** `<span class='redis-key'>{key}</span>`", unsafe_allow_html=True)

                    with col_b:
                        if value is not None:
                            if isinstance(value, (dict, list)):
                                st.json(value)
                            else:
                                st.code(str(value), language='json')
                        else:
                            st.info("No value found")
        else:
            st.info(f"🔍 No keys found matching pattern: `{pattern}`")

    def _render_performance_tab(self):
        st.header("📈 Performance Metrics")

        if self.data_streamer.performance_data:
            # Convert to DataFrame for better visualization
            df = pd.DataFrame(self.data_streamer.performance_data)

            # Performance metrics over time
            fig = go.Figure()

            if 'total_trades' in df.columns:
                fig.add_trace(go.Scatter(x=df['timestamp'], y=df['total_trades'],
                                       mode='lines+markers', name='Total Trades'))

            if 'winning_trades' in df.columns:
                fig.add_trace(go.Scatter(x=df['timestamp'], y=df['winning_trades'],
                                       mode='lines+markers', name='Winning Trades'))

            if 'total_pnl' in df.columns:
                fig.add_trace(go.Scatter(x=df['timestamp'], y=df['total_pnl'],
                                       mode='lines+markers', name='Total P&L'))

            fig.update_layout(title="Bot Performance Over Time", height=300)
            st.plotly_chart(fig, use_container_width=True)

            # Current performance metrics
            latest = self.data_streamer.performance_data[-1] if self.data_streamer.performance_data else {}

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Total Trades", latest.get('total_trades', 0))
            with col2:
                win_rate = latest.get('win_rate', 0)
                st.metric("Win Rate", f"{win_rate:.1f}%")
            with col3:
                st.metric("Total P&L", f"${latest.get('total_pnl', 0):.2f}")
            with col4:
                avg_duration = latest.get('avg_trade_duration', 0)
                st.metric("Avg Duration", f"{avg_duration:.1f}s")
        else:
            st.info("📊 No performance data available yet...")

    def _render_bot_status_tab(self):
        st.header("🤖 Bot Status Monitor")

        if self.data_streamer.bot_status_data:
            latest = self.data_streamer.bot_status_data[-1] if self.data_streamer.bot_status_data else {}

            # Bot status cards
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                status = latest.get('status', 'unknown')
                status_color = {'running': '🟢', 'stopped': '🔴', 'error': '🟡'}.get(status, '⚪')
                st.metric("Bot Status", f"{status_color} {status.title()}")

            with col2:
                st.metric("Active Positions", latest.get('active_positions', 0))

            with col3:
                st.metric("Open Orders", latest.get('open_orders', 0))

            with col4:
                last_activity = latest.get('last_activity', 'N/A')
                if last_activity != 'N/A':
                    st.metric("Last Activity", last_activity)
                else:
                    st.metric("Last Activity", "No data")

            # Status history chart
            if len(self.data_streamer.bot_status_data) > 1:
                status_df = pd.DataFrame(self.data_streamer.bot_status_data)

                fig = go.Figure()
                fig.add_trace(go.Scatter(x=status_df['timestamp'], y=status_df['active_positions'],
                                       mode='lines+markers', name='Active Positions'))
                fig.add_trace(go.Scatter(x=status_df['timestamp'], y=status_df['open_orders'],
                                       mode='lines+markers', name='Open Orders'))

                fig.update_layout(title="Bot Activity Over Time", height=300)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("🤖 No bot status data available yet...")

# Run the dashboard
if __name__ == "__main__":
    dashboard = RedisMonitoringDashboard()
    dashboard.run()
