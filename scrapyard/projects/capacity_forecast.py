"""
capacity_forecast — Forecast future capacity needs based on historical data and trends. Provides a reusable forecasting model for resource scheduling scenarios.

### PART-META-JSON
{
  "name": "capacity_forecast",
  "layer": "projects",
  "purpose": "Forecast future capacity needs based on historical data and trends. Provides a reusable forecasting model for resource scheduling scenarios.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "scrapyard.database.base_model",
    "scrapyard.utils.time_utils"
  ],
  "inputs": "Public API: generate_forecast(data, horizon); update_forecast(model, new_data); capacity_forecasts(...); ForecastModel(...).",
  "outputs": "Returns: generate_forecast -> pd.DataFrame; update_forecast -> None.",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.projects.capacity_forecast`.",
  "example": "from scrapyard.projects.capacity_forecast import *",
  "import_path": "scrapyard.projects.capacity_forecast"
}
### END-PART-META
"""

import logging
import os
import tempfile
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, Date, Float, select
from sqlalchemy.orm import Session, Mapped, mapped_column

from scrapyard.database.base_model import IntPKModel

logger = logging.getLogger(__name__)


class capacity_forecasts(IntPKModel):
    __tablename__ = "capacity_forecasts"
    
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    predicted_capacity: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_interval_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_interval_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class ForecastModel:
    """Linear trend forecasting model for capacity planning."""
    
    def __init__(self) -> None:
        self.slope: float = 0.0
        self.intercept: float = 0.0
        self.is_trained: bool = False
        self.ref_date: Optional[datetime] = None
        self.last_date: Optional[datetime] = None
        self.data_mean: float = 0.0
        self.data_std: float = 0.0
    
    def fit(self, data: pd.DataFrame) -> None:
        """Train the model on historical data with 'date' and 'capacity' columns."""
        if data.empty:
            raise ValueError("Training data cannot be empty")
        
        if 'date' not in data.columns or 'capacity' not in data.columns:
            raise ValueError("Data must contain 'date' and 'capacity' columns")
        
        df = data.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        self.ref_date = df['date'].min()
        self.last_date = df['date'].max()
        
        days = (df['date'] - self.ref_date).dt.days.values
        capacity = df['capacity'].values
        
        n = len(days)
        if n == 0:
            self.slope = 0.0
            self.intercept = 0.0
            self.data_mean = 0.0
            self.data_std = 0.0
        elif n == 1:
            self.slope = 0.0
            self.intercept = float(capacity[0])
            self.data_mean = float(capacity[0])
            self.data_std = 0.0
        else:
            x_mean = days.mean()
            y_mean = capacity.mean()
            
            numerator = ((days - x_mean) * (capacity - y_mean)).sum()
            denominator = ((days - x_mean) ** 2).sum()
            
            if abs(denominator) < 1e-10:
                self.slope = 0.0
            else:
                self.slope = numerator / denominator
            
            self.intercept = y_mean - self.slope * x_mean
            self.data_mean = float(y_mean)
            self.data_std = float(np.std(capacity))
        
        self.is_trained = True
        logger.debug(f"Model trained: slope={self.slope:.4f}, intercept={self.intercept:.4f}")
    
    def predict(self, horizon: int) -> pd.DataFrame:
        """Generate predictions for the next 'horizon' days."""
        if not self.is_trained:
            raise RuntimeError("Model must be trained before prediction")
        
        if self.ref_date is None or self.last_date is None:
            raise RuntimeError("Model dates not initialized")
        
        results: List[Dict[str, Any]] = []
        last_day_idx = (self.last_date - self.ref_date).days
        
        for i in range(1, horizon + 1):
            future_day_idx = last_day_idx + i
            pred_value = self.intercept + self.slope * future_day_idx
            
            ci_margin = 1.96 * self.data_std * (1.0 + i * 0.02)
            
            future_date = self.last_date + timedelta(days=i)
            
            results.append({
                'forecast_date': future_date.date(),
                'predicted_capacity': float(pred_value),
                'confidence_interval_low': float(pred_value - ci_margin),
                'confidence_interval_high': float(pred_value + ci_margin)
            })
        
        return pd.DataFrame(results)


def generate_forecast(data: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Generate a forecast for the given horizon using the provided data."""
    model = ForecastModel()
    model.fit(data)
    return model.predict(horizon)


def update_forecast(model: ForecastModel, new_data: pd.DataFrame) -> None:
    """Update the forecast model by retraining with new data."""
    logger.info("Updating forecast model with new data")
    model.fit(new_data)


def _selftest() -> None:
    """Execute offline self-test using temporary SQLite database."""
    logger.info("Starting capacity_forecast self-test")
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test_forecast.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        IntPKModel.metadata.create_all(engine)
        
        try:
            base_date = datetime.now()
            dates = [base_date - timedelta(days=30-i) for i in range(30)]
            capacities = [100 + i*2.5 + (i % 5) for i in range(30)]
            
            historical_data = pd.DataFrame({
                'date': dates,
                'capacity': capacities
            })
            
            model = ForecastModel()
            model.fit(historical_data)
            assert model.is_trained, "Model should be marked as trained"
            assert model.slope > 0, "Should detect positive trend"
            logger.info("✓ ForecastModel initialized and trained")
            
            horizon = 7
            forecast_df = generate_forecast(historical_data, horizon)
            assert isinstance(forecast_df, pd.DataFrame), "Must return DataFrame"
            assert forecast_df.shape[0] == horizon, f"Must have {horizon} rows"
            assert list(forecast_df.columns) == [
                'forecast_date', 'predicted_capacity', 
                'confidence_interval_low', 'confidence_interval_high'
            ]
            logger.info("✓ generate_forecast returns valid DataFrame")
            
            new_dates = [base_date - timedelta(days=3-i) for i in range(3)]
            new_capacities = [180.0, 182.0, 184.0]
            new_data = pd.DataFrame({'date': new_dates, 'capacity': new_capacities})
            
            update_forecast(model, new_data)
            assert model.is_trained, "Model should still be trained after update"
            logger.info("✓ update_forecast modifies existing forecast")
            
            with Session(engine) as session:
                for _, row in forecast_df.iterrows():
                    record = capacity_forecasts(
                        forecast_date=row['forecast_date'],
                        predicted_capacity=row['predicted_capacity'],
                        confidence_interval_low=row['confidence_interval_low'],
                        confidence_interval_high=row['confidence_interval_high']
                    )
                    session.add(record)
                session.commit()
                
                stmt = select(capacity_forecasts)
                records = session.execute(stmt).scalars().all()
                assert len(records) == horizon, f"Should have {horizon} records in DB"
                
                for rec in records:
                    assert isinstance(rec.forecast_date, date)
                    assert isinstance(rec.predicted_capacity, (int, float))
                    assert rec.confidence_interval_low is None or isinstance(rec.confidence_interval_low, (int, float))
                
                logger.info("✓ capacity_forecasts table populated correctly")
                
        finally:
            engine.dispose()
    
    logger.info("Self-test completed successfully")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _selftest()
