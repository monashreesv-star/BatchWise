import datetime
from app.database import get_db
from app.security import has_permission
from app.engine.ledger import allocate_stock_fifo, record_outward, get_item_stock
from app.engine.gst_invoice import calculate_gst_breakdown, generate_gst_invoice_pdf
from app.engine.shortage import check_stock_shortage

class SalesServiceError(Exception):
    pass

class UnauthorizedError(SalesServiceError):
    pass

def create_sales_order(conn, user: dict, customer_id: int, items: list, notes: str = None):
    if not has_permission(user["role"], "sales:create"):
        raise UnauthorizedError(f"Role '{user['role']}' is not authorized to create sales orders.")

    if not items:
        raise SalesServiceError("Order must contain at least one item.")

    cur = conn.cursor()
    cur.execute("SELECT * FROM parties WHERE id = ? AND party_type = 'customer'", (customer_id,))
    customer = cur.fetchone()
    if not customer:
        raise SalesServiceError(f"Customer with ID {customer_id} does not exist.")

    gst_calc = calculate_gst_breakdown(customer["state"], items)
    
    cur.execute("SELECT MAX(id) as max_id FROM sales_orders")
    so_count = (cur.fetchone()["max_id"] or 0) + 1
    today_str = datetime.date.today().strftime('%Y%m%d')
    so_number = f"SO-{today_str}-{so_count:04d}"
    while cur.execute("SELECT 1 FROM sales_orders WHERE so_number = ?", (so_number,)).fetchone():
        so_count += 1
        so_number = f"SO-{today_str}-{so_count:04d}"
    user_id = user.get("id") or user.get("user_id", 1)

    cur.execute("""
        INSERT INTO sales_orders (
            so_number, customer_id, salesman_id, status, order_date,
            total_taxable, total_cgst, total_sgst, total_tax, grand_total, notes
        ) VALUES (?, ?, ?, 'pending_approval', ?, ?, ?, ?, ?, ?, ?)
    """, (
        so_number, customer_id, user_id, datetime.date.today().isoformat(),
        gst_calc["total_taxable"], gst_calc["total_cgst"], gst_calc["total_sgst"],
        gst_calc["total_tax"], gst_calc["grand_total"], notes
    ))
    so_id = cur.lastrowid

    for it in gst_calc["items"]:
        cur.execute("""
            INSERT INTO so_items (
                so_id, item_id, quantity, unit_price, gst_rate,
                taxable_amount, cgst_amount, sgst_amount, total_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            so_id, it["item_id"], it["quantity"], it["unit_price"], it["gst_rate"],
            it["taxable_amount"], it["cgst_amount"], it["sgst_amount"], it["total_amount"]
        ))

    return {
        "so_id": so_id,
        "so_number": so_number,
        "customer_name": customer["name"],
        "status": "pending_approval",
        "grand_total": gst_calc["grand_total"]
    }

def approve_sales_order(conn, user: dict, so_id: int):
    if not has_permission(user["role"], "sales:approve"):
        raise UnauthorizedError(f"Role '{user['role']}' is NOT authorized to approve sales orders. Admin approval required.")

    cur = conn.cursor()
    cur.execute("SELECT * FROM sales_orders WHERE id = ?", (so_id,))
    so = cur.fetchone()
    if not so:
        raise SalesServiceError(f"Sales order {so_id} does not exist.")
    if so["status"] != "pending_approval":
        raise SalesServiceError(f"Cannot approve sales order in '{so['status']}' state.")

    user_id = user.get("id") or user.get("user_id", 1)
    cur.execute("""
        UPDATE sales_orders
        SET status = 'approved', approved_by = ?, approved_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (user_id, so_id))

    return {"so_id": so_id, "status": "approved"}

def generate_invoice_for_so(conn, user: dict, so_id: int):
    if not has_permission(user["role"], "sales:invoice"):
        raise UnauthorizedError(f"Role '{user['role']}' cannot generate GST invoices.")

    cur = conn.cursor()
    cur.execute("SELECT * FROM sales_orders WHERE id = ?", (so_id,))
    so = cur.fetchone()
    if not so:
        raise SalesServiceError(f"Sales order {so_id} does not exist.")
    if so["status"] != "approved":
        raise SalesServiceError(f"Sales order must be in 'approved' state before invoicing (current: {so['status']}).")

    cur.execute("SELECT * FROM parties WHERE id = ?", (so["customer_id"],))
    customer = cur.fetchone()

    cur.execute("""
        SELECT soi.*, i.sku, i.name, i.hsn_code
        FROM so_items soi
        JOIN items i ON soi.item_id = i.id
        WHERE soi.so_id = ?
    """, (so_id,))
    so_items = cur.fetchall()

    invoice_allocations = []
    for item in so_items:
        allocs = allocate_stock_fifo(conn, item["item_id"], item["quantity"])
        for a in allocs:
            unit_price = item["unit_price"]
            taxable = round(a["allocated_qty"] * unit_price, 2)
            half_rate = item["gst_rate"] / 2.0
            cgst = round(taxable * (half_rate / 100.0), 2)
            sgst = round(taxable * (half_rate / 100.0), 2)
            total = round(taxable + cgst + sgst, 2)

            invoice_allocations.append({
                "item_id": item["item_id"],
                "sku": item["sku"],
                "name": item["name"],
                "hsn_code": item["hsn_code"],
                "batch_id": a["batch_id"],
                "batch_number": a["batch_number"],
                "quantity": a["allocated_qty"],
                "unit_price": unit_price,
                "gst_rate": item["gst_rate"],
                "taxable_amount": taxable,
                "cgst_amount": cgst,
                "sgst_amount": sgst,
                "total_amount": total
            })

    cur.execute("SELECT MAX(id) as max_id FROM invoices")
    inv_count = (cur.fetchone()["max_id"] or 0) + 1
    today_str = datetime.date.today().strftime('%Y%m%d')
    inv_number = f"INV-{today_str}-{inv_count:04d}"
    while cur.execute("SELECT 1 FROM invoices WHERE invoice_number = ?", (inv_number,)).fetchone():
        inv_count += 1
        inv_number = f"INV-{today_str}-{inv_count:04d}"
    inv_date = datetime.date.today().isoformat()
    due_date = (datetime.date.today() + datetime.timedelta(days=15)).isoformat()

    total_taxable = round(sum(a["taxable_amount"] for a in invoice_allocations), 2)
    total_cgst = round(sum(a["cgst_amount"] for a in invoice_allocations), 2)
    total_sgst = round(sum(a["sgst_amount"] for a in invoice_allocations), 2)
    grand_total = round(sum(a["total_amount"] for a in invoice_allocations), 2)

    user_id = user.get("id") or user.get("user_id", 1)
    cur.execute("""
        INSERT INTO invoices (
            invoice_number, so_id, customer_id, invoice_date, due_date,
            total_taxable, total_cgst, total_sgst, total_igst, grand_total,
            amount_paid, balance_due, status, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, 0.0, ?, 'unpaid', ?)
    """, (
        inv_number, so_id, customer["id"], inv_date, due_date,
        total_taxable, total_cgst, total_sgst, grand_total,
        grand_total, user_id
    ))
    inv_id = cur.lastrowid

    for a in invoice_allocations:
        record_outward(
            conn, item_id=a["item_id"], batch_id=a["batch_id"], qty=a["quantity"],
            reference_type="INV", reference_id=inv_id, created_by=user_id,
            notes=f"Dispatched for Invoice {inv_number}", transaction_type="OUTWARD"
        )
        cur.execute("""
            INSERT INTO invoice_items (
                invoice_id, item_id, batch_id, batch_number, quantity,
                unit_price, hsn_code, taxable_amount, gst_rate, cgst_amount,
                sgst_amount, total_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            inv_id, a["item_id"], a["batch_id"], a["batch_number"], a["quantity"],
            a["unit_price"], a["hsn_code"], a["taxable_amount"], a["gst_rate"],
            a["cgst_amount"], a["sgst_amount"], a["total_amount"]
        ))

    new_balance = round(customer["current_balance"] + grand_total, 2)
    cur.execute("UPDATE parties SET current_balance = ? WHERE id = ?", (new_balance, customer["id"]))
    cur.execute("UPDATE sales_orders SET status = 'invoiced' WHERE id = ?", (so_id,))

    pdf_data = {
        "invoice_number": inv_number,
        "invoice_date": inv_date,
        "due_date": due_date,
        "so_number": so["so_number"],
        "customer": customer,
        "items": invoice_allocations,
        "total_taxable": total_taxable,
        "total_cgst": total_cgst,
        "total_sgst": total_sgst,
        "grand_total": grand_total
    }
    pdf_path = generate_gst_invoice_pdf(pdf_data)
    cur.execute("UPDATE invoices SET pdf_path = ? WHERE id = ?", (pdf_path, inv_id))

    return {
        "invoice_id": inv_id,
        "invoice_number": inv_number,
        "total_taxable": total_taxable,
        "total_cgst": total_cgst,
        "total_sgst": total_sgst,
        "grand_total": grand_total,
        "balance_due": grand_total,
        "pdf_path": pdf_path
    }
