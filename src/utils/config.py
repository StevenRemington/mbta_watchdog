import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Resolves to the 'mbta_watchdog' root folder
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent

class Config:
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    THINGSPEAK_API_KEY = os.getenv("THINGSPEAK_API_KEY")
    MBTA_API_KEY = os.getenv("MBTA_API_KEY")
    DISCORD_ALERT_CHANNEL_ID = int(os.getenv("DISCORD_ALERT_CHANNEL_ID", 0))

    # --- PATHS ---
    DATA_DIR = ROOT_DIR / "data"
    LOG_DIR = ROOT_DIR / "logs"
    
    DB_FILE = str(DATA_DIR / "mbta_logs.db")
    DRAFT_FILE = str(DATA_DIR / "current_email_draft.txt")

    # API & THRESHOLDS
    MBTA_API_URL = "https://api-v3.mbta.com/vehicles?filter[route]=CR-Worcester&include=stop"
    THINGSPEAK_URL = "https://api.thingspeak.com/update"
    POLL_INTERVAL_SECONDS = 120
    DELAY_THRESHOLD = 5
    MAJOR_DELAY_THRESHOLD = 20

    # Ensure directories exist
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)