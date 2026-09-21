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

#### `GET /sessions/{session_id}`
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

#### `GET /measurements?session_id=sess_20260921_fl2_walk1&floor=Floor%202`
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
    "sample_count": 5,
    "timestamp": "2026-09-21T15:46:10.000000Z",
    "created_at": "2026-09-21T15:46:10.045000Z"
  }
]
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
