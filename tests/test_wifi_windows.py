"""
tests/test_wifi_windows.py
Unit tests for backend/wifi_windows.py Wi-Fi information abstraction.
"""

import sys
import platform
import pytest
from datetime import datetime
from backend.wifi_windows import (
    WifiConnectionInfo,
    get_current_wifi_info,
    normalize_bssid,
    frequency_to_channel,
    channel_to_frequency,
    phy_type_to_str,
    _query_netsh_fallback,
)


def test_wifi_connection_info_dataclass():
    """Verify dataclass instantiates with defaults and converts to dict."""
    info = WifiConnectionInfo(is_connected=False)
    assert info.is_connected is False
    assert info.ssid is None
    assert info.rssi_dbm is None
    assert info.signal_percent is None

    d = info.to_dict()
    assert isinstance(d, dict)
    assert d["is_connected"] is False


def test_normalize_bssid():
    """Test MAC address normalization across different formats."""
    assert normalize_bssid("B0-95-75-89-C1-04") == "b0:95:75:89:c1:04"
    assert normalize_bssid("b0:95:75:89:c1:04") == "b0:95:75:89:c1:04"
    assert normalize_bssid("b0957589c104") == "b0:95:75:89:c1:04"
    assert normalize_bssid(b"\xb0\x95\x75\x89\xc1\x04") == "b0:95:75:89:c1:04"
    assert normalize_bssid(None) is None


def test_frequency_to_channel_24ghz():
    """Test 2.4 GHz channel derivation from frequency in MHz."""
    assert frequency_to_channel(2412.0) == 1
    assert frequency_to_channel(2437.0) == 6
    assert frequency_to_channel(2457.0) == 10
    assert frequency_to_channel(2462.0) == 11
    assert frequency_to_channel(2472.0) == 13
    assert frequency_to_channel(2484.0) == 14
    assert frequency_to_channel(2500.0) is None
    assert frequency_to_channel(None) is None


def test_frequency_to_channel_5ghz_and_6ghz():
    """Test 5 GHz and 6 GHz channel calculations."""
    assert frequency_to_channel(5180.0) == 36
    assert frequency_to_channel(5200.0) == 40
    assert frequency_to_channel(5745.0) == 149
    assert frequency_to_channel(5955.0) == 1  # 6 GHz band


def test_channel_to_frequency():
    """Test channel to center frequency mappings."""
    assert channel_to_frequency(1, "2.4GHz") == 2412.0
    assert channel_to_frequency(10, "2.4GHz") == 2457.0
    assert channel_to_frequency(14, "2.4GHz") == 2484.0
    assert channel_to_frequency(36, "5GHz") == 5180.0
    assert channel_to_frequency(None) is None


def test_phy_type_to_str():
    """Test PHY type mapping strings."""
    assert "802.11n" in phy_type_to_str(7)
    assert "802.11ac" in phy_type_to_str(8)
    assert "802.11ax" in phy_type_to_str(9)
    assert phy_type_to_str(None) is None


def test_signal_percent_distinct_from_rssi_dbm():
    """Ensure signal quality percentage and RSSI dBm are kept distinct and never conflated."""
    info = WifiConnectionInfo(
        is_connected=True,
        signal_percent=100,
        rssi_dbm=-33,
    )
    assert info.signal_percent == 100
    assert info.rssi_dbm == -33
    # Check that signal percentage is within 0-100%
    assert 0 <= info.signal_percent <= 100
    # Check that RSSI in dBm is negative
    assert info.rssi_dbm < 0


@pytest.mark.skipif(
    platform.system().lower() != "windows",
    reason="Native Wi-Fi tests only execute on Windows hosts",
)
def test_real_windows_wifi_query():
    """
    Live test against the active Windows system.
    Verifies that get_current_wifi_info returns a valid WifiConnectionInfo object.
    """
    info = get_current_wifi_info()
    assert isinstance(info, WifiConnectionInfo)
    assert info.timestamp is not None

    if info.is_connected:
        assert info.ssid is not None
        assert info.bssid is not None
        assert ":" in info.bssid
        assert info.signal_percent is not None
        assert 0 <= info.signal_percent <= 100
        # If native wlanapi provided dBm, verify it is realistic
        if info.rssi_dbm is not None:
            assert -100 <= info.rssi_dbm <= 0, f"Unrealistic RSSI dBm: {info.rssi_dbm}"
        # If channel is provided, verify it is positive
        if info.channel is not None:
            assert info.channel > 0


def test_netsh_fallback_does_not_fabricate_rssi():
    """Verify that netsh fallback does NOT set rssi_dbm (must remain None)."""
    fallback_info = _query_netsh_fallback()
    assert isinstance(fallback_info, WifiConnectionInfo)
    assert fallback_info.rssi_dbm is None, "Netsh fallback must NOT fabricate RSSI dBm"
