import pytest
import sys
import os
from pathlib import Path

# Add src to path so we can import modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database.database import DatabaseManager

@pytest.fixture
def db_manager():
    """Returns an in-memory DatabaseManager for testing."""
    return DatabaseManager(":memory:")