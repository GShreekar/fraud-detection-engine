"""
Neo4j client — connection setup for graph-based fraud pattern detection.

TODO: initialize Neo4j async driver using config settings.
"""

# TODO: from neo4j import AsyncGraphDatabase
# TODO: from app.config import settings

# driver = None

# def get_driver():
#     global driver
#     if driver is None:
#         driver = AsyncGraphDatabase.driver(
#             settings.NEO4J_URI,
#             auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
#         )
#     return driver

# async def close_driver():
#     if driver:
#         await driver.close()
