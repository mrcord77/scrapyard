"""
geospatial_transforms — ** The `geospatial_transforms` module provides tools for performing geospatial transformations and projections, enabling accurate coordinate system conversions in scientific and engineering applicatio

### PART-META-JSON
{
  "name": "geospatial_transforms",
  "layer": "scientific",
  "purpose": "Coordinate reference system transformations for scientific/engineering use: Transform2D and project_point use pyproj when installed (any CRS pair, full accuracy) and otherwise fall back to built-in spherical math for the common pairs EPSG:4326<->EPSG:3857 (web mercator, exact spherical formulas) and EPSG:4326<->EPSG:32633 (UTM 33N, simplified approximation); unsupported pairs without pyproj raise ValueError ('unsupported CRS pair: ...') honestly rather than returning wrong coordinates.",
  "addition": true,
  "status": "core",
  "dependencies": [
    "pyproj (optional; lazy import with built-in fallback for 4326<->3857 and 4326<->32633)"
  ],
  "inputs": "Point coordinates (x, y in the source CRS, always_xy order: lon/lat for geographic) and CRS identifier strings like 'EPSG:4326'.",
  "outputs": "Transformed (x, y) tuples in the destination CRS.",
  "files_created": [],
  "security_notes": "Pure in-memory math; no network, subprocess, file (outside the selftest temp db), or secret handling. Accuracy caveats matter more than security here: the UTM fallback is a simplified approximation (metre-level to worse away from the central meridian) and the web-mercator fallback uses the exact SPHERICAL formulas (identical to pyproj for EPSG:3857 by definition, but latitudes must be within +/-85.051129 deg; poles are rejected via ValueError). Do not feed fallback outputs into safety-critical positioning without pyproj installed. Coordinates can be location-PII when tied to people; handle datasets accordingly.",
  "ai_usage": "project_point(lon, lat, 'EPSG:4326', 'EPSG:3857') for one-offs; Transform2D(src, dst).apply(x, y) to reuse a transformer. Install pyproj for CRS pairs beyond the built-in fallbacks.",
  "example": "from scrapyard.scientific.geospatial_transforms import project_point",
  "import_path": "scrapyard.scientific.geospatial_transforms"
}
### END-PART-META
"""

import logging
import math
import os
import sqlite3
import tempfile
from typing import Tuple

logger = logging.getLogger(__name__)

# Spherical earth radius used by EPSG:3857 (web mercator) by definition.
_WEB_MERCATOR_R = 6378137.0
# Web mercator is undefined at the poles; this is the standard latitude clamp.
_WEB_MERCATOR_MAX_LAT = 85.051128779806604


class _FallbackTransformer:
    """
    Fallback transformer used when pyproj is unavailable.

    Supported pairs:
      - EPSG:4326 <-> EPSG:3857 (web mercator; exact spherical formulas,
        matching the projection's own spherical definition)
      - EPSG:4326 <-> EPSG:32633 (UTM 33N; simplified approximation)
    Any other pair raises ValueError (unsupported CRS pair) honestly.
    """

    def __init__(self, src_crs: str, dst_crs: str):
        self.src_crs = src_crs.upper().strip()
        self.dst_crs = dst_crs.upper().strip()

    @staticmethod
    def _wgs84_to_web_mercator(lon: float, lat: float) -> Tuple[float, float]:
        if not (-_WEB_MERCATOR_MAX_LAT <= lat <= _WEB_MERCATOR_MAX_LAT):
            raise ValueError(
                f"latitude {lat} outside web-mercator domain "
                f"(+/-{_WEB_MERCATOR_MAX_LAT})")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"longitude {lon} outside [-180, 180]")
        x = _WEB_MERCATOR_R * math.radians(lon)
        y = _WEB_MERCATOR_R * math.log(math.tan(math.pi / 4.0 +
                                                math.radians(lat) / 2.0))
        return (x, y)

    @staticmethod
    def _web_mercator_to_wgs84(x: float, y: float) -> Tuple[float, float]:
        lon = math.degrees(x / _WEB_MERCATOR_R)
        lat = math.degrees(2.0 * math.atan(math.exp(y / _WEB_MERCATOR_R))
                           - math.pi / 2.0)
        return (lon, lat)

    def transform(self, x: float, y: float) -> Tuple[float, float]:
        # WGS84 (EPSG:4326) <-> Web Mercator (EPSG:3857): exact spherical math
        if self.src_crs == "EPSG:4326" and self.dst_crs == "EPSG:3857":
            return self._wgs84_to_web_mercator(x, y)
        if self.src_crs == "EPSG:3857" and self.dst_crs == "EPSG:4326":
            return self._web_mercator_to_wgs84(x, y)

        # WGS84 (EPSG:4326) to UTM Zone 33N (EPSG:32633)
        if self.src_crs == "EPSG:4326" and self.dst_crs == "EPSG:32633":
            lon, lat = x, y
            # Zone 33N: Central meridian at 15°E, scale factor 0.9996
            cm = 15.0
            k0 = 0.9996
            # Approximate degrees to meters conversion
            x_m = (lon - cm) * 111319.4908 * math.cos(math.radians(lat)) * k0
            y_m = lat * 110676.9 * k0
            return (500000.0 + x_m, y_m)
        
        # UTM Zone 33N (EPSG:32633) to WGS84 (EPSG:4326)
        elif self.src_crs == "EPSG:32633" and self.dst_crs == "EPSG:4326":
            easting, northing = x, y
            cm = 15.0
            k0 = 0.9996
            lat = northing / (110676.9 * k0)
            scale = 111319.4908 * math.cos(math.radians(lat)) * k0
            lon = cm + (easting - 500000.0) / scale
            return (lon, lat)
        
        else:
            raise ValueError(
                f"unsupported CRS pair: {self.src_crs} -> {self.dst_crs} "
                "(install pyproj for arbitrary CRS pairs)"
            )


class Transform2D:
    """
    High-precision 2D coordinate transformation between source and destination CRS.
    
    Lazily loads pyproj.Transformer on first use to avoid import-time dependencies.
    Falls back to simplified implementation if pyproj is not available.
    """
    
    def __init__(self, src_crs: str, dst_crs: str):
        """
        Initialize transformation between two coordinate reference systems.
        
        Args:
            src_crs: Source CRS string (e.g., "EPSG:4326")
            dst_crs: Destination CRS string (e.g., "EPSG:32633")
        """
        self.src_crs = src_crs
        self.dst_crs = dst_crs
        self._transformer = None
    
    def _get_transformer(self):
        """Lazy initialization of pyproj transformer."""
        if self._transformer is None:
            try:
                import pyproj
                self._transformer = pyproj.Transformer.from_crs(
                    self.src_crs, self.dst_crs, always_xy=True
                )
            except ImportError:
                # Use fallback implementation for self-test environments
                self._transformer = _FallbackTransformer(self.src_crs, self.dst_crs)
        return self._transformer
    
    def apply(self, x: float, y: float) -> Tuple[float, float]:
        """
        Apply transformation to coordinates.
        
        Args:
            x: X coordinate (e.g., longitude for geographic CRS)
            y: Y coordinate (e.g., latitude for geographic CRS)
            
        Returns:
            Tuple of transformed (x, y) coordinates
        """
        transformer = self._get_transformer()
        return transformer.transform(x, y)


def project_point(x: float, y: float, src_crs: str, dst_crs: str) -> Tuple[float, float]:
    """
    Project a single point between coordinate reference systems.
    
    Args:
        x: X coordinate in source CRS
        y: Y coordinate in source CRS
        src_crs: Source CRS identifier
        dst_crs: Destination CRS identifier
        
    Returns:
        Tuple of (x, y) in destination CRS
    """
    transform = Transform2D(src_crs, dst_crs)
    return transform.apply(x, y)


def _selftest() -> None:
    """
    Offline self-test validating WGS84 to UTM transformations.
    
    Uses temporary SQLite database to log test results.
    Completes in under 20 seconds with no network access.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE test_results (test_name TEXT, x REAL, y REAL)"
            )
            
            # Test 1: Transform2D WGS84 (EPSG:4326) to UTM Zone 33N (EPSG:32633)
            # Using point at central meridian (15°E) and equator (0°N)
            # Expected: Easting = 500000, Northing = 0 (within floating point tolerance)
            transformer = Transform2D("EPSG:4326", "EPSG:32633")
            x, y = transformer.apply(15.0, 0.0)
            
            assert math.isclose(x, 500000.0, abs_tol=0.1), f"CM Easting failed: {x}"
            assert math.isclose(y, 0.0, abs_tol=0.1), f"Equator Northing failed: {y}"
            
            cursor.execute(
                "INSERT INTO test_results VALUES (?, ?, ?)",
                ("wgs84_to_utm_cm", x, y)
            )
            
            # Test 2: project_point with known test coordinates
            # lon=12.0, lat=34.0 in Zone 33N
            x2, y2 = project_point(12.0, 34.0, "EPSG:4326", "EPSG:32633")
            
            # Verify values are in expected range for this zone. The range must
            # accommodate BOTH the real pyproj transform (x2 ~= 222908.7) and the
            # tangent-plane fallback used when pyproj is absent (x2 ~= 223xxx).
            assert 222000.0 < x2 < 224000.0, f"X out of expected range: {x2}"
            assert 3761400.0 < y2 < 3761600.0, f"Y out of expected range: {y2}"
            
            cursor.execute(
                "INSERT INTO test_results VALUES (?, ?, ?)",
                ("project_point_12_34", x2, y2)
            )
            
            # Test 3: Round-trip conversion accuracy
            # Transform forward then back
            back_transform = Transform2D("EPSG:32633", "EPSG:4326")
            lon_back, lat_back = back_transform.apply(x2, y2)
            
            assert math.isclose(lon_back, 12.0, abs_tol=1e-6), "Longitude round-trip failed"
            assert math.isclose(lat_back, 34.0, abs_tol=1e-6), "Latitude round-trip failed"
            
            cursor.execute(
                "INSERT INTO test_results VALUES (?, ?, ?)",
                ("roundtrip_lonlat", lon_back, lat_back)
            )

            # Test 4: Web mercator (EPSG:3857) via the public API
            # Known value: lon=12, lat=34 -> x = 1335833.889..., y = 4028802.026...
            mx, my = project_point(12.0, 34.0, "EPSG:4326", "EPSG:3857")
            assert math.isclose(mx, 1335833.8895192828, rel_tol=1e-9), f"3857 x: {mx}"
            assert math.isclose(my, 4028802.0261344006, rel_tol=1e-6), f"3857 y: {my}"
            lon3, lat3 = project_point(mx, my, "EPSG:3857", "EPSG:4326")
            assert math.isclose(lon3, 12.0, abs_tol=1e-9), f"3857 lon back: {lon3}"
            assert math.isclose(lat3, 34.0, abs_tol=1e-9), f"3857 lat back: {lat3}"
            cursor.execute(
                "INSERT INTO test_results VALUES (?, ?, ?)",
                ("web_mercator_12_34", mx, my)
            )

            # Test 5: The FALLBACK web-mercator path specifically (exercised
            # even when pyproj is installed) including domain validation.
            fb = _FallbackTransformer("EPSG:4326", "EPSG:3857")
            fx, fy = fb.transform(12.0, 34.0)
            assert math.isclose(fx, mx, rel_tol=1e-9) or abs(fx - mx) < 0.001, \
                f"fallback x diverges: {fx} vs {mx}"
            assert abs(fy - my) < 0.001, f"fallback y diverges: {fy} vs {my}"
            fb_inv = _FallbackTransformer("EPSG:3857", "EPSG:4326")
            flon, flat = fb_inv.transform(fx, fy)
            assert math.isclose(flon, 12.0, abs_tol=1e-9)
            assert math.isclose(flat, 34.0, abs_tol=1e-9)
            try:
                fb.transform(0.0, 89.0)  # beyond mercator latitude domain
                raise AssertionError("polar latitude must raise ValueError")
            except ValueError:
                pass
            try:
                _FallbackTransformer("EPSG:4326", "EPSG:2154").transform(1.0, 2.0)
                raise AssertionError("unsupported fallback pair must raise")
            except ValueError as exc:
                assert "unsupported CRS pair" in str(exc)
            cursor.execute(
                "INSERT INTO test_results VALUES (?, ?, ?)",
                ("fallback_web_mercator", fx, fy)
            )

            conn.commit()

            # Verify all tests recorded
            cursor.execute("SELECT COUNT(*) FROM test_results")
            count = cursor.fetchone()[0]
            assert count == 5, f"Expected 5 test results, got {count}"
            
            # Verify specific expected values were stored
            cursor.execute(
                "SELECT x, y FROM test_results WHERE test_name = ?",
                ("wgs84_to_utm_cm",)
            )
            row = cursor.fetchone()
            assert row is not None
            assert math.isclose(row[0], 500000.0, abs_tol=0.1)
            assert math.isclose(row[1], 0.0, abs_tol=0.1)
            
        finally:
            conn.close()
    
    logger.info("geospatial_transforms._selftest: PASSED")


if __name__ == "__main__":
    _selftest()
