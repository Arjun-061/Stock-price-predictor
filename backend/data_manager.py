import time
import yfinance as yf
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DataManager:
    @staticmethod
    def fetch_stock_data(symbol: str, period: str = "2y", interval: str = "1d",
                          max_retries: int = 3) -> pd.DataFrame:
        """
        Fetch historical stock data from Yahoo Finance (no API key required).
        Retries a few times with backoff since the free Yahoo endpoint is
        occasionally flaky/rate-limited. Optimizes the memory footprint of the
        loaded DataFrame.
        """
        logger.info(f"Fetching stock data for {symbol} (period={period}, interval={interval})")
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period=period, interval=interval)
                if df.empty:
                    raise ValueError(
                        f"No data found for symbol: {symbol}. "
                        f"Double-check the ticker or search by company name."
                    )

                # Reset index to make Date a column
                df = df.reset_index()

                # Optimize data types to save memory
                df = DataManager.optimize_dtypes(df)
                return df
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt}/{max_retries} failed for {symbol}: {e}")
                if attempt < max_retries:
                    time.sleep(0.75 * attempt)  # simple backoff, no external deps

        logger.error(f"Error fetching stock data for {symbol}: {str(last_error)}")
        raise last_error

    @staticmethod
    def search_companies(query: str, max_results: int = 8) -> list:
        """
        Resolves a free-text query (company name OR ticker) to a list of
        candidate {symbol, name, exchange} matches using Yahoo Finance's
        public search endpoint via yfinance. No API key required.
        """
        query = (query or "").strip()
        if not query:
            return []

        results = []
        seen_symbols = set()
        try:
            search = yf.Search(query, max_results=max_results)
            for quote in search.quotes:
                symbol = quote.get("symbol")
                if not symbol or symbol in seen_symbols:
                    continue
                name = quote.get("longname") or quote.get("shortname") or symbol
                results.append({
                    "symbol": symbol,
                    "name": name,
                    "exchange": quote.get("exchange", ""),
                    "type": quote.get("quoteType", "")
                })
                seen_symbols.add(symbol)
        except Exception as e:
            logger.warning(f"yfinance company search failed for '{query}': {e}")

        return results[:max_results]

    @staticmethod
    def optimize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
        """
        Downcasts numerical columns in DataFrame to minimize memory footprint.
        """
        initial_mem = df.memory_usage(deep=True).sum() / 1024
        
        # Iterate and downcast numeric types
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                # Downcast floats to float32
                if pd.api.types.is_float_dtype(df[col]):
                    df[col] = df[col].astype(np.float32)
                # Downcast integers to smaller int types
                elif pd.api.types.is_integer_dtype(df[col]):
                    col_min, col_max = df[col].min(), df[col].max()
                    if col_min >= 0:
                        if col_max < 255:
                            df[col] = df[col].astype(np.uint8)
                        elif col_max < 65535:
                            df[col] = df[col].astype(np.uint16)
                        else:
                            df[col] = df[col].astype(np.uint32)
                    else:
                        if col_min > -128 and col_max < 127:
                            df[col] = df[col].astype(np.int8)
                        elif col_min > -32768 and col_max < 32767:
                            df[col] = df[col].astype(np.int16)
                        else:
                            df[col] = df[col].astype(np.int32)
            elif isinstance(df[col].dtype, pd.DatetimeTZDtype) or pd.api.types.is_datetime64_any_dtype(df[col]):
                continue
            else:
                # Convert object types to category if cardinality is low
                num_unique = df[col].nunique()
                num_total = len(df)
                if num_unique / num_total < 0.5:
                    df[col] = df[col].astype('category')
                    
        final_mem = df.memory_usage(deep=True).sum() / 1024
        logger.info(f"Memory optimized from {initial_mem:.2f} KB to {final_mem:.2f} KB")
        return df

    @staticmethod
    def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Computes various technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands)
        and returns a new DataFrame with indicators attached.
        """
        df = df.copy()
        
        # Ensure sorting by Date
        if 'Date' in df.columns:
            df = df.sort_values('Date').reset_index(drop=True)
        
        close = df['Close']
        
        # 1. Moving Averages
        df['SMA_20'] = close.rolling(window=20).mean().astype(np.float32)
        df['SMA_50'] = close.rolling(window=50).mean().astype(np.float32)
        df['EMA_12'] = close.ewm(span=12, adjust=False).mean().astype(np.float32)
        df['EMA_26'] = close.ewm(span=26, adjust=False).mean().astype(np.float32)
        df['EMA_50'] = close.ewm(span=50, adjust=False).mean().astype(np.float32)
        
        # 2. RSI (Relative Strength Index) - 14 periods
        delta = close.diff()
        gain = (delta.where(delta > 0, 0.0))
        loss = (-delta.where(delta < 0, 0.0))
        
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        
        # Wilder's smoothing technique for RS
        for i in range(14, len(df)):
            avg_gain.iloc[i] = (avg_gain.iloc[i-1] * 13 + gain.iloc[i]) / 14
            avg_loss.iloc[i] = (avg_loss.iloc[i-1] * 13 + loss.iloc[i]) / 14
            
        rs = avg_gain / (avg_loss + 1e-10) # Prevent division by zero
        df['RSI_14'] = (100 - (100 / (1.0 + rs))).astype(np.float32)
        
        # 3. MACD (Moving Average Convergence Divergence)
        df['MACD'] = (df['EMA_12'] - df['EMA_26']).astype(np.float32)
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean().astype(np.float32)
        df['MACD_Hist'] = (df['MACD'] - df['MACD_Signal']).astype(np.float32)
        
        # 4. Bollinger Bands (20 periods, 2 standard deviations)
        std_20 = close.rolling(window=20).std()
        df['BB_Middle'] = df['SMA_20']
        df['BB_Upper'] = (df['BB_Middle'] + 2 * std_20).astype(np.float32)
        df['BB_Lower'] = (df['BB_Middle'] - 2 * std_20).astype(np.float32)
        df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / df['BB_Middle']).astype(np.float32)
        
        # Drop rows with NaN values resulting from window calculations
        df = df.dropna().reset_index(drop=True)
        
        logger.info(f"Technical indicators computed. Shape: {df.shape}")
        return df
