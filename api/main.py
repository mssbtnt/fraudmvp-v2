"""
FastAPI — REST API for the Fraud MVP.

Endpoints:
  GET  /health              — health check
  GET  /alerts              — list alerts (with optional risk filter)
  GET  /entities            — list entities (with optional type filter)
  GET  /campaigns           — list detected campaigns
  GET  /stats               — high-level system stats
  GET  /sources             — list tracked sources
  POST /collect/trigger     — trigger a collection run
  POST /extract/trigger     — trigger extraction
  POST /score/trigger       — trigger scoring

Requires: pip install fastapi uvicorn
Run with: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.queue_handler import QueueHandler

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("api")

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Fraud MVP API",
    description="Fraud & Scam Intelligence Platform — REST API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    return datetime.utcnow().isoformat()

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
    queue_depth: dict[str, int]
    timestamp: str

class TriggerResponse(BaseModel):
    status: str
    message: str
    timestamp: str

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    """Health check."""
    return HealthResponse(
        status="ok",
        timestamp=dtiso(),
        version="0.1.0",
    )

@app.get("/stats", response_model=StatsResponse, tags=["System"])
async def stats():
    """High-level system statistics."""
    db = get_db()
    queue = get_queue()
    s = db.stats()
    queue_depth = {
        "raw_messages": queue.get_queue_length("raw_messages"),
        "extracted_entities": queue.get_queue_length("extracted_entities"),
        "alerts": queue.get_queue_length("alerts"),
    }
    return StatsResponse(
        entities=s["entities"],
        campaigns=s["campaigns"],
        sources=s["sources"],
        alerts_sent=s["alerts_sent"],
        queue_depth=queue_depth,
        timestamp=dtiso(),
    )

@app.get("/entities", response_model=list[EntityResponse], tags=["Entities"])
async def list_entities(
    type: str | None = Query(None, description="Filter by entity type (phone, bank_account, domain, url)"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
):
    """List tracked entities."""
    db = get_db()
    entities = db.get_recent_entities(etype=type, limit=limit)
    result = []
    for e in entities:
        edges = db.get_edges_for_entity(e["id"])
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
async def list_campaigns(
    risk: str | None = Query(None, description="Filter by risk level (low, medium, high, critical)"),
    limit: int = Query(50, ge=1, le=500),
):
    """List detected scam campaigns."""
    db = get_db()
    campaigns = db.get_recent_campaigns(limit=limit)
    result = []
    for c in campaigns:
        if risk and c.get("risk_level") != risk:
            continue
        import json
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
async def list_alerts(
    risk: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """List sent alerts (campaigns with alert_sent=1)."""
    db = get_db()
    campaigns = db.get_recent_campaigns(limit=limit)
    result = []
    import json
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
async def list_sources():
    """List tracked data sources."""
    db = get_db()
    with db.conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sources ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]

@app.post("/collect/trigger", response_model=TriggerResponse, tags=["Actions"])
async def trigger_collection():
    """
    Trigger a collector run.
    In production this would enqueue a job; for MVP it returns status.
    """
    queue = get_queue()
    q_len = queue.get_queue_length("raw_messages")
    return TriggerResponse(
        status="ok",
        message=f"Collection triggered. Queue depth: {q_len} messages. "
                "Run 'python -m agents.collector' to execute.",
        timestamp=dtiso(),
    )

@app.post("/extract/trigger", response_model=TriggerResponse, tags=["Actions"])
async def trigger_extraction():
    """Trigger an extraction run."""
    queue = get_queue()
    q_len = queue.get_queue_length("raw_messages")
    return TriggerResponse(
        status="ok",
        message=f"Extraction triggered. {q_len} messages in queue. "
                "Run 'python -m agents.extractor' to execute.",
        timestamp=dtiso(),
    )

@app.post("/score/trigger", response_model=TriggerResponse, tags=["Actions"])
async def trigger_scoring():
    """Trigger a scoring run."""
    return TriggerResponse(
        status="ok",
        message="Scoring triggered. Run 'python -m agents.scorer' to execute.",
        timestamp=dtiso(),
    )


# ─── Run directly ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
