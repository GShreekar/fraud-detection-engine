from fastapi import FastAPI
from app.routes import transaction

app = FastAPI(
    title="Fraud Detection Engine",
    description="Real-time transaction fraud scoring using rule-based checks, Redis velocity, and Neo4j graph analysis.",
    version="0.1.0",
)

app.include_router(transaction.router, prefix="/api/v1", tags=["transactions"])


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
