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

    def _get_receipt(self, train_id: str, days: int = 7):
        """Generates a history of failures using the database's aggregation logic."""
        bad_dates = self.db.get_failure_stats(train_id, days=days)
        
        count = len(bad_dates)
        if count <= 1: 
            return "" 

        # Format dates (e.g., "2023-10-01" -> "10/01")
        formatted_dates = [datetime.strptime(d, '%Y-%m-%d').strftime('%m/%d') for d in bad_dates]
        
        return (f"\n   -> 🧾 HISTORY: Train {train_id} has failed {count} times in the last {days} days "
                f"({', '.join(formatted_dates)}).")

    def _get_mbta_handle(self, platform: str) -> str:
        """Returns the correct MBTA handle based on the target platform."""
        return "@mbta.com" if platform == "bluesky" else "@MBTA_CR"

    def format_alert(self, row, condition: str, history_stats: list, platform: str = "bluesky", is_update: bool = False, last_delay: int = 0) -> str:
        """Formats the disruption alert text."""
        tid = row['Train']
        station = row['Station']
        handle = self._get_mbta_handle(platform)
        delay = row.get('DelayMinutes', 0)
        
        history_text = ""
        if history_stats and len(history_stats) > 1:
            dates_str = ", ".join([datetime.strptime(d, '%Y-%m-%d').strftime('%m/%d') for d in history_stats])
            history_text = f"\n\n🧾 HISTORY: Failed {len(history_stats)}x in last 7 days ({dates_str})."

        if condition == "CANCELED":
            return f"🚨 ALERT: MBTA Commuter Rail Train {tid} has been CANCELED at {station}.{history_text} {handle} #MBTA #WorcesterLine"
        
        # New Update logic for worsening delays
        if is_update:
            return f"📈 UPDATE: Train {tid} delays have worsened. Now running {delay} minutes late at {station} (previously {last_delay} min).{history_text} {handle} #MBTA #WorcesterLine"
        
        return f"⚠️ SEVERE DELAY: Train {tid} is running {delay} minutes late at {station}.{history_text} {handle} #MBTA #WorcesterLine"

    def format_morning_grade(self, stats: dict, platform: str = "bluesky") -> str:
        """Formats the morning commute report optimized for 280-character limits."""
        if not stats:
            return f"🌅 Morning Commute: No data available. {self._get_mbta_handle(platform)} #MBTA"

        handle = self._get_mbta_handle(platform)
        
        # Highly condensed format (~170 chars max)
        msg = (
            f"🌅 MBTA Morning Commute ({stats['date']})\n\n"
            f"🚆 Tracked: {stats['total_tracked']} Worcester Line trains\n"
            f"⚠️ Impact: {stats['percent_affected']}% delayed or canceled\n"
        )
        
        if stats['worst_delay'] > 0:
            msg += f"🐌 Worst: Train {stats['worst_train']} ({stats['worst_delay']}m late)\n"
        else:
            msg += "✅ Status: No major delays!\n"
            
        msg += f"\n{handle} #MBTA #WorcesterLine"
        return msg

    def format_daily_summary(self, stats: dict, platform: str = "bluesky") -> str:
        """Formats the daily summary report optimized for 280-character limits."""
        if not stats:
            return f"📊 Daily Summary: No data collected today. {self._get_mbta_handle(platform)} #MBTA"

        handle = self._get_mbta_handle(platform)
        
        # Highly condensed format (~210 chars max)
        msg = (
            f"📊 MBTA Day in Review ({stats['date']})\n\n"
            f"📈 Tracked: {stats['total_tracked']} trains\n"
            f"🛑 Issues: {stats['canceled_count']} Canceled, {stats['late_count']} Major Delays\n"
            f"⏱️ Avg Delay: {stats['avg_delay_mins']} mins (late trains only)\n"
            f"🐌 Slowest: Train {stats['worst_train']} ({stats['worst_delay']}m late)\n\n"
            f"{handle} #MBTA"
        )
        return msg
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