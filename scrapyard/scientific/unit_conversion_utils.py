"""
unit_conversion_utils — Provides reusable unit conversion utilities for scientific computing, supporting temperature and pressure conversions with extensibility via a registry.

### PART-META-JSON
{
  "name": "unit_conversion_utils",
  "layer": "scientific",
  "purpose": "Provides reusable unit conversion utilities for scientific computing, supporting temperature and pressure conversions with extensibility via a registry.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: convert_temperature(value, from_unit, to_unit); convert_pressure(value, from_unit, to_unit); UnitConversionError(...).",
  "outputs": "Returns: convert_temperature -> float; convert_pressure -> float.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scientific.unit_conversion_utils`.",
  "example": "from scrapyard.scientific.unit_conversion_utils import *",
  "import_path": "scrapyard.scientific.unit_conversion_utils"
}
### END-PART-META
"""
from typing import Dict
import logging

logger = logging.getLogger(__name__)

# Temperature is affine, not a simple additive offset between every pair, so we
# canonicalize through Kelvin: each unit declares how to convert TO Kelvin and
# FROM Kelvin. This makes every C/F/K pair correct with one set of formulas.
TEMPERATURE_UNITS = ('Celsius', 'Fahrenheit', 'Kelvin')

_TO_KELVIN = {
    'Celsius': lambda c: c + 273.15,
    'Fahrenheit': lambda f: (f - 32.0) * 5.0 / 9.0 + 273.15,
    'Kelvin': lambda k: k,
}
_FROM_KELVIN = {
    'Celsius': lambda k: k - 273.15,
    'Fahrenheit': lambda k: (k - 273.15) * 9.0 / 5.0 + 32.0,
    'Kelvin': lambda k: k,
}

PRESSURE_CONVERSIONS: Dict[str, Dict[str, float]] = {
    'Pascal': {'Atmosphere': 9.86923e-6},
    'Atmosphere': {'Pascal': 101325}
}

class UnitConversionError(Exception):
    pass

def convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit not in _TO_KELVIN or to_unit not in _FROM_KELVIN:
        raise UnitConversionError(f"Invalid temperature units: {from_unit} to {to_unit}")

    return _FROM_KELVIN[to_unit](_TO_KELVIN[from_unit](value))

def convert_pressure(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit not in PRESSURE_CONVERSIONS or to_unit not in PRESSURE_CONVERSIONS[from_unit]:
        raise UnitConversionError(f"Invalid pressure units: {from_unit} to {to_unit}")
    
    return value * PRESSURE_CONVERSIONS[from_unit][to_unit]

def _approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol

def _selftest():
    # Known-good anchor points across all C/F/K pairs.
    # 0 C == 32 F == 273.15 K
    assert _approx(convert_temperature(0, 'Celsius', 'Fahrenheit'), 32.0), "0C -> F"
    assert _approx(convert_temperature(0, 'Celsius', 'Kelvin'), 273.15), "0C -> K"
    assert _approx(convert_temperature(32, 'Fahrenheit', 'Celsius'), 0.0), "32F -> C"
    assert _approx(convert_temperature(273.15, 'Kelvin', 'Celsius'), 0.0), "273.15K -> C"
    # 100 C == 212 F == 373.15 K
    assert _approx(convert_temperature(100, 'Celsius', 'Fahrenheit'), 212.0), "100C -> F"
    assert _approx(convert_temperature(100, 'Celsius', 'Kelvin'), 373.15), "100C -> K"
    assert _approx(convert_temperature(212, 'Fahrenheit', 'Kelvin'), 373.15), "212F -> K"
    assert _approx(convert_temperature(373.15, 'Kelvin', 'Fahrenheit'), 212.0), "373.15K -> F"
    # 25 C == 77 F (the exact case Codex reported broken)
    assert _approx(convert_temperature(25, 'Celsius', 'Fahrenheit'), 77.0), "25C -> F"
    assert _approx(convert_temperature(77, 'Fahrenheit', 'Celsius'), 25.0), "77F -> C"
    # Identity conversions
    assert _approx(convert_temperature(300, 'Kelvin', 'Kelvin'), 300.0), "K -> K identity"

    pressure_test = convert_pressure(101325, 'Pascal', 'Atmosphere')
    assert abs(pressure_test - 1.0) < 0.001, f"Pressure conversion failed: {pressure_test}"

    # Invalid units MUST raise; a silently-passing try/except would hide a broken
    # guard, so assert the exception actually fired via an else-branch flag.
    raised = False
    try:
        convert_temperature(25, 'Celsius', 'InvalidUnit')
    except UnitConversionError as e:
        raised = True
        assert str(e) == "Invalid temperature units: Celsius to InvalidUnit", f"msg mismatch: {e}"
    assert raised, "invalid temperature unit must raise UnitConversionError"

    raised = False
    try:
        convert_pressure(101325, 'Pascal', 'InvalidUnit')
    except UnitConversionError as e:
        raised = True
        assert str(e) == "Invalid pressure units: Pascal to InvalidUnit", f"msg mismatch: {e}"
    assert raised, "invalid pressure unit must raise UnitConversionError"

    print("unit_conversion_utils selftest passed")

if __name__ == "__main__":
    _selftest()
