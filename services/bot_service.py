import sys
import asyncio
import discord
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, Any

# 1. Path resolution for subdirectories
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_PATH = str(ROOT_DIR / "src")

if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# 2. Project-specific imports
from utils.config import Config
from utils.logger import get_logger
from utils.reporter import Reporter
from database.database import DatabaseManager
from interfaces.bot import WatchdogBot
from interfaces.bluesky import BlueskyClient
from interfaces.twitter import TwitterClient

log = get_logger("Main-BotService")

@dataclass
class WatchdogState:
    """Holds the runtime state for alert tracking."""
    alert_history: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_summary_date: str = ""
    last_morning_report_date: str = ""

def initialize_app():
    """Ensures data and log directories exist."""
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    Config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log.info("📁 Bot Service Environment Initialized")

async def process_alerts(bot, bsky, twitter, current_data, state: WatchdogState, db: DatabaseManager, reporter):
    """Processes disruptions and mirrors successful social posts to Discord."""
    if current_data.empty:
        # Note: We no longer clear history here to maintain state between DB polls
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
        
        last_state = state.alert_history.get(tid, {"condition": "NONE", "delay": 0})
        last_cond = last_state.get("condition", "NONE")
        last_delay = last_state.get("delay", 0)

        needs_alert = False
        is_update = False

        if condition == "CANCELED" and last_cond != "CANCELED":
            needs_alert = True
        elif condition == "LATE_MAJOR":
            if last_cond not in ["LATE_MAJOR", "CANCELED"]:
                needs_alert = True
            elif last_cond != "CANCELED" and row['DelayMinutes'] >= last_delay + 10:
                needs_alert = True
                is_update = True
        
        if needs_alert:
            history = db.get_failure_stats(tid) #
            
            bsky_url = bsky.send_skeet(reporter.format_alert(row, condition, history, platform="bluesky", is_update=is_update, last_delay=last_delay)) if bsky else None
            twitter_url = twitter.post_alert(reporter.format_alert(row, condition, history, platform="twitter", is_update=is_update, last_delay=last_delay)) if twitter else None
            
            if bsky_url or twitter_url:
                title = f"🚨 Train {tid} CANCELED" if condition == "CANCELED" else f"⚠️ Major Delay: Train {tid}"
                if is_update: title = f"📈 UPDATE: Worsening Delay for Train {tid}"
                
                links = []
                if bsky_url: links.append(f"🔗 [View Alert on Bluesky]({bsky_url})")
                if twitter_url: links.append(f"🐦 [View Alert on X/Twitter]({twitter_url})")
                
                await bot.send_alert(title, "\n".join(links), 0x000000 if condition == "CANCELED" else 0xFF0000)
            
            state.alert_history[tid] = {"condition": condition, "delay": row['DelayMinutes']}

    state.alert_history = {k: v for k, v in state.alert_history.items() if k in active_ids}

async def bot_consumer_loop(reporter, bot, bsky, twitter, db, state: WatchdogState):
    """
    Consumer Loop: Periodically queries the database for recent logs to trigger alerts.
    This replaces the previous direct monitor_loop.
    """
    log.info("Starting Bot Consumer Loop...")
    while True:
        try:
            # Query the database for logs from the last 5 minutes
            data = db.get_recent_logs(minutes=5)
            
            if not data.empty:
                await process_alerts(bot, bsky, twitter, data, state, db, reporter)
            
            # Periodic Reporting (Morning Grade / Daily Summary) logic remains the same
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')

            # 10 AM Morning Report
            if now.hour == 10 and now.minute <= 5 and state.last_morning_report_date != today_str:
                stats = db.get_morning_commute_stats()
                if stats:
                    text = reporter.format_morning_grade(stats, "bluesky")
                    if bsky: bsky.send_skeet(text)
                    state.last_morning_report_date = today_str

            # 9 PM Daily Summary
            if now.hour == 21 and now.minute <= 5 and state.last_summary_date != today_str:
                stats = db.get_daily_summary_stats()
                if stats:
                    text = reporter.format_daily_summary(stats, "bluesky")
                    if bsky: bsky.send_skeet(text)
                    state.last_summary_date = today_str

        except Exception as e:
            log.error(f"Consumer Loop Error: {e}", exc_info=True)
        
        # Check the database every 2 minutes
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

async def main():
    initialize_app()
    app_state = WatchdogState()

    shared_db = DatabaseManager() # Singleton access to mbta_logs.db
    reporter = Reporter(db_manager=shared_db)
    bsky = BlueskyClient()
    twitter = TwitterClient() if Config.TWITTER_CONSUMER_KEY else None
    
    intents = discord.Intents.default()
    intents.message_content = True
    
    bot = WatchdogBot(
        db_manager=shared_db, 
        reporter=reporter, 
        bsky=bsky,      
        twitter=twitter,
        intents=intents
    )

    # Start the consumer loop as a background task
    asyncio.create_task(bot_consumer_loop(reporter, bot, bsky, twitter, shared_db, app_state))
    
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