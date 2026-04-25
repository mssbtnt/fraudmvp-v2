"""
EntityLinker — Co-occurrence graph builder for FraudMVP.

Builds relationships between entities based on:
- Co-occurrence in messages (same message mentions multiple entities)
- Shared channels (entities appear in same channel/platform)
- Shared phones (phone linked in WhatsApp + standalone)
- Shared domains (domain hosted with other bad domains)
- Same campaign (entities in same campaign cluster)
- Cross-reference (both on same BNM/SC alert entry)

Writes relationships to entity_relationships table with confidence scores.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from db.database import Database

log = logging.getLogger("entity_linker")


@dataclass
class RelationshipResult:
    """Result from a relationship query."""
    source_id: int
    target_id: int
    relationship_type: str
    confidence: float
    evidence: dict


# ─── Relationship confidence defaults ──────────────────────────────────────

RELATIONSHIP_CONFIDENCE = {
    "co_occurrence": 0.6,
    "shared_channel": 0.7,
    "shared_phone": 0.9,
    "shared_domain": 0.8,
    "same_campaign": 0.5,
    "cross_reference": 1.0,
}


class EntityLinker:
    """
    Build and query entity relationship graphs.
    
    Relationships are stored in the entity_relationships table and used for:
    - Score boosting (entities connected to known-bad entities get +10 to +30)
    - Alert enrichment (show related entities in alerts)
    - Campaign linking (connect campaigns through shared entities)
    """

    def __init__(self, db: Database, config: Optional[dict] = None):
        self.db = db
        self.config = config or {}
        self.rel_config = self.config.get("entity_relationships", {})
        self.min_confidence = self.rel_config.get("min_confidence", 0.5)
        self.same_campaign_max_entities = int(
            self.rel_config.get("same_campaign_max_entities", 100)
        )
        self.same_campaign_max_pairs = int(
            self.rel_config.get("same_campaign_max_pairs", 5000)
        )

    # ── Link from scraped messages ──────────────────────────────────────────

    def link_from_messages(self, messages: list[dict]) -> int:
        """
        Process scraped messages and create co-occurrence relationships.

        Co-occurrence relationships are only created when two entities appear
        together in ≥2 DISTINCT messages (different message hashes or timestamps).
        This prevents false co-occurrence signals from entities that only
        happen to appear in the same single message.

        Args:
            messages: List of dicts with 'text' and 'entities' keys.
                      'entities' should be a list of entity dicts with 'id', 'value', 'type'.

        Returns:
            Number of new relationships created.
        """
        created = 0

        # ── Pass 1: Count (entity_pair) → distinct_message_count ──────────
        # Only link entities that appear together across ≥2 different messages
        pair_counts: dict[tuple[int, int], int] = defaultdict(int)
        pair_msgs: dict[tuple[int, int], set[str]] = defaultdict(set)

        for msg in messages:
            entities = msg.get("entities", [])
            if len(entities) < 2:
                continue

            entity_ids = [e["id"] for e in entities]
            msg_key = msg.get("message_hash") or msg.get("timestamp") or str(id(msg))

            for i in range(len(entity_ids)):
                for j in range(i + 1, len(entity_ids)):
                    a, b = entity_ids[i], entity_ids[j]
                    pair = (min(a, b), max(a, b))
                    if pair not in pair_msgs or msg_key not in pair_msgs[pair]:
                        pair_counts[pair] += 1
                        pair_msgs[pair].add(msg_key)

        # ── Pass 2: Create relationships only for multi-message pairs ───────
        # Only load existing relationships for entity IDs in the current batch
        batch_entity_ids = list({eid for pair in pair_msgs for eid in pair})
        existing_counts: dict[tuple[int, int], int] = {}

        if batch_entity_ids:
            with self.db.conn() as conn:
                # Filter by entity IDs in the batch (not full table scan)
                placeholders = ",".join(["?"] * len(batch_entity_ids))
                existing_rows = conn.execute(
                    f"SELECT source_entity_id, target_entity_id, count "
                    f"FROM entity_relationships "
                    f"WHERE relationship_type = 'co_occurrence' "
                    f"AND (source_entity_id IN ({placeholders}) "
                    f"OR target_entity_id IN ({placeholders}))",
                    batch_entity_ids + batch_entity_ids,
                ).fetchall()

            for row in existing_rows:
                key = (row["source_entity_id"], row["target_entity_id"])
                existing_counts[key] = row["count"]

        # Deduplicate: only upsert each qualifying pair ONCE (not per-message)
        seen_pairs: set[tuple[int, int]] = set()

        for pair, msgs_set in pair_msgs.items():
            if len(msgs_set) < 2:
                continue

            source_id, target_id = pair

            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Use any message's metadata for evidence (they share channel/platform)
            # Collect all contributing timestamps for evidence
            contributing_timestamps = sorted(msgs_set)
            evidence = {
                "contributing_messages": len(msgs_set),
                "first_seen": contributing_timestamps[0],
            }

            existing_count = existing_counts.get(pair, 0)
            new_total = existing_count + len(msgs_set)
            new_confidence = min(0.6 + (new_total - 2) * 0.05, 0.95)

            created += self._upsert_relationship(
                source_id=source_id,
                target_id=target_id,
                rel_type="co_occurrence",
                confidence=new_confidence,
                evidence=evidence,
                additional_count=len(msgs_set),
            )

        if created > 0:
            log.info(f"Created {created} co-occurrence relationships from "
                    f"{len(messages)} messages")
        return created

    # ── Link from campaigns ────────────────────────────────────────────────

    def link_from_campaigns(self, campaigns: list[dict]) -> int:
        """
        Link entities within the same campaign cluster.
        
        Args:
            campaigns: List of campaign dicts with 'entity_ids' key (list of entity IDs).
        
        Returns:
            Number of new relationships created.
        """
        created = 0
        
        for campaign in campaigns:
            entity_ids = campaign.get("entity_ids", [])
            if isinstance(entity_ids, str):
                entity_ids = json.loads(entity_ids)

            entity_ids = sorted({int(entity_id) for entity_id in entity_ids})
            if len(entity_ids) < 2:
                continue

            pair_count = len(entity_ids) * (len(entity_ids) - 1) // 2
            if (
                len(entity_ids) > self.same_campaign_max_entities
                or pair_count > self.same_campaign_max_pairs
            ):
                log.warning(
                    "Skipping same_campaign relationship fanout for campaign %s: "
                    "%s entities would create %s pairs (limits: entities=%s, pairs=%s)",
                    campaign.get("id"),
                    len(entity_ids),
                    pair_count,
                    self.same_campaign_max_entities,
                    self.same_campaign_max_pairs,
                )
                continue

            for i in range(len(entity_ids)):
                for j in range(i + 1, len(entity_ids)):
                    source_id = entity_ids[i]
                    target_id = entity_ids[j]
                    if source_id > target_id:
                        source_id, target_id = target_id, source_id
                    
                    created += self._upsert_relationship(
                        source_id=source_id,
                        target_id=target_id,
                        rel_type="same_campaign",
                        confidence=RELATIONSHIP_CONFIDENCE["same_campaign"],
                        evidence={"campaign_id": campaign.get("id"), "campaign_type": campaign.get("campaign_type")},
                    )
        
        if created > 0:
            log.info(f"Created {created} same_campaign relationships from {len(campaigns)} campaigns")
        return created

    # ── Link from cross-references ─────────────────────────────────────────

    def link_from_cross_references(self, cross_refs: list[dict]) -> int:
        """
        Link entities that appear on the same BNM/SC alert entry.
        
        Args:
            cross_refs: List of cross-reference dicts with 'entity_id', 'source_db', 
                        'source_entity_name' keys.
        
        Returns:
            Number of new relationships created.
        """
        created = 0
        
        # Group by source entry (same BNM/SC listing often has multiple entities)
        by_source = defaultdict(list)
        for cr in cross_refs:
            key = (cr.get("source_db", ""), cr.get("source_entity_name", ""))
            by_source[key].append(cr)
        
        for key, refs in by_source.items():
            if len(refs) < 2:
                continue
            
            entity_ids = [cr["entity_id"] for cr in refs]
            source_db = key[0]
            
            for i in range(len(entity_ids)):
                for j in range(i + 1, len(entity_ids)):
                    source_id = entity_ids[i]
                    target_id = entity_ids[j]
                    if source_id > target_id:
                        source_id, target_id = target_id, source_id
                    
                    created += self._upsert_relationship(
                        source_id=source_id,
                        target_id=target_id,
                        rel_type="cross_reference",
                        confidence=RELATIONSHIP_CONFIDENCE["cross_reference"],
                        evidence={"source_db": source_db, "source_entry": key[1]},
                    )
        
        if created > 0:
            log.info(f"Created {created} cross_reference relationships")
        return created

    # ── Link from shared attributes ────────────────────────────────────────

    def link_shared_phones(self) -> int:
        """
        Find phone entities that also appear in WhatsApp links (shared phone number).
        Links phone entities with whatsapp_link entities that contain the same phone.
        Uses batch upsert instead of per-match DB calls.
        """
        created = 0

        with self.db.conn() as conn:
            # Get all phone entities
            phones = conn.execute(
                "SELECT id, value FROM entities WHERE type = 'phone'"
            ).fetchall()

            # Get all whatsapp_link entities
            whatsapp_links = conn.execute(
                "SELECT id, value FROM entities WHERE type = 'whatsapp_link'"
            ).fetchall()

        phone_map = {self._normalise_phone(p["value"]): p["id"] for p in phones}

        # Collect all matching pairs for batch upsert
        pairs: list[tuple[int, int, str, str]] = []  # (source_id, target_id, phone, whatsapp_link)
        for wl in whatsapp_links:
            wl_phone = self._extract_phone_from_whatsapp(wl["value"])
            if wl_phone and wl_phone in phone_map:
                phone_id = phone_map[wl_phone]
                wl_id = wl["id"]
                source_id = min(phone_id, wl_id)
                target_id = max(phone_id, wl_id)
                pairs.append((source_id, target_id, wl_phone, wl["value"]))

        # Batch check existing relationships
        if pairs:
            pair_ids = list({(p[0], p[1]) for p in pairs})
            with self.db.conn() as conn:
                placeholders = ",".join(["(?,?)"] * len(pair_ids))
                existing = conn.execute(
                    f"SELECT source_entity_id, target_entity_id, id, count, confidence "
                    f"FROM entity_relationships "
                    f"WHERE relationship_type = 'shared_phone' "
                    f"AND (source_entity_id, target_entity_id) IN ({placeholders})",
                    [val for pair in pair_ids for val in pair],
                ).fetchall()

            existing_set = {(r["source_entity_id"], r["target_entity_id"]) for r in existing}

            # Separate new vs existing
            new_pairs = []
            update_pairs = []
            for source_id, target_id, phone, wl_value in pairs:
                if (source_id, target_id) not in existing_set:
                    new_pairs.append((source_id, target_id, phone, wl_value))
                else:
                    update_pairs.append((source_id, target_id, phone, wl_value))

            # Batch insert new relationships
            if new_pairs:
                with self.db.conn() as conn:
                    conn.executemany(
                        "INSERT INTO entity_relationships "
                        "(source_entity_id, target_entity_id, relationship_type, confidence, evidence, count) "
                        "VALUES (?, ?, 'shared_phone', ?, ?, 1)",
                        [
                            (s, t, RELATIONSHIP_CONFIDENCE["shared_phone"],
                             json.dumps({"phone": p, "whatsapp_link": w}))
                            for s, t, p, w in new_pairs
                        ],
                    )
                    conn.commit()
                created += len(new_pairs)

            # Batch update existing relationships (increment count, update last_seen)
            if update_pairs:
                with self.db.conn() as conn:
                    for s, t, p, w in update_pairs:
                        conn.execute(
                            "UPDATE entity_relationships SET count = count + 1, "
                            "last_seen = CURRENT_TIMESTAMP "
                            "WHERE source_entity_id = ? AND target_entity_id = ? "
                            "AND relationship_type = 'shared_phone'",
                            (s, t),
                        )
                    conn.commit()

        if created > 0:
            log.info(f"Created {created} shared_phone relationships")
        return created

    # Maximum number of domain pairs per root domain group to prevent
    # pathological O(n²) explosion on popular root domains.
    MAX_DOMAIN_PAIRS_PER_ROOT = 50

    def link_shared_domains(self) -> int:
        """
        Find domain entities that share the same root domain.
        Links domains with the same registrable domain (e.g., scam1.example.com + scam2.example.com).
        Limits pairs per root domain to MAX_DOMAIN_PAIRS_PER_ROOT to avoid O(n²) explosion.
        """
        created = 0

        with self.db.conn() as conn:
            domains = conn.execute(
                "SELECT id, value FROM entities WHERE type = 'domain'"
            ).fetchall()

        # Group by root domain
        root_domain_map: dict[str, list[int]] = defaultdict(list)
        for d in domains:
            root = self._get_root_domain(d["value"])
            if root:
                root_domain_map[root].append(d["id"])

        # Link domains sharing the same root (with per-group limit)
        for root, ids in root_domain_map.items():
            if len(ids) < 2:
                continue

            # Limit pairs per root domain to prevent O(n²) explosion
            pair_count = 0
            for i in range(len(ids)):
                if pair_count >= self.MAX_DOMAIN_PAIRS_PER_ROOT:
                    break
                for j in range(i + 1, len(ids)):
                    if pair_count >= self.MAX_DOMAIN_PAIRS_PER_ROOT:
                        break
                    source_id = min(ids[i], ids[j])
                    target_id = max(ids[i], ids[j])

                    created += self._upsert_relationship(
                        source_id=source_id,
                        target_id=target_id,
                        rel_type="shared_domain",
                        confidence=RELATIONSHIP_CONFIDENCE["shared_domain"],
                        evidence={"root_domain": root},
                    )
                    pair_count += 1

        if created > 0:
            log.info(f"Created {created} shared_domain relationships")
        return created

    # ── Query methods ──────────────────────────────────────────────────────

    def get_related_entities(
        self, entity_id: int, max_depth: int = 2
    ) -> list[RelationshipResult]:
        """
        BFS traversal of relationship graph, up to max_depth hops.
        
        Args:
            entity_id: Starting entity ID
            max_depth: Maximum hops from starting entity
        
        Returns:
            List of RelationshipResult objects
        """
        results = []
        visited = {entity_id}
        queue = deque([(entity_id, 0)])
        
        with self.db.conn() as conn:
            while queue:
                current_id, depth = queue.popleft()
                if depth >= max_depth:
                    continue
                
                # Find all relationships involving this entity
                rows = conn.execute(
                    "SELECT source_entity_id, target_entity_id, relationship_type, "
                    "confidence, evidence FROM entity_relationships "
                    "WHERE source_entity_id = ? OR target_entity_id = ?",
                    (current_id, current_id),
                ).fetchall()
                
                for row in rows:
                    related_id = row["target_entity_id"] if row["source_entity_id"] == current_id else row["source_entity_id"]
                    
                    if related_id in visited:
                        continue
                    
                    visited.add(related_id)
                    
                    evidence = {}
                    if row["evidence"]:
                        try:
                            evidence = json.loads(row["evidence"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    
                    results.append(RelationshipResult(
                        source_id=row["source_entity_id"],
                        target_id=row["target_entity_id"],
                        relationship_type=row["relationship_type"],
                        confidence=row["confidence"],
                        evidence=evidence,
                    ))
                    
                    queue.append((related_id, depth + 1))
        
        return results

    def compute_relationship_boost(self, entity_id: int) -> float:
        """
        Calculate score boost based on how an entity connects to other bad entities.
        
        Uses the entity_relationships config in scoring_rules.yaml:
          co_occurrence: 10
          shared_phone: 25
          shared_domain: 20
          same_campaign: 15
          cross_reference: 30
        """
        relationships = self.get_related_entities(entity_id, max_depth=1)
        
        total_boost = 0.0
        seen_types = set()
        
        for rel in relationships:
            # Only count each relationship type once
            if rel.relationship_type in seen_types:
                continue
            seen_types.add(rel.relationship_type)
            
            weight_key = f"{rel.relationship_type}_weight"
            weight = self.rel_config.get(weight_key, 0)
            # Scale by confidence
            total_boost += weight * rel.confidence
        
        return min(total_boost, 30.0)  # Cap at 30

    # ── Private helpers ─────────────────────────────────────────────────────

    def _upsert_relationship(
        self,
        source_id: int,
        target_id: int,
        rel_type: str,
        confidence: float,
        evidence: dict,
        additional_count: int = 1,
    ) -> int:
        """Insert or update a relationship. Returns 1 if created, 0 if updated/skipped.

        Args:
            additional_count: Number of new observations to add to the count (default 1).
                              For co-occurrence, this is the number of distinct messages.
        """
        if source_id == target_id:
            return 0

        try:
            with self.db.conn() as conn:
                # Check if relationship already exists
                existing = conn.execute(
                    "SELECT id, count FROM entity_relationships "
                    "WHERE source_entity_id = ? AND target_entity_id = ? AND relationship_type = ?",
                    (source_id, target_id, rel_type),
                ).fetchone()

                if existing:
                    # Update: add additional_count, update confidence (max), update last_seen
                    new_count = (existing["count"] or 0) + additional_count
                    new_confidence = max(existing["confidence"], confidence)
                    conn.execute(
                        "UPDATE entity_relationships SET count = ?, confidence = ?, "
                        "last_seen = CURRENT_TIMESTAMP, evidence = ? WHERE id = ?",
                        (new_count, new_confidence, json.dumps(evidence), existing["id"]),
                    )
                    conn.commit()
                    return 0  # Updated, not new
                else:
                    conn.execute(
                        "INSERT INTO entity_relationships "
                        "(source_entity_id, target_entity_id, relationship_type, "
                        "confidence, evidence, count) VALUES (?, ?, ?, ?, ?, ?)",
                        (source_id, target_id, rel_type, confidence, json.dumps(evidence), additional_count),
                    )
                    conn.commit()
                    return 1  # New relationship
        except Exception as e:
            log.debug(f"Failed to upsert relationship {source_id}-{rel_type}->{target_id}: {e}")
            return 0

    @staticmethod
    def _normalise_phone(phone: str) -> str:
        """Normalise phone number for comparison."""
        import re
        # Strip +60, spaces, dashes, parentheses
        p = re.sub(r'[\s\-\(\)\+]', '', phone)
        if p.startswith("60"):
            p = p[2:]
        if p.startswith("0"):
            p = p[1:]
        return p

    @staticmethod
    def _extract_phone_from_whatsapp(url: str) -> Optional[str]:
        """Extract phone number from WhatsApp link."""
        import re
        # wa.me/6012345678 or wasap.my/6012345678
        match = re.search(r'(?:wa\.me|wasap\.my|chat\.whatsapp\.com)/?\+?(\d{8,15})', url)
        if match:
            phone = match.group(1)
            if phone.startswith("60"):
                phone = phone[2:]
            if phone.startswith("0"):
                phone = phone[1:]
            return phone
        return None

    @staticmethod
    def _get_root_domain(domain: str) -> Optional[str]:
        """Extract root domain (e.g., example.com from sub.example.com)."""
        # Simple approach: take last 2 parts for normal domains
        # For .com.my, .co.uk etc, take last 3 parts
        parts = domain.lower().strip().split(".")
        if len(parts) < 2:
            return None
        
        # Known multi-part TLDs
        multi_tlds = {".com.my", ".co.uk", ".com.sg", ".co.id", ".org.my", ".net.my"}
        last_three = ".".join(parts[-3:])
        if f".{last_three}" in multi_tlds or len(parts) >= 3 and parts[-2] in {"com", "co", "org", "net"} and len(parts[-1]) == 2:
            return ".".join(parts[-3:])
        
        return ".".join(parts[-2:])
