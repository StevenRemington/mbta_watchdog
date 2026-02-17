import sqlite3
import pandas as pd
from datetime import datetime, timedelta

from utils.config import Config
from utils.logger import get_logger

log = get_logger("Database")

class DatabaseManager:
    def __init__(self, db_path=None):
        """
        Initializes the DB manager.
        :param db_path: Path to SQLite file. Defaults to Config.DB_FILE.
                        Pass ':memory:' for unit tests.
        """
        self.db_path = db_path or Config.DB_FILE
        self._persistent_conn = None # For :memory: databases
        
        # Log the database path being used
        if self.db_path == ":memory:":
            log.warning("⚠️ Using IN-MEMORY database. Data will not be persisted.")
        else:
            log.info(f"✅ Using database file at: {self.db_path}")
            
        self._init_db()

    def _get_conn(self):
        """
        Returns a database connection.
        If using :memory:, returns the SAME connection every time to preserve state.
        """
        if self.db_path == ":memory:":
            if self._persistent_conn is None:
                self._persistent_conn = sqlite3.connect(self.db_path)
            return self._persistent_conn
        else:
            return sqlite3.connect(self.db_path)

    def _close_conn(self, conn):
        """Closes connection ONLY if it's not the persistent in-memory one."""
        if self.db_path != ":memory:":
            conn.close()

    def _init_db(self):
        """Creates table and indexes if they don't exist."""
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
        
        # Migration: Add direction column if missing
        try:
            cursor.execute("ALTER TABLE train_logs ADD COLUMN direction TEXT")
        except sqlite3.OperationalError:
            pass 
            
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_log_time ON train_logs (log_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_train_id ON train_logs (train_id)')
        
        conn.commit()
        self._close_conn(conn)

    def insert_data(self, df):
        if df.empty: return

        if 'Direction' not in df.columns:
            df['Direction'] = 'UNK'

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
        self._close_conn(conn)
        log.info(f"Inserted {len(records)} rows into DB.")

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