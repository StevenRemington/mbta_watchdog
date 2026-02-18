import pandas as pd
import aiohttp
from datetime import datetime
from dateutil import parser
from database.database import DatabaseManager
from utils.config import Config
from utils.logger import get_logger

log = get_logger("Monitor")

class MBTAMonitor:
    def __init__(self, db_manager=None):
        """
        Handles MBTA API polling.
        :param db_manager: Injected DatabaseManager instance.
        """
        self.headers = {"x-api-key": Config.MBTA_API_KEY} if Config.MBTA_API_KEY else {}
        self.db = db_manager or DatabaseManager()

    async def fetch_data(self):
        """Async fetch of live MBTA data using Predictions to calculate delay."""
        async with aiohttp.ClientSession() as session:
            try:
                # Switch to Predictions endpoint to get Schedule vs Actual data
                # include=vehicle (to get status/label), schedule (to get baseline), stop, trip
                url = f"{Config.MBTA_API_URL}/predictions?filter[route]=CR-Worcester&include=vehicle,schedule,stop,trip"
                
                async with session.get(url, headers=self.headers) as resp:
                    if resp.status != 200:
                        log.error(f"MBTA API Error: {resp.status}")
                        return pd.DataFrame()
                    data = await resp.json()
            except Exception as e:
                log.error(f"Network Error: {e}")
                return pd.DataFrame()

        if not data.get('data'):
            return pd.DataFrame()

        # Helper to parse JSON-API "included" array into a lookup dict
        def build_map(type_name):
            return {
                item['id']: item 
                for item in data.get('included', []) 
                if item.get('type') == type_name
            }

        vehicles_map = build_map('vehicle')
        schedules_map = build_map('schedule')
        stops_map = build_map('stop')
        trips_map = build_map('trip')

        records = []
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # We process predictions that have an active vehicle attached
        # Group by Trip/Vehicle to avoid duplicate rows for the same train (one per upcoming stop)
        # We usually want the "next" stop (closest time) to determine current delay.
        
        # 1. Group predictions by Vehicle ID
        vehicle_predictions = {}
        
        for pred in data['data']:
            # Check if this prediction is linked to a live vehicle
            try:
                veh_id = pred['relationships']['vehicle']['data']['id']
            except (KeyError, TypeError):
                continue # Skip predictions for trains that haven't started yet
            
            # We want the earliest prediction for this vehicle (Next stop)
            if veh_id not in vehicle_predictions:
                vehicle_predictions[veh_id] = pred
            else:
                # Compare times to keep the soonest one
                curr_time = pred['attributes']['arrival_time'] or pred['attributes']['departure_time']
                saved_time = vehicle_predictions[veh_id]['attributes']['arrival_time'] or vehicle_predictions[veh_id]['attributes']['departure_time']
                
                if curr_time and saved_time and curr_time < saved_time:
                    vehicle_predictions[veh_id] = pred

        # 2. Process each active vehicle
        for veh_id, pred in vehicle_predictions.items():
            vehicle = vehicles_map.get(veh_id)
            if not vehicle: continue
            
            # --- Extract Info ---
            v_attrs = vehicle['attributes']
            
            # Train Number (Try Trip Name first, then Label)
            trip_id = pred['relationships']['trip']['data']['id']
            trip = trips_map.get(trip_id)
            train_number = trip['attributes']['name'] if trip else v_attrs.get('label', 'UNK')
            
            # Status
            status = v_attrs.get('current_status', 'UNKNOWN')
            if status == "IN_TRANSIT_TO": status = "Moving To"
            elif status == "STOPPED_AT": status = "At Stop"
            
            # Direction
            dir_id = v_attrs.get('direction_id')
            direction = "IN" if dir_id == 1 else "OUT" if dir_id == 0 else "UNK"
            
            # Station Name
            stop_id = pred['relationships']['stop']['data']['id']
            stop = stops_map.get(stop_id)
            station_name = stop['attributes']['name'] if stop else "Unknown Stop"

            # --- CALCULATE DELAY ---
            # Prediction Time
            pred_ts_str = pred['attributes']['arrival_time'] or pred['attributes']['departure_time']
            
            # Schedule Time
            sched_id = pred['relationships']['schedule']['data']['id']
            schedule = schedules_map.get(sched_id)
            sched_ts_str = None
            if schedule:
                sched_ts_str = schedule['attributes']['arrival_time'] or schedule['attributes']['departure_time']
            
            delay_min = 0
            if pred_ts_str and sched_ts_str:
                p_time = parser.parse(pred_ts_str)
                s_time = parser.parse(sched_ts_str)
                # Calculate difference in minutes
                diff_sec = (p_time - s_time).total_seconds()
                delay_min = round(diff_sec / 60)
            
            # Determine Display Status
            display_status = status
            if delay_min > Config.DELAY_THRESHOLD:
                display_status = "LATE"

            records.append({
                "LogTime": now_str,
                "Train": train_number,
                "Status": display_status,
                "DelayMinutes": max(0, delay_min), # No negative delays
                "Station": station_name,
                "Direction": direction
            })

        log.info(f"Fetched {len(records)} active trains (Calculated via Predictions)")
        return pd.DataFrame(records)

    def save_data(self, df):
        """Saves current snapshot using the injected DB manager."""
        self.db.insert_data(df)