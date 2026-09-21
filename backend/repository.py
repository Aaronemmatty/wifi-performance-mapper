"""
backend/repository.py
Data Access Layer and Repository for PostgreSQL Measurement Persistence.

Provides parameterized SQL operations to record, query, and manage
survey sessions and historical measurement points.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from backend.database import get_db_cursor
from backend.wifi_windows import WifiConnectionInfo
from backend.network_tests import NetworkPerformanceResult


# ----------------------------------------------------------------------
# Session Repository Operations
# ----------------------------------------------------------------------

def create_session(
    session_id: str,
    name: str,
    floor: str,
    notes: Optional[str] = None,
    created_at: Optional[datetime] = None,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> Dict[str, Any]:
    """
    Insert a new survey session record.

    Uses parameterized SQL to prevent SQL injection.
    """
    if not session_id or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if not name or not name.strip():
        raise ValueError("name must be a non-empty string")
    if not floor or not floor.strip():
        raise ValueError("floor must be a non-empty string")

    ts = created_at or datetime.now(timezone.utc)
    sql = """
    INSERT INTO measurement_sessions (session_id, name, floor, created_at, notes)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING session_id, name, floor, created_at, notes;
    """
    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql, (session_id.strip(), name.strip(), floor.strip(), ts, notes))
        row = cur.fetchone()
        return dict(row)


def get_session(
    session_id: str,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> Optional[Dict[str, Any]]:
    """Retrieve a survey session by its unique session_id."""
    sql = """
    SELECT session_id, name, floor, created_at, notes
    FROM measurement_sessions
    WHERE session_id = %s;
    """
    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql, (session_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_sessions(
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> List[Dict[str, Any]]:
    """List all survey sessions ordered by creation date descending."""
    sql = """
    SELECT session_id, name, floor, created_at, notes
    FROM measurement_sessions
    ORDER BY created_at DESC;
    """
    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


# ----------------------------------------------------------------------
# Measurement Repository Operations
# ----------------------------------------------------------------------

def create_measurement(
    session_id: str,
    floor: str,
    x: float,
    y: float,
    rssi_dbm: Optional[int] = None,
    signal_percent: Optional[int] = None,
    latency_ms: Optional[float] = None,
    packet_loss_percent: Optional[float] = None,
    throughput_mbps: Optional[float] = None,
    ssid: Optional[str] = None,
    bssid: Optional[str] = None,
    channel: Optional[int] = None,
    frequency_mhz: Optional[float] = None,
    radio_type: Optional[str] = None,
    adapter_name: Optional[str] = None,
    driver_version: Optional[str] = None,
    sample_count: int = 1,
    timestamp: Optional[datetime] = None,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> Dict[str, Any]:
    """
    Insert an individual historical measurement point.

    Important Design Rule:
    Does NOT overwrite existing records at the same (session_id, floor, x, y).
    Every call creates a new historical record with a unique auto-incrementing ID.
    """
    if not session_id:
        raise ValueError("session_id is required")
    if not floor:
        raise ValueError("floor is required")
    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")

    # Validate constraint bounds before executing query
    if rssi_dbm is not None and rssi_dbm > 0:
        raise ValueError(f"rssi_dbm must be negative or zero, got {rssi_dbm}")
    if signal_percent is not None and not (0 <= signal_percent <= 100):
        raise ValueError(f"signal_percent must be between 0 and 100, got {signal_percent}")
    if latency_ms is not None and latency_ms < 0:
        raise ValueError(f"latency_ms cannot be negative, got {latency_ms}")
    if packet_loss_percent is not None and not (0 <= packet_loss_percent <= 100):
        raise ValueError(f"packet_loss_percent must be between 0 and 100, got {packet_loss_percent}")
    if throughput_mbps is not None and throughput_mbps < 0:
        raise ValueError(f"throughput_mbps cannot be negative, got {throughput_mbps}")

    ts = timestamp or datetime.now(timezone.utc)

    sql = """
    INSERT INTO measurements (
        session_id, floor, x, y,
        rssi_dbm, signal_percent, latency_ms, packet_loss_percent, throughput_mbps,
        ssid, bssid, channel, frequency_mhz, radio_type, adapter_name, driver_version,
        sample_count, timestamp
    ) VALUES (
        %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s
    )
    RETURNING
        id, session_id, floor, x, y,
        rssi_dbm, signal_percent, latency_ms, packet_loss_percent, throughput_mbps,
        ssid, bssid, channel, frequency_mhz, radio_type, adapter_name, driver_version,
        sample_count, timestamp, created_at;
    """
    params = (
        session_id, floor, float(x), float(y),
        rssi_dbm, signal_percent, latency_ms, packet_loss_percent, throughput_mbps,
        ssid, bssid, channel, frequency_mhz, radio_type, adapter_name, driver_version,
        int(sample_count), ts
    )

    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row)


def get_measurement(
    measurement_id: int,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> Optional[Dict[str, Any]]:
    """Retrieve an individual measurement record by ID."""
    sql = """
    SELECT * FROM measurements WHERE id = %s;
    """
    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql, (measurement_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_measurements_by_session(
    session_id: str,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve all measurements associated with a session, ordered chronologically."""
    sql = """
    SELECT * FROM measurements
    WHERE session_id = %s
    ORDER BY timestamp ASC, id ASC;
    """
    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql, (session_id,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def get_measurements_by_location(
    floor: str,
    x: float,
    y: float,
    session_id: Optional[str] = None,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> List[Dict[str, Any]]:
    """
    Retrieve all historical measurements recorded at a specific (floor, x, y) coordinate.
    """
    if session_id:
        sql = """
        SELECT * FROM measurements
        WHERE floor = %s AND x = %s AND y = %s AND session_id = %s
        ORDER BY timestamp ASC, id ASC;
        """
        params = (floor, float(x), float(y), session_id)
    else:
        sql = """
        SELECT * FROM measurements
        WHERE floor = %s AND x = %s AND y = %s
        ORDER BY timestamp ASC, id ASC;
        """
        params = (floor, float(x), float(y))

    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def list_measurements(
    session_id: Optional[str] = None,
    floor: Optional[str] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> List[Dict[str, Any]]:
    """
    List historical measurements with optional filtering by session, floor, and/or coordinates.
    All filters use parameterized SQL.
    """
    conditions = []
    params: List[Any] = []

    if session_id is not None:
        conditions.append("session_id = %s")
        params.append(session_id)
    if floor is not None:
        conditions.append("floor = %s")
        params.append(floor)
    if x is not None:
        conditions.append("x = %s")
        params.append(float(x))
    if y is not None:
        conditions.append("y = %s")
        params.append(float(y))

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
    SELECT * FROM measurements
    {where_clause}
    ORDER BY timestamp ASC, id ASC;
    """

    with get_db_cursor(database_url=database_url, is_test=is_test) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        return [dict(r) for r in rows]


# ----------------------------------------------------------------------
# Module Integration Helper
# ----------------------------------------------------------------------

def record_measurement_from_modules(
    session_id: str,
    floor: str,
    x: float,
    y: float,
    wifi_info: Optional[WifiConnectionInfo] = None,
    net_result: Optional[NetworkPerformanceResult] = None,
    sample_count: int = 1,
    database_url: Optional[str] = None,
    is_test: bool = False,
) -> Dict[str, Any]:
    """
    Convenience mapper converting output from `wifi_windows.py` and `network_tests.py`
    into a persistent database measurement record.
    """
    rssi_dbm = wifi_info.rssi_dbm if wifi_info else None
    signal_percent = wifi_info.signal_percent if wifi_info else None
    ssid = wifi_info.ssid if wifi_info else None
    bssid = wifi_info.bssid if wifi_info else None
    channel = wifi_info.channel if wifi_info else None
    freq = wifi_info.frequency_mhz if wifi_info else None
    radio_type = wifi_info.radio_type if wifi_info else None
    adapter = wifi_info.adapter_description if wifi_info else None
    driver_ver = wifi_info.driver_version if wifi_info else None

    latency_ms = None
    packet_loss = None
    throughput = None

    if net_result:
        if net_result.latency and net_result.latency.avg_ms is not None:
            latency_ms = net_result.latency.avg_ms
        if net_result.packet_loss:
            packet_loss = net_result.packet_loss.loss_percent
        if net_result.throughput and net_result.throughput.throughput_mbps is not None:
            throughput = net_result.throughput.throughput_mbps

    return create_measurement(
        session_id=session_id,
        floor=floor,
        x=x,
        y=y,
        rssi_dbm=rssi_dbm,
        signal_percent=signal_percent,
        latency_ms=latency_ms,
        packet_loss_percent=packet_loss,
        throughput_mbps=throughput,
        ssid=ssid,
        bssid=bssid,
        channel=channel,
        frequency_mhz=freq,
        radio_type=radio_type,
        adapter_name=adapter,
        driver_version=driver_ver,
        sample_count=sample_count,
        database_url=database_url,
        is_test=is_test,
    )
