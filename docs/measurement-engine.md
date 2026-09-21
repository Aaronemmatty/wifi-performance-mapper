# Measurement Engine & Measurement Service Architecture

## 1. Purpose & Responsibility

The **Measurement Engine** ([backend/measurement.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/measurement.py)) and **Measurement Service** ([backend/measurement_service.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/measurement_service.py)) form the application orchestration layer of the *Grid-Based Wi-Fi Performance Mapping and Monitoring System*.

Together, they perform reliable multi-metric survey measurements at designated physical grid coordinates $(floor, x, y)$ by combining:
1. **Windows Wi-Fi Measurement Layer** ([backend/wifi_windows.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/wifi_windows.py)) — RF metrics and AP metadata.
2. **Network Performance Layer** ([backend/network_tests.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/network_tests.py)) — End-to-end IP metrics (latency, packet loss, throughput).
3. **PostgreSQL Persistence Layer** ([backend/repository.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/repository.py)) — Historical append-only survey data persistence.

```text
┌─────────────────────────────────────────────────────────────┐
│                    Physical Grid Location                   │
│                     (floor, x, y)                           │
└──────────────────────────────┬──────────────────────────────┘
                               │
               ┌───────────────▼───────────────┐
               │    Collect Sample 1 (Wi-Fi+Net)│
               │    Collect Sample 2 (Wi-Fi+Net)│
               │    Collect Sample 3 (Wi-Fi+Net)│
               │    Collect Sample 4 (Wi-Fi+Net)│
               │    Collect Sample 5 (Wi-Fi+Net)│
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │  Filter None/Errors & Compute │
               │   Mathematical Medians        │
               │  Track BSSID Roaming & Status │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │     AggregatedMeasurement     │
               │ (Canonical Result + Raw Data) │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │   M7 Measurement Service      │
               │ (Evaluate Persistence Policy) │
               └───────────────┬───────────────┘
                               │
               ┌───────────────▼───────────────┐
               │    Repository / PostgreSQL    │
               │  (Append-only DB Record)      │
               └───────────────────────────────┘
```

---

## 2. Architectural Boundaries & Non-Responsibilities

To maintain clean modular boundaries:
- **Measurement Engine (`backend/measurement.py`)**: Responsible solely for multi-sample loop execution, median mathematics, failure isolation, and BSSID roaming tracking. Contains no SQL or DB logic.
- **Measurement Service (`backend/measurement_service.py`)**: Responsible for orchestrating the engine call, evaluating persistence policy based on `status`, mapping scalar medians to the repository contract, and returning the combined outcome (`MeasurementServiceResult`).
- **Repository (`backend/repository.py`)**: Responsible for executing parameterized SQL against PostgreSQL.
- **No Direct Hardware Query Internals in Service**: Hardware access belongs strictly to M2/M3.

---

## 3. Five-Sample Workflow & Explicit Sample Status

By default, the engine executes `sample_count = 5` (configurable positive integer $\ge 1$).

### A. Explicit Collection Status:
- **`COMPLETE`**: Exactly all requested samples were successfully collected with valid data (`valid_samples_count == sample_count`). E.g. `5/5` $\to$ `COMPLETE` (`is_successful = True`).
- **`PARTIAL`**: At least one sample was valid, but some requested samples failed (`0 < valid_samples_count < sample_count`). E.g. `4/5`, `3/5`, `1/5` $\to$ `PARTIAL` (`is_successful = True`).
- **`FAILED`**: Zero valid samples were obtained (`valid_samples_count == 0`). E.g. `0/5` $\to$ `FAILED` (`is_successful = False`).

### B. Sample Independence:
1. **Fresh Invocations**: Every sample loop iteration independently invokes `wifi_provider()` and `net_provider()`. Samples are never duplicated or cloned from earlier samples.
2. **Isolated Exception Handling**: If an underlying driver or network call raises an unhandled exception during one sample, the exception is caught, recorded in that sample's `SingleSampleResult.error_message`, and the loop proceeds to collect the remaining samples.
3. **Independent Timestamps**: Each `SingleSampleResult` preserves its individual ISO 8601 UTC acquisition timestamp.
4. **Post-Collection Aggregation**: Statistical aggregation occurs only after all configured samples have finished collection.

---

## 4. Median Methodology & Packet-Loss Aggregation

Radio frequency and IP network measurements are susceptible to short-duration anomalies (e.g. sporadic background broadcast traffic or transient AP scheduling spikes). The median provides a robust central tendency resistant to one-off outliers.

### A. Mathematical Median Rules (`calculate_median`):
- **Filtering**: `None`, `NaN`, and infinite values are filtered out.
- **Odd Sample Count ($k$ valid samples)**:
  $$\text{median} = S_{\lfloor k / 2 \rfloor} \quad (\text{where } S \text{ is the sorted valid array})$$
  *Example*: `[-70, -65, -68, -72, -66]` $\to$ Sorted `[-72, -70, -68, -66, -65]` $\to$ Median = `-68.0`.
- **Even Sample Count ($k$ valid samples)**:
  $$\text{median} = \frac{S_{(k/2) - 1} + S_{k/2}}{2.0}$$
  *Example*: `[-70, -60, -80, -90]` $\to$ Sorted `[-90, -80, -70, -60]` $\to$ Median = `-75.0`.
- **Single Valid Sample**: Returns that exact value ($k = 1 \implies \text{median} = S_0$).
- **Zero Preservation**: True `0.0` values (e.g. `0.0%` packet loss, `0.0 ms` latency) are strictly preserved and distinct from `None`.
- **Missing Value Handling**: If all samples for a specific metric are `None`, the calculated median is `None`. **`None` is NEVER converted to `0` or an arbitrary default.**

### B. Packet-Loss Aggregation:
- **Locked Project Definition**: Packet loss for a 5-sample survey point is defined as the **median of the valid sample-level packet-loss percentages**:
  $$\text{Aggregate Packet Loss} = \text{median}(L_1, L_2, L_3, L_4, L_5)$$
- *Example*: Samples with `[0%, 0%, 0%, 100%, 100%]` $\to$ Aggregate packet loss = `0.0%`.
- *Example*: Samples with `[0%, 25%, 50%, 75%, 100%]` $\to$ Aggregate packet loss = `50.0%`.
- Genuine `0.0%` and `100.0%` values are preserved as numbers; only genuinely missing data yields `None`.

---

## 5. BSSID Roaming Handling

During building grid surveys, a client device may roam between access points while staying connected to the campus SSID. Roaming does **not** invalidate the measurement.

### Roaming Tracking Rules:
1. **Raw Sample Integrity**: Each `SingleSampleResult` preserves the exact `bssid` associated with that individual sample.
2. **Roaming Indicator (`bssid_changed: bool`)**:
   - `bssid_changed = False` when all valid (non-None) BSSIDs in the collection are identical (or $\le 1$ valid BSSID observed).
   - `bssid_changed = True` when two or more distinct valid BSSIDs occur across the samples (e.g. `[A, A, B, B, B]` $\to$ `True`).
   - Missing/None samples are ignored when evaluating distinct BSSIDs (e.g. `[A, A, None, A, A]` $\to$ `False`).
3. **Observed BSSIDs (`bssids_observed: List[str]`)**: Deterministic, deduplicated list of all valid BSSID strings encountered during the multi-sample measurement.
4. **Summary BSSID**: The summary metadata fields (`bssid`, `channel`, `frequency_mhz`, etc.) reflect the latest valid connected Wi-Fi sample, while `rssi_dbm` represents the mathematical median of all valid RSSI readings across the roamed APs.

---

## 6. Persistence Integration Policy (Milestone 7)

The `Measurement Service` applies explicit persistence rules based on measurement status:

| Status | Persistence Decision | Behavior |
| :--- | :--- | :--- |
| **`COMPLETE`** | **PERSISTED** | Canonical scalar medians (`rssi_dbm`, `latency_ms`, `packet_loss_percent`, `throughput_mbps`, `ssid`, `bssid`, etc.) are written to PostgreSQL `measurements` table. `persisted = True`. |
| **`PARTIAL`** | **PERSISTED** | Usable scalar medians calculated over valid samples are persisted to PostgreSQL. `persisted = True`, `status = "PARTIAL"`, `error_message` records partial sample counts. |
| **`FAILED`** | **REJECTED / NOT PERSISTED** | No database row is created. Prevents pollution of spatial heatmaps with empty/zero dummy rows. `persisted = False`, `status = "FAILED"`. |

### Key Persistence Principles:
1. **NULL Value Preservation**: Unmeasured or unavailable metrics (e.g. unconfigured throughput or failed latency) are stored as SQL `NULL` and never coerced to `0`.
2. **Historical Append-Only**: Repeated survey passes at the same $(session\_id, floor, x, y)$ append new historical rows with unique IDs. No overwriting or deduplication occurs.
3. **No Schema Migration Required**: The canonical scalar fields map directly to the existing M4 `measurements` table schema. Transient collection metadata (`raw_samples`, `status`, `bssid_changed`) remains in the domain return object.

---

## 7. Canonical Data Models

### Engine Models ([backend/measurement.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/measurement.py)):
```python
@dataclass
class SingleSampleResult:
    sample_index: int
    timestamp: str
    wifi_info: Optional[WifiConnectionInfo] = None
    network_result: Optional[NetworkPerformanceResult] = None
    is_successful: bool = True
    error_message: Optional[str] = None

@dataclass
class AggregatedMeasurement:
    floor: str
    x: float
    y: float
    sample_count: int
    valid_samples_count: int
    timestamp: str
    status: str = "COMPLETE"
    is_successful: bool = True
    rssi_dbm: Optional[int] = None
    signal_percent: Optional[int] = None
    latency_ms: Optional[float] = None
    packet_loss_percent: Optional[float] = None
    throughput_mbps: Optional[float] = None
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
    raw_samples: List[SingleSampleResult] = field(default_factory=list)
    error_message: Optional[str] = None
```

### Service Model ([backend/measurement_service.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/measurement_service.py)):
```python
@dataclass
class MeasurementServiceResult:
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
```

---

## 8. Verification Evidence

### Automated Test Suite
- **Command**: `.venv\Scripts\pytest.exe -v`
- **Total Tests**: **109**
- **Passed**: **109**
- **Failed**: **0**
- **Skipped**: **0**
- **Errors**: **0**

### Live PostgreSQL Integration Test:
- Verified on `wifi_performance_mapper_test` database:
  - `COMPLETE` measurement persisted and retrieved.
  - `PARTIAL` measurement persisted with accurate valid sample medians.
  - `FAILED` measurement rejected without creating database row.
  - `NULL` values preserved as SQL `NULL`.
  - Historical measurements at identical coordinates coexist as distinct rows.
  - Foreign key validation on `session_id` enforced.
  - Test session and measurement cleanup executed cleanly.
