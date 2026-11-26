import json
from starlette.responses import JSONResponse, FileResponse, Response
from starlette.requests import Request
from app.database import get_db, execute_one, execute_query
from app.security import (
    verify_password, create_session_token, verify_session_token,
    has_permission, ROLE_PERMISSIONS
)
from app.services.sales_service import create_sales_order, approve_sales_order, generate_invoice_for_so
from app.services.purchase_service import create_purchase_order, create_goods_receipt_note
from app.services.production_service import create_production_order, complete_production_run
from app.services.payment_service import record_customer_payment, get_customer_outstanding_ledger
from app.services.traceability_service import trace_finished_good_upstream, trace_raw_material_downstream
from app.services.report_service import (
    get_monthly_stock_ledger_summary, get_gstr1_sales_report,
    get_production_variance_report, export_to_csv, export_to_excel_xml
)
from app.engine.shortage import check_stock_shortage
from app.engine.ledger import get_item_stock

def get_current_user(request: Request):
    token = request.cookies.get("batchwise_session")
    if not token:
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token = auth.split(" ")[1]
    if not token:
        return None
    session_data = verify_session_token(token)
    if not session_data:
        return None
    if "user_id" in session_data and "id" not in session_data:
        session_data["id"] = session_data["user_id"]
    elif "id" in session_data and "user_id" not in session_data:
        session_data["user_id"] = session_data["id"]

    # Ensure full_name is populated defensively
    if not session_data.get("full_name"):
        user_row = execute_one("SELECT full_name FROM users WHERE id = ?", (session_data["id"],))
        if user_row and user_row.get("full_name"):
            session_data["full_name"] = user_row["full_name"]
        else:
            session_data["full_name"] = session_data.get("username", "User").replace("_", " ").title()

    return session_data

async def api_login(request: Request):
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = execute_one("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
    if not user or not verify_password(password, user["password_hash"]):
        return JSONResponse({"error": "Invalid username or password"}, status_code=401)

    token = create_session_token(user["id"], user["username"], user["role"])
    dest_url = {
        "admin": "/",
        "salesman": "/salesman/dashboard",
        "production_manager": "/production/dashboard",
        "accountant": "/accountant/dashboard",
        "auditor": "/auditor/dashboard",
        "purchase_manager": "/purchase"
    }.get(user["role"], "/")

    response = JSONResponse({
        "success": True,
        "token": token,
        "redirect_url": dest_url,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "email": user["email"]
        }
    })
    response.set_cookie("batchwise_session", token, httponly=True, max_age=86400, samesite="lax")
    return response

async def api_logout(request: Request):
    response = JSONResponse({"success": True})
    response.delete_cookie("batchwise_session")
    return response

async def api_me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"authenticated": False}, status_code=401)
    return JSONResponse({"authenticated": True, "user": user})

async def api_sales_create(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    data = await request.json()
    with get_db() as conn:
        try:
            res = create_sales_order(
                conn, user=user, customer_id=data["customer_id"],
                items=data["items"], notes=data.get("notes")
            )
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_sales_approve(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    so_id = int(request.path_params["id"])
    with get_db() as conn:
        try:
            res = approve_sales_order(conn, user=user, so_id=so_id)
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_sales_invoice(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    so_id = int(request.path_params["id"])
    with get_db() as conn:
        try:
            res = generate_invoice_for_so(conn, user=user, so_id=so_id)
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_purchase_create(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    data = await request.json()
    with get_db() as conn:
        try:
            res = create_purchase_order(conn, user=user, supplier_id=data["supplier_id"], items=data["items"])
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_purchase_grn(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    data = await request.json()
    with get_db() as conn:
        try:
            res = create_goods_receipt_note(
                conn, user=user, po_id=data["po_id"],
                supplier_invoice_no=data.get("supplier_invoice_no", "SUPP-INV"),
                vehicle_no=data.get("vehicle_no", "KA-01-9999"),
                received_items=data["received_items"]
            )
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_production_create(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    data = await request.json()
    with get_db() as conn:
        try:
            res = create_production_order(
                conn, user=user, bom_id=data["bom_id"], target_qty=data["target_qty"],
                batch_number=data["batch_number"], start_date=data.get("start_date")
            )
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_production_complete(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    wo_id = int(request.path_params["id"])
    data = await request.json()
    with get_db() as conn:
        try:
            res = complete_production_run(
                conn, user=user, wo_id=wo_id,
                actual_qty_produced=data["actual_qty_produced"],
                consumptions=data["consumptions"],
                labor_cost=data.get("labor_cost", 0.0),
                overhead_cost=data.get("overhead_cost", 0.0)
            )
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_shortage_check(request: Request):
    data = await request.json()
    with get_db() as conn:
        res = check_stock_shortage(conn, data.get("items", []))
        return JSONResponse({"success": True, "data": res})

async def api_payment_record(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    data = await request.json()
    with get_db() as conn:
        try:
            res = record_customer_payment(
                conn, user=user, invoice_id=data["invoice_id"], amount=data["amount"],
                payment_mode=data.get("payment_mode", "bank_transfer"),
                reference_no=data.get("reference_no")
            )
            return JSONResponse({"success": True, "data": res})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

async def api_trace_upstream(request: Request):
    batch = request.path_params["batch"]
    with get_db() as conn:
        res = trace_finished_good_upstream(conn, batch)
        return JSONResponse({"success": True, "data": res})

async def api_trace_downstream(request: Request):
    batch = request.path_params["batch"]
    with get_db() as conn:
        res = trace_raw_material_downstream(conn, batch)
        return JSONResponse({"success": True, "data": res})

async def api_invoice_pdf(request: Request):
    inv_id = int(request.path_params["id"])
    inv = execute_one("SELECT pdf_path, invoice_number FROM invoices WHERE id = ?", (inv_id,))
    if not inv or not inv["pdf_path"]:
        return JSONResponse({"error": "Invoice PDF not found"}, status_code=404)
    return FileResponse(inv["pdf_path"], media_type="application/pdf", filename=f"{inv['invoice_number']}.pdf")

async def api_export_stock_csv(request: Request):
    with get_db() as conn:
        rep = get_monthly_stock_ledger_summary(conn)
        csv_str = export_to_csv(
            rep["items"],
            ["SKU", "Item Name", "Category", "UOM", "Opening Qty", "Inward Qty", "Outward Qty", "Closing Qty", "Standard Cost", "Valuation"],
            ["sku", "name", "category", "uom", "opening_qty", "inward_qty", "outward_qty", "closing_qty", "standard_cost", "total_valuation"]
        )
        return Response(csv_str, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=Stock_Ledger.csv"})

async def api_export_stock_excel(request: Request):
    with get_db() as conn:
        rep = get_monthly_stock_ledger_summary(conn)
        xml_str = export_to_excel_xml(
            "Stock_Ledger_Audit",
            ["SKU", "Item Name", "Category", "UOM", "Opening Qty", "Inward Qty", "Outward Qty", "Closing Qty", "Standard Cost", "Valuation"],
            rep["items"],
            ["sku", "name", "category", "uom", "opening_qty", "inward_qty", "outward_qty", "closing_qty", "standard_cost", "total_valuation"]
        )
        return Response(xml_str, media_type="application/vnd.ms-excel", headers={"Content-Disposition": "attachment; filename=Stock_Ledger.xls"})

async def api_simulate_benchmark(request: Request):
    from app.services.benchmark_service import execute_benchmark_journey
    try:
        res = execute_benchmark_journey()
        return JSONResponse({"success": True, "data": res})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def api_reset_seed(request: Request):
    from seed import seed_database
    from app.config import DB_PATH
    try:
        seed_database(DB_PATH, clean=True)
        return JSONResponse({"success": True, "message": "Database reset to clean state with benchmark scenario preloaded"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
