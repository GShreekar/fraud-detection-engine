from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.neo4j_client import close_neo4j, connect_neo4j
from app.db.redis_client import close_redis, connect_redis
from app.routes import transaction


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

app.include_router(transaction.router, prefix="/api/v1", tags=["transactions"])


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
