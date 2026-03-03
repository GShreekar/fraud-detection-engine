import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db.neo4j_client import close_neo4j, connect_neo4j
from app.db.redis_client import close_redis, connect_redis
from app.routes import transaction

logger = logging.getLogger(__name__)

# --- Structured logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks for external connections."""
    await connect_redis()
    connect_neo4j()
    yield
    await close_redis()
    await close_neo4j()


app = FastAPI(
    title="Fraud Detection Engine",
    description="Real-time transaction fraud scoring using rule-based checks, Redis velocity, and Neo4j graph analysis.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID to every request for log correlation."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            "unhandled_exception",
            extra={
                "request_id": request_id,
                "error": str(exc),
                "path": request.url.path,
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error"},
            headers={"X-Request-ID": request_id},
        )
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return a consistent JSON error for all unhandled exceptions."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        "unhandled_exception",
        extra={
            "request_id": request_id,
            "error": str(exc),
            "path": request.url.path,
        },
    )
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error"},
    )


app.include_router(transaction.router, prefix="/api/v1", tags=["transactions"])


@app.get("/health", tags=["health"])
def health_check():
    """Return application health status."""
    return {"status": "ok"}
