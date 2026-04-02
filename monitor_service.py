import asyncio
from src.api.monitor import MBTAMonitor
from src.database.database import DatabaseManager
from src.utils.config import Config

async def run_monitor():
    db = DatabaseManager() 
    monitor = MBTAMonitor(db_manager=db)
    print("🚀 MBTA Monitor Service Started...")
    while True:
        # Fetch and save data independently
        data = await monitor.fetch_data()
        monitor.save_data(data)
        await asyncio.sleep(Config.POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(run_monitor())