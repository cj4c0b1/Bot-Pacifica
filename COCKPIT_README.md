## 🚀 Pacifica Cockpit - Real-time Trading Dashboard

The Pacifica Cockpit is a modern, real-time dashboard for monitoring your grid trading bot operations.

### Features

- **📊 Real-time Overview**: Live metrics, Redis heartbeat, and data flow visualization
- **📈 Positions Monitor**: Real-time position tracking with P&L calculations
- **📋 Orders Dashboard**: Live order status and execution monitoring
- **⚠️ Liquidation Monitor**: Risk assessment and liquidation price tracking
- **💓 Redis Heartbeat**: Animated connectivity indicator
- **🎨 Modern UI**: Beautiful, responsive design with dark theme

### Installation & Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start Redis Server** (if not already running):
   ```bash
   redis-server
   ```

3. **Launch Dashboard**:
   ```bash
   python launch_cockpit.py
   ```

4. **Access Dashboard**:
   Open your browser and navigate to `http://localhost:8501`

### Dashboard Sections

#### 📊 Overview Tab
- **Redis Heartbeat**: Animated indicator showing Redis connectivity
- **Key Metrics**: Total positions, open orders, P&L, and latency
- **Data Flow Chart**: Real-time Redis throughput visualization

#### 📈 Positions Tab
- **Position Cards**: Visual display of current positions with P&L
- **Position Details**: Comprehensive table of all active positions

#### 📋 Orders Tab
- **Order Status**: Real-time order tracking with status badges
- **Order History**: Recent order executions and details

#### ⚠️ Liquidations Tab
- **Risk Assessment**: Color-coded liquidation risk levels
- **Risk Chart**: Visual comparison of current vs liquidation prices

### Customization

The dashboard is designed to integrate with your existing trading system:

1. **Connect Real Data**: Replace mock data functions in `pacifica_cockpit.py` with actual queries to your:
   - `position_manager` for live positions
   - `redis_client` for Redis metrics
   - Order management system for live orders

2. **Customize Styling**: Modify the CSS in `add_custom_css()` function for your preferred theme

3. **Add More Widgets**: Extend the modular design with additional monitoring components

### Technical Details

- **Framework**: Streamlit for web interface
- **Visualization**: Plotly for interactive charts
- **Real-time Updates**: Automatic refresh every 5 seconds
- **Responsive Design**: Works on desktop and mobile devices
- **Performance**: Optimized for real-time data display

The dashboard uses a modular architecture that can be easily extended with additional monitoring features as your trading system grows.
