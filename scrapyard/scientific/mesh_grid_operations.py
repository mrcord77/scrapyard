"""
mesh_grid_operations — ** The `scrapyard.scientific.mesh_grid_operations` module provides reusable functionality for manipulating mesh grids in scientific computing, supporting operations like slicing and merging. It is des

### PART-META-JSON
{
  "name": "mesh_grid_operations",
  "layer": "scientific",
  "purpose": "Provides reusable functionality for manipulating mesh grids in scientific computing, supporting operations like slicing and merging. It is des.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: slice_mesh(grid, slices); merge_meshes(grids).",
  "outputs": "Returns: slice_mesh -> np.ndarray; merge_meshes -> np.ndarray.",
  "files_created": [],
  "security_notes": "Pure computation: no network, filesystem, subprocess, secrets, or persistence; validate ranges/values at the call site as usual.",
  "ai_usage": "Import what you need from `scrapyard.scientific.mesh_grid_operations`.",
  "example": "from scrapyard.scientific.mesh_grid_operations import *",
  "import_path": "scrapyard.scientific.mesh_grid_operations"
}
### END-PART-META
"""
import numpy as np
from typing import List

def slice_mesh(grid: np.ndarray, slices: List[slice]) -> np.ndarray:
    """
    Slice a mesh grid along arbitrary axes with precision.
    
    Parameters:
        grid (np.ndarray): The input mesh grid to be sliced.
        slices (List[slice]): A list of slice objects specifying the slicing operation.

    Returns:
        np.ndarray: The sliced subgrid.
    """
    return grid[tuple(slices)]

def merge_meshes(grids: List[np.ndarray]) -> np.ndarray:
    """
    Merge multiple mesh grids into a unified structure.
    
    Parameters:
        grids (List[np.ndarray]): A list of mesh grids to be merged.

    Returns:
        np.ndarray: The combined mesh grid without overlap.
    """
    if not grids:
        raise ValueError("Grid list is empty")

    # Determine the shape and data type of the first grid
    base_shape = grids[0].shape
    dtype = grids[0].dtype

    for grid in grids[1:]:
        if grid.dtype != dtype or grid.shape != base_shape:
            raise ValueError("All grids must have the same shape and data type")

    # Concatenate along the first dimension (assuming 2D or 3D arrays)
    return np.concatenate(grids, axis=0)

def _selftest():
    """
    Self-test suite for validating the functionality of mesh_grid_operations.
    """
    import tempfile

    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    # Test data
    grid1 = np.array([[1, 2], [3, 4]])
    grid2 = np.array([[5, 6], [7, 8]])

    # Slice test
    sliced_grid = slice_mesh(grid1, [slice(None), slice(0, 1)])
    assert np.array_equal(sliced_grid, [[1], [3]])

    # Merge test
    merged_grid = merge_meshes([grid1, grid2])
    expected_merged_grid = np.array([[1, 2], [3, 4], [5, 6], [7, 8]])
    assert np.array_equal(merged_grid, expected_merged_grid)

    temp_dir.cleanup()

if __name__ == "__main__":
    _selftest()
