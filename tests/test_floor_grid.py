"""
tests/test_floor_grid.py
Floor Plan and Grid Representation Unit Tests for Milestone 10.

Verifies:
1. Static SVG floor plan asset existence on disk.
2. SVG XML parseability and structure.
3. Strict grid cell ID uniqueness.
4. Numerical coordinate presence and finiteness.
5. Coordinate uniqueness (bijective 1-to-1 mapping with physical grid cells).
6. Single-floor consistency (Floor-1).
7. Grid geometry and dimensions (10 cols x 6 rows = 60 cells).
8. Validation error handling for invalid/corrupted SVG assets.
"""

import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from backend.floor_grid import (
    DEFAULT_FLOOR_ID,
    DEFAULT_SVG_FILENAME,
    GridCellInfo,
    FloorPlanValidationResult,
    get_default_floor_plan_path,
    validate_floor_plan_svg,
)


# ----------------------------------------------------------------------
# 1. Floor Plan Asset Existence & Basic Parsing Tests
# ----------------------------------------------------------------------

def test_default_floor_plan_svg_exists():
    """Verify that frontend/floor1.svg exists on disk and is non-empty."""
    path = get_default_floor_plan_path()
    assert path.is_file(), f"Expected floor plan SVG file at {path}"
    assert path.stat().st_size > 500, "Floor plan SVG file appears unexpectedly small or empty"


def test_default_floor_plan_svg_valid_xml():
    """Verify that floor1.svg parses cleanly as valid XML without syntax errors."""
    path = get_default_floor_plan_path()
    tree = ET.parse(str(path))
    root = tree.getroot()
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    assert tag.lower() == "svg"
    assert "viewBox" in root.attrib
    assert root.attrib["viewBox"] == "0 0 1000 600"


# ----------------------------------------------------------------------
# 2. Comprehensive Grid Validation Tests
# ----------------------------------------------------------------------

def test_validate_default_floor_plan_success():
    """
    Run the complete validator against the default frontend/floor1.svg:
    - Must be valid with 0 errors
    - Floor must be 'Floor-1'
    - Total cells must be exactly 60 (10 cols x 6 rows)
    - ViewBox must be 0 0 1000 600
    """
    result = validate_floor_plan_svg()
    assert result.is_valid is True, f"Validation failed with errors: {result.errors}"
    assert result.errors == []
    assert result.floor == DEFAULT_FLOOR_ID
    assert result.total_cells == 60
    assert result.cols == 10
    assert result.rows == 6
    assert result.width == 1000.0
    assert result.height == 600.0


def test_grid_cell_ids_unique_and_non_empty():
    """Verify that all 60 cell IDs are non-empty and strictly unique."""
    result = validate_floor_plan_svg()
    assert result.is_valid is True
    cell_ids = result.cell_ids
    assert len(cell_ids) == 60
    assert len(set(cell_ids)) == 60, "Duplicate cell IDs detected in floor plan!"

    # Verify ID convention format cell-rXX-cYY
    for cid in cell_ids:
        assert cid.startswith("cell-r"), f"Invalid cell ID prefix: {cid}"
        assert "-c" in cid, f"Missing column indicator in cell ID: {cid}"


def test_grid_cell_coordinates_valid_and_finite():
    """Verify that every cell exposes finite positive (x, y) coordinates."""
    result = validate_floor_plan_svg()
    assert result.is_valid is True

    for cell in result.cells:
        assert isinstance(cell.x, float)
        assert isinstance(cell.y, float)
        assert 1.0 <= cell.x <= 10.0, f"Cell {cell.cell_id} X coordinate out of bounds: {cell.x}"
        assert 1.0 <= cell.y <= 6.0, f"Cell {cell.cell_id} Y coordinate out of bounds: {cell.y}"
        assert 1 <= cell.col <= 10
        assert 1 <= cell.row <= 6
        assert cell.width > 0
        assert cell.height > 0


def test_grid_coordinates_strictly_unique_no_overlap():
    """
    Verify coordinate uniqueness:
    No two distinct cells map to the same (x, y) coordinate pair.
    """
    result = validate_floor_plan_svg()
    assert result.is_valid is True

    coord_map = result.coordinate_map
    assert len(coord_map) == 60
    coords_list = list(coord_map.values())
    assert len(set(coords_list)) == 60, "Duplicate coordinate pairs detected in grid!"


def test_single_floor_consistency():
    """Verify that all 60 cells consistently map to Floor-1."""
    result = validate_floor_plan_svg()
    assert result.is_valid is True
    assert result.floor == "Floor-1"

    for cell in result.cells:
        assert cell.floor == "Floor-1", f"Cell {cell.cell_id} has mismatched floor: {cell.floor}"
        location_tuple = cell.to_measurement_location()
        assert location_tuple[0] == "Floor-1"
        assert location_tuple[1] == cell.x
        assert location_tuple[2] == cell.y


# ----------------------------------------------------------------------
# 3. Validator Error Detection Tests
# ----------------------------------------------------------------------

def test_validate_missing_file_returns_error():
    """Verify validator handles non-existent file cleanly."""
    result = validate_floor_plan_svg("frontend/non_existent_floor.svg")
    assert result.is_valid is False
    assert len(result.errors) > 0
    assert "not found" in result.errors[0].lower()


def test_validate_corrupted_xml_returns_error():
    """Verify validator handles corrupted/malformed XML cleanly."""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8") as f:
        f.write("<svg><rect>unclosed tag")
        temp_path = Path(f.name)

    try:
        result = validate_floor_plan_svg(temp_path)
        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "failed to parse" in result.errors[0].lower()
    finally:
        temp_path.unlink(missing_ok=True)


def test_validate_duplicate_cell_id_detected():
    """Verify validator detects duplicate cell IDs in an SVG."""
    bad_svg = """<svg viewBox="0 0 1000 600" width="1000" height="600" data-floor="Floor-1">
      <g id="grid-overlay" data-cols="2" data-rows="1">
        <rect id="cell-01" class="grid-cell" x="10" y="10" width="50" height="50" data-floor="Floor-1" data-x="1.0" data-y="1.0" />
        <rect id="cell-01" class="grid-cell" x="70" y="10" width="50" height="50" data-floor="Floor-1" data-x="2.0" data-y="1.0" />
      </g>
    </svg>"""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8") as f:
        f.write(bad_svg)
        temp_path = Path(f.name)

    try:
        result = validate_floor_plan_svg(temp_path)
        assert result.is_valid is False
        assert any("duplicate cell id" in err.lower() for err in result.errors)
    finally:
        temp_path.unlink(missing_ok=True)


def test_validate_duplicate_coordinate_detected():
    """Verify validator detects two distinct cells sharing identical (x, y) coordinates."""
    bad_svg = """<svg viewBox="0 0 1000 600" width="1000" height="600" data-floor="Floor-1">
      <g id="grid-overlay" data-cols="2" data-rows="1">
        <rect id="cell-01" class="grid-cell" x="10" y="10" width="50" height="50" data-floor="Floor-1" data-x="1.0" data-y="1.0" />
        <rect id="cell-02" class="grid-cell" x="70" y="10" width="50" height="50" data-floor="Floor-1" data-x="1.0" data-y="1.0" />
      </g>
    </svg>"""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8") as f:
        f.write(bad_svg)
        temp_path = Path(f.name)

    try:
        result = validate_floor_plan_svg(temp_path)
        assert result.is_valid is False
        assert any("duplicate grid coordinate" in err.lower() for err in result.errors)
    finally:
        temp_path.unlink(missing_ok=True)


def test_validate_mismatched_floor_detected():
    """Verify validator detects cells with a floor different from root floor."""
    bad_svg = """<svg viewBox="0 0 1000 600" width="1000" height="600" data-floor="Floor-1">
      <g id="grid-overlay" data-cols="1" data-rows="1">
        <rect id="cell-01" class="grid-cell" x="10" y="10" width="50" height="50" data-floor="Floor-2" data-x="1.0" data-y="1.0" />
      </g>
    </svg>"""
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8") as f:
        f.write(bad_svg)
        temp_path = Path(f.name)

    try:
        result = validate_floor_plan_svg(temp_path)
        assert result.is_valid is False
        assert any("mismatched" in err.lower() or "does not match" in err.lower() for err in result.errors)
    finally:
        temp_path.unlink(missing_ok=True)
