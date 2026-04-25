"""
FraudAlerterAgent — Campaign alert delivery via Telegram (or demo log).

Delegates formatting to services.alert_formatter.

Responsibilities:
- Consumes campaigns from Redis alerts queue
- Loads authoritative data from DB
- Formats and delivers alerts via Telegram bot
- Logs delivery status to DB
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler
from services.alert_formatter import (
    format_alert,
    format_summary,
    send_telegram_message,
    RISK_EMOJI,
    CAMPAIGN_TYPE_LABEL,
)
from services.alert_builder import AlertBuilder
from services.daily_report import build_daily_report, format_daily_report, DailyReportState

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN", "")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("alerter")


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


# ─── FraudAlerterAgent ────────────────────────────────────────────────────────

class FraudAlerterAgent:
    """
    Consumes campaign alerts from the alerts queue and delivers them.

    In demo mode: logs formatted alerts instead of sending.
    In live mode: sends via Telegram Bot API.
    """

    BATCH_SIZE = 20

    def __init__(self):
        self.queue = QueueHandler()
        self.db = Database()
        self.demo_mode = DEMO_MODE

        # Phase 1: Alert builder for rich narratives
        self.alert_builder = AlertBuilder(db=self.db)

        log.info(f"FraudAlerterAgent initialized (demo={self.demo_mode})")

    def _build_run_summary(self, delivered: int, failed: int) -> dict:
        """Build a daily-report summary dict from pipeline-provided env metadata."""
        def env_int(name: str, default: int = 0) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default

        def env_bool(name: str, default: bool = False) -> bool:
            return _env_flag(name, default)

        return {
            "collection": {
                "success": env_bool("FRAUDMVP_COLLECTION_SUCCESS", False),
                "required_sources": {
                    "telegram": {"success": env_bool("FRAUDMVP_TELEGRAM_SUCCESS", False), "messages": env_int("FRAUDMVP_TELEGRAM_MESSAGES", 0)},
                    "rss": {"success": env_bool("FRAUDMVP_RSS_SUCCESS", False), "messages": env_int("FRAUDMVP_RSS_MESSAGES", 0)},
                    "web": {"success": env_bool("FRAUDMVP_WEB_SUCCESS", False), "messages": env_int("FRAUDMVP_WEB_MESSAGES", 0)},
                    "opensanctions": {"success": env_bool("FRAUDMVP_OPENSANCTIONS_SUCCESS", False), "messages": env_int("FRAUDMVP_OPENSANCTIONS_MESSAGES", 0)},
                },
                "optional_sources": {
                    "semakmule": {"success": env_bool("FRAUDMVP_SEMAKMULE_SUCCESS", True), "messages": env_int("FRAUDMVP_SEMAKMULE_MESSAGES", 0), "enabled": True},
                    "reddit": {"success": env_bool("FRAUDMVP_REDDIT_SUCCESS", True), "messages": env_int("FRAUDMVP_REDDIT_MESSAGES", 0), "enabled": env_bool("FRAUDMVP_REDDIT_ENABLED", True)},
                },
                "scraped_messages_persisted": env_int("FRAUDMVP_SCRAPED_MESSAGES_PERSISTED", 0),
            },
            "extraction": {
                "success": env_bool("FRAUDMVP_EXTRACTION_SUCCESS", False),
                "messages_processed": env_int("FRAUDMVP_MESSAGES_PROCESSED", 0),
                "entities_extracted": env_int("FRAUDMVP_ENTITIES_EXTRACTED", 0),
            },
            "scoring": {
                "success": env_bool("FRAUDMVP_SCORING_SUCCESS", False),
                "campaigns_scored": env_int("FRAUDMVP_CAMPAIGNS_SCORED", 0),
                "alerts_triggered": env_int("FRAUDMVP_ALERTS_TRIGGERED", 0),
            },
            "alerting": {
                "success": failed == 0,
                "alerts_sent": delivered,
            },
        }

    def _send_daily_report(self, delivered: int, failed: int) -> None:
        """Send a run-level report that distinguishes no data from no alerts."""
        required_metadata = [
            "FRAUDMVP_COLLECTION_SUCCESS",
            "FRAUDMVP_EXTRACTION_SUCCESS",
            "FRAUDMVP_SCORING_SUCCESS",
        ]
        if not any(os.getenv(name) is not None for name in required_metadata):
            log.info("Skipping daily report because no pipeline run metadata was provided")
            return

        report_date = datetime.now(timezone.utc).strftime("%d/%m/%Y")
        summary = self._build_run_summary(delivered=delivered, failed=failed)
        report = build_daily_report(summary, report_date=report_date)

        if report.state == DailyReportState.ALERTS_FOUND and not _env_flag(
            "FRAUDMVP_SEND_ALERTS_FOUND_SUMMARY",
            False,
        ):
            return

        message = format_daily_report(report)
        if self.demo_mode:
            log.info("[DEMO DAILY REPORT]\n%s", message)
            return

        if not ALERT_BOT_TOKEN or not ALERT_CHAT_ID:
            log.warning("No ALERT_BOT_TOKEN or ALERT_CHAT_ID — daily report logged only")
            log.info("[DAILY REPORT]\n%s", message)
            return

        result = send_telegram_message(ALERT_BOT_TOKEN, ALERT_CHAT_ID, message)
        if "error" in result:
            log.warning("Failed to send daily report: %s", result.get("error"))
        else:
            log.info("Daily report sent: %s", report.state.value)

    def process_alert(self, campaign_json: str) -> bool:
        """
        Process a single campaign alert. Always fetches fresh entity data
        from DB so the alert always contains actionable information.
        Uses AlertBuilder for rich narratives with cross-reference + victim signals.
        """
        try:
            campaign = json.loads(campaign_json)
        except json.JSONDecodeError:
            log.error(f"Invalid JSON in alerts queue: {campaign_json[:80]}")
            return False

        db_id = campaign.get("db_id") or campaign.get("campaign_id")
        if not db_id:
            log.error("Alert payload has no campaign_id — cannot process")
            return False

        with self.db.conn() as conn:
            row = conn.execute(
                "SELECT * FROM campaigns WHERE id=?", (db_id,)
            ).fetchone()
            if not row:
                log.error(f"Campaign {db_id} not found in DB — skipping")
                return False
            campaign = dict(row)

        if campaign.get("alert_sent"):
            log.info(f"Campaign {db_id} already sent — skipping")
            return True

        entity_ids = json.loads(campaign.get("entity_ids") or "[]")
        if entity_ids:
            ph = ",".join("?" * len(entity_ids))
            with self.db.conn() as conn:
                rows = conn.execute(
                    f"SELECT type, value, count FROM entities WHERE id IN ({ph})",
                    entity_ids,
                ).fetchall()
            campaign["entity_values"] = [
                {"type": r["type"], "value": r["value"], "count": r["count"]}
                for r in rows
            ]

        # ── Phase 1: Use AlertBuilder for rich narratives ──────────────────
        # Build alert using cross-reference + victim signal data
        message_text = campaign.get("script_sample", "")
        channel = ""
        if campaign.get("channel_ids"):
            channels = json.loads(campaign["channel_ids"]) if isinstance(campaign["channel_ids"], str) else campaign["channel_ids"]
            channel = channels[0] if channels else ""

        # Check if cross_references and victim_signals are already in the campaign data
        # (populated by scorer.py Phase 1 integration)
        cross_refs = campaign.get("cross_references", [])
        victim_signals = campaign.get("victim_signals", [])

        # Phase 2 fields
        campaign_name = campaign.get("name", "")
        scam_type_tier = campaign.get("scam_type_tier", "keyword")
        trend_status = campaign.get("trend_status", "stable")
        relationship_boost = campaign.get("relationship_boost", 0.0)

        # Build rich alert narrative
        # Map entity_values → entities key expected by AlertBuilder.build_alert()
        if campaign.get("entity_values") and not campaign.get("entities"):
            campaign["entities"] = campaign["entity_values"]

        try:
            alert = self.alert_builder.build_alert(
                entity_data=campaign,
                score=campaign.get("score", 0),
                message_text=message_text,
                channel=channel,
                platform="telegram",
            )

            # Override with any cross-references from scorer (already computed)
            if cross_refs and not alert.entities:
                # Scorer already did cross-reference — attach to alert
                for ref in cross_refs:
                    for entity_narrative in alert.entities:
                        if entity_narrative.value == ref.get("entity_value", ""):
                            # Already has cross-refs from alert_builder
                            break

            formatted_chunks = self.alert_builder.format_for_telegram(alert)

            # Append Phase 2 metadata
            if campaign_name:
                for i, chunk in enumerate(formatted_chunks):
                    if i == 0:
                        # Prepend campaign name to first chunk
                        formatted_chunks[0] = f"📋 **{campaign_name}**\n\n{chunk}"
                    break  # Only modify first chunk

            if trend_status != "stable":
                trend_emoji = {"spike": "📈", "rising": "📊", "increasing": "📉"}.get(trend_status, "➡️")
                trend_suffix = f"\n{trend_emoji} **Trend:** {trend_status.title()}"
                if len(formatted_chunks[-1]) + len(trend_suffix) <= 4000:
                    formatted_chunks[-1] += trend_suffix

            if relationship_boost > 0:
                rel_suffix = f"\n🔗 **Entity Links:** +{int(relationship_boost)} (connected entities)"
                if len(formatted_chunks[-1]) + len(rel_suffix) <= 4000:
                    formatted_chunks[-1] += rel_suffix
        except Exception as e:
            log.warning(f"AlertBuilder failed, falling back to format_alert: {e}")
            formatted_chunks = [format_alert(campaign)]

        # ── Deliver alerts ──────────────────────────────────────────────────
        if self.demo_mode:
            for chunk in formatted_chunks:
                log.info(f"[DEMO ALERT]\n{chunk}")
            return True

        if not ALERT_BOT_TOKEN or not ALERT_CHAT_ID:
            log.warning("No ALERT_BOT_TOKEN or ALERT_CHAT_ID — logging only")
            for chunk in formatted_chunks:
                log.info(f"[ALERT]\n{chunk}")
            return True

        # Send all chunks
        all_sent = True
        full_message = "\n".join(formatted_chunks)
        for chunk in formatted_chunks:
            result = send_telegram_message(ALERT_BOT_TOKEN, ALERT_CHAT_ID, chunk)
            if "error" in result:
                log.error(f"Telegram delivery failed: {result['error']}")
                all_sent = False

        if all_sent:
            log.info(f"Telegram alert sent: campaign_id={db_id} ({len(formatted_chunks)} chunks)")
            self.db.mark_alert_sent(db_id)
            self.db.log_alert(
                campaign_id=db_id,
                alert_level=campaign.get("risk_level", "unknown"),
                message=full_message[:1000],
                sent_to=ALERT_CHAT_ID,
                status="delivered",
            )
        else:
            self.db.log_alert(
                campaign_id=db_id,
                alert_level=campaign.get("risk_level", "unknown"),
                message=full_message[:1000],
                sent_to=ALERT_CHAT_ID,
                status="partial",
                response="Some chunks failed to deliver",
            )

        return all_sent

    def run(self, batch_size: int = BATCH_SIZE, max_batches: int = 100) -> dict:
        """
        Process alerts from the queue.
        Runs up to max_batches iterations.
        Sends "No New Alert Found Today" if queue is empty.
        """
        log.info("═══ FraudAlerterAgent starting ═══")

        delivered = 0
        failed = 0
        count_by_risk: dict[str, int] = {}
        queue_was_empty = False

        for _ in range(max_batches):
            raw = self.queue.pop_from_queue("alerts", timeout=5)
            if raw is None:
                log.info("Alerts queue empty — stopping")
                queue_was_empty = True
                break

            campaign = {}
            try:
                campaign = json.loads(raw)
            except Exception:
                pass

            success = self.process_alert(raw)

            if success:
                delivered += 1
                risk = campaign.get("risk_level", "unknown")
                count_by_risk[risk] = count_by_risk.get(risk, 0) + 1
            else:
                failed += 1

            # Rate-limit between campaigns to avoid Telegram 429 floods
            time.sleep(0.5)

        self._send_daily_report(delivered=delivered, failed=failed)

        if count_by_risk:
            summary = format_summary(count_by_risk)
            log.info(f"\n{summary}")

        log.info(f"═══ Alerter complete: {delivered} delivered, {failed} failed ═══")
        return {
            "delivered": delivered,
            "failed": failed,
            "by_risk": count_by_risk,
        }


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = FraudAlerterAgent()
    result = agent.run()
    print(json.dumps(result, indent=2))
