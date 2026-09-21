"""
backend/floor_grid.py
Floor Plan and Grid Representation Validation Module for Milestone 10.

Provides lightweight inspection, parsing, and validation of static SVG floor plans
and their associated grid cell coordinate systems using the Python standard library.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Union


DEFAULT_FLOOR_ID = "Floor-1"
DEFAULT_SVG_FILENAME = "floor1.svg"


@dataclass
class GridCellInfo:
    """Represents the parsed geometry and coordinate mapping of a single grid cell."""
    cell_id: str
    floor: str
    row: int
    col: int
    x: float
    y: float
    svg_x: float
    svg_y: float
    width: float
    height: float

    def to_measurement_location(self) -> Tuple[str, float, float]:
        """Returns the canonical (floor, x, y) tuple for backend measurement mapping."""
        return (self.floor, self.x, self.y)


@dataclass
class FloorPlanValidationResult:
    """Encapsulates the complete validation assessment of an SVG floor plan."""
    is_valid: bool
    floor: str
    total_cells: int
    cols: int
    rows: int
    viewbox: str
    width: float
    height: float
    errors: List[str] = field(default_factory=list)
    cells: List[GridCellInfo] = field(default_factory=list)

    @property
    def cell_ids(self) -> List[str]:
        return [c.cell_id for c in self.cells]

    @property
    def coordinate_map(self) -> Dict[str, Tuple[float, float]]:
        return {c.cell_id: (c.x, c.y) for c in self.cells}


def get_default_floor_plan_path() -> Path:
    """Returns the filesystem path to the default floor 1 SVG asset."""
    project_root = Path(__file__).resolve().parent.parent
    return project_root / "frontend" / DEFAULT_SVG_FILENAME


def validate_floor_plan_svg(svg_path: Optional[Union[str, Path]] = None) -> FloorPlanValidationResult:
    """
    Parse and validate a static SVG floor plan and grid representation.

    Validates:
    - SVG file existence and valid XML syntax
    - SVG root element attributes (viewBox, width, height, data-floor)
    - Consistency of the target floor identifier
    - Existence of grid cells with valid rectangular geometry
    - Strict uniqueness of cell identifiers (id / data-cell-id)
    - Presence of finite numerical coordinates (data-x, data-y)
    - Strict uniqueness of mapped (x, y) coordinates
    - Structural row and column consistency
    """
    path = Path(svg_path) if svg_path is not None else get_default_floor_plan_path()
    errors: List[str] = []

    if not path.is_file():
        return FloorPlanValidationResult(
            is_valid=False,
            floor="UNKNOWN",
            total_cells=0,
            cols=0,
            rows=0,
            viewbox="",
            width=0.0,
            height=0.0,
            errors=[f"SVG floor plan file not found at: {path}"],
            cells=[],
        )

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
    except ET.ParseError as e:
        return FloorPlanValidationResult(
            is_valid=False,
            floor="UNKNOWN",
            total_cells=0,
            cols=0,
            rows=0,
            viewbox="",
            width=0.0,
            height=0.0,
            errors=[f"Failed to parse SVG XML: {str(e)}"],
            cells=[],
        )

    # Strip XML namespace if present
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag.lower() != "svg":
        errors.append(f"Root XML element must be <svg>, got <{tag}>")

    viewbox = root.attrib.get("viewBox", "")
    if not viewbox:
        errors.append("SVG root element is missing 'viewBox' attribute")

    try:
        width = float(root.attrib.get("width", 0))
        height = float(root.attrib.get("height", 0))
        if width <= 0 or height <= 0:
            errors.append(f"SVG width and height must be positive numbers, got width={width}, height={height}")
    except (ValueError, TypeError):
        errors.append("SVG width and height must be valid numerical values")
        width, height = 0.0, 0.0

    floor = root.attrib.get("data-floor", DEFAULT_FLOOR_ID).strip()
    if not floor:
        errors.append("SVG root is missing a valid 'data-floor' attribute")
        floor = DEFAULT_FLOOR_ID

    # Find grid overlay group
    grid_group = None
    for elem in root.iter():
        elem_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if elem_tag == "g" and elem.attrib.get("id") == "grid-overlay":
            grid_group = elem
            break

    expected_cols = 0
    expected_rows = 0
    if grid_group is not None:
        try:
            expected_cols = int(grid_group.attrib.get("data-cols", 0))
            expected_rows = int(grid_group.attrib.get("data-rows", 0))
        except (ValueError, TypeError):
            errors.append("grid-overlay group has invalid data-cols or data-rows attributes")

    # Collect grid cells
    cell_elements = []
    search_context = grid_group if grid_group is not None else root
    for elem in search_context.iter():
        elem_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if elem_tag == "rect":
            elem_id = elem.attrib.get("id", "")
            elem_class = elem.attrib.get("class", "")
            if "grid-cell" in elem_class or elem_id.startswith("cell-"):
                cell_elements.append(elem)

    if not cell_elements:
        errors.append("No grid cell <rect> elements found with class 'grid-cell' or id 'cell-*'")

    seen_cell_ids: set[str] = set()
    seen_coords: set[Tuple[float, float]] = set()
    parsed_cells: List[GridCellInfo] = []

    for idx, cell_elem in enumerate(cell_elements, start=1):
        cell_id = cell_elem.attrib.get("id", "").strip()
        if not cell_id:
            errors.append(f"Cell #{idx} is missing a required 'id' attribute")
            continue

        if cell_id in seen_cell_ids:
            errors.append(f"Duplicate cell ID detected: '{cell_id}'")
        seen_cell_ids.add(cell_id)

        cell_floor = cell_elem.attrib.get("data-floor", floor).strip()
        if cell_floor != floor:
            errors.append(f"Cell '{cell_id}' floor '{cell_floor}' does not match root floor '{floor}'")

        # Parse coordinate mapping (x, y)
        raw_x = cell_elem.attrib.get("data-x")
        raw_y = cell_elem.attrib.get("data-y")
        if raw_x is None or raw_y is None:
            errors.append(f"Cell '{cell_id}' is missing required 'data-x' or 'data-y' coordinate attributes")
            continue

        try:
            coord_x = float(raw_x)
            coord_y = float(raw_y)
            if math.isnan(coord_x) or math.isinf(coord_x) or math.isnan(coord_y) or math.isinf(coord_y):
                errors.append(f"Cell '{cell_id}' contains non-finite coordinate values (x={coord_x}, y={coord_y})")
                continue
        except (ValueError, TypeError):
            errors.append(f"Cell '{cell_id}' contains non-numeric coordinates (data-x='{raw_x}', data-y='{raw_y}')")
            continue

        coord_tuple = (coord_x, coord_y)
        if coord_tuple in seen_coords:
            errors.append(f"Duplicate grid coordinate detected: (x={coord_x}, y={coord_y}) shared by multiple cells")
        seen_coords.add(coord_tuple)

        # Parse row/col attributes
        try:
            row_idx = int(cell_elem.attrib.get("data-row", 0))
            col_idx = int(cell_elem.attrib.get("data-col", 0))
        except (ValueError, TypeError):
            row_idx, col_idx = 0, 0

        # Parse SVG geometry
        try:
            svg_x = float(cell_elem.attrib.get("x", 0.0))
            svg_y = float(cell_elem.attrib.get("y", 0.0))
            svg_w = float(cell_elem.attrib.get("width", 0.0))
            svg_h = float(cell_elem.attrib.get("height", 0.0))
            if svg_w <= 0 or svg_h <= 0:
                errors.append(f"Cell '{cell_id}' has non-positive width or height ({svg_w}x{svg_h})")
        except (ValueError, TypeError):
            errors.append(f"Cell '{cell_id}' has invalid geometry attributes")
            svg_x, svg_y, svg_w, svg_h = 0.0, 0.0, 0.0, 0.0

        parsed_cells.append(
            GridCellInfo(
                cell_id=cell_id,
                floor=cell_floor,
                row=row_idx,
                col=col_idx,
                x=coord_x,
                y=coord_y,
                svg_x=svg_x,
                svg_y=svg_y,
                width=svg_w,
                height=svg_h,
            )
        )

    # Grid dimension sanity checks
    if expected_cols > 0 and expected_rows > 0:
        expected_total = expected_cols * expected_rows
        if len(parsed_cells) != expected_total:
            errors.append(
                f"Grid cell count ({len(parsed_cells)}) does not match expected grid dimensions "
                f"({expected_cols} cols x {expected_rows} rows = {expected_total} cells)"
            )

    is_valid = len(errors) == 0 and len(parsed_cells) > 0

    return FloorPlanValidationResult(
        is_valid=is_valid,
        floor=floor,
        total_cells=len(parsed_cells),
        cols=expected_cols,
        rows=expected_rows,
        viewbox=viewbox,
        width=width,
        height=height,
        errors=errors,
        cells=parsed_cells,
    )
