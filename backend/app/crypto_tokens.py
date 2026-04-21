import hashlib
import hmac
import secrets


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_agent_id() -> str:
    return "agt_" + secrets.token_urlsafe(18).replace("=", "")


def generate_token() -> str:
    return secrets.token_urlsafe(48).replace("=", "")


def constant_time_token_equals(left: str, right: str) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    a = left.encode("utf-8")
    b = right.encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)
