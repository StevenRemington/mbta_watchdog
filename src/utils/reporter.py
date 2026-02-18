import pandas as pd
import aiohttp
from datetime import datetime
from database.database import DatabaseManager
from .logger import get_logger
from .config import Config 

log = get_logger("Reporter")

class Reporter:
    def __init__(self, db_manager=None):
        self.db = db_manager or DatabaseManager()

    def get_recent_history(self, minutes=60):
        return self.db.get_recent_logs(minutes=minutes)

    def _get_receipt(self, train_id, days=7):
        """Generates a history of failures for the email."""
        df = self.db.get_train_history(train_id, days=days)
        if df.empty: return ""
        
        df['LogTime'] = pd.to_datetime(df['LogTime'])
        df['Date'] = df['LogTime'].dt.date
        
        # Group by Date to find unique bad days
        daily_stats = df.groupby('Date').agg({
            'DelayMinutes': 'max',
            'Status': lambda x: 'CANCELED' if 'CANCELED' in set(x) else 'Active'
        }).reset_index()

        offenses = daily_stats[
            (daily_stats['DelayMinutes'] > Config.DELAY_THRESHOLD) | 
            (daily_stats['Status'] == 'CANCELED')
        ]
        
        count = len(offenses)
        if count <= 1: return "" # Ignore if it's just today

        dates = [d.strftime('%m/%d') for d in offenses['Date']]
        return (f"\n   -> 🧾 HISTORY: Train {train_id} has failed {count} times in the last {days} days "
                f"({', '.join(dates)}).")

    def generate_email(self, df_recent):
        """Generates the email draft text and returns it as a string."""
        bad_trains = []
        if not df_recent.empty:
            df_recent['Train'] = df_recent['Train'].astype(str)
            for train_id in df_recent['Train'].unique():
                t_rows = df_recent[df_recent['Train'] == train_id]
                max_delay = t_rows['DelayMinutes'].max()
                is_canceled = "CANCELED" in t_rows['Status'].values
                
                if is_canceled or max_delay > Config.DELAY_THRESHOLD:
                    receipt = self._get_receipt(train_id)
                    if is_canceled:
                        bad_trains.append(f" - Train {train_id}: CANCELED today.{receipt}")
                    else:
                        bad_trains.append(f" - Train {train_id}: Delayed {max_delay} min.{receipt}")

        timestamp = datetime.now().strftime('%I:%M %p')
        
        if not bad_trains:
            body = (f"To Whom It May Concern,\n\n"
                    f"This log confirms the Framingham/Worcester Line is operating ON SCHEDULE as of {timestamp}.\n"
                    f"Status: Green | System Nominal\n\n"
                    f"Sincerely,\n[Your Name]")
        else:
            body = (f"To Customer Service,\n\n"
                    f"I am writing to report unreliable service on the Worcester Line as of {timestamp}.\n\n"
                    f"CURRENT INCIDENTS:\n" + "\n".join(bad_trains) +
                    f"\n\nThe recurrence of these delays indicates a systemic failure rather than isolated incidents.\n"
                    f"Please provide an explanation for these repeated disruptions.\n\n"
                    f"Sincerely,\n[Your Name]")
        
        return body

    async def push_to_thingspeak(self, current_data):
        """Uploads core metrics to ThingSpeak dashboard, excluding the email text."""
        if current_data.empty or not Config.THINGSPEAK_API_KEY: return

        late_trains = current_data[current_data['DelayMinutes'] > Config.DELAY_THRESHOLD]
        late_count = len(late_trains)
        total_trains = len(current_data)
        max_delay = current_data['DelayMinutes'].max()

        if late_count == 0:
            status_msg = f"All Clear ({total_trains} trains)"
        else:
            msgs = [f"Tr{row['Train']} +{row['DelayMinutes']}m" for _, row in late_trains.head(2).iterrows()]
            status_msg = " | ".join(msgs)

        # Payload now only includes metrics and status, no longer includes email chunks
        payload = {
            "api_key": Config.THINGSPEAK_API_KEY,
            "field1": total_trains,
            "field2": late_count,
            "field3": max_delay,
            "status": status_msg
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(Config.THINGSPEAK_URL, data=payload) as resp:
                    pass # Fire and forget
            except Exception as e:
                log.error(f"ThingSpeak Error: {e}")