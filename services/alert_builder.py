"""
Alert Builder — Build rich, actionable alert narratives for FraudMVP.

Transforms raw entity + score data into detailed alert messages with:
- Cross-reference confirmation (BNM/SC/SemakMule matches)
- Victim signal evidence
- Trend data (spike detection)
- Entity relationships
- Actionable steps
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from db.database import Database
from services.cross_reference import CrossReferenceEngine, CrossReferenceResult
from services.victim_signal import VictimSignalDetector, VictimSignalResult

log = logging.getLogger("alert_builder")


# ─── Data Classes ──────────────────────────────────────────────────────────────


@dataclass
class EntityNarrative:
    """Narrative for a single entity in an alert."""
    value: str
    entity_type: str
    risk_level: str           # critical, high, medium, low
    cross_references: list[dict] = field(default_factory=list)
    trend: str = ""           # "↑ 340% (3 → 13 mentions)"
    co_occurs_with: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    count: int = 0
    formatted: str = ""


@dataclass
class CampaignNarrative:
    """Narrative for a campaign in an alert."""
    name: str
    scam_type: str
    active_since: str = ""
    message_count: int = 0
    channel_count: int = 0
    platforms: list[str] = field(default_factory=list)


@dataclass
class VictimNarrative:
    """Victim report narrative in an alert."""
    text: str
    source: str
    date: str
    severity: str    # financial_loss, police_report, community_warning, emotional


@dataclass
class TrendNarrative:
    """Trend data narrative for an alert."""
    direction: str     # ↑, ↓, →
    percentage: int = 0
    previous: int = 0
    current: int = 0
    period: str = "7-day"


@dataclass
class AlertNarrative:
    """Complete alert narrative."""
    risk_level: str           # critical, high, medium, low
    scam_type: str            # investment, job_task, phishing, etc.
    headline: str             # "🚨 CRITICAL — Confirmed Fraud Entity"
    entities: list[EntityNarrative] = field(default_factory=list)
    campaign: Optional[CampaignNarrative] = None
    victim_reports: list[VictimNarrative] = field(default_factory=list)
    trend: Optional[TrendNarrative] = None
    actions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw_score: int = 0


# ─── Alert Builder ─────────────────────────────────────────────────────────────


class AlertBuilder:
    """
    Build rich, actionable alert narratives from pipeline data.
    
    Integrates:
    - Cross-reference engine (BNM/SC/SemakMule matches)
    - Victim signal detection (financial loss, police reports)
    - Entity relationship data (co-occurring entities)
    - Trend data (spike detection)
    """

    DEFAULT_RISK_THRESHOLDS = {
        "critical": 90,
        "high": 70,
        "medium": 50,
        "low": 30,
    }

    # Emoji maps
    RISK_EMOJI = {
        "critical": "🚨",
        "high": "🔴",
        "medium": "🟠",
        "low": "🟡",
    }

    TYPE_EMOJI = {
        "phone": "📱",
        "bank_account": "🏦",
        "domain": "🌐",
        "telegram_url": "✈️",
        "telegram_channel": "✈️",
        "whatsapp_link": "💬",
        "facebook_url": "📘",
        "facebook_page": "📘",
        "company_name": "🏢",
        "email": "📧",
        "url": "🔗",
        "ip": "🖥️",
        "app_url": "📱",
        "instagram_url": "📸",
        "twitter_url": "🐦",
    }

    # Action templates by risk level
    ACTIONS = {
        "critical": [
            "Verify at SemakMule: https://semakmule.rmp.gov.my",
            "Report to PDRM (commercial crime): 03-2610 1559",
            "Report to BNM: 1-300-88-5465",
            "Block all identified numbers/accounts immediately",
        ],
        "high": [
            "Verify at SemakMule: https://semakmule.rmp.gov.my",
            "Report to BNM: 1-300-88-5465",
            "Do NOT transfer any funds",
            "Block suspicious contacts",
        ],
        "medium": [
            "Verify at SemakMule: https://semakmule.rmp.gov.my",
            "Exercise caution — do not share personal information",
            "Block suspicious contacts",
        ],
        "low": [
            "Monitor for escalation",
            "Verify at SemakMule: https://semakmule.rmp.gov.my",
        ],
    }

    def __init__(self, db: Database, cross_ref: CrossReferenceEngine | None = None,
                 victim_detector: VictimSignalDetector | None = None,
                 entity_linker=None):
        self.db = db
        self.cross_ref = cross_ref or CrossReferenceEngine(db=db)
        self.victim_detector = victim_detector or VictimSignalDetector()
        self.entity_linker = entity_linker  # Phase 3: EntityLinker
        self.risk_thresholds = self._load_risk_thresholds()

    def build_alert(self, entity_data: dict, score: int,
                    message_text: str = "",
                    channel: str = "",
                    platform: str = "telegram") -> AlertNarrative:
        """
        Build a rich alert narrative from pipeline data.
        
        Args:
            entity_data: Dict with entity details from the pipeline
            score: Computed risk score (0-100)
            message_text: Original message text (for victim signal detection)
            channel: Source channel name
            platform: Source platform (telegram, web, reddit)
            
        Returns:
            AlertNarrative with full context
        """
        # Determine risk level
        risk_level = self._compute_risk_level(score)

        # Build entity narratives
        entity_narratives = []
        total_confidence = 0.0

        # Get entity list from data
        entities = entity_data.get("entities", [])
        if not entities and "value" in entity_data:
            # Single entity format
            entities = [entity_data]

        for entity in entities:
            value = entity.get("value", "")
            entity_type = entity.get("type", "unknown")

            # Cross-reference
            cross_ref_result = self.cross_ref.check_entity(value, entity_type)

            # Build entity narrative
            narrative = EntityNarrative(
                value=value,
                entity_type=entity_type,
                risk_level=self._compute_risk_level(score + cross_ref_result.risk_boost),
                cross_references=[
                    {
                        "database": s.database,
                        "entity_name": s.entity_name,
                        "status": s.status,
                        "listed_date": s.listed_date,
                    }
                    for s in cross_ref_result.sources
                ],
                count=entity.get("count", 1),
                first_seen=entity.get("first_seen", ""),
                last_seen=entity.get("last_seen", ""),
            )

            # Add cross-reference details to formatted text
            narrative.formatted = self._format_entity(narrative, cross_ref_result)
            entity_narratives.append(narrative)

            total_confidence = max(total_confidence, cross_ref_result.confidence)

        # Detect victim signals
        victim_narratives = []
        if message_text:
            signal_result = self.victim_detector.detect_signals(message_text)
            if signal_result.signals:
                # Categorize by severity
                for signal in signal_result.signals:
                    severity = signal.signal_type
                    victim_narratives.append(VictimNarrative(
                        text=signal.extracted_text,
                        source=channel or platform,
                        date=datetime.now(timezone.utc).strftime("%d/%m/%Y"),
                        severity=severity,
                    ))

        # Build campaign narrative if available
        campaign_narrative = None
        campaign_id = entity_data.get("campaign_id")
        if campaign_id:
            campaign_narrative = self._build_campaign_narrative(campaign_id)

        # Determine scam type
        scam_type = entity_data.get("scam_type", entity_data.get("campaign_type", "unknown"))

        # Build headline
        has_cross_ref = any(n.cross_references for n in entity_narratives)
        headline = self._build_headline(risk_level, has_cross_ref, scam_type)

        # Build actions
        actions = self.ACTIONS.get(risk_level, self.ACTIONS["low"]).copy()

        # Add specific cross-reference actions
        for narrative in entity_narratives:
            for ref in narrative.cross_references:
                if ref["database"] == "bnm":
                    actions.append(f"⚠️ Confirmed on BNM Consumer Alert List")
                elif ref["database"] == "sc":
                    actions.append(f"⚠️ Confirmed on SC Investor Alert List")

        # Build final alert
        return AlertNarrative(
            risk_level=risk_level,
            scam_type=scam_type,
            headline=headline,
            entities=entity_narratives,
            campaign=campaign_narrative,
            victim_reports=victim_narratives,
            actions=list(dict.fromkeys(actions)),  # Deduplicate while preserving order
            confidence=total_confidence,
            raw_score=score,
        )

    def format_for_telegram(self, alert: AlertNarrative) -> list[str]:
        """
        Format an alert narrative for Telegram delivery.
        Splits into chunks of max 4000 characters.
        """
        lines = []

        # Header
        emoji = self.RISK_EMOJI.get(alert.risk_level, "⚠️")
        lines.append(f"{emoji} {alert.headline}")
        lines.append("━" * 30)

        # Entities
        for entity in alert.entities:
            lines.append(entity.formatted)

        # Victim reports
        if alert.victim_reports:
            lines.append("")
            lines.append("💬 Victim Reports:")
            for vr in alert.victim_reports[:3]:  # Max 3
                lines.append(f"  • \"{vr.text}\" ({vr.source}, {vr.date})")

        # Campaign
        if alert.campaign:
            lines.append("")
            lines.append(f"📋 Campaign: {alert.campaign.name}")
            lines.append(f"  Type: {alert.campaign.scam_type}")
            lines.append(f"  Active since: {alert.campaign.active_since}")
            lines.append(f"  {alert.campaign.message_count} messages across {alert.campaign.channel_count} channels")

        # Related entities (Phase 3: EntityLinker integration)
        if self.entity_linker and alert.entities:
            related_lines = self._format_related_entities(alert.entities)
            if related_lines:
                lines.append("")
                lines.append("🔗 Entities seen together:")
                lines.extend(related_lines)

        # Trend
        if alert.trend:
            lines.append("")
            lines.append(f"📊 {alert.trend.period} trend: {alert.trend.direction} {alert.trend.percentage}% "
                         f"({alert.trend.previous} → {alert.trend.current} mentions)")

        # Actions
        if alert.actions:
            lines.append("")
            lines.append("━" * 30)
            lines.append("✅ Actions:")
            for i, action in enumerate(alert.actions, 1):
                lines.append(f"  {i}. {action}")

        # Score
        lines.append("")
        lines.append(f"Score: {alert.raw_score} | Confidence: {alert.confidence:.0%} | "
                     f"Type: {alert.scam_type}")

        # Join and chunk
        full_text = "\n".join(lines)
        return self._chunk_message(full_text)

    # ─── Private Methods ───────────────────────────────────────────────────────

    def _compute_risk_level(self, score: int) -> str:
        """Compute risk level from score."""
        if score >= self.risk_thresholds["critical"]:
            return "critical"
        elif score >= self.risk_thresholds["high"]:
            return "high"
        elif score >= self.risk_thresholds["medium"]:
            return "medium"
        else:
            return "low"

    def _load_risk_thresholds(self) -> dict[str, int]:
        """Load risk thresholds from scoring rules to stay aligned with scorer."""
        config_path = Path(__file__).parent.parent / "config" / "scoring_rules.yaml"
        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            thresholds = config.get("risk_thresholds", {})
            return {
                "critical": int(thresholds.get("critical", self.DEFAULT_RISK_THRESHOLDS["critical"])),
                "high": int(thresholds.get("high", self.DEFAULT_RISK_THRESHOLDS["high"])),
                "medium": int(thresholds.get("medium", self.DEFAULT_RISK_THRESHOLDS["medium"])),
                "low": int(thresholds.get("low", self.DEFAULT_RISK_THRESHOLDS["low"])),
            }
        except Exception as exc:
            log.warning("Failed to load scoring thresholds for alert builder: %s", exc)
            return dict(self.DEFAULT_RISK_THRESHOLDS)

    def _format_entity(self, narrative: EntityNarrative,
                       cross_ref: CrossReferenceResult) -> str:
        """Format a single entity for the alert."""
        emoji = self.TYPE_EMOJI.get(narrative.entity_type, "❓")
        lines = [f"{emoji} {narrative.value}"]

        # Cross-reference matches
        for ref in narrative.cross_references:
            db_name = {
                "bnm": "BNM Consumer Alert",
                "sc": "SC Investor Alert",
                "semakmule": "PDRM SemakMule",
                "internal": "Previously flagged",
            }.get(ref.get("database", ""), ref.get("database", ""))
            status = ref.get("status", "confirmed")
            entity_name = ref.get("entity_name", "")
            listed_date = ref.get("listed_date", "")
            status_emoji = "⚠️" if status == "confirmed" else "🔍"
            lines.append(f"   {status_emoji} {db_name}: {entity_name} ({status})")
            if listed_date:
                lines.append(f"      Listed: {listed_date}")

        # Co-occurrences
        if narrative.co_occurs_with:
            lines.append(f"   🔗 Co-occurs with: {', '.join(narrative.co_occurs_with[:3])}")

        # Count and timing
        if narrative.count > 1:
            lines.append(f"   📊 Seen {narrative.count}x")

        return "\n".join(lines)

    def _build_headline(self, risk_level: str, has_cross_ref: bool,
                        scam_type: str) -> str:
        """Build an alert headline."""
        scam_labels = {
            "investment": "Investment Scam",
            "job_task": "Job / Task Scam",
            "aid_gov": "Government Aid Scam",
            "phishing": "Phishing Scam",
            "loan_shark": "Loan Shark / Ah Long",
            "romance": "Romance Scam",
            "ecommerce": "E-Commerce Scam",
            "qr": "QR Code Scam",
            "macau": "Macau Scam",
            "unknown": "Suspicious Activity",
        }

        label = scam_labels.get(scam_type, scam_type.title())

        if risk_level == "critical" and has_cross_ref:
            return f"CRITICAL — Confirmed Fraud Entity ({label})"
        elif risk_level == "critical":
            return f"CRITICAL — {label}"
        elif risk_level == "high" and has_cross_ref:
            return f"HIGH — Known Fraud Entity ({label})"
        elif risk_level == "high":
            return f"HIGH — {label}"
        elif risk_level == "medium":
            return f"MEDIUM — Suspected {label}"
        else:
            return f"LOW — Potential {label}"

    def _build_campaign_narrative(self, campaign_id: int) -> CampaignNarrative | None:
        """Build campaign narrative from DB data."""
        with self.db.conn() as conn:
            cursor = conn.execute(
                "SELECT id, score, risk_level, campaign_type, entity_ids, channel_ids, "
                "keywords, first_seen, last_seen FROM campaigns WHERE id = ?",
                (campaign_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            entity_ids = json.loads(row[4]) if row[4] else []
            channel_ids = json.loads(row[5]) if row[5] else []

            return CampaignNarrative(
                name=f"Campaign #{row[0]}",
                scam_type=row[3] or "unknown",
                active_since=row[7] or "",
                message_count=len(entity_ids),
                channel_count=len(channel_ids),
                platforms=list(set(ch.split(":")[0] for ch in channel_ids if ":" in ch)),
            )

    @staticmethod
    def _chunk_message(text: str, max_length: int = 4000) -> list[str]:
        """Split a long alert into multiple Telegram messages."""
        if len(text) <= max_length:
            return [text]

        chunks = []
        current_chunk = ""

        for line in text.split("\n"):
            if len(current_chunk) + len(line) + 1 > max_length:
                chunks.append(current_chunk)
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"

        if current_chunk:
            chunks.append(current_chunk)

        # Add continuation headers
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = f"[{i+1}/{len(chunks)}] " + chunk
            chunks[i] = chunk

        return chunks

    def _format_related_entities(self, entity_narratives: list[EntityNarrative]) -> list[str]:
        """Format related entities from EntityLinker for alert display."""
        lines = []

        if not self.entity_linker:
            return lines

        # Batch-lookup: collect all entity IDs first, then single query
        entity_id_map = {}  # (value, type) -> id
        with self.db.conn() as conn:
            for entity in entity_narratives[:3]:
                row = conn.execute(
                    "SELECT id FROM entities WHERE value = ? AND type = ? LIMIT 1",
                    (entity.value, entity.entity_type),
                ).fetchone()
                if row:
                    entity_id_map[(entity.value, entity.entity_type)] = row["id"]

        if not entity_id_map:
            return lines

        # Collect all related entity IDs in one pass
        all_related_by_entity = {}  # entity_id -> [(rel, other_id)]
        all_other_ids = set()
        for eid in entity_id_map.values():
            related = self.entity_linker.get_related_entities(eid, max_depth=1)
            if related:
                pairs = []
                for rel in related[:5]:
                    other_id = rel.target_id if rel.source_id == eid else rel.source_id
                    pairs.append((rel, other_id))
                    all_other_ids.add(other_id)
                all_related_by_entity[eid] = pairs

        if not all_other_ids:
            return lines

        # Single batch query for all related entity values
        other_values = {}  # id -> (value, type)
        with self.db.conn() as conn:
            placeholders = ",".join("?" * len(all_other_ids))
            rows = conn.execute(
                f"SELECT id, value, type FROM entities WHERE id IN ({placeholders})",
                list(all_other_ids),
            ).fetchall()
            for r in rows:
                other_values[r["id"]] = (r["value"], r["type"])

        # Format output
        for eid, pairs in all_related_by_entity.items():
            by_type = defaultdict(list)
            for rel, other_id in pairs:
                if other_id in other_values:
                    val, typ = other_values[other_id]
                    by_type[rel.relationship_type].append(f"{val[:40]} ({typ})")

            for rel_type, entities in by_type.items():
                label = rel_type.replace("_", " ").title()
                for entity in entities[:2]:
                    lines.append(f"  • {label}: {entity}")

        return lines[:6]


# ─── Convenience ──────────────────────────────────────────────────────────────

def create_alert_builder(db: Database | None = None) -> AlertBuilder:
    """Create an AlertBuilder with default dependencies."""
    if db is None:
        db = Database()
    cross_ref = CrossReferenceEngine(db=db)
    cross_ref.load()
    victim_detector = VictimSignalDetector()
    return AlertBuilder(db=db, cross_ref=cross_ref, victim_detector=victim_detector)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    # Test alert building
    db = Database()
    builder = create_alert_builder(db=db)
    
    # Simulate an alert
    test_data = {
        "value": "+60123456789",
        "type": "phone",
        "count": 5,
        "scam_type": "investment",
        "campaign_id": None,
        "entities": [
            {"value": "+60123456789", "type": "phone", "count": 5},
            {"value": "123456789012", "type": "bank_account", "count": 3},
        ],
    }
    
    alert = builder.build_alert(
        entity_data=test_data,
        score=75,
        message_text="Kena tipu RM50K oleh abang ni. Dah buat police report.",
        channel="asal_gombak",
        platform="telegram",
    )
    
    print(f"\n{'='*60}")
    print(f"  Alert Built")
    print(f"{'='*60}")
    print(f"Headline: {alert.headline}")
    print(f"Risk: {alert.risk_level}")
