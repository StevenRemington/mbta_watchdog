import pandas as pd
import os
import sqlite3
from config import Config
from database import DatabaseManager

def migrate():
    # 1. DEFINE PATHS
    # We look for the CSV in the 'data' folder
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
    # If your old CSV didn't have 'Station', fill it with 'Unknown'
    if 'Station' not in df.columns:
        df['Station'] = 'Unknown'

    # 4. INITIALIZE DB
    print("⚙️  Initializing Database...")
    db = DatabaseManager() # Uses Config.DB_FILE (data/mbta_logs.db)
    
    # 5. INSERT DATA
    print("🚀 Migrating records to SQLite...")
    try:
        # The insert_data method expects columns: LogTime, Train, Status, DelayMinutes, Station
        # It handles the renaming to lowercase DB columns automatically.
        db.insert_data(df)
        
        print("✅ Migration Complete!")
        print(f"   New Database: {Config.DB_FILE}")
        print("   You can now archive or delete the old CSV file.")
        
    except Exception as e:
        print(f"❌ Migration Failed: {e}")

if __name__ == "__main__":
    migrate()