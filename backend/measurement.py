"""
backend/measurement.py
Measurement Engine Orchestration Module for Milestone 6.

Responsible for performing multi-sample (default: 5 samples) Wi-Fi and network
performance measurements at a specified physical grid coordinate (floor, x, y),
calculating deterministic medians across valid samples, and returning a canonical
aggregated measurement structure.

Decoupled from raw SQL persistence, HTTP routing, and hardware-specific APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import math
import time
from typing import Optional, List, Dict, Any, Callable, Sequence, Union

from backend.wifi_windows import WifiConnectionInfo, get_current_wifi_info
from backend.network_tests import (
    NetworkPerformanceResult,
    measure_network_performance,
)


# ----------------------------------------------------------------------
# Mathematical & Aggregation Helpers
# ----------------------------------------------------------------------

def calculate_median(values: Sequence[Optional[Union[int, float]]]) -> Optional[float]:
    """
    Calculate the mathematical median of a sequence of numeric values, ignoring None.

    Mathematical Rules:
    - None and non-finite (NaN/inf) entries are filtered out.
    - If no valid numeric values remain, returns None (never converts None to 0).
    - If valid count is odd: returns the exact middle element of the sorted list.
    - If valid count is even: returns the arithmetic mean of the two middle elements.
    - Preserves negative values correctly (e.g. RSSI dBm: [-70, -65, -68, -72, -66] -> -68.0).
    - Preserves 0.0 as a valid measurement distinct from None.
    """
    valid: List[float] = []
    for v in values:
        if v is not None:
            try:
                fv = float(v)
                if not math.isnan(fv) and not math.isinf(fv):
                    valid.append(fv)
            except (ValueError, TypeError):
                continue

    if not valid:
        return None

    valid.sort()
    n = len(valid)
    mid = n // 2
    if n % 2 == 1:
        return valid[mid]
    else:
        return (valid[mid - 1] + valid[mid]) / 2.0


# ----------------------------------------------------------------------
# Data Models
# ----------------------------------------------------------------------

@dataclass
class SingleSampleResult:
    """
    Raw data collected during a single measurement sample.

    Captures the independent Wi-Fi state and network performance result
    along with its individual timestamp and execution status.
    """
    sample_index: int
    timestamp: str
    wifi_info: Optional[WifiConnectionInfo] = None
    network_result: Optional[NetworkPerformanceResult] = None
    is_successful: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_index": self.sample_index,
            "timestamp": self.timestamp,
            "wifi_info": self.wifi_info.to_dict() if self.wifi_info else None,
            "network_result": self.network_result.to_dict() if self.network_result else None,
            "is_successful": self.is_successful,
            "error_message": self.error_message,
        }


@dataclass
class AggregatedMeasurement:
    """
    Canonical measurement result representing an aggregated multi-sample survey point.

    Contains spatial coordinates, sample execution status (COMPLETE / PARTIAL / FAILED),
    aggregated medians for RF and network metrics, Wi-Fi roaming indicators,
    latest valid Wi-Fi context metadata, and the full sequence of raw samples.
    """
    floor: str
    x: float
    y: float
    sample_count: int
    valid_samples_count: int
    timestamp: str

    # Execution Status: 'COMPLETE', 'PARTIAL', 'FAILED'
    status: str = "COMPLETE"
    is_successful: bool = True

    # Aggregated Medians (None if unmeasured/unavailable)
    rssi_dbm: Optional[int] = None
    signal_percent: Optional[int] = None
    latency_ms: Optional[float] = None
    packet_loss_percent: Optional[float] = None
    throughput_mbps: Optional[float] = None

    # Wi-Fi Context Metadata & Roaming indicators
    ssid: Optional[str] = None
    bssid: Optional[str] = None
    bssid_changed: bool = False
    bssids_observed: List[str] = field(default_factory=list)
    channel: Optional[int] = None
    frequency_mhz: Optional[float] = None
    radio_type: Optional[str] = None
    receive_rate_mbps: Optional[float] = None
    transmit_rate_mbps: Optional[float] = None
    adapter_name: Optional[str] = None
    driver_version: Optional[str] = None

    # Raw collection data & Error tracking
    raw_samples: List[SingleSampleResult] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "floor": self.floor,
            "x": self.x,
            "y": self.y,
            "sample_count": self.sample_count,
            "valid_samples_count": self.valid_samples_count,
            "timestamp": self.timestamp,
            "status": self.status,
            "is_successful": self.is_successful,
            "rssi_dbm": self.rssi_dbm,
            "signal_percent": self.signal_percent,
            "latency_ms": self.latency_ms,
            "packet_loss_percent": self.packet_loss_percent,
            "throughput_mbps": self.throughput_mbps,
            "ssid": self.ssid,
            "bssid": self.bssid,
            "bssid_changed": self.bssid_changed,
            "bssids_observed": list(self.bssids_observed),
            "channel": self.channel,
            "frequency_mhz": self.frequency_mhz,
            "radio_type": self.radio_type,
            "receive_rate_mbps": self.receive_rate_mbps,
            "transmit_rate_mbps": self.transmit_rate_mbps,
            "adapter_name": self.adapter_name,
            "driver_version": self.driver_version,
            "raw_samples": [s.to_dict() for s in self.raw_samples],
            "error_message": self.error_message,
        }


# ----------------------------------------------------------------------
# Measurement Orchestration Engine
# ----------------------------------------------------------------------

def collect_single_sample(
    sample_index: int,
    wifi_provider: Optional[Callable[[], WifiConnectionInfo]] = None,
    net_provider: Optional[Callable[..., NetworkPerformanceResult]] = None,
    net_kwargs: Optional[Dict[str, Any]] = None,
) -> SingleSampleResult:
    """
    Collect an independent single measurement sample across Wi-Fi and network layers.

    Catches and isolates layer exceptions so one failing sample does not crash the entire run.
    """
    ts = datetime.now(timezone.utc).isoformat()
    wifi_fn = wifi_provider or get_current_wifi_info
    net_fn = net_provider or measure_network_performance
    net_args = net_kwargs or {}

    wifi_info: Optional[WifiConnectionInfo] = None
    net_result: Optional[NetworkPerformanceResult] = None
    errors: List[str] = []

    # 1. Collect Wi-Fi characteristics
    try:
        wifi_info = wifi_fn()
    except Exception as exc:
        errors.append(f"Wi-Fi query error: {str(exc)}")

    # 2. Collect Network performance metrics
    try:
        net_result = net_fn(**net_args)
    except Exception as exc:
        errors.append(f"Network test error: {str(exc)}")

    is_success = True
    err_msg = None
    if errors:
        is_success = False
        err_msg = "; ".join(errors)
    elif wifi_info and not wifi_info.is_connected and (not net_result or not net_result.is_successful):
        is_success = False
        err_msg = "Wi-Fi disconnected and network unreachable"

    return SingleSampleResult(
        sample_index=sample_index,
        timestamp=ts,
        wifi_info=wifi_info,
        network_result=net_result,
        is_successful=is_success,
        error_message=err_msg,
    )


def aggregate_samples(
    floor: str,
    x: float,
    y: float,
    samples: List[SingleSampleResult],
    sample_count: int,
) -> AggregatedMeasurement:
    """
    Aggregate a collected list of SingleSampleResults into a canonical AggregatedMeasurement.

    Calculates medians across valid samples, evaluates BSSID roaming, and sets explicit status:
    - COMPLETE: valid_samples_count == sample_count
    - PARTIAL:  0 < valid_samples_count < sample_count
    - FAILED:   valid_samples_count == 0
    """
    now_ts = datetime.now(timezone.utc).isoformat()

    rssi_values: List[Optional[int]] = []
    signal_values: List[Optional[int]] = []
    latency_values: List[Optional[float]] = []
    loss_values: List[Optional[float]] = []
    throughput_values: List[Optional[float]] = []

    valid_bssids: List[str] = []
    latest_valid_wifi: Optional[WifiConnectionInfo] = None
    valid_samples_count = 0

    for s in samples:
        if not s.is_successful:
            continue

        has_valid_metric = False

        if s.wifi_info and s.wifi_info.is_connected:
            latest_valid_wifi = s.wifi_info
            if s.wifi_info.bssid and s.wifi_info.bssid.strip():
                valid_bssids.append(s.wifi_info.bssid.strip())

            if s.wifi_info.rssi_dbm is not None:
                rssi_values.append(s.wifi_info.rssi_dbm)
                has_valid_metric = True
            if s.wifi_info.signal_percent is not None:
                signal_values.append(s.wifi_info.signal_percent)
                has_valid_metric = True

        if s.network_result:
            if s.network_result.latency and s.network_result.latency.median_ms is not None:
                latency_values.append(s.network_result.latency.median_ms)
                has_valid_metric = True
            elif s.network_result.latency and s.network_result.latency.avg_ms is not None:
                latency_values.append(s.network_result.latency.avg_ms)
                has_valid_metric = True

            if s.network_result.packet_loss is not None and s.network_result.packet_loss.loss_percent is not None:
                loss_values.append(s.network_result.packet_loss.loss_percent)
                has_valid_metric = True

            if s.network_result.throughput and s.network_result.throughput.throughput_mbps is not None:
                throughput_values.append(s.network_result.throughput.throughput_mbps)
                has_valid_metric = True

        if has_valid_metric or (s.wifi_info and s.wifi_info.is_connected) or (s.network_result and s.network_result.is_successful):
            valid_samples_count += 1

    # BSSID Roaming Analysis
    bssids_observed: List[str] = []
    for b in valid_bssids:
        if b not in bssids_observed:
            bssids_observed.append(b)

    bssid_changed = len(bssids_observed) >= 2

    # Status Determination
    if valid_samples_count == sample_count and sample_count > 0:
        measurement_status = "COMPLETE"
        is_overall_success = True
        err_msg = None
    elif valid_samples_count > 0:
        measurement_status = "PARTIAL"
        is_overall_success = True
        err_msg = f"Partial collection: {valid_samples_count} of {sample_count} samples valid"
    else:
        measurement_status = "FAILED"
        is_overall_success = False
        err_msg = "All measurement samples failed or yielded no valid metrics"

    # Calculate medians
    med_rssi = calculate_median(rssi_values)
    med_signal = calculate_median(signal_values)
    med_latency = calculate_median(latency_values)
    med_loss = calculate_median(loss_values)
    med_throughput = calculate_median(throughput_values)

    # Format integer/float fields appropriately
    final_rssi = int(round(med_rssi)) if med_rssi is not None else None
    final_signal = int(round(med_signal)) if med_signal is not None else None
    final_latency = round(med_latency, 2) if med_latency is not None else None
    final_loss = round(med_loss, 2) if med_loss is not None else None
    final_throughput = round(med_throughput, 2) if med_throughput is not None else None

    # Wi-Fi Context from latest valid sample
    ssid = latest_valid_wifi.ssid if latest_valid_wifi else None
    bssid = latest_valid_wifi.bssid if latest_valid_wifi else None
    channel = latest_valid_wifi.channel if latest_valid_wifi else None
    freq = latest_valid_wifi.frequency_mhz if latest_valid_wifi else None
    radio_type = latest_valid_wifi.radio_type if latest_valid_wifi else None
    rx_rate = latest_valid_wifi.receive_rate_mbps if latest_valid_wifi else None
    tx_rate = latest_valid_wifi.transmit_rate_mbps if latest_valid_wifi else None
    adapter = latest_valid_wifi.adapter_description if latest_valid_wifi else None
    driver_ver = latest_valid_wifi.driver_version if latest_valid_wifi else None

    return AggregatedMeasurement(
        floor=floor,
        x=float(x),
        y=float(y),
        sample_count=sample_count,
        valid_samples_count=valid_samples_count,
        timestamp=now_ts,
        status=measurement_status,
        is_successful=is_overall_success,
        rssi_dbm=final_rssi,
        signal_percent=final_signal,
        latency_ms=final_latency,
        packet_loss_percent=final_loss,
        throughput_mbps=final_throughput,
        ssid=ssid,
        bssid=bssid,
        bssid_changed=bssid_changed,
        bssids_observed=bssids_observed,
        channel=channel,
        frequency_mhz=freq,
        radio_type=radio_type,
        receive_rate_mbps=rx_rate,
        transmit_rate_mbps=tx_rate,
        adapter_name=adapter,
        driver_version=driver_ver,
        raw_samples=samples,
        error_message=err_msg,
    )


def measure_grid_point(
    floor: str,
    x: float,
    y: float,
    sample_count: int = 5,
    delay_between_samples_seconds: float = 0.0,
    wifi_provider: Optional[Callable[[], WifiConnectionInfo]] = None,
    net_provider: Optional[Callable[..., NetworkPerformanceResult]] = None,
    net_kwargs: Optional[Dict[str, Any]] = None,
) -> AggregatedMeasurement:
    """
    Perform a complete multi-sample measurement at a physical grid location (floor, x, y).

    Parameters:
        floor: Target floor plan identifier (e.g. 'Floor-1').
        x: Physical or grid X coordinate.
        y: Physical or grid Y coordinate.
        sample_count: Number of independent measurement samples to collect (default: 5).
        delay_between_samples_seconds: Pause between consecutive samples (default: 0.0).
        wifi_provider: Callable returning WifiConnectionInfo (defaults to get_current_wifi_info).
        net_provider: Callable returning NetworkPerformanceResult (defaults to measure_network_performance).
        net_kwargs: Optional dictionary of arguments passed to net_provider.

    Returns:
        AggregatedMeasurement containing median metrics, Wi-Fi metadata, roaming details, and raw sample history.

    Raises:
        ValueError: If location coordinates or sample_count parameters are invalid.
    """
    if not floor or not str(floor).strip():
        raise ValueError("floor must be a non-empty string")
    try:
        fx = float(x)
        fy = float(y)
    except (ValueError, TypeError):
        raise ValueError(f"x and y coordinates must be valid numbers, got x={x}, y={y}")

    if math.isnan(fx) or math.isinf(fx) or math.isnan(fy) or math.isinf(fy):
        raise ValueError(f"x and y coordinates must be finite numbers, got x={x}, y={y}")

    if sample_count < 1:
        raise ValueError(f"sample_count must be at least 1, got {sample_count}")

    samples: List[SingleSampleResult] = []
    for i in range(1, sample_count + 1):
        if i > 1 and delay_between_samples_seconds > 0.0:
            time.sleep(delay_between_samples_seconds)

        sample = collect_single_sample(
            sample_index=i,
            wifi_provider=wifi_provider,
            net_provider=net_provider,
            net_kwargs=net_kwargs,
        )
        samples.append(sample)

    return aggregate_samples(
        floor=floor.strip(),
        x=fx,
        y=fy,
        samples=samples,
        sample_count=sample_count,
    )
