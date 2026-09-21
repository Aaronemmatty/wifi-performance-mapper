# Static Floor Plan & Grid Foundation

## 1. Overview & Architectural Role

Milestone 10 establishes the **static SVG floor-plan and grid representation** for the *Grid-Based Wi-Fi Performance Mapping and Monitoring System*.

This component provides the spatial coordinate foundation that connects:
1. Physical survey measurement locations in the field.
2. Canonical database records in PostgreSQL `(floor, x, y)`.
3. Future interactive web dashboard selection and heatmap visualization layers.

---

## 2. Why Static SVG?

The system uses a standalone **Scalable Vector Graphic (SVG)** (`frontend/floor1.svg`) for the floor plan and grid representation:

- **Vector Scalability**: Renders crisply across displays, resolutions, and zoom levels without raster pixelation or artifacting.
- **Native DOM Event Interactivity**: Every grid cell is an individual SVG `<rect>` element with unique IDs and data attributes. In subsequent milestones, vanilla JavaScript can directly attach event handlers (`click`, `mouseenter`, `mouseleave`) without requiring heavy canvas/WebGL or third-party mapping libraries.
- **Decoupled Static Asset**: Operates entirely as a static file. It does not depend on runtime database queries, server-side SVG generation, or external cloud map services.
- **CSS Styling & Heatmap Readiness**: Visual cell states (default, hovered, selected, surveyed, metric heat gradient) can be styled cleanly via standard CSS classes and inline SVG attributes.

---

## 3. Floor Plan Layout & Single-Floor Scope

### Single-Floor Constraint
The project scope is strictly focused on **one college floor plan** identified as:

```text
Floor-1
```

Multi-floor selection, floor switching, and 3D building modeling are intentionally excluded to keep the survey workflow robust, lightweight, and focused.

### Development / MVP Layout
The default floor plan (`frontend/floor1.svg`) represents a typical academic department floor layout (dimensions: `viewBox="0 0 1000 600"`, `1000px x 600px`):

```text
+-------------------------------------------------------------------------------+
|                             OUTER BUILDING WALL                               |
|  +------------------+  +-------------+  +------------------+  +------------+  |
|  |  Computer Lab A  |  | Server / NOC|  |  Computer Lab B  |  |  Faculty   |  |
|  |     (Rm 101)     |  |  (Rm 102)   |  |     (Rm 103)     |  |   Lounge   |  |
|  +------------------+  +-------------+  +------------------+  +------------+  |
|                                                                               |
|  ========================= MAIN CORRIDOR (FLOOR 1) =========================  |
|                                                                               |
|  +---------------------+  +-------------------------+  +-------------------+  |
|  |  Student Study Hall |  |   Lecture Auditorium    |  |  Admin & Offices  |  |
|  |      (Rm 105)       |  |        (Rm 106)         |  |     (Rm 107)      |  |
|  +---------------------+  +-------------------------+  +-------------------+  |
+-------------------------------------------------------------------------------+
```

> [!NOTE]
> The initial layout is a **development / dummy floor plan representation**. It provides realistic room zones and corridors for testing and validation. It can be replaced with an actual university blueprint in the future by updating SVG paths while preserving the coordinate grid contract.

---

## 4. Grid System & Coordinate Mapping Contract

### Grid Geometry
- **Columns ($x$)**: 10 columns (indexed $1.0$ through $10.0$)
- **Rows ($y$)**: 6 rows (indexed $1.0$ through $6.0$)
- **Total Survey Cells**: **60 cells** ($10 \times 6 = 60$)
- **SVG Cell Bounding Box**: $86\text{px (width)} \times 80\text{px (height)}$ per cell (with origin offset $x=70, y=55$).

### Cell Identifier Convention
Every grid cell follows a strict deterministic naming pattern:

$$\text{cell-r}\langle\text{row:02d}\rangle\text{-c}\langle\text{col:02d}\rangle$$

Examples:
- Top-left cell: `cell-r01-c01`
- Top-right cell: `cell-r01-c10`
- Center hallway cell: `cell-r03-c05`
- Bottom-right cell: `cell-r06-c10`

### Coordinate Mapping Table

| Cell ID | SVG Element | Floor Plan Key (`floor`) | Grid X (`x`) | Grid Y (`y`) | Survey Zone Description |
|---|---|---|---|---|---|
| `cell-r01-c01` | `<rect id="cell-r01-c01">` | `Floor-1` | `1.0` | `1.0` | Computer Lab A (Northwest) |
| `cell-r01-c02` | `<rect id="cell-r01-c02">` | `Floor-1` | `2.0` | `1.0` | Computer Lab A (North) |
| `cell-r01-c03` | `<rect id="cell-r01-c03">` | `Floor-1` | `3.0` | `1.0` | Computer Lab A (Northeast) |
| `cell-r01-c04` | `<rect id="cell-r01-c04">` | `Floor-1` | `4.0` | `1.0` | Server / NOC Room (North) |
| `cell-r01-c05` | `<rect id="cell-r01-c05">` | `Floor-1` | `5.0` | `1.0` | Server / NOC Room (North) |
| `cell-r01-c06` | `<rect id="cell-r01-c06">` | `Floor-1` | `6.0` | `1.0` | Computer Lab B (Northwest) |
| `cell-r01-c10` | `<rect id="cell-r01-c10">` | `Floor-1` | `10.0` | `1.0` | Faculty Lounge (Northeast) |
| `cell-r03-c01` | `<rect id="cell-r03-c01">` | `Floor-1` | `1.0` | `3.0` | West Corridor Access |
| `cell-r03-c05` | `<rect id="cell-r03-c05">` | `Floor-1` | `5.0` | `3.0` | Central Main Corridor |
| `cell-r06-c01` | `<rect id="cell-r06-c01">` | `Floor-1` | `1.0` | `6.0` | Student Study Hall (Southwest) |
| `cell-r06-c10` | `<rect id="cell-r06-c10">` | `Floor-1` | `10.0` | `6.0` | Admin Offices (Southeast) |

### Coordinate Units & Meaning
- **Grid Coordinates ($x, y$)**: Coordinates mapped to the database and API are **normalized discrete grid coordinate indices** ($x \in [1.0, 10.0]$, $y \in [1.0, 6.0]$).
- They represent discrete survey points on the floor grid.
- They are **not** raw SVG canvas pixel values (which are $70\text{px} \dots 930\text{px}$) and **not** unverified physical GPS/meter coordinates.
- This decoupling ensures that any front-end scaling, responsive resizing, or CAD asset replacement does not break historical database measurements.

---

## 5. SVG Element Attributes Specification

Each `<rect>` cell element in `frontend/floor1.svg` exposes the following standard attributes:

```xml
<rect
  id="cell-r01-c01"
  class="grid-cell"
  x="70"
  y="55"
  width="86"
  height="80"
  data-cell-id="cell-r01-c01"
  data-floor="Floor-1"
  data-row="1"
  data-col="1"
  data-x="1.0"
  data-y="1.0">
  <title>cell-r01-c01 (Floor-1, x=1.0, y=1.0)</title>
</rect>
```

- `id`: Stable CSS selector and DOM identifier (`cell-rXX-cYY`).
- `class`: `"grid-cell"` for universal styling and hover transition states.
- `data-cell-id`: Redundant string identifier for programmatic dataset access.
- `data-floor`: Consistent floor plan key (`Floor-1`).
- `data-row`: 1-indexed row number ($1 \dots 6$).
- `data-col`: 1-indexed column number ($1 \dots 10$).
- `data-x`: Float $x$ grid coordinate for database/API payloads (`1.0` $\dots$ `10.0`).
- `data-y`: Float $y$ grid coordinate for database/API payloads (`1.0` $\dots$ `6.0`).
- `<title>`: Native SVG tooltip element displaying cell identity and coordinates.

---

## 6. Python SVG & Grid Validation Module

The system includes a lightweight validator in [`backend/floor_grid.py`](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/floor_grid.py) using the Python standard library (`xml.etree.ElementTree`).

### Automated Invariants Checked:
1. **File Integrity**: File exists on disk and parses cleanly without XML syntax errors.
2. **Root Element**: Root is `<svg>` with positive `width`, `height`, and valid `viewBox`.
3. **Floor Identifier**: Root and all cells consistently declare `data-floor="Floor-1"`.
4. **Cell ID Uniqueness**: No duplicate cell IDs exist anywhere in the document.
5. **Coordinate Finiteness**: All `data-x` and `data-y` attributes parse to finite, positive numbers.
6. **Coordinate Bijectivity (1-to-1)**: No two different cells map to the exact same $(x, y)$ coordinate pair.
7. **Grid Structure**: Total parsed cells match expected grid dimensions ($10 \times 6 = 60$).

---

## 7. Blueprint Replacement Procedure

To replace the MVP floor plan with an actual university blueprint in the future:
1. Open or export the architectural blueprint as an SVG with `viewBox="0 0 1000 600"` (or adjust width/height proportionally).
2. Place architectural geometry in `<g id="architectural-layer">`.
3. Align the `<g id="grid-overlay">` rectangles over the walkable survey areas of the floor.
4. Keep the `id="cell-rXX-cYY"`, `data-floor="Floor-1"`, `data-x="..."`, and `data-y="..."` attributes on the grid cell `<rect>` elements.
5. Run `.venv\Scripts\pytest.exe tests/test_floor_grid.py` to confirm structural integrity.

No database migrations, API changes, or measurement service modifications are required when updating the floor plan visual graphics.
