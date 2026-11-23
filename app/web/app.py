from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from pathlib import Path

from app.web.routes_ui import (
    ui_dashboard, ui_login, ui_quick_login, ui_sales, ui_purchase,
    ui_production, ui_inventory, ui_invoices, ui_traceability, ui_reports
)
from app.web.routes_api import (
    api_login, api_logout, api_me, api_sales_create, api_sales_approve,
    api_sales_invoice, api_purchase_create, api_purchase_grn,
    api_production_create, api_production_complete, api_shortage_check,
    api_payment_record, api_trace_upstream, api_trace_downstream,
    api_invoice_pdf, api_export_stock_csv, api_export_stock_excel
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
try:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

routes = [
    # UI Routes
    Route("/", endpoint=ui_dashboard, methods=["GET"]),
    Route("/login", endpoint=ui_login, methods=["GET"]),
    Route("/switch-role/{role}", endpoint=ui_quick_login, methods=["GET"]),
    Route("/sales", endpoint=ui_sales, methods=["GET"]),
    Route("/purchase", endpoint=ui_purchase, methods=["GET"]),
    Route("/production", endpoint=ui_production, methods=["GET"]),
    Route("/inventory", endpoint=ui_inventory, methods=["GET"]),
    Route("/invoices", endpoint=ui_invoices, methods=["GET"]),
    Route("/traceability", endpoint=ui_traceability, methods=["GET"]),
    Route("/reports", endpoint=ui_reports, methods=["GET"]),

    # API Auth Routes
    Route("/api/auth/login", endpoint=api_login, methods=["POST"]),
    Route("/api/auth/logout", endpoint=api_logout, methods=["POST"]),
    Route("/api/auth/me", endpoint=api_me, methods=["GET"]),

    # API Business Workflow Routes
    Route("/api/sales/orders", endpoint=api_sales_create, methods=["POST"]),
    Route("/api/sales/orders/{id:int}/approve", endpoint=api_sales_approve, methods=["POST"]),
    Route("/api/sales/orders/{id:int}/invoice", endpoint=api_sales_invoice, methods=["POST"]),
    Route("/api/purchase/orders", endpoint=api_purchase_create, methods=["POST"]),
    Route("/api/purchase/grn", endpoint=api_purchase_grn, methods=["POST"]),
    Route("/api/production/orders", endpoint=api_production_create, methods=["POST"]),
    Route("/api/production/orders/{id:int}/complete", endpoint=api_production_complete, methods=["POST"]),
    Route("/api/inventory/check-shortage", endpoint=api_shortage_check, methods=["POST"]),
    Route("/api/payments", endpoint=api_payment_record, methods=["POST"]),

    # API Traceability & Documents
    Route("/api/traceability/upstream/{batch}", endpoint=api_trace_upstream, methods=["GET"]),
    Route("/api/traceability/downstream/{batch}", endpoint=api_trace_downstream, methods=["GET"]),
    Route("/api/invoices/{id:int}/pdf", endpoint=api_invoice_pdf, methods=["GET"]),
    Route("/api/reports/export/csv", endpoint=api_export_stock_csv, methods=["GET"]),
    Route("/api/reports/export/excel", endpoint=api_export_stock_excel, methods=["GET"]),

    # Static Assets
    Mount("/static", app=StaticFiles(directory=str(STATIC_DIR)), name="static"),
]

middleware = [
    Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
]

app = Starlette(debug=True, routes=routes, middleware=middleware)
