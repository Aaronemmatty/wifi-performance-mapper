"""
backend/database.py
PostgreSQL Connection Management and Schema Initialization Module.

Provides robust connection handling, transaction management, and idempotent
schema creation for the Wi-Fi Performance Mapping and Monitoring System.
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Generator, Optional, Tuple, Any
from urllib.parse import urlparse

import psycopg2
from psycopg2.extensions import connection as PgConnection, cursor as PgCursor
from psycopg2.extras import RealDictCursor


# ----------------------------------------------------------------------
# Configuration & URL Helpers
# ----------------------------------------------------------------------

def parse_env_file(filepath: Path) -> dict[str, str]:
    """Parse key=value pairs from a .env file safely."""
    env_vars: dict[str, str] = {}
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


def get_database_url(is_test: bool = False) -> Optional[str]:
    """
    Retrieve database URL from environment or .env file.

    Priority:
        If is_test: TEST_DATABASE_URL -> DATABASE_URL (modified with _test suffix) -> None
        Else: DATABASE_URL -> None
    """
    env_key = "TEST_DATABASE_URL" if is_test else "DATABASE_URL"
    url = os.environ.get(env_key)

    if not url:
        root_env = Path(__file__).resolve().parent.parent / ".env"
        parsed = parse_env_file(root_env)
        url = parsed.get(env_key)
        if not url and is_test:
            # Check default DATABASE_URL from .env
            base_url = parsed.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
            if base_url:
                # Append _test to database name if feasible
                p = urlparse(base_url)
                if p.path and not p.path.endswith("_test"):
                    test_path = f"{p.path}_test"
                    url = base_url.replace(p.path, test_path)
                else:
                    url = base_url

    return url


def mask_database_url(url: Optional[str]) -> str:
    """Mask credentials in DATABASE_URL for safe logging."""
    if not url:
        return "None"
    try:
        p = urlparse(url)
        netloc = p.hostname or "localhost"
        if p.port:
            netloc += f":{p.port}"
        if p.username:
            user_part = f"{p.username}:***@"
        else:
            user_part = ""
        return f"{p.scheme}://{user_part}{netloc}{p.path}"
    except Exception:
        return "postgresql://***:***@localhost/..."


# ----------------------------------------------------------------------
# Connection & Transaction Context Managers
# ----------------------------------------------------------------------

def get_connection(database_url: Optional[str] = None, is_test: bool = False) -> PgConnection:
    """
    Establish a connection to PostgreSQL using the provided or configured URL.

    Raises:
        ValueError: If no DATABASE_URL is configured.
        psycopg2.OperationalError: If connection cannot be established.
    """
    target_url = database_url or get_database_url(is_test=is_test)
    if not target_url:
        raise ValueError(
            "DATABASE_URL is not configured. Please define DATABASE_URL in your environment or .env file."
        )

    conn = psycopg2.connect(target_url, connect_timeout=5)
    return conn


@contextlib.contextmanager
def get_db_connection(
    database_url: Optional[str] = None, is_test: bool = False
) -> Generator[PgConnection, None, None]:
    """
    Context manager providing a database connection with automatic commit on success
    and rollback on error, ensuring clean resource closing.
    """
    conn = get_connection(database_url=database_url, is_test=is_test)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextlib.contextmanager
def get_db_cursor(
    database_url: Optional[str] = None, is_test: bool = False, dict_cursor: bool = True
) -> Generator[PgCursor, None, None]:
    """
    Context manager yielding a transaction cursor (RealDictCursor by default).
    """
    with get_db_connection(database_url=database_url, is_test=is_test) as conn:
        cursor_factory = RealDictCursor if dict_cursor else None
        cur = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cur
        finally:
            cur.close()


def test_connection(database_url: Optional[str] = None, is_test: bool = False) -> Tuple[bool, str]:
    """
    Safely probe the PostgreSQL connection and return (success, message).
    """
    target_url = database_url or get_database_url(is_test=is_test)
    if not target_url:
        return False, "DATABASE_URL not configured"
    try:
        with get_db_cursor(database_url=target_url, is_test=is_test) as cur:
            cur.execute("SELECT version();")
            ver = cur.fetchone()
            ver_str = ver["version"] if ver else "Unknown"
            return True, f"Connected to PostgreSQL: {ver_str}"
    except Exception as exc:
        return False, f"Connection failed: {str(exc)}"


# ----------------------------------------------------------------------
# Schema Definition & Initialization
# ----------------------------------------------------------------------

SCHEMA_SQL = """
-- Table: measurement_sessions
-- Groups measurements performed during a specific survey walk/run.
CREATE TABLE IF NOT EXISTS measurement_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    floor VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Table: measurements
-- Stores individual historical point measurements.
-- Multiple records at the same (session_id, floor, x, y) are preserved to capture time-series history.
CREATE TABLE IF NOT EXISTS measurements (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) REFERENCES measurement_sessions(session_id) ON DELETE CASCADE,
    floor VARCHAR(64) NOT NULL,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    rssi_dbm INTEGER CHECK (rssi_dbm <= 0),
    signal_percent INTEGER CHECK (signal_percent >= 0 AND signal_percent <= 100),
    latency_ms DOUBLE PRECISION CHECK (latency_ms >= 0),
    packet_loss_percent DOUBLE PRECISION CHECK (packet_loss_percent >= 0 AND packet_loss_percent <= 100),
    throughput_mbps DOUBLE PRECISION CHECK (throughput_mbps >= 0),
    ssid VARCHAR(64),
    bssid VARCHAR(32),
    channel INTEGER,
    frequency_mhz DOUBLE PRECISION,
    radio_type VARCHAR(64),
    adapter_name VARCHAR(128),
    driver_version VARCHAR(64),
    sample_count INTEGER NOT NULL DEFAULT 1 CHECK (sample_count >= 1),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for spatial, temporal, and session querying
CREATE INDEX IF NOT EXISTS idx_measurements_session ON measurements(session_id);
CREATE INDEX IF NOT EXISTS idx_measurements_floor ON measurements(floor);
CREATE INDEX IF NOT EXISTS idx_measurements_coords ON measurements(floor, x, y);
CREATE INDEX IF NOT EXISTS idx_measurements_timestamp ON measurements(timestamp);
"""


def init_db(database_url: Optional[str] = None, is_test: bool = False) -> None:
    """
    Execute idempotent schema creation. Safe to run multiple times.
    """
    with get_db_connection(database_url=database_url, is_test=is_test) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
