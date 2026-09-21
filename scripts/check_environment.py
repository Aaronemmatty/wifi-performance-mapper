#!/usr/bin/env python3
"""
scripts/check_environment.py
Environment and Hardware Verification Script for Milestone 1.

Safely inspects the host environment, runtime dependencies, tools,
and Wi-Fi capabilities without modifying system state or exposing secrets.
"""

import os
import sys
import platform
import shutil
import subprocess
import re
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def is_venv_active() -> bool:
    """Check if the current script is running inside a Python virtual environment."""
    return hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )


def check_command(cmd: str) -> tuple[bool, str]:
    """Check if an executable is available on PATH."""
    loc = shutil.which(cmd)
    if loc:
        return True, loc
    return False, "Not found on PATH"


def run_cmd(args: list[str]) -> tuple[int, str]:
    """Run a safe local command and return its exit code and stdout/stderr."""
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return res.returncode, (res.stdout + res.stderr).strip()
    except Exception as exc:
        return -1, str(exc)


def inspect_wifi() -> dict:
    """Safely inspect Wi-Fi interfaces and drivers via netsh wlan."""
    wifi_info = {
        "adapter_found": False,
        "adapter_name": None,
        "adapter_desc": None,
        "state": None,
        "ssid": None,
        "bssid": None,
        "signal_raw": None,
        "radio_type": None,
        "channel": None,
        "rates": None,
        "rssi_dbm_exposed": False,
        "driver_version": None,
        "driver_vendor": None,
    }

    if platform.system().lower() != "windows":
        wifi_info["note"] = "Non-Windows system; netsh inspection skipped."
        return wifi_info

    # Inspect interfaces
    code, out = run_cmd(["netsh", "wlan", "show", "interfaces"])
    if code == 0 and "There is no wireless interface" not in out:
        wifi_info["adapter_found"] = True
        for line in out.splitlines():
            line_str = line.strip()
            if line_str.startswith("Name"):
                wifi_info["adapter_name"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("Description"):
                wifi_info["adapter_desc"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("State"):
                wifi_info["state"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("SSID") and not line_str.startswith("BSSID"):
                wifi_info["ssid"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("BSSID"):
                wifi_info["bssid"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("Signal"):
                wifi_info["signal_raw"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("Radio type"):
                wifi_info["radio_type"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("Channel"):
                wifi_info["channel"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("Receive rate") or line_str.startswith("Transmit rate"):
                rates = wifi_info.get("rates") or []
                rates.append(line_str)
                wifi_info["rates"] = rates

        # Check if dBm was found anywhere in the output
        if re.search(r"-?\d+\s*dBm", out, re.IGNORECASE):
            wifi_info["rssi_dbm_exposed"] = True
        else:
            wifi_info["rssi_dbm_exposed"] = False

    # Inspect drivers
    code_d, out_d = run_cmd(["netsh", "wlan", "show", "drivers"])
    if code_d == 0:
        for line in out_d.splitlines():
            line_str = line.strip()
            if line_str.startswith("Version") and ":" in line_str:
                wifi_info["driver_version"] = line_str.split(":", 1)[-1].strip()
            elif line_str.startswith("Vendor") and ":" in line_str and not wifi_info["driver_vendor"]:
                wifi_info["driver_vendor"] = line_str.split(":", 1)[-1].strip()

    return wifi_info


def inspect_postgres() -> dict:
    """Check for PostgreSQL executables, standard installation paths, and service."""
    pg_info = {
        "psql_on_path": False,
        "psql_path": None,
        "psql_version": None,
        "pg_isready_on_path": False,
        "installed_in_program_files": False,
        "service_detected": False,
        "pgadmin_found": False,
    }

    ok, loc = check_command("psql")
    if ok:
        pg_info["psql_on_path"] = True
        pg_info["psql_path"] = loc
        code, out = run_cmd([loc, "--version"])
        if code == 0:
            pg_info["psql_version"] = out.strip()
    else:
        # Check standard default installation directory
        default_pg_bin = Path(r"C:\Program Files\PostgreSQL\18\bin")
        default_psql = default_pg_bin / "psql.exe"
        if default_psql.exists():
            pg_info["installed_in_program_files"] = True
            pg_info["psql_path"] = str(default_psql)
            code, out = run_cmd([str(default_psql), "--version"])
            if code == 0:
                pg_info["psql_version"] = out.strip()

    # Check pgAdmin
    for p in [
        Path(r"C:\Program Files\PostgreSQL\18\pgAdmin 4"),
        Path(r"C:\Program Files\pgAdmin 4"),
        Path(r"C:\Users\emmat\AppData\Local\Programs\pgAdmin 4"),
    ]:
        if p.exists():
            pg_info["pgadmin_found"] = True
            pg_info["pgadmin_path"] = str(p)
            break

    return pg_info


def main() -> int:
    print("=" * 60)
    print("  Wi-Fi Performance Mapper - Milestone 1 Environment Check")
    print("=" * 60)

    # 1. System Info
    print("\n[1] SYSTEM & OS")
    print(f"  OS System:       {platform.system()} ({platform.release()})")
    print(f"  OS Version:      {platform.version()}")
    print(f"  Architecture:    {platform.machine()} ({platform.architecture()[0]})")
    print(f"  Project Root:    {Path(__file__).resolve().parent.parent}")

    # 2. Python Info
    print("\n[2] PYTHON RUNTIME")
    print(f"  Python Version:  {platform.python_version()} ({platform.python_implementation()})")
    print(f"  Executable:      {sys.executable}")
    in_venv = is_venv_active()
    print(f"  In Virtual Env:  {'YES (.venv active)' if in_venv else 'NO (System Python)'}")

    # 3. Development Tools
    print("\n[3] DEVELOPMENT TOOLS")
    git_ok, git_loc = check_command("git")
    if git_ok:
        _, git_ver = run_cmd(["git", "--version"])
        print(f"  Git:             FOUND -> {git_ver} ({git_loc})")
    else:
        print(f"  Git:             NOT FOUND")

    # 4. PostgreSQL
    print("\n[4] POSTGRESQL ENVIRONMENT")
    pg_info = inspect_postgres()
    if pg_info.get("psql_version"):
        print(f"  PostgreSQL:      FOUND -> {pg_info['psql_version']} ({pg_info['psql_path']})")
        if not pg_info["psql_on_path"]:
            print("  Note:            PostgreSQL binary is present in Program Files, not on user PATH.")
    else:
        print("  PostgreSQL:      NOT FOUND on system")

    if pg_info["pgadmin_found"]:
        print(f"  pgAdmin:         FOUND -> {pg_info.get('pgadmin_path')}")
    else:
        print("  pgAdmin:         NOT DETECTED")

    # 5. Wi-Fi Adapter & Capabilities
    print("\n[5] WI-FI ADAPTER & CAPABILITY FINDINGS")
    try:
        from backend.wifi_windows import get_current_wifi_info
        w_info = get_current_wifi_info()
        if w_info.is_connected:
            print(f"  Connection State: CONNECTED (Source: {w_info.raw_source})")
            print(f"  SSID:             {w_info.ssid}")
            print(f"  BSSID:            {w_info.bssid}")
            print(f"  Signal Quality:   {w_info.signal_percent}%")
            print(f"  True dBm RSSI:    {f'{w_info.rssi_dbm} dBm' if w_info.rssi_dbm is not None else 'NOT EXPOSED'}")
            print(f"  Center Frequency: {f'{w_info.frequency_mhz} MHz' if w_info.frequency_mhz else 'N/A'}")
            print(f"  Channel:          {w_info.channel}")
            print(f"  Radio Standard:   {w_info.radio_type}")
            print(f"  Link Rates:       Rx: {w_info.receive_rate_mbps} Mbps | Tx: {w_info.transmit_rate_mbps} Mbps")
            print(f"  Adapter:          {w_info.adapter_description}")
            print(f"  Driver:           {w_info.driver_provider} (v{w_info.driver_version}, Date: {w_info.driver_date})")
        else:
            print("  Wi-Fi Adapter:    DISCONNECTED / NO ACTIVE INTERFACE")
    except Exception as e:
        print(f"  Native Wi-Fi Check Error: {e}")

    print("\n" + "=" * 60)
    print("  Environment Check Completed Successfully.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
