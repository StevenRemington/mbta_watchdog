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
    
    async def get_live_prediction(self, train_id: str) -> dict:
        """
        Fetches the immediate next prediction for a specific train.
        Refactored from Bot._fetch_live_prediction.
        """
        async with aiohttp.ClientSession() as session:
            try:
                # 1. Find Vehicle to get the Trip ID
                url_veh = f"{Config.MBTA_API_URL}/vehicles?filter[route]=CR-Worcester&filter[label]={train_id}"
                async with session.get(url_veh, headers=self.headers) as resp:
                    v_data = await resp.json()
                    if not v_data['data']: 
                        return None
                    trip_id = v_data['data'][0]['relationships']['trip']['data']['id']

                # 2. Get Prediction for that Trip
                url_pred = f"{Config.MBTA_API_URL}/predictions?filter[trip]={trip_id}&sort=time&page[limit]=1&include=stop,schedule"
                async with session.get(url_pred, headers=self.headers) as resp:
                    p_data = await resp.json()
                    if not p_data['data']: 
                        return None
                    
                    # --- Parsing Logic ---
                    pred = p_data['data'][0]
                    # Helper to extract included objects
                    included = {f"{i['type']}:{i['id']}": i for i in p_data.get('included', [])}
                    
                    # Times
                    p_ts = pred['attributes']['arrival_time'] or pred['attributes']['departure_time']
                    
                    # Schedule
                    s_id = pred['relationships']['schedule']['data']['id']
                    schedule = included.get(f"schedule:{s_id}")
                    s_ts = schedule['attributes']['arrival_time'] or schedule['attributes']['departure_time'] if schedule else None
                    
                    # Stop Name
                    stop_id = pred['relationships']['stop']['data']['id']
                    stop = included.get(f"stop:{stop_id}")
                    stop_name = stop['attributes']['name'] if stop else "Unknown"

                    # Calculate Delay
                    delay = 0
                    if p_ts and s_ts:
                        p_dt = parser.parse(p_ts)
                        s_dt = parser.parse(s_ts)
                        delay = max(0, round((p_dt - s_dt).total_seconds() / 60))

                    return {
                        "stop": stop_name,
                        "predicted": parser.parse(p_ts).strftime('%I:%M %p') if p_ts else "N/A",
                        "scheduled": parser.parse(s_ts).strftime('%I:%M %p') if s_ts else "N/A",
                        "delay": delay
                    }
            except Exception as e:
                log.error(f"Prediction Fetch Error: {e}")
                return None

    def save_data(self, df):
        """Saves current snapshot using the injected DB manager."""
        self.db.insert_data(df)