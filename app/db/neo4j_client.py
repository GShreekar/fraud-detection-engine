"""
Neo4j client — async connection setup for graph-based fraud pattern detection.

Provides connect_neo4j(), close_neo4j(), and get_driver() for use
as a FastAPI lifespan hook and dependency.
"""

import logging

from neo4j import AsyncGraphDatabase

from app.config import settings

logger = logging.getLogger(__name__)

_driver = None


async def connect_neo4j() -> None:
    """Create the global async Neo4j driver and verify connectivity (called at startup)."""
    global _driver
    _driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        max_connection_pool_size=settings.NEO4J_MAX_CONNECTION_POOL_SIZE,
        connection_timeout=settings.NEO4J_CONNECTION_TIMEOUT,
    )
    try:
        await _driver.verify_connectivity()
        logger.info(
            "neo4j_connected",
            extra={"uri": settings.NEO4J_URI},
        )
    except Exception as exc:
        logger.warning(
            "neo4j_connectivity_check_failed",
            extra={"uri": settings.NEO4J_URI, "error": str(exc)},
        )


async def close_neo4j() -> None:
    """Close the global async Neo4j driver (called at shutdown)."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
        logger.info("neo4j_disconnected")


def get_driver():
    """Return the current Neo4j async driver instance."""
    return _driver
