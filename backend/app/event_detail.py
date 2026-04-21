from __future__ import annotations

from typing import Any

_EXCERPT_MAX = 512


def _sanitize_value(key: str, value: Any) -> Any:
    key_lower = str(key).lower()
    if key_lower in {"token", "password", "secret", "authorization", "bearer"}:
        return "[redacted]"
    if isinstance(value, dict):
        return sanitize_detail(value)
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value[:40]]
    if isinstance(value, str) and len(value) > _EXCERPT_MAX:
        return value[:_EXCERPT_MAX] + "..."
    return value


def sanitize_detail(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if detail is None:
        return None
    return {str(k): _sanitize_value(str(k), v) for k, v in detail.items()}
