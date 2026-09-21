# PostgreSQL Database Foundation & Measurement Persistence

## 1. Purpose & Architecture
This document details the PostgreSQL persistence architecture for the *Grid-Based Wi-Fi Performance Mapping and Monitoring System*. The database layer is designed to be completely decoupled from API frameworks and the user interface, storing historical survey sessions and multi-point network/RF measurements.

---

## 2. Environment & Database Names

- **PostgreSQL Version**: PostgreSQL 18 (Local native Windows service `postgresql-x64-18`, port 5432)
- **Primary Database**: `wifi_performance_mapper`
- **Isolated Test Database**: `wifi_performance_mapper_test`
- **Driver**: `psycopg2-binary` (Standard C-extension PostgreSQL driver for Python)

---

## 3. Configuration

Database connection parameters are read from the environment or the project root `.env` file (which is excluded from Git tracking via `.gitignore`):

```text
# Development Database URL
DATABASE_URL=postgresql://<user>:<password>@localhost:5432/wifi_performance_mapper

# Test Database URL (Used during automated test runs)
TEST_DATABASE_URL=postgresql://<user>:<password>@localhost:5432/wifi_performance_mapper_test
```

> [!SECURITY]
> Credentials are never hard-coded in source code, committed to Git, or exposed in logs. Connection strings printed by the application are automatically masked (e.g., `postgresql://postgres:***@localhost:5432/wifi_performance_mapper`).

---

## 4. Entity-Relationship & Schema Design

```text
+-----------------------+
| measurement_sessions  |
+-----------------------+
| session_id (PK)       |<----+
| name                  |     |
| floor                 |     | 1-to-many
| created_at            |     |
| notes                 |     |
+-----------------------+     |
                              |
+-----------------------+     |
|     measurements      |     |
+-----------------------+     |
| id (PK, SERIAL)       |     |
| session_id (FK)       |-----+
| floor                 |
| x                     |
| y                     |
| rssi_dbm              |
| signal_percent        |
| latency_ms            |
| packet_loss_percent   |
| throughput_mbps       |
| ssid                  |
| bssid                 |
| channel               |
| frequency_mhz         |
| radio_type            |
| adapter_name          |
| driver_version        |
| sample_count          |
| timestamp             |
| created_at            |
+-----------------------+
```

### Table 1: `measurement_sessions`
Represents an individual survey walk or data collection session on a designated floor.

| Column | Data Type | Constraints / Description |
|---|---|---|
| `session_id` | `VARCHAR(64)` | **PRIMARY KEY**. Unique survey identifier (e.g., `sess_20260921_fl2_walk1`). |
| `name` | `VARCHAR(255)` | **NOT NULL**. Human-readable session name (e.g., `Floor 2 North Wing Survey`). |
| `floor` | `VARCHAR(64)` | **NOT NULL**. Target floor identifier (e.g., `Floor 2`). |
| `created_at` | `TIMESTAMPTZ` | **NOT NULL DEFAULT CURRENT_TIMESTAMP**. Timezone-aware session creation time. |
| `notes` | `TEXT` | Optional survey notes or operator observations. |

### Table 2: `measurements`
Stores individual historical survey data points.

| Column | Data Type | Constraints / Description |
|---|---|---|
| `id` | `SERIAL` | **PRIMARY KEY**. Auto-incrementing unique measurement identifier. |
| `session_id` | `VARCHAR(64)` | **FOREIGN KEY** referencing `measurement_sessions(session_id)` `ON DELETE CASCADE`. |
| `floor` | `VARCHAR(64)` | **NOT NULL**. Spatial floor plan key. |
| `x` | `DOUBLE PRECISION` | **NOT NULL**. Horizontal grid / floor coordinate. |
| `y` | `DOUBLE PRECISION` | **NOT NULL**. Vertical grid / floor coordinate. |
| `rssi_dbm` | `INTEGER` | Physical signal strength in dBm. **`CHECK (rssi_dbm <= 0)`**. Allows `NULL`. |
| `signal_percent` | `INTEGER` | Quality percentage (0–100). **`CHECK (signal_percent >= 0 AND signal_percent <= 100)`**. |
| `latency_ms` | `DOUBLE PRECISION` | Round-trip latency in fractional milliseconds. **`CHECK (latency_ms >= 0)`**. |
| `packet_loss_percent` | `DOUBLE PRECISION` | Loss percentage (0–100). **`CHECK (packet_loss_percent >= 0 AND packet_loss_percent <= 100)`**. |
| `throughput_mbps` | `DOUBLE PRECISION` | Application-layer goodput in Mbps. **`CHECK (throughput_mbps >= 0)`**. |
| `ssid` | `VARCHAR(64)` | Wireless Network SSID (e.g. `THOMAS`). |
| `bssid` | `VARCHAR(32)` | AP MAC address (e.g. `b0:95:75:89:c1:04`). |
| `channel` | `INTEGER` | Operational 802.11 channel number. |
| `frequency_mhz` | `DOUBLE PRECISION` | Center frequency in MHz (e.g. `2457.0`). |
| `radio_type` | `VARCHAR(64)` | Wireless standard (e.g. `802.11n (HT)`). |
| `adapter_name` | `VARCHAR(128)` | Wi-Fi network interface description. |
| `driver_version` | `VARCHAR(64)` | Active wireless driver version string. |
| `sample_count` | `INTEGER` | **NOT NULL DEFAULT 1**. Number of readings aggregated (e.g. 5-sample median). |
| `timestamp` | `TIMESTAMPTZ` | **NOT NULL DEFAULT CURRENT_TIMESTAMP**. Exact capture timestamp. |
| `created_at` | `TIMESTAMPTZ` | **NOT NULL DEFAULT CURRENT_TIMESTAMP**. Database record insertion time. |

---

## 5. Performance Indexing Strategy

To support fast dashboard spatial rendering, session historical lookups, and time-series queries, the following indexes are established:

1. **`idx_measurements_session`**: Index on `measurements(session_id)` for rapid retrieval of entire session surveys.
2. **`idx_measurements_floor`**: Index on `measurements(floor)` for floor-wide filtering.
3. **`idx_measurements_coords`**: Composite index on `measurements(floor, x, y)` for fast grid cell historical lookups.
4. **`idx_measurements_timestamp`**: Index on `measurements(timestamp)` for chronological time-series slicing.

---

## 6. Historical Data Preservation

A core architectural guarantee is that **measurements are immutable historical records**:
- There is **no uniqueness constraint** on `(floor, x, y)` or `(session_id, floor, x, y)`.
- If an operator measures cell `(Floor 2, 10.5, 20.0)` at 10:00 AM and again at 10:05 AM, two separate records with unique `id` values are stored.
- This preserves the temporal progression of Wi-Fi and network health across surveys.

---

## 7. Strict NULL Semantics vs. Fake Zeroes

The database layer maintains strict mathematical fidelity between absent measurements and zero-value measurements:
- **`rssi_dbm = NULL`**: Hardware driver did not expose physical dBm (not 0 dBm, which would mean an unrealistically strong 1 milliwatt signal).
- **`packet_loss_percent = 0.0`**: 0% packet loss measured (all packets received).
- **`packet_loss_percent = NULL`**: Network probe failed to execute or was skipped.
- **`throughput_mbps = NULL`**: No throughput test was configured or conducted.

---

## 8. Schema Initialization & Repository Usage

### Schema Initialization
Schema creation is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`) and executed programmatically:

```python
from backend.database import init_db

init_db()  # Safe to execute multiple times on startup or migration
```

### Repository Usage
All SQL queries in [backend/repository.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/repository.py) are strictly parameterized to prevent SQL injection:

```python
from backend.repository import create_session, record_measurement_from_modules

# 1. Create survey session
session = create_session(
    session_id="sess_20260921_fl2",
    name="Floor 2 Walkthrough",
    floor="Floor 2",
)

# 2. Record measurement from live Wi-Fi and Network modules
measurement = record_measurement_from_modules(
    session_id="sess_20260921_fl2",
    floor="Floor 2",
    x=10.0,
    y=15.0,
    wifi_info=wifi_data,
    net_result=network_data,
    sample_count=5,
)
```

---

## 9. Known Limitations

1. **Localhost Authentication**: In the development environment, the local PostgreSQL service requires configuring credentials in `.env` (`DATABASE_URL=postgresql://<user>:<password>@localhost:5432/wifi_performance_mapper`).
2. **Migration Framework**: Formal schema migrations (e.g. Alembic) are intentionally deferred at this stage to keep the student architecture lightweight. DDL updates are managed idempotently in `init_db()`.
