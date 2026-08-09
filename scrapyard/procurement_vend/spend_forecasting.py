"""
spend_forecasting - Maintain spend forecast models and generate horizon forecasts from historical data.

### PART-META-JSON
{
  "name": "spend_forecasting",
  "layer": "procurement_vend",
  "purpose": "Maintain spend forecast models and generate horizon forecasts from historical data.",
  "addition": false,
  "status": "core",
  "dependencies": [
    "sqlalchemy"
  ],
  "inputs": "update_forecast_model(model_id, new_data); generate_forecast(model_id, horizon).",
  "outputs": "ForecastModel and Forecast rows with projected spend per period.",
  "files_created": [],
  "security_notes": "Forecasts are advisory analytics, not commitments - never gate payments on them. Inputs are structured records; no code evaluation. Float math is acceptable here by design.",
  "ai_usage": "Import what you need from `scrapyard.procurement_vend.spend_forecasting`; run the module directly to execute its offline selftest.",
  "example": "from scrapyard.procurement_vend.spend_forecasting import update_forecast_model",
  "import_path": "scrapyard.procurement_vend.spend_forecasting"
}
### END-PART-META
"""

from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    JSON,
    select,
    ForeignKey,
    create_engine,
)
from sqlalchemy.orm import Mapped, mapped_column, Session
from scrapyard.database.base_model import IntPKModel
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import os
import re
import logging
import tempfile

logger = logging.getLogger(__name__)

_engine: Any = None


class Forecast(IntPKModel):
    __tablename__ = "forecasts"
    model_id: Mapped[int] = mapped_column(ForeignKey("forecast_models.id"), nullable=False)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)


class ForecastModel(IntPKModel):
    __tablename__ = "forecast_models"
    model_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


SUPPORTED_ALGORITHMS = {"naive", "moving_average", "linear_regression"}


def _session() -> Session:
    if _engine is not None:
        return Session(bind=_engine)
    return Session()


def _bump_version(version: str) -> str:
    match = re.search(r"(\d+)$", version)
    if match:
        prefix = version[: match.start()]
        number = int(match.group(1)) + 1
        return f"{prefix}{number}"
    return f"{version}_v2"


def _select_algorithm(amounts: List[float]) -> str:
    n = len(amounts)
    if n >= 14:
        return "linear_regression"
    if n >= 3:
        return "moving_average"
    return "naive"


def _train_parameters(algorithm: str, amounts: List[float]) -> Dict[str, Any]:
    if not amounts:
        return {"window_size": 0, "mean_amount": 0.0, "slope": 0.0}

    n = len(amounts)
    mean = sum(amounts) / n

    if algorithm == "linear_regression" and n >= 2:
        x_mean = (n - 1) / 2.0
        slope = sum((i - x_mean) * (a - mean) for i, a in enumerate(amounts)) / max(
            sum((i - x_mean) ** 2 for i in range(n)), 1e-9
        )
    else:
        slope = 0.0

    return {
        "window_size": n,
        "mean_amount": round(mean, 4),
        "slope": round(slope, 6),
    }


def update_forecast_model(model_id: int, new_data: List[Dict[str, Any]]) -> ForecastModel:
    """
    Retrain a forecast model using new order data and persist a versioned model.
    """
    if not isinstance(new_data, list):
        raise TypeError("new_data must be a list of dicts")

    with _session() as session:
        latest = session.execute(
            select(ForecastModel)
            .where(ForecastModel.model_id == model_id)
            .order_by(ForecastModel.trained_at.desc())
        ).scalar_one_or_none()

        version = _bump_version(latest.version) if latest else "v1"

        amounts: List[float] = []
        for entry in new_data:
            try:
                amounts.append(float(entry.get("amount", 0.0)))
            except (TypeError, ValueError):
                continue

        algorithm = _select_algorithm(amounts)
        parameters = _train_parameters(algorithm, amounts)
        parameters["updated_records"] = len(new_data)

        model = ForecastModel(
            model_id=model_id,
            algorithm=algorithm,
            parameters=parameters,
            version=version,
            trained_at=datetime.now(timezone.utc),
        )
        session.add(model)
        session.commit()
        session.refresh(model)
        logger.info(
            "Trained forecast model %s version %s using %s",
            model_id,
            version,
            algorithm,
        )
        return model


def generate_forecast(model_id: int, horizon: int) -> Forecast:
    """
    Generate a future spend forecast for a given model and horizon (days).
    """
    if horizon < 0:
        raise ValueError("horizon must be a non-negative integer")

    with _session() as session:
        model = session.execute(
            select(ForecastModel)
            .where(ForecastModel.model_id == model_id)
            .order_by(ForecastModel.trained_at.desc())
        ).scalar_one_or_none()

        if model is None:
            model = ForecastModel(
                model_id=model_id,
                algorithm="default",
                parameters={},
                version="v1",
                trained_at=datetime.now(timezone.utc),
            )
            session.add(model)
            session.commit()
            session.refresh(model)

        mean_amount = float(model.parameters.get("mean_amount", 0.0))
        slope = float(model.parameters.get("slope", 0.0))
        n_records = int(model.parameters.get("updated_records", 0))

        historical = session.execute(
            select(Forecast)
            .where(Forecast.model_id == model.id)
            .order_by(Forecast.date.desc())
            .limit(30)
        ).scalars().all()

        if historical:
            recent_amounts = [f.amount for f in historical[:7]]
            recent_avg = sum(recent_amounts) / len(recent_amounts)
            amount = (mean_amount + recent_avg) / 2.0
        else:
            amount = mean_amount

        amount += slope * horizon
        amount = max(amount, 0.0)

        confidence = min(0.5 + 0.02 * n_records + 0.01 * len(historical), 0.99)
        forecast_date = datetime.now(timezone.utc) + timedelta(days=horizon)

        forecast = Forecast(
            model_id=model.id,
            date=forecast_date,
            amount=round(amount, 2),
            confidence=round(confidence, 2),
        )
        session.add(forecast)
        session.commit()
        session.refresh(forecast)
        logger.info(
            "Generated forecast for model %s horizon %sd: amount=%s confidence=%s",
            model_id,
            horizon,
            forecast.amount,
            forecast.confidence,
        )
        return forecast


def _selftest() -> None:
    global _engine
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)
        _engine = engine
        try:
            IntPKModel.metadata.create_all(engine)

            historical = [
                {"date": "2023-10-01", "amount": 500.0, "confidence": 0.9},
                {"date": "2023-10-02", "amount": 600.0, "confidence": 0.85},
                {"date": "2023-10-03", "amount": 550.0, "confidence": 0.88},
            ]

            model = update_forecast_model(model_id=1, new_data=historical)
            assert isinstance(model, ForecastModel)
            assert model.model_id == 1
            assert model.version == "v1"
            assert model.algorithm in SUPPORTED_ALGORITHMS

            forecast = generate_forecast(model_id=1, horizon=7)
            assert isinstance(forecast, Forecast)
            assert forecast.amount >= 0.0
            assert 0.0 <= forecast.confidence <= 1.0

            forecast_date = forecast.date
            if forecast_date.tzinfo is None:
                forecast_date = forecast_date.replace(tzinfo=timezone.utc)
            assert forecast_date > datetime.now(timezone.utc)

            new_orders = [{"date": "2023-10-04", "amount": 700.0}]
            model2 = update_forecast_model(model_id=1, new_data=new_orders)
            assert isinstance(model2, ForecastModel)
            assert model2.version == "v2"

            with Session(bind=engine) as session:
                stored_forecasts = session.execute(select(Forecast)).scalars().all()
                stored_models = session.execute(select(ForecastModel)).scalars().all()

            assert len(stored_forecasts) >= 1
            assert len(stored_models) == 2
            logger.info("spend_forecasting _selftest passed")
        finally:
            _engine = None
            engine.dispose()


if __name__ == "__main__":
    _selftest()
