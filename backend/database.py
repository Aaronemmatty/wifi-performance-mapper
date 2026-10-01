"""
backend/database.py
SQLite Connection Management and Schema Initialization Module.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Generator, Optional, Tuple, Any


def get_database_path(is_test: bool = False) -> str:
    """Get the SQLite database file path."""
    if is_test:
        return "test_database.sqlite3"
    return "database.sqlite3"

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_connection(database_url: Optional[str] = None, is_test: bool = False) -> sqlite3.Connection:
    target_url = database_url or get_database_path(is_test=is_test)
    conn = sqlite3.connect(target_url, timeout=5.0)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

@contextlib.contextmanager
def get_db_connection(
    database_url: Optional[str] = None, is_test: bool = False
) -> Generator[sqlite3.Connection, None, None]:
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
) -> Generator[sqlite3.Cursor, None, None]:
    with get_db_connection(database_url=database_url, is_test=is_test) as conn:
        if not dict_cursor:
            conn.row_factory = None
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

def test_connection(database_url: Optional[str] = None, is_test: bool = False) -> Tuple[bool, str]:
    target_url = database_url or get_database_path(is_test=is_test)
    try:
        with get_db_cursor(database_url=target_url, is_test=is_test) as cur:
            cur.execute("SELECT sqlite_version();")
            ver = cur.fetchone()
            ver_str = ver["sqlite_version()"] if ver else "Unknown"
            return True, f"Connected to SQLite: {ver_str}"
    except Exception as exc:
        return False, f"Connection failed: {str(exc)}"


SCHEMA_SQL = """
-- Table: measurement_sessions
CREATE TABLE IF NOT EXISTS measurement_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    floor VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Table: measurements
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id VARCHAR(64) REFERENCES measurement_sessions(session_id) ON DELETE CASCADE,
    floor VARCHAR(64) NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    rssi_dbm INTEGER CHECK (rssi_dbm <= 0),
    signal_percent INTEGER CHECK (signal_percent >= 0 AND signal_percent <= 100),
    latency_ms REAL CHECK (latency_ms >= 0),
    packet_loss_percent REAL CHECK (packet_loss_percent >= 0 AND packet_loss_percent <= 100),
    throughput_mbps REAL CHECK (throughput_mbps >= 0),
    ssid VARCHAR(64),
    bssid VARCHAR(32),
    channel INTEGER,
    frequency_mhz REAL,
    radio_type VARCHAR(64),
    adapter_name VARCHAR(128),
    driver_version VARCHAR(64),
    sample_count INTEGER NOT NULL DEFAULT 1 CHECK (sample_count >= 1),
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_measurements_session ON measurements(session_id);
CREATE INDEX IF NOT EXISTS idx_measurements_floor ON measurements(floor);
CREATE INDEX IF NOT EXISTS idx_measurements_coords ON measurements(floor, x, y);
CREATE INDEX IF NOT EXISTS idx_measurements_timestamp ON measurements(timestamp);
"""

def init_db(database_url: Optional[str] = None, is_test: bool = False) -> None:
    with get_db_connection(database_url=database_url, is_test=is_test) as conn:
        conn.executescript(SCHEMA_SQL)
