"""
backend/measurement_service.py
Measurement Service Integration Module for Milestone 7.

Orchestrates the end-to-end integration between the M6 Measurement Engine
(multi-sample data collection and median aggregation) and the M4 PostgreSQL
Persistence layer (repository data access).

Decoupled from raw SQL, direct DB connection handles, HTTP routing, and low-level hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

from backend.measurement import (
    AggregatedMeasurement,
    measure_grid_point,
)
from backend.repository import create_measurement
from backend.wifi_windows import WifiConnectionInfo
from backend.network_tests import NetworkPerformanceResult


# ----------------------------------------------------------------------
# Service Result Model
# ----------------------------------------------------------------------

@dataclass
class MeasurementServiceResult:
    """
    Canonical result returned by the Measurement Service after executing
    a survey measurement pass and attempting persistence.

    Fields:
        session_id: Target survey session foreign key identifier.
        floor: Target floor plan identifier.
        x: X coordinate of survey grid cell.
        y: Y coordinate of survey grid cell.
        status: Execution status ('COMPLETE', 'PARTIAL', 'FAILED').
        is_successful: True if COMPLETE or PARTIAL, False if FAILED.
        persisted: True if successfully written to PostgreSQL, False otherwise.
        aggregated: Full M6 AggregatedMeasurement domain object.
        db_record: Persisted database record dictionary (if persisted), None otherwise.
        error_message: Optional error message or partial collection note.
    """
    session_id: str
    floor: str
    x: float
    y: float
    status: str
    is_successful: bool
    persisted: bool
    aggregated: AggregatedMeasurement
    db_record: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "floor": self.floor,
            "x": self.x,
            "y": self.y,
            "status": self.status,
            "is_successful": self.is_successful,
            "persisted": self.persisted,
            "aggregated": self.aggregated.to_dict() if self.aggregated else None,
            "db_record": self.db_record,
            "error_message": self.error_message,
        }


# ----------------------------------------------------------------------
# Measurement Service Orchestration
# ----------------------------------------------------------------------

def execute_and_persist_measurement(
    session_id: str,
    floor: str,
    x: float,
    y: float,
    sample_count: int = 5,
    delay_between_samples_seconds: float = 0.0,
    wifi_provider: Optional[Callable[[], WifiConnectionInfo]] = None,
    net_provider: Optional[Callable[..., NetworkPerformanceResult]] = None,
    net_kwargs: Optional[Dict[str, Any]] = None,
    repository_create_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> MeasurementServiceResult:
    """
    Perform a complete multi-sample measurement at a physical grid location (floor, x, y),
    evaluate its collection status, and persist valid canonical metrics to PostgreSQL.

    Persistence Policy:
    - COMPLETE (5/5 valid): Persisted to database; persisted=True; status='COMPLETE'.
    - PARTIAL  (1-4/5 valid): Persisted to database with valid medians; persisted=True; status='PARTIAL'.
    - FAILED   (0/5 valid): NOT persisted (no fake zero row created); persisted=False; status='FAILED'.

    Parameters:
        session_id: Non-empty survey session foreign key string.
        floor: Target floor plan identifier.
        x: Grid cell X coordinate.
        y: Grid cell Y coordinate.
        sample_count: Number of independent measurement samples to collect (default: 5).
        delay_between_samples_seconds: Pause between consecutive samples (default: 0.0).
        wifi_provider: Optional injected Wi-Fi probe callable.
        net_provider: Optional injected Network probe callable.
        net_kwargs: Optional kwargs for network provider.
        repository_create_fn: Optional injected repository insertion callable.
        database_url: Optional explicit PostgreSQL connection URL.
        is_test: Set to True to target the test database configuration.

    Returns:
        MeasurementServiceResult object containing the persistence outcome, status,
        database record, and full M6 aggregated domain data.

    Raises:
        ValueError: If session_id, floor, x, y, or sample_count are invalid.
        psycopg2.IntegrityError: If session_id does not reference an existing session.
    """
    if not session_id or not str(session_id).strip():
        raise ValueError("session_id must be a non-empty string")
    if not floor or not str(floor).strip():
        raise ValueError("floor must be a non-empty string")

    clean_session_id = session_id.strip()
    clean_floor = floor.strip()

    # 1. Execute M6 measurement engine loop and aggregation
    aggregated = measure_grid_point(
        floor=clean_floor,
        x=x,
        y=y,
        sample_count=sample_count,
        delay_between_samples_seconds=delay_between_samples_seconds,
        wifi_provider=wifi_provider,
        net_provider=net_provider,
        net_kwargs=net_kwargs,
    )

    # 2. Inspect M6 status to determine persistence eligibility
    if aggregated.status == "FAILED":
        return MeasurementServiceResult(
            session_id=clean_session_id,
            floor=clean_floor,
            x=aggregated.x,
            y=aggregated.y,
            status="FAILED",
            is_successful=False,
            persisted=False,
            aggregated=aggregated,
            db_record=None,
            error_message=aggregated.error_message or "Measurement failed: no valid samples collected",
        )

    # 3. For COMPLETE or PARTIAL, persist canonical scalar metrics to PostgreSQL
    create_fn = repository_create_fn or create_measurement

    # Parse ISO 8601 UTC timestamp to datetime object if feasible
    ts: Optional[datetime] = None
    if aggregated.timestamp:
        try:
            ts = datetime.fromisoformat(aggregated.timestamp)
        except Exception:
            ts = datetime.now(timezone.utc)

    db_record = create_fn(
        session_id=clean_session_id,
        floor=clean_floor,
        x=aggregated.x,
        y=aggregated.y,
        rssi_dbm=aggregated.rssi_dbm,
        signal_percent=aggregated.signal_percent,
        latency_ms=aggregated.latency_ms,
        packet_loss_percent=aggregated.packet_loss_percent,
        throughput_mbps=aggregated.throughput_mbps,
        ssid=aggregated.ssid,
        bssid=aggregated.bssid,
        channel=aggregated.channel,
        frequency_mhz=aggregated.frequency_mhz,
        radio_type=aggregated.radio_type,
        adapter_name=aggregated.adapter_name,
        driver_version=aggregated.driver_version,
        sample_count=aggregated.sample_count,
        timestamp=ts,
        database_url=database_url,
        is_test=is_test,
    )

    return MeasurementServiceResult(
        session_id=clean_session_id,
        floor=clean_floor,
        x=aggregated.x,
        y=aggregated.y,
        status=aggregated.status,
        is_successful=True,
        persisted=True,
        aggregated=aggregated,
        db_record=db_record,
        error_message=aggregated.error_message,
    )
