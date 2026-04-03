"""
FraudAlerterAgent — Campaign alert formatter and Telegram delivery.

Responsibilities:
- Consumes campaigns from Redis alerts queue
- Formats structured alert messages (emoji + markdown)
- Delivers alerts via Telegram bot (or demo log)
- Logs alert delivery status to DB
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN", "")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("alerter")

# ─── Alert formatters ─────────────────────────────────────────────────────────

RISK_EMOJI = {
    "low": "📝",
    "medium": "⚠️",
    "high": "🚨",
    "critical": "🔥",
}

CAMPAIGN_TYPE_EMOJI = {
    "investment": "💰",
    "job_task": "💼",
    "aid_gov": "🏛️",
    "phishing": "🎣",
    "unknown": "❓",
}

CAMPAIGN_TYPE_LABEL = {
    "investment": "Investment Scam",
    "job_task": "Job / Task Scam",
    "aid_gov": "Aid / Gov Impersonation",
    "phishing": "Phishing / Account Hijack",
    "unknown": "Unknown Scam",
}


def format_alert(campaign: dict) -> str:
    """
    Format a campaign dict into a readable Telegram message.
    Uses HTML-style markdown for Telegram.
    """
    risk = campaign.get("risk_level", "unknown")
    ctype = campaign.get("campaign_type", "unknown")
    score = campaign.get("score", 0)
    emoji = RISK_EMOJI.get(risk, "⚠️")
    type_emoji = CAMPAIGN_TYPE_EMOJI.get(ctype, "❓")
    type_label = CAMPAIGN_TYPE_LABEL.get(ctype, ctype)

    # Format entities
    entity_ids = campaign.get("entity_ids", [])
    channel_ids = campaign.get("channel_ids", [])
    keywords = campaign.get("keywords", [])[:5]

    # Risk badge
    risk_badge = f"{risk.upper()}" if risk != "log_only" else "LOG"

    # Timestamp
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    # Build the message
    lines = [
        f"{emoji} SCAM CAMPAIGN ALERT",
        "",
        f"Risk Score: {score} ({risk_badge})",
        f"Type: {type_emoji} {type_label}",
        "",
        "📊 Campaign Stats:",
        f"  • Entities tracked: {campaign.get('entity_count', len(entity_ids))}",
        f"  • Channels affected: {campaign.get('channel_count', len(channel_ids))}",
        f"  • First seen: {campaign.get('first_seen', 'N/A')[:10]}",
        f"  • Last seen: {campaign.get('last_seen', 'N/A')[:10]}",
    ]

    if keywords:
        lines.append("")
        lines.append("🔑 Keywords:")
        for kw in keywords:
            lines.append(f"  • {kw}")

    if channel_ids:
        lines.append("")
        lines.append("📡 Channels:")
        for ch in channel_ids[:5]:
            lines.append(f"  • {ch}")
        if len(channel_ids) > 5:
            lines.append(f"  • ...and {len(channel_ids) - 5} more")

    reason = campaign.get("reason", "")
    if reason:
        lines.append("")
        lines.append(f"📋 Reason: {reason}")

    script_sample = campaign.get("script_sample", "")
    if script_sample:
        lines.append("")
        lines.append(f"📄 Sample: {script_sample[:150]}...")

    lines.append("")
    lines.append(f"_Detected: {now}_")

    return "\n".join(lines)


def format_summary(count_by_risk: dict) -> str:
    """Format an end-of-day or batch summary."""
    lines = [
        "📊 Campaign Detection Summary",
        "",
    ]
    for risk in ["critical", "high", "medium", "low"]:
        count = count_by_risk.get(risk, 0)
        emoji = RISK_EMOJI.get(risk, "•")
        lines.append(f"  {emoji} {risk.upper()}: {count}")
    total = sum(count_by_risk.values())
    lines.append(f"\nTotal campaigns: {total}")
    return "\n".join(lines)


# ─── Telegram delivery ────────────────────────────────────────────────────────

def send_telegram_message(bot_token: str, chat_id: str, text: str) -> dict:
    """Send a message via Telegram Bot API."""
    import httpx
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"error": str(e)}


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

        log.info(f"FraudAlerterAgent initialized (demo={self.demo_mode})")

    def process_alert(self, campaign_json: str) -> bool:
        """Process a single campaign alert. Returns True if delivered."""
        try:
            campaign = json.loads(campaign_json)
        except json.JSONDecodeError:
            log.error(f"Invalid JSON in alerts queue: {campaign_json[:80]}")
            return False

        formatted = format_alert(campaign)

        if self.demo_mode:
            log.info(f"[DEMO ALERT] {formatted}")
            return True

        # Live delivery
        if not ALERT_BOT_TOKEN or not ALERT_CHAT_ID:
            log.warning("No ALERT_BOT_TOKEN or ALERT_CHAT_ID — logging only")
            log.info(f"[ALERT] {formatted}")
            return True

        result = send_telegram_message(ALERT_BOT_TOKEN, ALERT_CHAT_ID, formatted)
        if "error" in result:
            log.error(f"Telegram delivery failed: {result['error']}")
            return False

        log.info(f"Telegram alert sent: campaign_id={campaign.get('db_id')}")
        return True

    def run(self, batch_size: int = BATCH_SIZE, max_batches: int = 100) -> dict:
        """
        Process alerts from the queue.
        Runs up to max_batches iterations.
        """
        log.info("═══ FraudAlerterAgent starting ═══")

        delivered = 0
        failed = 0
        count_by_risk: dict[str, int] = {}

        for _ in range(max_batches):
            raw = self.queue.pop_from_queue("alerts", timeout=5)
            if raw is None:
                log.info("Alerts queue empty — stopping")
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

        # Log summary
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
