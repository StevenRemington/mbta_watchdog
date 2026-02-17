import asyncio
import discord
import sys
import os
from pathlib import Path

# Professional Bootstrap: Add 'src' to the system path
# This allows 'from utils.config import Config' to work from anywhere
SRC_PATH = str(Path(__file__).resolve().parent / "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from utils.config import Config
from utils.logger import get_logger
from utils.reporter import Reporter
from database.database import DatabaseManager
from api.monitor import MBTAMonitor
from interfaces.bot import WatchdogBot

log = get_logger("Main")
alert_history = {} # Track sent alerts to avoid spam

async def process_alerts(bot, current_data):
    """Checks for delay > 20m or Cancellation."""
    global alert_history
    if current_data.empty:
        alert_history.clear()
        return

    active_ids = set()
    for _, row in current_data.iterrows():
        tid = str(row['Train'])
        active_ids.add(tid)
        
        condition = "NONE"
        if row['Status'] == "CANCELED": condition = "CANCELED"
        elif row['DelayMinutes'] >= Config.MAJOR_DELAY_THRESHOLD: condition = "LATE_20"
        
        last_cond = alert_history.get(tid, "NONE")
        
        if condition == "CANCELED" and last_cond != "CANCELED":
            await bot.send_alert(f"🚨 Train {tid} CANCELED", f"Loc: {row['Station']}", 0x000000)
            alert_history[tid] = "CANCELED"
        
        elif condition == "LATE_20" and last_cond not in ["LATE_20", "CANCELED"]:
            await bot.send_alert(f"⚠️ Major Delay: Train {tid}", f"{row['DelayMinutes']} min late @ {row['Station']}", 0xFF0000)
            alert_history[tid] = "LATE_20"

    # Cleanup finished trains
    for tid in list(alert_history.keys()):
        if tid not in active_ids: del alert_history[tid]

async def monitor_loop(monitor, reporter, bot):
    """Main background task for polling and analysis."""
    log.info("Starting Monitor Loop...")
    while True:
        try:
            # 1. Fetch & Save
            data = await monitor.fetch_data()
            monitor.save_data(data)

            # 2. Process Proactive Alerts
            await process_alerts(bot, data)

            # 3. Report & IoT Update
            hist = reporter.get_recent_history(60)
            txt = reporter.generate_email(hist)
            await reporter.push_to_thingspeak(data, txt)

        except Exception as e:
            log.error(f"Loop Error: {e}")
        
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

async def main():
    # 1. Initialize Shared Resource (Dependency Injection Pattern)
    shared_db = DatabaseManager()
    
    # 2. Inject Shared DB into all dependent components
    monitor = MBTAMonitor(db_manager=shared_db)
    reporter = Reporter(db_manager=shared_db)
    
    intents = discord.Intents.default()
    intents.message_content = True
    bot = WatchdogBot(db_manager=shared_db, intents=intents)

    # 3. Start the Background Task
    # Note: bot.start is blocking, so we schedule the monitor first
    asyncio.create_task(monitor_loop(monitor, reporter, bot))
    
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