"""
FraudScorerAgent — 9-step detection pipeline for fraud campaign scoring.

Step 1 — Entity Graph Construction: Map nodes (phone, bank, domain) to edges (channel, timestamp)
Step 2 — Frequency Scoring: entity count ≥3 → +40
Step 3 — Temporal Clustering: cross-channel spread <24h → +30
Step 4 — Content Similarity: LLM script match ≥80% → +20
Step 5 — Scam Type Classification: 3-tier (keyword → LLM → cross-ref)
Step 6 — Cross-Reference Scoring: BNM/SC match → +45 to +50
Step 7 — Victim Signal Scoring: financial loss, police report → +5 to +50
Step 8 — Entity Relationship Scoring: co-occurrence, shared phone → +10 to +30
Step 9 — Trend Scoring: spike/rise/increase → +10 to +20

Alert tiers:
  40-59  → log only
  60-79  → medium alert
  80-94  → high alert
  95+    → critical alert
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler
from services.campaign_types import normalize_campaign_type
from services.llm_similarity import ScriptSimilarityScorer, KeywordExtractor
from services.llm_enhancer import FraudLLMEnhancer
from services.cross_reference import CrossReferenceEngine
from services.victim_signal import VictimSignalDetector
from services.scam_classifier import ScamClassifier
from services.entity_linker import EntityLinker
from services.campaign_namer import CampaignNamer
from services.trend_detector import TrendDetector

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
CONFIG_DIR = Path(__file__).parent.parent / "config"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("scorer")


# ─── Scoring dataclasses ───────────────────────────────────────────────────────

@dataclass
class EntityNode:
    id: int
    value: str
    type: str
    count: int
    channels: list[str]
    platforms: list[str]
    first_seen: str
    last_seen: str
    campaign_id: int | None = None  # already assigned → skip re-clustering


@dataclass
class Campaign:
    """A detected scam campaign cluster."""
    entity_ids: list[int]
    channel_ids: list[str]
    score: int
    risk_level: str          # low, medium, high, critical
    campaign_type: str        # investment, job_task, aid_gov, phishing, loan_shark, romance, ecommerce, qr, macau
    keywords: list[str]
    reason: str
    script_sample: str
    first_seen: str
    last_seen: str
    entity_count: int
    channel_count: int
    cross_platform: bool
    # Phase 1: Enriched fields
    entity_values: list[dict] = None  # [{type, value, count}]
    cross_references: list[dict] = None  # [{entity_value, sources, confidence}]
    victim_signals: list[dict] = None   # [{type, text, weight}]
    # Phase 2: New fields
    name: str = ""                          # Auto-generated campaign name
    scam_type_tier: str = "keyword"          # "keyword" | "llm" | "cross_reference"
    scam_type_confidence: float = 0.0        # 0.0-1.0
    relationship_boost: float = 0.0          # Entity relationship boost
    trend_status: str = "stable"             # "spike" | "rising" | "increasing" | "stable" | "declining"

    def __post_init__(self):
        if self.entity_values is None:
            self.entity_values = []
        if self.cross_references is None:
            self.cross_references = []
        if self.victim_signals is None:
            self.victim_signals = []

    def to_dict(self) -> dict:
        return {
            "entity_ids": self.entity_ids,
            "channel_ids": self.channel_ids,
            "score": self.score,
            "risk_level": self.risk_level,
            "campaign_type": self.campaign_type,
            "keywords": self.keywords,
            "reason": self.reason,
            "script_sample": self.script_sample[:200] if self.script_sample else "",
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "entity_count": self.entity_count,
            "channel_count": self.channel_count,
            "cross_platform": self.cross_platform,
            "entity_values": self.entity_values,
            "cross_references": self.cross_references,
            "victim_signals": self.victim_signals,
            # Phase 2 fields
            "name": self.name,
            "scam_type_tier": self.scam_type_tier,
            "scam_type_confidence": self.scam_type_confidence,
            "relationship_boost": self.relationship_boost,
            "trend_status": self.trend_status,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ─── FraudScorerAgent ─────────────────────────────────────────────────────────

class FraudScorerAgent:
    """
    5-step detection pipeline for scam campaigns.

    Scans entities in DB, builds entity graph, scores clusters,
    and generates campaign alerts when threshold is breached.
    """

    def __init__(self):
        self.db = Database()
        self.queue = QueueHandler()
        self.keyword_extractor = KeywordExtractor()
        self.similarity_scorer = ScriptSimilarityScorer()
        self.llm_enhancer = FraudLLMEnhancer()  # Gemma 4 integration

        # Phase 1: Cross-reference engine + victim signal detector
        self.cross_ref = CrossReferenceEngine(db=self.db)
        self.cross_ref.load()
        self.victim_detector = VictimSignalDetector()

        # Load scoring rules
        cfg_path = CONFIG_DIR / "scoring_rules.yaml"
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                self.cfg = yaml.safe_load(f)
        else:
            self.cfg = {}

        self.freq_cfg = self.cfg.get("frequency", {})
        self.temporal_cfg = self.cfg.get("temporal", {})
        self.channel_cfg = self.cfg.get("channel_quality", {})
        self.platform_weights = self.cfg.get("source_weights", {})
        self.thresholds = self.cfg.get("risk_thresholds", {"low": 40, "medium": 60, "high": 80})
        self.cross_ref_cfg = self.cfg.get("cross_reference", {})
        self.victim_cfg = self.cfg.get("victim_signals", {})
        self.rel_cfg = self.cfg.get("entity_relationships", {})
        self.trend_cfg = self.cfg.get("trend", {})

        # Phase 2: Scam classifier, entity linker, campaign namer, trend detector
        self.scam_classifier = ScamClassifier(
            keyword_extractor=self.keyword_extractor,
            llm_enhancer=self.llm_enhancer,
            cross_reference_engine=self.cross_ref,
        )
        self.entity_linker = EntityLinker(db=self.db, config=self.cfg)
        self.campaign_namer = CampaignNamer(db=self.db)
        self.trend_detector = TrendDetector(db=self.db, config=self.cfg)

        log.info(f"FraudScorerAgent initialized (threshold={self.thresholds}, cross_ref loaded, Phase 2 active)")

    # ── Step 1: Entity Graph ──────────────────────────────────────────────────

    def build_entity_graph(self, since: str | None = None) -> dict[int, EntityNode]:
        """
        Step 1: Build entity graph from DB.
        Skips entities already assigned to a campaign.
        Uses delta scoring: only loads entities seen since last scoring run.

        Args:
            since: ISO date string (e.g. '2026-04-13'). If None, loads last 7 days.

        Returns: {entity_id: EntityNode}
        """
        if since is None:
            since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        # Delta: only entities not yet scored AND seen since `since`
        entities = self.db.get_recent_entities(limit=10000)
        graph: dict[int, EntityNode] = {}
        candidate_entities = [
            e for e in entities
            if not e.get("campaign_id")
            and (e.get("last_seen", "") >= since or e.get("first_seen", "") >= since)
        ]
        edges_map = self.db.get_edges_for_entities([e["id"] for e in candidate_entities])

        for e in candidate_entities:
            eid = e["id"]
            edges = edges_map.get(eid, [])
            channels = list({edge["channel"] for edge in edges})
            platforms = list({edge["platform"] for edge in edges})

            graph[eid] = EntityNode(
                id=eid,
                value=e["value"],
                type=e["type"],
                count=e["count"],
                channels=channels,
                platforms=platforms,
                first_seen=e["first_seen"],
                last_seen=e["last_seen"],
                campaign_id=e.get("campaign_id"),
            )

        log.info(f"Entity graph built: {len(graph)} nodes")
        return graph

    # ── Step 2: Frequency Scoring ─────────────────────────────────────────────

    def score_frequency(self, node: EntityNode) -> int:
        """Step 2: Score based on entity repetition count."""
        count = node.count
        if count >= 4:
            return self.freq_cfg.get("entity_count_4_plus", 50)
        elif count >= 3:
            return self.freq_cfg.get("entity_count_3", 40)
        elif count >= 2:
            return self.freq_cfg.get("each_additional_repeat", 10)
        return 0

    # ── Step 3: Temporal Clustering ──────────────────────────────────────────

    def score_temporal(self, node: EntityNode) -> int:
        """
        Step 3: Score based on cross-channel spread within 24h.
        Higher score for cross-platform spread.
        """
        if len(node.channels) >= 3:
            # Cross-channel cluster — check timing
            cross_platform = len(node.platforms) > 1
            if cross_platform:
                return self.temporal_cfg.get("cross_platform_24h", 40)
            return self.temporal_cfg.get("cross_channel_same_platform_24h", 30)
        elif len(node.channels) >= 2:
            return self.temporal_cfg.get("same_channel_48h", 15)
        return 0

    # ── Step 4: Content Similarity ────────────────────────────────────────────

    def score_content(self, text: str, campaign_type: str) -> tuple[int, list[str]]:
        """
        Step 4: Score based on keyword matching and LLM content similarity.
        Returns: (score, matched_keywords)
        """
        keywords_found = self.keyword_extractor.extract(text)
        matched: list[str] = []
        keyword_score = 0.0
        for kws in keywords_found.values():
            for item in kws:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    matched.append(item[0])
                    keyword_score += float(item[1])
                elif isinstance(item, str):
                    matched.append(item)

        # Scale keyword score to ~30 max
        score = min(int(keyword_score * 0.3), 30)
        return score, matched

    # ── Step 5: Campaign Formation ───────────────────────────────────────────

    def _risk_level(self, score: int) -> str:
        if score >= self.thresholds.get("critical", 95):
            return "critical"
        elif score >= self.thresholds.get("high", 80):
            return "high"
        elif score >= self.thresholds.get("medium", 60):
            return "medium"
        elif score >= self.thresholds.get("low", 40):
            return "low"
        return "log_only"

    def _classify_campaign_type(self, keywords: list[str]) -> str:
        """Map matched keywords to campaign type."""
        cat_map = {
            "investment": ["pelaburan", "crypto", "forex", "signal", "ipo", "trading", "robot", "uang gratis", "profit"],
            "job_task": ["kerja", "part time", "task", "tiktok", "duit", "misi", "rm50", "kerja mudah"],
            "aid_gov": ["bantuan", "kerajaan", "rm500", "bkm", "layak", "rm1000", "wang ehsan"],
            "phishing": ["otp", "verifikasi", "login", "suspended", "kansel", "password"],
        }
        best = "unknown"
        best_count = 0
        for cat, terms in cat_map.items():
            count = sum(1 for kw in keywords if any(t in kw.lower() for t in terms))
            if count > best_count:
                best = cat
                best_count = count
        return normalize_campaign_type(best)

    def cluster_entities(self, graph: dict[int, EntityNode]) -> list[Campaign]:
        """
        Step 5: Cluster entities by shared channels AND entity relationships.
        
        Two clustering passes:
        1. Channel-based: entities sharing ≥1 channel within temporal window
        2. Relationship-based: merge clusters connected by high-confidence relationships
        """
        # ── Pass 1: Channel-based clustering ────────────────────────────────
        channel_to_entities: dict[str, list[int]] = defaultdict(list)
        for eid, node in graph.items():
            for ch in node.channels:
                channel_to_entities[ch].append(eid)

        # BFS clustering by shared channels
        visited: set[int] = set()
        clusters: list[set[int]] = []

        for channel, entity_ids in channel_to_entities.items():
            for eid in entity_ids:
                if eid in visited:
                    continue

                cluster_ids: set[int] = set()
                local_visited: set[int] = {eid}
                queue: deque[int] = deque([eid])
                while queue:
                    curr = queue.popleft()
                    if curr not in graph:
                        continue
                    cluster_ids.add(curr)
                    visited.add(curr)
                    for ch in graph[curr].channels:
                        for neighbor in channel_to_entities.get(ch, []):
                            if neighbor not in local_visited:
                                local_visited.add(neighbor)
                                queue.append(neighbor)

                if len(cluster_ids) >= 2:
                    clusters.append(cluster_ids)

        log.info(f"Pass 1 (channel-based): {len(clusters)} clusters")

        # ── Pass 2: Relationship-based merge ────────────────────────────────
        # Check entity_relationships for cross-cluster connections
        # If entity A in cluster X has a high-confidence relationship with
        # entity B in cluster Y, merge X and Y
        merged_clusters = self._merge_by_relationships(clusters, graph)

        log.info(f"Pass 2 (relationship merge): {len(merged_clusters)} clusters")

        # ── Score and deduplicate clusters ──────────────────────────────────
        campaigns: list[Campaign] = []
        for cluster_ids in merged_clusters:
            campaign = self._score_cluster(cluster_ids, graph)
            if campaign.score >= self.thresholds.get("low", 40):
                # Campaign deduplication: check overlap with existing campaigns
                if not self._is_duplicate_campaign(campaign):
                    campaigns.append(campaign)

        log.info(f"Formed {len(campaigns)} campaign clusters (after dedup)")
        return campaigns

    def _merge_by_relationships(
        self, clusters: list[set[int]], graph: dict[int, EntityNode]
    ) -> list[set[int]]:
        """
        Merge clusters connected by high-confidence entity relationships.
        
        Merges if:
        - cross_reference relationship (confidence ≥ 1.0) → always merge
        - shared_phone relationship (confidence ≥ 0.9) → always merge
        - co_occurrence relationship (confidence ≥ 0.6) → merge if both clusters ≤5 entities
        """
        if not clusters:
            return clusters

        # Build entity → cluster index
        entity_cluster = {}
        for i, cluster in enumerate(clusters):
            for eid in cluster:
                entity_cluster[eid] = i

        # Union-Find for merging
        parent = list(range(len(clusters)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                # Merge smaller into larger
                if len(clusters[ra]) < len(clusters[rb]):
                    ra, rb = rb, ra
                parent[rb] = ra

        # Query entity_relationships for cross-cluster connections
        try:
            with self.db.conn() as conn:
                # Get all high-confidence relationships
                rows = conn.execute(
                    "SELECT source_entity_id, target_entity_id, relationship_type, confidence "
                    "FROM entity_relationships "
                    "WHERE confidence >= 0.6 "
                    "AND relationship_type IN ('cross_reference', 'shared_phone', 'co_occurrence', 'shared_domain')"
                ).fetchall()

            merge_thresholds = {
                "cross_reference": 0.8,    # High confidence — always merge
                "shared_phone": 0.8,       # High confidence — always merge
                "shared_domain": 0.7,      # Medium confidence
                "co_occurrence": 0.6,       # Lower confidence — only small clusters
            }

            merges = 0
            for row in rows:
                src = row[0]
                tgt = row[1]
                rel_type = row[2]
                confidence = row[3]

                if src not in entity_cluster or tgt not in entity_cluster:
                    continue

                src_cluster_idx = entity_cluster[src]
                tgt_cluster_idx = entity_cluster[tgt]

                if src_cluster_idx == tgt_cluster_idx:
                    continue  # Already in same cluster

                threshold = merge_thresholds.get(rel_type, 1.0)
                if confidence < threshold:
                    continue

                # For co_occurrence, only merge small clusters
                if rel_type == "co_occurrence":
                    if len(clusters[find(src_cluster_idx)]) > 5 or len(clusters[find(tgt_cluster_idx)]) > 5:
                        continue

                union(src_cluster_idx, tgt_cluster_idx)
                merges += 1

            if merges > 0:
                log.info(f"  Relationship merge: {merges} cluster pairs merged")

            # Rebuild clusters from union-find
            merged = defaultdict(set)
            for i in range(len(clusters)):
                root = find(i)
                merged[root].update(clusters[i])

            return list(merged.values())

        except Exception as e:
            log.warning(f"Relationship merge failed: {e}")
            return clusters

    def _is_duplicate_campaign(self, campaign: Campaign) -> bool:
        """
        Check if a new campaign overlaps ≥70% with an existing campaign.
        If so, it's a duplicate — skip it.
        """
        try:
            with self.db.conn() as conn:
                # Get recent campaigns
                existing = conn.execute(
                    "SELECT id, entity_ids FROM campaigns "
                    "WHERE created_at >= datetime('now', '-7 days') "
                    "ORDER BY created_at DESC LIMIT 50"
                ).fetchall()

            new_entity_set = set(campaign.entity_ids)

            for row in existing:
                try:
                    existing_ids = set(json.loads(row["entity_ids"]))
                except (json.JSONDecodeError, TypeError):
                    continue

                if not existing_ids:
                    continue

                # Jaccard similarity
                intersection = len(new_entity_set & existing_ids)
                union = len(new_entity_set | existing_ids)
                similarity = intersection / union if union > 0 else 0

                if similarity >= 0.7:
                    log.debug(f"  Duplicate campaign detected (similarity={similarity:.2f} "
                              f"with campaign {row['id']})")
                    return True

            return False
        except Exception as e:
            log.debug(f"Dedup check failed: {e}")
            return False

    def _score_cluster(
        self, cluster_ids: set[int], graph: dict[int, EntityNode]
    ) -> Campaign:
        """Score a cluster of entities as a campaign (9-step pipeline)."""
        nodes = [graph[eid] for eid in cluster_ids if eid in graph]
        if not nodes:
            return Campaign([], [], 0, "log_only", "unknown", [], "", "", "", "", 0, 0, False)

        # Aggregate channel info
        all_channels: set[str] = set()
        all_platforms: set[str] = set()
        all_texts: list[str] = []
        first_seen = min(n.first_seen for n in nodes)
        last_seen = max(n.last_seen for n in nodes)
        all_keywords: list[str] = []

        for node in nodes:
            all_channels.update(node.channels)
            all_platforms.update(node.platforms)
            all_texts.append(f"{node.type}:{node.value}")

        combined_text = " | ".join(all_texts)

        # Step 2: frequency score (sum of entity scores)
        freq_score = sum(self.score_frequency(n) for n in nodes)

        # Step 3: temporal score (max cross-channel score)
        temporal_score = max((self.score_temporal(n) for n in nodes), default=0)

        # Step 4: content similarity (best match across cluster texts)
        content_score, keywords = self.score_content(combined_text, "")
        all_keywords.extend(keywords)

        # Step 5: channel quality bonus
        channel_bonus = 0
        for ch in all_channels:
            if "telegram" in ch.lower():
                channel_bonus += self.channel_cfg.get("scam_language_detected", 20)

        # Platform weight
        primary_platform = list(all_platforms)[0] if all_platforms else "web"
        platform_weight = self.platform_weights.get(primary_platform, 0.8)

        # ── Step 5: Scam Type Classification (Phase 2) ──────────────────────
        classification_result = self.scam_classifier.classify(
            text=combined_text,
            keyword_results=None,
            cross_ref_result=None,
            score=0,  # Will update after scoring
        )
        campaign_type = classification_result.campaign_type
        scam_type_tier = classification_result.tier
        scam_type_confidence = classification_result.confidence

        # If Tier 1 gave "unknown" and we have keywords, try with keyword results
        if campaign_type == "unknown" and all_keywords:
            from services.llm_similarity import KeywordExtractor
            keyword_dict = {}
            for kw in all_keywords:
                keyword_dict.setdefault("matched", []).append([kw, 10])
            classification_result = self.scam_classifier._classify_tier1_keyword(
                combined_text, keyword_dict
            )
            if classification_result.campaign_type != "unknown":
                campaign_type = classification_result.campaign_type
                scam_type_tier = classification_result.tier
                scam_type_confidence = classification_result.confidence

        # ── Step 6: Cross-Reference Scoring (Phase 1) ──────────────────────
        cross_ref_score = 0
        cross_ref_matches = []
        best_cross_ref = None
        cr_cache_rows: list[tuple] = []  # Batch collect cross-ref INSERTs

        for node in nodes:
            cr_result = self.cross_ref.check_entity(node.value, node.type)
            if cr_result.matched:
                cross_ref_score += cr_result.risk_boost
                cross_ref_matches.append({
                    "entity_value": node.value,
                    "entity_type": node.type,
                    "sources": [
                        {"database": s.database, "entity_name": s.entity_name,
                         "status": s.status, "listed_date": s.listed_date}
                        for s in cr_result.sources
                    ],
                    "confidence": cr_result.confidence,
                })
                if best_cross_ref is None:
                    best_cross_ref = cr_result
                # Collect cross-reference rows for batch insert
                for src in cr_result.sources:
                    cr_cache_rows.append((
                        node.id, src.database, src.entity_name,
                        cr_result.confidence, src.listed_date, src.status,
                    ))

        # Batch insert cross-references (instead of N+1 individual inserts)
        if cr_cache_rows:
            try:
                with self.db.conn() as conn:
                    conn.executemany(
                        "INSERT OR REPLACE INTO cross_references "
                        "(entity_id, source_db, source_entity_name, match_confidence, listed_date, status) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        cr_cache_rows,
                    )
                    conn.commit()
            except Exception as e:
                log.debug(f"Failed to batch-cache cross-references: {e}")

        # Cap cross-reference boost
        max_cross_ref = self.cross_ref_cfg.get("bnm_match_boost", 50) + 10
        cross_ref_score = min(cross_ref_score, max_cross_ref)

        # Tier 3: Override scam type from cross-reference
        if best_cross_ref and scam_type_confidence < 0.95:
            cr_type_result = self.scam_classifier._classify_from_cross_reference(best_cross_ref)
            if cr_type_result and cr_type_result != "unknown":
                campaign_type = cr_type_result
                scam_type_tier = "cross_reference"
                scam_type_confidence = 0.95

        # ── Step 7: Victim Signal Scoring (Phase 1) ─────────────────────────
        victim_score = 0
        victim_signals_data = []
        message_text = combined_text
        victim_result = self.victim_detector.detect_signals(message_text)
        victim_score = self.victim_detector.compute_victim_score(victim_result)

        if victim_score > 0:
            victim_signals_data = [
                {"type": s.signal_type, "text": s.extracted_text, "weight": s.weight}
                for s in victim_result.signals[:5]
            ]

        # LLM enhancement for suspicious clusters (existing logic)
        llm_boost = 0
        base_score = freq_score + temporal_score + content_score + channel_bonus + cross_ref_score + victim_score
        total_score = int(base_score * platform_weight)

        if (
            self.llm_enhancer
            and getattr(self.llm_enhancer, "enabled", True)
            and combined_text
            and len(combined_text) > 20
            and total_score >= 40
        ):
            try:
                analysis = self.llm_enhancer.analyze_message(
                    combined_text,
                    entities=[{"type": n.type, "value": n.value} for n in nodes[:5]],
                    keyword_score=total_score,
                )
                if analysis.confidence > 0.0:
                    if analysis.risk_level == "critical":
                        llm_boost = 15
                    elif analysis.risk_level == "high":
                        llm_boost = 10
                    elif analysis.risk_level == "medium":
                        llm_boost = 5
                    llm_boost = int(llm_boost * analysis.confidence)

                    # Tier 2: LLM scam type if keyword was low confidence
                    if scam_type_confidence < 0.8 and total_score >= 60:
                        llm_type = normalize_campaign_type(analysis.scam_type)
                        if llm_type != "unknown":
                            campaign_type = llm_type
                            scam_type_tier = "llm"
                            scam_type_confidence = min(analysis.confidence, 0.90)
            except Exception as e:
                log.warning(f"LLM enhancement failed: {e}")

        total_score = min(total_score + llm_boost, 100)

        # ── Step 8: Entity Relationship Scoring (Phase 2) ──────────────────
        relationship_boost = 0.0
        for node in nodes:
            try:
                boost = self.entity_linker.compute_relationship_boost(node.id)
                relationship_boost = max(relationship_boost, boost)
            except Exception as e:
                log.debug(f"Relationship boost failed for entity {node.id}: {e}")

        total_score = min(total_score + int(relationship_boost), 100)

        # ── Step 9: Trend Scoring (Phase 2) ─────────────────────────────────
        trend_status = "stable"
        trend_boost = 0
        # Check trend for the most prominent entity
        if nodes:
            primary_node = max(nodes, key=lambda n: n.count)
            try:
                trends = self.trend_detector.detect_trends(entity_id=primary_node.id)
                if trends:
                    trend = trends[0]  # Highest boost first
                    trend_status = trend.trend_status
                    trend_boost = trend.boost
                    total_score = min(total_score + trend_boost, 100)
            except Exception as e:
                log.debug(f"Trend detection failed for entity {primary_node.id}: {e}")

        # Build reason string
        reason_parts = []
        if freq_score >= 40:
            reason_parts.append(f"high entity reuse (+{freq_score})")
        if temporal_score >= 30:
            reason_parts.append(f"cross-channel spread (+{temporal_score})")
        if content_score >= 15:
            reason_parts.append(f"keyword match (+{content_score})")
        if channel_bonus >= 20:
            reason_parts.append(f"scam language detected (+{channel_bonus})")
        if cross_ref_score > 0:
            reason_parts.append(f"cross-reference confirmed (+{cross_ref_score})")
        if victim_score > 0:
            reason_parts.append(f"victim signals (+{victim_score})")
        if llm_boost > 0:
            reason_parts.append(f"LLM boost (+{llm_boost})")
        if relationship_boost > 0:
            reason_parts.append(f"entity relationships (+{int(relationship_boost)})")
        if trend_boost > 0:
            reason_parts.append(f"trend: {trend_status} (+{trend_boost})")
        reason = "; ".join(reason_parts) if reason_parts else "threshold met"

        # Build entity_values for enriched alerter display
        entity_values = [
            {"type": n.type, "value": n.value, "count": n.count}
            for n in nodes
        ]

        # Generate campaign name
        campaign_name = self.campaign_namer.name_campaign(
            campaign_type=campaign_type,
            entity_values=entity_values,
            cross_references=cross_ref_matches,
        )

        return Campaign(
            entity_ids=sorted(cluster_ids),
            channel_ids=sorted(all_channels),
            score=total_score,
            risk_level=self._risk_level(total_score),
            campaign_type=campaign_type,  # Already normalized by scam_classifier
            keywords=list(set(all_keywords))[:20],
            reason=reason,
            script_sample=combined_text[:500],
            first_seen=first_seen,
            last_seen=last_seen,
            entity_count=len(nodes),
            channel_count=len(all_channels),
            cross_platform=len(all_platforms) > 1,
            entity_values=entity_values,
            cross_references=cross_ref_matches,
            victim_signals=victim_signals_data,
            # Phase 2 fields
            name=campaign_name,
            scam_type_tier=scam_type_tier,
            scam_type_confidence=scam_type_confidence,
            relationship_boost=relationship_boost,
            trend_status=trend_status,
        )

    # ── Main run ───────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Run the full 5-step detection pipeline.
        Returns summary dict.
        """
        log.info("═══ FraudScorerAgent starting ═══")

        # Step 1: Build entity graph
        graph = self.build_entity_graph()

        # Steps 2-5: Score and cluster
        campaigns = self.cluster_entities(graph)

        # Write campaigns to DB and queue alerts
        alerts_triggered = 0
        logged = 0
        by_risk: dict[str, int] = defaultdict(int)

        for campaign in campaigns:
            try:
                cid = self.db.upsert_campaign(
                    score=campaign.score,
                    risk_level=campaign.risk_level,
                    campaign_type=campaign.campaign_type,
                    entity_ids=campaign.entity_ids,
                    channel_ids=campaign.channel_ids,
                    keywords=campaign.keywords,
                    reason=campaign.reason,
                    script_sample=campaign.script_sample,
                )

                # Update Phase 2 fields
                try:
                    with self.db.conn() as conn:
                        conn.execute(
                            "UPDATE campaigns SET name = ?, scam_type_tier = ?, "
                            "scam_type_confidence = ?, relationship_boost = ?, "
                            "trend_status = ? WHERE id = ?",
                            (campaign.name, campaign.scam_type_tier,
                             campaign.scam_type_confidence, campaign.relationship_boost,
                             campaign.trend_status, cid),
                        )
                        conn.commit()
                except Exception as e:
                    log.debug(f"Failed to update Phase 2 fields: {e}")

                # Build entity relationships from campaign
                try:
                    self.entity_linker.link_from_campaigns([{
                        "id": cid,
                        "entity_ids": campaign.entity_ids,
                        "campaign_type": campaign.campaign_type,
                    }])
                except Exception as e:
                    log.debug(f"Entity linking failed: {e}")

                # Record mentions for trend detection
                try:
                    from datetime import date
                    entity_value_map = {
                        node_id: node.value for node_id, node in graph.items()
                    }
                    entity_count_map = {
                        entity.get("value", ""): int(entity.get("count", 1) or 1)
                        for entity in (campaign.entity_values or [])
                    }
                    entity_mentions = {
                        eid: max(1, entity_count_map.get(entity_value_map.get(eid, ""), 1))
                        for eid in campaign.entity_ids
                    }
                    self.trend_detector.record_mentions(date.today().isoformat(), entity_mentions)
                except Exception as e:
                    log.debug(f"Trend recording failed: {e}")

                campaign_json = campaign.to_dict()
                campaign_json["db_id"] = cid

                if campaign.risk_level in ("medium", "high", "critical"):
                    self.queue.push_to_queue("alerts", json.dumps(campaign_json))
                    alerts_triggered += 1
                else:
                    logged += 1

                by_risk[campaign.risk_level] += 1
                log.info(
                    f"  Campaign {cid}: score={campaign.score} "
                    f"risk={campaign.risk_level} type={campaign.campaign_type} "
                    f"entities={campaign.entity_count} channels={campaign.channel_count}"
                )

            except Exception as e:
                log.error(f"Failed to save campaign: {e}")

        stats = self.db.stats()
        result = {
            "entities_scored": len(graph),
            "campaigns_formed": len(campaigns),
            "alerts_triggered": alerts_triggered,
            "logged_only": logged,
            "by_risk": dict(by_risk),
            "db_stats": stats,
        }

        log.info(f"═══ Scoring complete: {alerts_triggered} alerts, {logged} logged ═══")
        return result


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = FraudScorerAgent()
    result = agent.run()
    print(json.dumps(result, indent=2))
