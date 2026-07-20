import os
import logging
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from bs4 import BeautifulSoup
import yfinance as yf

from .data_manager import DataManager
from .predictive_engine import PredictiveEngine

# Load configuration from a local .env file if one is present. Nothing here
# is a secret (yfinance needs no API key), but this makes host/port and CORS
# configurable per-environment without touching code.
load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

# All "live" timestamps shown to the user are in Indian Standard Time (IST),
# regardless of which server/timezone this process happens to run in.
IST = ZoneInfo("Asia/Kolkata")

# CORS: comma-separated list of allowed origins, e.g. "https://myapp.com,https://staging.myapp.com"
_cors_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
CORS_ALLOW_ORIGINS = ["*"] if _cors_env.strip() == "*" else [o.strip() for o in _cors_env.split(",") if o.strip()]

app = FastAPI(
    title="Stock Analyzer API",
    description="Backend for stock analysis and price prediction, backed by live Yahoo Finance data",
    version="2.0.0"
)

# CORS configuration to allow local connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Default watchable stocks (used as fallback or initial load)
DEFAULT_STOCKS = [
    {"symbol": "AAPL", "name": "Apple Inc."},
    {"symbol": "MSFT", "name": "Microsoft Corporation"},
    {"symbol": "GOOGL", "name": "Alphabet Inc."},
    {"symbol": "AMZN", "name": "Amazon.com Inc."},
    {"symbol": "TSLA", "name": "Tesla Inc."},
    {"symbol": "NVDA", "name": "NVIDIA Corporation"},
    {"symbol": "NFLX", "name": "Netflix Inc."},
    {"symbol": "META", "name": "Meta Platforms Inc."},
    {"symbol": "AMD", "name": "Advanced Micro Devices Inc."},
    {"symbol": "MS", "name": "Morgan Stanley"}
]


def fetch_sp500_tickers() -> List[Dict[str, str]]:
    """Fetches S&P 500 constituents from Wikipedia."""
    logger.info("Fetching S&P 500 stocks from Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read()
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', {'id': 'constituents'})
        stocks = []
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 2:
                symbol = cols[0].text.strip().replace('.', '-')
                name = cols[1].text.strip()
                stocks.append({"symbol": symbol, "name": name})
        logger.info(f"Successfully fetched {len(stocks)} stocks from Wikipedia.")
        return stocks
    except Exception as e:
        logger.error(f"Failed to fetch S&P 500 stocks: {e}")
        return []


@app.on_event("startup")
async def startup_event():
    global DEFAULT_STOCKS
    fetched = fetch_sp500_tickers()
    if fetched:
        DEFAULT_STOCKS = fetched


@app.get("/api/stocks", response_model=List[Dict[str, str]])
def get_stocks():
    """Returns a list of dynamically fetched or fallback stocks (for the popular-picks list)."""
    return DEFAULT_STOCKS[:12]


@app.get("/api/search")
def search_companies(q: str):
    """
    Resolves a free-text query (company name OR ticker symbol) into a list of
    candidate matches, e.g. "apple" -> [{"symbol": "AAPL", "name": "Apple Inc."}].
    No API key required: combines the local S&P 500 index with Yahoo Finance's
    public search endpoint (via yfinance) for broader coverage.
    """
    query = (q or "").strip()
    if not query:
        return []

    query_lower = query.lower()
    matches = []
    seen_symbols = set()

    local_matches = [
        s for s in DEFAULT_STOCKS
        if query_lower == s["symbol"].lower()
        or s["symbol"].lower().startswith(query_lower)
        or query_lower in s["name"].lower()
    ]
    local_matches.sort(key=lambda s: (not s["symbol"].lower().startswith(query_lower), s["name"]))

    for s in local_matches[:8]:
        if s["symbol"] not in seen_symbols:
            matches.append({"symbol": s["symbol"], "name": s["name"], "exchange": ""})
            seen_symbols.add(s["symbol"])

    if len(matches) < 8:
        try:
            remote_matches = DataManager.search_companies(query, max_results=8)
            for m in remote_matches:
                if m["symbol"] not in seen_symbols and len(matches) < 8:
                    matches.append(m)
                    seen_symbols.add(m["symbol"])
        except Exception as e:
            logger.warning(f"Remote company search failed, using local results only: {e}")

    return matches


@app.get("/api/quote/{symbol}")
def get_quote(symbol: str):
    """
    Fetches the current live price and day's trading stats for a symbol
    directly from Yahoo Finance (via yfinance). Used by the frontend to poll
    for an up-to-date price without re-running the full history/prediction
    pipeline. No API key required.
    """
    symbol = symbol.upper()
    try:
        ticker = yf.Ticker(symbol)

        # fast_info is a lightweight, low-latency real-time quote lookup
        fi = ticker.fast_info
        price = fi.get("lastPrice") or fi.get("last_price")
        prev_close = fi.get("previousClose") or fi.get("previous_close")
        day_high = fi.get("dayHigh") or fi.get("day_high")
        day_low = fi.get("dayLow") or fi.get("day_low")
        day_open = fi.get("open")
        volume = fi.get("lastVolume") or fi.get("last_volume")
        currency = fi.get("currency", "USD")
        market_cap = fi.get("marketCap") or fi.get("market_cap")

        if price is None:
            raise ValueError(f"No live price available for symbol: {symbol}")

        change = float(price) - float(prev_close) if prev_close else 0.0
        change_pct = (change / float(prev_close) * 100.0) if prev_close else 0.0

        return {
            "symbol": symbol,
            "price": float(price),
            "previous_close": float(prev_close) if prev_close else None,
            "open": float(day_open) if day_open else None,
            "day_high": float(day_high) if day_high else None,
            "day_low": float(day_low) if day_low else None,
            "volume": int(volume) if volume else None,
            "market_cap": int(market_cap) if market_cap else None,
            "currency": currency,
            "change": change,
            "change_percent": change_pct,
            "timestamp": datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p"),
            "timestamp_iso": datetime.now(IST).isoformat(),
            "timezone": "IST"
        }
    except Exception as e:
        logger.error(f"Error fetching live quote for {symbol}: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Could not fetch a live price for '{symbol}': {e}")


@app.get("/api/history/{symbol}")
def get_stock_history(symbol: str, period: str = "1y", interval: str = "1d"):
    """
    Fetches historical stock data from Yahoo Finance, calculates indicators,
    trains a predictive model, and returns historical data alongside
    performance metrics and a next-interval price prediction.
    """
    symbol = symbol.upper()
    try:
        try:
            ticker_info = yf.Ticker(symbol).info
            company_name = ticker_info.get('longName') or ticker_info.get('shortName') or symbol
            currency = ticker_info.get('currency') or 'USD'
        except Exception:
            company_name = symbol
            currency = 'USD'

        df = DataManager.fetch_stock_data(symbol, period=period, interval=interval)
        df_indicators = DataManager.compute_technical_indicators(df)

        engine = PredictiveEngine(model_type="gradient_boosting")
        metrics = engine.train_and_evaluate(df_indicators)
        next_pred = engine.predict_next(df_indicators)
        forecast_7day = engine.predict_next_n_days(df, n_days=7)

        X, y, X_latest = engine.prepare_data(df_indicators)
        X_scaled = engine.scaler.transform(X)
        y_pred_hist = engine.model.predict(X_scaled)

        history_list = []
        for i in range(len(df_indicators)):
            row = df_indicators.iloc[i]
            date_str = str(row['Date']).split(' ')[0] if 'Date' in df_indicators.columns else str(row.name).split(' ')[0]

            item = {
                "date": date_str,
                "open": float(row['Open']),
                "high": float(row['High']),
                "low": float(row['Low']),
                "close": float(row['Close']),
                "volume": int(row['Volume']),
                "sma20": float(row['SMA_20']) if not pd.isna(row['SMA_20']) else None,
                "sma50": float(row['SMA_50']) if not pd.isna(row['SMA_50']) else None,
                "rsi": float(row['RSI_14']) if not pd.isna(row['RSI_14']) else None,
                "macd": float(row['MACD']) if not pd.isna(row['MACD']) else None,
                "macd_signal": float(row['MACD_Signal']) if not pd.isna(row['MACD_Signal']) else None,
                "macd_hist": float(row['MACD_Hist']) if not pd.isna(row['MACD_Hist']) else None,
                "bb_upper": float(row['BB_Upper']) if not pd.isna(row['BB_Upper']) else None,
                "bb_middle": float(row['BB_Middle']) if not pd.isna(row['BB_Middle']) else None,
                "bb_lower": float(row['BB_Lower']) if not pd.isna(row['BB_Lower']) else None,
                "predicted": None
            }
            history_list.append(item)

        for idx in range(len(y_pred_hist)):
            target_idx = idx + 1
            if target_idx < len(history_list):
                history_list[target_idx]["predicted"] = float(y_pred_hist[idx])

        last_date = df_indicators.iloc[-1]['Date']
        if isinstance(last_date, str):
            last_date_dt = datetime.strptime(last_date.split(' ')[0], "%Y-%m-%d")
        else:
            last_date_dt = last_date.to_pydatetime()

        future_date = (last_date_dt + timedelta(days=1)).strftime("%Y-%m-%d")

        return {
            "symbol": symbol,
            "name": company_name,
            "currency": currency,
            "metrics": metrics,
            "next_prediction": next_pred,
            "future_date": future_date,
            "forecast_7day": forecast_7day,
            "history": history_list
        }
    except Exception as e:
        logger.error(f"Error processing stock history for {symbol}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Serve static frontend files
frontend_static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "static"))
os.makedirs(frontend_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=frontend_static_dir), name="static")


@app.get("/")
def read_index():
    """Serves the index.html page as the default root route."""
    index_path = os.path.join(frontend_static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return {"error": "Frontend files missing. Please run compilation / setup."}
