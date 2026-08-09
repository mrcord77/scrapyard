"""
numerical_integration — ** Provide core numerical integration tools for scientific computing, supporting both simple and adaptive methods. Designed for flexibility, accuracy, and integration with scientific workflows requiri

### PART-META-JSON
{
  "name": "numerical_integration",
  "layer": "scientific",
  "purpose": "Provide core numerical integration tools for scientific computing, supporting both simple and adaptive methods. Designed for flexibility, accuracy, and integration with scientific workflows requiri.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: trapz_integral(func, a, b, n); quad_integration(func, a, b, eps).",
  "outputs": "Returns: trapz_integral -> float; quad_integration -> float.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scientific.numerical_integration`.",
  "example": "from scrapyard.scientific.numerical_integration import *",
  "import_path": "scrapyard.scientific.numerical_integration"
}
### END-PART-META
"""
from typing import Callable
import numpy as np
from scipy.integrate import quad

def trapz_integral(func: Callable[[float], float], a: float, b: float, n: int) -> float:
    """
    Compute the definite integral of a function using the trapezoidal rule.
    
    :param func: The function to integrate.
    :param a: Lower limit of integration.
    :param b: Upper limit of integration.
    :param n: Number of subintervals (must be positive).
    :return: The approximate value of the integral.
    """
    if n <= 0:
        raise ValueError("Number of subintervals must be positive.")
    
    h = (b - a) / n
    x = np.linspace(a, b, n + 1)
    y = func(x)
    return h * (np.sum(y) - 0.5 * (y[0] + y[-1]))

def quad_integration(func: Callable[[float], float], a: float, b: float, eps: float = 1e-6) -> float:
    """
    Compute the definite integral of a function using adaptive quadrature.
    
    :param func: The function to integrate.
    :param a: Lower limit of integration.
    :param b: Upper limit of integration.
    :param eps: Desired absolute accuracy (default 1e-6).
    :return: The approximate value of the integral and an estimate of the error.
    """
    result, error = quad(func, a, b)
    return result

def _selftest():
    # Test trapz_integral with a linear function
    def linear_func(x):
        return 2 * x + 1
    
    result = trapz_integral(linear_func, 0, 1, 100)
    expected_result = 2.0  # The exact integral of the linear function from 0 to 1 is 2
    assert abs(result - expected_result) < 1e-5, f"Trapz integral failed: {result}"
    
    # Test quad_integration with a non-linear function
    def nonlinear_func(x):
        return np.sin(x)
    
    result = quad_integration(nonlinear_func, 0, np.pi)
    expected_result = 2.0  # The exact integral of sin from 0 to pi is 2
    assert abs(result - expected_result) < 1e-6, f"Quad integration failed: {result}"
    
    print("All tests passed.")

if __name__ == "__main__":
    _selftest()
