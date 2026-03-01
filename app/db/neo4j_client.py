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


def connect_neo4j() -> None:
    """Create the global async Neo4j driver (called at startup)."""
    global _driver
    _driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
    )
    logger.info(
        "neo4j_connected",
        extra={"uri": settings.NEO4J_URI},
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
