from fastapi import FastAPI, WebSocket

from app.ws_agent import handle_agent_websocket
from app.ws_social_observe import handle_social_observe_websocket


def register_ws_routes(app: FastAPI) -> None:
    @app.websocket("/v2/agent/ws")
    async def agent_ws(websocket: WebSocket) -> None:
        await handle_agent_websocket(websocket)

    @app.websocket("/v2/social/observe")
    async def social_observe_ws(websocket: WebSocket) -> None:
        await handle_social_observe_websocket(websocket)
