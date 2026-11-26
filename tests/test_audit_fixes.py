import unittest
import datetime
from app.database import get_db, execute_one, execute_query
from seed import seed_database
from app.services.payment_service import record_customer_payment, PaymentError
from app.services.production_service import create_production_order, complete_production_run
from app.engine.bom_production import create_work_order, execute_production_run
from app.services.sales_service import create_sales_order, approve_sales_order, generate_invoice_for_so
from app.services.purchase_service import create_purchase_order, create_goods_receipt_note
from app.services.traceability_service import trace_finished_good_upstream, trace_raw_material_downstream
from app.engine.ledger import verify_inventory_integrity, get_item_stock, record_inward, InsufficientStockError
from app.services.report_service import get_monthly_stock_ledger_summary, get_production_variance_report, get_gstr1_sales_report

class TestAuditFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_database(clean=True)

    def test_01_gst_payment_logic_and_overpayment_prevention(self):
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE role = 'salesman'")
            salesman = cur.fetchone()
            cur.execute("SELECT * FROM users WHERE role = 'admin'")
            admin = cur.fetchone()
            cur.execute("SELECT * FROM users WHERE role = 'accountant'")
            acct = cur.fetchone()
            cur.execute("SELECT * FROM parties WHERE party_type = 'customer'")
            customer = cur.fetchone()
            cur.execute("SELECT * FROM items WHERE category = 'finished_good'")
            item = cur.fetchone()

            # Ensure ample finished goods stock for testing
            record_inward(
                conn, item_id=item["id"], batch_number="FG-AUDIT-STOCK-TEST",
                qty=300.0, unit_cost=30.0, source_type="production", source_id=1,
                mfg_date="2026-11-26"
            )

            # Book SO: 150 units @ ₹50 = ₹7,500 + 5% GST = ₹7,875.00
            so_res = create_sales_order(conn, user=salesman, customer_id=customer["id"], items=[{"item_id": item["id"], "quantity": 150.0, "unit_price": 50.0}])
            approve_sales_order(conn, user=admin, so_id=so_res["so_id"])
            inv_res = generate_invoice_for_so(conn, user=admin, so_id=so_res["so_id"])
            inv_id = inv_res["invoice_id"]
            self.assertEqual(inv_res["grand_total"], 7875.0)

            # 1. Partial payment of ₹4,000
            pay1 = record_customer_payment(conn, user=acct, invoice_id=inv_id, amount=4000.0, payment_mode="bank_transfer", reference_no="UTR-AUDIT-TEST-001")
            self.assertEqual(pay1["amount"], 4000.0)
            self.assertEqual(pay1["balance_due"], 3875.0)
            self.assertEqual(pay1["status"], "partially_paid")

            cur.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
            inv_db = cur.fetchone()
            self.assertEqual(inv_db["amount_paid"], 4000.0)
            self.assertEqual(inv_db["balance_due"], 3875.0)
            self.assertEqual(inv_db["status"], "partially_paid")

            # 2. Overpayment rejection: attempt to pay ₹4,000 when balance is ₹3,875
            with self.assertRaises(PaymentError) as ctx:
                record_customer_payment(conn, user=acct, invoice_id=inv_id, amount=4000.0, reference_no="UTR-AUDIT-OVERPAY")
            self.assertIn("Overpayment rejected", str(ctx.exception))

            # 3. Duplicate payment rejection: attempt to record payment with same reference number
            with self.assertRaises(PaymentError) as ctx:
                record_customer_payment(conn, user=acct, invoice_id=inv_id, amount=1000.0, reference_no="UTR-AUDIT-TEST-001")
            self.assertIn("Duplicate payment rejected", str(ctx.exception))

            # 4. Settle remaining balance of ₹3,875
            pay2 = record_customer_payment(conn, user=acct, invoice_id=inv_id, amount=3875.0, reference_no="UTR-AUDIT-TEST-002")
            self.assertEqual(pay2["amount"], 3875.0)
            self.assertEqual(pay2["balance_due"], 0.0)
            self.assertEqual(pay2["status"], "paid")

            cur.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
            inv_db2 = cur.fetchone()
            self.assertEqual(inv_db2["amount_paid"], 7875.0)
            self.assertEqual(inv_db2["balance_due"], 0.0)
            self.assertEqual(inv_db2["status"], "paid")

            # 5. Attempt payment on already settled invoice
            with self.assertRaises(PaymentError) as ctx:
                record_customer_payment(conn, user=acct, invoice_id=inv_id, amount=100.0, reference_no="UTR-AUDIT-TEST-003")
            self.assertIn("already fully settled", str(ctx.exception))

    def test_02_production_work_order_uniqueness_and_deduplication(self):
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE role = 'production_manager'")
            prod_mgr = cur.fetchone()
            cur.execute("SELECT * FROM boms WHERE bom_code = 'BOM-MURUKKU-200'")
            bom = cur.fetchone()

            # 1. Automatic unique batch number generation when batch_number is None or empty
            wo_auto1 = create_production_order(conn, user=prod_mgr, bom_id=bom["id"], target_qty=200.0, batch_number=None)
            wo_auto2 = create_production_order(conn, user=prod_mgr, bom_id=bom["id"], target_qty=200.0, batch_number="")
            self.assertIsNotNone(wo_auto1["wo_id"])
            self.assertIsNotNone(wo_auto2["wo_id"])
            self.assertNotEqual(wo_auto1["wo_id"], wo_auto2["wo_id"])

            cur.execute("SELECT * FROM production_work_orders WHERE id = ?", (wo_auto1["wo_id"],))
            wo1_data = cur.fetchone()
            cur.execute("SELECT * FROM production_work_orders WHERE id = ?", (wo_auto2["wo_id"],))
            wo2_data = cur.fetchone()
            self.assertNotEqual(wo1_data["batch_number"], wo2_data["batch_number"])

            # 2. Idempotent submission: submitting exact same planned order returns existing ID without crash
            test_batch = "FG-TEST-UNIQUE-BATCH-99"
            wo_first = create_production_order(conn, user=prod_mgr, bom_id=bom["id"], target_qty=200.0, batch_number=test_batch)
            wo_dup = create_production_order(conn, user=prod_mgr, bom_id=bom["id"], target_qty=200.0, batch_number=test_batch)
            self.assertEqual(wo_first["wo_id"], wo_dup["wo_id"])

            # 3. If a different target_qty is passed with an existing batch, auto-versions safely
            wo_diff = create_production_order(conn, user=prod_mgr, bom_id=bom["id"], target_qty=300.0, batch_number=test_batch)
            self.assertNotEqual(wo_first["wo_id"], wo_diff["wo_id"])
            cur.execute("SELECT * FROM production_work_orders WHERE id = ?", (wo_diff["wo_id"],))
            wo_diff_data = cur.fetchone()
            self.assertTrue(wo_diff_data["batch_number"].startswith(test_batch))

    def test_03_production_bom_and_yield_calculations(self):
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE role = 'production_manager'")
            prod_mgr = cur.fetchone()
            cur.execute("SELECT * FROM boms WHERE bom_code = 'BOM-MURUKKU-200'")
            bom = cur.fetchone()

            wo = create_production_order(conn, user=prod_mgr, bom_id=bom["id"], target_qty=200.0, batch_number="FG-MURUKKU-CALC-TEST")
            wo_id = wo["wo_id"]

            cur.execute("SELECT id FROM stock_batches WHERE item_id = (SELECT id FROM items WHERE sku = 'RM-FLOUR-01') AND current_qty >= 40.0")
            flour_batch = cur.fetchone()
            cur.execute("SELECT id FROM stock_batches WHERE item_id = (SELECT id FROM items WHERE sku = 'RM-OIL-01') AND current_qty >= 10.5")
            oil_batch = cur.fetchone()
            cur.execute("SELECT id FROM stock_batches WHERE item_id = (SELECT id FROM items WHERE sku = 'RM-SPICE-01') AND current_qty >= 1.2")
            spice_batch = cur.fetchone()
            cur.execute("SELECT id FROM stock_batches WHERE item_id = (SELECT id FROM items WHERE sku = 'PM-POUCH-200') AND current_qty >= 194.0")
            pouch_batch = cur.fetchone()
            cur.execute("SELECT id FROM stock_batches WHERE item_id = (SELECT id FROM items WHERE sku = 'PM-CARTON-20') AND current_qty >= 9.0")
            carton_batch = cur.fetchone()

            cur.execute("SELECT id FROM items WHERE sku = 'RM-FLOUR-01'")
            flour_id = cur.fetchone()["id"]
            cur.execute("SELECT id FROM items WHERE sku = 'RM-OIL-01'")
            oil_id = cur.fetchone()["id"]
            cur.execute("SELECT id FROM items WHERE sku = 'RM-SPICE-01'")
            spice_id = cur.fetchone()["id"]
            cur.execute("SELECT id FROM items WHERE sku = 'PM-POUCH-200'")
            pouch_id = cur.fetchone()["id"]
            cur.execute("SELECT id FROM items WHERE sku = 'PM-CARTON-20'")
            carton_id = cur.fetchone()["id"]

            run_res = complete_production_run(
                conn, user=prod_mgr, wo_id=wo_id,
                actual_qty_produced=188.0,
                consumptions=[
                    {"component_item_id": flour_id, "batch_id": flour_batch["id"], "actual_qty": 40.0, "scrap_qty": 0.0},
                    {"component_item_id": oil_id, "batch_id": oil_batch["id"], "actual_qty": 10.5, "scrap_qty": 0.5},
                    {"component_item_id": spice_id, "batch_id": spice_batch["id"], "actual_qty": 1.2, "scrap_qty": 0.0},
                    {"component_item_id": pouch_id, "batch_id": pouch_batch["id"], "actual_qty": 194.0, "scrap_qty": 6.0},
                    {"component_item_id": carton_id, "batch_id": carton_batch["id"], "actual_qty": 9.0, "scrap_qty": 0.0},
                ],
                labor_cost=1200.0, overhead_cost=600.0
            )

            # Yield Efficiency: 188 / 200 = 94.0%
            self.assertEqual(run_res["yield_efficiency_percentage"], 94.0)
            # Production Variance: (188 - 200) / 200 = -6.0%
            self.assertEqual(run_res["yield_variance_percentage"], -6.0)
            # Unit Manufacturing Cost: approx ₹30.90
            self.assertAlmostEqual(run_res["actual_unit_cost"], 30.90, delta=0.15)

            # Calling complete again should return idempotent completed status without crashing
            repeat_run = complete_production_run(conn, user=prod_mgr, wo_id=wo_id, actual_qty_produced=188.0, consumptions=[])
            self.assertTrue(repeat_run.get("already_completed"))
            self.assertEqual(repeat_run["yield_efficiency_percentage"], 94.0)

    def test_04_inventory_integrity_and_traceability(self):
        with get_db() as conn:
            cur = conn.cursor()
            is_valid, discrepancies = verify_inventory_integrity(conn)
            self.assertTrue(is_valid, f"Inventory discrepancies found: {discrepancies}")

            # Verify upstream traceability on completed batch
            up_trace = trace_finished_good_upstream(conn, "FG-MURUKKU-CALC-TEST")
            self.assertTrue(up_trace["found"])
            self.assertGreater(len(up_trace["raw_materials_consumed"]), 0)
            for mat in up_trace["raw_materials_consumed"]:
                self.assertIsNotNone(mat["supplier_name"])

            # Verify downstream traceability on raw flour lot
            cur.execute("SELECT batch_number FROM stock_batches WHERE item_id = (SELECT id FROM items WHERE sku = 'RM-FLOUR-01') LIMIT 1")
            flour_batch = cur.fetchone()
            down_trace = trace_raw_material_downstream(conn, flour_batch["batch_number"])
            self.assertTrue(down_trace["found"])
            self.assertIsNotNone(down_trace["batch_details"]["supplier_name"])

    def test_05_reports_and_variance_reconciliation(self):
        with get_db() as conn:
            stock_rep = get_monthly_stock_ledger_summary(conn)
            self.assertGreater(len(stock_rep["items"]), 0)

            # Mass balance assertion: Opening + Inward - Outward == Closing
            for item in stock_rep["items"]:
                computed_closing = round(item["opening_qty"] + item["inward_qty"] - item["outward_qty"], 2)
                self.assertAlmostEqual(computed_closing, item["closing_qty"], delta=0.01)

            var_rep = get_production_variance_report(conn)
            self.assertGreater(len(var_rep["work_orders"]), 0)
            for wo in var_rep["work_orders"]:
                if wo["actual_qty"] > 0 and wo["target_qty"] > 0:
                    expected_eff = round((wo["actual_qty"] / wo["target_qty"]) * 100.0, 2)
                    self.assertEqual(wo["yield_efficiency_percentage"], expected_eff)

if __name__ == "__main__":
    unittest.main()
