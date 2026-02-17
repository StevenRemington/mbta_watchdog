import pytest
import pandas as pd
from datetime import datetime

def test_insert_and_retrieve_logs(db_manager):
    """Test that data can be inserted and retrieved correctly."""
    # Create dummy data
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data = {
        "LogTime": [now_str],
        "Train": ["508"],
        "Status": ["LATE"],
        "DelayMinutes": [10],
        "Station": ["Natick"],
        "Direction": ["IN"]
    }
    df = pd.DataFrame(data)
    
    # Insert
    db_manager.insert_data(df)
    
    # Retrieve recent
    recent = db_manager.get_recent_logs(minutes=60)
    
    assert not recent.empty
    assert len(recent) == 1
    assert recent.iloc[0]['Train'] == "508"
    assert recent.iloc[0]['Status'] == "LATE"

def test_get_train_history(db_manager):
    """Test retrieving history for a specific train."""
    # Insert two records: one recent, one old
    data = [
        {"LogTime": "2024-01-01 10:00:00", "Train": "508", "Status": "LATE", "DelayMinutes": 15, "Station": "Natick", "Direction": "IN"},
        {"LogTime": "2024-01-02 10:00:00", "Train": "512", "Status": "ON TIME", "DelayMinutes": 0, "Station": "Boston", "Direction": "OUT"}
    ]
    df = pd.DataFrame(data)
    db_manager.insert_data(df)
    
    # Query for Train 508 (should find 1)
    history_508 = db_manager.get_train_history("508", days=3650) # Use a large window to catch old dates
    assert len(history_508) == 1
    assert history_508.iloc[0]['Train'] == "508"

    # Query for Train 999 (should find 0)
    history_999 = db_manager.get_train_history("999", days=3650)
    assert history_999.empty