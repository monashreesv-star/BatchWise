import sys
import os
from pathlib import Path

# Add project root directory to sys.path so 'app' and 'seed' packages resolve
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import DB_PATH

# Automatically bootstrap and seed the database on serverless cold start if missing
def bootstrap_database():
    try:
        from app.database import get_db
        has_tables = False
        if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
            try:
                with get_db(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                    if cur.fetchone():
                        has_tables = True
            except Exception:
                has_tables = False

        if not has_tables:
            from seed import seed_database
            seed_database(DB_PATH, clean=False)
    except Exception as e:
        print(f"[Vercel Init] Database bootstrap error: {e}")

bootstrap_database()

from app.web.app import app
