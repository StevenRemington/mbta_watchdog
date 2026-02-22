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
        """Aggregates comprehensive stats for the current calendar day."""
        today = datetime.now().strftime('%Y-%m-%d')
        query = "SELECT * FROM train_logs WHERE log_time >= ?"
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(query, conn, params=(today,))
        finally:
            self._close_conn(conn)
        
        if df.empty: return None

        # Analyze unique trains by their worst performance today
        daily_trains = df.groupby('train_id').agg({
            'delay_minutes': 'max',
            'status': lambda x: 'CANCELED' if 'CANCELED' in x.values else 'ACTIVE'
        }).reset_index()

        total = len(daily_trains)
        if total == 0: return None

        # Calculate concrete impact statistics
        late_trains = daily_trains[daily_trains['delay_minutes'] > Config.DELAY_THRESHOLD]
        late_count = len(late_trains)
        canceled_count = len(daily_trains[daily_trains['status'] == 'CANCELED'])
        
        avg_delay = round(late_trains['delay_minutes'].mean(), 1) if late_count > 0 else 0
        
        max_idx = daily_trains['delay_minutes'].idxmax()
        worst_train = daily_trains.loc[max_idx]

        return {
            "date": datetime.now().strftime('%m/%d/%Y'),
            "total_tracked": total,
            "late_count": late_count,
            "canceled_count": canceled_count,
            "percent_affected": round(((late_count + canceled_count) / total) * 100, 1),
            "avg_delay_mins": avg_delay,
            "worst_train": worst_train['train_id'],
            "worst_delay": worst_train['delay_minutes']
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
        """Aggregates stats for the morning rush (6 AM - 10 AM)."""
        now = datetime.now()
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

        # Analyze unique trains by their worst performance in the morning
        daily_trains = df.groupby('train_id').agg({
            'delay_minutes': 'max',
            'status': lambda x: 'CANCELED' if 'CANCELED' in x.values else 'ACTIVE'
        }).reset_index()

        total = len(daily_trains)
        if total == 0: return None

        # Calculate concrete impact statistics
        late_trains = daily_trains[daily_trains['delay_minutes'] > Config.DELAY_THRESHOLD]
        late_count = len(late_trains)
        canceled_count = len(daily_trains[daily_trains['status'] == 'CANCELED'])
        
        # Average delay among the trains that were late
        avg_delay = round(late_trains['delay_minutes'].mean(), 1) if late_count > 0 else 0
        
        max_idx = daily_trains['delay_minutes'].idxmax()
        worst_train = daily_trains.loc[max_idx]

        return {
            "date": now.strftime('%m/%d/%Y'),
            "total_tracked": total,
            "late_count": late_count,
            "canceled_count": canceled_count,
            "percent_affected": round(((late_count + canceled_count) / total) * 100, 1),
            "avg_delay_mins": avg_delay,
            "worst_train": worst_train['train_id'],
            "worst_delay": worst_train['delay_minutes']
        }
    
    def get_train_analysis(self, train_id: str, days: int = 30):
        """
        Generates a 30-day performance report for a specific train.
        Fixed to calculate 'Per Trip' reliability consistently.
        """
        cutoff = datetime.now() - timedelta(days=days)
        conn = self._get_conn()
        
        try:
            # --- FIX: All metrics now count DISTINCT DATES (Trips) ---
            query_stats = """
                SELECT 
                    COUNT(DISTINCT date(log_time)) as total_trips,
                    
                    COUNT(DISTINCT CASE 
                        WHEN status = 'CANCELED' THEN date(log_time) 
                    END) as canceled_days,
                    
                    COUNT(DISTINCT CASE 
                        WHEN delay_minutes > ? AND status != 'CANCELED' THEN date(log_time) 
                    END) as late_days,
                    
                    AVG(delay_minutes) as avg_delay
                FROM train_logs 
                WHERE train_id = ? AND log_time >= ?
            """
            cursor = conn.cursor()
            cursor.execute(query_stats, (Config.DELAY_THRESHOLD, train_id, cutoff))
            stats = cursor.fetchone() 
            
            if not stats or stats[0] == 0:
                return None

            total = stats[0]
            canceled = stats[1] # Now represents "Days Canceled"
            late = stats[2]     # Now represents "Days Late"
            avg_delay = stats[3] if stats[3] else 0
            
            # Worst Day Analysis (Remains the same)
            query_days = """
                SELECT 
                    strftime('%w', log_time) as dow,
                    AVG(delay_minutes) as avg_daily_delay
                FROM train_logs
                WHERE train_id = ? AND log_time >= ?
                GROUP BY dow
                ORDER BY avg_daily_delay DESC
                LIMIT 1
            """
            cursor.execute(query_days, (train_id, cutoff))
            worst_day_row = cursor.fetchone()
            
            worst_day_str = "N/A"
            if worst_day_row:
                days_map = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                worst_day_str = days_map[int(worst_day_row[0])]

            # Reliability Formula
            # Now (Total Trips - Bad Trips) / Total Trips
            failures = (canceled + late)
            
            # Safety clamp to prevent negative numbers if a train is both Late AND Canceled same day
            failures = min(failures, total) 
            
            reliability = ((total - failures) / total) * 100

            return {
                "train_id": train_id,
                "days_analyzed": days,
                "total_runs": total,
                "reliability_percent": round(reliability, 1),
                "avg_delay_minutes": round(avg_delay, 1),
                "worst_day": worst_day_str,
                "canceled_count": canceled,
                "late_count": late
            }

        finally:
            self._close_conn(conn)

    def get_leaderboard_stats(self, days: int = 30):
        """
        Identifies the top 3 worst performing trains in the last 30 days.
        """
        cutoff = datetime.now() - timedelta(days=days)
        conn = self._get_conn()
        try:
            # We rank by a "Misery Score": (Cancellations * 3) + (Major Delays * 1)
            query = """
                SELECT 
                    train_id,
                    SUM(CASE WHEN status = 'CANCELED' THEN 1 ELSE 0 END) as cancels,
                    SUM(CASE WHEN delay_minutes > 15 THEN 1 ELSE 0 END) as major_delays,
                    MAX(delay_minutes) as worst_delay
                FROM train_logs
                WHERE log_time >= ?
                GROUP BY train_id
                HAVING cancels > 0 OR major_delays > 0
                ORDER BY (cancels * 3 + major_delays) DESC
                LIMIT 3 
            """
            cursor = conn.cursor()
            cursor.execute(query, (cutoff,))
            rows = cursor.fetchall()
            
            results = []
            for r in rows:
                results.append({
                    "train": r[0],
                    "cancels": r[1],
                    "major_lates": r[2],
                    "max_delay": r[3]
                })
            return results
        finally:
            self._close_conn(conn)