"""
tests/test_measurement.py
Comprehensive Unit Test Suite for Milestone 6 Measurement Engine.

Tests:
1. Median calculation helper (odd, even, negatives, None values, all-None, single value, zero preservation).
2. Five-sample collection loop and configurable sample counts.
3. Fresh invocation of underlying measurement layers and timestamp independence.
4. Location input validation and preservation.
5. Explicit Sample Status (COMPLETE, PARTIAL, FAILED) across 5/5, 4/5, 3/5, 1/5, 0/5.
6. Packet-loss aggregation as the median of sample-level percentages ([0,0,0,100,100] -> 0%, etc.).
7. BSSID roaming tracking (bssid_changed, bssids_observed, per-sample raw retention).
8. Failure semantics (Wi-Fi failure, latency failure, 100% packet loss, throughput failure, complete failure).
9. Exception isolation and canonical serialization.
"""

from datetime import datetime, timezone
import math
import pytest
from typing import List, Optional

from backend.wifi_windows import WifiConnectionInfo
from backend.network_tests import (
    NetworkPerformanceResult,
    LatencySummary,
    LatencyProbe,
    PacketLossResult,
    ThroughputResult,
)
from backend.measurement import (
    calculate_median,
    SingleSampleResult,
    AggregatedMeasurement,
    collect_single_sample,
    aggregate_samples,
    measure_grid_point,
)


# ----------------------------------------------------------------------
# Fixtures & Helper Factories
# ----------------------------------------------------------------------

def make_dummy_wifi_info(
    is_connected: bool = True,
    ssid: str = "Test-Campus-WiFi",
    bssid: str = "00:11:22:33:44:55",
    signal_percent: int = 85,
    rssi_dbm: Optional[int] = -55,
    channel: int = 6,
    frequency_mhz: float = 2437.0,
    radio_type: str = "802.11n (HT)",
    rx_rate: float = 144.0,
    tx_rate: float = 144.0,
    adapter_desc: str = "Test Wireless Adapter",
    driver_ver: str = "1.0.0",
) -> WifiConnectionInfo:
    return WifiConnectionInfo(
        is_connected=is_connected,
        ssid=ssid if is_connected else None,
        bssid=bssid if is_connected else None,
        signal_percent=signal_percent if is_connected else None,
        rssi_dbm=rssi_dbm if is_connected else None,
        channel=channel if is_connected else None,
        frequency_mhz=frequency_mhz if is_connected else None,
        radio_type=radio_type if is_connected else None,
        receive_rate_mbps=rx_rate if is_connected else None,
        transmit_rate_mbps=tx_rate if is_connected else None,
        adapter_description=adapter_desc,
        driver_version=driver_ver,
        timestamp=datetime.now(timezone.utc).isoformat(),
        raw_source="test_mock",
    )


def make_dummy_net_result(
    is_successful: bool = True,
    avg_ms: Optional[float] = 12.5,
    median_ms: Optional[float] = 12.0,
    loss_percent: float = 0.0,
    throughput_mbps: Optional[float] = 45.0,
    tp_status: str = "COMPLETED",
) -> NetworkPerformanceResult:
    return NetworkPerformanceResult(
        target_host="8.8.8.8",
        timestamp=datetime.now(timezone.utc).isoformat(),
        latency=LatencySummary(
            min_ms=10.0 if is_successful else None,
            avg_ms=avg_ms if is_successful else None,
            max_ms=15.0 if is_successful else None,
            median_ms=median_ms if is_successful else None,
            successful_probes=4 if is_successful else 0,
            total_probes=4,
        ),
        packet_loss=PacketLossResult(
            sent_probes=4,
            received_probes=4 if is_successful and loss_percent == 0.0 else (0 if loss_percent == 100.0 else 2),
            lost_probes=0 if is_successful and loss_percent == 0.0 else (4 if loss_percent == 100.0 else 2),
            loss_percent=loss_percent,
        ),
        probes=[],
        throughput=ThroughputResult(
            throughput_mbps=throughput_mbps,
            bytes_transferred=1048576 if throughput_mbps else 0,
            duration_seconds=1.0,
            target_url="http://test/stream",
            status=tp_status,
            is_application_layer=True,
            error_message=None if tp_status == "COMPLETED" else "Throughput unavailable",
        ),
        is_successful=is_successful,
        error_message=None if is_successful else "All probes failed",
    )


# ----------------------------------------------------------------------
# 1. Median Calculation Helper Tests
# ----------------------------------------------------------------------

def test_calculate_median_odd_numbers():
    """Verify exact median with odd number of values (specification test vector)."""
    # Test vector from specification: [-70, -65, -68, -72, -66] -> sorted [-72, -70, -68, -66, -65] -> median = -68.0
    values = [-70, -65, -68, -72, -66]
    med = calculate_median(values)
    assert med == -68.0


def test_calculate_median_even_numbers():
    """Verify median with even number of values calculates mean of middle two elements."""
    # [-70, -60, -80, -90] -> sorted [-90, -80, -70, -60] -> (-80 + -70) / 2 = -75.0
    values = [-70, -60, -80, -90]
    med = calculate_median(values)
    assert med == -75.0

    # Float values: [10.5, 12.5, 14.5, 16.5] -> (12.5 + 14.5) / 2 = 13.5
    assert calculate_median([10.5, 12.5, 14.5, 16.5]) == 13.5


def test_calculate_median_with_none_values():
    """Verify None values are excluded without treating None as zero."""
    # [-70, None, -65, None, -68] -> valid: [-70, -65, -68] -> sorted [-70, -68, -65] -> -68.0
    values = [-70, None, -65, None, -68]
    med = calculate_median(values)
    assert med == -68.0


def test_calculate_median_all_none():
    """Verify calculating median on all-None sequence returns None, never 0."""
    assert calculate_median([None, None, None]) is None
    assert calculate_median([]) is None


def test_calculate_median_single_value():
    """Verify calculating median on a single valid value returns that exact value."""
    assert calculate_median([42.5]) == 42.5
    assert calculate_median([None, -55, None]) == -55.0


def test_calculate_median_preserves_zero():
    """Verify that 0.0 is preserved as a valid numeric measurement and not discarded."""
    assert calculate_median([0.0, 0.0, 0.0]) == 0.0
    assert calculate_median([0.0, None, 10.0]) == 5.0


def test_calculate_median_handles_nan_and_inf():
    """Verify that NaN and inf values are safely filtered out."""
    assert calculate_median([float("nan"), -70, float("inf"), -60, -65]) == -65.0


# ----------------------------------------------------------------------
# 2. Location & Argument Validation Tests
# ----------------------------------------------------------------------

def test_measure_grid_point_location_validation():
    """Verify location coordinates and sample_count input validation."""
    # Invalid empty floor
    with pytest.raises(ValueError, match="floor must be a non-empty string"):
        measure_grid_point(floor="", x=10.0, y=20.0)

    with pytest.raises(ValueError, match="floor must be a non-empty string"):
        measure_grid_point(floor="   ", x=10.0, y=20.0)

    # Invalid non-numeric coordinates
    with pytest.raises(ValueError, match="x and y coordinates must be valid numbers"):
        measure_grid_point(floor="Floor-1", x="invalid", y=20.0)

    with pytest.raises(ValueError, match="x and y coordinates must be finite numbers"):
        measure_grid_point(floor="Floor-1", x=float("nan"), y=20.0)

    with pytest.raises(ValueError, match="x and y coordinates must be finite numbers"):
        measure_grid_point(floor="Floor-1", x=10.0, y=float("inf"))

    # Invalid sample_count
    with pytest.raises(ValueError, match="sample_count must be at least 1"):
        measure_grid_point(floor="Floor-1", x=10.0, y=20.0, sample_count=0)

    with pytest.raises(ValueError, match="sample_count must be at least 1"):
        measure_grid_point(floor="Floor-1", x=10.0, y=20.0, sample_count=-3)


# ----------------------------------------------------------------------
# 3. Five-Sample Default and Fresh Sample Invocation Tests
# ----------------------------------------------------------------------

def test_measure_grid_point_collects_exactly_5_samples_by_default():
    """Verify engine collects exactly 5 independent samples by default."""
    call_counts = {"wifi": 0, "net": 0}

    def mock_wifi():
        call_counts["wifi"] += 1
        return make_dummy_wifi_info(rssi_dbm=-60 - call_counts["wifi"])

    def mock_net():
        call_counts["net"] += 1
        return make_dummy_net_result(avg_ms=10.0 + call_counts["net"])

    result = measure_grid_point(
        floor="Floor-2",
        x=15.5,
        y=25.0,
        wifi_provider=mock_wifi,
        net_provider=mock_net,
    )

    assert result.sample_count == 5
    assert len(result.raw_samples) == 5
    assert call_counts["wifi"] == 5
    assert call_counts["net"] == 5
    assert result.valid_samples_count == 5
    assert result.status == "COMPLETE"
    assert result.is_successful is True
    assert result.floor == "Floor-2"
    assert result.x == 15.5
    assert result.y == 25.0


def test_measure_grid_point_configurable_sample_count():
    """Verify engine supports configurable sample count (e.g. 3 samples)."""
    call_counts = {"wifi": 0, "net": 0}

    def mock_wifi():
        call_counts["wifi"] += 1
        return make_dummy_wifi_info()

    def mock_net():
        call_counts["net"] += 1
        return make_dummy_net_result()

    result = measure_grid_point(
        floor="Floor-1",
        x=5.0,
        y=10.0,
        sample_count=3,
        wifi_provider=mock_wifi,
        net_provider=mock_net,
    )

    assert result.sample_count == 3
    assert len(result.raw_samples) == 3
    assert call_counts["wifi"] == 3
    assert call_counts["net"] == 3
    assert result.status == "COMPLETE"


def test_measure_grid_point_sample_independence_and_timestamps():
    """Verify that each sample result has its own sample index and independent timestamps."""
    wifi_results = [
        make_dummy_wifi_info(rssi_dbm=-70),
        make_dummy_wifi_info(rssi_dbm=-65),
        make_dummy_wifi_info(rssi_dbm=-68),
        make_dummy_wifi_info(rssi_dbm=-72),
        make_dummy_wifi_info(rssi_dbm=-66),
    ]
    net_results = [
        make_dummy_net_result(median_ms=10.0),
        make_dummy_net_result(median_ms=12.0),
        make_dummy_net_result(median_ms=14.0),
        make_dummy_net_result(median_ms=16.0),
        make_dummy_net_result(median_ms=18.0),
    ]

    wifi_idx = 0
    net_idx = 0

    def mock_wifi():
        nonlocal wifi_idx
        res = wifi_results[wifi_idx]
        wifi_idx += 1
        return res

    def mock_net():
        nonlocal net_idx
        res = net_results[net_idx]
        net_idx += 1
        return res

    result = measure_grid_point(
        floor="Floor-Ground",
        x=0.0,
        y=0.0,
        sample_count=5,
        wifi_provider=mock_wifi,
        net_provider=mock_net,
    )

    # Check sample indices
    for i, s in enumerate(result.raw_samples, start=1):
        assert s.sample_index == i
        assert isinstance(s.timestamp, str)
        assert s.wifi_info is not None
        assert s.network_result is not None

    # Check median results
    # RSSI: [-70, -65, -68, -72, -66] -> sorted: [-72, -70, -68, -66, -65] -> -68
    assert result.rssi_dbm == -68
    # Latency: [10, 12, 14, 16, 18] -> 14.0
    assert result.latency_ms == 14.0


# ----------------------------------------------------------------------
# 4. Locked Decision A: Explicit Sample Status Tests
# ----------------------------------------------------------------------

def test_sample_status_complete_5_of_5():
    """Verify 5 requested / 5 valid yields status='COMPLETE' and is_successful=True."""
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60),
            network_result=make_dummy_net_result(median_ms=15.0),
            is_successful=True,
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.sample_count == 5
    assert agg.valid_samples_count == 5
    assert agg.status == "COMPLETE"
    assert agg.is_successful is True
    assert agg.error_message is None


def test_sample_status_partial_4_of_5():
    """Verify 5 requested / 4 valid yields status='PARTIAL' and is_successful=True."""
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60) if i <= 4 else None,
            network_result=make_dummy_net_result(median_ms=15.0) if i <= 4 else None,
            is_successful=(i <= 4),
            error_message="Probe failed" if i == 5 else None,
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.sample_count == 5
    assert agg.valid_samples_count == 4
    assert agg.status == "PARTIAL"
    assert agg.is_successful is True
    assert "4 of 5 samples valid" in agg.error_message


def test_sample_status_partial_3_of_5():
    """Verify 5 requested / 3 valid yields status='PARTIAL' and is_successful=True."""
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60) if i <= 3 else None,
            network_result=make_dummy_net_result(median_ms=15.0) if i <= 3 else None,
            is_successful=(i <= 3),
            error_message="Probe failed" if i > 3 else None,
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.sample_count == 5
    assert agg.valid_samples_count == 3
    assert agg.status == "PARTIAL"
    assert agg.is_successful is True
    assert "3 of 5 samples valid" in agg.error_message


def test_sample_status_partial_1_of_5():
    """Verify 5 requested / 1 valid yields status='PARTIAL' and is_successful=True."""
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60) if i == 1 else None,
            network_result=make_dummy_net_result(median_ms=15.0) if i == 1 else None,
            is_successful=(i == 1),
            error_message="Probe failed" if i > 1 else None,
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.sample_count == 5
    assert agg.valid_samples_count == 1
    assert agg.status == "PARTIAL"
    assert agg.is_successful is True
    assert "1 of 5 samples valid" in agg.error_message


def test_sample_status_failed_0_of_5():
    """Verify 5 requested / 0 valid yields status='FAILED' and is_successful=False."""
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=None,
            network_result=None,
            is_successful=False,
            error_message="Fatal driver timeout",
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.sample_count == 5
    assert agg.valid_samples_count == 0
    assert agg.status == "FAILED"
    assert agg.is_successful is False
    assert agg.error_message == "All measurement samples failed or yielded no valid metrics"


# ----------------------------------------------------------------------
# 5. Locked Decision B: Packet Loss Aggregation Tests
# ----------------------------------------------------------------------

def test_packet_loss_aggregation_locked_vector_0_0_0_100_100():
    """
    Verify locked decision test vector: [0, 0, 0, 100, 100] -> median 0.0%.
    Ensures sample-level percentage median is used rather than pooled probe average.
    """
    loss_percentages = [0.0, 0.0, 0.0, 100.0, 100.0]
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60),
            network_result=make_dummy_net_result(loss_percent=loss_percentages[i - 1]),
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.packet_loss_percent == 0.0


def test_packet_loss_aggregation_gradient_0_25_50_75_100():
    """Verify median across gradient [0, 25, 50, 75, 100] yields exact middle 50.0%."""
    loss_percentages = [0.0, 25.0, 50.0, 75.0, 100.0]
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60),
            network_result=make_dummy_net_result(loss_percent=loss_percentages[i - 1]),
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.packet_loss_percent == 50.0


def test_packet_loss_aggregation_mixed_missing_values():
    """Verify missing packet-loss samples are ignored while preserving valid 0.0% and 50.0%."""
    samples = [
        SingleSampleResult(
            sample_index=1,
            timestamp="2026-09-21T10:00:01Z",
            wifi_info=make_dummy_wifi_info(),
            network_result=make_dummy_net_result(loss_percent=0.0),
        ),
        SingleSampleResult(
            sample_index=2,
            timestamp="2026-09-21T10:00:02Z",
            wifi_info=make_dummy_wifi_info(),
            network_result=None,  # missing net
        ),
        SingleSampleResult(
            sample_index=3,
            timestamp="2026-09-21T10:00:03Z",
            wifi_info=make_dummy_wifi_info(),
            network_result=make_dummy_net_result(loss_percent=25.0),
        ),
        SingleSampleResult(
            sample_index=4,
            timestamp="2026-09-21T10:00:04Z",
            wifi_info=make_dummy_wifi_info(),
            network_result=None,  # missing net
        ),
        SingleSampleResult(
            sample_index=5,
            timestamp="2026-09-21T10:00:05Z",
            wifi_info=make_dummy_wifi_info(),
            network_result=make_dummy_net_result(loss_percent=50.0),
        ),
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    # Valid loss: [0.0, 25.0, 50.0] -> median 25.0%
    assert agg.packet_loss_percent == 25.0


def test_packet_loss_preserves_legitimate_0_and_100():
    """Verify 0.0% and 100.0% packet loss are never converted to None."""
    # 0.0%
    samples_0 = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(),
            network_result=make_dummy_net_result(loss_percent=0.0),
        )
        for i in range(1, 6)
    ]
    agg_0 = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples_0, sample_count=5)
    assert agg_0.packet_loss_percent == 0.0

    # 100.0%
    samples_100 = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(),
            network_result=make_dummy_net_result(loss_percent=100.0),
        )
        for i in range(1, 6)
    ]
    agg_100 = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples_100, sample_count=5)
    assert agg_100.packet_loss_percent == 100.0


# ----------------------------------------------------------------------
# 6. Locked Decision C: BSSID Roaming Tests
# ----------------------------------------------------------------------

def test_bssid_roaming_same_bssid_all_samples():
    """Verify [A, A, A, A, A] yields bssid_changed=False and bssids_observed=['A']."""
    bssid_a = "00:11:22:33:44:aa"
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a),
            network_result=make_dummy_net_result(),
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.bssid == bssid_a
    assert agg.bssid_changed is False
    assert agg.bssids_observed == [bssid_a]


def test_bssid_roaming_changed_bssid_two_distinct():
    """Verify [A, A, B, B, B] yields bssid_changed=True and bssids_observed=['A', 'B']."""
    bssid_a = "00:11:22:33:44:aa"
    bssid_b = "00:11:22:33:44:bb"
    bssids = [bssid_a, bssid_a, bssid_b, bssid_b, bssid_b]

    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(bssid=bssids[i - 1]),
            network_result=make_dummy_net_result(),
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.bssid == bssid_b  # Latest valid sample
    assert agg.bssid_changed is True
    assert agg.bssids_observed == [bssid_a, bssid_b]

    # Verify each raw sample preserves its individual BSSID
    assert agg.raw_samples[0].wifi_info.bssid == bssid_a
    assert agg.raw_samples[1].wifi_info.bssid == bssid_a
    assert agg.raw_samples[2].wifi_info.bssid == bssid_b
    assert agg.raw_samples[3].wifi_info.bssid == bssid_b
    assert agg.raw_samples[4].wifi_info.bssid == bssid_b


def test_bssid_roaming_same_bssid_with_missing_sample():
    """Verify [A, A, None, A, A] ignores None and yields bssid_changed=False."""
    bssid_a = "00:11:22:33:44:aa"
    samples = [
        SingleSampleResult(
            sample_index=1,
            timestamp="2026-09-21T10:00:01Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=2,
            timestamp="2026-09-21T10:00:02Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=3,
            timestamp="2026-09-21T10:00:03Z",
            wifi_info=None,  # Disconnected/missing sample
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=4,
            timestamp="2026-09-21T10:00:04Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=5,
            timestamp="2026-09-21T10:00:05Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a),
            network_result=make_dummy_net_result(),
        ),
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.bssid == bssid_a
    assert agg.bssid_changed is False
    assert agg.bssids_observed == [bssid_a]


def test_bssid_roaming_changed_bssid_with_missing_sample():
    """Verify [A, A, B, None, B] yields bssid_changed=True and bssids_observed=['A', 'B']."""
    bssid_a = "00:11:22:33:44:aa"
    bssid_b = "00:11:22:33:44:bb"
    samples = [
        SingleSampleResult(
            sample_index=1,
            timestamp="2026-09-21T10:00:01Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=2,
            timestamp="2026-09-21T10:00:02Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=3,
            timestamp="2026-09-21T10:00:03Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_b),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=4,
            timestamp="2026-09-21T10:00:04Z",
            wifi_info=None,
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=5,
            timestamp="2026-09-21T10:00:05Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_b),
            network_result=make_dummy_net_result(),
        ),
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    assert agg.bssid == bssid_b
    assert agg.bssid_changed is True
    assert agg.bssids_observed == [bssid_a, bssid_b]


def test_rssi_aggregation_during_roaming():
    """
    Verify RSSI aggregation during BSSID roaming:
    BSSID A -> -55 dBm, -57 dBm
    BSSID B -> -65 dBm, -67 dBm, -66 dBm
    Aggregate RSSI median = -65 dBm, with bssid_changed=True.
    """
    bssid_a = "00:11:22:33:44:aa"
    bssid_b = "00:11:22:33:44:bb"
    samples = [
        SingleSampleResult(
            sample_index=1,
            timestamp="2026-09-21T10:00:01Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a, rssi_dbm=-55),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=2,
            timestamp="2026-09-21T10:00:02Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_a, rssi_dbm=-57),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=3,
            timestamp="2026-09-21T10:00:03Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_b, rssi_dbm=-65),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=4,
            timestamp="2026-09-21T10:00:04Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_b, rssi_dbm=-67),
            network_result=make_dummy_net_result(),
        ),
        SingleSampleResult(
            sample_index=5,
            timestamp="2026-09-21T10:00:05Z",
            wifi_info=make_dummy_wifi_info(bssid=bssid_b, rssi_dbm=-66),
            network_result=make_dummy_net_result(),
        ),
    ]
    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)
    # Sorted RSSI: [-67, -66, -65, -57, -55] -> median is -65
    assert agg.rssi_dbm == -65
    assert agg.bssid_changed is True
    assert agg.bssids_observed == [bssid_a, bssid_b]
    assert agg.bssid == bssid_b


# ----------------------------------------------------------------------
# 7. Complete Failure & Exception Isolation Tests
# ----------------------------------------------------------------------

def test_failure_wifi_disconnected_does_not_fabricate_rssi():
    """Verify that when Wi-Fi is disconnected, RSSI/SSID are None and not fabricated."""
    disconnected_wifi = WifiConnectionInfo(
        is_connected=False,
        timestamp="2026-09-21T10:00:00Z",
        raw_source="test_mock",
    )

    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=disconnected_wifi,
            network_result=make_dummy_net_result(median_ms=15.0),
        )
        for i in range(1, 6)
    ]

    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)

    assert agg.rssi_dbm is None
    assert agg.signal_percent is None
    assert agg.ssid is None
    assert agg.bssid is None
    assert agg.bssid_changed is False
    assert agg.bssids_observed == []
    assert agg.latency_ms == 15.0
    assert agg.valid_samples_count == 5
    assert agg.status == "COMPLETE"


def test_failure_network_latency_failure_does_not_convert_to_zero_ms():
    """Verify latency probe failure results in None, never 0.0 ms."""
    failed_net = make_dummy_net_result(is_successful=False, avg_ms=None, median_ms=None, loss_percent=100.0)

    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-65),
            network_result=failed_net,
        )
        for i in range(1, 6)
    ]

    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)

    assert agg.rssi_dbm == -65
    assert agg.latency_ms is None  # Must remain None, not 0.0
    assert agg.packet_loss_percent == 100.0  # Must preserve 100%


def test_failure_throughput_unavailable_preserves_none():
    """Verify throughput failure/unconfigured status preserves throughput_mbps as None."""
    net_no_tp = make_dummy_net_result(throughput_mbps=None, tp_status="NOT_CONFIGURED")

    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60),
            network_result=net_no_tp,
        )
        for i in range(1, 6)
    ]

    agg = aggregate_samples(floor="Floor-1", x=1.0, y=1.0, samples=samples, sample_count=5)

    assert agg.rssi_dbm == -60
    assert agg.throughput_mbps is None


def test_failure_all_samples_fail():
    """Verify that when all 5 samples fail, AggregatedMeasurement reports FAILED cleanly."""
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=None,
            network_result=None,
            is_successful=False,
            error_message="Network unreachable",
        )
        for i in range(1, 6)
    ]

    agg = aggregate_samples(floor="Floor-1", x=0.0, y=0.0, samples=samples, sample_count=5)

    assert agg.sample_count == 5
    assert agg.valid_samples_count == 0
    assert agg.status == "FAILED"
    assert agg.is_successful is False
    assert agg.rssi_dbm is None
    assert agg.latency_ms is None
    assert agg.bssid_changed is False
    assert agg.bssids_observed == []
    assert agg.error_message == "All measurement samples failed or yielded no valid metrics"


def test_collect_single_sample_exception_isolation():
    """Verify collect_single_sample isolates exceptions thrown by providers."""
    def failing_wifi():
        raise RuntimeError("Hardware failure in wlanapi")

    def failing_net():
        raise ConnectionResetError("Socket reset")

    sample = collect_single_sample(
        sample_index=1,
        wifi_provider=failing_wifi,
        net_provider=failing_net,
    )

    assert sample.sample_index == 1
    assert sample.is_successful is False
    assert "Hardware failure" in sample.error_message
    assert "Socket reset" in sample.error_message
    assert sample.wifi_info is None
    assert sample.network_result is None


def test_aggregated_measurement_serialization_to_dict():
    """Verify to_dict serialization contains all required fields including status and roaming."""
    samples = [
        SingleSampleResult(
            sample_index=i,
            timestamp=f"2026-09-21T10:00:0{i}Z",
            wifi_info=make_dummy_wifi_info(rssi_dbm=-60),
            network_result=make_dummy_net_result(loss_percent=0.0),
        )
        for i in range(1, 6)
    ]
    agg = aggregate_samples(floor="Floor-1", x=2.5, y=3.5, samples=samples, sample_count=5)
    d = agg.to_dict()

    assert d["floor"] == "Floor-1"
    assert d["x"] == 2.5
    assert d["y"] == 3.5
    assert d["sample_count"] == 5
    assert d["valid_samples_count"] == 5
    assert d["status"] == "COMPLETE"
    assert d["is_successful"] is True
    assert d["bssid_changed"] is False
    assert isinstance(d["bssids_observed"], list)
    assert len(d["raw_samples"]) == 5
