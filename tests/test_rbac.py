import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import has_permission, ROLE_PERMISSIONS, verify_password, hash_password, create_session_token, verify_session_token

class TestRBAC(unittest.TestCase):
    def test_password_hashing(self):
        pw = "SuperSecret123"
        hashed = hash_password(pw)
        self.assertTrue(hashed.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password(pw, hashed))
        self.assertFalse(verify_password("WrongPassword", hashed))

    def test_session_tokens(self):
        token = create_session_token(1, "admin", "admin")
        payload = verify_session_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["username"], "admin")
        self.assertEqual(payload["role"], "admin")
        tampered = token[:-4] + "abcd"
        self.assertIsNone(verify_session_token(tampered))

    def test_role_matrix(self):
        self.assertTrue(has_permission("admin", "sales:approve"))
        self.assertTrue(has_permission("admin", "purchase:create"))
        self.assertTrue(has_permission("admin", "production:create"))
        self.assertTrue(has_permission("admin", "payments:record"))

        self.assertTrue(has_permission("salesman", "sales:create"))
        self.assertFalse(has_permission("salesman", "sales:approve"))
        self.assertFalse(has_permission("salesman", "purchase:create"))
        self.assertFalse(has_permission("salesman", "production:create"))

        self.assertTrue(has_permission("purchase_manager", "purchase:create"))
        self.assertTrue(has_permission("purchase_manager", "purchase:receive"))
        self.assertFalse(has_permission("purchase_manager", "sales:approve"))
        self.assertFalse(has_permission("purchase_manager", "production:execute"))

        self.assertTrue(has_permission("production_manager", "production:create"))
        self.assertTrue(has_permission("production_manager", "production:execute"))
        self.assertFalse(has_permission("production_manager", "sales:approve"))
        self.assertFalse(has_permission("production_manager", "payments:record"))

        self.assertTrue(has_permission("auditor", "reports:view"))
        self.assertTrue(has_permission("auditor", "payments:record"))
        self.assertFalse(has_permission("auditor", "production:execute"))
        self.assertFalse(has_permission("auditor", "sales:approve"))

if __name__ == "__main__":
    unittest.main()
