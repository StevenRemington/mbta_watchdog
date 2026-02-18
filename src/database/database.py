import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import threading

from utils.config import Config
from utils.logger import get_logger

log = get_logger("Database")

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, db_path=None):
        """Thread-safe Singleton implementation."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DatabaseManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path=None):
        """
        Initializes the connection only once.
        """
        if self._initialized: return
        
        self.db_path = db_path or Config.DB_FILE
        self._persistent_conn = None 
        
        if self.db_path == ":memory:":
            log.warning("⚠️ Using IN-MEMORY database. Data will not be persisted.")
        else:
            log.info(f"✅ Database Connection Initialized: {self.db_path}")
            
        # In a real production app, use Alembic here. 
        # For this refactor, we still init the schema but only once.
        self._init_db()
        self._initialized = True

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
        """
        Creates tables. 
        NOTE: In production, remove this and use Alembic migrations (alembic upgrade head).
        """
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
        # Indexes
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

    def get_failure_stats(self, train_id: str, days: int = 7, delay_threshold: int = 5) -> list:
        """
        Returns a list of dates (str) where the train failed (Late or Canceled).
        Replaces the logic previously found in Reporter._get_receipt.
        """
        cutoff = datetime.now() - timedelta(days=days)
        query = """
            SELECT date(log_time) as log_date, MAX(delay_minutes) as max_delay, status
            FROM train_logs
            WHERE train_id = ? AND log_time >= ?
            GROUP BY log_date
        """
        conn = self._get_conn()
        try:
            # We use the raw cursor here for more complex aggregation flexibility
            cursor = conn.cursor()
            cursor.execute(query, (train_id, cutoff))
            rows = cursor.fetchall()
        finally:
            self._close_conn(conn)

        bad_dates = []
        for r in rows:
            # r = (log_date, max_delay, status)
            log_date, max_delay, status = r[0], r[1], r[2]
            
            # Check if this day counts as a 'failure'
            # Note: The group_concat in SQLite is tricky, so we check if the *max* delay was high
            # or if the status captured was CANCELED.
            if max_delay > delay_threshold or status == 'CANCELED':
                bad_dates.append(log_date)
                
        return bad_dates
    
    def get_morning_commute_stats(self):
        """Aggregates stats for the morning rush (6 AM - 10 AM) and assigns a grade."""
        now = datetime.now()
        # Define the 6:00 AM to 10:00 AM window for TODAY
        start_str = now.replace(hour=6, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        end_str = now.replace(hour=10, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        
        query = "SELECT * FROM train_logs WHERE log_time >= ? AND log_time <= ?"
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(query, conn, params=(start_str, end_str))
        finally:
            self._close_conn(conn)
        
        if df.empty: 
            return None

        # Group by Train ID to find the worst status for each unique train
        daily_trains = df.groupby('train_id').agg({
            'delay_minutes': 'max',
            'status': lambda x: 'CANCELED' if 'CANCELED' in x.values else 'ACTIVE'
        }).reset_index()

        total = len(daily_trains)
        if total == 0: return None

        # Calculate Metrics
        late_count = len(daily_trains[daily_trains['delay_minutes'] > Config.DELAY_THRESHOLD])
        canceled_count = len(daily_trains[daily_trains['status'] == 'CANCELED'])
        on_time = total - late_count - canceled_count
        
        # Grading Logic (Strict Curve)
        # 90%+ = A, 80% = B, 70% = C, 60% = D, <60% = F
        score = (on_time / total) * 100
        if score >= 90: grade = "A"
        elif score >= 80: grade = "B"
        elif score >= 70: grade = "C"
        elif score >= 60: grade = "D"
        else: grade = "F"

        # Find the Worst Offender
        max_idx = daily_trains['delay_minutes'].idxmax()
        worst_train = daily_trains.loc[max_idx]

        return {
            "date": now.strftime('%Y-%m-%d'),
            "total": total,
            "late": late_count,
            "canceled": canceled_count,
            "grade": grade,
            "worst_train": worst_train['train_id'],
            "worst_delay": worst_train['delay_minutes']
        }