import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_db
from app.models import reset_db
from seed import seed_database
from app.engine.ledger import record_inward, record_outward, get_item_stock, allocate_stock_fifo, InsufficientStockError, verify_inventory_integrity

class TestStockLedger(unittest.TestCase):
    def setUp(self):
        seed_database(clean=True)

    def test_inward_outward_ledger_cycle(self):
        with get_db() as conn:
            b_id = record_inward(
                conn, item_id=1, batch_number="TEST-BATCH-01", qty=500.0,
                unit_cost=32.0, source_type="grn", source_id=1, mfg_date="2026-11-17"
            )
            self.assertEqual(get_item_stock(conn, 1), 500.0)

            tx_num = record_outward(conn, item_id=1, batch_id=b_id, qty=200.0, reference_type="WO", reference_id=1)
            self.assertTrue(tx_num.startswith("STX-"))
            self.assertEqual(get_item_stock(conn, 1), 300.0)

            is_valid, _ = verify_inventory_integrity(conn)
            self.assertTrue(is_valid)

    def test_insufficient_stock_exception(self):
        with get_db() as conn:
            b_id = record_inward(
                conn, item_id=1, batch_number="TEST-BATCH-02", qty=50.0,
                unit_cost=30.0, source_type="grn", source_id=1, mfg_date="2026-11-17"
            )
            with self.assertRaises(InsufficientStockError):
                record_outward(conn, item_id=1, batch_id=b_id, qty=100.0, reference_type="INV", reference_id=1)

    def test_fifo_allocation(self):
        with get_db() as conn:
            b1 = record_inward(conn, item_id=1, batch_number="FIFO-B1", qty=100.0, unit_cost=30.0, source_type="grn", source_id=1, mfg_date="2026-11-01")
            b2 = record_inward(conn, item_id=1, batch_number="FIFO-B2", qty=100.0, unit_cost=32.0, source_type="grn", source_id=2, mfg_date="2026-11-10")

            allocations = allocate_stock_fifo(conn, item_id=1, required_qty=150.0)
            self.assertEqual(len(allocations), 2)
            self.assertEqual(allocations[0]["batch_number"], "FIFO-B1")
            self.assertEqual(allocations[0]["allocated_qty"], 100.0)
            self.assertEqual(allocations[1]["batch_number"], "FIFO-B2")
            self.assertEqual(allocations[1]["allocated_qty"], 50.0)

if __name__ == "__main__":
    unittest.main()
