import asyncio
import discord
import sys
from pathlib import Path

# Add 'src' to system path to allow 'from api.monitor import ...'
sys.path.append(str(Path(__file__).resolve().parent / "src"))

from config import Config
from logger import get_logger
from monitor import MBTAMonitor
from reporter import Reporter
from bot import WatchdogBot

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

async def monitor_loop(bot):
    monitor = MBTAMonitor()
    reporter = Reporter()
    log.info("Starting Monitor Loop...")
    await asyncio.sleep(5) # Let bot connect

    while True:
        try:
            # 1. Fetch & Save
            data = await monitor.fetch_data()
            monitor.save_data(data)

            # 2. Alerts
            await process_alerts(bot, data)

            # 3. Report & IoT
            hist = reporter.get_recent_history(60)
            txt = reporter.generate_email(hist)
            await reporter.push_to_thingspeak(data, txt)

        except Exception as e:
            log.error(f"Loop Error: {e}")
        
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

def main():
    intents = discord.Intents.default()
    intents.message_content = True
    bot = WatchdogBot(intents=intents)

    # Schedule Monitor as Background Task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.create_task(monitor_loop(bot))
    
    log.info("Starting Bot...")
    try:
        loop.run_until_complete(bot.start(Config.DISCORD_TOKEN))
    except KeyboardInterrupt:
        log.info("Shutting down.")

if __name__ == "__main__":
    main()