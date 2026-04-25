"""
FraudMVP Pipeline — Daily orchestration of the full detection pipeline.

Steps:
1. Ingest new messages (from Redis queue or DB re-process)
2. Run entity linking on new entities
3. Run trend detection (daily mention update)
4. Run scorer on entity clusters
5. Run alerter on high-risk campaigns
6. Update cross-reference cache
7. Log pipeline summary

Usage:
    python -m services.pipeline run           # Full pipeline
    python -m services.pipeline ingest       # Ingest only
    python -m services.pipeline score        # Score only
    python -m services.pipeline trend         # Update trends only
"""

from __future__ import annotations

import json
import logging
import os
import sys
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import Database
from services.cross_reference import CrossReferenceEngine
from services.entity_linker import EntityLinker
from services.trend_detector import TrendDetector
from services.victim_signal import VictimSignalDetector
from services.scam_classifier import ScamClassifier
from services.ingestion import IngestionPipeline

log = logging.getLogger("pipeline")

CONFIG_DIR = Path(__file__).parent.parent / "config"


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay values into base."""
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


class FraudMVPPipeline:
    """
    Daily pipeline runner for FraudMVP.
    
    Orchestrates all Phase 1-3 components in the correct order.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.db = Database()

        # Load pipeline config
        cfg_path = Path(config_path) if config_path else CONFIG_DIR / "pipeline.yaml"
        self.config = self._load_config(cfg_path)

        # Initialize services
        self.ingestion = IngestionPipeline(db=self.db)
        self.trend_detector = TrendDetector(db=self.db, config=self.config)
        self.entity_linker = EntityLinker(db=self.db, config=self.config)

        # Initialize scorer once (expensive: loads BNM/SC data, LLM clients, scoring rules)
        self._scorer = None

        log.info("FraudMVPPipeline initialized")

    def _load_config(self, cfg_path: Path) -> dict:
        """Load pipeline config merged with shared scoring rules."""
        config = self._default_config()

        scoring_rules_path = CONFIG_DIR / "scoring_rules.yaml"
        if scoring_rules_path.exists():
            with open(scoring_rules_path, encoding="utf-8") as f:
                config = _deep_merge(config, yaml.safe_load(f) or {})

        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                config = _deep_merge(config, yaml.safe_load(f) or {})

        return config

    def _default_config(self) -> dict:
        return {
            "pipeline": {
                "ingest_batch_size": 100,
                "score_threshold": 60,
                "alert_threshold": 70,
            },
            "trend": {},
            "entity_relationships": {},
        }

    # ── Full Pipeline ─────────────────────────────────────────────────────

    def run(
        self,
        *,
        since: Optional[str] = None,
        platform: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        reset_derived: bool = False,
    ) -> dict:
        """Run the full pipeline."""
        log.info("═══ FraudMVP Pipeline starting ═══")
        start = datetime.now(timezone.utc)

        results = {
            "started_at": start.isoformat(),
            "ingest": {},
            "link": {},
            "trend": {},
            "score": {},
            "alert": {},
            "summary": {},
        }

        # Step 1: Ingest new messages
        try:
            results["ingest"] = self._run_ingest(
                since=since,
                platform=platform,
                limit=limit,
                dry_run=dry_run,
                reset_derived=reset_derived,
            )
            # Circuit breaker: if ingest fails completely, skip downstream scoring
            if results["ingest"].get("error"):
                log.warning("Ingest had errors — downstream steps may produce stale results")
        except Exception as e:
            log.error(f"Ingest step failed: {e}")
            results["ingest"]["error"] = str(e)
            log.warning("Ingest failed completely — skipping score step to avoid stale alerts")
            results["score"] = {"skipped": True, "reason": "ingest_failed"}

        # Step 2: Entity linking
        try:
            results["link"] = self._run_link()
        except Exception as e:
            log.error(f"Link step failed: {e}")
            results["link"]["error"] = str(e)

        # Step 3: Trend detection
        try:
            results["trend"] = self._run_trend()
        except Exception as e:
            log.error(f"Trend step failed: {e}")
            results["trend"]["error"] = str(e)

        # Step 4: Score (skip if ingest failed completely)
        if dry_run:
            log.info("Skipping score and alert steps in dry-run mode")
            results["score"] = {"skipped": True, "reason": "dry_run"}
            results["alert"] = {"skipped": True, "reason": "dry_run"}
        elif results.get("score", {}).get("skipped"):
            log.warning("Skipping score step — ingest failed")
        else:
            try:
                results["score"] = self._run_score()
            except Exception as e:
                log.error(f"Score step failed: {e}")
                results["score"] = {"error": str(e)}

        # Step 5: Alert
        if not dry_run:
            try:
                results["alert"] = self._run_alert()
            except Exception as e:
                log.error(f"Alert step failed: {e}")
                results["alert"]["error"] = str(e)

        # Summary
        end = datetime.now(timezone.utc)
        elapsed = (end - start).total_seconds()
        results["completed_at"] = end.isoformat()
        results["elapsed_seconds"] = round(elapsed, 2)

        log.info(f"═══ Pipeline complete ({elapsed:.1f}s) ═══")
        return results

    # ── Individual Steps ───────────────────────────────────────────────────

    def _run_ingest(
        self,
        *,
        since: Optional[str] = None,
        platform: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        reset_derived: bool = False,
    ) -> dict:
        """Ingest new messages from DB and wire them through the IngestionPipeline."""
        log.info("Step 1: Ingesting messages...")
        since = since or date.today().isoformat()
        limit = limit or self.config.get("pipeline", {}).get("ingest_batch_size", 100)

        # Re-process messages from today (or last 24h) through Phase 2 services
        result = self.ingestion.ingest_from_db(
            since=since,
            limit=limit,
            platform=platform,
            dry_run=dry_run,
            reset_derived=reset_derived,
        )
        log.info(f"  Ingested: {result.get('messages_processed', 0)} messages, "
                 f"{result.get('relationships_created', 0)} relationships, "
                 f"{result.get('cross_ref_matches', 0)} cross-ref matches")
        return result

    def _run_link(self) -> dict:
        """Run batch entity linking (shared phones, shared domains)."""
        log.info("Step 2: Entity linking...")
        shared_phones = self.entity_linker.link_shared_phones()
        shared_domains = self.entity_linker.link_shared_domains()

        result = {
            "shared_phones": shared_phones,
            "shared_domains": shared_domains,
        }
        log.info(f"  Links: {shared_phones} shared phones, {shared_domains} shared domains")
        return result

    def _run_trend(self) -> dict:
        """Update daily trend detection."""
        log.info("Step 3: Trend detection...")
        trends = self.trend_detector.detect_trends()

        spike_count = sum(1 for t in trends if t.trend_status == "spike")
        rising_count = sum(1 for t in trends if t.trend_status == "rising")
        increasing_count = sum(1 for t in trends if t.trend_status == "increasing")

        result = {
            "total_trends": len(trends),
            "spike": spike_count,
            "rising": rising_count,
            "increasing": increasing_count,
        }
        log.info(f"  Trends: {spike_count} spikes, {rising_count} rising, {increasing_count} increasing")
        return result

    def _run_score(self) -> dict:
        """Run scorer on entity clusters."""
        log.info("Step 4: Scoring campaigns...")
        try:
            # Reuse cached scorer (avoids re-loading BNM/SC data, LLM clients on every call)
            if self._scorer is None:
                from agents.scorer import FraudScorerAgent
                self._scorer = FraudScorerAgent()
            scorer = self._scorer
            scorer_result = scorer.run()
            by_risk = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            by_risk.update(scorer_result.get("by_risk", {}))
            total_campaigns = scorer_result.get("campaigns_formed", 0)

            result = {
                "total_campaigns": total_campaigns,
                **by_risk,
                "alerts_triggered": scorer_result.get("alerts_triggered", 0),
                "entities_scored": scorer_result.get("entities_scored", 0),
                "db_stats": scorer_result.get("db_stats", {}),
            }
            log.info(f"  Campaigns: {total_campaigns} total "
                     f"(critical={by_risk.get('critical', 0)}, "
                     f"high={by_risk.get('high', 0)}, "
                     f"medium={by_risk.get('medium', 0)})")
            return result
        except Exception as e:
            log.error(f"Scorer failed: {e}")
            return {"error": str(e)}

    def _run_alert(self) -> dict:
        """Report alert queue state for manual/worker-driven alert delivery."""
        log.info("Step 5: Alert queue status...")
        try:
            from services.queue_handler import QueueHandler

            queue = QueueHandler()
            pending_alerts = queue.get_queue_length("alerts")
            result = {
                "status": "manual_or_worker_required",
                "pending_alerts": pending_alerts,
                "note": "Alerter is not executed by services.pipeline; run agents.alerter separately or attach a worker.",
            }
            log.info("  Alert queue pending=%s", pending_alerts)
            return result
        except Exception as e:
            log.error(f"Alerter failed: {e}")
            return {"error": str(e)}

    # ── Partial Runs ───────────────────────────────────────────────────────

    def run_ingest_only(
        self,
        *,
        since: Optional[str] = None,
        platform: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        reset_derived: bool = False,
    ) -> dict:
        """Run only the ingestion step."""
        return self._run_ingest(
            since=since,
            platform=platform,
            limit=limit,
            dry_run=dry_run,
            reset_derived=reset_derived,
        )

    def run_score_only(self) -> dict:
        """Run only the scoring step."""
        return self._run_score()

    def run_trend_only(self) -> dict:
        """Run only the trend update step."""
        return self._run_trend()


# ─── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    import argparse
    parser = argparse.ArgumentParser(description="FraudMVP Pipeline Runner")
    parser.add_argument("command", choices=["run", "ingest", "score", "trend"],
                        help="Pipeline command")
    parser.add_argument("--since", help="Replay messages scraped on/after this ISO date or timestamp")
    parser.add_argument("--platform", help="Replay only one platform")
    parser.add_argument("--limit", type=int, help="Replay limit")
    parser.add_argument("--dry-run", action="store_true", help="Preview replay scope without mutating derived tables")
    parser.add_argument("--reset-derived", action="store_true", help="Clear derived tables before replay for deterministic rebuilds")
    args = parser.parse_args()

    pipeline = FraudMVPPipeline()

    if args.command == "run":
        result = pipeline.run(
            since=args.since,
            platform=args.platform,
            limit=args.limit,
            dry_run=args.dry_run,
            reset_derived=args.reset_derived,
        )
    elif args.command == "ingest":
        result = pipeline.run_ingest_only(
            since=args.since,
            platform=args.platform,
            limit=args.limit,
            dry_run=args.dry_run,
            reset_derived=args.reset_derived,
        )
    elif args.command == "score":
        result = pipeline.run_score_only()
    elif args.command == "trend":
        result = pipeline.run_trend_only()

    print(json.dumps(result, indent=2, default=str))
