import asyncio
import discord
from datetime import datetime
import sys
from pathlib import Path

SRC_PATH = str(Path(__file__).resolve().parent / "src")
if SRC_PATH not in sys.path: sys.path.insert(0, SRC_PATH)

from utils.config import Config
from utils.logger import get_logger
from utils.reporter import Reporter
from database.database import DatabaseManager
from api.monitor import MBTAMonitor
from interfaces.bot import WatchdogBot
from interfaces.bluesky import BlueskyClient

log = get_logger("Main")
alert_history = {}
last_summary_date = "" # Track daily highlights to post once at 9pm

async def process_alerts(bot, bsky, current_data):
    """Checks for service disruptions and sends cross-platform notifications."""
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
        elif row['DelayMinutes'] >= Config.MAJOR_DELAY_THRESHOLD: condition = "LATE_MAJOR"
        
        last_cond = alert_history.get(tid, "NONE")
        
        if condition == "CANCELED" and last_cond != "CANCELED":
            # 1. Post to Bluesky first to get the link
            skeet_text = f"🚨 ALERT: MBTA Commuter Rail Train {tid} has been CANCELED at {row['Station']}. @mbta.com #MBTA #WorcesterLine"
            post_url = bsky.send_skeet(skeet_text)
            
            # 2. Send Discord alert with the link
            description = f"🔗 [View Alert on Bluesky]({post_url})" if post_url else f"Loc: {row['Station']}"
            await bot.send_alert(f"🚨 Train {tid} CANCELED", description, 0x000000)
            
            alert_history[tid] = "CANCELED"
        
        elif condition == "LATE_MAJOR" and last_cond not in ["LATE_MAJOR", "CANCELED"]:
            # 1. Post to Bluesky first to get the link
            skeet_text = f"⚠️ SEVERE DELAY: Train {tid} is running {row['DelayMinutes']} minutes late at {row['Station']}. @mbta.com #MBTA #WorcesterLine"
            post_url = bsky.send_skeet(skeet_text)
            
            # 2. Send Discord alert with the link
            description = f"🔗 [View Alert on Bluesky]({post_url})" if post_url else f"{row['DelayMinutes']} min late @ {row['Station']}"
            await bot.send_alert(f"⚠️ Major Delay: Train {tid}", description, 0xFF0000)
            
            alert_history[tid] = "LATE_MAJOR"

    for tid in list(alert_history.keys()):
        if tid not in active_ids: del alert_history[tid]

async def monitor_loop(monitor, reporter, bot, bsky, db):
    global last_summary_date
    log.info("Starting Monitor Loop...")
    while True:
        try:
            # 1. Core Logic
            data = await monitor.fetch_data()
            monitor.save_data(data)
            await process_alerts(bot, bsky, data)
            
            hist = reporter.get_recent_history(60)
            txt = reporter.generate_email(hist)
            await reporter.push_to_thingspeak(data, txt)

            # 2. Daily Summary Logic (Check for 9 PM)
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')
            if now.hour == 21 and now.minute <= 5 and last_summary_date != today_str:
                log.info("Generating Daily Highlight Post...")
                stats = db.get_daily_summary_stats()
                
                # Post to Bluesky and capture the URL
                post_url = bsky.post_daily_summary(stats)
                
                # Send Discord alert for the summary
                description = f"🔗 [View Daily Summary on Bluesky]({post_url})" if post_url else "Today's service summary has been generated."
                await bot.send_alert(f"📊 Daily Service Summary - {today_str}", description, 0x3498db)
                
                last_summary_date = today_str

        except Exception as e:
            log.error(f"Loop Error: {e}")
        
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

async def main():
    shared_db = DatabaseManager()
    monitor = MBTAMonitor(db_manager=shared_db)
    reporter = Reporter(db_manager=shared_db)
    bsky = BlueskyClient()
    
    intents = discord.Intents.default()
    intents.message_content = True
    bot = WatchdogBot(db_manager=shared_db, intents=intents)

    asyncio.create_task(monitor_loop(monitor, reporter, bot, bsky, shared_db))
    
    log.info("Starting Discord Interface...")
    try:
        await bot.start(Config.DISCORD_TOKEN)
    except KeyboardInterrupt:
        log.info("Shutting down.")

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass