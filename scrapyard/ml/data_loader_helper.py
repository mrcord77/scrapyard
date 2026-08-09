"""
data_loader_helper — Provides reusable data loading and preprocessing utilities for neural network training and evaluation, with support for database-backed data sources and flexible preprocessing pipelines.

### PART-META-JSON
{
  "name": "data_loader_helper",
  "layer": "ml",
  "purpose": "Provides reusable data loading and preprocessing utilities for neural network training and evaluation, with support for database-backed data sources and flexible preprocessing pipelines.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: DataLoaderHelper(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Persists through SQLAlchemy with parameterized queries (no raw-SQL string interpolation); the composing app owns access control.",
  "ai_usage": "Import what you need from `scrapyard.ml.data_loader_helper`.",
  "example": "from scrapyard.ml.data_loader_helper import *",
  "import_path": "scrapyard.ml.data_loader_helper"
}
### END-PART-META
"""

import logging
import os
import tempfile
from typing import Dict, Tuple, Any

import pandas as pd
import numpy as np
from sqlalchemy import create_engine, select, Float, String
from sqlalchemy.orm import Session, declarative_base, Mapped, mapped_column
from sqlalchemy.sql import Select

logger = logging.getLogger(__name__)


class DataLoaderHelper:
    """Helper class for loading data from SQLAlchemy sources and preprocessing for ML pipelines."""
    
    def load_data(self, query: Select, session: Session) -> pd.DataFrame:
        """
        Execute SQLAlchemy query and return results as a pandas DataFrame.
        
        Args:
            query: SQLAlchemy Select statement
            session: SQLAlchemy Session instance
            
        Returns:
            DataFrame containing query results with appropriate column names
            
        Raises:
            ValueError: If query or session is None
            RuntimeError: If query execution fails
        """
        if query is None:
            raise ValueError("Query cannot be None")
        if session is None:
            raise ValueError("Session cannot be None")
        
        try:
            result = session.execute(query)
            rows = result.all()
            
            if not rows:
                return pd.DataFrame()
            
            columns = result.keys()
            data = [row._asdict() for row in rows]
            return pd.DataFrame(data, columns=columns)
            
        except Exception as e:
            raise RuntimeError(f"Failed to execute query: {e}") from e
    
    def preprocess_data(self, data: pd.DataFrame, config: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Preprocess DataFrame according to configuration specification.
        
        Args:
            data: Input pandas DataFrame
            config: Configuration dictionary with keys:
                - 'features': List[str] (required) - column names to use as features
                - 'target': str (optional) - column name to use as target
                - 'drop_na': bool (optional, default False) - whether to drop rows with NA
                - 'scale': str (optional) - 'standard' or 'minmax' or None
                
        Returns:
            Tuple of (X, y) where X is feature array of shape (n_samples, n_features)
            and y is target array of shape (n_samples, 1) if target specified,
            otherwise empty array.
            
        Raises:
            ValueError: If data is invalid or config missing required keys
            KeyError: If specified columns not found in DataFrame
        """
        if data is None:
            raise ValueError("Data cannot be None")
        if not isinstance(data, pd.DataFrame):
            raise ValueError("Data must be a pandas DataFrame")
        if not isinstance(config, dict):
            raise ValueError("Config must be a dictionary")
        
        if 'features' not in config:
            raise ValueError("Config must contain 'features' key")
        
        features = config['features']
        target = config.get('target')
        drop_na = config.get('drop_na', False)
        scale = config.get('scale')
        
        missing_features = [f for f in features if f not in data.columns]
        if missing_features:
            raise KeyError(f"Feature columns not found: {missing_features}")
        
        if target is not None and target not in data.columns:
            raise KeyError(f"Target column not found: {target}")
        
        df = data.copy()
        relevant_cols = list(features)
        if target is not None:
            relevant_cols.append(target)
        df = df[relevant_cols]
        
        if drop_na:
            df = df.dropna()
        
        if len(df) == 0:
            X = np.empty((0, len(features)), dtype=np.float32)
            y = np.empty((0, 1), dtype=np.float32) if target is not None else np.array([], dtype=np.float32)
            return X, y
        
        X = df[features].to_numpy(dtype=np.float32)
        
        if target is not None:
            y = df[target].to_numpy(dtype=np.float32).reshape(-1, 1)
        else:
            y = np.array([], dtype=np.float32)
        
        if scale == 'standard':
            means = np.mean(X, axis=0)
            stds = np.std(X, axis=0)
            stds[stds == 0] = 1.0
            X = (X - means) / stds
        elif scale == 'minmax':
            mins = np.min(X, axis=0)
            maxs = np.max(X, axis=0)
            ranges = maxs - mins
            ranges[ranges == 0] = 1.0
            X = (X - mins) / ranges
        elif scale is not None:
            raise ValueError(f"Unknown scaling method: {scale}")
        
        return X, y


def _selftest():
    """Offline self-test using temporary SQLite database."""
    from sqlalchemy.orm import sessionmaker
    
    Base = declarative_base()
    
    class TestRecord(Base):
        __tablename__ = "test_records"
        id: Mapped[int] = mapped_column(primary_key=True)
        feature_a: Mapped[float] = mapped_column(Float)
        feature_b: Mapped[float] = mapped_column(Float)
        target: Mapped[float] = mapped_column(Float)
        category: Mapped[str] = mapped_column(String(50))
    
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_engine(f"sqlite:///{db_path}")
        
        try:
            Base.metadata.create_all(engine)
            SessionFactory = sessionmaker(bind=engine)
            
            with SessionFactory() as session:
                for i in range(100):
                    session.add(TestRecord(
                        feature_a=float(i),
                        feature_b=float(i * 2),
                        target=float(i + 5),
                        category=f"cat_{i % 3}"
                    ))
                session.commit()
            
            helper = DataLoaderHelper()
            
            with SessionFactory() as session:
                query = select(TestRecord.feature_a, TestRecord.feature_b, TestRecord.target)
                df = helper.load_data(query, session)
                
                assert isinstance(df, pd.DataFrame)
                assert len(df) == 100
                assert list(df.columns) == ['feature_a', 'feature_b', 'target']
                
                empty_query = select(TestRecord).where(TestRecord.id > 1000)
                empty_df = helper.load_data(empty_query, session)
                assert isinstance(empty_df, pd.DataFrame) and len(empty_df) == 0
            
            config = {
                'features': ['feature_a', 'feature_b'],
                'target': 'target',
                'scale': 'standard'
            }
            X, y = helper.preprocess_data(df, config)
            
            assert isinstance(X, np.ndarray) and isinstance(y, np.ndarray)
            assert X.shape == (100, 2)
            assert y.shape == (100, 1)
            assert np.allclose(np.mean(X, axis=0), 0, atol=1e-6)
            assert np.allclose(np.std(X, axis=0), 1, atol=1e-6)
            
            config_no_target = {'features': ['feature_a', 'feature_b']}
            X_nt, y_nt = helper.preprocess_data(df, config_no_target)
            assert y_nt.size == 0
            
            config_minmax = {
                'features': ['feature_a', 'feature_b'],
                'target': 'target',
                'scale': 'minmax'
            }
            X_mm, _ = helper.preprocess_data(df, config_minmax)
            assert np.allclose(np.min(X_mm, axis=0), 0)
            assert np.allclose(np.max(X_mm, axis=0), 1)
            
            df_na = df.copy()
            df_na.loc[0, 'feature_a'] = np.nan
            config_drop = {
                'features': ['feature_a', 'feature_b'],
                'target': 'target',
                'drop_na': True
            }
            X_drop, y_drop = helper.preprocess_data(df_na, config_drop)
            assert X_drop.shape[0] == 99
            
            try:
                helper.load_data(None, session)
                assert False
            except ValueError:
                pass
            
            try:
                helper.load_data(query, None)
                assert False
            except ValueError:
                pass
            
            try:
                helper.preprocess_data(None, config)
                assert False
            except ValueError:
                pass
            
            try:
                helper.preprocess_data(df, {})
                assert False
            except ValueError:
                pass
            
            try:
                helper.preprocess_data(df, {'features': ['missing_col']})
                assert False
            except KeyError:
                pass
            
            try:
                helper.preprocess_data(df, {'features': ['feature_a'], 'scale': 'invalid'})
                assert False
            except ValueError:
                pass
            
            empty_df = pd.DataFrame(columns=['feature_a', 'feature_b', 'target'])
            X_empty, y_empty = helper.preprocess_data(empty_df, config)
            assert X_empty.shape == (0, 2)
            assert y_empty.shape == (0, 1)
            
        finally:
            engine.dispose()
    
    return True


if __name__ == "__main__":
    _selftest()
