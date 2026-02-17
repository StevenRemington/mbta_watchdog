import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # --- SECRETS ---
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    THINGSPEAK_API_KEY = os.getenv("THINGSPEAK_API_KEY")
    MBTA_API_KEY = os.getenv("MBTA_API_KEY")
    DISCORD_ALERT_CHANNEL_ID = int(os.getenv("DISCORD_ALERT_CHANNEL_ID", 0))

    # --- SETTINGS ---
    MBTA_API_URL = "https://api-v3.mbta.com/vehicles?filter[route]=CR-Worcester&include=stop"
    THINGSPEAK_URL = "https://api.thingspeak.com/update"
    
    # Paths
    DB_FILE = os.path.join("data", "mbta_logs.db")
    DRAFT_FILE = os.path.join("data", "current_email_draft.txt")

    # Thresholds
    POLL_INTERVAL_SECONDS = 120  # 2 minutes
    DELAY_THRESHOLD = 5          # Minutes (Yellow/Minor)
    MAJOR_DELAY_THRESHOLD = 20   # Minutes (Red/Alert)

    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)