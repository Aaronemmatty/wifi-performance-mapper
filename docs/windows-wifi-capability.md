# Windows Wi-Fi Measurement Capability & API Findings

## Overview
This document records the empirical findings, API investigations, and hardware capabilities verified during **Milestone 2** for the *Grid-Based Wi-Fi Performance Mapping and Monitoring System*.

---

## 1. Hardware & Environment Tested

| Property | Value / Details |
|---|---|
| **Operating System** | Microsoft Windows 10 (Build 10.0.19045.6466, AMD64 64-bit) |
| **Wi-Fi Adapter** | Qualcomm Atheros QCA9377 Wireless Network Adapter |
| **Physical MAC Address** | `f8:28:19:4e:6c:a1` |
| **Driver Provider** | Qualcomm Atheros Communications Inc. / Microsoft |
| **Driver Version** | `12.0.0.722` (Driver Date: 2018-08-22) |
| **Driver Type** | Native Wi-Fi Driver (`netathr10x.inf`, NDIS 6.50) |
| **Current Connection** | Connected to SSID `THOMAS`, BSSID `b0:95:75:89:c1:04` |

---

## 2. Windows APIs Investigated

### A. Windows CLI (`netsh wlan`)
- **Commands Tested**:
  - `netsh wlan show interfaces`
  - `netsh wlan show drivers`
  - `netsh wlan show networks mode=bssid`
- **Findings**:
  - Exposes SSID, BSSID, Signal Quality Percentage (`0% - 100%`), Channel, Radio Type (`802.11n`), Link Rates (Rx / Tx), and Driver Details.
  - **Does NOT expose physical RSSI in dBm**. Only reports a normalized integer percentage.
  - Implemented as a secondary fallback parser in [backend/wifi_windows.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/wifi_windows.py) where `rssi_dbm` is explicitly kept as `None`.

### B. WMI / CIM (`root\wmi`)
- **Class Tested**: `MSNdis_80211_ReceivedSignalStrength`
- **Findings**: Unsupported / not exposed by modern Windows Native Wi-Fi drivers (returns empty or class error).

### C. Windows Native Wi-Fi API (`wlanapi.dll` via `ctypes`)
- **Functions Tested**:
  - `WlanOpenHandle`: Opens a client handle to the WLAN service.
  - `WlanEnumInterfaces`: Enumerates active WLAN adapters.
  - `WlanQueryInterface` (`wlan_intf_opcode_current_connection` / opcode 7): Retrieves `WLAN_CONNECTION_ATTRIBUTES` and `WLAN_ASSOCIATION_ATTRIBUTES` (SSID, BSSID, Signal Quality %, PHY Type, Rx/Tx rates in kbps).
  - `WlanGetNetworkBssList`: Queries `WLAN_BSS_ENTRY` records for the interface.
- **Findings & Breakthrough**:
  - `WLAN_BSS_ENTRY.lRssi` (type `DOT11_RSSI` / `c_long`) returns the **true measured physical RSSI in dBm** (e.g., `-33 dBm`, `-25 dBm`, `-35 dBm`).
  - `WLAN_BSS_ENTRY.ulChCenterFrequency` returns the **exact channel center frequency in kHz** (e.g., `2457000 kHz` = `2457.0 MHz`), matching IEEE 802.11 Channel 10.
  - Tested repeatedly with dynamic variation reflecting true RF signal conditions.

---

## 3. Confirmed Wi-Fi Fields

| Field | Obtained? | API / Source | Unit / Example Value | Verification Status |
|---|---|---|---|---|
| **SSID** | YES | `WlanQueryInterface` / `netsh` | String (`THOMAS`) | **VERIFIED** |
| **BSSID** | YES | `WlanQueryInterface` / `WlanGetNetworkBssList` | MAC String (`b0:95:75:89:c1:04`) | **VERIFIED** |
| **Signal Quality** | YES | `WLAN_ASSOCIATION_ATTRIBUTES.wlanSignalQuality` | Percentage (`100%`) | **VERIFIED** |
| **RSSI dBm** | YES | `WLAN_BSS_ENTRY.lRssi` (`wlanapi.dll`) | Signed integer dBm (`-33 dBm`) | **VERIFIED** |
| **Channel** | YES | Derived from `ulChCenterFrequency` & `netsh` | Integer (`10`) | **VERIFIED** |
| **Center Frequency** | YES | `WLAN_BSS_ENTRY.ulChCenterFrequency` | Float MHz (`2457.0 MHz`) | **VERIFIED** |
| **Radio Standard** | YES | `WLAN_ASSOCIATION_ATTRIBUTES.dot11PhyType` | String (`802.11n (HT)`) | **VERIFIED** |
| **Receive Rate** | YES | `WLAN_ASSOCIATION_ATTRIBUTES.ulRxRate` | Float Mbps (`150.0 Mbps`) | **VERIFIED** |
| **Transmit Rate** | YES | `WLAN_ASSOCIATION_ATTRIBUTES.ulTxRate` | Float Mbps (`150.0 Mbps`) | **VERIFIED** |
| **Adapter Name & Description** | YES | `WlanEnumInterfaces` / `netsh` | `Wi-Fi` / `Qualcomm Atheros QCA9377...` | **VERIFIED** |
| **Driver Info** | YES | `netsh wlan show drivers` | `Qualcomm Atheros Communications Inc.` (v12.0.0.722, 22-08-2018) | **VERIFIED** |
| **Timestamp** | YES | Python `datetime.now(timezone.utc)` | ISO 8601 UTC timestamp | **VERIFIED** |

---

## 4. RSSI Decision & Technical Explanation

### Decision: **VERIFIED**

### Evidence:
1. **API Ground Truth**: In Microsoft Windows Native Wi-Fi SDK (`wlanapi.h`), `WLAN_BSS_ENTRY.lRssi` is defined as:
   ```c
   DOT11_RSSI lRssi; // The RSSI value, in units of decibels relative to 1 milliwatt (dBm).
   ```
2. **Empirical Measurement**: Real-time queries against the Qualcomm Atheros QCA9377 adapter return dynamic negative integers (such as `-25 dBm`, `-33 dBm`, `-35 dBm`) that accurately correlate with physical RF power levels.
3. **Strict Separation from Signal Percentage**: Signal quality (`100%`) is kept strictly separate from RSSI dBm (`-33 dBm`). No mathematical approximations (such as `signal_percent - 100`) are used.
4. **Fallback Safety**: In the event that the Native Wi-Fi API cannot be loaded or fails, the netsh fallback safely sets `rssi_dbm = None` rather than fabricating a value.

---

## 5. Architectural Isolation & Abstraction

The Wi-Fi measurement capability is encapsulated in [backend/wifi_windows.py](file:///c:/Users/emmat/Downloads/wifi-performance-mapper/backend/wifi_windows.py).
Upper layers (such as the upcoming measurement engine and FastAPI service) interact with the Wi-Fi subsystem solely through:

```python
from backend.wifi_windows import get_current_wifi_info

wifi_info: WifiConnectionInfo = get_current_wifi_info()
```

This guarantees complete hardware independence for future milestones and enables seamless integration with other operating systems or secondary test laptops.

---

## 6. Limitations & Future Hardware Compatibility

1. **Host-Specific Chipset**: The current development environment uses a Qualcomm Atheros QCA9377. Different Wi-Fi adapters (such as Intel AX200/AX210, Realtek, or MediaTek chipsets on the secondary laptop during the college survey) may report different RSSI sampling intervals or PHY types (e.g. 802.11ax Wi-Fi 6).
2. **Frequency Bands**: The channel calculation helper currently supports 2.4 GHz (channels 1–14), 5 GHz (UNII 1–3, channels 36–177), and 6 GHz (Wi-Fi 6E/7, channels 1–233).
3. **Association Requirement**: `WlanGetNetworkBssList` reports BSS entries visible to the adapter. If the adapter is disconnected, `is_connected` is reported as `False` and metric fields remain `None`.
