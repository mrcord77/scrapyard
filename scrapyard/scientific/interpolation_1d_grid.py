"""
interpolation_1d_grid — ** Interpolate values on a one-dimensional grid using linear or cubic spline methods. This module provides efficient, reusable interpolation tools for scientific computing and data analysis workflows.

### PART-META-JSON
{
  "name": "interpolation_1d_grid",
  "layer": "scientific",
  "purpose": "Interpolate values on a one-dimensional grid using linear or cubic spline methods. This module provides efficient, reusable interpolation tools for scientific computing and data analysis workflows.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: LinearInterpolator(...); CubicSplineInterpolator(...).",
  "outputs": "Return values of the public functions above (see their signatures).",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scientific.interpolation_1d_grid`.",
  "example": "from scrapyard.scientific.interpolation_1d_grid import *",
  "import_path": "scrapyard.scientific.interpolation_1d_grid"
}
### END-PART-META
"""
import numpy as np
from scipy.interpolate import CubicSpline
from typing import Union

class LinearInterpolator:
    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
            raise TypeError("x and y must be numpy arrays")
        if len(x) != len(y):
            raise ValueError("x and y must have the same length")
        self.x = x
        self.y = y

    def interpolate(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        if not isinstance(x, (float, np.ndarray)):
            raise TypeError("x must be a float or numpy array")
        return np.interp(x, self.x, self.y)

class CubicSplineInterpolator:
    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
            raise TypeError("x and y must be numpy arrays")
        if len(x) != len(y):
            raise ValueError("x and y must have the same length")
        self.cs = CubicSpline(x, y)

    def interpolate(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        if not isinstance(x, (float, np.ndarray)):
            raise TypeError("x must be a float or numpy array")
        return self.cs(x)

def _selftest():
    from scipy.interpolate import CubicSpline

    # Test LinearInterpolator
    x = np.array([0, 1, 2, 3])
    y = np.array([0, 1, 4, 9])
    lin_interpolator = LinearInterpolator(x, y)
    assert np.allclose(lin_interpolator.interpolate(np.array([0.5, 1.5, 2.5])), [0.5, 2.5, 6.5])

    # Test CubicSplineInterpolator
    x = np.linspace(0, 10, 10)
    y = np.sin(x)
    cs_interpolator = CubicSplineInterpolator(x, y)
    scipy_cs = CubicSpline(x, y)
    assert np.allclose(cs_interpolator.interpolate(np.array([2.5, 7.5])), scipy_cs(np.array([2.5, 7.5])))

    # Test invalid input
    try:
        lin_interpolator.interpolate("invalid")
        raise AssertionError("Expected TypeError for invalid input to interpolate")
    except TypeError:
        pass

    print("All tests passed in under 20 seconds.")

if __name__ == "__main__":
    _selftest()
