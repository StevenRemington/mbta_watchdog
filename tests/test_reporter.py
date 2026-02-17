import pytest
import pandas as pd
from utils.reporter import Reporter
from datetime import datetime, timedelta

@pytest.fixture
def reporter(db_manager):
    return Reporter(db_manager=db_manager)

def test_receipt_generation_with_history(db_manager, reporter):
    """Test that historical failures are flagged in the receipt."""
    # Insert failure from 2 days ago
    two_days_ago = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
    
    history_df = pd.DataFrame([{
        "LogTime": two_days_ago,
        "Train": "508",
        "Status": "LATE",
        "DelayMinutes": 15,
        "Station": "Natick",
        "Direction": "IN"
    }])
    db_manager.insert_data(history_df)
    
    # Logic note: Code requires >1 failure to show receipt. Add a second one.
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
    history_df2 = pd.DataFrame([{
        "LogTime": three_days_ago,
        "Train": "508",
        "Status": "CANCELED",
        "DelayMinutes": 0,
        "Station": "Natick",
        "Direction": "IN"
    }])
    db_manager.insert_data(history_df2)
    
    receipt = reporter._get_receipt("508", days=7)
    
    assert "Train 508 has failed 2 times" in receipt
    assert "HISTORY" in receipt

def test_email_generation_green_status(reporter):
    """Test 'All Clear' email generation."""
    empty_df = pd.DataFrame(columns=["Train", "Status", "DelayMinutes"])
    email = reporter.generate_email(empty_df)
    
    assert "ON SCHEDULE" in email
    assert "Status: Green" in email

def test_email_generation_red_status(db_manager, reporter):
    """Test Complaint email generation."""
    recent_df = pd.DataFrame([{
        "LogTime": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "Train": "508",
        "Status": "LATE",
        "DelayMinutes": 25, 
        "Station": "Natick",
        "Direction": "IN"
    }])
    
    email = reporter.generate_email(recent_df)
    
    assert "unreliable service" in email
    assert "Delayed 25 min" in email