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
