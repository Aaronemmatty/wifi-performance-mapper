"""
tests/test_api.py
FastAPI Backend and REST API Test Suite for Milestone 5.

Verifies health checks, session management, measurement persistence,
query filtering, NULL/zero fidelity, historical coexistence, and error handling.
"""

from __future__ import annotations

import unittest.mock as mock
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
import psycopg2

from backend.main import create_app, app


@pytest.fixture
def client():
    """Test client for default FastAPI app."""
    return TestClient(app)


# ----------------------------------------------------------------------
# 1. Health & Documentation Tests
# ----------------------------------------------------------------------

def test_health_check_endpoint(client):
    """Verify GET /health returns status: ok without triggering database operations."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_available(client):
    """Verify OpenAPI JSON and documentation endpoints are exposed."""
    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200

    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    data = openapi_resp.json()
    assert "paths" in data
    assert "/health" in data["paths"]
    assert "/sessions" in data["paths"]
    assert "/measurements" in data["paths"]
    assert "/measurements/measure" in data["paths"]


# ----------------------------------------------------------------------
# 2. Session API Tests
# ----------------------------------------------------------------------

def test_create_session_success(client):
    """Test POST /sessions creates and returns session data."""
    mock_session = {
        "session_id": "sess_test_01",
        "name": "Floor 2 Survey",
        "floor": "Floor 2",
        "created_at": "2026-09-21T10:00:00Z",
        "notes": "Testing survey creation",
    }
    with mock.patch("backend.main.create_session", return_value=mock_session):
        response = client.post(
            "/sessions",
            json={
                "session_id": "sess_test_01",
                "name": "Floor 2 Survey",
                "floor": "Floor 2",
                "notes": "Testing survey creation",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["session_id"] == "sess_test_01"
        assert data["name"] == "Floor 2 Survey"
        assert data["floor"] == "Floor 2"


def test_create_session_validation_error(client):
    """Test POST /sessions rejects missing or empty required fields with 422."""
    # Missing floor
    response = client.post(
        "/sessions",
        json={"session_id": "sess_01", "name": "Survey"},
    )
    assert response.status_code == 422

    # Empty whitespace session_id
    response = client.post(
        "/sessions",
        json={"session_id": "   ", "name": "Survey", "floor": "Floor 1"},
    )
    assert response.status_code == 422


def test_create_session_duplicate_conflict(client):
    """Test POST /sessions returns 409 Conflict when session_id already exists."""
    with mock.patch("backend.main.create_session", side_effect=psycopg2.IntegrityError("duplicate key")):
        response = client.post(
            "/sessions",
            json={"session_id": "duplicate_id", "name": "Survey", "floor": "Floor 1"},
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]


def test_list_sessions_success(client):
    """Test GET /sessions returns list of survey sessions."""
    mock_list = [
        {
            "session_id": "sess_02",
            "name": "Floor 2 Afternoon",
            "floor": "Floor 2",
            "created_at": "2026-09-21T14:00:00Z",
            "notes": None,
        },
        {
            "session_id": "sess_01",
            "name": "Floor 1 Morning",
            "floor": "Floor 1",
            "created_at": "2026-09-21T09:00:00Z",
            "notes": "Clear weather",
        },
    ]
    with mock.patch("backend.main.list_sessions", return_value=mock_list):
        response = client.get("/sessions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["session_id"] == "sess_02"
        assert data[1]["session_id"] == "sess_01"


def test_get_session_by_id_found_and_not_found(client):
    """Test GET /sessions/{session_id} handles found (200) and missing (404)."""
    mock_session = {
        "session_id": "sess_found",
        "name": "Found Survey",
        "floor": "Floor 3",
        "created_at": "2026-09-21T12:00:00Z",
        "notes": None,
    }
    with mock.patch("backend.main.get_session", side_effect=lambda session_id, **kwargs: mock_session if session_id == "sess_found" else None):
        # Found
        resp_found = client.get("/sessions/sess_found")
        assert resp_found.status_code == 200
        assert resp_found.json()["session_id"] == "sess_found"

        # Not found
        resp_missing = client.get("/sessions/non_existent_sess")
        assert resp_missing.status_code == 404
        assert "not found" in resp_missing.json()["detail"].lower()


# ----------------------------------------------------------------------
# 3. Measurement API Tests
# ----------------------------------------------------------------------

def test_create_measurement_success(client):
    """Test POST /measurements records and returns measurement point."""
    mock_measurement = {
        "id": 1,
        "session_id": "sess_01",
        "floor": "Floor 2",
        "x": 10.5,
        "y": 20.0,
        "rssi_dbm": -35,
        "signal_percent": 100,
        "latency_ms": 8.5,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 50.0,
        "ssid": "CAMPUS_WIFI",
        "bssid": "00:11:22:33:44:55",
        "channel": 6,
        "frequency_mhz": 2437.0,
        "radio_type": "802.11n",
        "adapter_name": "Qualcomm Atheros",
        "driver_version": "12.0.0.722",
        "sample_count": 5,
        "timestamp": "2026-09-21T10:05:00Z",
        "created_at": "2026-09-21T10:05:01Z",
    }
    with mock.patch("backend.main.create_measurement", return_value=mock_measurement):
        response = client.post(
            "/measurements",
            json={
                "session_id": "sess_01",
                "floor": "Floor 2",
                "x": 10.5,
                "y": 20.0,
                "rssi_dbm": -35,
                "signal_percent": 100,
                "latency_ms": 8.5,
                "packet_loss_percent": 0.0,
                "throughput_mbps": 50.0,
                "sample_count": 5,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == 1
        assert data["rssi_dbm"] == -35
        assert data["latency_ms"] == 8.5
        assert data["packet_loss_percent"] == 0.0
        assert data["sample_count"] == 5


def test_create_measurement_foreign_key_failure(client):
    """Test POST /measurements returns 400 Bad Request when session_id does not exist."""
    with mock.patch("backend.main.create_measurement", side_effect=psycopg2.IntegrityError("fk violation")):
        response = client.post(
            "/measurements",
            json={
                "session_id": "non_existent_session",
                "floor": "Floor 1",
                "x": 0.0,
                "y": 0.0,
            },
        )
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"].lower()


def test_measurement_constraint_validation_errors(client):
    """Test Pydantic validation rejects out-of-bounds metric values with 422."""
    # Positive RSSI is physically invalid
    resp = client.post("/measurements", json={"session_id": "s1", "floor": "F1", "x": 0, "y": 0, "rssi_dbm": 10})
    assert resp.status_code == 422

    # Signal percent > 100
    resp = client.post("/measurements", json={"session_id": "s1", "floor": "F1", "x": 0, "y": 0, "signal_percent": 150})
    assert resp.status_code == 422

    # Negative latency
    resp = client.post("/measurements", json={"session_id": "s1", "floor": "F1", "x": 0, "y": 0, "latency_ms": -5.0})
    assert resp.status_code == 422

    # Negative throughput
    resp = client.post("/measurements", json={"session_id": "s1", "floor": "F1", "x": 0, "y": 0, "throughput_mbps": -1.0})
    assert resp.status_code == 422

    # Sample count < 1
    resp = client.post("/measurements", json={"session_id": "s1", "floor": "F1", "x": 0, "y": 0, "sample_count": 0})
    assert resp.status_code == 422


# ----------------------------------------------------------------------
# 4. NULL Semantics vs Fake Zeroes
# ----------------------------------------------------------------------

def test_null_semantics_preserved_in_api(client):
    """Verify API preserves explicit null values and does not substitute fake zeros."""
    mock_null_resp = {
        "id": 10,
        "session_id": "s_null",
        "floor": "Floor 1",
        "x": 5.0,
        "y": 5.0,
        "rssi_dbm": None,
        "signal_percent": None,
        "latency_ms": None,
        "packet_loss_percent": None,
        "throughput_mbps": None,
        "ssid": None,
        "bssid": None,
        "channel": None,
        "frequency_mhz": None,
        "radio_type": None,
        "adapter_name": None,
        "driver_version": None,
        "sample_count": 1,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:00Z",
    }
    with mock.patch("backend.main.create_measurement", return_value=mock_null_resp) as mock_create:
        response = client.post(
            "/measurements",
            json={
                "session_id": "s_null",
                "floor": "Floor 1",
                "x": 5.0,
                "y": 5.0,
                "rssi_dbm": None,
                "latency_ms": None,
                "packet_loss_percent": None,
                "throughput_mbps": None,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["rssi_dbm"] is None
        assert data["latency_ms"] is None
        assert data["packet_loss_percent"] is None
        assert data["throughput_mbps"] is None

        # Verify kwargs passed to repository had None
        kwargs = mock_create.call_args[1]
        assert kwargs["rssi_dbm"] is None
        assert kwargs["latency_ms"] is None
        assert kwargs["packet_loss_percent"] is None
        assert kwargs["throughput_mbps"] is None


def test_zero_values_preserved_in_api(client):
    """Verify measured zero values (0% loss, 0.0 Mbps) are preserved as 0.0 and not null."""
    mock_zero_resp = {
        "id": 11,
        "session_id": "s_zero",
        "floor": "Floor 1",
        "x": 5.0,
        "y": 5.0,
        "rssi_dbm": -50,
        "signal_percent": 80,
        "latency_ms": 10.0,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 0.0,
        "ssid": None,
        "bssid": None,
        "channel": None,
        "frequency_mhz": None,
        "radio_type": None,
        "adapter_name": None,
        "driver_version": None,
        "sample_count": 1,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:00Z",
    }
    with mock.patch("backend.main.create_measurement", return_value=mock_zero_resp):
        response = client.post(
            "/measurements",
            json={
                "session_id": "s_zero",
                "floor": "Floor 1",
                "x": 5.0,
                "y": 5.0,
                "packet_loss_percent": 0.0,
                "throughput_mbps": 0.0,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["packet_loss_percent"] == 0.0
        assert data["throughput_mbps"] == 0.0


# ----------------------------------------------------------------------
# 5. Historical Coexistence Tests
# ----------------------------------------------------------------------

def test_historical_measurements_coexistence_api(client):
    """
    Verify that creating multiple measurements at the exact same (session_id, floor, x, y)
    returns distinct records with different IDs, preserving history without overwrite.
    """
    row_1 = {
        "id": 101,
        "session_id": "sess_walk",
        "floor": "Floor 2",
        "x": 10.5,
        "y": 20.0,
        "rssi_dbm": -35,
        "sample_count": 1,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:00Z",
    }
    row_2 = {
        "id": 102,
        "session_id": "sess_walk",
        "floor": "Floor 2",
        "x": 10.5,
        "y": 20.0,
        "rssi_dbm": -40,
        "sample_count": 1,
        "timestamp": "2026-09-21T10:05:00Z",
        "created_at": "2026-09-21T10:05:00Z",
    }

    with mock.patch("backend.main.create_measurement", side_effect=[row_1, row_2]):
        resp1 = client.post("/measurements", json={"session_id": "sess_walk", "floor": "Floor 2", "x": 10.5, "y": 20.0, "rssi_dbm": -35})
        resp2 = client.post("/measurements", json={"session_id": "sess_walk", "floor": "Floor 2", "x": 10.5, "y": 20.0, "rssi_dbm": -40})

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] == 101
        assert resp2.json()["id"] == 102
        assert resp1.json()["rssi_dbm"] == -35
        assert resp2.json()["rssi_dbm"] == -40


# ----------------------------------------------------------------------
# 6. Measurement Listing & Filtering Tests
# ----------------------------------------------------------------------

def test_list_measurements_with_filters(client):
    """Test GET /measurements passes query parameters to repository."""
    mock_records = [
        {
            "id": 1,
            "session_id": "sess_01",
            "floor": "Floor 2",
            "x": 10.0,
            "y": 20.0,
            "sample_count": 1,
            "timestamp": "2026-09-21T10:00:00Z",
            "created_at": "2026-09-21T10:00:00Z",
        }
    ]
    with mock.patch("backend.main.list_measurements", return_value=mock_records) as mock_list:
        response = client.get("/measurements?session_id=sess_01&floor=Floor%202&x=10.0&y=20.0")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == 1

        mock_list.assert_called_once_with(
            session_id="sess_01",
            floor="Floor 2",
            x=10.0,
            y=20.0,
            database_url=None,
            is_test=False,
        )


def test_get_measurement_by_id_found_and_not_found(client):
    """Test GET /measurements/{id} handles found (200) and missing (404)."""
    mock_record = {
        "id": 42,
        "session_id": "sess_01",
        "floor": "Floor 1",
        "x": 1.0,
        "y": 2.0,
        "sample_count": 1,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:00Z",
    }
    with mock.patch("backend.main.get_measurement", side_effect=lambda measurement_id, **kwargs: mock_record if measurement_id == 42 else None):
        # Found
        resp_found = client.get("/measurements/42")
        assert resp_found.status_code == 200
        assert resp_found.json()["id"] == 42

        # Not found
        resp_missing = client.get("/measurements/999")
        assert resp_missing.status_code == 404
        assert "not found" in resp_missing.json()["detail"].lower()


# ----------------------------------------------------------------------
# 7. Measurement Orchestration API Tests (Milestone 8)
# ----------------------------------------------------------------------

def _make_wifi_info(
    is_connected: bool = True,
    bssid: str = "00:11:22:33:44:55",
    rssi_dbm: int = -45,
    signal_percent: int = 90,
) -> WifiConnectionInfo:
    from backend.wifi_windows import WifiConnectionInfo
    return WifiConnectionInfo(
        is_connected=is_connected,
        ssid="CAMPUS_WIFI" if is_connected else None,
        bssid=bssid if is_connected else None,
        signal_percent=signal_percent if is_connected else 0,
        rssi_dbm=rssi_dbm if is_connected else None,
        channel=6 if is_connected else None,
        frequency_mhz=2437.0 if is_connected else None,
        radio_type="802.11ax" if is_connected else None,
        receive_rate_mbps=300.0 if is_connected else None,
        transmit_rate_mbps=300.0 if is_connected else None,
        adapter_name="Wi-Fi 6 Adapter" if is_connected else None,
        driver_version="22.100.0.3" if is_connected else None,
    )


def _make_net_result(
    is_successful: bool = True,
    latency_median_ms: Optional[float] = 6.0,
    packet_loss_percent: Optional[float] = 0.0,
    throughput_mbps: Optional[float] = 85.5,
) -> NetworkPerformanceResult:
    from backend.network_tests import (
        NetworkPerformanceResult,
        LatencySummary,
        PacketLossResult,
        ThroughputResult,
    )
    loss = packet_loss_percent if packet_loss_percent is not None else 100.0
    return NetworkPerformanceResult(
        target_host="192.168.1.1",
        timestamp=datetime.now(timezone.utc).isoformat(),
        latency=LatencySummary(
            min_ms=latency_median_ms - 1.0 if latency_median_ms is not None else None,
            avg_ms=latency_median_ms,
            max_ms=latency_median_ms + 1.0 if latency_median_ms is not None else None,
            median_ms=latency_median_ms,
            successful_probes=4 if is_successful else 0,
            total_probes=4,
        ),
        packet_loss=PacketLossResult(
            sent_probes=4,
            received_probes=4 if is_successful and loss == 0.0 else 0,
            lost_probes=0 if is_successful and loss == 0.0 else 4,
            loss_percent=loss,
        ),
        probes=[],
        throughput=ThroughputResult(
            throughput_mbps=throughput_mbps,
            status="COMPLETED" if throughput_mbps is not None else "NOT_CONFIGURED",
        ),
        is_successful=is_successful,
        error_message=None if is_successful else "Network unreachable",
    )


def test_measure_endpoint_request_validation(client):
    """Verify POST /measurements/measure rejects invalid inputs and forbidden sample_count with 422."""
    # 1. Missing session_id
    resp = client.post("/measurements/measure", json={"floor": "Floor 1", "x": 10.0, "y": 20.0})
    assert resp.status_code == 422

    # 2. Empty / whitespace floor
    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "   ", "x": 10.0, "y": 20.0})
    assert resp.status_code == 422

    # 3. Empty / whitespace session_id
    resp = client.post("/measurements/measure", json={"session_id": "", "floor": "Floor 1", "x": 10.0, "y": 20.0})
    assert resp.status_code == 422

    # 4. Caller attempting to pass arbitrary sample_count must be rejected (extra forbidden)
    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": 10.0, "y": 20.0, "sample_count": 1})
    assert resp.status_code == 422

    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": 10.0, "y": 20.0, "sample_count": 4})
    assert resp.status_code == 422

    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": 10.0, "y": 20.0, "sample_count": 5})
    assert resp.status_code == 422

    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": 10.0, "y": 20.0, "sample_count": 6})
    assert resp.status_code == 422

    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": 10.0, "y": 20.0, "sample_count": 50})
    assert resp.status_code == 422

    # 5. Non-numeric / non-finite coordinate strings
    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": "invalid_x", "y": 20.0})
    assert resp.status_code == 422

    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": "NaN", "y": 20.0})
    assert resp.status_code == 422

    resp = client.post("/measurements/measure", json={"session_id": "s1", "floor": "Floor 1", "x": 10.0, "y": "Infinity"})
    assert resp.status_code == 422


def test_measure_endpoint_complete_measurement(client):
    """
    Verify POST /measurements/measure for a 5/5 valid sample measurement:
    - Request does NOT pass sample_count (methodology locks to 5)
    - Status code: 200 OK
    - status: COMPLETE
    - persisted: True
    - valid_samples_count: 5
    - sample_count: 5
    - Canonical measurement record populated with medians
    """
    wifi = _make_wifi_info(is_connected=True, bssid="00:11:22:33:44:55", rssi_dbm=-45)
    net = _make_net_result(is_successful=True, latency_median_ms=6.0, packet_loss_percent=0.0, throughput_mbps=85.5)

    mock_db_row = {
        "id": 101,
        "session_id": "sess_measure_01",
        "floor": "Floor-1",
        "x": 10.0,
        "y": 15.0,
        "rssi_dbm": -45,
        "signal_percent": 90,
        "latency_ms": 6.0,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 85.5,
        "ssid": "CAMPUS_WIFI",
        "bssid": "00:11:22:33:44:55",
        "channel": 6,
        "frequency_mhz": 2437.0,
        "radio_type": "802.11ax",
        "adapter_name": "Wi-Fi 6 Adapter",
        "driver_version": "22.100.0.3",
        "sample_count": 5,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:01Z",
    }

    with mock.patch("backend.measurement.get_current_wifi_info", return_value=wifi), \
         mock.patch("backend.measurement.measure_network_performance", return_value=net), \
         mock.patch("backend.measurement_service.create_measurement", return_value=mock_db_row):

        response = client.post(
            "/measurements/measure",
            json={"session_id": "sess_measure_01", "floor": "Floor-1", "x": 10.0, "y": 15.0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "sess_measure_01"
        assert data["floor"] == "Floor-1"
        assert data["x"] == 10.0
        assert data["y"] == 15.0
        assert data["status"] == "COMPLETE"
        assert data["is_successful"] is True
        assert data["persisted"] is True
        assert data["valid_samples_count"] == 5
        assert data["sample_count"] == 5
        assert data["bssid_changed"] is False
        assert data["bssids_observed"] == ["00:11:22:33:44:55"]
        assert data["measurement"] is not None
        assert data["measurement"]["id"] == 101
        assert data["measurement"]["rssi_dbm"] == -45
        assert data["measurement"]["latency_ms"] == 6.0
        assert data["measurement"]["packet_loss_percent"] == 0.0
        assert data["measurement"]["throughput_mbps"] == 85.5


def test_measure_endpoint_partial_measurement(client):
    """
    Verify POST /measurements/measure for a 3/5 valid sample measurement:
    - Status code: 200 OK
    - status: PARTIAL
    - persisted: True
    - valid_samples_count: 3
    - sample_count: 5
    - Canonical medians persisted from the 3 valid samples
    """
    valid_wifi = _make_wifi_info(is_connected=True, rssi_dbm=-60)
    valid_net = _make_net_result(is_successful=True, latency_median_ms=12.0)
    failed_wifi = _make_wifi_info(is_connected=False)
    failed_net = _make_net_result(is_successful=False, latency_median_ms=None, packet_loss_percent=None)

    wifi_sequence = [valid_wifi, valid_wifi, failed_wifi, valid_wifi, failed_wifi]
    net_sequence = [valid_net, valid_net, failed_net, valid_net, failed_net]

    mock_db_row = {
        "id": 102,
        "session_id": "sess_measure_partial",
        "floor": "Floor-2",
        "x": 5.0,
        "y": 8.0,
        "rssi_dbm": -60,
        "signal_percent": 90,
        "latency_ms": 12.0,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 85.5,
        "ssid": "CAMPUS_WIFI",
        "bssid": "00:11:22:33:44:55",
        "channel": 6,
        "frequency_mhz": 2437.0,
        "radio_type": "802.11ax",
        "adapter_name": "Wi-Fi 6 Adapter",
        "driver_version": "22.100.0.3",
        "sample_count": 5,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:01Z",
    }

    with mock.patch("backend.measurement.get_current_wifi_info", side_effect=wifi_sequence), \
         mock.patch("backend.measurement.measure_network_performance", side_effect=net_sequence), \
         mock.patch("backend.measurement_service.create_measurement", return_value=mock_db_row):

        response = client.post(
            "/measurements/measure",
            json={"session_id": "sess_measure_partial", "floor": "Floor-2", "x": 5.0, "y": 8.0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PARTIAL"
        assert data["is_successful"] is True
        assert data["persisted"] is True
        assert data["valid_samples_count"] == 3
        assert data["sample_count"] == 5
        assert data["measurement"] is not None
        assert data["measurement"]["id"] == 102
        assert "3 of 5" in data["error_message"]


def test_measure_endpoint_failed_measurement(client):
    """
    Verify POST /measurements/measure for a 0/5 valid sample measurement:
    - Status code: 502 Bad Gateway (probe failure)
    - status: FAILED
    - persisted: False
    - valid_samples_count: 0
    - sample_count: 5
    - measurement is None (zero rows written)
    """
    failed_wifi = _make_wifi_info(is_connected=False)
    failed_net = _make_net_result(is_successful=False, latency_median_ms=None, packet_loss_percent=None)

    with mock.patch("backend.measurement.get_current_wifi_info", return_value=failed_wifi), \
         mock.patch("backend.measurement.measure_network_performance", return_value=failed_net), \
         mock.patch("backend.measurement_service.create_measurement") as mock_create:

        response = client.post(
            "/measurements/measure",
            json={"session_id": "sess_measure_fail", "floor": "Floor-1", "x": 0.0, "y": 0.0},
        )

        assert response.status_code == 502
        data = response.json()
        assert data["status"] == "FAILED"
        assert data["is_successful"] is False
        assert data["persisted"] is False
        assert data["valid_samples_count"] == 0
        assert data["sample_count"] == 5
        assert data["measurement"] is None
        assert "failed" in data["error_message"].lower()

        # Confirm repository was never called
        mock_create.assert_not_called()


def test_measure_endpoint_preserves_null_and_zero_values(client):
    """Verify that null metrics (throughput=None) and numeric zeroes (packet_loss=0.0) are preserved."""
    wifi = _make_wifi_info(is_connected=True, rssi_dbm=-70)
    net = _make_net_result(is_successful=True, latency_median_ms=15.0, packet_loss_percent=0.0, throughput_mbps=None)

    mock_db_row = {
        "id": 103,
        "session_id": "sess_null_zero",
        "floor": "Floor-1",
        "x": 2.0,
        "y": 3.0,
        "rssi_dbm": -70,
        "signal_percent": 90,
        "latency_ms": 15.0,
        "packet_loss_percent": 0.0,
        "throughput_mbps": None,
        "ssid": "CAMPUS_WIFI",
        "bssid": "00:11:22:33:44:55",
        "channel": 6,
        "frequency_mhz": 2437.0,
        "radio_type": "802.11ax",
        "adapter_name": "Wi-Fi 6 Adapter",
        "driver_version": "22.100.0.3",
        "sample_count": 5,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:01Z",
    }

    with mock.patch("backend.measurement.get_current_wifi_info", return_value=wifi), \
         mock.patch("backend.measurement.measure_network_performance", return_value=net), \
         mock.patch("backend.measurement_service.create_measurement", return_value=mock_db_row) as mock_create:

        response = client.post(
            "/measurements/measure",
            json={"session_id": "sess_null_zero", "floor": "Floor-1", "x": 2.0, "y": 3.0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["measurement"]["throughput_mbps"] is None
        assert data["measurement"]["packet_loss_percent"] == 0.0

        # Check repository call kwargs
        kwargs = mock_create.call_args[1]
        assert kwargs["throughput_mbps"] is None
        assert kwargs["packet_loss_percent"] == 0.0


def test_measure_endpoint_historical_measurements_coexistence(client):
    """
    Verify two sequential measurement requests at the same (session_id, floor, x, y)
    create two distinct database records with unique IDs.
    """
    wifi = _make_wifi_info(is_connected=True)
    net = _make_net_result(is_successful=True)

    row1 = {
        "id": 201,
        "session_id": "sess_hist",
        "floor": "Floor-1",
        "x": 10.0,
        "y": 20.0,
        "rssi_dbm": -45,
        "sample_count": 5,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:01Z",
    }
    row2 = {
        "id": 202,
        "session_id": "sess_hist",
        "floor": "Floor-1",
        "x": 10.0,
        "y": 20.0,
        "rssi_dbm": -50,
        "sample_count": 5,
        "timestamp": "2026-09-21T10:05:00Z",
        "created_at": "2026-09-21T10:05:01Z",
    }

    with mock.patch("backend.measurement.get_current_wifi_info", return_value=wifi), \
         mock.patch("backend.measurement.measure_network_performance", return_value=net), \
         mock.patch("backend.measurement_service.create_measurement", side_effect=[row1, row2]):

        resp1 = client.post("/measurements/measure", json={"session_id": "sess_hist", "floor": "Floor-1", "x": 10.0, "y": 20.0})
        resp2 = client.post("/measurements/measure", json={"session_id": "sess_hist", "floor": "Floor-1", "x": 10.0, "y": 20.0})

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["measurement"]["id"] == 201
        assert resp2.json()["measurement"]["id"] == 202


def test_measure_endpoint_session_foreign_key_failure(client):
    """Verify POST /measurements/measure returns 400 Bad Request when session_id does not exist."""
    wifi = _make_wifi_info(is_connected=True)
    net = _make_net_result(is_successful=True)

    with mock.patch("backend.measurement.get_current_wifi_info", return_value=wifi), \
         mock.patch("backend.measurement.measure_network_performance", return_value=net), \
         mock.patch("backend.measurement_service.create_measurement", side_effect=psycopg2.IntegrityError("fk violation")):

        response = client.post(
            "/measurements/measure",
            json={"session_id": "non_existent_sess", "floor": "Floor-1", "x": 1.0, "y": 1.0},
        )

        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"].lower()


def test_measure_endpoint_bssid_roaming(client):
    """
    Verify POST /measurements/measure when BSSID roaming occurs during probing:
    - bssid_changed: True
    - bssids_observed: [BSSID_A, BSSID_B]
    - Status: COMPLETE (not rejected due to roaming)
    """
    wifi_a = _make_wifi_info(is_connected=True, bssid="00:11:22:33:44:01", rssi_dbm=-45)
    wifi_b = _make_wifi_info(is_connected=True, bssid="00:11:22:33:44:02", rssi_dbm=-55)
    net = _make_net_result(is_successful=True)

    wifi_sequence = [wifi_a, wifi_a, wifi_b, wifi_b, wifi_b]
    net_sequence = [net, net, net, net, net]

    mock_db_row = {
        "id": 301,
        "session_id": "sess_roam",
        "floor": "Floor-1",
        "x": 10.0,
        "y": 10.0,
        "rssi_dbm": -55,
        "signal_percent": 90,
        "latency_ms": 6.0,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 85.5,
        "ssid": "CAMPUS_WIFI",
        "bssid": "00:11:22:33:44:02",
        "sample_count": 5,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:01Z",
    }

    with mock.patch("backend.measurement.get_current_wifi_info", side_effect=wifi_sequence), \
         mock.patch("backend.measurement.measure_network_performance", side_effect=net_sequence), \
         mock.patch("backend.measurement_service.create_measurement", return_value=mock_db_row):

        response = client.post(
            "/measurements/measure",
            json={"session_id": "sess_roam", "floor": "Floor-1", "x": 10.0, "y": 10.0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "COMPLETE"
        assert data["is_successful"] is True
        assert data["bssid_changed"] is True
        assert set(data["bssids_observed"]) == {"00:11:22:33:44:01", "00:11:22:33:44:02"}
        assert data["measurement"]["bssid"] == "00:11:22:33:44:02"


def test_measure_endpoint_internal_server_error(client):
    """Verify unexpected exceptions in measurement orchestration return 500 Internal Server Error."""
    with mock.patch("backend.main.execute_and_persist_measurement", side_effect=RuntimeError("unexpected crash")):
        response = client.post(
            "/measurements/measure",
            json={"session_id": "sess_err", "floor": "Floor-1", "x": 0.0, "y": 0.0},
        )
        assert response.status_code == 500
        assert "internal server error" in response.json()["detail"].lower()


# ----------------------------------------------------------------------
# 8. M9 — Sessions & Historical Measurement Read API Tests
# ----------------------------------------------------------------------

def test_get_sessions_field_preservation_and_read_only(client):
    """
    Verify GET /sessions returns all persisted fields (session_id, name, floor, created_at, notes)
    and executes as a pure read operation without invoking mutation functions.
    """
    mock_sessions = [
        {
            "session_id": "sess_fl2_01",
            "name": "Floor 2 Survey",
            "floor": "Floor 2",
            "created_at": "2026-09-21T14:30:00Z",
            "notes": "Afternoon run",
        },
        {
            "session_id": "sess_fl1_01",
            "name": "Floor 1 Survey",
            "floor": "Floor 1",
            "created_at": "2026-09-21T10:00:00Z",
            "notes": None,
        },
    ]

    with mock.patch("backend.main.list_sessions", return_value=mock_sessions) as mock_list, \
         mock.patch("backend.main.create_session") as mock_create:

        resp = client.get("/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        # Verify field preservation
        assert data[0]["session_id"] == "sess_fl2_01"
        assert data[0]["name"] == "Floor 2 Survey"
        assert data[0]["floor"] == "Floor 2"
        assert data[0]["created_at"] == "2026-09-21T14:30:00Z"
        assert data[0]["notes"] == "Afternoon run"

        assert data[1]["session_id"] == "sess_fl1_01"
        assert data[1]["notes"] is None

        # Verify read-only: no write methods invoked
        mock_list.assert_called_once()
        mock_create.assert_not_called()


def test_get_session_by_id_read_only_and_404(client):
    """
    Verify GET /sessions/{session_id}:
    - Returns full persisted session when found
    - Returns 404 with clean detail when missing
    - Does not modify database or create a session on 404
    """
    mock_session = {
        "session_id": "sess_existing",
        "name": "Existing Survey",
        "floor": "Floor 3",
        "created_at": "2026-09-21T12:00:00Z",
        "notes": "Verified notes",
    }

    with mock.patch("backend.main.get_session", side_effect=lambda session_id, **kwargs: mock_session if session_id == "sess_existing" else None) as mock_get, \
         mock.patch("backend.main.create_session") as mock_create:

        # 1. Existing session
        resp_found = client.get("/sessions/sess_existing")
        assert resp_found.status_code == 200
        found_data = resp_found.json()
        assert found_data["session_id"] == "sess_existing"
        assert found_data["name"] == "Existing Survey"
        assert found_data["floor"] == "Floor 3"
        assert found_data["notes"] == "Verified notes"

        # 2. Unknown session
        resp_404 = client.get("/sessions/sess_non_existent")
        assert resp_404.status_code == 404
        assert "not found" in resp_404.json()["detail"].lower()

        # Verify no create called
        mock_create.assert_not_called()


def test_get_measurement_by_id_all_19_fields(client):
    """
    Verify GET /measurements/{id} preserves all 19 contract fields:
    id, session_id, floor, x, y, rssi_dbm, signal_percent, latency_ms,
    packet_loss_percent, throughput_mbps, ssid, bssid, channel, frequency_mhz,
    radio_type, adapter_name, driver_version, sample_count, timestamp, created_at.
    """
    mock_record = {
        "id": 42,
        "session_id": "sess_full_01",
        "floor": "Floor 2",
        "x": 12.5,
        "y": 24.0,
        "rssi_dbm": -42,
        "signal_percent": 95,
        "latency_ms": 5.2,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 92.4,
        "ssid": "CAMPUS_WIFI",
        "bssid": "00:11:22:33:44:55",
        "channel": 36,
        "frequency_mhz": 5180.0,
        "radio_type": "802.11ax",
        "adapter_name": "Intel Wi-Fi 6 AX200",
        "driver_version": "22.50.1.1",
        "sample_count": 5,
        "timestamp": "2026-09-21T11:00:00Z",
        "created_at": "2026-09-21T11:00:01Z",
    }

    with mock.patch("backend.main.get_measurement", return_value=mock_record):
        resp = client.get("/measurements/42")
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == 42
        assert data["session_id"] == "sess_full_01"
        assert data["floor"] == "Floor 2"
        assert data["x"] == 12.5
        assert data["y"] == 24.0
        assert data["rssi_dbm"] == -42
        assert data["signal_percent"] == 95
        assert data["latency_ms"] == 5.2
        assert data["packet_loss_percent"] == 0.0
        assert data["throughput_mbps"] == 92.4
        assert data["ssid"] == "CAMPUS_WIFI"
        assert data["bssid"] == "00:11:22:33:44:55"
        assert data["channel"] == 36
        assert data["frequency_mhz"] == 5180.0
        assert data["radio_type"] == "802.11ax"
        assert data["adapter_name"] == "Intel Wi-Fi 6 AX200"
        assert data["driver_version"] == "22.50.1.1"
        assert data["sample_count"] == 5
        assert "2026-09-21T11:00:00" in data["timestamp"]
        assert "2026-09-21T11:00:01" in data["created_at"]


def test_get_measurement_by_id_404_clean_error(client):
    """Verify GET /measurements/{id} for non-existent ID returns 404 without leaking stack trace."""
    with mock.patch("backend.main.get_measurement", return_value=None):
        resp = client.get("/measurements/99999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


def test_get_measurements_null_zero_hundred_fidelity_read(client):
    """
    Verify GET /measurements and GET /measurements/{id} preserve exact distinctions:
    - throughput_mbps = null != 0.0
    - packet_loss_percent = 0.0 != null
    - packet_loss_percent = 100.0 != null
    - rssi_dbm = null != 0
    """
    row_zero_loss = {
        "id": 1,
        "session_id": "sess_fidelity",
        "floor": "Floor 1",
        "x": 0.0,
        "y": 0.0,
        "rssi_dbm": -50,
        "signal_percent": 80,
        "latency_ms": 10.0,
        "packet_loss_percent": 0.0,
        "throughput_mbps": None,  # NULL throughput
        "ssid": "WIFI",
        "bssid": "00:11:22:33:44:55",
        "channel": 1,
        "frequency_mhz": 2412.0,
        "radio_type": "802.11n",
        "adapter_name": "Adapter",
        "driver_version": "1.0",
        "sample_count": 5,
        "timestamp": "2026-09-21T10:00:00Z",
        "created_at": "2026-09-21T10:00:00Z",
    }
    row_hundred_loss = {
        "id": 2,
        "session_id": "sess_fidelity",
        "floor": "Floor 1",
        "x": 1.0,
        "y": 1.0,
        "rssi_dbm": None,  # NULL RSSI
        "signal_percent": None,
        "latency_ms": None,
        "packet_loss_percent": 100.0,  # 100% loss
        "throughput_mbps": 0.0,  # Explicit 0.0 throughput
        "ssid": None,
        "bssid": None,
        "channel": None,
        "frequency_mhz": None,
        "radio_type": None,
        "adapter_name": None,
        "driver_version": None,
        "sample_count": 5,
        "timestamp": "2026-09-21T10:01:00Z",
        "created_at": "2026-09-21T10:01:00Z",
    }

    # 1. Test GET /measurements list
    with mock.patch("backend.main.list_measurements", return_value=[row_zero_loss, row_hundred_loss]):
        resp = client.get("/measurements?session_id=sess_fidelity")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2

        # Item 0: 0.0 packet loss, null throughput, -50 RSSI
        assert items[0]["packet_loss_percent"] == 0.0
        assert items[0]["packet_loss_percent"] is not None
        assert items[0]["throughput_mbps"] is None
        assert items[0]["rssi_dbm"] == -50

        # Item 1: 100.0 packet loss, 0.0 throughput, null RSSI
        assert items[1]["packet_loss_percent"] == 100.0
        assert items[1]["throughput_mbps"] == 0.0
        assert items[1]["throughput_mbps"] is not None
        assert items[1]["rssi_dbm"] is None

    # 2. Test GET /measurements/{id} for item 1
    with mock.patch("backend.main.get_measurement", return_value=row_hundred_loss):
        resp_single = client.get("/measurements/2")
        assert resp_single.status_code == 200
        data = resp_single.json()
        assert data["packet_loss_percent"] == 100.0
        assert data["throughput_mbps"] == 0.0
        assert data["rssi_dbm"] is None


def test_get_measurements_duplicate_coordinates_historical_retrieval(client):
    """
    Verify historical append-only duplicate-coordinate preservation:
    Two measurements at identical (session_id, floor, x, y) are both returned in list
    and remain individually accessible by distinct IDs without overwriting or collapsing.
    """
    row_t1 = {
        "id": 501,
        "session_id": "sess_dup_coords",
        "floor": "Floor 1",
        "x": 5.0,
        "y": 5.0,
        "rssi_dbm": -40,
        "signal_percent": 90,
        "latency_ms": 4.5,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 80.0,
        "sample_count": 5,
        "timestamp": "2026-09-21T09:00:00Z",
        "created_at": "2026-09-21T09:00:01Z",
    }
    row_t2 = {
        "id": 502,
        "session_id": "sess_dup_coords",
        "floor": "Floor 1",
        "x": 5.0,
        "y": 5.0,
        "rssi_dbm": -55,
        "signal_percent": 75,
        "latency_ms": 12.0,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 45.0,
        "sample_count": 5,
        "timestamp": "2026-09-21T11:00:00Z",
        "created_at": "2026-09-21T11:00:01Z",
    }

    # Querying list by session and location returns both records
    with mock.patch("backend.main.list_measurements", return_value=[row_t1, row_t2]):
        resp = client.get("/measurements?session_id=sess_dup_coords&floor=Floor%201&x=5.0&y=5.0")
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) == 2
        assert records[0]["id"] == 501
        assert records[1]["id"] == 502
        assert records[0]["rssi_dbm"] == -40
        assert records[1]["rssi_dbm"] == -55
        assert records[0]["x"] == records[1]["x"] == 5.0
        assert records[0]["y"] == records[1]["y"] == 5.0

    # Each is individually accessible by its distinct ID
    with mock.patch("backend.main.get_measurement", side_effect=lambda measurement_id, **kwargs: row_t1 if measurement_id == 501 else (row_t2 if measurement_id == 502 else None)):
        resp1 = client.get("/measurements/501")
        assert resp1.status_code == 200
        assert resp1.json()["id"] == 501
        assert resp1.json()["rssi_dbm"] == -40

        resp2 = client.get("/measurements/502")
        assert resp2.status_code == 200
        assert resp2.json()["id"] == 502
        assert resp2.json()["rssi_dbm"] == -55
