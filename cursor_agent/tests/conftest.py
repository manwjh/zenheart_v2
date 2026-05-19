"""Test isolation — load_env mutates os.environ; monkeypatch only tracks patched keys."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_cursor_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
