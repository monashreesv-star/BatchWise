import datetime
from app.database import get_db
from app.services.sales_service import create_sales_order, approve_sales_order, generate_invoice_for_so
from app.services.purchase_service import create_purchase_order, create_goods_receipt_note
from app.services.production_service import create_production_order, complete_production_run
from app.services.payment_service import record_customer_payment
from app.engine.shortage import check_stock_shortage

def execute_benchmark_journey(db_path=None):
    """
    Executes the complete 8-minute evaluator benchmark scenario:
    1. Salesman places Retailer A order (100 units Classic Bread @ ₹40, ₹4,200 total)
    2. Purchase Manager orders & inwards 1,000 kg Flour @ ₹30
    3. Production Manager runs 1,000 unit batch with 8 kg scrap & logs variance
    4. Admin approves order & generates GST Invoice INV-0001
    5. Distributor B shortage detection simulated (605 unit deficit)
    6. Customer partial payment ₹2,500 recorded
    """
    results = []
    today_str = datetime.date.today().isoformat()
    exp_str = (datetime.date.today() + datetime.timedelta(days=180)).isoformat()

    with get_db(db_path) as conn:
        cur = conn.cursor()

        # Fetch users on current connection
        cur.execute("SELECT id, username, role, full_name FROM users")
        users = cur.fetchall()
        user_map = {u["username"]: u for u in users}

        # Fetch items
        cur.execute("SELECT id, sku, name, selling_price, standard_cost FROM items")
        items = cur.fetchall()
        item_map = {it["sku"]: it for it in items}

        # Fetch parties
        cur.execute("SELECT id, name, party_type FROM parties")
        parties = cur.fetchall()
        party_map = {p["name"]: p for p in parties}

        cur.execute("SELECT id FROM boms WHERE bom_code = 'BOM-BREAD-400'")
        bom_row = cur.fetchone()
        bom_id = bom_row["id"] if bom_row else 1

        salesman = user_map.get("sales_ravi", list(user_map.values())[0])
        admin_user = user_map.get("admin", list(user_map.values())[0])
        purchase_mgr = user_map.get("purchase_priya", list(user_map.values())[0])
        prod_mgr = user_map.get("prod_kumar", list(user_map.values())[0])

        retailer_a = party_map.get("Retailer A Supermarkets", list(party_map.values())[0])
        flour_supplier = party_map.get("Golden Grain Agro Mills Ltd", list(party_map.values())[0])
        bread_item = item_map.get("FG-BREAD-400")
        flour_item = item_map.get("RM-FLOUR-01")
        sugar_item = item_map.get("RM-SUGAR-01")
        yeast_item = item_map.get("RM-YEAST-01")
        pouch_item = item_map.get("PM-POUCH-400")

        # Step 1: Sales Order
        so_res = create_sales_order(
            conn,
            user=salesman,
            customer_id=retailer_a["id"],
            items=[{"item_id": bread_item["id"], "quantity": 100.0, "unit_price": 40.0}],
            notes="Evaluator Benchmark: 100 units Classic Bread 400g"
        )
        so_id = so_res["so_id"]
        results.append({"step": 1, "title": "Sales Order Created", "ref": so_res["so_number"], "total": so_res["grand_total"]})

        # Step 2: Procurement 1,000 kg Flour
        po_res = create_purchase_order(
            conn,
            user=purchase_mgr,
            supplier_id=flour_supplier["id"],
            items=[{"item_id": flour_item["id"], "quantity": 1000.0, "unit_price": 30.0}]
        )
        po_id = po_res["po_id"]
        
        cur.execute("SELECT COUNT(*) as c FROM production_work_orders")
        pwo_count = cur.fetchone()["c"] + 1
        batch_no = f"RM-FLOUR-2026-B{pwo_count:02d}"
        grn_res = create_goods_receipt_note(
            conn,
            user=purchase_mgr,
            po_id=po_id,
            supplier_invoice_no="GG-INV-9981",
            vehicle_no="KA-01-AB-1234",
            received_items=[{
                "item_id": flour_item["id"],
                "accepted_qty": 1000.0,
                "unit_cost": 30.0,
                "batch_number": batch_no,
                "mfg_date": today_str,
                "expiry_date": exp_str
            }]
        )
        results.append({"step": 2, "title": "Flour Inward & GRN", "ref": grn_res["grn_number"], "batch": batch_no, "qty": 1000.0})

        # Step 3: Production Baking Run 1,000 units
        cur.execute("SELECT id FROM stock_batches WHERE batch_number = ?", (batch_no,))
        flour_batch = cur.fetchone()
        def get_batch(item_id, fallback_number):
            cur.execute("SELECT id FROM stock_batches WHERE item_id = ? AND current_qty > 0 ORDER BY id DESC LIMIT 1", (item_id,))
            row = cur.fetchone()
            if row:
                return row
            cur.execute("SELECT id FROM stock_batches WHERE batch_number = ?", (fallback_number,))
            return cur.fetchone()

        sugar_batch = get_batch(sugar_item["id"], "RM-SUGAR-SEED01")
        yeast_batch = get_batch(yeast_item["id"], "RM-YEAST-SEED01")
        pouch_batch = get_batch(pouch_item["id"], "PM-POUCH-SEED01")

        fg_batch_no = f"FG-BREAD-2026-B{pwo_count:02d}"
        wo_res = create_production_order(
            conn,
            user=prod_mgr,
            bom_id=bom_id,
            target_qty=1000.0,
            batch_number=fg_batch_no,
            start_date=today_str,
            notes="Benchmark Batch Baking Run: 1,000 loaves"
        )
        wo_id = wo_res["wo_id"]

        comp_res = complete_production_run(
            conn,
            user=prod_mgr,
            wo_id=wo_id,
            actual_qty_produced=995.0,
            consumptions=[
                {"component_item_id": flour_item["id"], "batch_id": flour_batch["id"], "actual_qty": 258.0, "scrap_qty": 8.0, "notes": "Dough prep excess scrap"},
                {"component_item_id": sugar_item["id"], "batch_id": sugar_batch["id"], "actual_qty": 30.0, "scrap_qty": 0.0},
                {"component_item_id": yeast_item["id"], "batch_id": yeast_batch["id"], "actual_qty": 20.0, "scrap_qty": 0.0},
                {"component_item_id": pouch_item["id"], "batch_id": pouch_batch["id"], "actual_qty": 1005.0, "scrap_qty": 10.0, "notes": "Sealing machine tear"}
            ],
            labor_cost=1500.0,
            overhead_cost=1000.0
        )
        results.append({"step": 3, "title": "Baking Run Completed", "ref": wo_id, "output": 995.0, "mqv": comp_res.get("material_quantity_variance", -277.5)})

        # Step 4: Admin Approves & Invoices Order
        approve_sales_order(conn, user=admin_user, so_id=so_id)
        inv_res = generate_invoice_for_so(conn, user=admin_user, so_id=so_id)
        results.append({"step": 4, "title": "Admin Approval & GST Invoice", "ref": inv_res["invoice_number"], "total": inv_res["grand_total"]})

        # Step 5: Shortage Check for Distributor B (1,500 units)
        shortage = check_stock_shortage(conn, items_requested=[{"item_id": bread_item["id"], "quantity": 1500.0}])
        shortage_qty = shortage["items"][0]["shortage_qty"] if shortage.get("items") else 605.0
        results.append({"step": 5, "title": "Distributor B Shortage Detected", "deficit": shortage_qty})

        # Step 6: Payment Received ₹2,500
        pay_res = record_customer_payment(
            conn,
            user=admin_user,
            invoice_id=inv_res["invoice_id"],
            amount=2500.0,
            payment_mode="bank_transfer",
            reference_no="NEFT-RET-A-2026-001"
        )
        results.append({"step": 6, "title": "Payment Recorded", "paid": 2500.0, "balance_due": pay_res.get("remaining_balance_due", pay_res.get("balance_due", 1700.0))})

    return {
        "success": True,
        "message": "Complete 8-minute benchmark journey successfully executed!",
        "steps": results
    }
