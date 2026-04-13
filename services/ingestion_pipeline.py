"""
Ingestion pipeline for DB-backed downstream processing.

This branch does not yet contain the Phase 2 enrichers described in the
project plan, but the orchestration layer still needs a concrete ingestion
step after extraction so downstream processing runs from the database state
the extractor has already written.
"""

from __future__ import annotations

from db.database import Database
from agents.scorer import FraudScorerAgent


class IngestionPipeline:
    """
    Bridge extracted entities in the database into downstream analysis.

    The current implementation is DB-first: the extractor persists entities,
    then this pipeline triggers the scorer against the database snapshot
    instead of relying on an intermediate extracted_entities queue.
    """

    def __init__(
        self,
        db: Database | None = None,
        scorer: FraudScorerAgent | None = None,
    ):
        self.db = db or Database()
        self.scorer = scorer or FraudScorerAgent()

    def ingest_batch(self) -> dict:
        """Compatibility wrapper for batch-oriented callers."""
        return self.ingest_from_db()

    def ingest_from_db(self) -> dict:
        """Run downstream ingestion against entities already persisted in the DB."""
        entity_count = len(self.db.get_recent_entities(limit=10000))
        scoring_result = self.scorer.run()
        return {
            "entities_ingested": entity_count,
            "scoring": scoring_result,
        }
