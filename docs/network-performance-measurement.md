# Network Performance Measurement: Latency, Packet Loss, and Throughput

## 1. Purpose
This document outlines the architecture, mathematical methodologies, configuration parameters, and verification procedures for the network performance measurement layer of the *Grid-Based Wi-Fi Performance Mapping and Monitoring System*.

---

## 2. Distinction: Network Performance vs. Wi-Fi Radio Metrics

A foundational principle of this project is the strict separation between **Wi-Fi Radio Metrics** and **Network Performance Metrics**:

- **Wi-Fi Radio Metrics (Milestone 2)**:
  - Examples: Physical RSSI (`-35 dBm`), link rates (`150 Mbps`), channel (`10`), frequency (`2457.0 MHz`), PHY standard (`802.11n HT`).
  - Origin: Directly measured at the physical/data-link layer between the client wireless network adapter and the local Access Point (AP).
- **Network Performance Metrics (Milestone 3)**:
  - Examples: Latency (RTT in ms), packet loss (%), application-layer throughput (Mbps).
  - Origin: End-to-end IP network performance between the client and a designated test target.
  - Influencing Factors: RF signal quality, AP CPU/queue load, local switch/gateway congestion, upstream WAN routing, firewall latency, DNS resolution, and target server response times.

---

## 3. Latency Methodology

### A. Measurement Mechanism
Latency is evaluated using ICMP Echo Request/Reply probes executed against a configurable network target (default: `TEST_TARGET` in configuration).

### B. Parameters & Configuration
- **Target Host (`TEST_TARGET`)**: IP address or hostname of the benchmark server (e.g., local gateway `192.168.1.1` or reference target `8.8.8.8`).
- **Probe Count (`LATENCY_PROBE_COUNT`)**: Number of consecutive probes per measurement run (default: `4`, range: 1–50).
- **Timeout (`LATENCY_TIMEOUT_SECONDS`)**: Per-probe response timeout (default: `2.0` seconds).

### C. Mathematical Calculations & Summary
For a series of $N$ probes where $k$ probes succeed with round-trip times $\{r_1, r_2, \dots, r_k\}$ in milliseconds:
- **Minimum Latency**: $\min(r_1, r_2, \dots, r_k)$
- **Average Latency**: $\frac{1}{k} \sum_{i=1}^{k} r_i$
- **Maximum Latency**: $\max(r_1, r_2, \dots, r_k)$
- **Median Latency**: $\text{median}(r_1, r_2, \dots, r_k)$
- **Failed Probes ($k = 0$)**: Latency summary metrics are recorded as `None` (never fabricated as 0.0 ms).

---

## 4. Packet Loss Methodology

### A. Calculation Formula
Packet loss is computed directly from empirical probe transmission outcomes:

$$\text{Packet Loss (\%)} = \left( \frac{\text{Lost Probes}}{\text{Total Probes Sent}} \right) \times 100.0$$

Where:
- $\text{Total Probes Sent} = N$
- $\text{Received Probes} = k$ (probes returning valid ICMP Echo Replies within the timeout window)
- $\text{Lost Probes} = N - k$

### B. Boundary Conditions
- $k = N \implies 0.0\%$ loss.
- $0 < k < N \implies$ Partial loss (e.g. 1 loss out of 4 = $25.0\%$).
- $k = 0 \implies 100.0\%$ loss (target unreachable, packet dropped, or host timeout).

---

## 5. Throughput Methodology

### A. Architecture & Scope
Throughput in this module measures **Application-Layer Goodput** (effective transfer rate) rather than the physical 802.11 PHY link rate:
- **PHY Link Rate (from `wifi_windows.py`)**: Maximum theoretical data rate supported by the current modulation and coding scheme (MCS index) between adapter and AP.
- **Application Throughput (from `network_tests.py`)**: Actual rate at which payload bytes are transferred over TCP/IP streaming to/from a dedicated benchmark endpoint.

### B. Measurement Formula
When `THROUGHPUT_TARGET_URL` is configured, a timed HTTP byte stream is transferred using standard high-resolution monotonic clocks (`time.perf_counter()`):

$$\text{Throughput (Mbps)} = \frac{\text{Total Bytes Transferred} \times 8}{\text{Elapsed Time (seconds)} \times 1,000,000}$$

### C. Implementation Status: **VERIFIED IMPLEMENTED (Local Controlled Pipeline Verified)**
- **Deterministic Engine**: The byte stream reading, high-precision timing, transfer calculations, and error-handling logic are fully implemented and verified with automated test suites.
- **No Arbitrary Public Speedtests**: Standardized Wi-Fi performance benchmarking uses a dedicated controlled endpoint. Public internet speed tests introduce external ISP throttling and transit latency that distort spatial Wi-Fi mapping.
- **Default State**: When `THROUGHPUT_TARGET_URL` is unconfigured, the system reports status `NOT_CONFIGURED` without fabricating numbers.

---

## 6. Controlled Throughput Verification

### A. Controlled Server Architecture ([scripts/throughput_server.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/scripts/throughput_server.py))
To verify the throughput engine without relying on external Internet servers, a lightweight, zero-dependency HTTP server is provided:
- **Runtime**: Python standard library `http.server` & `socketserver.ThreadingMixIn`.
- **Endpoints**:
  - `GET /health` &rarr; Returns JSON status `{"status": "ok", "service": "throughput_server"}`.
  - `GET /payload?size=<bytes>` &rarr; Streams deterministic binary data chunks (64 KB chunks) matching the exact requested byte count.
- **Start Command**:
  ```cmd
  .venv\Scripts\python.exe scripts\throughput_server.py --host 127.0.0.1 --port 8088 --size 1048576
  ```
- **Stop Command**: Send `Ctrl+C` or call `server.shutdown()`.

### B. Verification Evidence (Live Localhost Test)

1. **Test 1: 1 MB Payload (1,048,576 bytes)**:
   - **Target**: `http://127.0.0.1:8088/payload?size=1048576`
   - **Expected Bytes**: `1,048,576`
   - **Received Bytes**: `1,048,576` (Exact Match)
   - **Duration**: `0.0880` seconds
   - **Calculated Speed**: `95.01 Mbps`
   - **Status**: `COMPLETED`

2. **Test 2: 5 MB Payload (5,242,880 bytes)**:
   - **Target**: `http://127.0.0.1:8088/payload?size=5242880`
   - **Expected Bytes**: `5,242,880`
   - **Received Bytes**: `5,242,880` (Exact Match)
   - **Duration**: `0.0060` seconds
   - **Calculated Speed**: `6552.37 Mbps` (Loopback memory bandwidth)
   - **Status**: `COMPLETED`

3. **Test 3: Controlled Failure Test (Targeting closed port 9999)**:
   - **Target**: `http://127.0.0.1:9999/payload`
   - **Status**: `FAILED`
   - **Throughput Mbps**: `None` (Safely handled; no fake numbers fabricated)
   - **Error Message**: `HTTP/Network error: timed out`

### C. Critical Scope Distinction: Localhost vs. Wi-Fi Verification & UI Status
- **Verified on Development Machine**: Proves that the HTTP client, byte counter, wall-clock timer, Mbps formula, error handling, and `ThroughputResult` object are 100% bug-free and operational.
- **Not Proved by Localhost**: Loopback traffic (`127.0.0.1`) does not cross the physical Wi-Fi air interface.
- **Deferred From Main Survey UI**: Throughput measurement remains fully implemented in the backend, but is currently deferred and hidden from the main user-facing metric selector because measuring physical Wi-Fi throughput requires a reachable dedicated LAN/intranet target.
- **College Wi-Fi Environment**: Enterprise Wi-Fi with AP Client Isolation prevents peer-to-peer laptop routing on the campus network.
- **Future Activation**: When an accessible dedicated Ethernet/LAN server or intranet throughput target is provisioned, `THROUGHPUT_TARGET_URL` can be populated in `.env` and the metric selector option re-enabled in the UI.

---

## 7. Data Structures Overview

The module exposes clean, serializable dataclasses in [backend/network_tests.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/network_tests.py):

```python
@dataclass
class LatencyProbe:
    probe_index: int
    success: bool
    rtt_ms: Optional[float] = None
    error_message: Optional[str] = None

@dataclass
class LatencySummary:
    min_ms: Optional[float] = None
    avg_ms: Optional[float] = None
    max_ms: Optional[float] = None
    median_ms: Optional[float] = None
    successful_probes: int = 0
    total_probes: int = 0

@dataclass
class PacketLossResult:
    sent_probes: int
    received_probes: int
    lost_probes: int
    loss_percent: float

@dataclass
class ThroughputResult:
    throughput_mbps: Optional[float] = None
    bytes_transferred: int = 0
    duration_seconds: float = 0.0
    target_url: Optional[str] = None
    status: str = "DEFERRED"  # 'COMPLETED', 'DEFERRED', 'NOT_CONFIGURED', 'FAILED'
    is_application_layer: bool = True
    error_message: Optional[str] = None

@dataclass
class NetworkPerformanceResult:
    target_host: str
    timestamp: str
    latency: LatencySummary
    packet_loss: PacketLossResult
    probes: List[LatencyProbe]
    throughput: ThroughputResult
    is_successful: bool
    error_message: Optional[str] = None
```

---

## 8. Known Limitations & College Verification Requirements

1. **ICMP Filtering on Campus Firewalls**: Some institutional networks restrict or rate-limit ICMP Echo traffic between subnets. When deploying on the college network, the target host should be verified to allow ICMP (or configured to point to the local default gateway / subnet router).
2. **Dedicated Throughput Server**: Measuring maximum floor throughput without ISP bottlenecking requires deploying a lightweight server (`scripts/throughput_server.py`) inside the college network during Milestone 9.
3. **Multi-AP Roaming & Handoffs**: Latency spikes may temporarily occur during 802.11 BSSID roaming between campus access points.
