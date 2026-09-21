"""
backend/wifi_windows.py
Windows Native Wi-Fi Capability and Measurement Abstraction Module.

This module provides hardware-independent programmatic access to Wi-Fi connection
characteristics on Windows systems, utilizing the Windows Native Wi-Fi API (wlanapi.dll)
via standard-library ctypes, with a safe netsh fallback parser.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import platform
import re
import subprocess
from typing import Optional, Any, Dict


@dataclass
class WifiConnectionInfo:
    """
    Structured representation of current Wi-Fi connection characteristics.

    Fields:
        is_connected: True if an active Wi-Fi connection is established.
        ssid: Service Set Identifier (network name).
        bssid: Basic Service Set Identifier (MAC address of connected AP, e.g. 'b0:95:75:89:c1:04').
        signal_percent: Signal quality percentage (0 - 100%).
        rssi_dbm: Measured Received Signal Strength Indication in dBm (e.g. -35 dBm)
                  obtained from WLAN_BSS_ENTRY.lRssi. None if unexposed by API/driver.
        channel: Operational Wi-Fi channel number (e.g. 10, 36).
        frequency_mhz: Operational center frequency in MHz (e.g. 2457.0 MHz).
        radio_type: Wireless standard description (e.g. '802.11n (HT)', '802.11ac (VHT)').
        receive_rate_mbps: Link receive rate in Megabits per second (e.g. 150.0).
        transmit_rate_mbps: Link transmit rate in Megabits per second (e.g. 150.0).
        adapter_name: System interface name (e.g. 'Wi-Fi').
        adapter_description: Hardware description (e.g. 'Qualcomm Atheros QCA9377 Wireless Network Adapter').
        driver_provider: Driver provider/vendor (e.g. 'Qualcomm Atheros Communications Inc.').
        driver_version: Installed driver version string (e.g. '12.0.0.722').
        driver_date: Installed driver release date string (e.g. '2018-08-22').
        timestamp: ISO 8601 UTC timestamp of measurement acquisition.
        raw_source: Underlying query mechanism used ('native_wlanapi' or 'netsh_fallback').
    """

    is_connected: bool
    ssid: Optional[str] = None
    bssid: Optional[str] = None
    signal_percent: Optional[int] = None
    rssi_dbm: Optional[int] = None
    channel: Optional[int] = None
    frequency_mhz: Optional[float] = None
    radio_type: Optional[str] = None
    receive_rate_mbps: Optional[float] = None
    transmit_rate_mbps: Optional[float] = None
    adapter_name: Optional[str] = None
    adapter_description: Optional[str] = None
    driver_provider: Optional[str] = None
    driver_version: Optional[str] = None
    driver_date: Optional[str] = None
    timestamp: Optional[str] = None
    raw_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert connection data to dictionary."""
        return asdict(self)


# ----------------------------------------------------------------------
# Channel & Frequency Mapping Helpers
# ----------------------------------------------------------------------

def normalize_bssid(bssid: str | bytes | None) -> Optional[str]:
    """Normalize BSSID / MAC address to lowercase colon-delimited format."""
    if bssid is None:
        return None
    if isinstance(bssid, bytes):
        return ":".join(f"{b:02x}" for b in bssid)
    cleaned = re.sub(r"[^0-9a-fA-F]", "", bssid)
    if len(cleaned) == 12:
        return ":".join(cleaned[i : i + 2].lower() for i in range(0, 12, 2))
    return bssid.strip().lower()


def frequency_to_channel(freq_mhz: float | None) -> Optional[int]:
    """
    Derive IEEE standard Wi-Fi channel from frequency in MHz.

    Supports 2.4 GHz, 5 GHz, and 6 GHz Wi-Fi frequency plans.
    """
    if freq_mhz is None:
        return None
    freq_int = int(round(freq_mhz))

    # 2.4 GHz Band (Channels 1 - 13)
    if 2412 <= freq_int <= 2472:
        if (freq_int - 2407) % 5 == 0:
            return (freq_int - 2407) // 5
    # 2.4 GHz Band (Channel 14 - Japan)
    elif freq_int == 2484:
        return 14
    # 5 GHz Band (Channels 36 - 177)
    elif 5000 <= freq_int <= 5900:
        if (freq_int - 5000) % 5 == 0:
            return (freq_int - 5000) // 5
    # 6 GHz Band (Channels 1 - 233)
    elif 5950 <= freq_int <= 7115:
        if (freq_int - 5950) % 5 == 0:
            return (freq_int - 5950) // 5

    return None


def channel_to_frequency(channel: int | None, band: str = "2.4GHz") -> Optional[float]:
    """Derive standard center frequency in MHz from channel number and band."""
    if channel is None or channel <= 0:
        return None
    if band == "2.4GHz":
        if 1 <= channel <= 13:
            return float(2407 + 5 * channel)
        elif channel == 14:
            return 2484.0
    elif band == "5GHz":
        if 7 <= channel <= 180:
            return float(5000 + 5 * channel)
    elif band == "6GHz":
        if 1 <= channel <= 233:
            return float(5950 + 5 * channel)
    return None


def phy_type_to_str(phy_type: int | None) -> Optional[str]:
    """Map Windows DOT11_PHY_TYPE enum integer to human-readable radio standard."""
    if phy_type is None:
        return None
    mapping = {
        0: "Unknown",
        1: "802.11 FHSS",
        2: "802.11 DSSS",
        3: "802.11 IR Baseband",
        4: "802.11a (OFDM)",
        5: "802.11b (HRDSSS)",
        6: "802.11g (ERP)",
        7: "802.11n (HT)",
        8: "802.11ac (VHT)",
        9: "802.11ax (HE)",
        10: "802.11be (EHT)",
    }
    return mapping.get(phy_type, f"DOT11_PHY_TYPE_{phy_type}")


# ----------------------------------------------------------------------
# Windows Native Wi-Fi API Ctypes Structures
# ----------------------------------------------------------------------

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

    def __str__(self) -> str:
        d4 = bytes(self.Data4)
        return (
            f"{{{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-"
            f"{d4[:2].hex()}-{d4[2:].hex()}}}"
        )


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", wintypes.WCHAR * 256),
        ("isState", wintypes.DWORD),
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", wintypes.DWORD),
        ("dwIndex", wintypes.DWORD),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class DOT11_SSID(ctypes.Structure):
    _fields_ = [
        ("uSSIDLength", wintypes.ULONG),
        ("ucSSID", ctypes.c_char * 32),
    ]

    def to_string(self) -> str:
        length = min(self.uSSIDLength, 32)
        return self.ucSSID[:length].decode("utf-8", errors="replace")


class WLAN_ASSOCIATION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", wintypes.DWORD),
        ("dot11Bssid", wintypes.BYTE * 6),
        ("dot11PhyType", wintypes.DWORD),
        ("uDot11PhyIndex", wintypes.ULONG),
        ("wlanSignalQuality", wintypes.ULONG),
        ("ulRxRate", wintypes.ULONG),
        ("ulTxRate", wintypes.ULONG),
    ]


class WLAN_SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("bSecurityEnabled", wintypes.BOOL),
        ("bOneXEnabled", wintypes.BOOL),
        ("dot11AuthAlgorithm", wintypes.DWORD),
        ("dot11CipherAlgorithm", wintypes.DWORD),
    ]


class WLAN_CONNECTION_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("isState", wintypes.DWORD),
        ("wlanConnectionMode", wintypes.DWORD),
        ("strProfileName", wintypes.WCHAR * 256),
        ("wlanAssociationAttributes", WLAN_ASSOCIATION_ATTRIBUTES),
        ("wlanSecurityAttributes", WLAN_SECURITY_ATTRIBUTES),
    ]


class WLAN_RATE_SET(ctypes.Structure):
    _fields_ = [
        ("uRateSetLength", wintypes.ULONG),
        ("usRateSet", wintypes.USHORT * 126),
    ]


class WLAN_BSS_ENTRY(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("uPhyId", wintypes.ULONG),
        ("dot11Bssid", wintypes.BYTE * 6),
        ("dot11BssType", wintypes.DWORD),
        ("dot11BssPhyType", wintypes.DWORD),
        ("lRssi", ctypes.c_long),  # DOT11_RSSI in dBm (e.g. -35)
        ("uLinkQuality", wintypes.ULONG),  # 0 - 100%
        ("bInRegDomain", wintypes.BOOLEAN),
        ("usBeaconPeriod", wintypes.USHORT),
        ("ullTimestamp", ctypes.c_uint64),
        ("ullHostTimestamp", ctypes.c_uint64),
        ("usCapabilityInformation", wintypes.USHORT),
        ("ulChCenterFrequency", wintypes.ULONG),  # in kHz
        ("wlanRateSet", WLAN_RATE_SET),
        ("ulIeOffset", wintypes.ULONG),
        ("ulIeSize", wintypes.ULONG),
    ]


def _get_driver_details() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Retrieve driver provider, version, and date from netsh wlan show drivers."""
    provider, version, date = None, None, None
    try:
        res = subprocess.run(
            ["netsh", "wlan", "show", "drivers"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                line_str = line.strip()
                if line_str.startswith("Vendor") and ":" in line_str and not provider:
                    provider = line_str.split(":", 1)[-1].strip()
                elif line_str.startswith("Version") and ":" in line_str and not version:
                    version = line_str.split(":", 1)[-1].strip()
                elif line_str.startswith("Date") and ":" in line_str and not date:
                    date = line_str.split(":", 1)[-1].strip()
    except Exception:
        pass
    return provider, version, date


# ----------------------------------------------------------------------
# Primary Native Implementation
# ----------------------------------------------------------------------

def _query_native_wlanapi() -> Optional[WifiConnectionInfo]:
    """
    Query the active Wi-Fi connection using Windows Native Wi-Fi API (wlanapi.dll).

    Returns:
        WifiConnectionInfo populated with exact physical metrics (including dBm RSSI
        and center frequency) if connected, or None if wlanapi fails.
    """
    if platform.system().lower() != "windows":
        return None

    try:
        wlanapi = ctypes.windll.wlanapi
    except Exception:
        return None

    h_client = wintypes.HANDLE()
    negotiated_ver = wintypes.DWORD()
    ret = wlanapi.WlanOpenHandle(2, None, ctypes.byref(negotiated_ver), ctypes.byref(h_client))
    if ret != 0:
        return None

    p_if_list = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
    try:
        ret = wlanapi.WlanEnumInterfaces(h_client, None, ctypes.byref(p_if_list))
        if ret != 0 or not p_if_list or p_if_list.contents.dwNumberOfItems == 0:
            return WifiConnectionInfo(
                is_connected=False,
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw_source="native_wlanapi",
            )

        num_interfaces = p_if_list.contents.dwNumberOfItems

        class REAL_INTERFACE_LIST(ctypes.Structure):
            _fields_ = [
                ("dwNumberOfItems", wintypes.DWORD),
                ("dwIndex", wintypes.DWORD),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * num_interfaces),
            ]

        real_if_list = ctypes.cast(
            p_if_list, ctypes.POINTER(REAL_INTERFACE_LIST)
        ).contents

        # Find connected interface
        driver_provider, driver_ver, driver_date = _get_driver_details()

        for i in range(num_interfaces):
            if_item = real_if_list.InterfaceInfo[i]
            guid = if_item.InterfaceGuid
            desc = if_item.strInterfaceDescription

            # Query current connection
            p_data_size = wintypes.DWORD()
            p_data = ctypes.c_void_p()
            opcode_type = wintypes.DWORD()
            wlan_intf_opcode_current_connection = 7

            ret_query = wlanapi.WlanQueryInterface(
                h_client,
                ctypes.byref(guid),
                wlan_intf_opcode_current_connection,
                None,
                ctypes.byref(p_data_size),
                ctypes.byref(p_data),
                ctypes.byref(opcode_type),
            )

            if ret_query != 0 or not p_data.value:
                continue

            try:
                conn_attr = ctypes.cast(
                    p_data, ctypes.POINTER(WLAN_CONNECTION_ATTRIBUTES)
                ).contents
                assoc = conn_attr.wlanAssociationAttributes
                ssid = assoc.dot11Ssid.to_string()
                bssid = normalize_bssid(bytes(assoc.dot11Bssid))
                signal_percent = int(assoc.wlanSignalQuality)
                rx_rate_mbps = round(assoc.ulRxRate / 1000.0, 2)
                tx_rate_mbps = round(assoc.ulTxRate / 1000.0, 2)
                phy_type = assoc.dot11PhyType
                radio_type = phy_type_to_str(phy_type)

                rssi_dbm = None
                frequency_mhz = None
                channel = None

                # Query BSS list to retrieve exact physical dBm RSSI and Center Frequency
                p_bss_list = ctypes.c_void_p()
                ret_bss = wlanapi.WlanGetNetworkBssList(
                    h_client,
                    ctypes.byref(guid),
                    None,
                    3,     # dot11_BSS_type_any
                    False, # bSecurityEnabled
                    None,
                    ctypes.byref(p_bss_list),
                )

                if ret_bss == 0 and p_bss_list.value:
                    try:
                        header = ctypes.cast(
                            p_bss_list, ctypes.POINTER(wintypes.DWORD * 2)
                        ).contents
                        num_bss = header[1]
                        current_ptr = p_bss_list.value + 8  # Skip header

                        for _ in range(num_bss):
                            entry = WLAN_BSS_ENTRY.from_address(current_ptr)
                            entry_bssid = normalize_bssid(bytes(entry.dot11Bssid))
                            if entry_bssid and bssid and entry_bssid.lower() == bssid.lower():
                                rssi_dbm = int(entry.lRssi)
                                if entry.ulChCenterFrequency > 0:
                                    frequency_mhz = round(entry.ulChCenterFrequency / 1000.0, 2)
                                    channel = frequency_to_channel(frequency_mhz)
                                break
                            current_ptr += (entry.ulIeOffset + entry.ulIeSize)
                    finally:
                        wlanapi.WlanFreeMemory(p_bss_list)

                return WifiConnectionInfo(
                    is_connected=True,
                    ssid=ssid,
                    bssid=bssid,
                    signal_percent=signal_percent,
                    rssi_dbm=rssi_dbm,
                    channel=channel,
                    frequency_mhz=frequency_mhz,
                    radio_type=radio_type,
                    receive_rate_mbps=rx_rate_mbps,
                    transmit_rate_mbps=tx_rate_mbps,
                    adapter_name="Wi-Fi",
                    adapter_description=desc,
                    driver_provider=driver_provider,
                    driver_version=driver_ver,
                    driver_date=driver_date,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw_source="native_wlanapi",
                )
            finally:
                wlanapi.WlanFreeMemory(p_data)

        return WifiConnectionInfo(
            is_connected=False,
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw_source="native_wlanapi",
        )

    finally:
        if p_if_list:
            wlanapi.WlanFreeMemory(p_if_list)
        wlanapi.WlanCloseHandle(h_client, None)


# ----------------------------------------------------------------------
# Netsh Fallback Implementation
# ----------------------------------------------------------------------

def _query_netsh_fallback() -> WifiConnectionInfo:
    """
    Fallback parser using netsh wlan show interfaces.

    Note:
        netsh does NOT expose dBm RSSI. rssi_dbm will be returned as None.
    """
    now_ts = datetime.now(timezone.utc).isoformat()
    try:
        res = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            check=False,
            timeout=6,
        )
        if res.returncode != 0:
            return WifiConnectionInfo(
                is_connected=False, timestamp=now_ts, raw_source="netsh_fallback"
            )

        out = res.stdout
        if "State" not in out or "connected" not in out.lower():
            return WifiConnectionInfo(
                is_connected=False, timestamp=now_ts, raw_source="netsh_fallback"
            )

        info: Dict[str, Any] = {}
        for line in out.splitlines():
            line_str = line.strip()
            if ":" in line_str:
                k, v = [part.strip() for part in line_str.split(":", 1)]
                info[k] = v

        if info.get("State", "").lower() != "connected":
            return WifiConnectionInfo(
                is_connected=False, timestamp=now_ts, raw_source="netsh_fallback"
            )

        ssid = info.get("SSID")
        bssid = normalize_bssid(info.get("BSSID"))
        signal_raw = info.get("Signal", "")
        signal_percent = None
        if "%" in signal_raw:
            try:
                signal_percent = int(signal_raw.replace("%", "").strip())
            except ValueError:
                pass

        channel = None
        if "Channel" in info:
            try:
                channel = int(info["Channel"])
            except ValueError:
                pass

        frequency_mhz = channel_to_frequency(channel, "2.4GHz") if channel else None
        radio_type = info.get("Radio type")

        rx_rate = None
        tx_rate = None
        if "Receive rate (Mbps)" in info:
            try:
                rx_rate = float(info["Receive rate (Mbps)"])
            except ValueError:
                pass
        if "Transmit rate (Mbps)" in info:
            try:
                tx_rate = float(info["Transmit rate (Mbps)"])
            except ValueError:
                pass

        driver_provider, driver_ver, driver_date = _get_driver_details()

        return WifiConnectionInfo(
            is_connected=True,
            ssid=ssid,
            bssid=bssid,
            signal_percent=signal_percent,
            rssi_dbm=None,  # netsh does not provide dBm
            channel=channel,
            frequency_mhz=frequency_mhz,
            radio_type=radio_type,
            receive_rate_mbps=rx_rate,
            transmit_rate_mbps=tx_rate,
            adapter_name=info.get("Name", "Wi-Fi"),
            adapter_description=info.get("Description"),
            driver_provider=driver_provider,
            driver_version=driver_ver,
            driver_date=driver_date,
            timestamp=now_ts,
            raw_source="netsh_fallback",
        )
    except Exception:
        return WifiConnectionInfo(
            is_connected=False, timestamp=now_ts, raw_source="netsh_fallback"
        )


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def get_current_wifi_info() -> WifiConnectionInfo:
    """
    Retrieve the current Wi-Fi connection information on Windows.

    Uses Windows Native Wi-Fi API (wlanapi.dll) as the primary provider to obtain
    true physical RSSI in dBm and center frequency. Falls back to netsh CLI parsing
    if the Native API cannot be queried.

    Returns:
        WifiConnectionInfo instance.
    """
    info = _query_native_wlanapi()
    if info is not None:
        return info
    return _query_netsh_fallback()
