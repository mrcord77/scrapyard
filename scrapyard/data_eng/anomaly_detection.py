"""
anomaly_detection — Statistical and ML anomaly detection over pandas DataFrames:
Z-score flagging for univariate/numeric data and Isolation Forest for multivariate data.

### PART-META-JSON
{
  "name": "anomaly_detection",
  "layer": "data_eng",
  "purpose": "Flags anomalous rows in numeric DataFrames: z_score_anomaly_detection adds z_score/is_anomaly columns using per-column Z-scores against a caller threshold (zero-variance columns handled safely), and isolation_forest adds anomaly_score/is_anomaly via scikit-learn's IsolationForest with fixed random_state for reproducibility.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pandas",
    "numpy",
    "scikit-learn (isolation_forest only)"
  ],
  "inputs": "pandas DataFrames with at least one numeric column; Z-score threshold (>0) or contamination fraction in (0, 0.5].",
  "outputs": "Copies of the input DataFrame with added z_score/anomaly_score and boolean is_anomaly columns.",
  "files_created": [],
  "security_notes": "Pure in-memory computation: no network, subprocess, file, or secret handling (the selftest writes only a throwaway SQLite log in a temp dir). Operationally, anomaly flags are statistical hints, not verdicts - do not gate security decisions (fraud blocks, account locks) on is_anomaly alone, and beware that an attacker who controls training-window data can shift the baseline (data poisoning) to hide outliers. Results on non-numeric columns are ignored, not errors.",
  "ai_usage": "z_score_anomaly_detection(df, threshold=3.0) for quick univariate screens; isolation_forest(df, contamination=0.1) for multivariate structure.",
  "example": "from scrapyard.data_eng.anomaly_detection import z_score_anomaly_detection",
  "import_path": "scrapyard.data_eng.anomaly_detection"
}
### END-PART-META
"""
from __future__ import annotations

import logging
import numbers
import os
import sqlite3
import tempfile
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

__all__ = [
    "z_score_anomaly_detection",
    "isolation_forest",
    "_selftest",
]

logger = logging.getLogger(__name__)


def z_score_anomaly_detection(data: pd.DataFrame, threshold: float = 3.0) -> pd.DataFrame:
    """
    Detect anomalies in a univariate or numeric DataFrame using Z-scores.

    Parameters
    ----------
    data:
        Input DataFrame containing numeric values.
    threshold:
        Z-score magnitude above which a row is flagged as an anomaly.

    Returns
    -------
    DataFrame with additional ``z_score`` and ``is_anomaly`` columns.
    """
    import numpy as np
    import pandas as pd

    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"data must be a pandas DataFrame, got {type(data).__name__}")
    if isinstance(threshold, bool) or not isinstance(threshold, numbers.Real):
        raise TypeError("threshold must be a real number")
    if threshold <= 0:
        raise ValueError("threshold must be a positive number")
    if data.empty:
        raise ValueError("data must not be empty")

    result = data.copy()
    numeric = result.select_dtypes(include=[np.number])

    if numeric.empty:
        raise ValueError("data must contain at least one numeric column")

    mean = numeric.mean()
    std = numeric.std(ddof=0)
    std_safe = std.replace(0, np.nan)

    z_scores = ((numeric - mean) / std_safe).fillna(0.0)

    result["z_score"] = z_scores.abs().max(axis=1)
    result["is_anomaly"] = result["z_score"] > threshold

    logger.debug("Z-score anomaly detection completed: %d anomalies", int(result["is_anomaly"].sum()))
    return result


def isolation_forest(data: pd.DataFrame, contamination: float = 0.1) -> pd.DataFrame:
    """
    Detect anomalies in multivariate numeric data using an Isolation Forest.

    Parameters
    ----------
    data:
        Input DataFrame containing numeric columns.
    contamination:
        Expected proportion of anomalies in the data (0, 0.5].

    Returns
    -------
    DataFrame with additional ``anomaly_score`` and ``is_anomaly`` columns.
    """
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import IsolationForest

    if not isinstance(data, pd.DataFrame):
        raise TypeError(f"data must be a pandas DataFrame, got {type(data).__name__}")
    if isinstance(contamination, bool) or not isinstance(contamination, numbers.Real):
        raise TypeError("contamination must be a real number")
    if not (0.0 < contamination <= 0.5):
        raise ValueError("contamination must be in the interval (0, 0.5]")
    if data.empty:
        raise ValueError("data must not be empty")

    numeric = data.select_dtypes(include=[np.number])

    if numeric.empty:
        raise ValueError("data must contain at least one numeric column")
    if len(numeric) < 2:
        raise ValueError("isolation forest requires at least two samples")

    model = IsolationForest(
        contamination=float(contamination),
        random_state=42,
        n_estimators=100,
    )
    predictions = model.fit_predict(numeric)
    scores = model.decision_function(numeric)

    result = data.copy()
    result["anomaly_score"] = scores
    result["is_anomaly"] = predictions == -1

    logger.debug("Isolation Forest completed: %d anomalies", int(result["is_anomaly"].sum()))
    return result


def _selftest() -> None:
    """
    Offline self-test for the anomaly detection module.

    Uses a temporary SQLite backend, synthetic data, and assertion checks.
    """
    import numpy as np
    import pandas as pd

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "anomaly_selftest.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS run_log (id INTEGER PRIMARY KEY, timestamp REAL)"
            )
            conn.execute("INSERT INTO run_log (timestamp) VALUES (?)", (time.time(),))
            conn.commit()
        finally:
            conn.close()

        rng = np.random.default_rng(42)

        # ---- Z-score test ----
        values = rng.normal(loc=10.0, scale=2.0, size=100)
        values[0] = 100.0  # clear univariate outlier

        df_univariate = pd.DataFrame({"value": values})
        z_result = z_score_anomaly_detection(df_univariate, threshold=3.0)

        assert isinstance(z_result, pd.DataFrame)
        assert "z_score" in z_result.columns
        assert "is_anomaly" in z_result.columns
        assert z_result["is_anomaly"].sum() >= 1, "Z-score should flag the injected outlier"

        # Invalid Z-score inputs
        try:
            z_score_anomaly_detection("not a dataframe")
            raise AssertionError("Expected TypeError for non-DataFrame input")
        except TypeError:
            pass

        try:
            z_score_anomaly_detection(df_univariate, threshold=-1.0)
            raise AssertionError("Expected ValueError for non-positive threshold")
        except ValueError:
            pass

        # ---- Isolation Forest test ----
        normal_data = rng.multivariate_normal(mean=[0.0, 0.0], cov=[[1.0, 0.0], [0.0, 1.0]], size=100)
        anomaly_data = rng.multivariate_normal(
            mean=[10.0, 10.0], cov=[[1.0, 0.0], [0.0, 1.0]], size=10
        )
        df_multivariate = pd.DataFrame(
            np.vstack([normal_data, anomaly_data]),
            columns=["x", "y"],
        )

        if_result = isolation_forest(df_multivariate, contamination=0.1)

        assert isinstance(if_result, pd.DataFrame)
        assert "anomaly_score" in if_result.columns
        assert "is_anomaly" in if_result.columns
        assert 0 < if_result["is_anomaly"].sum() <= 20, "Isolation Forest should flag some anomalies"

        # Invalid Isolation Forest inputs
        try:
            isolation_forest([1, 2, 3])
            raise AssertionError("Expected TypeError for non-DataFrame input")
        except TypeError:
            pass

        try:
            isolation_forest(df_multivariate, contamination=0.8)
            raise AssertionError("Expected ValueError for invalid contamination")
        except ValueError:
            pass

    logger.info("scrapyard.data_eng.anomaly_detection _selftest passed")


if __name__ == "__main__":
    _selftest()
