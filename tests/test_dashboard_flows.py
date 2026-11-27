import unittest
import asyncio
import json
from starlette.requests import Request
from app.web.routes_api import (
    api_login, api_sales_create, api_sales_approve, api_sales_invoice,
    api_production_create, api_production_complete, api_payment_record
)
from seed import seed_database

def make_post_request(path: str, data: dict = None, token: str = None, path_params: dict = None):
    body_bytes = json.dumps(data or {}).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body_bytes)).encode("utf-8"))
    ]
    if token:
        headers.append((b"cookie", f"batchwise_session={token}".encode("utf-8")))

    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "path_params": path_params or {}
    }
    return Request(scope, receive)

class TestDashboardFlows(unittest.TestCase):
    def setUp(self):
        seed_database(clean=True)

    def test_salesman_order_flow(self):
        req_login = make_post_request("/api/auth/login", {"username": "sales_ravi", "password": "sales123"})
        resp_login = asyncio.run(api_login(req_login))
        self.assertEqual(resp_login.status_code, 200)
        token_salesman = json.loads(resp_login.body.decode("utf-8"))["token"]

        req_so = make_post_request("/api/sales/orders", {
            "customer_id": 3,
            "items": [{"item_id": 7, "quantity": 150, "unit_price": 50.0}],
            "notes": "NIT Trichy Benchmark Demo Step 4 (Retailer A)"
        }, token=token_salesman)
        resp_so = asyncio.run(api_sales_create(req_so))
        self.assertEqual(resp_so.status_code, 200)
        so_data = json.loads(resp_so.body.decode("utf-8"))
        self.assertTrue(so_data.get("success"))

    def test_production_run_flow(self):
        req_prod_login = make_post_request("/api/auth/login", {"username": "prod_suresh", "password": "prod123"})
        resp_prod_login = asyncio.run(api_login(req_prod_login))
        self.assertEqual(resp_prod_login.status_code, 200)
        token_prod = json.loads(resp_prod_login.body.decode("utf-8"))["token"]

        req_wo = make_post_request("/api/production/orders", {
            "bom_id": 1,
            "target_qty": 200,
            "batch_number": "FG-MURUKKU-DEMO01",
            "start_date": "2026-11-27"
        }, token=token_prod)
        resp_wo = asyncio.run(api_production_create(req_wo))
        self.assertEqual(resp_wo.status_code, 200)
        wo_id = json.loads(resp_wo.body.decode("utf-8"))["data"]["wo_id"]

        req_comp = make_post_request(f"/api/production/orders/{wo_id}/complete", {
            "actual_qty_produced": 188,
            "consumptions": [
                {"component_item_id": 1, "item_id": 1, "actual_qty": 40.0, "scrap_qty": 0.0},
                {"component_item_id": 2, "item_id": 2, "actual_qty": 10.5, "scrap_qty": 0.0},
                {"component_item_id": 3, "item_id": 3, "actual_qty": 1.2, "scrap_qty": 0.0},
                {"component_item_id": 4, "item_id": 4, "actual_qty": 188.0, "scrap_qty": 6.0},
                {"component_item_id": 6, "item_id": 6, "actual_qty": 9.0, "scrap_qty": 0.0}
            ],
            "labor_cost": 1200.0,
            "overhead_cost": 600.0
        }, token=token_prod, path_params={"id": wo_id})
        resp_comp = asyncio.run(api_production_complete(req_comp))
        self.assertEqual(resp_comp.status_code, 200)
        comp_data = json.loads(resp_comp.body.decode("utf-8"))["data"]
        self.assertEqual(comp_data["yield_efficiency_percentage"], 94.0)

    def test_payment_split_flow(self):
        req_admin_login = make_post_request("/api/auth/login", {"username": "admin", "password": "admin123"})
        token_admin = json.loads(asyncio.run(api_login(req_admin_login)).body.decode("utf-8"))["token"]

        # Invoice 1 has total 7875, paid 4000, balance 3875 in preloaded scenario
        req_pay = make_post_request("/api/payments", {
            "invoice_id": 1,
            "payment_amount": 3875.0,
            "payment_method": "NEFT",
            "reference_number": "UTR-FINAL-001"
        }, token=token_admin)
        res_pay = asyncio.run(api_payment_record(req_pay))
        self.assertEqual(res_pay.status_code, 200)
        pay_data = json.loads(res_pay.body.decode("utf-8"))["data"]
        self.assertEqual(pay_data["status"], "paid")
        self.assertEqual(pay_data["balance_due"], 0.0)

if __name__ == "__main__":
    unittest.main()
