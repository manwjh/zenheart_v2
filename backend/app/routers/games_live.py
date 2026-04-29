import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.games_live_registry import GamesLiveRegistry

router = APIRouter(prefix="/v2/games", tags=["games"])


@router.get("/active")
async def list_active_games(request: Request) -> dict[str, object]:
    """
    Public read: live maze sessions (agents on `/v2/games/ws` with an active maze).
    Same data as the first and subsequent SSE `data` lines on `GET /v2/games/stream`.
    """
    reg: GamesLiveRegistry = request.app.state.games_live_registry
    return {"sessions": await reg.list_sessions()}


@router.get("/stream")
async def stream_games(request: Request) -> StreamingResponse:
    """
    Server-Sent Events: push a JSON line whenever any live session updates or a player drops.
    Human Game page should prefer this over polling `GET /v2/games/active`.
    """
    reg: GamesLiveRegistry = request.app.state.games_live_registry

    async def event_gen():
        q = await reg.subscribe()
        try:
            if await request.is_disconnected():
                return
            initial = await reg.list_sessions()
            yield f"data: {json.dumps({'sessions': initial})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await reg.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
