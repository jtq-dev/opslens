import sqlite3
from .settings import settings

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS runs (
      id TEXT PRIMARY KEY,
      created_at TEXT NOT NULL,
      host TEXT NOT NULL,
      archive_name TEXT NOT NULL,
      uname TEXT,
      os_release TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS metrics (
      run_id TEXT NOT NULL,
      key TEXT NOT NULL,
      value REAL NOT NULL,
      unit TEXT,
      PRIMARY KEY (run_id, key),
      FOREIGN KEY (run_id) REFERENCES runs(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS artifacts (
      run_id TEXT NOT NULL,
      name TEXT NOT NULL,
      content TEXT NOT NULL,
      PRIMARY KEY (run_id, name),
      FOREIGN KEY (run_id) REFERENCES runs(id)
    )
    """)

    conn.commit()
    conn.close()
