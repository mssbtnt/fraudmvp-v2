"""
Message Ingestion Pipeline — Connects extractor output to EntityLinker and TrendDetector.

Flow:
  Raw Message → Extractor → entities + edges
    → EntityLinker.link_from_messages()  [co-occurrence]
    → TrendDetector.record_mentions()    [daily counts]
    → Cross-reference check on new entities
    → Push extracted entities to scored_entities queue

This is the MISSING PIECE that connects the extractor to the Phase 2 services.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from db.database import Database
from services.cross_reference import CrossReferenceEngine
from services.entity_linker import EntityLinker
from services.trend_detector import TrendDetector
from services.victim_signal import VictimSignalDetector
from services.scam_classifier import ScamClassifier

log = logging.getLogger("ingestion")

CONFIG_DIR = Path(__file__).parent.parent / "config"


class IngestionPipeline:
    """
    Processes extracted entities and wires them to Phase 2 services.
    
    Called after the extractor has written entities + edges to DB.
    Performs:
    1. Entity linking (co-occurrence from messages)
    2. Trend tracking (daily mention counts)
    3. Cross-reference checks (BNM/SC lookup)
    4. Victim signal detection
    5. Scam type pre-classification
    """

    def __init__(
        self,
        db: Database,
        cross_ref: Optional[CrossReferenceEngine] = None,
        entity_linker: Optional[EntityLinker] = None,
        trend_detector: Optional[TrendDetector] = None,
        victim_detector: Optional[VictimSignalDetector] = None,
        scam_classifier: Optional[ScamClassifier] = None,
        config_path: Optional[str] = None,
    ):
        self.db = db

        # Load Phase 2 services (lazy init)
        self.cross_ref = cross_ref
        self.entity_linker = entity_linker or EntityLinker(db=db)
        self.trend_detector = trend_detector or TrendDetector(db=db)
        self.victim_detector = victim_detector or VictimSignalDetector()
        self.scam_classifier = scam_classifier or ScamClassifier()

        # Load config
        cfg_path = Path(config_path) if config_path else CONFIG_DIR / "scoring_rules.yaml"
        self.config = {}
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}

        self._cross_ref_loaded = False

    def _ensure_cross_ref(self):
        """Lazy-load cross-reference engine (expensive on first load)."""
        if not self._cross_ref_loaded:
            if self.cross_ref is None:
                self.cross_ref = CrossReferenceEngine(db=self.db)
            self.cross_ref.load()
            self._cross_ref_loaded = True

    # ── Main Ingestion Method ──────────────────────────────────────────────

    def ingest_message(
        self,
        message_text: str,
        extracted_entities: list[dict],
        platform: str = "unknown",
        channel: str = "unknown",
        message_hash: str = "",
        timestamp: Optional[str] = None,
    ) -> dict:
        """
        Process a single message's extracted entities through Phase 2 services.
        
        Args:
            message_text: Raw message text (for victim signals + scam classification)
            extracted_entities: List of dicts with 'id', 'value', 'type', 'count'
            platform: Source platform
            channel: Source channel
            message_hash: Message hash for dedup
            timestamp: ISO timestamp
        
        Returns:
            Dict with ingestion results
        """
        results = {
            "entities_processed": len(extracted_entities),
            "relationships_created": 0,
            "mentions_recorded": 0,
            "cross_ref_matches": 0,
            "victim_signals": 0,
            "scam_type": "unknown",
            "scam_type_tier": "keyword",
            "scam_type_confidence": 0.0,
        }

        if not extracted_entities:
            return results

        ts = timestamp or datetime.now(timezone.utc).isoformat()
        try:
            today = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            today = date.today().isoformat()

        # ── 1. Entity Linking (co-occurrence) ──────────────────────────────
        try:
            msg_data = {
                "text": message_text,
                "entities": extracted_entities,
                "channel": channel,
                "platform": platform,
                "timestamp": ts,
            }
            rel_count = self.entity_linker.link_from_messages([msg_data])
            results["relationships_created"] = rel_count
        except Exception as e:
            log.warning(f"Entity linking failed: {e}")

        # ── 2. Trend Tracking (daily mentions) ─────────────────────────────
        try:
            entity_mentions = {
                e["id"]: e.get("count", 1)
                for e in extracted_entities
                if "id" in e
            }
            mention_count = self.trend_detector.record_mentions(
                today, entity_mentions, platform=platform
            )
            results["mentions_recorded"] = mention_count
        except Exception as e:
            log.warning(f"Trend tracking failed: {e}")

        # ── 3. Cross-Reference Checks ──────────────────────────────────────
        try:
            self._ensure_cross_ref()
            cr_matches = 0
            cr_rows = []
            for entity in extracted_entities:
                if "id" not in entity:
                    continue
                cr_result = self.cross_ref.check_entity(
                    entity.get("value", ""), entity.get("type", "")
                )
                if cr_result.matched:
                    cr_matches += 1
                    for src in cr_result.sources:
                        cr_rows.append((
                            entity["id"], src.database, src.entity_name,
                            cr_result.confidence, src.listed_date, src.status,
                        ))
            # Batch insert cross-reference cache
            if cr_rows:
                try:
                    with self.db.conn() as conn:
                        entity_ids = sorted({row[0] for row in cr_rows})
                        placeholders = ",".join("?" * len(entity_ids))
                        conn.execute(
                            f"DELETE FROM cross_references WHERE entity_id IN ({placeholders})",
                            entity_ids,
                        )
                        conn.executemany(
                            "INSERT OR REPLACE INTO cross_references "
                            "(entity_id, source_db, source_entity_name, "
                            "match_confidence, listed_date, status) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            cr_rows,
                        )
                    created = self.entity_linker.link_from_cross_references(
                        [
                            {
                                "entity_id": row[0],
                                "source_db": row[1],
                                "source_entity_name": row[2],
                            }
                            for row in cr_rows
                        ]
                    )
                    results["relationships_created"] += created
                except Exception as e:
                    log.debug(f"Cross-ref batch cache write failed: {e}")
            results["cross_ref_matches"] = cr_matches
        except Exception as e:
            log.warning(f"Cross-reference check failed: {e}")

        # ── 4. Victim Signal Detection ─────────────────────────────────────
        try:
            victim_result = self.victim_detector.detect_signals(message_text)
            victim_score = self.victim_detector.compute_victim_score(victim_result)
            results["victim_signals"] = len(victim_result.signals)
            results["victim_score"] = victim_score

            # Cache victim signals in DB for each entity (batch insert)
            if victim_result.signals:
                vs_rows = []
                for entity in extracted_entities[:3]:
                    if "id" not in entity:
                        continue
                    for signal in victim_result.signals[:3]:
                        vs_rows.append((
                            entity["id"], signal.signal_type,
                            signal.pattern_matched or "", signal.extracted_text or "",
                            signal.extracted_amount if signal.extracted_amount else None,
                            signal.weight,
                        ))
                if vs_rows:
                    try:
                        with self.db.conn() as conn:
                            entity_ids = sorted({row[0] for row in vs_rows})
                            placeholders = ",".join("?" * len(entity_ids))
                            conn.execute(
                                f"DELETE FROM victim_signals WHERE entity_id IN ({placeholders})",
                                entity_ids,
                            )
                            conn.executemany(
                                "INSERT INTO victim_signals "
                                "(entity_id, signal_type, pattern_matched, extracted_text, "
                                "extracted_amount, weight) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                vs_rows,
                            )
                    except Exception as e:
                        log.debug(f"Victim signal batch cache write failed: {e}")
        except Exception as e:
            log.warning(f"Victim signal detection failed: {e}")

        # ── 5. Scam Type Pre-Classification ────────────────────────────────
        try:
            # Use the best cross-ref result for Tier 3
            best_cr = None
            if results["cross_ref_matches"] > 0:
                self._ensure_cross_ref()
                for entity in extracted_entities:
                    cr_result = self.cross_ref.check_entity(
                        entity.get("value", ""), entity.get("type", "")
                    )
                    if cr_result.matched and (best_cr is None or cr_result.confidence > best_cr.confidence):
                        best_cr = cr_result

            classification = self.scam_classifier.classify(
                text=message_text,
                cross_ref_result=best_cr,
                score=0,  # Will be properly scored by scorer
            )
            results["scam_type"] = classification.campaign_type
            results["scam_type_tier"] = classification.tier
            results["scam_type_confidence"] = classification.confidence
        except Exception as e:
            log.warning(f"Scam classification failed: {e}")

        return results

    def ingest_batch(
        self,
        messages: list[dict],
    ) -> dict:
        """
        Process a batch of messages through the ingestion pipeline.
        
        Args:
            messages: List of dicts with keys:
                'text', 'entities', 'platform', 'channel', 'message_hash', 'timestamp'
        
        Returns:
            Aggregated ingestion results
        """
        total_results = {
            "messages_processed": 0,
            "entities_processed": 0,
            "relationships_created": 0,
            "mentions_recorded": 0,
            "cross_ref_matches": 0,
            "victim_signal_count": 0,
            "scam_types": defaultdict(int),
        }

        for msg in messages:
            result = self.ingest_message(
                message_text=msg.get("text", ""),
                extracted_entities=msg.get("entities", []),
                platform=msg.get("platform", "unknown"),
                channel=msg.get("channel", "unknown"),
                message_hash=msg.get("message_hash", ""),
                timestamp=msg.get("timestamp"),
            )

            total_results["messages_processed"] += 1
            total_results["entities_processed"] += result["entities_processed"]
            total_results["relationships_created"] += result["relationships_created"]
            total_results["mentions_recorded"] += result["mentions_recorded"]
            total_results["cross_ref_matches"] += result["cross_ref_matches"]
            total_results["victim_signal_count"] += result.get("victim_signals", 0)
            total_results["scam_types"][result["scam_type"]] += 1

        # Also do batch-level entity linking (shared phones, shared domains)
        try:
            shared_phones = self.entity_linker.link_shared_phones()
            shared_domains = self.entity_linker.link_shared_domains()
            total_results["shared_phones"] = shared_phones
            total_results["shared_domains"] = shared_domains
            total_results["relationships_created"] += shared_phones + shared_domains
        except Exception as e:
            log.warning(f"Batch entity linking failed: {e}")

        log.info(
            f"Ingested {total_results['messages_processed']} messages: "
            f"{total_results['entities_processed']} entities, "
            f"{total_results['relationships_created']} relationships, "
            f"{total_results['cross_ref_matches']} cross-ref matches"
        )

        # Convert defaultdict to regular dict for JSON serialization
        total_results["scam_types"] = dict(total_results["scam_types"])
        return total_results

    # ── Ingest from DB (for re-processing existing data) ──────────────────

    def ingest_from_db(
        self,
        since: Optional[str] = None,
        limit: int = 1000,
        platform: Optional[str] = None,
        dry_run: bool = False,
        reset_derived: bool = False,
    ) -> dict:
        """
        Re-process messages already in the DB through the ingestion pipeline.
        Useful for backfilling entity_relationships and entity_mentions.
        
        Args:
            since: ISO timestamp — only process messages after this date
            limit: Max messages to process
            platform: Filter by platform
        
        Returns:
            Aggregated ingestion results
        """
        with self.db.conn() as conn:
            query = """
                SELECT sm.text, sm.platform, sm.channel, sm.text_hash AS message_hash, sm.scraped_at,
                       GROUP_CONCAT(e.id || '::' || e.value || '::' || e.type, '||') as entities_str
                FROM scraped_messages sm
                LEFT JOIN entity_edges ee ON ee.message_hash = sm.text_hash
                LEFT JOIN entities e ON e.id = ee.entity_id
                WHERE 1=1
            """
            params = []

            if since:
                query += " AND sm.scraped_at >= ?"
                params.append(since)

            if platform:
                query += " AND sm.platform = ?"
                params.append(platform)

            query += " GROUP BY sm.text_hash ORDER BY sm.scraped_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

        messages = []
        for row in rows:
            entities = []
            if row["entities_str"]:
                for entry in row["entities_str"].split("||"):
                    parts = entry.split("::")
                    if len(parts) >= 3:
                        entities.append({
                            "id": int(parts[0]),
                            "value": parts[1],
                            "type": parts[2],
                            "count": 1,
                        })

            messages.append({
                "text": row["text"] or "",
                "entities": entities,
                "platform": row["platform"] or "unknown",
                "channel": row["channel"] or "unknown",
                "message_hash": row["message_hash"] or "",
                "timestamp": row["scraped_at"],
            })

        if not messages:
            log.info("No messages found in DB for re-processing")
            return {"messages_processed": 0}

        if dry_run:
            return {
                "messages_processed": len(messages),
                "entities_processed": sum(len(msg["entities"]) for msg in messages),
                "dry_run": True,
                "platform": platform,
                "since": since,
            }

        if reset_derived:
            cleared = self.db.reset_derived_tables()
            log.info("Reset derived tables before replay: %s", cleared)

        log.info(f"Re-processing {len(messages)} messages from DB")
        result = self.ingest_batch(messages)
        if reset_derived:
            result["derived_tables_reset"] = True
        return result
