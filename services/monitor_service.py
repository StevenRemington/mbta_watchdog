import sys
import asyncio
from pathlib import Path

# 1. Resolve the path to the 'src' directory correctly from a subdirectory
# Path(__file__).resolve() is services/monitor_service.py
# .parent is services/
# .parent.parent is the root mbta_watchdog/
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_PATH = str(ROOT_DIR / "src")

if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# 2. Now import using the project's absolute import style
from api.monitor import MBTAMonitor
from database.database import DatabaseManager
from utils.config import Config

async def run_monitor():
    db = DatabaseManager() 
    monitor = MBTAMonitor(db_manager=db)
    print("🚀 MBTA Monitor Service Started...")
    while True:
        try:
            # Fetch and save data independently
            data = await monitor.fetch_data()
            if not data.empty:
                monitor.save_data(data)
        except Exception as e:
            print(f"❌ Monitor Error: {e}")
            
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(run_monitor())