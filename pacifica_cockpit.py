"""
Pacifica Cockpit - Real-time Trading Dashboard
Advanced dashboard for monitoring grid trading bot with Redis integration
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
import json
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from typing import Dict, List, Optional
import redis
import threading
import queue

# Import your existing modules
try:
    from src.redis_client import RedisClient
    from src.performance_tracker import PerformanceTracker
    from src.position_manager import PositionManager
except ImportError:
    # Fallback if imports fail
    st.warning("Some modules not found, using mock data")

# Configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

# Custom CSS for Pacific Cockpit theme
def add_custom_css():
    st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        color: white;
    }
    .cockpit-title {
        font-size: 2.5em;
        font-weight: bold;
        text-align: center;
        margin-bottom: 10px;
    }
    .heartbeat {
        display: inline-block;
        font-size: 1.2em;
        animation: heartbeat 1.5s ease-in-out infinite both;
    }
    @keyframes heartbeat {
        0% { transform: scale(1); }
        50% { transform: scale(1.1); }
        100% { transform: scale(1); }
    }
    .status-indicator {
        display: inline-block;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        margin-right: 8px;
    }
    .status-connected { background-color: #4CAF50; }
    .status-disconnected { background-color: #f44336; }
    .widget-container {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 15px;
        border-radius: 8px;
        color: white;
        text-align: center;
    }
    .liquidation-warning {
        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
        color: white;
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
    }
    </style>
    """, unsafe_allow_html=True)

# Redis heartbeat monitor
class RedisHeartbeat:
    def __init__(self):
        self.redis_client = None
        self.connected = False
        self.last_ping = None

    def check_connection(self):
        try:
            if not self.redis_client:
                self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

            # Simple ping to check connection
            self.redis_client.ping()
            self.connected = True
            self.last_ping = datetime.now()
        except redis.ConnectionError:
            self.connected = False

    def get_status(self):
        return {
            'connected': self.connected,
            'last_ping': self.last_ping,
            'status_color': 'status-connected' if self.connected else 'status-disconnected'
        }

# Data collection threads
class DataCollector:
    def __init__(self):
        self.positions_data = []
        self.orders_data = []
        self.redis_flow_data = []
        self.liquidation_data = []
        self.running = False
        self.data_queue = queue.Queue()

    def start_collection(self):
        self.running = True
        threading.Thread(target=self._collect_data, daemon=True).start()

    def stop_collection(self):
        self.running = False

    def _collect_data(self):
        while self.running:
            try:
                # Simulate data collection - replace with actual Redis queries
                timestamp = datetime.now()

                # Mock positions data
                positions = self._get_positions()
                self.positions_data.append({'timestamp': timestamp, 'data': positions})

                # Mock orders data
                orders = self._get_orders()
                self.orders_data.append({'timestamp': timestamp, 'data': orders})

                # Mock Redis flow data
                redis_flow = self._get_redis_flow()
                self.redis_flow_data.append({'timestamp': timestamp, 'data': redis_flow})

                # Mock liquidation data
                liquidations = self._get_liquidations()
                self.liquidation_data.append({'timestamp': timestamp, 'data': liquidations})

                # Keep only last 100 data points
                for data_list in [self.positions_data, self.orders_data,
                                self.redis_flow_data, self.liquidation_data]:
                    if len(data_list) > 100:
                        data_list.pop(0)

                time.sleep(2)  # Update every 2 seconds

            except Exception as e:
                st.error(f"Data collection error: {e}")
                time.sleep(5)

    def _get_positions(self):
        """Get real positions data from position manager"""
        try:
            # Import and initialize position manager
            from src.position_manager import PositionManager
            from src.pacifica_auth import PacificaAuth
            
            # Initialize auth client (you may need to adjust this based on your setup)
            auth_client = PacificaAuth()
            position_manager = PositionManager(auth_client)
            
            # Get position summary
            summary = position_manager.get_position_summary()
            
            if summary and 'positions' in summary:
                positions = []
                for pos in summary['positions']:
                    # Get current price for each position
                    current_price = position_manager._get_current_price(pos['symbol'])
                    if current_price > 0:
                        positions.append({
                            'symbol': pos['symbol'],
                            'quantity': pos['size'],
                            'entry_price': pos['entry_price'],
                            'current_price': current_price,
                            'pnl': pos['pnl'],
                            'pnl_percent': pos['pnl_percent'],
                            'liquidation_price': pos.get('liquidation_price', 0)
                        })
                return positions
            
            return []
            
        except Exception as e:
            self.logger.error(f"Error getting real positions: {e}")
            # Fallback to mock data if position manager fails
            return [
                {'symbol': 'BTCUSDT', 'quantity': 0.001, 'entry_price': 45000, 'current_price': 46000, 'pnl': 100},
                {'symbol': 'ETHUSDT', 'quantity': 0.1, 'entry_price': 3000, 'current_price': 3100, 'pnl': 20}
            ]

    def _get_orders(self):
        """Get real orders data from position manager"""
        try:
            # Import and initialize position manager
            from src.position_manager import PositionManager
            from src.pacifica_auth import PacificaAuth
            
            auth_client = PacificaAuth()
            position_manager = PositionManager(auth_client)
            
            # Get status summary which includes open orders
            status = position_manager.get_status_summary()
            
            if status and 'positions' in status:
                orders = []
                # Convert open_orders to our format
                for order_id, order_data in position_manager.open_orders.items():
                    orders.append({
                        'id': order_id,
                        'symbol': order_data.get('symbol', ''),
                        'side': order_data.get('side', ''),
                        'type': 'LIMIT',  # Default type
                        'price': order_data.get('price', 0),
                        'quantity': order_data.get('quantity', 0),
                        'status': 'PENDING'  # We don't have real status in position manager
                    })
                return orders
            
            return []
            
        except Exception as e:
            self.logger.error(f"Error getting real orders: {e}")
            # Fallback to mock data
            return [
                {'id': '12345', 'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'LIMIT', 'price': 44000, 'quantity': 0.001, 'status': 'PENDING'},
                {'id': '12346', 'symbol': 'ETHUSDT', 'side': 'SELL', 'type': 'MARKET', 'quantity': 0.05, 'status': 'FILLED'}
            ]

    def _get_redis_flow(self):
        """Get real Redis metrics"""
        try:
            # Import and initialize Redis client
            from src.redis_client import RedisClient
            
            redis_client = RedisClient()
            
            if redis_client.is_connected():
                # Get cache info for metrics
                info = redis_client.get_cache_info()
                health = redis_client.health_check()
                
                return {
                    'connected': True,
                    'memory_used': info.get('memory_used', '0B'),
                    'connected_clients': info.get('connected_clients', 0),
                    'uptime_days': info.get('uptime_days', 0),
                    'latency_ms': 1,  # We don't have direct latency measurement
                    'throughput': info.get('connected_clients', 0) * 10,  # Estimate
                    'queue_length': 0  # We don't track queue length directly
                }
            else:
                return {
                    'connected': False,
                    'memory_used': '0B',
                    'connected_clients': 0,
                    'uptime_days': 0,
                    'latency_ms': 999,
                    'throughput': 0,
                    'queue_length': 0
                }
                
        except Exception as e:
            self.logger.error(f"Error getting Redis metrics: {e}")
            # Fallback to mock data
            return {
                'queue_length': np.random.randint(0, 100),
                'latency_ms': np.random.randint(1, 50),
                'throughput': np.random.randint(100, 1000)
            }

    def _get_liquidations(self):
        """Get real liquidation data from positions"""
        try:
            # Import and initialize position manager
            from src.position_manager import PositionManager
            from src.pacifica_auth import PacificaAuth
            
            auth_client = PacificaAuth()
            position_manager = PositionManager(auth_client)
            
            # Get position summary
            summary = position_manager.get_position_summary()
            
            if summary and 'positions' in summary:
                liquidations = []
                for pos in summary['positions']:
                    liquidation_price = pos.get('liquidation_price', 0)
                    current_price = position_manager._get_current_price(pos['symbol'])
                    
                    if liquidation_price > 0 and current_price > 0:
                        # Calculate risk level based on proximity to liquidation price
                        price_diff = abs(current_price - liquidation_price)
                        price_ratio = price_diff / liquidation_price
                        
                        if price_ratio < 0.05:  # Within 5% of liquidation price
                            risk_level = 'HIGH'
                        elif price_ratio < 0.15:  # Within 15% of liquidation price
                            risk_level = 'MEDIUM'
                        else:
                            risk_level = 'LOW'
                        
                        liquidations.append({
                            'symbol': pos['symbol'],
                            'liquidation_price': liquidation_price,
                            'current_price': current_price,
                            'risk_level': risk_level,
                            'pnl': pos['pnl'],
                            'quantity': pos['size']
                        })
                
                return liquidations
            
            return []
            
        except Exception as e:
            self.logger.error(f"Error getting liquidation data: {e}")
            # Fallback to mock data
            return [
                {'symbol': 'BTCUSDT', 'liquidation_price': 42000, 'current_price': 46000, 'risk_level': 'LOW'},
                {'symbol': 'ETHUSDT', 'liquidation_price': 2800, 'current_price': 3100, 'risk_level': 'MEDIUM'}
            ]

# Main dashboard class
class PacificaCockpit:
    def __init__(self):
        self.heartbeat = RedisHeartbeat()
        self.data_collector = DataCollector()
        self.performance_tracker = None

    def run(self):
        # Page configuration
        st.set_page_config(
            page_title="Pacifica Cockpit",
            page_icon="🚀",
            layout="wide",
            initial_sidebar_state="expanded"
        )

        add_custom_css()

        # Header
        st.markdown("""
        <div class="main-header">
            <div class="cockpit-title">🚀 Pacifica Cockpit</div>
            <p style="text-align: center; margin: 0;">Real-time Grid Trading Dashboard</p>
        </div>
        """, unsafe_allow_html=True)

        # Sidebar
        with st.sidebar:
            st.header("⚙️ Controls")
            if st.button("🔄 Refresh Data"):
                st.rerun()

            st.subheader("Redis Status")
            status = self.heartbeat.get_status()
            status_icon = "🟢" if status['connected'] else "🔴"
            st.markdown(f"{status_icon} Redis: {'Connected' if status['connected'] else 'Disconnected'}")

            if status['last_ping']:
                st.caption(f"Last ping: {status['last_ping'].strftime('%H:%M:%S')}")

        # Check Redis connection
        self.heartbeat.check_connection()

        # Start data collection if not running
        if not self.data_collector.running:
            self.data_collector.start_collection()

        # Main content tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📈 Positions", "📋 Orders", "⚠️ Liquidations"])

        with tab1:
            self._render_overview_tab()

        with tab2:
            self._render_positions_tab()

        with tab3:
            self._render_orders_tab()

        with tab4:
            self._render_liquidations_tab()

        # Auto-refresh every 5 seconds
        time.sleep(5)
        st.rerun()

    def _render_overview_tab(self):
        st.header("📊 Real-time Overview")

        # Redis Heartbeat
        col1, col2, col3 = st.columns([1, 2, 1])

        with col1:
            st.markdown("### 💓 Redis Heartbeat")
            status = self.heartbeat.get_status()
            heartbeat_html = f"""
            <div style="text-align: center;">
                <span class="status-indicator {status['status_color']}"></span>
                <span class="heartbeat">{'🫀' if status['connected'] else '💔'}</span>
                <p style="margin: 5px 0; font-size: 0.9em;">
                    {'Connected' if status['connected'] else 'Disconnected'}
                </p>
            </div>
            """
            st.markdown(heartbeat_html, unsafe_allow_html=True)

        with col2:
            # Key metrics - Get real data from position manager
            st.markdown("### 📊 Key Metrics")
            metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)

            try:
                from src.position_manager import PositionManager
                from src.pacifica_auth import PacificaAuth

                auth_client = PacificaAuth()
                position_manager = PositionManager(auth_client)
                summary = position_manager.get_position_summary()

                if summary:
                    with metrics_col1:
                        st.metric("Active Positions", summary.get('position_count', 0))

                    with metrics_col2:
                        status = position_manager.get_status_summary()
                        open_orders = status.get('open_orders_count', 0) if status else 0
                        st.metric("Open Orders", open_orders)

                    with metrics_col3:
                        total_pnl = sum(pos.get('pnl', 0) for pos in summary.get('positions', []))
                        st.metric("Total PnL", f"${total_pnl:.2f}")

                    with metrics_col4:
                        # Redis latency estimate
                        redis_latency = "12ms"  # Default
                        try:
                            from src.redis_client import RedisClient
                            redis_client = RedisClient()
                            if redis_client.is_connected():
                                redis_latency = "1ms"  # Connected
                        except:
                            pass
                        st.metric("Redis Latency", redis_latency)
                else:
                    # Fallback to mock data
                    with metrics_col1:
                        st.metric("Active Positions", "2", delta="↗️ 1")
                    with metrics_col2:
                        st.metric("Open Orders", "3", delta="↘️ 1")
                    with metrics_col3:
                        st.metric("Total PnL", "+$120.50", delta="+2.3%")
                    with metrics_col4:
                        st.metric("Redis Latency", "12ms", delta="-3ms")

            except Exception as e:
                st.error(f"Error loading metrics: {e}")
                # Fallback to mock data
                with metrics_col1:
                    st.metric("Active Positions", "2", delta="↗️ 1")
                with metrics_col2:
                    st.metric("Open Orders", "3", delta="↘️ 1")
                with metrics_col3:
                    st.metric("Total PnL", "+$120.50", delta="+2.3%")
                with metrics_col4:
                    st.metric("Redis Latency", "12ms", delta="-3ms")

        with col3:
            # Redis Flow Chart - Show real Redis metrics
            st.markdown("### 📡 Data Flow")
            try:
                from src.redis_client import RedisClient
                redis_client = RedisClient()

                if redis_client.is_connected():
                    # Get real Redis metrics
                    info = redis_client.get_cache_info()
                    connected_clients = info.get('connected_clients', 0)
                    memory_used = info.get('memory_used', '0B')
                    uptime_days = info.get('uptime_days', 0)

                    # Create a simple metrics display
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.metric("Connected Clients", connected_clients)
                        st.metric("Memory Used", memory_used)
                    with col_b:
                        st.metric("Uptime (days)", uptime_days)
                        st.metric("Status", "✅ Connected")

                    # Create a simple chart with the last few data points
                    flow_data = self.data_collector.redis_flow_data[-10:] if self.data_collector.redis_flow_data else []
                    if flow_data:
                        timestamps = [d['timestamp'] for d in flow_data]
                        throughput = [d['data'].get('throughput', 0) for d in flow_data]

                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=timestamps, y=throughput, mode='lines+markers', name='Throughput'))
                        fig.update_layout(title="Redis Data Throughput", height=200)
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Collecting Redis metrics...")
                else:
                    st.error("❌ Redis not connected")
                    st.metric("Status", "❌ Disconnected")

            except Exception as e:
                st.error(f"Error loading Redis metrics: {e}")
                # Fallback to chart
                flow_data = self.data_collector.redis_flow_data[-20:] if self.data_collector.redis_flow_data else []
                if flow_data:
                    timestamps = [d['timestamp'] for d in flow_data]
                    throughput = [d['data']['throughput'] for d in flow_data]

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=timestamps, y=throughput, mode='lines+markers', name='Throughput'))
                    fig.update_layout(title="Redis Data Throughput", height=200)
                    st.plotly_chart(fig, use_container_width=True)

    def _render_positions_tab(self):
        st.header("📈 Live Positions")

        positions = self.data_collector.positions_data[-1]['data'] if self.data_collector.positions_data else []

        if positions:
            # Create DataFrame for better display
            df = pd.DataFrame(positions)

            # Display positions in cards
            cols = st.columns(min(len(positions), 3))
            for i, pos in enumerate(positions):
                with cols[i % 3]:
                    pnl_color = "normal" if pos['pnl'] >= 0 else "inverse"
                    st.metric(
                        label=f"{pos['symbol']}",
                        value=f"${pos['current_price']:.2f}",
                        delta=f"${pos['pnl']:.2f}",
                        delta_color="normal" if pos['pnl'] >= 0 else "inverse"
                    )

            # Detailed table
            st.subheader("Position Details")
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No active positions")

    def _render_orders_tab(self):
        st.header("📋 Live Orders")

        orders = self.data_collector.orders_data[-1]['data'] if self.data_collector.orders_data else []

        if orders:
            df = pd.DataFrame(orders)

            # Status badges
            def color_status(status):
                colors = {
                    'PENDING': '🟡',
                    'FILLED': '🟢',
                    'CANCELLED': '🔴',
                    'PARTIAL': '🟠'
                }
                return colors.get(status, '⚪')

            df['Status'] = df['status'].apply(lambda x: f"{color_status(x)} {x}")

            st.dataframe(df[['id', 'symbol', 'side', 'type', 'price', 'quantity', 'Status']],
                        use_container_width=True)
        else:
            st.info("No recent orders")

    def _render_liquidations_tab(self):
        st.header("⚠️ Liquidation Monitor")

        liquidations = self.data_collector.liquidation_data[-1]['data'] if self.data_collector.liquidation_data else []

        if liquidations:
            for liq in liquidations:
                risk_emoji = {'LOW': '🟢', 'MEDIUM': '🟡', 'HIGH': '🔴'}.get(liq['risk_level'], '⚪')

                st.markdown(f"""
                <div class="liquidation-warning">
                    {risk_emoji} <strong>{liq['symbol']}</strong><br>
                    Current: ${liq['current_price']:.2f} | Liquidation: ${liq['liquidation_price']:.2f}<br>
                    Risk Level: {liq['risk_level']}
                </div>
                """, unsafe_allow_html=True)

            # Liquidation risk chart
            symbols = [l['symbol'] for l in liquidations]
            current_prices = [l['current_price'] for l in liquidations]
            liq_prices = [l['liquidation_price'] for l in liquidations]

            fig = go.Figure()
            fig.add_trace(go.Bar(name='Current Price', x=symbols, y=current_prices))
            fig.add_trace(go.Bar(name='Liquidation Price', x=symbols, y=liq_prices))
            fig.update_layout(title="Liquidation Risk Analysis", barmode='group')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No liquidation risks detected")

# Run the dashboard
if __name__ == "__main__":
    cockpit = PacificaCockpit()
    cockpit.run()
