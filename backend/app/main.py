from fastapi import FastAPI

from app.bootstrap import lifespan
from app.router_assembly import register_http_routes
from app.services.http_error_handlers import register_http_error_handlers
from app.ws_endpoints import register_ws_routes


app = FastAPI(title="Zenheart v2 backend", lifespan=lifespan)
register_http_error_handlers(app)


@app.get("/")
async def root() -> dict[str, str]:
    """Landing for local checks; API routes live under /v2/… (and /health)."""
    return {
        "service": "zenheart-v2-backend",
        "health": "/health",
        "openapi_docs": "/docs",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v2/health")
async def health_v2() -> dict[str, str]:
    """Same as /health; use when the reverse proxy only forwards /v2/*."""
    return {"status": "ok"}


register_http_routes(app)
register_ws_routes(app)
