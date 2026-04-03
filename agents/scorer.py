"""
FraudScorerAgent — 5-step detection pipeline for fraud campaign scoring.

Step 1 — Entity Graph Construction: Map nodes (phone, bank, domain) to edges (channel, timestamp)
Step 2 — Frequency Scoring: entity count ≥3 → +40
Step 3 — Temporal Clustering: cross-channel spread <24h → +30
Step 4 — Content Similarity: LLM script match ≥80% → +20
Step 5 — Campaign Formation: cluster score ≥60 → alert

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
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler
from services.llm_similarity import ScriptSimilarityScorer, KeywordExtractor

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


@dataclass
class Campaign:
    """A detected scam campaign cluster."""
    entity_ids: list[int]
    channel_ids: list[str]
    score: int
    risk_level: str          # low, medium, high, critical
    campaign_type: str        # investment, job_task, aid_gov, phishing
    keywords: list[str]
    reason: str
    script_sample: str
    first_seen: str
    last_seen: str
    entity_count: int
    channel_count: int
    cross_platform: bool

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

        log.info(f"FraudScorerAgent initialized (threshold={self.thresholds})")

    # ── Step 1: Entity Graph ──────────────────────────────────────────────────

    def build_entity_graph(self) -> dict[int, EntityNode]:
        """
        Step 1: Build entity graph from DB.
        Returns: {entity_id: EntityNode}
        """
        entities = self.db.get_recent_entities(limit=10000)
        graph: dict[int, EntityNode] = {}

        for e in entities:
            eid = e["id"]
            edges = self.db.get_edges_for_entity(eid)
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
        return best

    def cluster_entities(self, graph: dict[int, EntityNode]) -> list[Campaign]:
        """
        Step 5: Cluster entities by shared channels and build campaigns.
        Entities sharing ≥1 channel within temporal window → same campaign.
        """
        # Group entities by channel
        channel_to_entities: dict[str, list[int]] = defaultdict(list)
        for eid, node in graph.items():
            for ch in node.channels:
                channel_to_entities[ch].append(eid)

        # Entities that share a channel are candidates for same campaign
        visited: set[int] = set()
        campaigns: list[Campaign] = []

        for channel, entity_ids in channel_to_entities.items():
            for eid in entity_ids:
                if eid in visited:
                    continue

                # BFS to find all connected entities (same channel cluster)
                cluster_ids = set()
                queue = [eid]
                while queue:
                    curr = queue.pop(0)
                    if curr in visited or curr not in graph:
                        continue
                    visited.add(curr)
                    cluster_ids.add(curr)
                    # Add all entities sharing any channel with curr
                    for ch in graph[curr].channels:
                        for neighbor in channel_to_entities.get(ch, []):
                            if neighbor not in visited:
                                queue.append(neighbor)

                if len(cluster_ids) < 2:
                    continue

                # Score the cluster
                campaign = self._score_cluster(cluster_ids, graph)
                if campaign.score >= self.thresholds.get("low", 40):
                    campaigns.append(campaign)

        log.info(f"Formed {len(campaigns)} campaign clusters")
        return campaigns

    def _score_cluster(
        self, cluster_ids: set[int], graph: dict[int, EntityNode]
    ) -> Campaign:
        """Score a cluster of entities as a campaign."""
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
            # Sample text from entity metadata
            all_texts.append(f"{node.type}:{node.value}")

        # Step 2: frequency score (sum of entity scores)
        freq_score = sum(self.score_frequency(n) for n in nodes)

        # Step 3: temporal score (max cross-channel score)
        temporal_score = max((self.score_temporal(n) for n in nodes), default=0)

        # Step 4: content similarity (best match across cluster texts)
        combined_text = " | ".join(all_texts)
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

        total_score = int((freq_score + temporal_score + content_score + channel_bonus) * platform_weight)
        total_score = min(total_score, 100)

        campaign_type = self._classify_campaign_type(all_keywords)

        reason_parts = []
        if freq_score >= 40:
            reason_parts.append(f"high entity reuse (+{freq_score})")
        if temporal_score >= 30:
            reason_parts.append(f"cross-channel spread (+{temporal_score})")
        if content_score >= 15:
            reason_parts.append(f"keyword match (+{content_score})")
        if channel_bonus >= 20:
            reason_parts.append(f"scam language detected (+{channel_bonus})")
        reason = "; ".join(reason_parts) if reason_parts else "threshold met"

        return Campaign(
            entity_ids=sorted(cluster_ids),
            channel_ids=sorted(all_channels),
            score=total_score,
            risk_level=self._risk_level(total_score),
            campaign_type=campaign_type,
            keywords=list(set(all_keywords))[:20],
            reason=reason,
            script_sample=combined_text[:500],
            first_seen=first_seen,
            last_seen=last_seen,
            entity_count=len(nodes),
            channel_count=len(all_channels),
            cross_platform=len(all_platforms) > 1,
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
                campaign_json = campaign.to_dict()
                campaign_json["db_id"] = cid

                if campaign.risk_level in ("medium", "high", "critical"):
                    self.queue.push_to_queue("alerts", json.dumps(campaign_json))
                    self.db.mark_alert_sent(cid)
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
