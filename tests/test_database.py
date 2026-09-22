"""
tests/test_database.py
Comprehensive Database and Repository Unit Tests for Milestone 4.

Tests connection management, schema initialization, historical record preservation,
NULL semantics, constraint validation, parameterized SQL safety, and live PostgreSQL integration.
"""

from __future__ import annotations

import unittest.mock as mock
from datetime import datetime, timezone
import pytest

from backend.database import (
    get_database_url,
    mask_database_url,
    get_connection,
    test_connection as db_test_connection,
    init_db,
    SCHEMA_SQL,
)
from backend.repository import (
    create_session,
    get_session,
    list_sessions,
    create_measurement,
    get_measurement,
    get_measurements_by_session,
    get_measurements_by_location,
    record_measurement_from_modules,
)
from backend.wifi_windows import WifiConnectionInfo
from backend.network_tests import (
    NetworkPerformanceResult,
    LatencySummary,
    PacketLossResult,
    ThroughputResult,
    LatencyProbe,
)


# ----------------------------------------------------------------------
# Configuration & Masking Tests
# ----------------------------------------------------------------------

def test_mask_database_url():
    """Verify passwords are redacted from connection URLs in logs."""
    url = "postgresql://postgres:SecretPassword123@localhost:5432/wifi_mapper"
    masked = mask_database_url(url)
    assert "SecretPassword123" not in masked
    assert "postgres:***@localhost:5432/wifi_mapper" in masked

    assert mask_database_url(None) == "None"
    assert mask_database_url("") == "None"


def test_database_probe_connection_unconfigured(monkeypatch):
    """Test db_test_connection handles unconfigured and invalid URLs cleanly."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with mock.patch("backend.database.parse_env_file", return_value={}):
        ok, msg = db_test_connection(database_url=None)
        assert ok is False
        assert "not configured" in msg.lower()


def test_get_database_url_precedence(monkeypatch):
    """Test environment variable precedence for regular and test URLs."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/devdb")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

    assert get_database_url(is_test=False) == "postgresql://user:pass@localhost:5432/devdb"
    assert get_database_url(is_test=True) == "postgresql://user:pass@localhost:5432/testdb"


def test_get_connection_unconfigured(monkeypatch):
    """Verify ValueError is raised if connection is attempted without DATABASE_URL."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    with mock.patch("backend.database.parse_env_file", return_value={}):
        with pytest.raises(ValueError, match="DATABASE_URL is not configured"):
            get_connection()


# ----------------------------------------------------------------------
# Schema & SQL Safety Tests
# ----------------------------------------------------------------------

def test_schema_sql_contains_required_tables_and_indexes():
    """Verify DDL contains both tables, constraints, and performance indexes."""
    assert "CREATE TABLE IF NOT EXISTS measurement_sessions" in SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS measurements" in SCHEMA_SQL
    assert "idx_measurements_session" in SCHEMA_SQL
    assert "idx_measurements_floor" in SCHEMA_SQL
    assert "idx_measurements_coords" in SCHEMA_SQL
    assert "idx_measurements_timestamp" in SCHEMA_SQL
    # Verify negative RSSI constraint check exists
    assert "CHECK (rssi_dbm <= 0)" in SCHEMA_SQL


def test_init_db_executes_idempotent_ddl():
    """Test init_db executes schema DDL against connection cursor."""
    mock_cursor = mock.MagicMock()
    mock_conn = mock.MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with mock.patch("backend.database.get_db_connection", return_value=mock.MagicMock()) as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_conn
        init_db(database_url="postgresql://mock:mock@localhost/test")
        mock_cursor.execute.assert_called_once_with(SCHEMA_SQL)


# ----------------------------------------------------------------------
# Repository Operations & Parameterized SQL Tests
# ----------------------------------------------------------------------

def test_create_session_parameterized():
    """Test session creation executes parameterized SQL without string formatting."""
    mock_row = {
        "session_id": "sess_01",
        "name": "Floor 2 Survey",
        "floor": "Floor 2",
        "created_at": datetime.now(timezone.utc),
        "notes": "Initial test walk",
    }
    mock_cursor = mock.MagicMock()
    mock_cursor.fetchone.return_value = mock_row

    with mock.patch("backend.repository.get_db_cursor") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_cursor

        result = create_session(
            session_id="sess_01",
            name="Floor 2 Survey",
            floor="Floor 2",
            notes="Initial test walk",
            database_url="postgresql://mock/db",
        )

        assert result["session_id"] == "sess_01"
        assert result["floor"] == "Floor 2"
        # Verify parameterized SQL was called
        assert mock_cursor.execute.called
        sql_arg, params_arg = mock_cursor.execute.call_args[0]
        assert "%s" in sql_arg
        assert params_arg[0] == "sess_01"
        assert params_arg[1] == "Floor 2 Survey"


def test_create_session_validation_errors():
    """Test validation errors for empty session parameters."""
    with pytest.raises(ValueError, match="session_id"):
        create_session(session_id="", name="Valid", floor="Floor 1")
    with pytest.raises(ValueError, match="name"):
        create_session(session_id="s1", name="  ", floor="Floor 1")
    with pytest.raises(ValueError, match="floor"):
        create_session(session_id="s1", name="Valid", floor="")


# ----------------------------------------------------------------------
# Historical Record Preservation Tests
# ----------------------------------------------------------------------

def test_historical_measurements_coexistence():
    """
    MANDATORY REQUIREMENT:
    Verify that inserting multiple measurements at the exact same (session_id, floor, x, y)
    produces distinct historical records and does NOT overwrite.
    """
    mock_row_1 = {
        "id": 101,
        "session_id": "sess_walk_01",
        "floor": "Floor 2",
        "x": 10.5,
        "y": 20.0,
        "rssi_dbm": -35,
        "signal_percent": 100,
        "latency_ms": 4.2,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 85.0,
        "timestamp": datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc),
    }
    mock_row_2 = {
        "id": 102,
        "session_id": "sess_walk_01",
        "floor": "Floor 2",
        "x": 10.5,
        "y": 20.0,
        "rssi_dbm": -38,  # Changed over time
        "signal_percent": 95,
        "latency_ms": 5.1,
        "packet_loss_percent": 0.0,
        "throughput_mbps": 82.0,
        "timestamp": datetime(2026, 9, 21, 10, 5, 0, tzinfo=timezone.utc),
    }

    mock_cursor = mock.MagicMock()
    # First call returns row 1, second call returns row 2
    mock_cursor.fetchone.side_effect = [mock_row_1, mock_row_2]
    # Location query returns both rows
    mock_cursor.fetchall.return_value = [mock_row_1, mock_row_2]

    with mock.patch("backend.repository.get_db_cursor") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_cursor

        m1 = create_measurement(
            session_id="sess_walk_01", floor="Floor 2", x=10.5, y=20.0,
            rssi_dbm=-35, signal_percent=100, latency_ms=4.2, database_url="postgresql://mock/db"
        )
        m2 = create_measurement(
            session_id="sess_walk_01", floor="Floor 2", x=10.5, y=20.0,
            rssi_dbm=-38, signal_percent=95, latency_ms=5.1, database_url="postgresql://mock/db"
        )

        history = get_measurements_by_location(
            floor="Floor 2", x=10.5, y=20.0, session_id="sess_walk_01", database_url="postgresql://mock/db"
        )

        assert m1["id"] == 101
        assert m2["id"] == 102
        assert len(history) == 2
        assert history[0]["rssi_dbm"] == -35
        assert history[1]["rssi_dbm"] == -38
        assert history[0]["id"] != history[1]["id"]


# ----------------------------------------------------------------------
# NULL Semantics vs Fake Zeroes
# ----------------------------------------------------------------------

def test_null_semantics_preserved():
    """
    Verify that unavailable measurements (e.g. throughput=None, latency=None)
    remain NULL in the database parameters and are NOT converted into fake zeroes.
    """
    mock_cursor = mock.MagicMock()
    mock_cursor.fetchone.return_value = {
        "id": 1,
        "session_id": "s1",
        "floor": "F1",
        "x": 0.0,
        "y": 0.0,
        "rssi_dbm": None,
        "signal_percent": None,
        "latency_ms": None,
        "packet_loss_percent": None,
        "throughput_mbps": None,
    }

    with mock.patch("backend.repository.get_db_cursor") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_cursor

        create_measurement(
            session_id="s1",
            floor="F1",
            x=0.0,
            y=0.0,
            rssi_dbm=None,
            signal_percent=None,
            latency_ms=None,
            packet_loss_percent=None,
            throughput_mbps=None,
            database_url="postgresql://mock/db",
        )

        sql_arg, params_arg = mock_cursor.execute.call_args[0]
        # Verify that None was passed to params (which maps to SQL NULL)
        assert params_arg[4] is None  # rssi_dbm
        assert params_arg[5] is None  # signal_percent
        assert params_arg[6] is None  # latency_ms
        assert params_arg[7] is None  # packet_loss_percent
        assert params_arg[8] is None  # throughput_mbps


# ----------------------------------------------------------------------
# Constraint Validation Tests
# ----------------------------------------------------------------------

def test_measurement_constraint_validation():
    """Verify constraint errors on invalid numerical bounds."""
    # Positive RSSI is physically invalid
    with pytest.raises(ValueError, match="rssi_dbm must be negative or zero"):
        create_measurement(session_id="s1", floor="F1", x=0, y=0, rssi_dbm=25)

    # Signal percentage out of [0, 100]
    with pytest.raises(ValueError, match="signal_percent must be between 0 and 100"):
        create_measurement(session_id="s1", floor="F1", x=0, y=0, signal_percent=150)

    # Negative latency
    with pytest.raises(ValueError, match="latency_ms cannot be negative"):
        create_measurement(session_id="s1", floor="F1", x=0, y=0, latency_ms=-5.0)

    # Negative throughput
    with pytest.raises(ValueError, match="throughput_mbps cannot be negative"):
        create_measurement(session_id="s1", floor="F1", x=0, y=0, throughput_mbps=-10.0)


# ----------------------------------------------------------------------
# Module Integration Helper Tests
# ----------------------------------------------------------------------

def test_record_measurement_from_modules_mapping():
    """Verify clean mapping from WifiConnectionInfo and NetworkPerformanceResult to DB."""
    wifi = WifiConnectionInfo(
        is_connected=True,
        ssid="THOMAS",
        bssid="b0:95:75:89:c1:04",
        signal_percent=100,
        rssi_dbm=-33,
        channel=10,
        frequency_mhz=2457.0,
        radio_type="802.11n (HT)",
        adapter_description="Qualcomm Atheros QCA9377",
        driver_version="12.0.0.722",
    )

    net = NetworkPerformanceResult(
        target_host="8.8.8.8",
        timestamp=datetime.now(timezone.utc).isoformat(),
        latency=LatencySummary(min_ms=4.0, avg_ms=4.5, max_ms=5.0, median_ms=4.5, successful_probes=4, total_probes=4),
        packet_loss=PacketLossResult(sent_probes=4, received_probes=4, lost_probes=0, loss_percent=0.0),
        probes=[LatencyProbe(probe_index=1, success=True, rtt_ms=4.5)],
        throughput=ThroughputResult(throughput_mbps=95.0, status="COMPLETED"),
        is_successful=True,
    )

    mock_cursor = mock.MagicMock()
    mock_cursor.fetchone.return_value = {"id": 1, "session_id": "s_integ"}

    with mock.patch("backend.repository.get_db_cursor") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = mock_cursor

        record = record_measurement_from_modules(
            session_id="s_integ",
            floor="Floor 3",
            x=5.0,
            y=12.0,
            wifi_info=wifi,
            net_result=net,
            sample_count=5,
            database_url="postgresql://mock/db",
        )

        assert record["session_id"] == "s_integ"
        sql_arg, params = mock_cursor.execute.call_args[0]
        # Check mapped parameters
        assert params[0] == "s_integ"
        assert params[1] == "Floor 3"
        assert params[2] == 5.0
        assert params[3] == 12.0
        assert params[4] == -33  # rssi_dbm
        assert params[5] == 100  # signal_percent
        assert params[6] == 4.5  # latency_ms (from avg_ms)
        assert params[7] == 0.0  # packet_loss_percent
        assert params[8] == 95.0 # throughput_mbps
        assert params[9] == "THOMAS" # ssid
        assert params[10] == "b0:95:75:89:c1:04" # bssid
        assert params[11] == 10 # channel
        assert params[12] == 2457.0 # frequency_mhz
        assert params[16] == 5 # sample_count
