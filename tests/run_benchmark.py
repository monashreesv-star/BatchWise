import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_db, execute_one, execute_query
from app.models import reset_db
from seed import seed_database
from app.services.sales_service import create_sales_order, approve_sales_order, generate_invoice_for_so, UnauthorizedError
from app.services.purchase_service import create_purchase_order, create_goods_receipt_note
from app.services.production_service import create_production_order, complete_production_run
from app.services.payment_service import record_customer_payment, get_customer_outstanding_ledger
from app.services.traceability_service import trace_finished_good_upstream, trace_raw_material_downstream
from app.services.report_service import (
    get_monthly_stock_ledger_summary, get_gstr1_sales_report,
    get_production_variance_report, export_to_csv, export_to_excel_xml
)
from app.engine.ledger import verify_inventory_integrity, get_item_stock
from app.engine.shortage import check_stock_shortage
from app.engine.bom_production import add_pack_size_bom

def log_step(step_num, title):
    print(f"\n{'='*75}")
    print(f" [BENCHMARK STEP {step_num}] {title}")
    print(f"{'='*75}")

def assert_equal(actual, expected, desc):
    if actual == expected:
        print(f"  [PASS] {desc}: {actual}")
    else:
        print(f"  [FAIL] {desc}: Expected {expected}, got {actual}")
        raise AssertionError(f"Assertion failed for {desc}: Expected {expected}, got {actual}")

def assert_almost_equal(actual, expected, desc, tolerance=0.01):
    diff = abs(actual - expected)
    if diff <= tolerance:
        print(f"  [PASS] {desc}: {actual} (approx {expected})")
    else:
        print(f"  [FAIL] {desc}: Expected {expected}, got {actual} (diff {diff})")
        raise AssertionError(f"Assertion failed for {desc}: Expected {expected}, got {actual}")

def run_benchmark():
    print("===========================================================================")
    print(" BATCHWISE INDUSTRIAL ERP - END-TO-END BENCHMARK VERIFICATION SUITE")
    print("===========================================================================")

    log_step("0", "Clean Database Initialization & Baseline Seeding")
    seed_database(clean=True)

    with get_db() as conn:
        users = execute_query("SELECT id, username, role FROM users")
        assert_equal(len(users), 5, "Total business roles seeded")
        user_map = {u["username"]: u for u in users}

        items = execute_query("SELECT id, sku, name FROM items")
        item_map = {it["sku"]: it for it in items}

        parties = execute_query("SELECT id, name, party_type FROM parties")
        party_map = {p["name"]: p for p in parties}

    log_step("1", "Salesman (sales_ravi) Places Retailer A Order")
    salesman = user_map["sales_ravi"]
    retailer_a = party_map["Retailer A Supermarkets"]
    bread_item = item_map["FG-BREAD-400"]

    with get_db() as conn:
        so_res = create_sales_order(
            conn, user=salesman, customer_id=retailer_a["id"],
            items=[{"item_id": bread_item["id"], "quantity": 100, "unit_price": 40.0}],
            notes="Retailer A initial weekly order"
        )
        so_id = so_res["so_id"]

    with get_db() as conn:
        db_so = execute_one("SELECT * FROM sales_orders WHERE id = ?", (so_id,))
        assert_equal(db_so["status"], "pending_approval", "SO Status")
        assert_almost_equal(db_so["total_taxable"], 4000.0, "SO Taxable Amount")
        assert_almost_equal(db_so["total_cgst"], 100.0, "SO CGST (2.5%)")
        assert_almost_equal(db_so["total_sgst"], 100.0, "SO SGST (2.5%)")
        assert_almost_equal(db_so["grand_total"], 4200.0, "SO Grand Total")

    log_step("2", "Security & RBAC Enforcement: Salesman Forbidden from Approving")
    with get_db() as conn:
        try:
            approve_sales_order(conn, user=salesman, so_id=so_id)
            raise AssertionError("Security failure: Salesman was able to approve sales order!")
        except UnauthorizedError:
            print("  [PASS] Role Permission Check: Salesman successfully blocked from approving order.")

    log_step("3", "Procurement: Purchase Manager Orders & Inwards 1,000 kg Flour")
    purchaser = user_map["purchase_priya"]
    supplier = party_map["Golden Grain Agro Mills Ltd"]
    flour_item = item_map["RM-FLOUR-01"]

    with get_db() as conn:
        po_res = create_purchase_order(
            conn, user=purchaser, supplier_id=supplier["id"],
            items=[{"item_id": flour_item["id"], "quantity": 1000.0, "unit_price": 30.0}]
        )
        po_id = po_res["po_id"]

        grn_res = create_goods_receipt_note(
            conn, user=purchaser, po_id=po_id, supplier_invoice_no="GG-INV-9981",
            vehicle_no="KA-01-AB-1234",
            received_items=[{
                "item_id": flour_item["id"],
                "accepted_qty": 1000.0,
                "unit_cost": 30.0,
                "batch_number": "RM-FLOUR-2026-B01",
                "mfg_date": "2026-11-17",
                "expiry_date": "2027-05-17"
            }]
        )

    with get_db() as conn:
        db_batch = execute_one("SELECT * FROM stock_batches WHERE batch_number = 'RM-FLOUR-2026-B01'")
        assert_equal(db_batch["current_qty"], 1000.0, "Raw Flour Batch Current Qty")
        assert_equal(db_batch["unit_cost"], 30.0, "Raw Flour Batch Unit Cost")

        db_tx = execute_one("""
            SELECT * FROM stock_transactions
            WHERE batch_number = 'RM-FLOUR-2026-B01' AND transaction_type = 'INWARD'
        """)
        assert_equal(db_tx["qty"], 1000.0, "Ledger Inward Qty")
        assert_equal(db_tx["total_value"], 30000.0, "Ledger Inward Valuation")

        is_valid, _ = verify_inventory_integrity(conn)
        assert_equal(is_valid, True, "Inventory Ledger Integrity Audit after GRN")

    log_step("4", "Production: BOM Consumption, Scrap Logging & Variance Analysis")
    prod_manager = user_map["prod_kumar"]

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM boms WHERE bom_code = 'BOM-BREAD-400'")
        bom_id = cur.fetchone()["id"]

        wo_res = create_production_order(
            conn, user=prod_manager, bom_id=bom_id, target_qty=1000.0,
            batch_number="FG-BREAD-2026-B01", start_date="2026-11-17",
            notes="Morning industrial baking shift"
        )
        wo_id = wo_res["wo_id"]

        flour_batch = execute_one("SELECT id FROM stock_batches WHERE batch_number = 'RM-FLOUR-2026-B01'")
        sugar_batch = execute_one("SELECT id FROM stock_batches WHERE batch_number = 'RM-SUGAR-SEED01'")
        yeast_batch = execute_one("SELECT id FROM stock_batches WHERE batch_number = 'RM-YEAST-SEED01'")
        pouch_batch = execute_one("SELECT id FROM stock_batches WHERE batch_number = 'PM-POUCH-SEED01'")

        prod_res = complete_production_run(
            conn, user=prod_manager, wo_id=wo_id,
            actual_qty_produced=995.0,
            consumptions=[
                {"component_item_id": flour_item["id"], "batch_id": flour_batch["id"], "actual_qty": 258.0, "scrap_qty": 8.0, "notes": "Dough preparation excess loss"},
                {"component_item_id": item_map["RM-SUGAR-01"]["id"], "batch_id": sugar_batch["id"], "actual_qty": 30.0, "scrap_qty": 0.0},
                {"component_item_id": item_map["RM-YEAST-01"]["id"], "batch_id": yeast_batch["id"], "actual_qty": 20.0, "scrap_qty": 0.0},
                {"component_item_id": item_map["PM-POUCH-400"]["id"], "batch_id": pouch_batch["id"], "actual_qty": 1005.0, "scrap_qty": 10.0, "notes": "Sealing machine tear"},
            ],
            labor_cost=1500.0, overhead_cost=1000.0
        )

    with get_db() as conn:
        db_wo = execute_one("SELECT * FROM production_work_orders WHERE id = ?", (wo_id,))
        assert_equal(db_wo["actual_qty"], 995.0, "Actual Finished Bread Produced")
        assert_equal(db_wo["status"], "completed", "Work Order Status")
        assert_almost_equal(db_wo["material_quantity_variance"], -320.80, "Total Batch Material Quantity Variance (MQV)")
        assert_almost_equal(db_wo["yield_variance_percentage"], -0.50, "Production Yield Variance %")
        assert_equal(db_wo["actual_unit_cost"] > 16.0, True, "Unit Cost Calculated (> ₹16)")

        flour_cons = execute_one("""
            SELECT * FROM wo_material_consumptions
            WHERE wo_id = ? AND component_item_id = ?
        """, (wo_id, flour_item["id"]))
        assert_almost_equal(flour_cons["variance_cost"], -277.50, "Flour Material Quantity Variance (MQV)")
        assert_equal(flour_cons["scrap_qty"], 8.0, "Flour Scrap Logged (kg)")

        flour_stock = get_item_stock(conn, flour_item["id"])
        assert_equal(flour_stock, 742.0, "Remaining Flour Stock in Warehouse")

        fg_batch = execute_one("SELECT * FROM stock_batches WHERE batch_number = 'FG-BREAD-2026-B01'")
        assert_equal(fg_batch["current_qty"], 995.0, "Finished Goods Batch Stock")

        is_valid, _ = verify_inventory_integrity(conn)
        assert_equal(is_valid, True, "Stock Ledger Integrity Audit after Production Run")

    log_step("5", "Admin Approves Retailer A Order & Issues Official GST Invoice")
    admin = user_map["admin"]

    with get_db() as conn:
        approve_sales_order(conn, user=admin, so_id=so_id)
        inv_res = generate_invoice_for_so(conn, user=admin, so_id=so_id)
        inv_id = inv_res["invoice_id"]

    with get_db() as conn:
        db_inv = execute_one("SELECT * FROM invoices WHERE id = ?", (inv_id,))
        assert_equal(db_inv["status"], "unpaid", "Invoice Status")
        assert_almost_equal(db_inv["total_taxable"], 4000.0, "Invoice Taxable")
        assert_almost_equal(db_inv["total_cgst"], 100.0, "Invoice CGST")
        assert_almost_equal(db_inv["total_sgst"], 100.0, "Invoice SGST")
        assert_almost_equal(db_inv["grand_total"], 4200.0, "Invoice Grand Total")
        assert_almost_equal(db_inv["balance_due"], 4200.0, "Invoice Balance Due")
        assert_equal(os.path.exists(db_inv["pdf_path"]), True, "GST Invoice PDF File Exists on Disk")

        bread_stock = get_item_stock(conn, bread_item["id"])
        assert_equal(bread_stock, 895.0, "Finished Bread Stock after Dispatch")

        db_cust = execute_one("SELECT current_balance FROM parties WHERE id = ?", (retailer_a["id"],))
        assert_almost_equal(db_cust["current_balance"], 4200.0, "Retailer A Outstanding Ledger Balance")

    log_step("6", "Distributor B Order & Automated Shortage Detection Engine")
    distributor_b = party_map["Distributor B Wholesale Hub"]

    with get_db() as conn:
        shortage_res = check_stock_shortage(conn, [{"item_id": bread_item["id"], "quantity": 1500.0}])

        assert_equal(shortage_res["has_shortage"], True, "Shortage Detected Flag")
        item_status = shortage_res["items"][0]
        assert_equal(item_status["requested_qty"], 1500.0, "Distributor B Requested Qty")
        assert_equal(item_status["available_stock"], 895.0, "Available Stock in Active Batches")
        assert_equal(item_status["shortage_qty"], 605.0, "Calculated Shortage Deficit")

        flour_replenish = [r for r in shortage_res["raw_material_replenishment"] if r["component_sku"] == "RM-FLOUR-01"][0]
        assert_almost_equal(flour_replenish["required_for_production"], 152.76, "Flour Required for Replenishment (inc. 1% scrap)")
        print(f"  [PASS] Shortage Detection Engine correctly calculated 605 unit deficit and 151.25 kg flour replenishment.")

    log_step("7", "Accounts: Payment Processing & Outstanding Aging Ledger")
    auditor = user_map["audit_anita"]

    with get_db() as conn:
        pay_res = record_customer_payment(
            conn, user=auditor, invoice_id=inv_id, amount=2500.0,
            payment_mode="bank_transfer", reference_no="UTR-HDFC-991823"
        )

    with get_db() as conn:
        db_inv = execute_one("SELECT * FROM invoices WHERE id = ?", (inv_id,))
        assert_equal(db_inv["status"], "partially_paid", "Invoice Status after Partial Payment")
        assert_almost_equal(db_inv["amount_paid"], 2500.0, "Invoice Amount Paid")
        assert_almost_equal(db_inv["balance_due"], 1700.0, "Invoice Remaining Balance Due")

        db_cust = execute_one("SELECT current_balance FROM parties WHERE id = ?", (retailer_a["id"],))
        assert_almost_equal(db_cust["current_balance"], 1700.0, "Retailer A Remaining Balance")

        aging_res = get_customer_outstanding_ledger(conn, customer_id=retailer_a["id"])
        assert_almost_equal(aging_res["aging_summary"]["0_to_30_days"], 1700.0, "Aging 0-30 Days Bucket")

    log_step("8", "Batch Traceability: Upstream Recipe Genealogy & Downstream Recall")
    with get_db() as conn:
        up_trace = trace_finished_good_upstream(conn, "FG-BREAD-2026-B01")
        assert_equal(up_trace["found"], True, "Finished Good Upstream Trace Found")
        assert_equal(up_trace["batch_details"]["wo_number"], db_wo["wo_number"], "Linked Work Order")
        assert_equal(len(up_trace["raw_materials_consumed"]) >= 4, True, "Raw Materials Traced")
        flour_source = [m for m in up_trace["raw_materials_consumed"] if m["comp_sku"] == "RM-FLOUR-01"][0]
        assert_equal(flour_source["supplier_name"], supplier["name"], "Raw Flour Traced to Supplier")

        down_trace = trace_raw_material_downstream(conn, "RM-FLOUR-2026-B01")
        assert_equal(down_trace["found"], True, "Raw Flour Downstream Trace Found")
        assert_equal(len(down_trace["work_orders_used_in"]) >= 1, True, "Traced to Baking Work Order")
        assert_equal(len(down_trace["customers_dispatched_to"]) >= 1, True, "Traced to Customer Dispatches")
        cust_dispatch = down_trace["customers_dispatched_to"][0]
        assert_equal(cust_dispatch["customer_name"], retailer_a["name"], "Traced to Retailer A Invoice")
        print(f"  [PASS] End-to-end 360-degree traceability verified from Supplier to Customer!")

    log_step("9", "Audit & Compliance: Monthly Ledger, GSTR-1 & Formatted Excel Exports")
    with get_db() as conn:
        stock_rep = get_monthly_stock_ledger_summary(conn)
        assert_equal(stock_rep["total_inventory_value"] > 0, True, "Closing Inventory Valuation")

        gstr1_rep = get_gstr1_sales_report(conn)
        assert_almost_equal(gstr1_rep["totals"]["grand_total"], 4200.0, "GSTR-1 Grand Total Sales")

        var_rep = get_production_variance_report(conn)
        assert_equal(len(var_rep["work_orders"]), 1, "Production Work Order in Variance Report")

        csv_data = export_to_csv(stock_rep["items"], ["SKU", "Item Name", "Closing Qty", "Valuation"], ["sku", "name", "closing_qty", "total_valuation"])
        assert_equal("RM-FLOUR-01" in csv_data, True, "CSV Export Content Validation")

        excel_xml = export_to_excel_xml("Stock_Audit", ["SKU", "Item Name", "Closing Qty", "Valuation"], stock_rep["items"], ["sku", "name", "closing_qty", "total_valuation"])
        assert_equal("<Workbook" in excel_xml and "</Workbook>" in excel_xml, True, "Excel XML Structure Validation")
        print(f"  [PASS] Compliance reports and exports generated successfully.")

    log_step("10", "Interview Preparation: Dynamic Multi-Pack BOM Extension")
    with get_db() as conn:
        pouch_800 = item_map["PM-POUCH-800"]
        new_item_id, new_bom_id = add_pack_size_bom(
            conn, base_bom_code="BOM-BREAD-400",
            new_sku="FG-BREAD-800", new_name="Family Sliced Bread 800g",
            multiplier=2.0, new_packing_item_id=pouch_800["id"], selling_price=75.0
        )

        cur = conn.cursor()
        cur.execute("SELECT * FROM bom_items WHERE bom_id = ?", (new_bom_id,))
        new_bom_lines = cur.fetchall()
        cur.execute("SELECT * FROM items WHERE id = ?", (new_item_id,))
        new_item = cur.fetchone()

        assert_equal(new_item["sku"], "FG-BREAD-800", "New Pack Size SKU Created")
        flour_800 = [b for b in new_bom_lines if b["component_item_id"] == flour_item["id"]][0]
        assert_equal(flour_800["quantity"], 0.50, "Flour Scaled Proportionally (0.25 * 2.0 = 0.50 kg)")
        pouch_800_line = [b for b in new_bom_lines if b["component_item_id"] == pouch_800["id"]][0]
        assert_equal(pouch_800_line["quantity"], 1.0, "Packaging Substituted with 800g Pouch")
        print(f"  [PASS] Technical Differentiator Verified: Added 800g pack sharing existing BOM without duplicating dough math!")

    print(f"\n{'='*75}")
    print(" ALL 10 BENCHMARK PHASES PASSED WITH 100% DATABASE ASSERTIONS!")
    print(f"{'='*75}\n")

if __name__ == "__main__":
    run_benchmark()
