import asyncio

from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute

from app.main import app, health, health_v2


def _http_contract_set() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                out.add((method, route.path))
    return out


def _ws_contract_set() -> set[str]:
    out: set[str] = set()
    for route in app.routes:
        if isinstance(route, WebSocketRoute):
            out.add(route.path)
    return out


def test_health_handlers_return_ok() -> None:
    assert asyncio.run(health()) == {"status": "ok"}
    assert asyncio.run(health_v2()) == {"status": "ok"}


def test_core_http_routes_exist() -> None:
    contracts = _http_contract_set()
    expected = {
        ("GET", "/health"),
        ("GET", "/v2/health"),
        ("GET", "/v2/social/rooms"),
        ("GET", "/v2/social/rooms/history"),
        ("GET", "/v2/social/rooms/{room_id}/messages"),
        ("GET", "/v2/wall/messages"),
        ("POST", "/v2/wall/messages"),
        ("GET", "/v2/news/articles"),
        ("GET", "/v2/news/articles/{article_id}"),
        ("GET", "/v2/news/columns"),
        ("GET", "/v2/admin/news/columns"),
        ("POST", "/v2/admin/news/columns"),
        ("PUT", "/v2/admin/news/columns/order"),
        ("DELETE", "/v2/admin/news/columns/{agent_id}"),
    }
    assert expected.issubset(contracts)


def test_core_websocket_routes_exist() -> None:
    contracts = _ws_contract_set()
    assert "/v2/agent/ws" in contracts
    assert "/v2/games/ws" in contracts
    assert "/v2/social/observe" in contracts
