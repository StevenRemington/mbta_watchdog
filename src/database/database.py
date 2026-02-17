import sqlite3
import pandas as pd
from datetime import datetime, timedelta

from utils.config import Config
from utils.logger import get_logger

log = get_logger("Database")

class DatabaseManager:
    def __init__(self):
        self.db_path = Config.DB_FILE
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Creates table and indexes."""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # Create table with direction column
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS train_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_time TIMESTAMP,
                train_id TEXT,
                status TEXT,
                delay_minutes INTEGER,
                station TEXT,
                direction TEXT
            )
        ''')
        
        # MIGRATION: Attempt to add the column if it's missing (for existing DBs)
        try:
            cursor.execute("ALTER TABLE train_logs ADD COLUMN direction TEXT")
        except sqlite3.OperationalError:
            pass # Column likely already exists
            
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_log_time ON train_logs (log_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_train_id ON train_logs (train_id)')
        
        conn.commit()
        conn.close()

    def insert_data(self, df):
        if df.empty: return

        # Ensure 'Direction' exists in the incoming data
        if 'Direction' not in df.columns:
            df['Direction'] = 'UNK'

        # Rename columns to match DB Schema
        records = df.rename(columns={
            "LogTime": "log_time",
            "Train": "train_id", 
            "Status": "status",
            "DelayMinutes": "delay_minutes",
            "Station": "station",
            "Direction": "direction"
        })
        
        conn = self._get_conn()
        records.to_sql('train_logs', conn, if_exists='append', index=False)
        conn.close()
        log.info(f"Inserted {len(records)} rows into DB.")

    def get_recent_logs(self, minutes=60):
        cutoff = datetime.now() - timedelta(minutes=minutes)
        query = "SELECT * FROM train_logs WHERE log_time >= ?"
        
        conn = self._get_conn()
        df = pd.read_sql_query(query, conn, params=(cutoff,))
        conn.close()
        
        return df.rename(columns={
            "log_time": "LogTime",
            "train_id": "Train",
            "status": "Status",
            "delay_minutes": "DelayMinutes",
            "station": "Station",
            "direction": "Direction"
        })

    def get_train_history(self, train_id, days=7):
        cutoff = datetime.now() - timedelta(days=days)
        query = "SELECT * FROM train_logs WHERE train_id = ? AND log_time >= ?"
        
        conn = self._get_conn()
        df = pd.read_sql_query(query, conn, params=(train_id, cutoff))
        conn.close()
        
        return df.rename(columns={
            "log_time": "LogTime",
            "train_id": "Train",
            "status": "Status",
            "delay_minutes": "DelayMinutes",
            "station": "Station",
            "direction": "Direction"
        })