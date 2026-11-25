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

# Company GST details (Tamil Nadu State: 33) - CDI NIT Trichy Benchmark
COMPANY = {
    "name": "BatchWise South Indian Foods Pvt Ltd",
    "gstin": "33AABCU9603R1Z7",
    "state": "Tamil Nadu",
    "state_code": "33",
    "address": "Plot 12, SIDCO Industrial Estate, Thuvakudi, Tiruchirappalli, Tamil Nadu - 620015",
    "email": "accounts@batchwisefoods.com",
    "phone": "+91 431 250 3000"
}

ROLES = ["admin", "salesman", "purchase_manager", "production_manager", "auditor"]
