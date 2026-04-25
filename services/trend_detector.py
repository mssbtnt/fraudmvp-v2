"""
TrendDetector — Mention spike/rise detection for FraudMVP.

Populates entity_mentions table daily with per-entity mention counts.
Computes 7-day EMA (Exponential Moving Average) for each entity.
Detects spikes (>200% EMA), rises (100-200%), increases (50-100%).

Uses config scoring_rules.yaml trend section:
  spike_boost: 20
  rising_boost: 15
  increasing_boost: 10
  ema_span: 7
  window_days: 30
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from db.database import Database

log = logging.getLogger("trend_detector")


@dataclass
class TrendResult:
    """Result from trend detection."""
    entity_id: int
    entity_value: str
    entity_type: str
    trend_status: str      # "spike", "rising", "increasing", "stable", "declining"
    current_count: int
    ema: float
    percentage_change: float
    boost: int              # Score boost based on trend


class TrendDetector:
    """
    Track entity mention trends and detect spikes.
    
    Daily mention counts are stored in entity_mentions.
    EMA is computed over a configurable window (default: 7 days).
    Trends are detected by comparing current day's count to EMA.
    """

    def __init__(self, db: Database, config: Optional[dict] = None):
        self.db = db
        self.config = config or {}
        self.trend_config = self.config.get("trend", {})
        
        # Trend thresholds
        self.spike_boost = self.trend_config.get("spike_boost", 20)
        self.rising_boost = self.trend_config.get("rising_boost", 15)
        self.increasing_boost = self.trend_config.get("increasing_boost", 10)
        self.ema_span = self.trend_config.get("ema_span", 7)
        self.window_days = self.trend_config.get("window_days", 30)

    # ── Record Mentions ────────────────────────────────────────────────────

    def record_mentions(
        self, mention_date: str, entity_mentions: dict[int, int],
        platform: str = "telegram"
    ) -> int:
        """
        Record daily mention counts for entities.
        
        Args:
            mention_date: Date string (YYYY-MM-DD)
            entity_mentions: {entity_id: mention_count}
            platform: Source platform
        
        Returns:
            Number of rows inserted/updated
        """
        inserted = 0
        
        with self.db.conn() as conn:
            # Batch fetch existing records
            entity_ids = list(entity_mentions.keys())
            placeholders = ",".join("?" * len(entity_ids))
            existing_rows = conn.execute(
                f"SELECT entity_id, mention_count, platforms FROM entity_mentions "
                f"WHERE entity_id IN ({placeholders}) AND date = ?",
                entity_ids + [mention_date],
            ).fetchall()
            
            existing_map = {}  # entity_id → (mention_count, platforms)
            for row in existing_rows:
                existing_map[row["entity_id"]] = (row["mention_count"], row["platforms"])
            
            # Build batch inserts and updates
            inserts = []
            updates = []
            for entity_id, count in entity_mentions.items():
                if entity_id in existing_map:
                    old_count, platforms_str = existing_map[entity_id]
                    new_count = old_count + count
                    try:
                        import json
                        plat_list = json.loads(platforms_str or "[]")
                        if platform not in plat_list:
                            plat_list.append(platform)
                        platforms = json.dumps(plat_list)
                    except (json.JSONDecodeError, TypeError):
                        platforms = f'["{platform}"]'
                    updates.append((new_count, platforms, entity_id, mention_date))
                else:
                    import json
                    inserts.append((entity_id, mention_date, count, json.dumps([platform])))
            
            # Batch execute
            if inserts:
                conn.executemany(
                    "INSERT INTO entity_mentions (entity_id, date, mention_count, platforms) "
                    "VALUES (?, ?, ?, ?)",
                    inserts,
                )
                inserted += len(inserts)
            
            if updates:
                conn.executemany(
                    "UPDATE entity_mentions SET mention_count = ?, platforms = ? "
                    "WHERE entity_id = ? AND date = ?",
                    updates,
                )
                inserted += len(updates)
            
            conn.commit()
        
        if inserted > 0:
            log.info(f"Recorded {inserted} entity mention entries for {mention_date}")
        return inserted

    # ── Compute EMA ─────────────────────────────────────────────────────────

    def get_ema(self, entity_id: int, days: Optional[int] = None) -> float:
        """
        Compute Exponential Moving Average for an entity's mention count.
        
        Args:
            entity_id: Entity ID
            days: Lookback window (default: self.window_days)
        
        Returns:
            EMA value (0.0 if no data)
        """
        days = days or self.window_days
        
        with self.db.conn() as conn:
            rows = conn.execute(
                "SELECT date, mention_count FROM entity_mentions "
                "WHERE entity_id = ? AND date >= date('now', ?) "
                "ORDER BY date ASC",
                (entity_id, f"-{days} days"),
            ).fetchall()
        
        if not rows:
            return 0.0
        
        # Compute EMA
        multiplier = 2.0 / (self.ema_span + 1)
        ema = float(rows[0]["mention_count"])  # Start with first value
        
        for row in rows[1:]:
            count = float(row["mention_count"])
            ema = (count - ema) * multiplier + ema
        
        return ema

    # ── Detect Trends ───────────────────────────────────────────────────────

    def detect_trends(
        self,
        entity_id: Optional[int] = None,
        campaign_type: Optional[str] = None,
    ) -> list[TrendResult]:
        """
        Detect mention trends for entities.
        
        Args:
            entity_id: Specific entity to check (None = all entities)
            campaign_type: Filter by campaign type (None = all)
        
        Returns:
            List of TrendResult objects
        """
        results = []
        
        # Get entities to check
        with self.db.conn() as conn:
            if entity_id:
                entities = conn.execute(
                    "SELECT id, value, type FROM entities WHERE id = ?",
                    (entity_id,),
                ).fetchall()
            elif campaign_type:
                # Get entities linked to campaigns of this type
                entities = conn.execute(
                    "SELECT DISTINCT e.id, e.value, e.type FROM entities e "
                    "JOIN campaigns c ON c.entity_ids LIKE '%' || e.id || '%' "
                    "WHERE c.campaign_type = ?",
                    (campaign_type,),
                ).fetchall()
            else:
                # Get all entities with recent mentions
                entities = conn.execute(
                    "SELECT DISTINCT e.id, e.value, e.type FROM entities e "
                    "INNER JOIN entity_mentions em ON em.entity_id = e.id "
                    "WHERE em.date >= date('now', '-7 days') "
                    "ORDER BY e.id",
                ).fetchall()
        
        for entity in entities:
            eid = entity["id"]
            value = entity["value"]
            etype = entity["type"]
            
            # Get current day's count
            today = date.today().isoformat()
            with self.db.conn() as conn:
                today_row = conn.execute(
                    "SELECT mention_count FROM entity_mentions "
                    "WHERE entity_id = ? AND date = ?",
                    (eid, today),
                ).fetchone()
            
            current_count = today_row["mention_count"] if today_row else 0
            
            # Get EMA
            ema = self.get_ema(eid)
            
            # Determine trend
            if ema <= 0:
                # No baseline — check if there are any mentions at all
                if current_count > 0:
                    trend_status = "increasing"
                    percentage = float("inf")
                    boost = self.increasing_boost
                else:
                    trend_status = "stable"
                    percentage = 0.0
                    boost = 0
            else:
                percentage = ((current_count - ema) / ema) * 100
                
                if percentage >= 200:
                    trend_status = "spike"
                    boost = self.spike_boost
                elif percentage >= 100:
                    trend_status = "rising"
                    boost = self.rising_boost
                elif percentage >= 50:
                    trend_status = "increasing"
                    boost = self.increasing_boost
                elif percentage >= -20:
                    trend_status = "stable"
                    boost = 0
                else:
                    trend_status = "declining"
                    boost = 0
            
            if boost > 0 or current_count > 0:
                results.append(TrendResult(
                    entity_id=eid,
                    entity_value=value,
                    entity_type=etype,
                    trend_status=trend_status,
                    current_count=current_count,
                    ema=round(ema, 2),
                    percentage_change=round(percentage, 1) if percentage != float("inf") else 999.9,
                    boost=boost,
                ))
        
        # Sort by boost descending
        results.sort(key=lambda r: r.boost, reverse=True)
        return results

    # ── Batch Record from Scrape ────────────────────────────────────────────

    def record_from_scrape(self, platform: str = "telegram") -> int:
        """
        Calculate and record mention counts from scraped_messages + entity_edges.
        This is a batch operation that should be run daily.
        
        Args:
            platform: Source platform
        
        Returns:
            Number of entity mention records created/updated
        """
        today = date.today().isoformat()
        
        with self.db.conn() as conn:
            # Count mentions per entity for today
            rows = conn.execute(
                "SELECT ee.entity_id, COUNT(*) as cnt "
                "FROM entity_edges ee "
                "WHERE DATE(ee.timestamp) = ? "
                "GROUP BY ee.entity_id",
                (today,),
            ).fetchall()
        
        if not rows:
            log.info(f"No entity mentions found for {today}")
            return 0
        
        entity_mentions = {row["entity_id"]: row["cnt"] for row in rows}
        return self.record_mentions(today, entity_mentions, platform)