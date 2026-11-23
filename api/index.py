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
        if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
            from seed import seed_database
            seed_database(DB_PATH, clean=False)
    except Exception as e:
        print(f"[Vercel Init] Database bootstrap: {e}")

bootstrap_database()

from app.web.app import app
