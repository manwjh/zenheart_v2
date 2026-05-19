from fastapi import FastAPI, WebSocket

from app.ws_agent import handle_agent_websocket
from app.ws_social_observe import handle_social_observe_websocket

AGENT_WS_PATH = "/v2/agent/ws"
SOCIAL_OBSERVE_WS_PATH = "/v2/social/observe"
PUBLIC_WS_ENDPOINTS = frozenset({AGENT_WS_PATH, SOCIAL_OBSERVE_WS_PATH})


def register_ws_routes(app: FastAPI) -> None:
    # These are the only public WebSocket endpoints in v2. Most files named
    # services/ws_*.py are frame-family handlers dispatched by /v2/agent/ws,
    # not additional sockets.
    @app.websocket(AGENT_WS_PATH)
    async def agent_ws(websocket: WebSocket) -> None:
        await handle_agent_websocket(websocket)

    @app.websocket(SOCIAL_OBSERVE_WS_PATH)
    async def social_observe_ws(websocket: WebSocket) -> None:
        await handle_social_observe_websocket(websocket)
