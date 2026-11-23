import sqlite3
from contextlib import contextmanager
from app.config import DB_PATH

def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def get_connection(db_path=None):
    path = db_path or DB_PATH
    try:
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(path, timeout=10.0, check_same_thread=False)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn

@contextmanager
def get_db(db_path=None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def execute_query(query, params=(), db_path=None):
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

def execute_one(query, params=(), db_path=None):
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()

def execute_write(query, params=(), db_path=None):
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.lastrowid
