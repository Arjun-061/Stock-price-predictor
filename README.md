# Stock Analyser - Stock Market Analyzer Web Application

An advanced stock analytics dashboard featuring live-mocked prices via WebSockets, automated machine learning price predictions ($t+1$), and key performance indicators. The backend is built using FastAPI and Scikit-Learn, while the frontend is constructed with high-fidelity glassmorphism Vanilla CSS and responsive Plotly.js charts.

## Features

- **No API key needed**: All real market data (history + company search) comes from Yahoo Finance via the free `yfinance` library. Nothing to sign up for, nothing to configure.
- **Search by company name or ticker**: Type "apple", "tesla", or "AAPL" in the search box and pick from a live autocomplete dropdown — no need to know the exact ticker symbol.
- **Real Historical Data**: Pulls actual historical OHLCV data for any publicly traded ticker.
- **Predictive ML Engine**: Uses a Gradient Boosting Regressor (Scikit-Learn) trained on historical data to predict the next closing price ($t+1$) based on technical indicator combinations.
- **Advanced Technical Indicators**: Computes SMA (20, 50), EMA (12, 26, 50), RSI (14), MACD (Signal, Histogram), and Bollinger Bands (Upper, Middle, Lower, Width).
- **RAM Optimization**: Vectorized NumPy/Pandas processing downcasts all default float64 columns to float32, and integers to appropriate narrow uint/int sub-types, lowering memory requirements.
- **High-Quality UI**: Glassmorphic layout styled in a warm cream & terracotta theme, with color-coded KPI cards, an accented active-selection indicator, and themed scrollbars throughout. Contains multi-pane charts overlaying prices with moving averages, Bollinger bands, and ML prediction boundaries.
- **Note on the "Live Ticker"**: The sidebar's WebSocket price ticks are a simulated random-walk animation layered on top of the real last close (there's no free real-time tick feed without a paid API key). It's labeled as simulated in the UI. The historical chart, indicators, and ML predictions are all computed from real data.

---

## Directory Structure

```text
stock_analyzer/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI Web & WebSocket server
│   ├── data_manager.py      # yfinance data pull & indicator builder
│   └── predictive_engine.py # ML training and prediction pipeline
├── frontend/
│   └── static/
│       ├── index.html       # HTML structure (SEO optimized)
│       ├── style.css        # Glassmorphic custom styling
│       └── app.js           # REST/WS consumer and Plotly visualizer
├── tests/
│   └── test_prediction.py   # Automated pytest suite
├── requirements.txt         # Package dependencies
├── run.py                   # Server execution entrypoint
└── README.md                # Documentation (this file)
```

---

## Technical Details

### 1. Vectorized Memory Optimization
Standard numerical operations in Pandas default to `float64` (8 bytes per value). To optimize performance under production loads, we iterate through DataFrame columns in `backend/data_manager.py`:
- Float values are cast to `float32` (4 bytes), yielding a **50% RAM savings** for standard price arrays.
- Integers (e.g., volume or index ranges) are downcasted to `uint8`, `uint16`, or `uint32` depending on their maximum bounds, reducing memory usage up to **75%**.

### 2. Predictive Engine Pipeline
At each timestep $t$:
1. The engine shifts the Close price by -1 to form the target: $y_{t} = Close_{t+1}$.
2. Features are scaled using `StandardScaler` to prevent larger scale values (like volume) from overpowering ratios (like RSI).
3. The Gradient Boosting model trains on historical indicators, validating on a 20% chronological test split.
4. It outputs directional accuracy: Did the model accurately predict price movement direction ($Price_{t+1} > Price_t$ vs. $Pred_{t+1} > Price_t$)?
5. A final rolling prediction for the next period is made using the latest feature row.

---

## Getting Started

### Installation

1. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

2. Configure environment (optional): a `.env` file is included with sensible
   defaults. No API key is required — market data comes from yfinance's
   public endpoints — but you can copy `.env.example` to `.env` and adjust
   `HOST`, `PORT`, `CORS_ALLOW_ORIGINS`, `LOG_LEVEL`, or
   `WS_TICK_INTERVAL_SECONDS` for your environment.

### Running Tests

Execute the automated test suite to verify model integrity:
```powershell
python -m pytest tests/
```

### Launching the Application

Start the FastAPI server:
```powershell
python run.py
```

Once running, navigate to `http://localhost:8000` in your web browser.
- Select from default stocks (e.g., AAPL, MSFT, TSLA, NVDA) or use the search bar to inspect any global ticker.
- Observe the WebSocket terminal log update live with trade ticks every 1.5 seconds.
- Watch predictions adjust and recalculate as candle intervals complete.
- The **Live Feed** connection is self-healing: if it drops (network blip, tab
  backgrounded, laptop sleep), the frontend automatically reconnects with
  backoff and a heartbeat ping keeps idle connections alive, so the pill in
  the header returns to "Live Feed Active" on its own.
