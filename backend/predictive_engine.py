import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
import logging

logger = logging.getLogger(__name__)

class PredictiveEngine:
    def __init__(self, model_type: str = "gradient_boosting"):
        self.model_type = model_type
        if model_type == "random_forest":
            self.model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        else:
            self.model = GradientBoostingRegressor(n_estimators=100, random_state=42, learning_rate=0.05)
        self.scaler = StandardScaler()
        self.feature_cols = [
            'Close', 'Open', 'High', 'Low', 'Volume',
            'SMA_20', 'SMA_50', 'EMA_12', 'EMA_26', 'EMA_50',
            'RSI_14', 'MACD', 'MACD_Signal', 'MACD_Hist',
            'BB_Middle', 'BB_Upper', 'BB_Lower', 'BB_Width'
        ]

    def prepare_data(self, df: pd.DataFrame):
        """
        Prepares the feature matrix X and target y.
        Shifts the Close price by -1 to create target y (price at t+1).
        """
        # Ensure all required features are present
        missing_cols = [col for col in self.feature_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing columns for prediction features: {missing_cols}")
        
        # Create target: price at t+1
        df_prep = df.copy()
        df_prep['Target_Close'] = df_prep['Close'].shift(-1)
        
        # The last row has Target_Close = NaN, which is the one we want to predict
        latest_row = df_prep.iloc[[-1]]
        
        # For training, drop the last row
        df_train = df_prep.dropna(subset=['Target_Close']).reset_index(drop=True)
        
        X = df_train[self.feature_cols].values
        y = df_train['Target_Close'].values
        
        X_latest = latest_row[self.feature_cols].values
        
        return X, y, X_latest

    def train_and_evaluate(self, df: pd.DataFrame):
        """
        Trains the model and evaluates it using a train-test split.
        Returns accuracy and error metrics.
        """
        X, y, X_latest = self.prepare_data(df)
        
        if len(X) < 30:
            raise ValueError("Insufficient data points for training a model. Need at least 30 historical samples after indicator generation.")
            
        # Standardize features
        X_scaled = self.scaler.fit_transform(X)
        
        # Train-test split (time-series split: we keep chronological order)
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X_scaled[:split_idx], X_scaled[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # Fit model
        logger.info(f"Training {self.model_type} model on {len(X_train)} samples...")
        self.model.fit(X_train, y_train)
        
        # Predict on test set
        y_pred = self.model.predict(X_test)
        
        # Metrics
        mae = mean_absolute_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        # Mean Absolute Percentage Error (MAPE)
        mape = np.mean(np.abs((y_test - y_pred) / y_test)) * 100
        
        # Directional Accuracy (did the model predict the correct direction of t+1 relative to t?)
        # For the test set, 'current' close is the 'Close' column of the test window.
        # X_test was scaled, but we can retrieve the raw close prices from df_train.
        # Let's map back:
        test_df = df.iloc[20:][split_idx:split_idx + len(X_test)] # aligned with X_test, adjusting for indices
        # Let's compute actual directions vs predicted directions:
        # Actual direction: target(t+1) > close(t)
        # Predicted direction: pred(t+1) > close(t)
        raw_close_test = df.loc[df.index[split_idx : split_idx + len(y_test)], 'Close'].values
        
        actual_up = y_test > raw_close_test
        predicted_up = y_pred > raw_close_test
        dir_accuracy = np.mean(actual_up == predicted_up) * 100
        
        metrics = {
            "mae": float(mae),
            "mape": float(mape),
            "r2": float(r2),
            "directional_accuracy": float(dir_accuracy),
            "train_samples": int(len(X_train)),
            "test_samples": int(len(X_test))
        }
        
        logger.info(f"Model Evaluation: MAE={mae:.4f}, MAPE={mape:.2f}%, DirAcc={dir_accuracy:.2f}%, R2={r2:.4f}")
        
        # Retrain on the entire dataset to maximize accuracy for the live prediction
        self.model.fit(X_scaled, y)
        
        return metrics

    def predict_next(self, df: pd.DataFrame) -> float:
        """
        Predicts the Close price at time t+1 using the latest row.
        Assumes the model is already trained.
        """
        X, y, X_latest = self.prepare_data(df)
        
        # Standardize the latest feature row using the fitted scaler
        X_latest_scaled = self.scaler.transform(X_latest)
        
        prediction = self.model.predict(X_latest_scaled)[0]
        return float(prediction)
