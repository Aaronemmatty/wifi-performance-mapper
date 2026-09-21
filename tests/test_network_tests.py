"""
tests/test_network_tests.py
Deterministic Unit Tests for backend/network_tests.py.
"""

import os
import sys
import unittest.mock as mock
from datetime import datetime
import pytest

from backend.network_tests import (
    LatencyProbe,
    LatencySummary,
    PacketLossResult,
    ThroughputResult,
    NetworkPerformanceResult,
    parse_ping_output,
    execute_single_probe,
    calculate_latency_summary,
    calculate_packet_loss,
    measure_throughput,
    measure_network_performance,
    get_config_value,
    parse_env_file,
)


# ----------------------------------------------------------------------
# Ping Output Parser Tests
# ----------------------------------------------------------------------

def test_parse_ping_output_standard_success():
    """Test standard Windows ping success line."""
    output = "Reply from 8.8.8.8: bytes=32 time=14ms TTL=118"
    success, rtt, err = parse_ping_output(output)
    assert success is True
    assert rtt == 14.0
    assert err is None


def test_parse_ping_output_sub_millisecond():
    """Test sub-millisecond Windows ping output (time<1ms)."""
    output = "Reply from 127.0.0.1: bytes=32 time<1ms TTL=128"
    success, rtt, err = parse_ping_output(output)
    assert success is True
    assert rtt == 0.5
    assert err is None


def test_parse_ping_output_decimal():
    """Test decimal milliseconds output if present."""
    output = "Reply from 192.168.1.1: bytes=32 time=2.45ms TTL=64"
    success, rtt, err = parse_ping_output(output)
    assert success is True
    assert rtt == 2.45
    assert err is None


def test_parse_ping_output_timeout():
    """Test request timed out response."""
    output = "Pinging 192.0.2.1 with 32 bytes of data:\nRequest timed out.\n"
    success, rtt, err = parse_ping_output(output)
    assert success is False
    assert rtt is None
    assert "timed out" in err.lower()


def test_parse_ping_output_unreachable():
    """Test destination host unreachable response."""
    output = "Reply from 192.168.1.1: Destination host unreachable."
    success, rtt, err = parse_ping_output(output)
    assert success is False
    assert rtt is None
    assert "unreachable" in err.lower()


def test_parse_ping_output_unresolved_host():
    """Test invalid domain name output."""
    output = "Ping request could not find host nonexistent.domain.invalid."
    success, rtt, err = parse_ping_output(output)
    assert success is False
    assert rtt is None
    assert "resolution failed" in err.lower() or "not find host" in err.lower()


def test_parse_ping_output_empty():
    """Test empty string handling."""
    success, rtt, err = parse_ping_output("")
    assert success is False
    assert rtt is None
    assert err is not None


# ----------------------------------------------------------------------
# Latency Summary Calculation Tests
# ----------------------------------------------------------------------

def test_calculate_latency_summary_all_success():
    """Test summary statistics with all successful probes."""
    probes = [
        LatencyProbe(probe_index=1, success=True, rtt_ms=10.0),
        LatencyProbe(probe_index=2, success=True, rtt_ms=20.0),
        LatencyProbe(probe_index=3, success=True, rtt_ms=15.0),
        LatencyProbe(probe_index=4, success=True, rtt_ms=25.0),
    ]
    summary = calculate_latency_summary(probes)
    assert summary.total_probes == 4
    assert summary.successful_probes == 4
    assert summary.min_ms == 10.0
    assert summary.max_ms == 25.0
    assert summary.avg_ms == 17.5
    assert summary.median_ms == 17.5  # median of [10, 15, 20, 25] is (15+20)/2 = 17.5


def test_calculate_latency_summary_mixed_results():
    """Test summary calculation when some probes fail."""
    probes = [
        LatencyProbe(probe_index=1, success=True, rtt_ms=12.0),
        LatencyProbe(probe_index=2, success=False, rtt_ms=None, error_message="Timeout"),
        LatencyProbe(probe_index=3, success=True, rtt_ms=18.0),
        LatencyProbe(probe_index=4, success=False, rtt_ms=None, error_message="Timeout"),
    ]
    summary = calculate_latency_summary(probes)
    assert summary.total_probes == 4
    assert summary.successful_probes == 2
    assert summary.min_ms == 12.0
    assert summary.max_ms == 18.0
    assert summary.avg_ms == 15.0
    assert summary.median_ms == 15.0


def test_calculate_latency_summary_all_failed():
    """Test summary calculation when all probes fail (never fabricate zero)."""
    probes = [
        LatencyProbe(probe_index=1, success=False, rtt_ms=None, error_message="Timeout"),
        LatencyProbe(probe_index=2, success=False, rtt_ms=None, error_message="Timeout"),
    ]
    summary = calculate_latency_summary(probes)
    assert summary.total_probes == 2
    assert summary.successful_probes == 0
    assert summary.min_ms is None
    assert summary.avg_ms is None
    assert summary.max_ms is None
    assert summary.median_ms is None


# ----------------------------------------------------------------------
# Packet Loss Calculation Tests
# ----------------------------------------------------------------------

def test_packet_loss_zero_percent():
    """Test 0% packet loss."""
    probes = [
        LatencyProbe(probe_index=i, success=True, rtt_ms=5.0)
        for i in range(1, 5)
    ]
    loss = calculate_packet_loss(probes)
    assert loss.sent_probes == 4
    assert loss.received_probes == 4
    assert loss.lost_probes == 0
    assert loss.loss_percent == 0.0


def test_packet_loss_partial():
    """Test partial packet loss (25% and 50%)."""
    probes_25 = [
        LatencyProbe(probe_index=1, success=True, rtt_ms=5.0),
        LatencyProbe(probe_index=2, success=True, rtt_ms=6.0),
        LatencyProbe(probe_index=3, success=True, rtt_ms=5.5),
        LatencyProbe(probe_index=4, success=False, rtt_ms=None),
    ]
    loss_25 = calculate_packet_loss(probes_25)
    assert loss_25.lost_probes == 1
    assert loss_25.loss_percent == 25.0

    probes_50 = [
        LatencyProbe(probe_index=1, success=True, rtt_ms=5.0),
        LatencyProbe(probe_index=2, success=False, rtt_ms=None),
    ]
    loss_50 = calculate_packet_loss(probes_50)
    assert loss_50.lost_probes == 1
    assert loss_50.loss_percent == 50.0


def test_packet_loss_hundred_percent():
    """Test 100% packet loss."""
    probes = [
        LatencyProbe(probe_index=1, success=False, rtt_ms=None),
        LatencyProbe(probe_index=2, success=False, rtt_ms=None),
    ]
    loss = calculate_packet_loss(probes)
    assert loss.sent_probes == 2
    assert loss.received_probes == 0
    assert loss.lost_probes == 2
    assert loss.loss_percent == 100.0


def test_packet_loss_empty_list():
    """Test empty probe list handling."""
    loss = calculate_packet_loss([])
    assert loss.sent_probes == 0
    assert loss.loss_percent == 0.0


# ----------------------------------------------------------------------
# Throughput Measurement Tests
# ----------------------------------------------------------------------

def test_measure_throughput_not_configured():
    """Verify unconfigured throughput target returns clean deferred status."""
    res = measure_throughput(target_url=None)
    assert res.status == "NOT_CONFIGURED"
    assert res.throughput_mbps is None
    assert res.bytes_transferred == 0
    assert res.is_application_layer is True
    assert "No throughput target URL configured" in res.error_message


def test_measure_throughput_calculation_mocked():
    """Test deterministic throughput calculation with mocked streaming data."""
    # Transfer 2,500,000 bytes in 2.0 seconds:
    # Bits = 2,500,000 * 8 = 20,000,000 bits
    # Mbps = 20,000,000 / (2.0 * 1,000,000) = 10.0 Mbps
    chunk_1 = b"X" * 1_250_000
    chunk_2 = b"X" * 1_250_000
    chunks = [chunk_1, chunk_2, b""]

    class MockResponse:
        def __init__(self):
            self.chunks_iter = iter(chunks)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            try:
                return next(self.chunks_iter)
            except StopIteration:
                return b""

    # start_time (100.0), loop iter 1 (100.5), loop iter 2 (101.0), loop exit (101.5), end_time (102.0)
    time_seq = [100.0, 100.5, 101.0, 101.5, 102.0, 102.0]
    with mock.patch("urllib.request.urlopen", return_value=MockResponse()):
        with mock.patch("time.perf_counter", side_effect=time_seq):
            res = measure_throughput(target_url="http://testserver.local/payload", timeout_seconds=5.0)
            assert res.status == "COMPLETED"
            assert res.bytes_transferred == 2_500_000
            assert res.duration_seconds == 2.0
            # (2,500,000 * 8) / (2.0 * 1,000,000) = 10.0 Mbps
            assert res.throughput_mbps == 10.0


def test_measure_throughput_network_failure_handled():
    """Test throughput handles network/HTTP error gracefully without crashing."""
    import urllib.error
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        res = measure_throughput(target_url="http://unreachable.test.server/file")
        assert res.status == "FAILED"
        assert res.throughput_mbps is None
        assert "Connection refused" in res.error_message


# ----------------------------------------------------------------------
# Configuration & End-to-End Aggregation Tests
# ----------------------------------------------------------------------

def test_get_config_value_defaults():
    """Test configuration retrieval with type casting and fallbacks."""
    val_int = get_config_value("NONEXISTENT_INT_VAR", default=10, val_type=int)
    assert val_int == 10

    val_float = get_config_value("NONEXISTENT_FLOAT_VAR", default=2.5, val_type=float)
    assert val_float == 2.5


def test_execute_single_probe_invalid_target():
    """Test single probe handles empty target safely."""
    probe = execute_single_probe(target_host="", probe_index=1)
    assert probe.success is False
    assert probe.rtt_ms is None
    assert "invalid target" in probe.error_message.lower()


def test_measure_network_performance_aggregated_mocked():
    """Test full measurement pipeline with mocked probe responses."""
    mock_probe_1 = LatencyProbe(probe_index=1, success=True, rtt_ms=10.0)
    mock_probe_2 = LatencyProbe(probe_index=2, success=True, rtt_ms=12.0)

    with mock.patch("backend.network_tests.execute_single_probe", side_effect=[mock_probe_1, mock_probe_2]):
        result = measure_network_performance(target_host="192.168.1.1", probe_count=2, timeout_seconds=1.0)
        assert isinstance(result, NetworkPerformanceResult)
        assert result.target_host == "192.168.1.1"
        assert result.is_successful is True
        assert result.latency.avg_ms == 11.0
        assert result.packet_loss.loss_percent == 0.0
        assert len(result.probes) == 2
        assert result.throughput.status == "NOT_CONFIGURED"


# ----------------------------------------------------------------------
# Live Controlled Throughput Server Tests (Using Dynamic Ephemeral Port)
# ----------------------------------------------------------------------

def test_controlled_throughput_server_transfer_1mb():
    """Verify live HTTP transfer of exact 1 MB payload against local controlled server."""
    from scripts.throughput_server import run_in_thread
    server, thread = run_in_thread(host="127.0.0.1", port=0, default_payload_size=1048576)
    actual_port = server.server_address[1]

    try:
        url = f"http://127.0.0.1:{actual_port}/payload"
        result = measure_throughput(target_url=url, timeout_seconds=5.0)

        assert result.status == "COMPLETED"
        assert result.bytes_transferred == 1048576  # Exactly 1 MB received
        assert result.duration_seconds > 0.0
        assert result.throughput_mbps is not None
        assert result.throughput_mbps > 0.0
        assert result.is_application_layer is True
        assert result.error_message is None
    finally:
        server.shutdown()
        server.server_close()


def test_controlled_throughput_server_custom_size():
    """Verify live HTTP transfer with custom query size parameter (256 KB = 262,144 bytes)."""
    from scripts.throughput_server import run_in_thread
    server, thread = run_in_thread(host="127.0.0.1", port=0)
    actual_port = server.server_address[1]

    try:
        custom_bytes = 262144
        url = f"http://127.0.0.1:{actual_port}/payload?size={custom_bytes}"
        result = measure_throughput(target_url=url, timeout_seconds=5.0)

        assert result.status == "COMPLETED"
        assert result.bytes_transferred == custom_bytes
        assert result.duration_seconds > 0.0
        assert result.throughput_mbps > 0.0
    finally:
        server.shutdown()
        server.server_close()


def test_controlled_throughput_server_failure_stopped():
    """Verify client handles unreachable/closed server without fabricating throughput."""
    # Target closed port on localhost
    result = measure_throughput(target_url="http://127.0.0.1:59999/payload", timeout_seconds=1.0)
    assert result.status == "FAILED"
    assert result.throughput_mbps is None
    assert result.bytes_transferred == 0
    assert result.error_message is not None

