import unittest
import asyncio
from starlette.requests import Request
from app.web.routes_ui import (
    ui_dashboard, ui_login, ui_salesman_dashboard,
    ui_production_dashboard, ui_accountant_dashboard, ui_auditor_dashboard
)
from app.database import execute_one
from app.security import create_session_token

def make_request(path: str, token: str = None):
    headers = []
    if token:
        headers.append((b"cookie", f"batchwise_session={token}".encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
    }
    return Request(scope)

class TestRoleWorkspaces(unittest.TestCase):
    def test_login_page_renders(self):
        req = make_request("/login")
        resp = asyncio.run(ui_login(req))
        self.assertEqual(resp.status_code, 200)
        body = resp.body.decode("utf-8")
        self.assertIn("BatchWise", body)
        self.assertIn("Sign in", body)

    def test_salesman_workspace_and_rbac(self):
        salesman = execute_one("SELECT * FROM users WHERE role = 'salesman'")
        token = create_session_token(salesman["id"], salesman["username"], salesman["role"])
        
        # Root dashboard redirects to /salesman/dashboard
        req_root = make_request("/", token)
        resp_root = asyncio.run(ui_dashboard(req_root))
        self.assertEqual(resp_root.status_code, 307)
        self.assertEqual(resp_root.headers["location"], "/salesman/dashboard")

        # Salesman dashboard renders 200
        req_dash = make_request("/salesman/dashboard", token)
        resp_dash = asyncio.run(ui_salesman_dashboard(req_dash))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn("FIELD SALES OPERATIONS", resp_dash.body.decode("utf-8"))

        # Salesman blocked from production dashboard (403)
        req_prod = make_request("/production/dashboard", token)
        resp_prod = asyncio.run(ui_production_dashboard(req_prod))
        self.assertEqual(resp_prod.status_code, 403)

        # Salesman blocked from accountant dashboard (403)
        req_acct = make_request("/accountant/dashboard", token)
        resp_acct = asyncio.run(ui_accountant_dashboard(req_acct))
        self.assertEqual(resp_acct.status_code, 403)

    def test_production_supervisor_workspace_and_rbac(self):
        prod = execute_one("SELECT * FROM users WHERE role = 'production_manager'")
        token = create_session_token(prod["id"], prod["username"], prod["role"])

        # Root redirects to /production/dashboard
        req_root = make_request("/", token)
        resp_root = asyncio.run(ui_dashboard(req_root))
        self.assertEqual(resp_root.status_code, 307)
        self.assertEqual(resp_root.headers["location"], "/production/dashboard")

        # Supervisor dashboard renders 200
        req_dash = make_request("/production/dashboard", token)
        resp_dash = asyncio.run(ui_production_dashboard(req_dash))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn("MANUFACTURING FLOOR", resp_dash.body.decode("utf-8"))

        # Supervisor blocked from accountant dashboard (403)
        req_acct = make_request("/accountant/dashboard", token)
        resp_acct = asyncio.run(ui_accountant_dashboard(req_acct))
        self.assertEqual(resp_acct.status_code, 403)

    def test_accountant_workspace_and_rbac(self):
        acct = execute_one("SELECT * FROM users WHERE role = 'accountant'")
        token = create_session_token(acct["id"], acct["username"], acct["role"])

        # Root redirects to /accountant/dashboard
        req_root = make_request("/", token)
        resp_root = asyncio.run(ui_dashboard(req_root))
        self.assertEqual(resp_root.status_code, 307)
        self.assertEqual(resp_root.headers["location"], "/accountant/dashboard")

        # Accountant dashboard renders 200
        req_dash = make_request("/accountant/dashboard", token)
        resp_dash = asyncio.run(ui_accountant_dashboard(req_dash))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn("FINANCIAL ACCOUNTING", resp_dash.body.decode("utf-8"))

        # Accountant blocked from production dashboard (403)
        req_prod = make_request("/production/dashboard", token)
        resp_prod = asyncio.run(ui_production_dashboard(req_prod))
        self.assertEqual(resp_prod.status_code, 403)

    def test_auditor_workspace_and_rbac(self):
        aud = execute_one("SELECT * FROM users WHERE role = 'auditor'")
        token = create_session_token(aud["id"], aud["username"], aud["role"])

        # Root redirects to /auditor/dashboard
        req_root = make_request("/", token)
        resp_root = asyncio.run(ui_dashboard(req_root))
        self.assertEqual(resp_root.status_code, 307)
        self.assertEqual(resp_root.headers["location"], "/auditor/dashboard")

        # Auditor dashboard renders 200
        req_dash = make_request("/auditor/dashboard", token)
        resp_dash = asyncio.run(ui_auditor_dashboard(req_dash))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn("STATUTORY AUDIT & GOVERNANCE", resp_dash.body.decode("utf-8"))

    def test_admin_workspace(self):
        admin = execute_one("SELECT * FROM users WHERE role = 'admin'")
        token = create_session_token(admin["id"], admin["username"], admin["role"])

        # Admin renders executive overview directly
        req_root = make_request("/", token)
        resp_root = asyncio.run(ui_dashboard(req_root))
        self.assertEqual(resp_root.status_code, 200)
        self.assertIn("Executive", resp_root.body.decode("utf-8"))

if __name__ == "__main__":
    unittest.main()
