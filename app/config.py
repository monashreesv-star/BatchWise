import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# In serverless environments (e.g. Vercel, AWS Lambda), current working directory is read-only.
# We store SQLite database and generated invoices in the temporary directory.
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    DATA_DIR = Path(tempfile.gettempdir()) / "batchwise_data"
else:
    DATA_DIR = BASE_DIR / "data"

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

DB_PATH = os.environ.get("BATCHWISE_DB", str(DATA_DIR / "batchwise.db"))
SECRET_KEY = os.environ.get("BATCHWISE_SECRET", "batchwise-secret-key-production-ready-2026")
SESSION_COOKIE = "batchwise_session"

# Company GST details (Karnataka State: 29)
COMPANY = {
    "name": "BatchWise Bakeries & Foods Pvt Ltd",
    "gstin": "29AABCU9603R1Z7",
    "state": "Karnataka",
    "state_code": "29",
    "address": "Plot 42, Food Processing Industrial Area, Phase II, Bengaluru - 560058",
    "email": "accounts@batchwise.com",
    "phone": "+91 80 2839 4000"
}

ROLES = ["admin", "salesman", "purchase_manager", "production_manager", "auditor"]
