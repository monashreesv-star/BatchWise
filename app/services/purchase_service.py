import datetime
from app.database import get_db
from app.security import has_permission
from app.engine.ledger import record_inward
from app.engine.gst_invoice import calculate_gst_breakdown

class PurchaseServiceError(Exception):
    pass

class UnauthorizedError(PurchaseServiceError):
    pass

def create_purchase_order(conn, user: dict, supplier_id: int, items: list):
    if not has_permission(user["role"], "purchase:create"):
        raise UnauthorizedError(f"Role '{user['role']}' is not authorized to create purchase orders.")

    cur = conn.cursor()
    cur.execute("SELECT * FROM parties WHERE id = ? AND party_type = 'supplier'", (supplier_id,))
    supplier = cur.fetchone()
    if not supplier:
        raise PurchaseServiceError(f"Supplier ID {supplier_id} not found.")

    gst_calc = calculate_gst_breakdown(supplier["state"], items)

    cur.execute("SELECT COUNT(*) as count FROM purchase_orders")
    po_count = cur.fetchone()["count"] + 1
    po_number = f"PO-{datetime.date.today().strftime('%Y%m%d')}-{po_count:04d}"

    cur.execute("""
        INSERT INTO purchase_orders (
            po_number, supplier_id, status, order_date,
            total_taxable, total_tax, grand_total, created_by
        ) VALUES (?, ?, 'approved', ?, ?, ?, ?, ?)
    """, (
        po_number, supplier_id, datetime.date.today().isoformat(),
        gst_calc["total_taxable"], gst_calc["total_tax"], gst_calc["grand_total"], user["id"]
    ))
    po_id = cur.lastrowid

    for it in gst_calc["items"]:
        cur.execute("""
            INSERT INTO po_items (
                po_id, item_id, quantity, unit_price, gst_rate,
                taxable_amount, cgst_amount, sgst_amount, total_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            po_id, it["item_id"], it["quantity"], it["unit_price"], it["gst_rate"],
            it["taxable_amount"], it["cgst_amount"], it["sgst_amount"], it["total_amount"]
        ))

    return {
        "po_id": po_id,
        "po_number": po_number,
        "supplier_name": supplier["name"],
        "grand_total": gst_calc["grand_total"]
    }

def create_goods_receipt_note(conn, user: dict, po_id: int, supplier_invoice_no: str,
                              vehicle_no: str, received_items: list, receipt_date: str = None):
    if not has_permission(user["role"], "purchase:receive"):
        raise UnauthorizedError(f"Role '{user['role']}' cannot receive goods (GRN).")

    cur = conn.cursor()
    cur.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,))
    po = cur.fetchone()
    if not po:
        raise PurchaseServiceError(f"PO {po_id} not found.")

    receipt_date = receipt_date or datetime.date.today().isoformat()

    cur.execute("SELECT COUNT(*) as count FROM goods_receipt_notes")
    grn_count = cur.fetchone()["count"] + 1
    grn_number = f"GRN-{datetime.date.today().strftime('%Y%m%d')}-{grn_count:04d}"

    total_amt = round(sum(it["accepted_qty"] * it["unit_cost"] for it in received_items), 2)

    cur.execute("""
        INSERT INTO goods_receipt_notes (
            grn_number, po_id, supplier_id, receipt_date, vehicle_no,
            supplier_invoice_no, supplier_invoice_date, total_amount, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        grn_number, po_id, po["supplier_id"], receipt_date, vehicle_no,
        supplier_invoice_no, receipt_date, total_amt, user["id"]
    ))
    grn_id = cur.lastrowid

    for it in received_items:
        acc_qty = float(it["accepted_qty"])
        unit_cost = float(it["unit_cost"])
        b_no = it["batch_number"]
        mfg_dt = it.get("mfg_date", receipt_date)
        exp_dt = it.get("expiry_date")

        cur.execute("""
            INSERT INTO grn_items (
                grn_id, item_id, received_qty, accepted_qty, rejected_qty,
                unit_cost, batch_number, mfg_date, expiry_date
            ) VALUES (?, ?, ?, ?, 0.0, ?, ?, ?, ?)
        """, (grn_id, it["item_id"], acc_qty, acc_qty, unit_cost, b_no, mfg_dt, exp_dt))

        record_inward(
            conn, item_id=it["item_id"], batch_number=b_no, qty=acc_qty,
            unit_cost=unit_cost, source_type="grn", source_id=grn_id,
            mfg_date=mfg_dt, expiry_date=exp_dt, created_by=user["id"],
            notes=f"GRN {grn_number} from PO {po['po_number']}", reference_type="GRN"
        )

    cur.execute("UPDATE purchase_orders SET status = 'received' WHERE id = ?", (po_id,))

    return {
        "grn_id": grn_id,
        "grn_number": grn_number,
        "total_amount": total_amt,
        "status": "received"
    }
