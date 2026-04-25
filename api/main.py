"""
FastAPI — REST API for the Fraud MVP.

Endpoints:
  GET  /health              — health check (no auth, unlimited)
  GET  /stats               — system statistics (60 req/min, auth required)
  GET  /entities            — list entities (60 req/min, auth required)
  GET  /campaigns           — list campaigns (60 req/min, auth required)
  GET  /alerts              — list sent alerts (60 req/min, auth required)
  GET  /sources             — list sources (60 req/min, auth required)
  POST /collect/trigger     — trigger collection (10 req/min, auth required)
  POST /extract/trigger     — trigger extraction (10 req/min, auth required)
  POST /score/trigger       — trigger scoring (10 req/min, auth required)

Auth: X-API-Key header (or ?api_key= query param) required on all endpoints except /health.
Rate limits: 60/min for reads, 10/min for writes (per IP).

Run with: uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --reload
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Security, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyQuery, APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN", "")

# Auto-generate a token if none is set (dev convenience); log it so the operator
# can copy it into .env to persist.
if not API_ACCESS_TOKEN:
    raise RuntimeError(
        "API_ACCESS_TOKEN is not set in environment. "
        "Set it in .env before starting the server."
    )

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("api")
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# ─── Rate Limiter ─────────────────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
)

# Per-endpoint limits
READ_LIMITS  = "60/minute"   # /stats, /entities, /campaigns, /alerts, /sources
WRITE_LIMITS = "10/minute"    # /collect/trigger, /extract/trigger, /score/trigger

# ─── Auth ─────────────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_api_key_query  = APIKeyQuery(name="api_key", auto_error=False)


async def verify_api_key(
    header_key: str | None = Security(_api_key_header),
    query_key:  str | None = Security(_api_key_query),
) -> str:
    """Return the API key if valid; raise 401 otherwise."""
    key = header_key or query_key
    if not key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header or api_key query parameter",
        )
    if not secrets.compare_digest(key, API_ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Fraud MVP API",
    description="Fraud & Scam Intelligence Platform — REST API",
    version="0.2.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_db() -> Database:
    return Database()

def get_queue() -> QueueHandler:
    return QueueHandler()

def dtiso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _query_scalar(conn, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


def _query_optional_timestamp(conn, sql: str, params: tuple = ()) -> str | None:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return None
    value = row[0]
    return str(value) if value else None


def _parse_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _clean_reason_label(raw_reason: str) -> str:
    cleaned = re.sub(r"\s*\(\+\d+\)\s*$", "", raw_reason).strip()
    return cleaned or "Other"


def _build_fresh_data_status(freshness: dict, recent_activity: dict) -> dict:
    freshness_checks = {
        "messages": bool(freshness.get("has_recent_scraped_messages")),
        "entities": bool(freshness.get("has_recent_entities")),
        "campaigns": bool(freshness.get("has_recent_campaigns")),
        "alerts": bool(freshness.get("has_recent_alerts")),
    }
    active_count = sum(1 for is_active in freshness_checks.values() if is_active)
    if active_count >= 3:
        status = "fresh"
        label = "Live"
    elif active_count >= 1:
        status = "degraded"
        label = "Partial"
    else:
        status = "stale"
        label = "Stale"
    return {
        "status": status,
        "label": label,
        "checks": freshness_checks,
        "recent_activity": recent_activity,
    }


def _entity_lookup(conn, entity_ids: list[int]) -> dict[int, dict]:
    if not entity_ids:
        return {}
    placeholders = ",".join("?" * len(entity_ids))
    rows = conn.execute(
        f"""
        SELECT id, value, type, count, first_seen, last_seen
        FROM entities
        WHERE id IN ({placeholders})
        """,
        entity_ids,
    ).fetchall()
    return {row["id"]: dict(row) for row in rows}


def _campaign_evidence_counts(conn, entity_ids: list[int]) -> dict:
    if not entity_ids:
        return {
            "cross_references": 0,
            "victim_signals": 0,
            "relationships": 0,
            "has_supporting_evidence": False,
        }
    placeholders = ",".join("?" * len(entity_ids))
    cross_references = _query_scalar(
        conn,
        f"SELECT COUNT(*) FROM cross_references WHERE entity_id IN ({placeholders})",
        tuple(entity_ids),
    )
    victim_signals = _query_scalar(
        conn,
        f"SELECT COUNT(*) FROM victim_signals WHERE entity_id IN ({placeholders})",
        tuple(entity_ids),
    )
    relationships = _query_scalar(
        conn,
        f"""
        SELECT COUNT(*)
        FROM entity_relationships
        WHERE source_entity_id IN ({placeholders})
           OR target_entity_id IN ({placeholders})
        """,
        tuple(entity_ids + entity_ids),
    )
    return {
        "cross_references": cross_references,
        "victim_signals": victim_signals,
        "relationships": relationships,
        "has_supporting_evidence": any(
            count > 0 for count in (cross_references, victim_signals, relationships)
        ),
    }


def _build_campaign_summary_item(conn, campaign: dict) -> dict:
    entity_ids = [int(entity_id) for entity_id in _parse_json_list(campaign.get("entity_ids"))]
    channel_ids = [str(channel_id) for channel_id in _parse_json_list(campaign.get("channel_ids"))]
    keywords = [str(keyword) for keyword in _parse_json_list(campaign.get("keywords"))]
    entities = _entity_lookup(conn, entity_ids)
    evidence = _campaign_evidence_counts(conn, entity_ids)
    top_entities = [
        {
            "id": entity["id"],
            "value": entity["value"],
            "type": entity["type"],
            "count": entity["count"],
        }
        for entity in sorted(
            entities.values(),
            key=lambda item: (item.get("count", 0), item["value"]),
            reverse=True,
        )[:5]
    ]
    return {
        "id": campaign["id"],
        "score": campaign["score"],
        "risk_level": campaign["risk_level"],
        "campaign_type": campaign["campaign_type"],
        "first_seen": campaign.get("first_seen"),
        "last_seen": campaign.get("last_seen"),
        "entity_count": len(entity_ids),
        "channel_count": len(channel_ids),
        "keywords": keywords,
        "reason_summary": campaign.get("reason") or "No reason recorded.",
        "alert_sent": bool(campaign.get("alert_sent")),
        "alert_sent_at": campaign.get("alert_sent_at"),
        "top_entities": top_entities,
        "evidence": evidence,
    }


def _build_dashboard_summary(db: Database, queue: QueueHandler) -> dict:
    now = datetime.now(timezone.utc)
    cutoff_30d = (now - timedelta(days=30)).date().isoformat()
    snapshot = _build_operational_snapshot(db, queue)
    recent_campaign_rows = db.get_recent_campaigns(limit=8)

    with db.conn() as conn:
        risk_distribution = [
            {"label": row["risk_level"], "value": row["count"]}
            for row in conn.execute(
                """
                SELECT risk_level, COUNT(*) AS count
                FROM campaigns
                GROUP BY risk_level
                ORDER BY CASE risk_level
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END
                """
            ).fetchall()
        ]
        campaign_trend = [
            {"date": row["day"], "campaigns": row["campaigns"]}
            for row in conn.execute(
                """
                SELECT DATE(last_seen) AS day, COUNT(*) AS campaigns
                FROM campaigns
                WHERE DATE(last_seen) >= ?
                GROUP BY DATE(last_seen)
                ORDER BY day ASC
                """,
                (cutoff_30d,),
            ).fetchall()
        ]
        scam_type_distribution = [
            {"label": row["campaign_type"], "value": row["count"]}
            for row in conn.execute(
                """
                SELECT campaign_type, COUNT(*) AS count
                FROM campaigns
                GROUP BY campaign_type
                ORDER BY count DESC, campaign_type ASC
                """
            ).fetchall()
        ]
        top_reused_entities = [
            {
                "id": row["id"],
                "value": row["value"],
                "type": row["type"],
                "count": row["count"],
                "last_seen": row["last_seen"],
            }
            for row in conn.execute(
                """
                SELECT id, value, type, count, last_seen
                FROM entities
                ORDER BY count DESC, last_seen DESC
                LIMIT 10
                """
            ).fetchall()
        ]
        active_channels = [
            {
                "channel": row["channel"],
                "platform": row["platform"],
                "messages": row["messages"],
            }
            for row in conn.execute(
                """
                SELECT channel, platform, COUNT(*) AS messages
                FROM scraped_messages
                WHERE DATE(scraped_at) >= ?
                GROUP BY channel, platform
                ORDER BY messages DESC, channel ASC
                LIMIT 8
                """,
                (cutoff_30d,),
            ).fetchall()
        ]
        active_platforms = [
            {
                "platform": row["platform"],
                "messages": row["messages"],
                "channels": row["channels"],
            }
            for row in conn.execute(
                """
                SELECT platform, COUNT(*) AS messages, COUNT(DISTINCT channel) AS channels
                FROM scraped_messages
                WHERE DATE(scraped_at) >= ?
                GROUP BY platform
                ORDER BY messages DESC, platform ASC
                """,
                (cutoff_30d,),
            ).fetchall()
        ]
        cross_reference_matches = _query_scalar(conn, "SELECT COUNT(*) FROM cross_references")
        victim_signal_detections = _query_scalar(conn, "SELECT COUNT(*) FROM victim_signals")
        entity_relationship_count = _query_scalar(conn, "SELECT COUNT(*) FROM entity_relationships")
        linked_entity_depth_avg = conn.execute(
            "SELECT COALESCE(AVG(json_array_length(entity_ids)), 0) AS avg_depth FROM campaigns"
        ).fetchone()["avg_depth"]
        supporting_campaigns = _query_scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM campaigns c
            WHERE EXISTS (
                SELECT 1
                FROM json_each(c.entity_ids) entity_ids
                JOIN cross_references cr ON cr.entity_id = entity_ids.value
            )
            OR EXISTS (
                SELECT 1
                FROM json_each(c.entity_ids) entity_ids
                JOIN victim_signals vs ON vs.entity_id = entity_ids.value
            )
            OR EXISTS (
                SELECT 1
                FROM json_each(c.entity_ids) entity_ids
                JOIN entity_relationships er
                  ON er.source_entity_id = entity_ids.value
                  OR er.target_entity_id = entity_ids.value
            )
            """
        )
        total_campaigns = max(len(recent_campaign_rows), _query_scalar(conn, "SELECT COUNT(*) FROM campaigns"))
        supporting_evidence_pct = (
            round((supporting_campaigns / total_campaigns) * 100, 1) if total_campaigns else 0.0
        )
        cross_reference_sources = [
            {"label": row["source_db"], "value": row["matches"]}
            for row in conn.execute(
                """
                SELECT source_db, COUNT(*) AS matches
                FROM cross_references
                GROUP BY source_db
                ORDER BY matches DESC, source_db ASC
                """
            ).fetchall()
        ]
        victim_signal_breakdown = [
            {"label": row["signal_type"], "value": row["detections"]}
            for row in conn.execute(
                """
                SELECT signal_type, COUNT(*) AS detections
                FROM victim_signals
                GROUP BY signal_type
                ORDER BY detections DESC, signal_type ASC
                """
            ).fetchall()
        ]

        reason_counts: dict[str, int] = {}
        for row in conn.execute(
            "SELECT reason FROM campaigns WHERE reason IS NOT NULL AND TRIM(reason) != ''"
        ).fetchall():
            segments = [segment.strip() for segment in row["reason"].split(";") if segment.strip()]
            for segment in segments:
                label = _clean_reason_label(segment)
                reason_counts[label] = reason_counts.get(label, 0) + 1
        alert_reason_breakdown = [
            {"label": label, "value": count}
            for label, count in sorted(
                reason_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:8]
        ]

        recent_campaigns = [
            _build_campaign_summary_item(conn, campaign) for campaign in recent_campaign_rows
        ]
        recent_alert_rows = conn.execute(
            """
            SELECT *
            FROM alert_log
            ORDER BY sent_at DESC
            LIMIT 8
            """
        ).fetchall()
        recent_alerts = []
        for row in recent_alert_rows:
            campaign_row = conn.execute(
                "SELECT * FROM campaigns WHERE id = ?",
                (row["campaign_id"],),
            ).fetchone()
            recent_alerts.append(
                {
                    "id": row["id"],
                    "campaign_id": row["campaign_id"],
                    "alert_level": row["alert_level"],
                    "status": row["status"],
                    "sent_at": row["sent_at"],
                    "message_preview": (row["message"] or "").strip()[:220],
                    "campaign_type": campaign_row["campaign_type"] if campaign_row else None,
                    "risk_level": campaign_row["risk_level"] if campaign_row else row["alert_level"],
                    "score": campaign_row["score"] if campaign_row else None,
                }
            )

    freshness = snapshot["freshness"]
    recent_activity = snapshot["recent_activity"]
    operations = {
        "last_successful_pipeline_run_at": freshness.get("latest_pipeline_log_at")
        or freshness.get("latest_campaign_seen_at")
        or freshness.get("latest_entity_seen_at")
        or freshness.get("latest_scraped_message_at"),
        "next_scheduled_run_at": None,
        "next_scheduled_run_label": "Managed by external scheduler",
        "fresh_data_status": _build_fresh_data_status(freshness, recent_activity),
        "queue_depth": snapshot["queue_depth"],
        "queue_backend": snapshot["queue_backend"],
        "messages_ingested_24h": recent_activity["scraped_messages_24h"],
        "entities_extracted_24h": recent_activity["entities_24h"],
        "campaigns_formed_24h": recent_activity["campaigns_24h"],
        "alerts_sent_24h": recent_activity["alerts_24h"],
        "latest_timestamps": freshness,
        "runtime_model": snapshot["runtime_model"],
    }

    return {
        "generated_at": dtiso(),
        "operations": operations,
        "intelligence": {
            "risk_distribution": risk_distribution,
            "campaign_trend": campaign_trend,
            "scam_type_distribution": scam_type_distribution,
            "top_active_campaigns": recent_campaigns[:5],
            "top_reused_entities": top_reused_entities,
            "active_channels": active_channels,
            "active_platforms": active_platforms,
        },
        "evidence": {
            "cross_reference_matches": cross_reference_matches,
            "victim_signal_detections": victim_signal_detections,
            "entity_relationship_count": entity_relationship_count,
            "linked_entity_depth_avg": round(float(linked_entity_depth_avg or 0), 1),
            "alert_reason_breakdown": alert_reason_breakdown,
            "campaigns_with_supporting_evidence_pct": supporting_evidence_pct,
            "cross_reference_sources": cross_reference_sources,
            "victim_signal_breakdown": victim_signal_breakdown,
        },
        "recent_campaigns": recent_campaigns,
        "recent_alerts": recent_alerts,
    }


def _build_campaign_drilldown(db: Database, campaign_id: int) -> dict | None:
    with db.conn() as conn:
        row = conn.execute(
            "SELECT * FROM campaigns WHERE id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        campaign = dict(row)
        entity_ids = [int(entity_id) for entity_id in _parse_json_list(campaign.get("entity_ids"))]
        channel_ids = [str(channel_id) for channel_id in _parse_json_list(campaign.get("channel_ids"))]
        entities = _entity_lookup(conn, entity_ids)
        evidence = _campaign_evidence_counts(conn, entity_ids)
        cross_reference_rows = []
        victim_signal_rows = []
        relationship_rows = []
        if entity_ids:
            placeholders = ",".join("?" * len(entity_ids))
            cross_reference_rows = [
                dict(record)
                for record in conn.execute(
                    f"""
                    SELECT cr.entity_id, e.value, e.type, cr.source_db, cr.match_confidence, cr.status, cr.checked_at
                    FROM cross_references cr
                    JOIN entities e ON e.id = cr.entity_id
                    WHERE cr.entity_id IN ({placeholders})
                    ORDER BY cr.checked_at DESC, cr.id DESC
                    LIMIT 20
                    """,
                    tuple(entity_ids),
                ).fetchall()
            ]
            victim_signal_rows = [
                dict(record)
                for record in conn.execute(
                    f"""
                    SELECT vs.entity_id, e.value, e.type, vs.signal_type, vs.extracted_text, vs.extracted_amount, vs.detected_at
                    FROM victim_signals vs
                    JOIN entities e ON e.id = vs.entity_id
                    WHERE vs.entity_id IN ({placeholders})
                    ORDER BY vs.detected_at DESC, vs.id DESC
                    LIMIT 20
                    """,
                    tuple(entity_ids),
                ).fetchall()
            ]
            relationship_rows = [
                dict(record)
                for record in conn.execute(
                    f"""
                    SELECT er.relationship_type, er.confidence, er.count, er.last_seen,
                           src.id AS source_entity_id, src.value AS source_value, src.type AS source_type,
                           tgt.id AS target_entity_id, tgt.value AS target_value, tgt.type AS target_type
                    FROM entity_relationships er
                    JOIN entities src ON src.id = er.source_entity_id
                    JOIN entities tgt ON tgt.id = er.target_entity_id
                    WHERE er.source_entity_id IN ({placeholders})
                       OR er.target_entity_id IN ({placeholders})
                    ORDER BY er.count DESC, er.last_seen DESC
                    LIMIT 20
                    """,
                    tuple(entity_ids + entity_ids),
                ).fetchall()
            ]
        recent_alert = conn.execute(
            """
            SELECT id, alert_level, status, sent_at, message
            FROM alert_log
            WHERE campaign_id = ?
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        return {
            "id": campaign["id"],
            "score": campaign["score"],
            "risk_level": campaign["risk_level"],
            "campaign_type": campaign["campaign_type"],
            "keywords": _parse_json_list(campaign.get("keywords")),
            "reason": campaign.get("reason") or "No reason recorded.",
            "first_seen": campaign.get("first_seen"),
            "last_seen": campaign.get("last_seen"),
            "alert_sent": bool(campaign.get("alert_sent")),
            "alert_sent_at": campaign.get("alert_sent_at"),
            "channel_ids": channel_ids,
            "entities": [
                {
                    "id": entity["id"],
                    "value": entity["value"],
                    "type": entity["type"],
                    "count": entity["count"],
                    "first_seen": entity["first_seen"],
                    "last_seen": entity["last_seen"],
                }
                for entity in sorted(
                    entities.values(),
                    key=lambda item: (item.get("count", 0), item["value"]),
                    reverse=True,
                )
            ],
            "metrics": {
                "entity_count": len(entity_ids),
                "channel_count": len(channel_ids),
                **evidence,
            },
            "cross_references": cross_reference_rows,
            "victim_signals": victim_signal_rows,
            "relationships": relationship_rows,
            "recent_alert": dict(recent_alert) if recent_alert else None,
        }


def _build_operational_snapshot(db: Database, queue: QueueHandler) -> dict:
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    log_path = Path(__file__).parent.parent / "logs" / "pipeline.log"

    with db.conn() as conn:
        base_stats = db.stats()
        scraped_messages = _query_scalar(conn, "SELECT COUNT(*) FROM scraped_messages")
        recent_activity = {
            "scraped_messages_24h": _query_scalar(
                conn,
                "SELECT COUNT(*) FROM scraped_messages WHERE scraped_at >= ?",
                (cutoff_24h,),
            ),
            "entities_24h": _query_scalar(
                conn,
                "SELECT COUNT(*) FROM entities WHERE last_seen >= ?",
                (cutoff_24h,),
            ),
            "campaigns_24h": _query_scalar(
                conn,
                "SELECT COUNT(*) FROM campaigns WHERE last_seen >= ?",
                (cutoff_24h,),
            ),
            "alerts_24h": _query_scalar(
                conn,
                "SELECT COUNT(*) FROM campaigns WHERE alert_sent=1 AND alert_sent_at >= ?",
                (cutoff_24h,),
            ),
        }
        freshness = {
            "latest_scraped_message_at": _query_optional_timestamp(
                conn,
                "SELECT MAX(scraped_at) FROM scraped_messages",
            ),
            "latest_entity_seen_at": _query_optional_timestamp(
                conn,
                "SELECT MAX(last_seen) FROM entities",
            ),
            "latest_campaign_seen_at": _query_optional_timestamp(
                conn,
                "SELECT MAX(last_seen) FROM campaigns",
            ),
            "latest_alert_sent_at": _query_optional_timestamp(
                conn,
                "SELECT MAX(alert_sent_at) FROM campaigns WHERE alert_sent=1",
            ),
            "latest_pipeline_log_at": (
                datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc).isoformat()
                if log_path.exists()
                else None
            ),
            "has_recent_scraped_messages": recent_activity["scraped_messages_24h"] > 0,
            "has_recent_entities": recent_activity["entities_24h"] > 0,
            "has_recent_campaigns": recent_activity["campaigns_24h"] > 0,
            "has_recent_alerts": recent_activity["alerts_24h"] > 0,
        }

    queue_depth = {
        "raw_messages": queue.get_queue_length("raw_messages"),
        "extracted_entities": queue.get_queue_length("extracted_entities"),
        "alerts": queue.get_queue_length("alerts"),
    }

    runtime_model = {
        "scheduler": "external_systemd_timer",
        "api_triggers_background_jobs": False,
        "supported_execution": [
            "./fraud-mvp-daily-pipeline.sh",
            "./fraud-mvp-reddit-sidecar.sh",
            "python3 -m agents.reddit_collector --promote-qualified",
            "python3 -m services.pipeline ingest",
        ],
        "notes": [
            "API trigger endpoints are informational only.",
            "Background execution is managed outside FastAPI.",
            "No recent data can mean collector inactivity, upstream auth issues, or a broken scheduler.",
        ],
    }

    return {
        "base_stats": base_stats,
        "scraped_messages": scraped_messages,
        "queue_depth": queue_depth,
        "queue_backend": queue.status(),
        "recent_activity": recent_activity,
        "freshness": freshness,
        "runtime_model": runtime_model,
    }

# ─── Response models ──────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str

class EntityResponse(BaseModel):
    id: int
    value: str
    type: str
    count: int
    first_seen: str
    last_seen: str
    channels: list[str]

class AlertResponse(BaseModel):
    id: int
    risk_level: str
    campaign_type: str
    score: int
    entity_count: int
    channel_count: int
    reason: str
    keywords: list[str]
    first_seen: str
    last_seen: str
    alert_sent: bool

class CampaignResponse(BaseModel):
    id: int
    score: int
    risk_level: str
    campaign_type: str
    entity_ids: list[int]
    channel_ids: list[str]
    keywords: list[str]
    reason: str
    first_seen: str
    last_seen: str
    alert_sent: bool

class StatsResponse(BaseModel):
    entities: int
    campaigns: int
    sources: int
    alerts_sent: int
    scraped_messages: int
    queue_depth: dict[str, int]
    queue_backend: dict
    recent_activity: dict
    freshness: dict
    timestamp: str

class TriggerResponse(BaseModel):
    status: str
    message: str
    timestamp: str


class RuntimeModel(BaseModel):
    scheduler: str
    api_triggers_background_jobs: bool
    supported_execution: list[str]
    notes: list[str]


class QueueStatus(BaseModel):
    available: bool
    redis_url: str
    mode: str
    error: str | None = None


class RecentActivity(BaseModel):
    scraped_messages_24h: int
    entities_24h: int
    campaigns_24h: int
    alerts_24h: int


class FreshnessStatus(BaseModel):
    latest_scraped_message_at: str | None = None
    latest_entity_seen_at: str | None = None
    latest_campaign_seen_at: str | None = None
    latest_alert_sent_at: str | None = None
    latest_pipeline_log_at: str | None = None
    has_recent_scraped_messages: bool
    has_recent_entities: bool
    has_recent_campaigns: bool
    has_recent_alerts: bool


class CollectorHealth(BaseModel):
    queue_backend: QueueStatus
    recent_activity: RecentActivity
    freshness: FreshnessStatus
    runtime_model: RuntimeModel
    timestamp: str

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    """Health check. No auth required, unlimited."""
    return HealthResponse(status="ok", timestamp=dtiso(), version="0.2.0")


@app.get("/stats", response_model=StatsResponse, tags=["System"])
@limiter.limit(READ_LIMITS)
async def stats(request: Request, _auth: str = Security(verify_api_key)):
    """System statistics. Auth required."""
    db = get_db()
    queue = get_queue()
    snapshot = _build_operational_snapshot(db, queue)
    s = snapshot["base_stats"]
    return StatsResponse(
        entities=s["entities"],
        campaigns=s["campaigns"],
        sources=s["sources"],
        alerts_sent=s["alerts_sent"],
        scraped_messages=snapshot["scraped_messages"],
        queue_depth=snapshot["queue_depth"],
        queue_backend=snapshot["queue_backend"],
        recent_activity=snapshot["recent_activity"],
        freshness=snapshot["freshness"],
        timestamp=dtiso(),
    )


@app.get("/status", response_model=CollectorHealth, tags=["System"])
@limiter.limit(READ_LIMITS)
async def status(request: Request, _auth: str = Security(verify_api_key)):
    """
    Operator-focused runtime status.

    Answers:
    - Is Redis available?
    - Has recent data arrived?
    - Have entities/campaigns/alerts updated recently?
    - Does this API launch background jobs? (No)
    """
    db = get_db()
    queue = get_queue()
    snapshot = _build_operational_snapshot(db, queue)
    return CollectorHealth(
        queue_backend=QueueStatus(**snapshot["queue_backend"]),
        recent_activity=RecentActivity(**snapshot["recent_activity"]),
        freshness=FreshnessStatus(**snapshot["freshness"]),
        runtime_model=RuntimeModel(**snapshot["runtime_model"]),
        timestamp=dtiso(),
    )


@app.get("/dashboard_api/summary", tags=["Dashboard"])
@limiter.limit(READ_LIMITS)
async def dashboard_summary(request: Request):
    """Management dashboard summary built from existing pipeline tables."""
    db = get_db()
    queue = get_queue()
    return _build_dashboard_summary(db, queue)


@app.get("/dashboard_api/campaigns/{campaign_id}", tags=["Dashboard"])
@limiter.limit(READ_LIMITS)
async def dashboard_campaign_detail(
    campaign_id: int,
    request: Request,
):
    """Detailed campaign evidence view for dashboard drilldown."""
    db = get_db()
    detail = _build_campaign_drilldown(db, campaign_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return detail


@app.get("/entities", response_model=list[EntityResponse], tags=["Entities"])
@limiter.limit(READ_LIMITS)
async def list_entities(
    request: Request,
    _auth: str = Security(verify_api_key),
    type: str | None = Query(None, description="Filter by type (phone, bank_account, domain, url)"),
    limit: int = Query(50, ge=1, le=500),
):
    """List tracked entities. Auth required."""
    db = get_db()
    entities = db.get_recent_entities(etype=type, limit=limit)
    if not entities:
        return []
    entity_ids = [e["id"] for e in entities]
    edges_map = db.get_edges_for_entities(entity_ids)
    result = []
    for e in entities:
        edges = edges_map.get(e["id"], [])
        channels = list({edge["channel"] for edge in edges})
        result.append(EntityResponse(
            id=e["id"],
            value=e["value"],
            type=e["type"],
            count=e["count"],
            first_seen=e["first_seen"],
            last_seen=e["last_seen"],
            channels=channels,
        ))
    return result


@app.get("/campaigns", response_model=list[CampaignResponse], tags=["Campaigns"])
@limiter.limit(READ_LIMITS)
async def list_campaigns(
    request: Request,
    _auth: str = Security(verify_api_key),
    risk: str | None = Query(None, description="Filter by risk (low, medium, high, critical)"),
    limit: int = Query(50, ge=1, le=500),
):
    """List detected scam campaigns. Auth required."""
    db = get_db()
    campaigns = db.get_recent_campaigns(limit=limit)
    result = []
    for c in campaigns:
        if risk and c.get("risk_level") != risk:
            continue
        result.append(CampaignResponse(
            id=c["id"],
            score=c["score"],
            risk_level=c["risk_level"],
            campaign_type=c["campaign_type"],
            entity_ids=json.loads(c.get("entity_ids", "[]")),
            channel_ids=json.loads(c.get("channel_ids", "[]")),
            keywords=json.loads(c.get("keywords", "[]")),
            reason=c.get("reason", ""),
            first_seen=c.get("first_seen", ""),
            last_seen=c.get("last_seen", ""),
            alert_sent=bool(c.get("alert_sent")),
        ))
    return result


@app.get("/alerts", response_model=list[AlertResponse], tags=["Alerts"])
@limiter.limit(READ_LIMITS)
async def list_alerts(
    request: Request,
    _auth: str = Security(verify_api_key),
    risk: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """List sent alerts (campaigns with alert_sent=1). Auth required."""
    db = get_db()
    campaigns = db.get_recent_campaigns(limit=limit)
    result = []
    for c in campaigns:
        if not c.get("alert_sent"):
            continue
        if risk and c.get("risk_level") != risk:
            continue
        result.append(AlertResponse(
            id=c["id"],
            risk_level=c["risk_level"],
            campaign_type=c["campaign_type"],
            score=c["score"],
            entity_count=len(json.loads(c.get("entity_ids", "[]"))),
            channel_count=len(json.loads(c.get("channel_ids", "[]"))),
            reason=c.get("reason", ""),
            keywords=json.loads(c.get("keywords", "[]")),
            first_seen=c.get("first_seen", ""),
            last_seen=c.get("last_seen", ""),
            alert_sent=bool(c.get("alert_sent")),
        ))
    return result


@app.get("/sources", tags=["Sources"])
@limiter.limit(READ_LIMITS)
async def list_sources(request: Request, _auth: str = Security(verify_api_key)):
    """List tracked data sources. Auth required."""
    db = get_db()
    with db.conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sources ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/collect/trigger", response_model=TriggerResponse, tags=["Actions"])
@limiter.limit(WRITE_LIMITS)
async def trigger_collection(request: Request, _auth: str = Security(verify_api_key)):
    """
    Manual-only collection endpoint.
    This API does not enqueue background jobs; it reports the current queue
    state and the command the operator should run.
    """
    queue = get_queue()
    q_len = queue.get_queue_length("raw_messages")
    return TriggerResponse(
        status="manual_only",
        message=(
            f"No background collector is wired to this API. "
            f"Current raw_messages depth: {q_len}. "
            f"Background execution is managed by systemd/user services. "
            f"Run './fraud-mvp-daily-pipeline.sh' manually if needed, "
            f"or check '/status' for recent collector activity."
        ),
        timestamp=dtiso(),
    )


@app.post("/extract/trigger", response_model=TriggerResponse, tags=["Actions"])
@limiter.limit(WRITE_LIMITS)
async def trigger_extraction(request: Request, _auth: str = Security(verify_api_key)):
    """Manual-only extraction endpoint. Auth required."""
    queue = get_queue()
    q_len = queue.get_queue_length("raw_messages")
    return TriggerResponse(
        status="manual_only",
        message=(
            f"No background extractor is wired to this API. "
            f"Current raw_messages depth: {q_len}. "
            f"Run './fraud-mvp-daily-pipeline.sh' manually if needed, "
            f"or check '/status' for queue freshness and recent extraction activity."
        ),
        timestamp=dtiso(),
    )


@app.post("/score/trigger", response_model=TriggerResponse, tags=["Actions"])
@limiter.limit(WRITE_LIMITS)
async def trigger_scoring(request: Request, _auth: str = Security(verify_api_key)):
    """Manual-only scoring endpoint. Auth required."""
    return TriggerResponse(
        status="manual_only",
        message=(
            "No background scorer is wired to this API. "
            "Run './fraud-mvp-daily-pipeline.sh' manually if needed, "
            "or check '/status' for recent campaigns and alerts."
        ),
        timestamp=dtiso(),
    )


if FRONTEND_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIR, html=True), name="dashboard")


# ─── Run directly ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
