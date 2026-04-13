"""
Service-level orchestrator for the Fraud MVP pipeline.

The extractor already persists entities to the database, and the scorer reads
from the database. Because of that, the orchestrator must not enqueue the same
entities a second time when running extraction as part of the end-to-end flow.
"""

from __future__ import annotations

from agents.extractor import FraudExtractorAgent
from services.ingestion_pipeline import IngestionPipeline


def run_extraction(
    batch_size: int = FraudExtractorAgent.BATCH_SIZE,
    max_batches: int = 100,
    write_to_queue: bool = True,
) -> dict:
    """Run the extractor with an explicit queue-write policy."""
    extractor = FraudExtractorAgent()
    return extractor.run(
        batch_size=batch_size,
        max_batches=max_batches,
        write_to_queue=write_to_queue,
    )


def orchestrate_pipeline(
    extraction_batch_size: int = FraudExtractorAgent.BATCH_SIZE,
    extraction_max_batches: int = 100,
) -> dict:
    """
    Run extraction and downstream ingestion in sequence.

    Extraction is DB-first in this branch, so queue fan-out is disabled here to
    avoid duplicate extracted_entities pushes. Downstream processing starts from
    the database snapshot immediately after extraction.
    """
    extraction_result = run_extraction(
        batch_size=extraction_batch_size,
        max_batches=extraction_max_batches,
        write_to_queue=False,
    )

    ingestion_pipeline = IngestionPipeline()
    ingestion_result = ingestion_pipeline.ingest_from_db()

    return {
        "extraction": extraction_result,
        "ingestion": ingestion_result,
    }
