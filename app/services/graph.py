"""
GraphService — Neo4j-backed relationship fraud detection.

Detects shared device/IP fraud patterns by querying the transaction
graph for suspicious connections between users, devices, and IPs.

TODO: implement Cypher queries for graph-based pattern detection.
"""

from app.models.transaction import TransactionRequest


class GraphService:
    def __init__(self):
        # TODO: inject Neo4j client from app.db.neo4j_client
        pass

    async def evaluate(self, transaction: TransactionRequest) -> tuple[float, list[str]]:
        """
        Queries the graph for fraud patterns and returns (score_contribution, reasons).
        Stub: returns (0.0, []) until Neo4j client is wired.
        """
        score = 0.0
        reasons: list[str] = []

        # TODO: query shared device/IP rings using Cypher, e.g.:
        # MATCH (u:User)-[:USED]->(d:Device)<-[:USED]-(other:User) ...

        return score, reasons
