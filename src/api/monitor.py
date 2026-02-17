import pandas as pd
import aiohttp
from datetime import datetime
from database import DatabaseManager

from utils.config import Config
from utils.logger import get_logger

log = get_logger("Monitor")

class MBTAMonitor:
    def __init__(self):
        self.headers = {"x-api-key": Config.MBTA_API_KEY} if Config.MBTA_API_KEY else {}
        self.db = DatabaseManager()

    async def fetch_data(self):
        """Async fetch of live MBTA data."""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(Config.MBTA_API_URL, headers=self.headers) as resp:
                    if resp.status != 200:
                        log.error(f"MBTA API Error: {resp.status}")
                        return pd.DataFrame()
                    data = await resp.json()
            except Exception as e:
                log.error(f"Network Error: {e}")
                return pd.DataFrame()

        if not data.get('data'):
            return pd.DataFrame()

        # Build Map of Stop IDs -> Names
        stop_map = {}
        if 'included' in data:
            for item in data['included']:
                if item.get('type') == 'stop':
                    stop_map[item['id']] = item['attributes'].get('name', 'Unknown')

        records = []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for vehicle in data['data']:
            attrs = vehicle['attributes']
            
            train_id = attrs.get('label', 'UNK')
            status = attrs.get('current_status', 'UNKNOWN')
            
            # --- NEW: Extract Direction ---
            # 0 = Outbound, 1 = Inbound
            dir_id = attrs.get('direction_id')
            if dir_id == 1:
                direction = "IN"
            elif dir_id == 0:
                direction = "OUT"
            else:
                direction = "UNK"
            
            delay_sec = attrs.get('delay')
            delay_min = round(delay_sec / 60) if delay_sec is not None else 0
            
            # Find Station
            stop_id = None
            try:
                stop_id = vehicle['relationships']['stop']['data']['id']
            except (KeyError, TypeError):
                pass
            station_name = stop_map.get(stop_id, "In Transit")
            
            # Clean Status
            if status == "IN_TRANSIT_TO": status = "Moving To"
            elif status == "STOPPED_AT": status = "At Stop"
            
            if delay_min > Config.DELAY_THRESHOLD:
                status = "LATE"

            if status != "ADDED": 
                records.append({
                    "LogTime": now_str,
                    "Train": train_id,
                    "Status": status,
                    "DelayMinutes": delay_min,
                    "Station": station_name,
                    "Direction": direction  # <--- CRITICAL ADDITION
                })

        return pd.DataFrame(records)

    def save_data(self, df):
        """Saves current snapshot to DB."""
        self.db.insert_data(df)