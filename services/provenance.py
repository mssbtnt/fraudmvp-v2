"""
Helpers for classifying and backfilling entity provenance.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from services.raw_message import RawMessage, stable_message_hash


REFERENCE_SOURCES = {
    "bnm_fca_list": {
        "channel": "BNM Financial Consumer Alert",
        "platform": "opensanctions",
        "label": "BNM FCA",
    },
    "sc_investor_alert_list": {
        "channel": "SC Investor Alert",
        "platform": "opensanctions",
        "label": "SC Investor Alert",
    },
}


def parse_entity_metadata(entity: dict) -> dict:
    raw = entity.get("metadata")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def classify_entity_provenance(entity: dict) -> dict:
    """Classify an entity as reference import, message-backed, or unknown."""
    metadata = parse_entity_metadata(entity)
    source = metadata.get("source")
    platform = metadata.get("platform")
    channel = metadata.get("channel") or metadata.get("source_channel")

    if source in REFERENCE_SOURCES:
        info = REFERENCE_SOURCES[source]
        return {
            "provenance_class": "reference_import",
            "platform": info["platform"],
            "channel": info["channel"],
            "source": source,
            "label": info["label"],
            "timestamp": metadata.get("date_added_to_fca") or metadata.get("date_added"),
        }

    if platform and channel:
        return {
            "provenance_class": "message_backed",
            "platform": platform,
            "channel": channel,
            "source": source or platform,
            "label": channel,
            "timestamp": metadata.get("first_seen") or metadata.get("last_seen"),
        }

    return {
        "provenance_class": "unknown_provenance",
        "platform": None,
        "channel": None,
        "source": source or platform or "unknown",
        "label": "unknown",
        "timestamp": None,
    }


def normalize_provenance_timestamp(value: str | None) -> str:
    """Normalize imported provenance dates to ISO-8601 where possible."""
    if not value:
        return datetime.now(timezone.utc).isoformat()

    candidates = [value]
    if value.endswith("Z"):
        candidates.append(value.replace("Z", "+00:00"))

    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate).isoformat()
        except ValueError:
            pass

    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue

    return datetime.now(timezone.utc).isoformat()


def build_backfill_raw_message(entity: dict) -> RawMessage | None:
    """Build a synthetic but explicit raw message for provenance backfill."""
    metadata = parse_entity_metadata(entity)
    provenance = classify_entity_provenance(entity)
    if provenance["provenance_class"] == "unknown_provenance":
        return None

    entity_type = entity.get("type", "unknown")
    entity_value = entity.get("value", "")
    title = metadata.get("original_name") or metadata.get("parent_entity") or entity_value
    channel = provenance["channel"] or "historical_backfill"
    platform = provenance["platform"] or "unknown"
    timestamp = normalize_provenance_timestamp(provenance["timestamp"])

    if provenance["provenance_class"] == "reference_import":
        text = (
            f"[{provenance['label']}] Historical alert-list entity: "
            f"{title} | type={entity_type} | value={entity_value}"
        )
    else:
        text = (
            f"[{platform}] Historical observed entity from {channel}: "
            f"type={entity_type} | value={entity_value}"
        )

    message_hash = stable_message_hash(
        text,
        fallback_seed=f"backfill:{entity.get('id')}:{platform}:{channel}:{entity_value}",
    )

    raw_json = json.dumps(
        {
            "entity_id": entity.get("id"),
            "entity_type": entity_type,
            "entity_value": entity_value,
            "metadata": metadata,
            "provenance": provenance,
            "synthetic": True,
        },
        ensure_ascii=False,
    )

    return RawMessage(
        platform=platform,
        channel=channel,
        channel_id=str(entity.get("id")),
        sender_id=None,
        text=text,
        member_count=None,
        timestamp=timestamp,
        message_hash=message_hash,
        raw_json=raw_json,
        message_id=f"backfill:{entity.get('id')}",
    )
