import asyncio
import discord
from datetime import datetime
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any

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
from interfaces.twitter import TwitterClient

log = get_logger("Main")

@dataclass
class WatchdogState:
    """Holds the runtime state of the application."""
    # Updated: Now stores a dict with condition and delay to track worsening status
    alert_history: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_summary_date: str = ""
    last_morning_report_date: str = ""

def initialize_app():
    """Performs startup setup tasks."""
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log.info("📁 Environment Initialized")

async def process_alerts(bot, bsky, twitter, current_data, state: WatchdogState, db: DatabaseManager, reporter):
    """Checks for disruptions and mirrors successful social posts to Discord."""
    if current_data.empty:
        state.alert_history.clear()
        return

    active_ids = set()
    for _, row in current_data.iterrows():
        tid = str(row['Train'])
        active_ids.add(tid)
        
        # Determine current condition
        condition = "NONE"
        if row['Status'] == "CANCELED": 
            condition = "CANCELED"
        elif row['DelayMinutes'] >= Config.MAJOR_DELAY_THRESHOLD: 
            condition = "LATE_MAJOR"
        
        # Get the last known state for this train
        last_state = state.alert_history.get(tid, {"condition": "NONE", "delay": 0})
        last_cond = last_state.get("condition", "NONE")
        last_delay = last_state.get("delay", 0)

        needs_alert = False
        is_update = False

        # Logic Gate: Threshold-Based Updates
        if condition == "CANCELED" and last_cond != "CANCELED":
            needs_alert = True
        elif condition == "LATE_MAJOR":
            if last_cond not in ["LATE_MAJOR", "CANCELED"]:
                # Initial severe delay alert
                needs_alert = True
            elif last_cond != "CANCELED" and row['DelayMinutes'] >= last_delay + 10:
                # Delay worsened by at least 10 minutes (Threshold trigger)
                needs_alert = True
                is_update = True
        
        if needs_alert:
            history = db.get_failure_stats(tid)
            
            # 1. Post to Bluesky
            bsky_url = None
            if bsky:
                bsky_text = reporter.format_alert(
                    row, condition, history, platform="bluesky", is_update=is_update, last_delay=last_delay
                )
                bsky_url = bsky.send_skeet(bsky_text)
            
            # 2. Post to Twitter
            twitter_url = None
            if twitter:
                twitter_text = reporter.format_alert(
                    row, condition, history, platform="twitter", is_update=is_update, last_delay=last_delay
                )
                twitter_url = twitter.post_alert(twitter_text)
            
            # 3. Mirror to Discord only if at least one social post succeeded
            if bsky_url or twitter_url:
                if condition == "CANCELED":
                    title = f"🚨 Train {tid} CANCELED"
                    color = 0x000000
                elif is_update:
                    title = f"📈 UPDATE: Worsening Delay for Train {tid}"
                    color = 0xFF8C00 # Dark Orange for updates
                else:
                    title = f"⚠️ Major Delay: Train {tid}"
                    color = 0xFF0000
                
                # Build the dynamic description with appropriate links
                links = []
                if bsky_url:
                    links.append(f"🔗 [View Alert on Bluesky]({bsky_url})")
                if twitter_url:
                    links.append(f"🐦 [View Alert on X/Twitter]({twitter_url})")
                
                description = "\n".join(links)
                await bot.send_alert(title, description, color)
            
            # Update the application state with the newly alerted delay
            state.alert_history[tid] = {"condition": condition, "delay": row['DelayMinutes']}

    # Cleanup logic: Remove trains that are no longer active
    state.alert_history = {k: v for k, v in state.alert_history.items() if k in active_ids}

async def monitor_loop(monitor, reporter, bot, bsky, twitter, db, state: WatchdogState):
    log.info("Starting Monitor Loop...")
    while True:
        try:
            data = await monitor.fetch_data()
            monitor.save_data(data)
            
            # Process real-time alerts
            await process_alerts(bot, bsky, twitter, data, state, db, reporter)
            
            # External Reporting (ThingSpeak)
            await reporter.push_to_thingspeak(data) 

            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')

            # Periodic Reports
            reports = [
                {"hour": 10, "attr": "last_morning_report_date", "func": db.get_morning_commute_stats, "fmt": reporter.format_morning_grade, "label": "Morning Grade"},
                {"hour": 21, "attr": "last_summary_date", "func": db.get_daily_summary_stats, "fmt": reporter.format_daily_summary, "label": "Daily Summary"}
            ]

            for r in reports:
                if now.hour == r["hour"] and now.minute <= 5 and getattr(state, r["attr"]) != today_str:
                    stats = r["func"]()
                    if stats:
                        bsky_url = bsky.send_skeet(r["fmt"](stats, "bluesky")) if bsky else None
                        twitter_url = twitter.post_alert(r["fmt"](stats, "twitter")) if twitter else None
                        
                        if bsky_url or twitter_url:
                            links = []
                            if bsky_url:
                                links.append(f"🔗 [View on Bluesky]({bsky_url})")
                            if twitter_url:
                                links.append(f"🐦 [View on X/Twitter]({twitter_url})")
                                
                            description = "\n".join(links)
                            await bot.send_alert(f"📊 {r['label']}", description, 0x3498db)
                            setattr(state, r["attr"], today_str)

        except Exception as e:
            log.error(f"Loop Error: {e}", exc_info=True)
        
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

async def main():
    initialize_app()
    app_state = WatchdogState()

    shared_db = DatabaseManager()
    monitor = MBTAMonitor(db_manager=shared_db)
    reporter = Reporter(db_manager=shared_db)
    bsky = BlueskyClient()
    twitter = TwitterClient() if Config.TWITTER_CONSUMER_KEY else None
    
    intents = discord.Intents.default()
    intents.message_content = True
    
    bot = WatchdogBot(
        db_manager=shared_db, 
        reporter=reporter, 
        monitor=monitor, 
        bsky=bsky,      
        twitter=twitter,
        intents=intents
    )

    asyncio.create_task(monitor_loop(monitor, reporter, bot, bsky, twitter, shared_db, app_state))
    
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