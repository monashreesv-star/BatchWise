import datetime
from app.database import get_db

class LedgerError(Exception):
    pass

class InsufficientStockError(LedgerError):
    pass

def generate_tx_number(conn):
    cur = conn.cursor()
    cur.execute("SELECT MAX(id) as max_id FROM stock_transactions")
    max_id = (cur.fetchone()["max_id"] or 0) + 1
    today_str = datetime.date.today().strftime('%Y%m%d')
    tx_num = f"STX-{today_str}-{max_id:05d}"
    while cur.execute("SELECT 1 FROM stock_transactions WHERE transaction_number = ?", (tx_num,)).fetchone():
        max_id += 1
        tx_num = f"STX-{today_str}-{max_id:05d}"
    return tx_num

def record_inward(conn, item_id: int, batch_number: str, qty: float, unit_cost: float,
                  source_type: str, source_id: int, mfg_date: str, expiry_date: str = None,
                  created_by: int = None, notes: str = None, reference_type: str = "GRN"):
    if qty <= 0:
        raise LedgerError("Inward quantity must be strictly greater than zero.")
    if unit_cost < 0:
        raise LedgerError("Unit cost cannot be negative.")

    cur = conn.cursor()
    cur.execute("SELECT * FROM stock_batches WHERE batch_number = ?", (batch_number,))
    existing_batch = cur.fetchone()

    if existing_batch:
        batch_id = existing_batch["id"]
        new_qty = round(existing_batch["current_qty"] + qty, 4)
        cur.execute("""
            UPDATE stock_batches
            SET current_qty = ?, status = 'active'
            WHERE id = ?
        """, (new_qty, batch_id))
    else:
        cur.execute("""
            INSERT INTO stock_batches (batch_number, item_id, initial_qty, current_qty, unit_cost,
                                       mfg_date, expiry_date, source_type, source_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """, (batch_number, item_id, qty, qty, unit_cost, mfg_date, expiry_date, source_type, source_id))
        batch_id = cur.lastrowid

    tx_num = generate_tx_number(conn)
    total_val = round(qty * unit_cost, 2)
    cur.execute("""
        INSERT INTO stock_transactions (transaction_number, item_id, batch_id, batch_number,
                                        transaction_type, qty, unit_cost, total_value,
                                        reference_type, reference_id, notes, created_by)
        VALUES (?, ?, ?, ?, 'INWARD', ?, ?, ?, ?, ?, ?, ?)
    """, (tx_num, item_id, batch_id, batch_number, qty, unit_cost, total_val, reference_type, source_id, notes, created_by))

    return batch_id

def record_outward(conn, item_id: int, batch_id: int, qty: float,
                   reference_type: str, reference_id: int, created_by: int = None,
                   notes: str = None, transaction_type: str = "OUTWARD"):
    if qty <= 0:
        raise LedgerError("Outward quantity must be strictly greater than zero.")

    cur = conn.cursor()
    cur.execute("SELECT * FROM stock_batches WHERE id = ?", (batch_id,))
    batch = cur.fetchone()

    if not batch:
        raise LedgerError(f"Batch with ID {batch_id} does not exist.")
    if batch["item_id"] != item_id:
        raise LedgerError(f"Batch {batch['batch_number']} does not belong to item ID {item_id}.")
    if batch["current_qty"] < qty:
        raise InsufficientStockError(
            f"Insufficient stock in batch {batch['batch_number']}. "
            f"Available: {batch['current_qty']}, Requested: {qty}"
        )

    new_qty = round(batch["current_qty"] - qty, 4)
    status = "consumed" if new_qty == 0 else "active"

    cur.execute("""
        UPDATE stock_batches
        SET current_qty = ?, status = ?
        WHERE id = ?
    """, (new_qty, status, batch_id))

    tx_num = generate_tx_number(conn)
    unit_cost = batch["unit_cost"]
    total_val = round(-qty * unit_cost, 2)

    cur.execute("""
        INSERT INTO stock_transactions (transaction_number, item_id, batch_id, batch_number,
                                        transaction_type, qty, unit_cost, total_value,
                                        reference_type, reference_id, notes, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (tx_num, item_id, batch_id, batch["batch_number"], transaction_type, -qty, unit_cost, total_val, reference_type, reference_id, notes, created_by))

    return tx_num

def get_item_stock(conn, item_id: int) -> float:
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(current_qty), 0.0) as total_stock
        FROM stock_batches
        WHERE item_id = ? AND status = 'active'
    """, (item_id,))
    row = cur.fetchone()
    return round(row["total_stock"], 4)

def allocate_stock_fifo(conn, item_id: int, required_qty: float):
    total_avail = get_item_stock(conn, item_id)
    if total_avail < required_qty:
        raise InsufficientStockError(
            f"Insufficient total inventory for item ID {item_id}. "
            f"Available: {total_avail}, Required: {required_qty}, Deficit: {round(required_qty - total_avail, 4)}"
        )

    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM stock_batches
        WHERE item_id = ? AND current_qty > 0 AND status = 'active'
        ORDER BY mfg_date ASC, id ASC
    """, (item_id,))
    batches = cur.fetchall()

    allocations = []
    remaining = required_qty

    for b in batches:
        if remaining <= 0:
            break
        take = min(b["current_qty"], remaining)
        allocations.append({
            "batch_id": b["id"],
            "batch_number": b["batch_number"],
            "allocated_qty": round(take, 4),
            "unit_cost": b["unit_cost"]
        })
        remaining = round(remaining - take, 4)

    return allocations

def verify_inventory_integrity(conn, item_id: int = None):
    cur = conn.cursor()
    query_batches = "SELECT item_id, SUM(current_qty) as batch_stock FROM stock_batches GROUP BY item_id"
    query_ledger = "SELECT item_id, SUM(qty) as ledger_stock FROM stock_transactions GROUP BY item_id"

    cur.execute(query_batches)
    batch_map = {row["item_id"]: round(row["batch_stock"], 4) for row in cur.fetchall()}

    cur.execute(query_ledger)
    ledger_map = {row["item_id"]: round(row["ledger_stock"], 4) for row in cur.fetchall()}

    items_to_check = [item_id] if item_id else set(list(batch_map.keys()) + list(ledger_map.keys()))
    discrepancies = []

    for i in items_to_check:
        b_qty = batch_map.get(i, 0.0)
        l_qty = ledger_map.get(i, 0.0)
        if abs(b_qty - l_qty) > 0.0001:
            discrepancies.append({
                "item_id": i,
                "batch_sum": b_qty,
                "ledger_sum": l_qty,
                "variance": round(b_qty - l_qty, 4)
            })

    return len(discrepancies) == 0, discrepancies
