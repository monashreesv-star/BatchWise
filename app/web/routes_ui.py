from starlette.templating import Jinja2Templates
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.requests import Request
from pathlib import Path
from app.database import get_db, execute_query, execute_one
from app.web.routes_api import get_current_user
from app.services.report_service import get_monthly_stock_ledger_summary, get_gstr1_sales_report, get_production_variance_report
from app.services.payment_service import get_customer_outstanding_ledger

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def render_template(request: Request, name: str, context: dict = None, status_code: int = 200):
    ctx = context.copy() if context else {}
    ctx["request"] = request
    return templates.TemplateResponse(request=request, name=name, context=ctx, status_code=status_code)

async def ui_dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_db() as conn:
        sales_count = execute_one("SELECT COUNT(*) as c, COALESCE(SUM(grand_total), 0) as s FROM sales_orders")
        invoice_stats = execute_one("SELECT COUNT(*) as c, COALESCE(SUM(grand_total), 0) as total, COALESCE(SUM(balance_due), 0) as due FROM invoices")
        batch_stats = execute_one("SELECT COUNT(*) as c, COALESCE(SUM(current_qty * unit_cost), 0) as val FROM stock_batches WHERE status = 'active'")
        wo_stats = execute_one("SELECT COUNT(*) as c, COALESCE(SUM(actual_qty), 0) as output FROM production_work_orders WHERE status = 'completed'")

        # Stock valuation by category
        cat_val_rows = execute_query("""
            SELECT i.category, ROUND(SUM(sb.current_qty * sb.unit_cost), 2) as val
            FROM stock_batches sb
            JOIN items i ON sb.item_id = i.id
            WHERE sb.current_qty > 0 AND sb.status = 'active'
            GROUP BY i.category
        """)
        cat_val = {r["category"]: r["val"] for r in cat_val_rows}

        # Latest production work order with variance
        latest_wo = execute_one("""
            SELECT wo.*, i.name as finished_good_name
            FROM production_work_orders wo
            JOIN items i ON wo.finished_item_id = i.id
            ORDER BY wo.id DESC LIMIT 1
        """)

        recent_orders = execute_query("""
            SELECT so.*, p.name as customer_name
            FROM sales_orders so
            JOIN parties p ON so.customer_id = p.id
            ORDER BY so.id DESC LIMIT 5
        """)

        recent_batches = execute_query("""
            SELECT sb.*, i.name as item_name, i.sku
            FROM stock_batches sb
            JOIN items i ON sb.item_id = i.id
            WHERE sb.status = 'active'
            ORDER BY sb.id DESC LIMIT 5
        """)

        # Determine benchmark journey progress flags
        so_done = execute_one("SELECT COUNT(*) as c FROM sales_orders")["c"] > 0
        grn_done = execute_one("SELECT COUNT(*) as c FROM goods_receipt_notes")["c"] > 0
        wo_done = execute_one("SELECT COUNT(*) as c FROM production_work_orders WHERE status = 'completed'")["c"] > 0
        inv_done = execute_one("SELECT COUNT(*) as c FROM invoices")["c"] > 0
        pay_done = execute_one("SELECT COUNT(*) as c FROM payments")["c"] > 0

        items = execute_query("SELECT * FROM items WHERE category = 'finished_good'")
        customers = execute_query("SELECT * FROM parties WHERE party_type = 'customer'")
        suppliers = execute_query("SELECT * FROM parties WHERE party_type = 'supplier'")
        raw_materials = execute_query("SELECT * FROM items WHERE category = 'raw_material'")
        boms = execute_query("SELECT b.*, i.name as finished_good_name FROM boms b JOIN items i ON b.finished_item_id = i.id")

    return render_template(request, "dashboard.html", {
        "user": user,
        "sales_count": sales_count["c"],
        "sales_val": sales_count["s"],
        "revenue": invoice_stats["total"],
        "outstanding": invoice_stats["due"],
        "collected": round(invoice_stats["total"] - invoice_stats["due"], 2),
        "active_batches": batch_stats["c"],
        "stock_valuation": batch_stats["val"],
        "work_orders_count": wo_stats["c"],
        "total_output": wo_stats["output"],
        "latest_wo": latest_wo,
        "cat_val": cat_val,
        "journey": {
            "so": so_done, "grn": grn_done, "wo": wo_done, "inv": inv_done, "pay": pay_done
        },
        "recent_orders": recent_orders,
        "recent_batches": recent_batches,
        "items": items,
        "customers": customers,
        "suppliers": suppliers,
        "raw_materials": raw_materials,
        "boms": boms
    })

async def ui_login(request: Request):
    return render_template(request, "login.html")

async def ui_quick_login(request: Request):
    role = request.path_params["role"]
    user_map = {
        "admin": "admin",
        "salesman": "sales_ravi",
        "purchase": "purchase_priya",
        "production": "prod_kumar",
        "auditor": "audit_anita"
    }
    username = user_map.get(role, "admin")
    user = execute_one("SELECT * FROM users WHERE username = ?", (username,))
    if not user:
        return RedirectResponse(url="/login")

    from app.security import create_session_token
    token = create_session_token(user["id"], user["username"], user["role"])
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("batchwise_session", token, httponly=True, max_age=86400, samesite="lax")
    return response

async def ui_sales(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    orders = execute_query("""
        SELECT so.*, p.name as customer_name, p.gstin as customer_gstin, u.full_name as salesman_name,
               (SELECT COUNT(*) FROM so_items WHERE so_id = so.id) as item_count
        FROM sales_orders so
        JOIN parties p ON so.customer_id = p.id
        JOIN users u ON so.salesman_id = u.id
        ORDER BY so.id DESC
    """)
    customers = execute_query("SELECT * FROM parties WHERE party_type = 'customer'")
    items = execute_query("SELECT * FROM items WHERE category = 'finished_good'")

    total_booked = execute_one("SELECT COUNT(*) as c, COALESCE(SUM(grand_total), 0) as s FROM sales_orders")
    pending = execute_one("SELECT COUNT(*) as c, COALESCE(SUM(grand_total), 0) as s FROM sales_orders WHERE status = 'pending_approval'")
    invoiced = execute_one("SELECT COUNT(*) as c, COALESCE(SUM(grand_total), 0) as s FROM invoices")

    return render_template(request, "sales.html", {
        "user": user, "orders": orders,
        "customers": customers, "items": items,
        "total_booked_count": total_booked["c"],
        "total_booked_val": total_booked["s"],
        "pending_count": pending["c"],
        "pending_val": pending["s"],
        "invoiced_count": invoiced["c"],
        "invoiced_val": invoiced["s"],
    })

async def ui_purchase(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    pos = execute_query("""
        SELECT po.*, p.name as supplier_name, u.full_name as creator_name
        FROM purchase_orders po
        JOIN parties p ON po.supplier_id = p.id
        JOIN users u ON po.created_by = u.id
        ORDER BY po.id DESC
    """)
    grns = execute_query("""
        SELECT grn.*, p.name as supplier_name, po.po_number
        FROM goods_receipt_notes grn
        JOIN parties p ON grn.supplier_id = p.id
        LEFT JOIN purchase_orders po ON grn.po_id = po.id
        ORDER BY grn.id DESC
    """)
    suppliers = execute_query("SELECT * FROM parties WHERE party_type = 'supplier'")
    raw_materials = execute_query("SELECT * FROM items WHERE category = 'raw_material'")

    return render_template(request, "purchase.html", {
        "user": user, "purchase_orders": pos,
        "grns": grns, "suppliers": suppliers, "raw_materials": raw_materials
    })

async def ui_production(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    work_orders = execute_query("""
        SELECT wo.*, i.name as finished_good_name, b.bom_code
        FROM production_work_orders wo
        JOIN items i ON wo.finished_item_id = i.id
        JOIN boms b ON wo.bom_id = b.id
        ORDER BY wo.id DESC
    """)
    boms = execute_query("SELECT b.*, i.name as finished_good_name FROM boms b JOIN items i ON b.finished_item_id = i.id")
    raw_batches = execute_query("""
        SELECT sb.*, i.name as item_name, i.sku
        FROM stock_batches sb
        JOIN items i ON sb.item_id = i.id
        WHERE sb.current_qty > 0 AND sb.status = 'active'
        ORDER BY i.category, sb.mfg_date ASC
    """)

    return render_template(request, "production.html", {
        "user": user, "work_orders": work_orders,
        "boms": boms, "raw_batches": raw_batches
    })

async def ui_inventory(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    batches = execute_query("""
        SELECT sb.*, i.name as item_name, i.sku, i.uom, i.category
        FROM stock_batches sb
        JOIN items i ON sb.item_id = i.id
        ORDER BY sb.id DESC
    """)
    ledger_tx = execute_query("""
        SELECT st.*, i.name as item_name, i.sku
        FROM stock_transactions st
        JOIN items i ON st.item_id = i.id
        ORDER BY st.id DESC LIMIT 30
    """)
    finished_goods = execute_query("SELECT * FROM items WHERE category = 'finished_good'")

    return render_template(request, "inventory.html", {
        "user": user, "batches": batches,
        "ledger_tx": ledger_tx, "finished_goods": finished_goods
    })

async def ui_invoices(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    invoices = execute_query("""
        SELECT inv.*, p.name as customer_name, p.gstin as customer_gstin
        FROM invoices inv
        JOIN parties p ON inv.customer_id = p.id
        ORDER BY inv.id DESC
    """)
    return render_template(request, "invoices.html", {
        "user": user, "invoices": invoices
    })

async def ui_traceability(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    all_batches = execute_query("""
        SELECT sb.batch_number, sb.source_type, i.sku, i.name, i.category
        FROM stock_batches sb
        JOIN items i ON sb.item_id = i.id
        ORDER BY sb.id DESC
    """)
    return render_template(request, "traceability.html", {
        "user": user, "batches": all_batches
    })

async def ui_reports(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login")

    with get_db() as conn:
        stock_summary = get_monthly_stock_ledger_summary(conn)
        gstr1 = get_gstr1_sales_report(conn)
        variance = get_production_variance_report(conn)
        outstanding = get_customer_outstanding_ledger(conn)

    return render_template(request, "reports.html", {
        "user": user, "stock_summary": stock_summary,
        "gstr1": gstr1, "variance": variance, "outstanding": outstanding
    })
