import argparse
import sys
import uvicorn
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import DB_PATH
from seed import seed_database
from tests.run_benchmark import run_benchmark

def main():
    parser = argparse.ArgumentParser(description="BatchWise Industrial ERP Server & Benchmark")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--seed", action="store_true", help="Force database seed")
    parser.add_argument("--benchmark", action="store_true", help="Run automated benchmark suite and exit")

    args = parser.parse_args()

    if args.benchmark:
        print("[RUNNER] Executing BatchWise Benchmark Suite...")
        run_benchmark()
        return

    # Check if DB exists, seed if missing or requested
    db_file = Path(DB_PATH)
    if args.seed or not db_file.exists() or db_file.stat().st_size == 0:
        print("[RUNNER] Initializing and seeding clean database...")
        seed_database(clean=True)

    print(f"\n{'='*70}")
    print(" BATCHWISE INDUSTRIAL MANUFACTURING ERP v2.0")
    print(f" Live Web Dashboard: http://{args.host}:{args.port}")
    print(" Evaluator 1-Click Persona Switcher: Included in Navbar")
    print(" Automated Benchmark Mode: python run.py --benchmark")
    print(f"{'='*70}\n")

    uvicorn.run("app.web.app:app", host=args.host, port=args.port, reload=False, log_level="info")

if __name__ == "__main__":
    main()
