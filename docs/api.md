# FastAPI Backend & REST API Layer

## 1. Overview
This document details the HTTP REST API foundation for the *Grid-Based Wi-Fi Performance Mapping and Monitoring System*. The API layer exposes survey session creation and multi-metric Wi-Fi/network measurement persistence over standard HTTP. It communicates directly with the repository abstraction layer (`backend/repository.py`), keeping data access isolated from HTTP transport logic.

---

## 2. Starting the API Locally

From the project root using the project virtual environment:

```powershell
# Set database URL (or configure in .env)
$env:DATABASE_URL = "postgresql://postgres:password@localhost:5432/wifi_performance_mapper"

# Start Uvicorn ASGI Server
.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000 --reload
```

- **Base URL**: `http://127.0.0.1:8000`
- **Interactive Swagger UI**: `http://127.0.0.1:8000/docs`
- **OpenAPI JSON**: `http://127.0.0.1:8000/openapi.json`

---

## 3. Endpoints Summary

| Method | Endpoint | Description | Request Body | Response Status |
|---|---|---|---|---|
| `GET` | `/health` | Application liveness probe | None | `200 OK` |
| `POST` | `/sessions` | Create new survey session | `SessionCreateRequest` | `201 Created` / `400` / `409` / `422` |
| `GET` | `/sessions` | List all survey sessions (descending by date) | None | `200 OK` |
| `GET` | `/sessions/{session_id}` | Retrieve single session by ID | None | `200 OK` / `404 Not Found` |
| `POST` | `/measurements` | Record historical measurement point | `MeasurementCreateRequest` | `201 Created` / `400` / `422` |
| `GET` | `/measurements` | List measurements with optional filters (`session_id`, `floor`, `x`, `y`) | Query Params | `200 OK` |
| `GET` | `/measurements/{id}` | Retrieve single measurement by ID | None | `200 OK` / `404 Not Found` |
| `POST` | `/measurements/measure` | Trigger active multi-sample probe and persist canonical measurement | `MeasureTriggerRequest` | `200 OK` / `502 Bad Gateway` / `400` / `422` |

---

## 4. Request & Response Examples

### System Health

#### `GET /health`
```json
{
  "status": "ok"
}
```

---

### Survey Sessions

#### `POST /sessions`
**Request:**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "name": "Floor 2 North Wing Walkthrough",
  "floor": "Floor 2",
  "notes": "Survey during peak campus hours"
}
```

**Response (`201 Created`):**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "name": "Floor 2 North Wing Walkthrough",
  "floor": "Floor 2",
  "created_at": "2026-09-21T15:45:00.123456Z",
  "notes": "Survey during peak campus hours"
}
```

#### `GET /sessions`
Retrieves all survey sessions ordered chronologically descending (`ORDER BY created_at DESC`). Pure read operation without database side effects.

**Response (`200 OK`):**
```json
[
  {
    "session_id": "sess_20260921_fl2_walk1",
    "name": "Floor 2 North Wing Walkthrough",
    "floor": "Floor 2",
    "created_at": "2026-09-21T15:45:00.123456Z",
    "notes": "Survey during peak campus hours"
  },
  {
    "session_id": "sess_20260921_fl1_walk1",
    "name": "Floor 1 Morning Walkthrough",
    "floor": "Floor 1",
    "created_at": "2026-09-21T09:00:00.000000Z",
    "notes": null
  }
]
```

#### `GET /sessions/{session_id}`
Retrieves a specific survey session by its unique `session_id`.

**Response (`200 OK`):**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "name": "Floor 2 North Wing Walkthrough",
  "floor": "Floor 2",
  "created_at": "2026-09-21T15:45:00.123456Z",
  "notes": "Survey during peak campus hours"
}
```

**Response (`404 Not Found`):**
```json
{
  "detail": "Session 'unknown_sess_id' not found."
}
```

---

### Measurements

#### `POST /measurements`
**Request:**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "floor": "Floor 2",
  "x": 10.5,
  "y": 20.0,
  "rssi_dbm": -35,
  "signal_percent": 100,
  "latency_ms": 8.5,
  "packet_loss_percent": 0.0,
  "throughput_mbps": 50.0,
  "ssid": "CAMPUS_WIFI",
  "bssid": "00:11:22:33:44:55",
  "channel": 6,
  "frequency_mhz": 2437.0,
  "radio_type": "802.11n (HT)",
  "adapter_name": "Qualcomm Atheros QCA9377",
  "driver_version": "12.0.0.722",
  "sample_count": 5
}
```

**Response (`201 Created`):**
```json
{
  "id": 1,
  "session_id": "sess_20260921_fl2_walk1",
  "floor": "Floor 2",
  "x": 10.5,
  "y": 20.0,
  "rssi_dbm": -35,
  "signal_percent": 100,
  "latency_ms": 8.5,
  "packet_loss_percent": 0.0,
  "throughput_mbps": 50.0,
  "ssid": "CAMPUS_WIFI",
  "bssid": "00:11:22:33:44:55",
  "channel": 6,
  "frequency_mhz": 2437.0,
  "radio_type": "802.11n (HT)",
  "adapter_name": "Qualcomm Atheros QCA9377",
  "driver_version": "12.0.0.722",
  "sample_count": 5,
  "timestamp": "2026-09-21T15:46:10.000000Z",
  "created_at": "2026-09-21T15:46:10.045000Z"
}
```

#### `GET /measurements`
Retrieves historical measurements with optional filtering. Results are returned in deterministic chronological order (`ORDER BY timestamp ASC, id ASC`). Measurements at identical `(session_id, floor, x, y)` coordinates remain distinct historical records and are never collapsed or overwritten.

**Query Parameters:**
- `session_id` (string, optional): Filter by survey session foreign key.
- `floor` (string, optional): Filter by floor identifier.
- `x` (float, optional): Filter by exact X coordinate.
- `y` (float, optional): Filter by exact Y coordinate.

**Example: `GET /measurements?session_id=sess_20260921_fl2_walk1&floor=Floor%202`**

**Response (`200 OK`):**
```json
[
  {
    "id": 1,
    "session_id": "sess_20260921_fl2_walk1",
    "floor": "Floor 2",
    "x": 10.5,
    "y": 20.0,
    "rssi_dbm": -35,
    "signal_percent": 100,
    "latency_ms": 8.5,
    "packet_loss_percent": 0.0,
    "throughput_mbps": 50.0,
    "ssid": "CAMPUS_WIFI",
    "bssid": "00:11:22:33:44:55",
    "channel": 6,
    "frequency_mhz": 2437.0,
    "radio_type": "802.11n (HT)",
    "adapter_name": "Qualcomm Atheros QCA9377",
    "driver_version": "12.0.0.722",
    "sample_count": 5,
    "timestamp": "2026-09-21T15:46:10.000000Z",
    "created_at": "2026-09-21T15:46:10.045000Z"
  }
]
```

#### `GET /measurements/{id}`
Retrieves an individual historical measurement record by its primary key ID. Preserves all 19 canonical contract fields and NULL/0/100 metric distinctions.

**Response (`200 OK`):**
```json
{
  "id": 1,
  "session_id": "sess_20260921_fl2_walk1",
  "floor": "Floor 2",
  "x": 10.5,
  "y": 20.0,
  "rssi_dbm": -35,
  "signal_percent": 100,
  "latency_ms": 8.5,
  "packet_loss_percent": 0.0,
  "throughput_mbps": 50.0,
  "ssid": "CAMPUS_WIFI",
  "bssid": "00:11:22:33:44:55",
  "channel": 6,
  "frequency_mhz": 2437.0,
  "radio_type": "802.11n (HT)",
  "adapter_name": "Qualcomm Atheros QCA9377",
  "driver_version": "12.0.0.722",
  "sample_count": 5,
  "timestamp": "2026-09-21T15:46:10.000000Z",
  "created_at": "2026-09-21T15:46:10.045000Z"
}
```

**Response (`404 Not Found`):**
```json
{
  "detail": "Measurement with ID 99999 not found."
}
```

---

### Active Measurement Orchestration (Milestone 8)

#### `POST /measurements/measure`

Orchestrates an active multi-sample measurement pass at a physical grid point:
1. Validates request coordinates and survey session existence.
2. Enforces the project's survey methodology: **always collects exactly 5 samples per grid cell** (callers specify location coordinates; sample count is locked).
3. Invokes the M7 `MeasurementService` and executes the M6 `MeasurementEngine`.
4. Aggregates sample medians across valid samples, evaluates roaming state (`bssid_changed`, `bssids_observed`), and determines collection status.
5. Persists canonical metrics to PostgreSQL if `COMPLETE` (5/5 valid) or `PARTIAL` (1–4/5 valid).
6. Returns structured response (`200 OK` on complete/partial, `502 Bad Gateway` if all samples failed).

**Request Schema (`MeasureTriggerRequest`):**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "floor": "Floor 2",
  "x": 10.5,
  "y": 20.0
}
```

- `session_id` (string, required): Survey session foreign key (1-64 characters, non-whitespace).
- `floor` (string, required): Floor plan identifier (1-64 characters, non-whitespace).
- `x` (float, required): Finite X grid coordinate.
- `y` (float, required): Finite Y grid coordinate.
*(Note: `sample_count` is not caller-configurable; the API strictly enforces the 5-sample survey methodology).*

#### COMPLETE Measurement Example (`200 OK`)
**Response:**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "floor": "Floor 2",
  "x": 10.5,
  "y": 20.0,
  "status": "COMPLETE",
  "is_successful": true,
  "persisted": true,
  "valid_samples_count": 5,
  "sample_count": 5,
  "bssid_changed": false,
  "bssids_observed": [
    "00:11:22:33:44:55"
  ],
  "measurement": {
    "id": 101,
    "session_id": "sess_20260921_fl2_walk1",
    "floor": "Floor 2",
    "x": 10.5,
    "y": 20.0,
    "rssi_dbm": -45,
    "signal_percent": 90,
    "latency_ms": 6.0,
    "packet_loss_percent": 0.0,
    "throughput_mbps": 85.5,
    "ssid": "CAMPUS_WIFI",
    "bssid": "00:11:22:33:44:55",
    "channel": 6,
    "frequency_mhz": 2437.0,
    "radio_type": "802.11ax",
    "adapter_name": "Wi-Fi 6 Adapter",
    "driver_version": "22.100.0.3",
    "sample_count": 5,
    "timestamp": "2026-09-21T10:00:00Z",
    "created_at": "2026-09-21T10:00:01Z"
  },
  "error_message": null
}
```

#### PARTIAL Measurement Example (`200 OK`)
**Response:**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "floor": "Floor 2",
  "x": 5.0,
  "y": 8.0,
  "status": "PARTIAL",
  "is_successful": true,
  "persisted": true,
  "valid_samples_count": 3,
  "sample_count": 5,
  "bssid_changed": false,
  "bssids_observed": [
    "00:11:22:33:44:55"
  ],
  "measurement": {
    "id": 102,
    "session_id": "sess_20260921_fl2_walk1",
    "floor": "Floor 2",
    "x": 5.0,
    "y": 8.0,
    "rssi_dbm": -60,
    "signal_percent": 80,
    "latency_ms": 12.0,
    "packet_loss_percent": 0.0,
    "throughput_mbps": 85.5,
    "ssid": "CAMPUS_WIFI",
    "bssid": "00:11:22:33:44:55",
    "channel": 6,
    "frequency_mhz": 2437.0,
    "radio_type": "802.11ax",
    "adapter_name": "Wi-Fi 6 Adapter",
    "driver_version": "22.100.0.3",
    "sample_count": 5,
    "timestamp": "2026-09-21T10:00:00Z",
    "created_at": "2026-09-21T10:00:01Z"
  },
  "error_message": "Partial collection: 3 of 5 samples valid"
}
```

#### FAILED Measurement Example (`502 Bad Gateway`)
**Response:**
```json
{
  "session_id": "sess_20260921_fl2_walk1",
  "floor": "Floor 2",
  "x": 0.0,
  "y": 0.0,
  "status": "FAILED",
  "is_successful": false,
  "persisted": false,
  "valid_samples_count": 0,
  "sample_count": 5,
  "bssid_changed": false,
  "bssids_observed": [],
  "measurement": null,
  "error_message": "All measurement samples failed or yielded no valid metrics"
}
```

---

## 5. Architectural Guarantees

1. **Strict NULL vs. Zero Fidelity**:
   - `packet_loss_percent: null` -> Network probe was unavailable or skipped.
   - `packet_loss_percent: 0.0` -> Zero packet loss was actively measured.
   - `throughput_mbps: null` -> Throughput test was not performed.
   - `rssi_dbm: null` -> Hardware driver did not report dBm value.
2. **Historical Append-Only Semantics**:
   - Every `POST /measurements` creates a new row with a unique auto-incrementing ID.
   - Repeated measurements at the same `(session_id, floor, x, y)` coordinate coexist to provide time-series history for heatmaps.
3. **Data & Credential Security**:
   - Error handlers return clean HTTP status codes (`400`, `404`, `409`, `422`, `500`) without exposing internal database connection strings, passwords, or raw SQL.
4. **Authentication Intentionally Deferred**:
   - User authentication and authorization (JWT, API tokens, user accounts) are intentionally deferred for this student project MVP to streamline local grid survey data collection.

---

## 6. Running Tests

Run the complete test suite:

```powershell
.venv\Scripts\pytest.exe -v
```

Run API tests only:

```powershell
.venv\Scripts\pytest.exe -v tests/test_api.py
```
