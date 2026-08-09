"""
data_augmentation_pipeline — Apply data augmentation techniques to datasets in a modular and reusable way, enabling consistent preprocessing across ML projects.

### PART-META-JSON
{
  "name": "data_augmentation_pipeline",
  "layer": "ml",
  "purpose": "Apply data augmentation techniques to datasets in a modular and reusable way, enabling consistent preprocessing across ML projects.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: apply_augmentations(dataset, pipeline); make_gaussian_noise_step(columns, sigma, seed); make_oversample_step(label_column, seed); make_column_flip_step(columns); AugmentationPipeline(...).",
  "outputs": "Returns: apply_augmentations -> pd.DataFrame; make_gaussian_noise_step -> Callable; make_oversample_step -> Callable; make_column_flip_step -> Callable.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.ml.data_augmentation_pipeline`.",
  "example": "from scrapyard.ml.data_augmentation_pipeline import *",
  "import_path": "scrapyard.ml.data_augmentation_pipeline"
}
### END-PART-META
"""

from typing import Optional, List, Callable
import pandas as pd
import logging
from dataclasses import dataclass, field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class AugmentationPipeline:
    steps: List[Callable] = field(default_factory=list)

def apply_augmentations(dataset: pd.DataFrame, pipeline: AugmentationPipeline) -> pd.DataFrame:
    """
    Apply a series of data augmentation functions to the dataset.

    :param dataset: A pandas DataFrame containing the input data.
    :param pipeline: An instance of AugmentationPipeline with defined augmentation steps.
    :return: The transformed dataset as a pandas DataFrame.
    """
    for step in pipeline.steps:
        try:
            dataset = step(dataset)
        except Exception as e:
            logger.error(f"Failed to apply augmentation step: {e}")
            raise
    return dataset

# --- Reusable, REAL augmentation steps ------------------------------------

def make_gaussian_noise_step(columns: List[str], sigma: float = 0.01,
                             seed: int = 0) -> Callable:
    """Return a step adding deterministic Gaussian noise to numeric columns."""
    import numpy as np

    def add_noise(df: pd.DataFrame) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        out = df.copy()
        for col in columns:
            out[col] = out[col] + rng.normal(0.0, sigma, size=len(out))
        return out
    return add_noise


def make_oversample_step(label_column: str, seed: int = 0) -> Callable:
    """Return a step that oversamples minority classes to balance the label
    column (random duplication, deterministic)."""
    def oversample(df: pd.DataFrame) -> pd.DataFrame:
        counts = df[label_column].value_counts()
        max_count = counts.max()
        parts = [df]
        for label, count in counts.items():
            if count < max_count:
                extra = df[df[label_column] == label].sample(
                    n=max_count - count, replace=True, random_state=seed)
                parts.append(extra)
        return pd.concat(parts, ignore_index=True)
    return oversample


def make_column_flip_step(columns: List[str]) -> Callable:
    """Return a step that sign-flips numeric columns (a 1-D 'mirror')."""
    def flip(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in columns:
            out[col] = -out[col]
        return out
    return flip


# Self-test function
def _selftest():
    import pandas as pd

    df = pd.DataFrame({
        'x': [1.0, 2.0, 3.0, 4.0],
        'y': [0.5, -0.5, 1.5, -1.5],
        'label': [0, 0, 0, 1],
    })

    # Real steps: noise + flip, composed through the pipeline
    pipeline = AugmentationPipeline(steps=[
        make_gaussian_noise_step(['x'], sigma=0.01, seed=42),
        make_column_flip_step(['y']),
    ])
    out = apply_augmentations(df, pipeline)

    assert list(out.columns) == ['x', 'y', 'label']
    # noise actually changed x (but only slightly), flip actually negated y
    assert not out['x'].equals(df['x'])
    assert (out['x'] - df['x']).abs().max() < 0.1
    assert (out['y'] == -df['y']).all()
    # input not mutated
    assert df['y'].tolist() == [0.5, -0.5, 1.5, -1.5]

    # oversampling balances the label column
    balanced = apply_augmentations(
        df, AugmentationPipeline(steps=[make_oversample_step('label', seed=1)]))
    counts = balanced['label'].value_counts()
    assert counts[0] == counts[1] == 3

    # a failing step propagates (with logging), not silently swallowed
    def broken(_df):
        raise RuntimeError("bad step")

    try:
        apply_augmentations(df, AugmentationPipeline(steps=[broken]))
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass

    # empty pipeline is a no-op
    same = apply_augmentations(df, AugmentationPipeline())
    assert same.equals(df)

    logger.info("Self-test passed: Augmentations applied successfully.")
    print("data_augmentation_pipeline selftest passed")

if __name__ == "__main__":
    _selftest()
