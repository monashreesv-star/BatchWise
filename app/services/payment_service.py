import datetime
from app.database import get_db
from app.security import has_permission

class PaymentError(Exception):
    pass

class UnauthorizedError(PaymentError):
    pass

def record_customer_payment(conn, user: dict, invoice_id: int, amount: float,
                            payment_mode: str = "bank_transfer", reference_no: str = None,
                            payment_date: str = None, notes: str = None):
    if not has_permission(user["role"], "payments:record"):
        raise UnauthorizedError(f"Role '{user['role']}' is not authorized to record payments.")

    if amount <= 0:
        raise PaymentError("Payment amount must be greater than zero.")

    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    inv = cur.fetchone()
    if not inv:
        raise PaymentError(f"Invoice {invoice_id} not found.")

    if inv["status"] == "paid" or inv["balance_due"] <= 0:
        raise PaymentError(f"Invoice {inv['invoice_number']} is already fully settled (balance due is ₹0.00).")

    # Prevent overpayment beyond remaining balance due
    if round(amount, 2) > round(inv["balance_due"], 2):
        raise PaymentError(
            f"Overpayment rejected: Payment amount ₹{amount:.2f} exceeds remaining balance due "
            f"₹{inv['balance_due']:.2f} for invoice {inv['invoice_number']}."
        )

    # Prevent duplicate payment with identical reference number on the same invoice
    if reference_no and reference_no.strip():
        cur.execute("""
            SELECT id, payment_number, amount, payment_date FROM payments
            WHERE invoice_id = ? AND reference_no = ?
        """, (invoice_id, reference_no.strip()))
        dup = cur.fetchone()
        if dup:
            raise PaymentError(
                f"Duplicate payment rejected: A payment ({dup['payment_number']}) with reference '{reference_no.strip()}' "
                f"of ₹{dup['amount']:.2f} was already recorded for invoice {inv['invoice_number']} on {dup['payment_date']}."
            )

    payment_date = payment_date or datetime.date.today().isoformat()
    new_paid = round(inv["amount_paid"] + amount, 2)
    new_due = round(inv["balance_due"] - amount, 2)

    # Never mark an invoice fully paid unless total cumulative payments equal or exceed the grand total
    if new_due <= 0.001 and new_paid >= round(inv["grand_total"], 2) - 0.01:
        new_due = 0.0
        new_status = "paid"
    else:
        new_status = "partially_paid"

    cur.execute("SELECT MAX(id) as max_id FROM payments")
    max_id = (cur.fetchone()["max_id"] or 0) + 1
    today_str = datetime.date.today().strftime('%Y%m%d')
    payment_number = f"PAY-{today_str}-{max_id:04d}"
    while cur.execute("SELECT 1 FROM payments WHERE payment_number = ?", (payment_number,)).fetchone():
        max_id += 1
        payment_number = f"PAY-{today_str}-{max_id:04d}"

    user_id = user.get("id") or user.get("user_id", 1)

    cur.execute("""
        INSERT INTO payments (
            payment_number, invoice_id, customer_id, payment_date,
            payment_mode, reference_no, amount, notes, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payment_number, invoice_id, inv["customer_id"], payment_date,
        payment_mode, reference_no, amount, notes, user_id
    ))
    pay_id = cur.lastrowid

    cur.execute("""
        UPDATE invoices
        SET amount_paid = ?, balance_due = ?, status = ?
        WHERE id = ?
    """, (new_paid, new_due, new_status, invoice_id))

    cur.execute("SELECT current_balance FROM parties WHERE id = ?", (inv["customer_id"],))
    cust = cur.fetchone()
    new_cust_balance = round(cust["current_balance"] - amount, 2)
    cur.execute("UPDATE parties SET current_balance = ? WHERE id = ?", (new_cust_balance, inv["customer_id"]))

    return {
        "payment_id": pay_id,
        "payment_number": payment_number,
        "invoice_id": invoice_id,
        "invoice_number": inv["invoice_number"],
        "amount": amount,
        "amount_paid": amount,
        "total_amount_paid": new_paid,
        "balance_due": new_due,
        "remaining_balance_due": new_due,
        "status": new_status,
        "invoice_status": new_status,
        "customer_new_balance": new_cust_balance
    }

def get_customer_outstanding_ledger(conn, customer_id: int = None):
    cur = conn.cursor()
    query = """
        SELECT i.*, p.name as customer_name, p.gstin, p.credit_limit
        FROM invoices i
        JOIN parties p ON i.customer_id = p.id
        WHERE i.balance_due > 0
    """
    params = ()
    if customer_id:
        query += " AND i.customer_id = ?"
        params = (customer_id,)

    query += " ORDER BY i.invoice_date ASC"
    cur.execute(query, params)
    invoices = cur.fetchall()

    today = datetime.date.today()
    aging = {
        "0_to_30_days": 0.0,
        "31_to_60_days": 0.0,
        "61_to_90_days": 0.0,
        "over_90_days": 0.0,
        "total_outstanding": 0.0
    }

    report_lines = []
    for inv in invoices:
        inv_dt = datetime.date.fromisoformat(inv["invoice_date"])
        age_days = (today - inv_dt).days
        bal = inv["balance_due"]

        aging["total_outstanding"] += bal
        if age_days <= 30:
            aging["0_to_30_days"] += bal
        elif age_days <= 60:
            aging["31_to_60_days"] += bal
        elif age_days <= 90:
            aging["61_to_90_days"] += bal
        else:
            aging["over_90_days"] += bal

        report_lines.append({
            "invoice_id": inv["id"],
            "invoice_number": inv["invoice_number"],
            "customer_name": inv["customer_name"],
            "invoice_date": inv["invoice_date"],
            "grand_total": inv["grand_total"],
            "amount_paid": inv["amount_paid"],
            "balance_due": bal,
            "age_days": age_days,
            "status": inv["status"]
        })

    for k in aging:
        aging[k] = round(aging[k], 2)

    return {
        "invoices": report_lines,
        "aging_summary": aging
    }
