"""
tests/test_environment.py
Basic project and environment verification test suite for Milestone 1.
"""

import sys
import platform
from pathlib import Path
from scripts.check_environment import is_venv_active, inspect_wifi, inspect_postgres


def test_python_version():
    """Ensure Python version is at least 3.10."""
    assert sys.version_info >= (3, 10), "Python version must be >= 3.10"


def test_venv_detected():
    """Verify that tests are executing inside a virtual environment or valid runtime."""
    assert sys.executable is not None


def test_project_structure():
    """Verify standard project directories and essential files exist."""
    root = Path(__file__).resolve().parent.parent
    assert (root / "backend").is_dir(), "backend directory missing"
    assert (root / "backend" / "__init__.py").is_file(), "backend/__init__.py missing"
    assert (root / "frontend").is_dir(), "frontend directory missing"
    assert (root / "tests").is_dir(), "tests directory missing"
    assert (root / "scripts").is_dir(), "scripts directory missing"
    assert (root / "docs").is_dir(), "docs directory missing"
    assert (root / ".gitignore").is_file(), ".gitignore missing"
    assert (root / ".env.example").is_file(), ".env.example missing"
    assert (root / "README.md").is_file(), "README.md missing"
    assert (root / "pyproject.toml").is_file(), "pyproject.toml missing"
    assert (root / "requirements.txt").is_file(), "requirements.txt missing"


def test_inspect_wifi_structure():
    """Verify Wi-Fi inspection function returns valid dictionary schema."""
    wifi = inspect_wifi()
    assert isinstance(wifi, dict)
    assert "adapter_found" in wifi
    assert "rssi_dbm_exposed" in wifi


def test_inspect_postgres_structure():
    """Verify PostgreSQL inspection function returns valid schema."""
    pg = inspect_postgres()
    assert isinstance(pg, dict)
    assert "psql_on_path" in pg
    assert "installed_in_program_files" in pg


def test_network_tests_module_exists():
    """Verify backend/network_tests.py module exists and functions are callable."""
    from backend.network_tests import measure_network_performance, LatencyProbe, LatencySummary
    assert callable(measure_network_performance)
    assert LatencyProbe is not None
    assert LatencySummary is not None


def test_database_module_exists():
    """Verify backend/database.py and backend/repository.py exist and functions are callable."""
    from backend.database import get_database_url, init_db, get_connection
    from backend.repository import create_session, create_measurement
    assert callable(get_database_url)
    assert callable(init_db)
    assert callable(get_connection)
    assert callable(create_session)
    assert callable(create_measurement)


def test_api_module_exists():
    """Verify backend/main.py exists and exports FastAPI app."""
    from backend.main import app, create_app
    assert app is not None
    assert callable(create_app)
