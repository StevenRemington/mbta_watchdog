import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch
from api.monitor import MBTAMonitor

MOCK_MBTA_RESPONSE = {
    "data": [
        {
            "attributes": {
                "label": "508",
                "current_status": "STOPPED_AT",
                "delay": 600, 
                "direction_id": 1
            },
            "relationships": {
                "stop": {"data": {"id": "place-sstat"}}
            }
        }
    ],
    "included": [
        {
            "type": "stop",
            "id": "place-sstat",
            "attributes": {"name": "South Station"}
        }
    ]
}

@pytest.mark.asyncio
async def test_fetch_data_parsing(db_manager):
    """Test that JSON response is correctly parsed into a DataFrame."""
    monitor = MBTAMonitor(db_manager=db_manager)

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = MOCK_MBTA_RESPONSE
        mock_get.return_value.__aenter__.return_value = mock_response

        df = await monitor.fetch_data()

        assert not df.empty
        assert len(df) == 1
        assert df.iloc[0]["Train"] == "508"
        assert df.iloc[0]["DelayMinutes"] == 10 
        assert df.iloc[0]["Station"] == "South Station"
        assert df.iloc[0]["Status"] == "LATE" 
        assert df.iloc[0]["Direction"] == "IN" 

@pytest.mark.asyncio
async def test_fetch_data_api_failure(db_manager):
    """Test graceful failure on API error."""
    monitor = MBTAMonitor(db_manager=db_manager)

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = AsyncMock()
        mock_response.status = 500 
        mock_get.return_value.__aenter__.return_value = mock_response

        df = await monitor.fetch_data()
        
        assert df.empty