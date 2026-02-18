import asyncio
import discord
from datetime import datetime
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict

# Ensure src/ is in the python path
SRC_PATH = str(Path(__file__).resolve().parent / "src")
if SRC_PATH not in sys.path: 
    sys.path.insert(0, SRC_PATH)

from utils.config import Config
from utils.logger import get_logger
from utils.reporter import Reporter
from database.database import DatabaseManager
from api.monitor import MBTAMonitor
from interfaces.bot import WatchdogBot
from interfaces.bluesky import BlueskyClient

# Initialize Logger
log = get_logger("Main")

@dataclass
class WatchdogState:
    """Holds the runtime state of the application."""
    alert_history: Dict[str, str] = field(default_factory=dict)
    last_summary_date: str = ""
    last_morning_report_date: str = ""

def initialize_app():
    """Performs startup setup tasks (directories, logging, etc)."""
    # Create necessary directories
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log.info("📁 Environment Initialized")

async def process_alerts(bot, bsky, current_data, state: WatchdogState, db: DatabaseManager):
    """Checks for disruptions and adds historical context to alerts."""
    if current_data.empty:
        state.alert_history.clear()
        return

    active_ids = set()
    for _, row in current_data.iterrows():
        tid = str(row['Train'])
        active_ids.add(tid)
        
        condition = "NONE"
        if row['Status'] == "CANCELED": 
            condition = "CANCELED"
        elif row['DelayMinutes'] >= Config.MAJOR_DELAY_THRESHOLD: 
            condition = "LATE_MAJOR"
        
        last_cond = state.alert_history.get(tid, "NONE")
        
        # If we are about to send an alert, generate the "Receipt"
        receipt_text = ""
        if condition in ["CANCELED", "LATE_MAJOR"] and condition != last_cond:
            # Check history (This returns 'today' + past failures)
            bad_dates = db.get_failure_stats(tid)
            
            # If there is more than just today's failure, shame them.
            if len(bad_dates) > 1:
                # Format dates: "2024-02-14" -> "02/14"
                dates_str = ", ".join([datetime.strptime(d, '%Y-%m-%d').strftime('%m/%d') for d in bad_dates])
                receipt_text = f"\n\n🧾 HISTORY: Failed {len(bad_dates)}x in last 7 days ({dates_str})."
        # ---------------------------

        if condition == "CANCELED" and last_cond != "CANCELED":
            skeet_text = f"🚨 ALERT: MBTA Commuter Rail Train {tid} has been CANCELED at {row['Station']}.{receipt_text} @mbta.com #MBTA #WorcesterLine"
            
            post_url = bsky.send_skeet(skeet_text)
            description = f"🔗 [View Alert on Bluesky]({post_url})" if post_url else f"Location: {row['Station']}"
            await bot.send_alert(f"🚨 Train {tid} CANCELED", description, 0x000000)
            state.alert_history[tid] = "CANCELED"
        
        elif condition == "LATE_MAJOR" and last_cond not in ["LATE_MAJOR", "CANCELED"]:
            skeet_text = f"⚠️ SEVERE DELAY: Train {tid} is running {row['DelayMinutes']} minutes late at {row['Station']}.{receipt_text} @mbta.com #MBTA #WorcesterLine"
            
            post_url = bsky.send_skeet(skeet_text)
            description = f"🔗 [View Alert on Bluesky]({post_url})" if post_url else f"{row['DelayMinutes']} min late @ {row['Station']}"
            await bot.send_alert(f"⚠️ Major Delay: Train {tid}", description, 0xFF0000)
            state.alert_history[tid] = "LATE_MAJOR"

    # Prune old keys
    for tid in list(state.alert_history.keys()):
        if tid not in active_ids: 
            del state.alert_history[tid]

async def monitor_loop(monitor, reporter, bot, bsky, db, state: WatchdogState):
    log.info("Starting Monitor Loop...")
    while True:
        try:
            # 1. Core Logic
            data = await monitor.fetch_data()
            monitor.save_data(data)
            await process_alerts(bot, bsky, data, state, db)
            
            # 2. Reporting
            await reporter.push_to_thingspeak(data) 

            # 3. Morning Grade Logic (Runs at 10:00 AM) ---
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')

            if now.hour == 10 and now.minute <= 5 and state.last_morning_report_date != today_str:
                log.info("Generating Morning Commute Grade...")
                morning_stats = db.get_morning_commute_stats()
                
                if morning_stats:
                    # Post to Bluesky
                    post_url = bsky.post_morning_grade(morning_stats)
                    
                    # Post to Discord
                    description = f"🔗 [View Report on Bluesky]({post_url})" if post_url else "Morning report generated."
                    grade_color = 0x2ecc71 if morning_stats['grade'] in ['A', 'B'] else 0xe74c3c
                    await bot.send_alert(f"🌅 Morning Grade: {morning_stats['grade']}", description, grade_color)
                    
                    state.last_morning_report_date = today_str
            # ---------------------------------------------------

            # 4. Daily Summary Logic (Runs at 09:00 PM)
            if now.hour == 21 and now.minute <= 5 and state.last_summary_date != today_str:
                log.info("Generating Daily Highlight Post...")
                stats = db.get_daily_summary_stats()
                post_url = bsky.post_daily_summary(stats)
                description = f"🔗 [View Daily Summary on Bluesky]({post_url})" if post_url else "Today's service summary has been generated."
                await bot.send_alert(f"📊 Daily Service Summary - {today_str}", description, 0x3498db)
                state.last_summary_date = today_str

        except Exception as e:
            log.error(f"Loop Error: {e}", exc_info=True)
        
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

async def main():
    # 1. Initialize Environment
    initialize_app()
    
    # 2. Initialize State
    app_state = WatchdogState()

    # 3. Initialize Services
    # DatabaseManager is now a Singleton, so we can instantiate it safely
    shared_db = DatabaseManager()
    monitor = MBTAMonitor(db_manager=shared_db)
    reporter = Reporter(db_manager=shared_db)
    bsky = BlueskyClient()
    
    intents = discord.Intents.default()
    intents.message_content = True
    
    # Inject dependencies including the Monitor
    bot = WatchdogBot(
        db_manager=shared_db, 
        reporter=reporter, 
        monitor=monitor, 
        intents=intents
    )

    asyncio.create_task(monitor_loop(monitor, reporter, bot, bsky, shared_db, app_state))
    
    log.info("Starting Discord Interface...")
    try:
        await bot.start(Config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        log.info("Shutting down.")

if __name__ == "__main__":
    try: 
        asyncio.run(main())
    except KeyboardInterrupt: 
        pass