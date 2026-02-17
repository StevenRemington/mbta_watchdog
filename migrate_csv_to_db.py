import pandas as pd
import os
import sys
from pathlib import Path

# Bootstrap path
SRC_PATH = str(Path(__file__).resolve().parent / "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from utils.config import Config
from database.database import DatabaseManager

def migrate():
    # 1. DEFINE PATHS
    csv_file = os.path.join("data", "mbta_worcester_log.csv")
    
    if not os.path.exists(csv_file):
        print(f"❌ Old CSV file not found at: {csv_file}")
        return

    print(f"📖 Reading {csv_file}...")
    
    # 2. READ CSV
    try:
        df = pd.read_csv(csv_file)
        print(f"   -> Found {len(df)} records.")
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return

    # 3. CLEAN DATA (Handle Missing Columns)
    if 'Station' not in df.columns:
        df['Station'] = 'Unknown'

    # 4. INITIALIZE DB
    print("⚙️  Initializing Database...")
    db = DatabaseManager() 
    
    # 5. INSERT DATA
    print("🚀 Migrating records to SQLite...")
    try:
        db.insert_data(df)
        print("✅ Migration Complete!")
        print(f"   New Database: {Config.DB_FILE}")
        print("   You can now archive or delete the old CSV file.")
    except Exception as e:
        print(f"❌ Migration Failed: {e}")

if __name__ == "__main__":
    migrate()