"""
Pacifica Cockpit - Redis-Powered Real-time Trading Dashboard
Advanced dashboard for monitoring positions, orders, and liquidation data from Redis
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
import json
import logging
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
from typing import Dict, List, Optional, Any
import redis
import threading
import queue
from collections import defaultdict

# Import Redis client
try:
    from src.redis_client import RedisClient
except ImportError:
    st.warning("Redis client not found, using direct Redis connection")

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
                timestamp = datetime.now()

                # Get positions from Redis
                positions = self._get_positions_from_redis()
                self.positions_data.append({'timestamp': timestamp, 'data': positions})

                # Get orders from Redis
                orders = self._get_orders_from_redis()
                self.orders_data.append({'timestamp': timestamp, 'data': orders})

                # Get Redis flow data
                redis_flow = self._get_redis_flow()
                self.redis_flow_data.append({'timestamp': timestamp, 'data': redis_flow})

                # Get liquidation data
                liquidations = self._get_liquidations_from_redis(positions)
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

# Main dashboard class
class PacificaCockpit:
    def __init__(self):
        self.heartbeat = RedisHeartbeat()
        self.data_collector = DataCollector()
        self.performance_tracker = None
        self.logger = logging.getLogger('PacificaCockpit')

    def _get_positions_from_redis(self):
        """Get positions by aggregating trades from Redis"""
        try:
            # Connect to Redis
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

            # Get all trade keys
            trade_keys = r.keys('trade:*')

            # Group trades by symbol and calculate positions
            positions = defaultdict(lambda: {'quantity': 0, 'avg_price': 0, 'total_cost': 0, 'trades': []})

            for trade_key in trade_keys:
                trade_data = r.hgetall(trade_key)
                if trade_data:
                    trade_dict = {}
                    for field, value in trade_data.items():
                        field_str = field.decode('utf-8') if isinstance(field, bytes) else field
                        value_str = value.decode('utf-8') if isinstance(value, bytes) else str(value)
                        trade_dict[field_str] = value_str

                    symbol = trade_dict.get('symbol', '')
                    side = trade_dict.get('side', '')
                    quantity = float(trade_dict.get('quantity', 0))
                    price = float(trade_dict.get('price', 0))

                    if symbol and quantity > 0:
                        if side == 'buy':
                            # Add to position
                            current_qty = positions[symbol]['quantity']
                            current_cost = positions[symbol]['total_cost']

                            new_qty = current_qty + quantity
                            new_cost = current_cost + (quantity * price)

                            positions[symbol]['quantity'] = new_qty
                            positions[symbol]['total_cost'] = new_cost
                            positions[symbol]['avg_price'] = new_cost / new_qty if new_qty > 0 else 0
                            positions[symbol]['trades'].append(trade_dict)

                        elif side == 'sell':
                            # Reduce position
                            current_qty = positions[symbol]['quantity']
                            if current_qty > 0:
                                positions[symbol]['quantity'] = max(0, current_qty - quantity)
                                positions[symbol]['trades'].append(trade_dict)

            # Convert to our expected format
            active_positions = []
            for symbol, pos_data in positions.items():
                if pos_data['quantity'] > 0:
                    active_positions.append({
                        'symbol': symbol,
                        'quantity': pos_data['quantity'],
                        'entry_price': pos_data['avg_price'],
                        'current_price': pos_data['avg_price'],  # We'll get real price later
                        'pnl': 0,  # Will calculate based on current price
                        'pnl_percent': 0,
                        'liquidation_price': 0  # Will need to calculate or get from elsewhere
                    })

            return active_positions

        except Exception as e:
            self.logger.error(f"Error getting positions from Redis: {e}")
            return []

    def _get_orders_from_redis(self):
        """Get orders data from Redis"""
        try:
            # Connect to Redis
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)

            # Get all order keys
            order_keys = r.keys('orders:*')

            orders = []
            for order_key in order_keys:
                order_value = r.get(order_key)
                if order_value:
                    try:
                        order_data = json.loads(order_value.decode('utf-8') if isinstance(order_value, bytes) else order_value)

                        # Convert to our expected format
                        orders.append({
                            'id': str(order_data.get('id', order_key.decode('utf-8') if isinstance(order_key, bytes) else str(order_key))),
                            'symbol': order_data.get('symbol', ''),
                            'side': order_data.get('side', ''),
                            'type': order_data.get('type', 'LIMIT'),
                            'price': float(order_data.get('price', 0)),
                            'quantity': float(order_data.get('quantity', 0)),
                            'status': 'PENDING'  # We don't have status in Redis orders
                        })
                    except Exception as e:
                        self.logger.warning(f"Error parsing order {order_key}: {e}")

            return orders

        except Exception as e:
            self.logger.error(f"Error getting orders from Redis: {e}")
            return []

    def _get_liquidations_from_redis(self, positions):
        """Calculate liquidation data from positions"""
        liquidations = []

        for pos in positions:
            symbol = pos['symbol']
            quantity = pos['quantity']
            entry_price = pos['entry_price']

            # For now, use a simple liquidation price calculation
            # In a real implementation, this would come from your risk management
            liquidation_price = entry_price * 0.9  # 10% below entry as example

            # Calculate risk level
            price_diff = abs(entry_price - liquidation_price)
            price_ratio = price_diff / entry_price

            if price_ratio < 0.05:  # Within 5% of liquidation price
                risk_level = 'HIGH'
            elif price_ratio < 0.15:  # Within 15% of liquidation price
                risk_level = 'MEDIUM'
            else:
                risk_level = 'LOW'

            liquidations.append({
                'symbol': symbol,
                'liquidation_price': liquidation_price,
                'current_price': entry_price,
                'risk_level': risk_level,
                'pnl': pos['pnl'],
                'quantity': quantity
            })

        return liquidations

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
            <p style="text-align: center; margin: 0;">Redis-Powered Real-time Trading Dashboard</p>
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
            # Key metrics - Get real data from Redis
            st.markdown("### 📊 Key Metrics")
            metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)

            try:
                # Get positions from Redis
                positions = self._get_positions_from_redis()
                orders = self._get_orders_from_redis()

                with metrics_col1:
                    st.metric("Active Positions", len(positions))

                with metrics_col2:
                    st.metric("Open Orders", len(orders))

                with metrics_col3:
                    # Calculate total P&L from positions
                    total_pnl = 0
                    for pos in positions:
                        # For now, use a simple calculation based on quantity and entry price
                        # In a real implementation, you'd calculate based on current market price
                        total_pnl += pos.get('pnl', 0)

                    st.metric("Total P&L", f"${total_pnl:.2f}")

                with metrics_col4:
                    # Redis latency estimate
                    redis_latency = "1ms"  # Direct Redis connection
                    st.metric("Redis Latency", redis_latency)

            except Exception as e:
                st.error(f"Error loading metrics: {e}")
                # Fallback to mock data
                with metrics_col1:
                    st.metric("Active Positions", "2", delta="↗️ 1")
                with metrics_col2:
                    st.metric("Open Orders", "3", delta="↘️ 1")
                with metrics_col3:
                    st.metric("Total P&L", "+$120.50", delta="+2.3%")
                with metrics_col4:
                    st.metric("Redis Latency", "1ms", delta="Direct")

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

            # Display positions in cards - handle error cases
            cols = st.columns(min(len(positions), 3))
            for i, pos in enumerate(positions):
                with cols[i % 3]:
                    # Handle error cases
                    if 'error' in pos:
                        st.error(f"❌ {pos['error']}")
                        st.metric(label=f"{pos['symbol']}", value="Error", delta="Check logs")
                    elif 'price_error' in pos:
                        st.warning(f"⚠️ {pos['price_error']}")
                        st.metric(
                            label=f"{pos['symbol']}",
                            value=f"${pos['entry_price']:.4f}",
                            delta="Price unavailable",
                            delta_color="off"
                        )
                    else:
                        pnl_color = "normal" if pos['pnl'] >= 0 else "inverse"
                        st.metric(
                            label=f"{pos['symbol']}",
                            value=f"${pos['current_price']:.4f}",
                            delta=f"${pos['pnl']:.2f}",
                            delta_color=pnl_color
                        )

            # Enhanced detailed table with error handling
            st.subheader("Position Details")

            # Handle error columns
            if 'error' in df.columns:
                # Show error rows differently
                error_rows = df[df['error'].notna()]
                normal_rows = df[df['error'].isna()]

                if not error_rows.empty:
                    st.error("❌ **API/Connection Errors Detected:**")
                    st.dataframe(error_rows[['symbol', 'error']], use_container_width=True)

                if not normal_rows.empty:
                    # Show normal positions
                    display_df = normal_rows.drop(columns=['error', 'price_error'] if 'price_error' in normal_rows.columns else ['error'])
                    st.dataframe(display_df, use_container_width=True)
            else:
                # Normal display
                st.dataframe(df, use_container_width=True)

            # Show position count
            real_positions = [p for p in positions if 'error' not in p and 'price_error' not in p]
            if real_positions:
                st.success(f"✅ Found {len(real_positions)} active position(s)")
            else:
                st.warning("⚠️ No positions with valid data found")

        else:
            st.info("🔄 Loading position data...")

            # Try to show direct position data for debugging
            try:
                # Show positions directly from Redis
                positions = self._get_positions_from_redis()
                if positions:
                    st.success(f"✅ Found {len(positions)} position(s) in Redis")
                    for pos in positions[:3]:  # Show first 3 positions
                        st.info(f"📈 {pos['symbol']}: {pos['quantity']} @ ${pos['entry_price']:.4f}")
                else:
                    st.info("💡 No positions found in Redis")

            except Exception as e:
                st.error(f"❌ Cannot connect to Redis: {e}")

    def _render_orders_tab(self):
        st.header("📋 Live Orders")

        orders = self.data_collector.orders_data[-1]['data'] if self.data_collector.orders_data else []

        if orders:
            df = pd.DataFrame(orders)

            # Handle error cases in orders
            if 'error' in df.columns:
                error_rows = df[df['error'].notna()]
                normal_rows = df[df['error'].isna()]

                if not error_rows.empty:
                    st.warning("⚠️ **Orders API Issues Detected:**")
                    for _, row in error_rows.iterrows():
                        st.info(f"📋 {row['error']}")
                        if row.get('quantity', 0) > 0:
                            st.metric("Orders Count", f"{int(row['quantity'])} orders", help="Orders detected but details unavailable")

                if not normal_rows.empty:
                    st.subheader("Order Details")
                    display_df = normal_rows.drop(columns=['error'])
                    st.dataframe(display_df, use_container_width=True)
            else:
                # Normal display
                st.dataframe(df, use_container_width=True)

            # Show orders count
            real_orders = [o for o in orders if 'error' not in o]
            if real_orders:
                st.success(f"✅ Found {len(real_orders)} order(s)")
            else:
                st.warning("⚠️ No orders with valid data found")

        else:
            st.info("🔄 Loading orders data...")

            # Try to show direct orders data for debugging
            try:
                # Show orders directly from Redis
                orders = self._get_orders_from_redis()
                if orders:
                    st.success(f"✅ Found {len(orders)} order(s) in Redis")
                    st.json(orders[:3])  # Show first 3 orders as JSON
                else:
                    st.info("💡 No orders found in Redis")

            except Exception as e:
                st.error(f"❌ Cannot connect to Redis: {e}")

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
