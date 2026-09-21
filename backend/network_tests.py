"""
backend/network_tests.py
Network Performance Measurement Module for Milestone 3.

Provides hardware-independent measurement abstractions for:
1. Latency (Round-Trip Time in milliseconds across configurable probes)
2. Packet Loss (Calculated from probe failure percentage)
3. Application-Layer Throughput (Configurable HTTP/socket streaming rate in Mbps)

Note on Metrics Distinction:
- RSSI (dBm) and PHY link rates (Mbps) in `wifi_windows.py` represent Wi-Fi radio metrics.
- Latency, packet loss, and throughput represent end-to-end Network Performance metrics
  affected by network congestion, routing, server distance, and AP load in addition to RF conditions.
"""

from __future__ import annotations

import os
import re
import statistics
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
import urllib.request
import urllib.error


# ----------------------------------------------------------------------
# Data Structures
# ----------------------------------------------------------------------

@dataclass
class LatencyProbe:
    """Represents the result of an individual latency probe."""
    probe_index: int
    success: bool
    rtt_ms: Optional[float] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LatencySummary:
    """Summary statistics across all probes in a test run."""
    min_ms: Optional[float] = None
    avg_ms: Optional[float] = None
    max_ms: Optional[float] = None
    median_ms: Optional[float] = None
    successful_probes: int = 0
    total_probes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PacketLossResult:
    """Calculated packet loss statistics for a test run."""
    sent_probes: int
    received_probes: int
    lost_probes: int
    loss_percent: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ThroughputResult:
    """
    Application-layer throughput measurement result.

    Note: This measures end-to-end application transfer rate (Goodput),
    distinct from the raw Wi-Fi link speed reported by the wireless adapter.
    """
    throughput_mbps: Optional[float] = None
    bytes_transferred: int = 0
    duration_seconds: float = 0.0
    target_url: Optional[str] = None
    status: str = "DEFERRED"  # 'COMPLETED', 'DEFERRED', 'NOT_CONFIGURED', 'FAILED'
    is_application_layer: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkPerformanceResult:
    """Aggregated network performance dataset for a survey location/run."""
    target_host: str
    timestamp: str
    latency: LatencySummary
    packet_loss: PacketLossResult
    probes: List[LatencyProbe]
    throughput: ThroughputResult
    is_successful: bool
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_host": self.target_host,
            "timestamp": self.timestamp,
            "latency": self.latency.to_dict(),
            "packet_loss": self.packet_loss.to_dict(),
            "probes": [p.to_dict() for p in self.probes],
            "throughput": self.throughput.to_dict(),
            "is_successful": self.is_successful,
            "error_message": self.error_message,
        }


# ----------------------------------------------------------------------
# Configuration Helpers
# ----------------------------------------------------------------------

def parse_env_file(filepath: Path) -> Dict[str, str]:
    """Simple parser for .env files without external dependencies."""
    env_vars: Dict[str, str] = {}
    if not filepath.is_file():
        return env_vars
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                if "=" in line_str:
                    key, val = line_str.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    if key:
                        env_vars[key] = val
    except Exception:
        pass
    return env_vars


def get_config_value(key: str, default: Any, val_type: type = str) -> Any:
    """Retrieve config from OS environment or project .env with type conversion."""
    val = os.environ.get(key)
    if val is None:
        # Check project root .env
        root_env = Path(__file__).resolve().parent.parent / ".env"
        parsed = parse_env_file(root_env)
        val = parsed.get(key)

    if val is None or val == "":
        return default

    try:
        if val_type == int:
            return int(val)
        elif val_type == float:
            return float(val)
        elif val_type == bool:
            return str(val).lower() in ("true", "1", "yes")
        return str(val)
    except (ValueError, TypeError):
        return default


# ----------------------------------------------------------------------
# Probe Parser & Latency / Loss Calculation
# ----------------------------------------------------------------------

def parse_ping_output(output: str) -> tuple[bool, Optional[float], Optional[str]]:
    """
    Parse the standard output of Windows ping.exe to determine probe success and RTT.

    Handles localized strings, sub-millisecond responses ('<1ms'), and timeout/unreachable errors.
    """
    if not output:
        return False, None, "No output from ping command"

    for line in output.splitlines():
        line_str = line.strip()

        # Match time=Xms or time<1ms
        match = re.search(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", line_str, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            # If line specifies time<1ms, record as 0.5ms precision
            if "time<" in line_str.lower() and val <= 1.0:
                val = 0.5
            return True, val, None

        if "<1ms" in line_str.lower():
            return True, 0.5, None

        # Check explicit error conditions
        if "timed out" in line_str.lower() or "request timed out" in line_str.lower():
            return False, None, "Request timed out"
        if "unreachable" in line_str.lower():
            return False, None, "Destination host unreachable"
        if "could not find host" in line_str.lower():
            return False, None, "Host resolution failed"
        if "general failure" in line_str.lower():
            return False, None, "General network failure"
        if "transmit failed" in line_str.lower():
            return False, None, "Transmit failed"

    return False, None, "No response or unrecognized ICMP output"


def execute_single_probe(
    target_host: str,
    timeout_seconds: float = 2.0,
    probe_index: int = 1,
) -> LatencyProbe:
    """
    Execute a single ICMP echo probe using Windows ping utility.

    Returns:
        LatencyProbe instance with status, rtt_ms, and error if applicable.
    """
    if not target_host or not target_host.strip():
        return LatencyProbe(
            probe_index=probe_index,
            success=False,
            error_message="Invalid target host: empty target",
        )

    clean_target = target_host.strip()
    timeout_ms = max(100, int(timeout_seconds * 1000))
    cmd = ["ping", "-n", "1", "-w", str(timeout_ms), clean_target]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds + 3.0,
        )
        combined_output = (proc.stdout or "") + (proc.stderr or "")
        success, rtt, err = parse_ping_output(combined_output)
        return LatencyProbe(
            probe_index=probe_index,
            success=success,
            rtt_ms=rtt,
            error_message=err if not success else None,
        )
    except subprocess.TimeoutExpired:
        return LatencyProbe(
            probe_index=probe_index,
            success=False,
            error_message=f"Probe execution timed out after {timeout_seconds}s",
        )
    except Exception as exc:
        return LatencyProbe(
            probe_index=probe_index,
            success=False,
            error_message=f"Subprocess error: {str(exc)}",
        )


def calculate_latency_summary(probes: List[LatencyProbe]) -> LatencySummary:
    """Calculate min, avg, max, and median latency from a list of probe results."""
    total = len(probes)
    successful_rtts = [p.rtt_ms for p in probes if p.success and p.rtt_ms is not None]
    success_count = len(successful_rtts)

    if success_count == 0:
        return LatencySummary(
            min_ms=None,
            avg_ms=None,
            max_ms=None,
            median_ms=None,
            successful_probes=0,
            total_probes=total,
        )

    min_val = round(min(successful_rtts), 2)
    avg_val = round(sum(successful_rtts) / success_count, 2)
    max_val = round(max(successful_rtts), 2)
    med_val = round(float(statistics.median(successful_rtts)), 2)

    return LatencySummary(
        min_ms=min_val,
        avg_ms=avg_val,
        max_ms=max_val,
        median_ms=med_val,
        successful_probes=success_count,
        total_probes=total,
    )


def calculate_packet_loss(probes: List[LatencyProbe]) -> PacketLossResult:
    """
    Calculate packet loss percentage based on probe success/failure.

    Formula: (lost_probes / total_probes) * 100.0
    """
    total = len(probes)
    if total == 0:
        return PacketLossResult(
            sent_probes=0,
            received_probes=0,
            lost_probes=0,
            loss_percent=0.0,
        )

    received = sum(1 for p in probes if p.success and p.rtt_ms is not None)
    lost = total - received
    loss_pct = round((lost / total) * 100.0, 2)

    return PacketLossResult(
        sent_probes=total,
        received_probes=received,
        lost_probes=lost,
        loss_percent=loss_pct,
    )


# ----------------------------------------------------------------------
# Throughput Measurement
# ----------------------------------------------------------------------

def measure_throughput(
    target_url: Optional[str] = None,
    timeout_seconds: float = 5.0,
    chunk_size: int = 65536,
) -> ThroughputResult:
    """
    Perform a controlled HTTP streaming throughput test.

    If target_url is None or empty, returns a structured DEFERRED / NOT_CONFIGURED status.
    If target_url is supplied, streams data chunks, measures byte count and duration via
    high-resolution timer, and computes application-layer transfer rate in Mbps.

    Formula: (total_bytes * 8) / (duration_seconds * 1,000,000)
    """
    if not target_url or not target_url.strip():
        return ThroughputResult(
            throughput_mbps=None,
            bytes_transferred=0,
            duration_seconds=0.0,
            target_url=None,
            status="NOT_CONFIGURED",
            is_application_layer=True,
            error_message="No throughput target URL configured. Dedicated survey test server required.",
        )

    clean_url = target_url.strip()
    total_bytes = 0
    start_time = time.perf_counter()
    duration = 0.0

    try:
        req = urllib.request.Request(
            clean_url,
            headers={"User-Agent": "WiFiPerformanceMapper/0.1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            while True:
                elapsed = time.perf_counter() - start_time
                if elapsed >= timeout_seconds:
                    break
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)

        end_time = time.perf_counter()
        duration = max(end_time - start_time, 0.0001)

        if total_bytes == 0:
            return ThroughputResult(
                throughput_mbps=0.0,
                bytes_transferred=0,
                duration_seconds=round(duration, 3),
                target_url=clean_url,
                status="FAILED",
                is_application_layer=True,
                error_message="No data transferred from endpoint",
            )

        mbps = round((total_bytes * 8.0) / (duration * 1_000_000.0), 2)
        return ThroughputResult(
            throughput_mbps=mbps,
            bytes_transferred=total_bytes,
            duration_seconds=round(duration, 3),
            target_url=clean_url,
            status="COMPLETED",
            is_application_layer=True,
            error_message=None,
        )
    except urllib.error.URLError as url_err:
        duration = round(time.perf_counter() - start_time, 3)
        return ThroughputResult(
            throughput_mbps=None,
            bytes_transferred=total_bytes,
            duration_seconds=duration,
            target_url=clean_url,
            status="FAILED",
            is_application_layer=True,
            error_message=f"HTTP/Network error: {str(url_err.reason)}",
        )
    except Exception as exc:
        duration = round(time.perf_counter() - start_time, 3)
        return ThroughputResult(
            throughput_mbps=None,
            bytes_transferred=total_bytes,
            duration_seconds=duration,
            target_url=clean_url,
            status="FAILED",
            is_application_layer=True,
            error_message=f"Throughput measurement error: {str(exc)}",
        )


# ----------------------------------------------------------------------
# Public Aggregated Measurement API
# ----------------------------------------------------------------------

def measure_network_performance(
    target_host: Optional[str] = None,
    probe_count: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
    throughput_url: Optional[str] = None,
) -> NetworkPerformanceResult:
    """
    Execute a full network performance measurement pass (latency, packet loss, throughput).

    Parameters:
        target_host: Hostname or IP to ping (defaults to TEST_TARGET from config, or '8.8.8.8').
        probe_count: Number of latency probes (defaults to LATENCY_PROBE_COUNT or 4).
        timeout_seconds: Per-probe timeout in seconds (defaults to LATENCY_TIMEOUT_SECONDS or 2.0).
        throughput_url: Optional URL for throughput benchmark (defaults to THROUGHPUT_TARGET_URL).

    Returns:
        NetworkPerformanceResult object.
    """
    if target_host is None:
        target_host = get_config_value("TEST_TARGET", default="8.8.8.8", val_type=str)
    if probe_count is None:
        probe_count = get_config_value("LATENCY_PROBE_COUNT", default=4, val_type=int)
    if timeout_seconds is None:
        timeout_seconds = get_config_value("LATENCY_TIMEOUT_SECONDS", default=2.0, val_type=float)
    if throughput_url is None:
        throughput_url = get_config_value("THROUGHPUT_TARGET_URL", default=None, val_type=str)

    probe_count = max(1, min(probe_count, 50))
    timeout_seconds = max(0.1, min(timeout_seconds, 30.0))
    ts = datetime.now(timezone.utc).isoformat()

    probes: List[LatencyProbe] = []
    for i in range(1, probe_count + 1):
        probe = execute_single_probe(
            target_host=target_host,
            timeout_seconds=timeout_seconds,
            probe_index=i,
        )
        probes.append(probe)

    lat_summary = calculate_latency_summary(probes)
    loss_result = calculate_packet_loss(probes)
    tp_result = measure_throughput(target_url=throughput_url)

    is_success = lat_summary.successful_probes > 0

    err_msg = None
    if not is_success:
        first_err = next((p.error_message for p in probes if p.error_message), "All probes failed")
        err_msg = f"Network measurement failed for target {target_host}: {first_err}"

    return NetworkPerformanceResult(
        target_host=target_host,
        timestamp=ts,
        latency=lat_summary,
        packet_loss=loss_result,
        probes=probes,
        throughput=tp_result,
        is_successful=is_success,
        error_message=err_msg,
    )
