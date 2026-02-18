import sqlite3
import pandas as pd
from datetime import datetime, timedelta

from utils.config import Config
from utils.logger import get_logger

log = get_logger("Database")

class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = db_path or Config.DB_FILE
        self._persistent_conn = None 
        
        if self.db_path == ":memory:":
            log.warning("⚠️ Using IN-MEMORY database. Data will not be persisted.")
        else:
            log.info(f"✅ Using database file at: {self.db_path}")
            
        self._init_db()

    def _get_conn(self):
        if self.db_path == ":memory:":
            if self._persistent_conn is None:
                self._persistent_conn = sqlite3.connect(self.db_path)
            return self._persistent_conn
        return sqlite3.connect(self.db_path)

    def _close_conn(self, conn):
        if self.db_path != ":memory:":
            conn.close()

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
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
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_log_time ON train_logs (log_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_train_id ON train_logs (train_id)')
        conn.commit()
        self._close_conn(conn)

    def insert_data(self, df):
        if df.empty: return
        records = df.rename(columns={
            "LogTime": "log_time", "Train": "train_id", 
            "Status": "status", "DelayMinutes": "delay_minutes",
            "Station": "station", "Direction": "direction"
        })
        conn = self._get_conn()
        records.to_sql('train_logs', conn, if_exists='append', index=False)
        self._close_conn(conn)

    def get_recent_logs(self, minutes=60):
        cutoff = datetime.now() - timedelta(minutes=minutes)
        query = "SELECT * FROM train_logs WHERE log_time >= ?"
        conn = self._get_conn()
        df = pd.read_sql_query(query, conn, params=(cutoff,))
        self._close_conn(conn)
        return df.rename(columns={
            "log_time": "LogTime", "train_id": "Train",
            "status": "Status", "delay_minutes": "DelayMinutes",
            "station": "Station", "direction": "Direction"
        })

    def get_train_history(self, train_id, days=7):
        cutoff = datetime.now() - timedelta(days=days)
        query = "SELECT * FROM train_logs WHERE train_id = ? AND log_time >= ?"
        conn = self._get_conn()
        df = pd.read_sql_query(query, conn, params=(train_id, cutoff))
        self._close_conn(conn)
        return df.rename(columns={
            "log_time": "LogTime", "train_id": "Train",
            "status": "Status", "delay_minutes": "DelayMinutes",
            "station": "Station", "direction": "Direction"
        })

    def get_daily_summary_stats(self):
        """Aggregates stats for the current calendar day."""
        today = datetime.now().strftime('%Y-%m-%d')
        query = "SELECT * FROM train_logs WHERE log_time >= ?"
        conn = self._get_conn()
        df = pd.read_sql_query(query, conn, params=(today,))
        self._close_conn(conn)
        
        if df.empty: return None

        # Analyze unique trains by their worst performance today
        daily_trains = df.groupby('train_id').agg({
            'delay_minutes': 'max',
            'status': lambda x: 'CANCELED' if 'CANCELED' in x.values else 'ACTIVE'
        }).reset_index()

        total = len(daily_trains)
        affected = daily_trains[
            (daily_trains['delay_minutes'] > Config.DELAY_THRESHOLD) | 
            (daily_trains['status'] == 'CANCELED')
        ]
        affected_count = len(affected)
        
        # Biggest delay logic
        max_idx = daily_trains['delay_minutes'].idxmax()
        worst_train = daily_trains.loc[max_idx]

        return {
            "date": today,
            "total": total,
            "affected_count": affected_count,
            "percent_affected": (affected_count / total * 100) if total > 0 else 0,
            "max_train": worst_train['train_id'],
            "max_delay": worst_train['delay_minutes']
        }