import os
import sys
import pandas as pd
import numpy as np
import pytest

# Add project root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.data_manager import DataManager
from backend.predictive_engine import PredictiveEngine

@pytest.fixture
def sample_stock_df():
    """Generates a dummy historical DataFrame with 100 rows."""
    np.random.seed(42)
    dates = pd.date_range(start="2023-01-01", periods=100)
    
    # Simulate random walk for prices
    close = 150.0
    closes = []
    for _ in range(100):
        close *= (1 + np.random.normal(0, 0.01))
        closes.append(close)
        
    df = pd.DataFrame({
        'Date': dates,
        'Open': [c * (1 + np.random.normal(0, 0.005)) for c in closes],
        'High': [c * 1.01 for c in closes],
        'Low': [c * 0.99 for c in closes],
        'Close': closes,
        'Volume': np.random.randint(1000000, 5000000, size=100),
        'Dividends': 0.0,
        'Stock Splits': 0.0
    })
    return df

def test_dtype_optimization(sample_stock_df):
    # Verify we start with standard pandas float64 types
    assert sample_stock_df['Close'].dtype == np.float64
    
    # Run optimization
    df_opt = DataManager.optimize_dtypes(sample_stock_df)
    
    # Check that Close is downcasted to float32
    assert df_opt['Close'].dtype == np.float32
    # Check that Volume is downcasted to uint32 (since values are positive integers < 4B)
    assert df_opt['Volume'].dtype in [np.uint32, np.int32]

def test_technical_indicators_generation(sample_stock_df):
    df_indicators = DataManager.compute_technical_indicators(sample_stock_df)
    
    # Verify calculated indicators exist
    expected_cols = [
        'SMA_20', 'SMA_50', 'EMA_12', 'EMA_26', 'EMA_50',
        'RSI_14', 'MACD', 'MACD_Signal', 'MACD_Hist',
        'BB_Middle', 'BB_Upper', 'BB_Lower', 'BB_Width'
    ]
    for col in expected_cols:
        assert col in df_indicators.columns
        assert df_indicators[col].dtype == np.float32
        
    # Verify NaNs are dropped
    assert not df_indicators.isnull().values.any()
    # The shape should be smaller by 49 rows (due to SMA_50 and rolling window dependencies)
    assert len(df_indicators) == len(sample_stock_df) - 49

def test_predictive_engine_pipeline(sample_stock_df):
    df_indicators = DataManager.compute_technical_indicators(sample_stock_df)
    
    # Initialize engine
    engine = PredictiveEngine(model_type="gradient_boosting")
    
    # 1. Prepare data
    X, y, X_latest = engine.prepare_data(df_indicators)
    
    # Assert dimensions
    # X should have length of (df_indicators - 1) because the last row is shifted to create targets
    assert len(X) == len(df_indicators) - 1
    assert len(y) == len(df_indicators) - 1
    assert X_latest.shape == (1, len(engine.feature_cols))
    
    # 2. Train and evaluate
    metrics = engine.train_and_evaluate(df_indicators)
    
    assert "mae" in metrics
    assert "mape" in metrics
    assert "r2" in metrics
    assert "directional_accuracy" in metrics
    assert metrics["train_samples"] > 0
    assert metrics["test_samples"] > 0
    
    # 3. Predict next interval price
    next_price = engine.predict_next(df_indicators)
    assert isinstance(next_price, float)
    assert next_price > 0.0
