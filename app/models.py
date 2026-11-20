import sqlite3
from app.database import get_db

SCHEMA_SQL = """
-- 1. Users & Authentication
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'salesman', 'purchase_manager', 'production_manager', 'auditor')),
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Items & Master Products
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('raw_material', 'packing_material', 'sub_assembly', 'finished_good')),
    uom TEXT NOT NULL,
    hsn_code TEXT NOT NULL,
    min_stock_alert REAL NOT NULL DEFAULT 0.0 CHECK(min_stock_alert >= 0),
    standard_cost REAL NOT NULL DEFAULT 0.0 CHECK(standard_cost >= 0),
    selling_price REAL NOT NULL DEFAULT 0.0 CHECK(selling_price >= 0),
    gst_rate REAL NOT NULL DEFAULT 0.0 CHECK(gst_rate >= 0),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Bill of Materials (BOM)
CREATE TABLE IF NOT EXISTS boms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    finished_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    base_qty REAL NOT NULL DEFAULT 1.0 CHECK(base_qty > 0),
    uom TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bom_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_id INTEGER NOT NULL REFERENCES boms(id) ON DELETE CASCADE,
    component_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    quantity REAL NOT NULL CHECK(quantity > 0),
    scrap_percentage REAL NOT NULL DEFAULT 0.0 CHECK(scrap_percentage >= 0),
    notes TEXT,
    UNIQUE(bom_id, component_item_id)
);

-- 4. Parties (Customers & Suppliers)
CREATE TABLE IF NOT EXISTS parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_type TEXT NOT NULL CHECK(party_type IN ('customer', 'supplier')),
    name TEXT NOT NULL,
    gstin TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    state TEXT NOT NULL DEFAULT 'Karnataka',
    state_code TEXT NOT NULL DEFAULT '29',
    credit_limit REAL NOT NULL DEFAULT 0.0 CHECK(credit_limit >= 0),
    current_balance REAL NOT NULL DEFAULT 0.0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Stock Batches & Lots
CREATE TABLE IF NOT EXISTS stock_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_number TEXT UNIQUE NOT NULL,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    initial_qty REAL NOT NULL CHECK(initial_qty >= 0),
    current_qty REAL NOT NULL CHECK(current_qty >= 0),
    unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
    mfg_date DATE NOT NULL,
    expiry_date DATE,
    source_type TEXT NOT NULL CHECK(source_type IN ('grn', 'production', 'opening_stock', 'adjustment')),
    source_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'consumed', 'quarantine', 'expired')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Double-Entry Stock Transactions Ledger (Immutable Audit Trail)
CREATE TABLE IF NOT EXISTS stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_number TEXT UNIQUE NOT NULL,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    batch_id INTEGER REFERENCES stock_batches(id) ON DELETE RESTRICT,
    batch_number TEXT NOT NULL,
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('INWARD', 'OUTWARD', 'SCRAP', 'PRODUCTION_IN', 'PRODUCTION_OUT', 'ADJUSTMENT')),
    qty REAL NOT NULL,
    unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
    total_value REAL NOT NULL,
    reference_type TEXT NOT NULL CHECK(reference_type IN ('PO', 'GRN', 'WO', 'INV', 'ADJ', 'SEED')),
    reference_id INTEGER NOT NULL,
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. Purchase Orders
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT UNIQUE NOT NULL,
    supplier_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'approved' CHECK(status IN ('draft', 'approved', 'received', 'cancelled')),
    order_date DATE NOT NULL,
    total_taxable REAL NOT NULL DEFAULT 0.0 CHECK(total_taxable >= 0),
    total_tax REAL NOT NULL DEFAULT 0.0 CHECK(total_tax >= 0),
    grand_total REAL NOT NULL DEFAULT 0.0 CHECK(grand_total >= 0),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS po_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    gst_rate REAL NOT NULL DEFAULT 0.0 CHECK(gst_rate >= 0),
    taxable_amount REAL NOT NULL CHECK(taxable_amount >= 0),
    cgst_amount REAL NOT NULL CHECK(cgst_amount >= 0),
    sgst_amount REAL NOT NULL CHECK(sgst_amount >= 0),
    total_amount REAL NOT NULL CHECK(total_amount >= 0)
);

-- 8. Goods Receipt Notes (GRN)
CREATE TABLE IF NOT EXISTS goods_receipt_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grn_number TEXT UNIQUE NOT NULL,
    po_id INTEGER REFERENCES purchase_orders(id) ON DELETE RESTRICT,
    supplier_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE RESTRICT,
    receipt_date DATE NOT NULL,
    vehicle_no TEXT,
    supplier_invoice_no TEXT,
    supplier_invoice_date DATE,
    total_amount REAL NOT NULL DEFAULT 0.0 CHECK(total_amount >= 0),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS grn_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grn_id INTEGER NOT NULL REFERENCES goods_receipt_notes(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    received_qty REAL NOT NULL CHECK(received_qty >= 0),
    accepted_qty REAL NOT NULL CHECK(accepted_qty >= 0),
    rejected_qty REAL NOT NULL DEFAULT 0.0 CHECK(rejected_qty >= 0),
    unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
    batch_number TEXT NOT NULL,
    mfg_date DATE NOT NULL,
    expiry_date DATE
);

-- 9. Production Work Orders
CREATE TABLE IF NOT EXISTS production_work_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_number TEXT UNIQUE NOT NULL,
    bom_id INTEGER NOT NULL REFERENCES boms(id) ON DELETE RESTRICT,
    finished_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    batch_number TEXT UNIQUE NOT NULL,
    target_qty REAL NOT NULL CHECK(target_qty > 0),
    actual_qty REAL NOT NULL DEFAULT 0.0 CHECK(actual_qty >= 0),
    scrap_qty REAL NOT NULL DEFAULT 0.0 CHECK(scrap_qty >= 0),
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned', 'in_progress', 'completed', 'cancelled')),
    start_date DATE NOT NULL,
    completion_date DATE,
    standard_material_cost REAL NOT NULL DEFAULT 0.0,
    actual_material_cost REAL NOT NULL DEFAULT 0.0,
    labor_cost REAL NOT NULL DEFAULT 0.0,
    overhead_cost REAL NOT NULL DEFAULT 0.0,
    total_actual_cost REAL NOT NULL DEFAULT 0.0,
    actual_unit_cost REAL NOT NULL DEFAULT 0.0,
    material_quantity_variance REAL NOT NULL DEFAULT 0.0,
    material_cost_variance REAL NOT NULL DEFAULT 0.0,
    yield_variance_percentage REAL NOT NULL DEFAULT 0.0,
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wo_material_consumptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_id INTEGER NOT NULL REFERENCES production_work_orders(id) ON DELETE CASCADE,
    component_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    batch_id INTEGER REFERENCES stock_batches(id) ON DELETE RESTRICT,
    batch_number TEXT NOT NULL,
    standard_qty REAL NOT NULL CHECK(standard_qty >= 0),
    actual_qty REAL NOT NULL CHECK(actual_qty >= 0),
    variance_qty REAL NOT NULL DEFAULT 0.0,
    unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
    variance_cost REAL NOT NULL DEFAULT 0.0,
    scrap_qty REAL NOT NULL DEFAULT 0.0 CHECK(scrap_qty >= 0),
    notes TEXT
);

-- 10. Sales Orders
CREATE TABLE IF NOT EXISTS sales_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    so_number TEXT UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE RESTRICT,
    salesman_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'pending_approval' CHECK(status IN ('draft', 'pending_approval', 'approved', 'invoiced', 'rejected')),
    order_date DATE NOT NULL,
    total_taxable REAL NOT NULL DEFAULT 0.0 CHECK(total_taxable >= 0),
    total_cgst REAL NOT NULL DEFAULT 0.0 CHECK(total_cgst >= 0),
    total_sgst REAL NOT NULL DEFAULT 0.0 CHECK(total_sgst >= 0),
    total_tax REAL NOT NULL DEFAULT 0.0 CHECK(total_tax >= 0),
    grand_total REAL NOT NULL DEFAULT 0.0 CHECK(grand_total >= 0),
    rejection_reason TEXT,
    notes TEXT,
    approved_by INTEGER REFERENCES users(id),
    approved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS so_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    so_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    gst_rate REAL NOT NULL DEFAULT 0.0 CHECK(gst_rate >= 0),
    taxable_amount REAL NOT NULL CHECK(taxable_amount >= 0),
    cgst_amount REAL NOT NULL CHECK(cgst_amount >= 0),
    sgst_amount REAL NOT NULL CHECK(sgst_amount >= 0),
    total_amount REAL NOT NULL CHECK(total_amount >= 0)
);

-- 11. Invoices (GST Compliant)
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    so_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE RESTRICT,
    customer_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE RESTRICT,
    invoice_date DATE NOT NULL,
    due_date DATE NOT NULL,
    total_taxable REAL NOT NULL CHECK(total_taxable >= 0),
    total_cgst REAL NOT NULL DEFAULT 0.0 CHECK(total_cgst >= 0),
    total_sgst REAL NOT NULL DEFAULT 0.0 CHECK(total_sgst >= 0),
    total_igst REAL NOT NULL DEFAULT 0.0 CHECK(total_igst >= 0),
    grand_total REAL NOT NULL CHECK(grand_total >= 0),
    amount_paid REAL NOT NULL DEFAULT 0.0 CHECK(amount_paid >= 0),
    balance_due REAL NOT NULL CHECK(balance_due >= 0),
    status TEXT NOT NULL DEFAULT 'unpaid' CHECK(status IN ('unpaid', 'partially_paid', 'paid', 'cancelled')),
    pdf_path TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    batch_id INTEGER REFERENCES stock_batches(id) ON DELETE RESTRICT,
    batch_number TEXT NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    hsn_code TEXT NOT NULL,
    taxable_amount REAL NOT NULL CHECK(taxable_amount >= 0),
    gst_rate REAL NOT NULL CHECK(gst_rate >= 0),
    cgst_amount REAL NOT NULL DEFAULT 0.0 CHECK(cgst_amount >= 0),
    sgst_amount REAL NOT NULL DEFAULT 0.0 CHECK(sgst_amount >= 0),
    igst_amount REAL NOT NULL DEFAULT 0.0 CHECK(igst_amount >= 0),
    total_amount REAL NOT NULL CHECK(total_amount >= 0)
);

-- 12. Payments & Customer Outstanding Ledger
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_number TEXT UNIQUE NOT NULL,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
    customer_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE RESTRICT,
    payment_date DATE NOT NULL,
    payment_mode TEXT NOT NULL CHECK(payment_mode IN ('bank_transfer', 'upi', 'cash', 'cheque', 'neft_rtgs')),
    reference_no TEXT,
    amount REAL NOT NULL CHECK(amount > 0),
    notes TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 13. Audit Log for Full Traceability
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_batches_item ON stock_batches(item_id, status);
CREATE INDEX IF NOT EXISTS idx_stock_batches_number ON stock_batches(batch_number);
CREATE INDEX IF NOT EXISTS idx_stock_trans_item_batch ON stock_transactions(item_id, batch_id);
CREATE INDEX IF NOT EXISTS idx_stock_trans_created ON stock_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_so_customer ON sales_orders(customer_id, status);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id, status);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
"""

def init_db(db_path=None):
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA_SQL)

def reset_db(db_path=None):
    with get_db(db_path) as conn:
        tables = [
            "audit_logs", "payments", "invoice_items", "invoices",
            "so_items", "sales_orders", "wo_material_consumptions",
            "production_work_orders", "grn_items", "goods_receipt_notes",
            "po_items", "purchase_orders", "stock_transactions",
            "stock_batches", "bom_items", "boms", "parties",
            "items", "users"
        ]
        for t in tables:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.executescript(SCHEMA_SQL)
