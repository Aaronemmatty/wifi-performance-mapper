"""
tests/test_measurement_service.py
Unit Test Suite for Milestone 7 Measurement Service Integration.

Tests:
1. COMPLETE (5/5) measurement collection and persistence.
2. PARTIAL (3/5) measurement collection and persistence.
3. FAILED (0/5) measurement rejection (persisted=False, db_record=None, no fake row).
4. NULL metric preservation (None values remain None).
5. Historical append-only behavior (repeated measurements at same coordinate coexist).
6. Session ID validation.
7. BSSID roaming integration (persisting valid medians across AP transitions).
8. Packet loss median propagation to repository.
9. Serialization to dictionary.
"""

from datetime import datetime, timezone
import pytest
from typing import Dict, Any, List, Optional

from backend.wifi_windows import WifiConnectionInfo
from backend.network_tests import (
    NetworkPerformanceResult,
    LatencySummary,
    PacketLossResult,
    ThroughputResult,
)
from backend.measurement import SingleSampleResult, AggregatedMeasurement
from backend.measurement_service import (
    MeasurementServiceResult,
    execute_and_persist_measurement,
)


# ----------------------------------------------------------------------
# Mock Helpers & Test Fixtures
# ----------------------------------------------------------------------

def make_test_wifi(
    is_connected: bool = True,
    bssid: str = "00:11:22:33:44:55",
    rssi_dbm: Optional[int] = -55,
    signal_percent: int = 80,
    ssid: str = "Campus-WiFi",
) -> WifiConnectionInfo:
    return WifiConnectionInfo(
        is_connected=is_connected,
        ssid=ssid if is_connected else None,
        bssid=bssid if is_connected else None,
        signal_percent=signal_percent if is_connected else None,
        rssi_dbm=rssi_dbm if is_connected else None,
        channel=6 if is_connected else None,
        frequency_mhz=2437.0 if is_connected else None,
        radio_type="802.11n (HT)" if is_connected else None,
        adapter_description="Test Adapter",
        driver_version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
        raw_source="mock",
    )


def make_test_net(
    is_successful: bool = True,
    median_ms: Optional[float] = 15.0,
    loss_percent: float = 0.0,
    throughput_mbps: Optional[float] = 50.0,
) -> NetworkPerformanceResult:
    return NetworkPerformanceResult(
        target_host="8.8.8.8",
        timestamp=datetime.now(timezone.utc).isoformat(),
        latency=LatencySummary(
            min_ms=10.0 if is_successful else None,
            avg_ms=median_ms if is_successful else None,
            max_ms=20.0 if is_successful else None,
            median_ms=median_ms if is_successful else None,
            successful_probes=4 if is_successful else 0,
            total_probes=4,
        ),
        packet_loss=PacketLossResult(
            sent_probes=4,
            received_probes=4 if is_successful and loss_percent == 0.0 else 0,
            lost_probes=0 if is_successful and loss_percent == 0.0 else 4,
            loss_percent=loss_percent,
        ),
        probes=[],
        throughput=ThroughputResult(
            throughput_mbps=throughput_mbps,
            status="COMPLETED" if throughput_mbps else "NOT_CONFIGURED",
        ),
        is_successful=is_successful,
    )


# ----------------------------------------------------------------------
# 1. Complete, Partial, and Failed Lifecycle Tests
# ----------------------------------------------------------------------

def test_execute_and_persist_complete_5_of_5():
    """Verify 5/5 valid samples results in status='COMPLETE', persisted=True, and calls repository."""
    recorded_params = []

    def mock_repo_create(**kwargs):
        recorded_params.append(kwargs)
        return {"id": 101, **kwargs, "created_at": datetime.now(timezone.utc)}

    wifi_mock = lambda: make_test_wifi(rssi_dbm=-60)
    net_mock = lambda: make_test_net(median_ms=12.0, loss_percent=0.0, throughput_mbps=80.0)

    res = execute_and_persist_measurement(
        session_id="session-001",
        floor="Floor-1",
        x=10.0,
        y=20.0,
        sample_count=5,
        wifi_provider=wifi_mock,
        net_provider=net_mock,
        repository_create_fn=mock_repo_create,
    )

    assert res.session_id == "session-001"
    assert res.floor == "Floor-1"
    assert res.x == 10.0
    assert res.y == 20.0
    assert res.status == "COMPLETE"
    assert res.is_successful is True
    assert res.persisted is True
    assert res.db_record is not None
    assert res.db_record["id"] == 101
    assert res.db_record["rssi_dbm"] == -60
    assert res.db_record["latency_ms"] == 12.0
    assert res.db_record["throughput_mbps"] == 80.0
    assert res.db_record["sample_count"] == 5
    assert len(recorded_params) == 1


def test_execute_and_persist_partial_3_of_5():
    """Verify 3/5 valid samples results in status='PARTIAL', persisted=True, and valid medians."""
    recorded_params = []

    def mock_repo_create(**kwargs):
        recorded_params.append(kwargs)
        return {"id": 102, **kwargs, "created_at": datetime.now(timezone.utc)}

    call_count = {"wifi": 0, "net": 0}

    def mock_wifi():
        call_count["wifi"] += 1
        if call_count["wifi"] <= 3:
            return make_test_wifi(rssi_dbm=-60 - call_count["wifi"])
        return make_test_wifi(is_connected=False)

    def mock_net():
        call_count["net"] += 1
        if call_count["net"] <= 3:
            return make_test_net(median_ms=10.0 + call_count["net"])
        return make_test_net(is_successful=False, median_ms=None, loss_percent=100.0)

    res = execute_and_persist_measurement(
        session_id="session-002",
        floor="Floor-2",
        x=5.0,
        y=15.0,
        sample_count=5,
        wifi_provider=mock_wifi,
        net_provider=mock_net,
        repository_create_fn=mock_repo_create,
    )

    assert res.status == "PARTIAL"
    assert res.is_successful is True
    assert res.persisted is True
    assert res.aggregated.valid_samples_count == 3
    assert res.db_record is not None
    assert res.db_record["id"] == 102
    # RSSI across 3 valid: [-61, -62, -63] -> median -62
    assert res.db_record["rssi_dbm"] == -62
    # Latency across 3 valid: [11.0, 12.0, 13.0] -> median 12.0
    assert res.db_record["latency_ms"] == 12.0
    assert "3 of 5 samples valid" in res.error_message
    assert len(recorded_params) == 1


def test_execute_and_persist_failed_0_of_5():
    """Verify 0/5 valid samples results in status='FAILED', persisted=False, and NO repository call."""
    repo_called = False

    def mock_repo_create(**kwargs):
        nonlocal repo_called
        repo_called = True
        return {"id": 999, **kwargs}

    wifi_mock = lambda: make_test_wifi(is_connected=False)
    net_mock = lambda: make_test_net(is_successful=False, median_ms=None, loss_percent=100.0)

    res = execute_and_persist_measurement(
        session_id="session-003",
        floor="Floor-1",
        x=0.0,
        y=0.0,
        sample_count=5,
        wifi_provider=wifi_mock,
        net_provider=net_mock,
        repository_create_fn=mock_repo_create,
    )

    assert res.status == "FAILED"
    assert res.is_successful is False
    assert res.persisted is False
    assert res.db_record is None
    assert repo_called is False
    assert res.aggregated.valid_samples_count == 0


# ----------------------------------------------------------------------
# 2. NULL Preservation Tests
# ----------------------------------------------------------------------

def test_execute_and_persist_preserves_null_metrics():
    """Verify that unmeasured/missing metrics remain None when passed to repository."""
    recorded_params = []

    def mock_repo_create(**kwargs):
        recorded_params.append(kwargs)
        return {"id": 103, **kwargs}

    # Wi-Fi connected but no throughput server configured
    wifi_mock = lambda: make_test_wifi(rssi_dbm=-55)
    net_mock = lambda: make_test_net(median_ms=20.0, throughput_mbps=None)

    res = execute_and_persist_measurement(
        session_id="session-004",
        floor="Floor-1",
        x=1.0,
        y=2.0,
        sample_count=3,
        wifi_provider=wifi_mock,
        net_provider=net_mock,
        repository_create_fn=mock_repo_create,
    )

    assert res.persisted is True
    assert res.db_record["throughput_mbps"] is None
    assert recorded_params[0]["throughput_mbps"] is None


# ----------------------------------------------------------------------
# 3. Historical Append-Only Tests
# ----------------------------------------------------------------------

def test_execute_and_persist_historical_append_only():
    """Verify repeated measurements at the same (session_id, floor, x, y) create separate records."""
    records_stored = []

    def mock_repo_create(**kwargs):
        record_id = len(records_stored) + 1
        rec = {"id": record_id, **kwargs}
        records_stored.append(rec)
        return rec

    wifi_mock1 = lambda: make_test_wifi(rssi_dbm=-50)
    wifi_mock2 = lambda: make_test_wifi(rssi_dbm=-65)
    net_mock = lambda: make_test_net()

    res1 = execute_and_persist_measurement(
        session_id="session-walk",
        floor="Floor-Main",
        x=10.0,
        y=10.0,
        wifi_provider=wifi_mock1,
        net_provider=net_mock,
        repository_create_fn=mock_repo_create,
    )

    res2 = execute_and_persist_measurement(
        session_id="session-walk",
        floor="Floor-Main",
        x=10.0,
        y=10.0,
        wifi_provider=wifi_mock2,
        net_provider=net_mock,
        repository_create_fn=mock_repo_create,
    )

    assert res1.persisted is True
    assert res2.persisted is True
    assert len(records_stored) == 2
    assert records_stored[0]["id"] == 1
    assert records_stored[0]["rssi_dbm"] == -50
    assert records_stored[1]["id"] == 2
    assert records_stored[1]["rssi_dbm"] == -65


# ----------------------------------------------------------------------
# 4. Input & Session Validation Tests
# ----------------------------------------------------------------------

def test_execute_and_persist_validation_errors():
    """Verify validation errors for empty session_id or floor."""
    with pytest.raises(ValueError, match="session_id must be a non-empty string"):
        execute_and_persist_measurement(session_id="", floor="Floor-1", x=0.0, y=0.0)

    with pytest.raises(ValueError, match="floor must be a non-empty string"):
        execute_and_persist_measurement(session_id="session-1", floor="", x=0.0, y=0.0)


# ----------------------------------------------------------------------
# 5. BSSID Roaming Integration Tests
# ----------------------------------------------------------------------

def test_execute_and_persist_bssid_roaming_integration():
    """Verify BSSID roaming persists canonical latest BSSID and median RSSI."""
    recorded_params = []

    def mock_repo_create(**kwargs):
        recorded_params.append(kwargs)
        return {"id": 104, **kwargs}

    bssid_a = "00:11:22:33:44:aa"
    bssid_b = "00:11:22:33:44:bb"
    samples_wifi = [
        make_test_wifi(bssid=bssid_a, rssi_dbm=-55),
        make_test_wifi(bssid=bssid_a, rssi_dbm=-57),
        make_test_wifi(bssid=bssid_b, rssi_dbm=-65),
        make_test_wifi(bssid=bssid_b, rssi_dbm=-67),
        make_test_wifi(bssid=bssid_b, rssi_dbm=-66),
    ]
    idx = 0

    def mock_wifi():
        nonlocal idx
        w = samples_wifi[idx]
        idx += 1
        return w

    res = execute_and_persist_measurement(
        session_id="session-roam",
        floor="Floor-1",
        x=2.0,
        y=3.0,
        sample_count=5,
        wifi_provider=mock_wifi,
        net_provider=lambda: make_test_net(),
        repository_create_fn=mock_repo_create,
    )

    assert res.persisted is True
    assert res.aggregated.bssid_changed is True
    assert res.aggregated.bssids_observed == [bssid_a, bssid_b]
    assert res.db_record["bssid"] == bssid_b
    assert res.db_record["rssi_dbm"] == -65


# ----------------------------------------------------------------------
# 6. Packet Loss Median Integration Tests
# ----------------------------------------------------------------------

def test_execute_and_persist_packet_loss_median_vector():
    """Verify [0, 0, 0, 100, 100] packet loss vector passes median 0.0% to repository."""
    recorded_params = []

    def mock_repo_create(**kwargs):
        recorded_params.append(kwargs)
        return {"id": 105, **kwargs}

    loss_vals = [0.0, 0.0, 0.0, 100.0, 100.0]
    idx = 0

    def mock_net():
        nonlocal idx
        n = make_test_net(loss_percent=loss_vals[idx])
        idx += 1
        return n

    res = execute_and_persist_measurement(
        session_id="session-loss",
        floor="Floor-1",
        x=4.0,
        y=5.0,
        sample_count=5,
        wifi_provider=lambda: make_test_wifi(),
        net_provider=mock_net,
        repository_create_fn=mock_repo_create,
    )

    assert res.persisted is True
    assert res.db_record["packet_loss_percent"] == 0.0
    assert recorded_params[0]["packet_loss_percent"] == 0.0


# ----------------------------------------------------------------------
# 7. Serialization Tests
# ----------------------------------------------------------------------

def test_measurement_service_result_to_dict():
    """Verify to_dict serialization of MeasurementServiceResult."""
    wifi_mock = lambda: make_test_wifi(rssi_dbm=-60)
    net_mock = lambda: make_test_net()

    res = execute_and_persist_measurement(
        session_id="session-dict",
        floor="Floor-1",
        x=1.0,
        y=1.0,
        sample_count=3,
        wifi_provider=wifi_mock,
        net_provider=net_mock,
        repository_create_fn=lambda **kwargs: {"id": 106, **kwargs},
    )

    d = res.to_dict()
    assert d["session_id"] == "session-dict"
    assert d["floor"] == "Floor-1"
    assert d["status"] == "COMPLETE"
    assert d["persisted"] is True
    assert isinstance(d["aggregated"], dict)
    assert d["db_record"]["id"] == 106
