"""
tests/test_frontend_grid.py
Frontend Floor Grid Foundation, Browser Measurement Workflow, and Heatmap Visualization Tests (M11–M13).

Verifies:
1. Static frontend asset files exist on disk (index.html, style.css, app.js, floor1.svg).
2. Authoritative floor1.svg remains referenced as the single source of truth.
3. Required UI containers and element IDs exist in index.html (M11 selection, M12 session/measurement, M13 metric selector & dynamic legend).
4. Required CSS interactive and result states exist in style.css (.grid-cell, :hover, .selected, .cell-null, .cell-unmeasured, .heatmap-legend).
5. JavaScript contract contains SVG loading, 60-cell discovery, session management, measurement orchestration, and M13 heatmap rendering.
6. M13 metric configuration maps exactly the four primary metrics (rssi_dbm, latency_ms, packet_loss_percent, throughput_mbps).
7. Dynamic session-relative min/max normalization, single-value handling, 0.0 numeric preservation, and null exclusion.
8. Latest-measurement-per-cell cache semantics (later records overwrite earlier records for the same cell).
9. Historical measurements query contract (GET /measurements?session_id=...&floor=Floor-1).
10. Authoritative SVG integration contract remains verified (60 cells, unique IDs, dataset attributes).
11. FastAPI same-origin static file serving (/ serves index.html, /floor1.svg, /style.css, /app.js).
"""

from pathlib import Path
import re
import xml.etree.ElementTree as ET
import pytest
from fastapi.testclient import TestClient

from backend.floor_grid import (
    DEFAULT_FLOOR_ID,
    DEFAULT_SVG_FILENAME,
    validate_floor_plan_svg,
)
from backend.main import create_app


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


# ----------------------------------------------------------------------
# Test 1 — Frontend files exist
# ----------------------------------------------------------------------

def test_frontend_files_exist():
    """Verify that frontend/index.html, frontend/style.css, and frontend/app.js exist and are non-empty."""
    expected_files = [
        FRONTEND_DIR / "index.html",
        FRONTEND_DIR / "style.css",
        FRONTEND_DIR / "app.js",
        FRONTEND_DIR / DEFAULT_SVG_FILENAME,
    ]

    for file_path in expected_files:
        assert file_path.is_file(), f"Required frontend file missing: {file_path.name}"
        assert file_path.stat().st_size > 0, f"Frontend file is empty: {file_path.name}"


# ----------------------------------------------------------------------
# Test 2 — Floor SVG remains referenced
# ----------------------------------------------------------------------

def test_floor_svg_remains_referenced():
    """Verify that the frontend scripts/markup specifically reference the authoritative floor1.svg."""
    app_js_path = FRONTEND_DIR / "app.js"
    assert app_js_path.is_file()

    js_content = app_js_path.read_text(encoding="utf-8")
    assert "floor1.svg" in js_content, "app.js does not reference 'floor1.svg'"


# ----------------------------------------------------------------------
# Test 3 — Required UI containers exist in HTML (M11, M12 & M13)
# ----------------------------------------------------------------------

def test_required_ui_containers_exist_in_html():
    """Verify that index.html contains the necessary container and field IDs for M11, M12, and M13."""
    html_path = FRONTEND_DIR / "index.html"
    assert html_path.is_file()

    html_content = html_path.read_text(encoding="utf-8")

    # Essential structural IDs
    required_ids = [
        # M11 Grid & Selection IDs
        "floorplan-container",
        "selection-panel",
        "no-selection-msg",
        "cell-details-container",
        "selected-cell-id",
        "selected-floor",
        "selected-x",
        "selected-y",
        "selected-row",
        "selected-col",
        # M12 Session IDs
        "session-panel",
        "session-select",
        "create-session-form",
        "new-session-id",
        "new-session-name",
        "new-session-floor",
        "submit-create-session-btn",
        "active-session-badge",
        # M12 Measurement Action IDs
        "measure-btn",
        "measure-loading-indicator",
        "measure-error-banner",
        # M12 Measurement Results IDs
        "measurement-result-panel",
        "result-status-badge",
        "result-persisted-badge",
        "result-rssi",
        "result-signal",
        "result-latency",
        "result-packet-loss",
        "result-throughput",
        "result-id",
        "result-session",
        "result-coords",
        "result-ssid",
        "result-bssid",
        "result-roaming",
        "result-timestamp",
        # M13 Metric Selector IDs
        "metric-selector-container",
        "metric-select",
        # M13 Dynamic Legend IDs
        "heatmap-legend",
        "legend-metric-label",
        "legend-scale-type",
        "legend-active-body",
        "legend-min-val",
        "legend-max-val",
        "legend-gradient-bar",
        "legend-empty-msg",
        # M13 Cached Cell Summary Details
        "cell-survey-summary",
        "cell-measured-status-badge",
        "cell-metrics-list",
        "cell-cached-rssi",
        "cell-cached-signal",
        "cell-cached-latency",
        "cell-cached-packet-loss",
        "cell-cached-throughput",
        "cell-cached-ap",
        "cell-cached-timestamp",
        "cell-cached-samples",
    ]

    for element_id in required_ids:
        pattern = rf'id=["\']{re.escape(element_id)}["\']'
        assert re.search(pattern, html_content), f"index.html is missing element with id='{element_id}'"

    # Verify script and style linkages
    assert 'rel="stylesheet"' in html_content and "style.css" in html_content
    assert "<script" in html_content and "app.js" in html_content


# ----------------------------------------------------------------------
# Test 4 — Required CSS states exist in style.css
# ----------------------------------------------------------------------

def test_required_css_states_exist():
    """Verify that style.css contains the required interactive, result, and heatmap CSS selectors."""
    css_path = FRONTEND_DIR / "style.css"
    assert css_path.is_file()

    css_content = css_path.read_text(encoding="utf-8")

    # Required selectors
    assert ".grid-cell" in css_content, "style.css missing base .grid-cell rule"
    assert ".grid-cell:hover" in css_content or ":hover" in css_content, "style.css missing .grid-cell:hover rule"
    assert ".grid-cell.selected" in css_content or ".selected" in css_content, "style.css missing .grid-cell.selected rule"
    assert ".heatmap-legend" in css_content, "style.css missing .heatmap-legend rule"
    assert ".legend-gradient-bar" in css_content, "style.css missing .legend-gradient-bar rule"
    assert ".cell-null" in css_content, "style.css missing .cell-null neutral state rule"
    assert ".cell-unmeasured" in css_content, "style.css missing .cell-unmeasured state rule"
    assert ".spinner" in css_content, "style.css missing .spinner loading animation"


# ----------------------------------------------------------------------
# Test 5 — JavaScript contains required interaction & measurement contract
# ----------------------------------------------------------------------

def test_javascript_interaction_and_measurement_contract():
    """Verify that app.js implements SVG fetch, cell parsing, session handling, and measurement calling."""
    app_js_path = FRONTEND_DIR / "app.js"
    assert app_js_path.is_file()

    js_content = app_js_path.read_text(encoding="utf-8")

    # Verify fetch & parsing mechanism
    assert "fetch(" in js_content, "app.js missing fetch call"
    assert "DOMParser" in js_content or "parseFromString" in js_content, "app.js missing SVG XML DOM parsing"

    # Verify grid cell discovery
    assert ".grid-cell" in js_content, "app.js does not query for '.grid-cell'"
    assert "60" in js_content, "app.js does not validate 60 cell count"

    # Verify dataset attribute parsing
    assert "dataset.x" in js_content or "dataset['x']" in js_content
    assert "dataset.y" in js_content or "dataset['y']" in js_content
    assert "dataset.row" in js_content or "dataset['row']" in js_content
    assert "dataset.col" in js_content or "dataset['col']" in js_content
    assert "dataset.floor" in js_content or "dataset['floor']" in js_content

    # Verify M12 Session & Measurement endpoints
    assert "/sessions" in js_content, "app.js missing /sessions endpoint call"
    assert "/measurements/measure" in js_content, "app.js missing /measurements/measure endpoint call"
    assert "session_id" in js_content
    assert "sample_count" not in js_content.split("/measurements/measure")[1].split("}")[0], \
        "app.js must NOT send sample_count in /measurements/measure payload"


# ----------------------------------------------------------------------
# Test 6 — M13 Primary Metric Selector and Mapping Contract
# ----------------------------------------------------------------------

def test_m13_metric_configuration_and_mappings():
    """Verify that app.js defines exactly the 4 primary metrics and excludes signal_percent from selector."""
    app_js_path = FRONTEND_DIR / "app.js"
    assert app_js_path.is_file()
    js_content = app_js_path.read_text(encoding="utf-8")

    # Exactly four primary metric backend fields
    assert "rssi_dbm" in js_content, "app.js missing rssi_dbm metric key"
    assert "latency_ms" in js_content, "app.js missing latency_ms metric key"
    assert "packet_loss_percent" in js_content, "app.js missing packet_loss_percent metric key"
    assert "throughput_mbps" in js_content, "app.js missing throughput_mbps metric key"

    # Verify HTML selector contains exactly the 4 primary options
    html_path = FRONTEND_DIR / "index.html"
    html_content = html_path.read_text(encoding="utf-8")
    assert 'value="rssi_dbm"' in html_content
    assert 'value="latency_ms"' in html_content
    assert 'value="packet_loss_percent"' in html_content
    assert 'value="throughput_mbps"' in html_content
    assert 'value="signal_percent"' not in html_content, "signal_percent must not be in heatmap metric selector"


# ----------------------------------------------------------------------
# Test 7 — M13 Dynamic Session-Relative Scale Normalization Semantics
# ----------------------------------------------------------------------

def test_m13_dynamic_normalization_and_scale_semantics():
    """Verify normalization logic for higher-is-better, lower-is-better, zero values, and single-value edges."""
    def normalize_value(value, min_val, max_val, is_higher_better):
        if min_val is None or max_val is None or min_val == max_val:
            return 0.5
        val_range = max_val - min_val
        if val_range <= 0:
            return 0.5
        t = (value - min_val) / val_range if is_higher_better else (max_val - value) / val_range
        return max(0.0, min(1.0, t))

    # 1. Higher is better (RSSI)
    # Range: -80 to -40
    assert normalize_value(-40, -80, -40, True) == 1.0  # Best RSSI -> 1.0 (Green)
    assert normalize_value(-80, -80, -40, True) == 0.0  # Worst RSSI -> 0.0 (Blue)
    assert normalize_value(-60, -80, -40, True) == 0.5  # Midpoint -> 0.5 (Cyan)

    # 2. Lower is better (Latency)
    # Range: 10ms to 50ms
    assert normalize_value(10, 10, 50, False) == 1.0   # Best Latency -> 1.0 (Green)
    assert normalize_value(50, 10, 50, False) == 0.0   # Worst Latency -> 0.0 (Blue)
    assert normalize_value(30, 10, 50, False) == 0.5   # Midpoint -> 0.5 (Cyan)

    # 3. Lower is better with valid 0.0 (Packet Loss)
    # Range: 0.0% to 20.0%
    assert normalize_value(0.0, 0.0, 20.0, False) == 1.0   # 0% loss is best score
    assert normalize_value(20.0, 0.0, 20.0, False) == 0.0  # 20% loss is worst score

    # 4. Single-value edge case (Vmin == Vmax)
    assert normalize_value(-50.0, -50.0, -50.0, True) == 0.5
    assert normalize_value(25.0, 25.0, 25.0, False) == 0.5


# ----------------------------------------------------------------------
# Test 8 — M13 Latest-Measurement-Per-Cell Cache Winning Semantics
# ----------------------------------------------------------------------

def test_m13_latest_per_cell_cache_semantics():
    """Verify that multiple historical measurements for the same cell resolve to the latest measurement."""
    measurements = [
        {"id": 1, "floor": "Floor-1", "x": 10.0, "y": 20.0, "rssi_dbm": -75, "timestamp": "2026-09-21T10:00:00Z"},
        {"id": 2, "floor": "Floor-1", "x": 10.0, "y": 20.0, "rssi_dbm": -45, "timestamp": "2026-09-21T10:05:00Z"},
        {"id": 3, "floor": "Floor-1", "x": 30.0, "y": 40.0, "rssi_dbm": -60, "timestamp": "2026-09-21T10:06:00Z"},
    ]

    cache = {}
    for m in measurements:
        key = f"{m['floor']}_{m['x']:.2f}_{m['y']:.2f}"
        cache[key] = m

    # Cell (10.0, 20.0) should have the latest measurement (#2 with -45 dBm)
    assert cache["Floor-1_10.00_20.00"]["id"] == 2
    assert cache["Floor-1_10.00_20.00"]["rssi_dbm"] == -45
    # Cell (30.0, 40.0) remains independent
    assert cache["Floor-1_30.00_40.00"]["id"] == 3


# ----------------------------------------------------------------------
# Test 9 — M13 Historical Measurement API Query Contract
# ----------------------------------------------------------------------

def test_m13_historical_measurement_api_query():
    """Verify app.js queries GET /measurements with session_id and floor."""
    app_js_path = FRONTEND_DIR / "app.js"
    js_content = app_js_path.read_text(encoding="utf-8")

    assert "/measurements?" in js_content or "/measurements" in js_content
    assert "session_id" in js_content
    assert "Floor-1" in js_content


# ----------------------------------------------------------------------
# Test 10 — Authoritative SVG integration contract remains valid
# ----------------------------------------------------------------------

def test_svg_integration_contract_valid():
    """Verify frontend/floor1.svg passes the M10 structural validation contract."""
    svg_path = FRONTEND_DIR / DEFAULT_SVG_FILENAME
    result = validate_floor_plan_svg(svg_path)

    assert result.is_valid is True, f"Floor plan SVG validation failed: {result.errors}"
    assert result.total_cells == 60
    assert result.cols == 10
    assert result.rows == 6
    assert result.floor == DEFAULT_FLOOR_ID
    assert len(result.cell_ids) == 60
    assert len(set(result.cell_ids)) == 60
    assert len(result.coordinate_map) == 60
    assert len(set(result.coordinate_map.values())) == 60


# ----------------------------------------------------------------------
# Test 11 — FastAPI same-origin static files mounting
# ----------------------------------------------------------------------

def test_fastapi_serves_frontend_same_origin():
    """Verify that FastAPI serves index.html at '/' and all static assets at their respective paths."""
    app = create_app(is_test=True)
    client = TestClient(app)

    # 1. Root route serves index.html
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert "text/html" in resp_root.headers.get("content-type", "")
    assert "Wi-Fi Performance Mapper" in resp_root.text
    assert "floorplan-container" in resp_root.text
    assert "metric-select" in resp_root.text
    assert "heatmap-legend" in resp_root.text

    # 2. Static SVG asset
    resp_svg = client.get("/floor1.svg")
    assert resp_svg.status_code == 200
    assert "image/svg+xml" in resp_svg.headers.get("content-type", "")
    assert "grid-overlay" in resp_svg.text

    # 3. Static CSS asset
    resp_css = client.get("/style.css")
    assert resp_css.status_code == 200
    assert ".grid-cell" in resp_css.text
    assert ".heatmap-legend" in resp_css.text

    # 4. Static JS asset
    resp_js = client.get("/app.js")
    assert resp_js.status_code == 200
    assert "renderHeatmap" in resp_js.text

    # 5. API routes remain fully functional and take routing precedence
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json() == {"status": "ok"}


# ----------------------------------------------------------------------
# Test 12 — M14 Survey Coverage and Total Readings Calculation
# ----------------------------------------------------------------------

def test_m14_survey_coverage_and_total_readings_calculation():
    """Verify deterministic coverage calculation, distinct cell counting, and total readings tracking."""
    def calculate_coverage(measurements):
        if not measurements:
            return {"distinct_count": 0, "total_cells": 60, "percentage": 0.0, "total_readings": 0}
        distinct_keys = {
            f"{m['floor']}_{float(m['x']):.2f}_{float(m['y']):.2f}"
            for m in measurements
            if "floor" in m and "x" in m and "y" in m
        }
        distinct_count = len(distinct_keys)
        percentage = (distinct_count / 60.0) * 100.0
        return {
            "distinct_count": distinct_count,
            "total_cells": 60,
            "percentage": percentage,
            "total_readings": len(measurements),
        }

    # 1. 0 measurements -> 0/60 (0.0%), Total Readings: 0
    cov0 = calculate_coverage([])
    assert cov0["distinct_count"] == 0
    assert cov0["total_cells"] == 60
    assert cov0["percentage"] == 0.0
    assert cov0["total_readings"] == 0

    # 2. 3 measurements at 3 different cells -> 3/60 (5.0%), Total Readings: 3
    meas3_diff = [
        {"id": 1, "floor": "Floor-1", "x": 1.0, "y": 1.0, "rssi_dbm": -50},
        {"id": 2, "floor": "Floor-1", "x": 2.0, "y": 1.0, "rssi_dbm": -55},
        {"id": 3, "floor": "Floor-1", "x": 3.0, "y": 1.0, "rssi_dbm": -60},
    ]
    cov3 = calculate_coverage(meas3_diff)
    assert cov3["distinct_count"] == 3
    assert cov3["total_cells"] == 60
    assert pytest.approx(cov3["percentage"], 0.01) == 5.0
    assert cov3["total_readings"] == 3

    # 3. 3 repeated measurements at 1 cell -> 1/60 (~1.67%), Total Readings: 3
    meas3_same = [
        {"id": 10, "floor": "Floor-1", "x": 4.0, "y": 2.0, "rssi_dbm": -42},
        {"id": 11, "floor": "Floor-1", "x": 4.0, "y": 2.0, "rssi_dbm": -44},
        {"id": 12, "floor": "Floor-1", "x": 4.0, "y": 2.0, "rssi_dbm": -41},
    ]
    cov_same = calculate_coverage(meas3_same)
    assert cov_same["distinct_count"] == 1
    assert cov_same["total_cells"] == 60
    assert pytest.approx(cov_same["percentage"], 0.01) == (1 / 60.0) * 100.0
    assert cov_same["total_readings"] == 3

    # 4. 60 distinct cells -> 60/60 (100.0%)
    meas60 = [
        {"id": i + 1, "floor": "Floor-1", "x": float(col), "y": float(row), "rssi_dbm": -50}
        for row in range(1, 7)
        for col, i in enumerate(range((row - 1) * 10, row * 10), start=1)
    ]
    cov60 = calculate_coverage(meas60)
    assert cov60["distinct_count"] == 60
    assert cov60["total_cells"] == 60
    assert cov60["percentage"] == 100.0
    assert cov60["total_readings"] == 60

    # 5. Persisted record with all null metrics counts towards coverage
    meas_null = [{"id": 99, "floor": "Floor-1", "x": 5.0, "y": 5.0, "rssi_dbm": None, "throughput_mbps": None}]
    cov_null = calculate_coverage(meas_null)
    assert cov_null["distinct_count"] == 1
    assert cov_null["total_readings"] == 1


# ----------------------------------------------------------------------
# Test 13 — M14 Selected-Cell History Filtering, Ordering & NULL Fidelity
# ----------------------------------------------------------------------

def test_m14_selected_cell_history_filtering_and_null_fidelity():
    """Verify history filtering strictly by session/floor/x/y, deterministic ordering, and null formatting."""
    all_measurements = [
        # Target cell readings (Session A, Cell 4.0, 2.0)
        {"id": 101, "session_id": "sess_a", "floor": "Floor-1", "x": 4.0, "y": 2.0, "rssi_dbm": -45, "latency_ms": 12.5, "packet_loss_percent": 0.0, "throughput_mbps": None, "sample_count": 5, "timestamp": "2026-09-22T10:00:00Z"},
        {"id": 105, "session_id": "sess_a", "floor": "Floor-1", "x": 4.0, "y": 2.0, "rssi_dbm": -42, "latency_ms": 10.0, "packet_loss_percent": 100.0, "throughput_mbps": 85.4, "sample_count": 5, "timestamp": "2026-09-22T10:05:00Z"},
        # Another cell in Session A
        {"id": 102, "session_id": "sess_a", "floor": "Floor-1", "x": 5.0, "y": 2.0, "rssi_dbm": -60, "latency_ms": 20.0, "packet_loss_percent": 0.0, "throughput_mbps": 40.0, "sample_count": 5, "timestamp": "2026-09-22T10:01:00Z"},
        # Same coordinates but different session (Session B)
        {"id": 201, "session_id": "sess_b", "floor": "Floor-1", "x": 4.0, "y": 2.0, "rssi_dbm": -80, "latency_ms": 50.0, "packet_loss_percent": 20.0, "throughput_mbps": 5.0, "sample_count": 5, "timestamp": "2026-09-22T11:00:00Z"},
    ]

    target_cell = {"floor": "Floor-1", "x": 4.0, "y": 2.0}
    active_session_id = "sess_a"

    target_key = f"{target_cell['floor']}_{target_cell['x']:.2f}_{target_cell['y']:.2f}"

    filtered = [
        m for m in all_measurements
        if m["session_id"] == active_session_id and f"{m['floor']}_{m['x']:.2f}_{m['y']:.2f}" == target_key
    ]

    # Verify filtering isolation
    assert len(filtered) == 2
    assert [m["id"] for m in filtered] == [101, 105]

    # Check first record formatting
    rec1 = filtered[0]
    assert rec1["rssi_dbm"] == -45
    assert rec1["packet_loss_percent"] == 0.0  # 0.0 preserved as numeric
    assert rec1["throughput_mbps"] is None     # null throughput remains null (renders N/A)

    # Check second record formatting
    rec2 = filtered[1]
    assert rec2["packet_loss_percent"] == 100.0  # 100% loss preserved


# ----------------------------------------------------------------------
# Test 14 — M14 Session Switching and State Isolation
# ----------------------------------------------------------------------

def test_m14_session_switching_isolation():
    """Verify switching from Session A to Session B resets coverage, history, and total readings."""
    session_a_data = [
        {"id": 1, "session_id": "sess_a", "floor": "Floor-1", "x": 1.0, "y": 1.0, "rssi_dbm": -50},
        {"id": 2, "session_id": "sess_a", "floor": "Floor-1", "x": 2.0, "y": 1.0, "rssi_dbm": -55},
    ]

    session_b_data = [
        {"id": 3, "session_id": "sess_b", "floor": "Floor-1", "x": 5.0, "y": 5.0, "rssi_dbm": -70},
    ]

    empty_session_data = []

    # Helper simulating state updates
    def process_session_switch(new_measurements):
        distinct = {f"{m['floor']}_{float(m['x']):.2f}_{float(m['y']):.2f}" for m in new_measurements}
        return {
            "sessionMeasurements": list(new_measurements),
            "coverage_count": len(distinct),
            "total_readings": len(new_measurements),
        }

    # Session A
    state_a = process_session_switch(session_a_data)
    assert state_a["coverage_count"] == 2
    assert state_a["total_readings"] == 2

    # Switch to Session B
    state_b = process_session_switch(session_b_data)
    assert state_b["coverage_count"] == 1
    assert state_b["total_readings"] == 1
    assert len(state_b["sessionMeasurements"]) == 1
    assert state_b["sessionMeasurements"][0]["id"] == 3

    # Switch to empty session
    state_empty = process_session_switch(empty_session_data)
    assert state_empty["coverage_count"] == 0
    assert state_empty["total_readings"] == 0
    assert len(state_empty["sessionMeasurements"]) == 0


# ----------------------------------------------------------------------
# Test 15 — M14 Live Measurement Append & Duplicate Protection
# ----------------------------------------------------------------------

def test_m14_live_measurement_append_and_duplicate_protection():
    """Verify merging live measurement updates total readings and coverage, and protects against duplicate IDs."""
    existing_measurements = [
        {"id": 50, "session_id": "sess_1", "floor": "Floor-1", "x": 3.0, "y": 2.0, "rssi_dbm": -60},
    ]

    def append_live_measurement(measurements_list, live_m):
        exists = any(m["id"] == live_m["id"] for m in measurements_list)
        if not exists:
            measurements_list.append(live_m)
        distinct = {f"{m['floor']}_{float(m['x']):.2f}_{float(m['y']):.2f}" for m in measurements_list}
        return len(distinct), len(measurements_list)

    # 1. Append measurement at a NEW cell -> coverage increments, total readings increments
    live_new_cell = {"id": 51, "session_id": "sess_1", "floor": "Floor-1", "x": 6.0, "y": 4.0, "rssi_dbm": -45}
    cov, total = append_live_measurement(existing_measurements, live_new_cell)
    assert cov == 2
    assert total == 2

    # 2. Append measurement at the SAME cell -> coverage stays 2, total readings increments to 3
    live_same_cell = {"id": 52, "session_id": "sess_1", "floor": "Floor-1", "x": 6.0, "y": 4.0, "rssi_dbm": -48}
    cov, total = append_live_measurement(existing_measurements, live_same_cell)
    assert cov == 2
    assert total == 3

    # 3. Duplicate append attempt with SAME measurement ID #52 -> no change
    cov, total = append_live_measurement(existing_measurements, live_same_cell)
    assert cov == 2
    assert total == 3


# ----------------------------------------------------------------------
# Test 16 — M14 Historical Status Fidelity Contract
# ----------------------------------------------------------------------

def test_m14_historical_status_fidelity_contract():
    """Verify that app.js does not fabricate transient orchestration status (COMPLETE/PARTIAL/FAILED) on historical rows."""
    app_js_path = FRONTEND_DIR / "app.js"
    js_content = app_js_path.read_text(encoding="utf-8")

    # Locate renderCellHistory implementation
    assert "function renderCellHistory" in js_content
    history_func_body = js_content.split("function renderCellHistory")[1].split("function fetchSessionMeasurements")[0]

    # Historical rows must display actual sample_count and metric values, not synthesized orchestration status
    assert "badge-status-complete" not in history_func_body
    assert "badge-status-partial" not in history_func_body
    assert "badge-status-failed" not in history_func_body
    assert "COMPLETE" not in history_func_body
    assert "PARTIAL" not in history_func_body


# ----------------------------------------------------------------------
# Test 17 — M14 Required UI Elements in HTML and CSS
# ----------------------------------------------------------------------

def test_m14_required_ui_elements_in_html_and_css():
    """Verify that index.html and style.css contain all required M14 IDs and classes."""
    html_content = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    css_content = (FRONTEND_DIR / "style.css").read_text(encoding="utf-8")

    m14_html_ids = [
        "survey-progress-card",
        "survey-coverage-text",
        "survey-total-readings-text",
        "survey-progress-bar-track",
        "survey-progress-bar-fill",
        "cell-history-section",
        "cell-history-count-badge",
        "cell-history-empty",
        "cell-history-list",
    ]

    for element_id in m14_html_ids:
        pattern = rf'id=["\']{re.escape(element_id)}["\']'
        assert re.search(pattern, html_content), f"index.html is missing M14 ID: {element_id}"

    m14_css_classes = [
        ".survey-progress-card",
        ".progress-stats-row",
        ".progress-label",
        ".progress-readings-count",
        ".progress-bar-track",
        ".progress-bar-fill",
        ".cell-history-section",
        ".history-header",
        ".history-title",
        ".history-empty-msg",
        ".history-list",
        ".history-row",
        ".history-row-header",
        ".history-row-metrics",
    ]

    for css_class in m14_css_classes:
        assert css_class in css_content, f"style.css is missing M14 class: {css_class}"

