import hashlib
import hmac
import secrets
import json
import base64
from app.config import SECRET_KEY, ROLES
from app.database import execute_one, execute_write

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"pbkdf2_sha256$100000${salt}${key.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        parts = hashed.split('$')
        if len(parts) != 4 or parts[0] != 'pbkdf2_sha256':
            return False
        iterations = int(parts[1])
        salt = parts[2]
        expected_key = parts[3]
        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
        return hmac.compare_digest(key.hex(), expected_key)
    except Exception:
        return False

def create_session_token(user_id: int, username: str, role: str, full_name: str = None) -> str:
    payload = {
        "id": user_id,
        "user_id": user_id,
        "username": username,
        "role": role,
        "full_name": full_name or username.replace("_", " ").title(),
        "nonce": secrets.token_hex(8)
    }
    payload_bytes = json.dumps(payload).encode('utf-8')
    sig = hmac.new(SECRET_KEY.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
    return f"{base64.urlsafe_b64encode(payload_bytes).decode('utf-8')}.{sig}"

def verify_session_token(token: str):
    if not token or '.' not in token:
        return None
    try:
        payload_b64, sig = token.split('.', 1)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode('utf-8'))
        expected_sig = hmac.new(SECRET_KEY.encode('utf-8'), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        data = json.loads(payload_bytes.decode('utf-8'))
        if "user_id" in data and "id" not in data:
            data["id"] = data["user_id"]
        elif "id" in data and "user_id" not in data:
            data["user_id"] = data["id"]
        return data
    except Exception:
        return None

ROLE_PERMISSIONS = {
    "admin": {
        "sales:create", "sales:approve", "sales:invoice", "sales:view",
        "purchase:create", "purchase:receive", "purchase:view",
        "production:create", "production:execute", "production:view",
        "inventory:adjust", "inventory:view",
        "payments:record", "payments:view",
        "reports:view", "reports:export", "audit:view", "traceability:view"
    },
    "salesman": {
        "sales:create", "sales:view",
        "customers:view", "customers:create",
        "inventory:view"
    },
    "purchase_manager": {
        "purchase:create", "purchase:receive", "purchase:view",
        "inventory:view"
    },
    "production_manager": {
        "production:create", "production:execute", "production:view",
        "inventory:view", "bom:view"
    },
    "accountant": {
        "sales:view", "sales:invoice",
        "purchase:view", "inventory:view",
        "payments:record", "payments:view",
        "reports:view", "reports:export"
    },
    "auditor": {
        "sales:view", "purchase:view", "production:view",
        "inventory:view", "payments:view",
        "reports:view", "reports:export", "audit:view", "traceability:view"
    }
}

def has_permission(role: str, permission: str) -> bool:
    if role == "admin":
        return True
    allowed = ROLE_PERMISSIONS.get(role, set())
    return permission in allowed
