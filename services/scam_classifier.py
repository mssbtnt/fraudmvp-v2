"""
ScamClassifier — 3-tier scam type classification for FraudMVP.

Tier 1 (Keyword): Fast regex-based classification using keyword patterns.
Tier 2 (LLM): Gemma 4 analysis when keyword confidence < 0.8.
Tier 3 (Cross-Reference): Override with BNM/SC entity type when matched.

Returns: (campaign_type, confidence, tier_used)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from services.campaign_types import normalize_campaign_type

log = logging.getLogger("scam_classifier")

CONFIG_DIR = Path(__file__).parent.parent / "config"


@dataclass
class ClassificationResult:
    """Result from scam type classification."""
    campaign_type: str       # One of 10 canonical types
    confidence: float        # 0.0-1.0
    tier: str                # "keyword", "llm", "cross_reference"
    matched_keywords: list[str]  # Keywords that triggered classification
    source: str              # "keyword_extractor", "gemma4", "bnm", "sc", "internal"


class ScamClassifier:
    """
    3-tier scam type classifier.
    
    Tier 1: Keyword matching (fast, ~70% recall, ~90% precision)
    Tier 2: LLM analysis (when Tier 1 confidence < 0.8, ~85% recall)
    Tier 3: Cross-reference override (when BNM/SC match found, ~95% precision)
    """

    def __init__(
        self,
        keyword_extractor=None,
        llm_enhancer=None,
        cross_reference_engine=None,
        config_path: Optional[str] = None,
    ):
        self.keyword_extractor = keyword_extractor
        self.llm_enhancer = llm_enhancer
        self.cross_reference_engine = cross_reference_engine

        # Load scam type definitions
        cfg_path = Path(config_path) if config_path else CONFIG_DIR / "scam_types.yaml"
        self.type_definitions = {}
        self.type_keywords = {}  # {type: {"primary": [...], "secondary": [...]}}
        self.type_aliases = {}   # {alias: canonical_type}

        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for type_name, type_def in data.get("types", {}).items():
                self.type_definitions[type_name] = type_def
                self.type_keywords[type_name] = {
                    "primary": type_def.get("keywords", {}).get("primary", []),
                    "secondary": type_def.get("keywords", {}).get("secondary", []),
                }
                for alias in type_def.get("aliases", []):
                    self.type_aliases[alias.lower()] = type_name

        log.info(f"ScamClassifier loaded: {len(self.type_definitions)} types, "
                 f"{len(self.type_aliases)} aliases")

    def classify(
        self,
        text: str,
        keyword_results: Optional[dict] = None,
        cross_ref_result: Optional[object] = None,
        score: int = 0,
    ) -> ClassificationResult:
        """
        Classify a message/campaign using the 3-tier system.
        
        Args:
            text: Message text or campaign script sample
            keyword_results: Pre-computed keyword extraction results (optional)
            cross_ref_result: Cross-reference result from Phase 1 (optional)
            score: Current campaign score (used to decide LLM tier)
        
        Returns:
            ClassificationResult with type, confidence, tier, and matched keywords
        """
        # ── Tier 3: Cross-Reference Override (highest confidence) ──────────
        if cross_ref_result and hasattr(cross_ref_result, "matched") and cross_ref_result.matched:
            cr_type = self._classify_from_cross_reference(cross_ref_result)
            if cr_type and cr_type != "unknown":
                log.info(f"Tier 3 (cross-reference): {cr_type} "
                         f"(confidence=0.95, sources={len(cross_ref_result.sources)})")
                return ClassificationResult(
                    campaign_type=cr_type,
                    confidence=0.95,
                    tier="cross_reference",
                    matched_keywords=[],
                    source=cross_ref_result.sources[0].database if cross_ref_result.sources else "unknown",
                )

        # ── Tier 1: Keyword Classification ─────────────────────────────────
        tier1_result = self._classify_tier1_keyword(text, keyword_results)
        if tier1_result.confidence >= 0.8:
            log.info(f"Tier 1 (keyword): {tier1_result.campaign_type} "
                     f"(confidence={tier1_result.confidence:.2f})")
            return tier1_result

        # ── Tier 2: LLM Classification (when Tier 1 is uncertain) ──────────
        if self.llm_enhancer and score >= 60:
            tier2_result = self._classify_tier2_llm(text)
            if tier2_result and tier2_result.confidence > tier1_result.confidence:
                log.info(f"Tier 2 (LLM): {tier2_result.campaign_type} "
                         f"(confidence={tier2_result.confidence:.2f})")
                return tier2_result

        # Fall back to Tier 1 result (even if low confidence)
        log.info(f"Tier 1 (keyword, fallback): {tier1_result.campaign_type} "
                 f"(confidence={tier1_result.confidence:.2f})")
        return tier1_result

    # ── Tier 1: Keyword-Based Classification ──────────────────────────────────

    def _classify_tier1_keyword(
        self, text: str, keyword_results: Optional[dict] = None
    ) -> ClassificationResult:
        """
        Classify based on keyword matching.
        Scores each type by counting keyword hits, weighted by primary/secondary.
        """
        text_lower = text.lower()
        type_scores = {}
        matched_keywords = []

        for type_name, keywords in self.type_keywords.items():
            if type_name == "unknown":
                continue

            score = 0.0
            type_matches = []

            # Primary keywords: weight 1.0
            for kw in keywords.get("primary", []):
                if kw.lower() in text_lower:
                    score += 1.0
                    type_matches.append(kw)

            # Secondary keywords: weight 0.5
            for kw in keywords.get("secondary", []):
                if kw.lower() in text_lower:
                    score += 0.5
                    type_matches.append(kw)

            # Type aliases: weight 0.8 (canonical synonyms)
            for alias, canonical in self.type_aliases.items():
                if canonical == type_name and alias in text_lower:
                    score += 0.8
                    type_matches.append(alias)

            if score > 0:
                type_scores[type_name] = score
                matched_keywords.extend(type_matches)

        # Also check keyword_results from KeywordExtractor if available
        if keyword_results:
            for category, kws in keyword_results.items():
                for item in kws:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        kw_text, kw_weight = item[0], float(item[1])
                        # Try to match keyword to a scam type
                        for type_name, type_def in self.type_definitions.items():
                            if type_name == "unknown":
                                continue
                            aliases = type_def.get("aliases", [])
                            if kw_text.lower() in [a.lower() for a in aliases]:
                                type_scores[type_name] = type_scores.get(type_name, 0) + kw_weight * 0.01

        if not type_scores:
            return ClassificationResult(
                campaign_type="unknown",
                confidence=0.0,
                tier="keyword",
                matched_keywords=[],
                source="keyword_extractor",
            )

        # Find best type
        best_type = max(type_scores, key=type_scores.get)
        best_score = type_scores[best_type]

        # Normalise confidence: 0.4 base for any match, +0.1 per keyword hit, cap 0.95
        confidence = min(0.4 + best_score * 0.1, 0.95)

        return ClassificationResult(
            campaign_type=normalize_campaign_type(best_type),
            confidence=confidence,
            tier="keyword",
            matched_keywords=list(set(matched_keywords))[:10],
            source="keyword_extractor",
        )

    # ── Tier 2: LLM-Based Classification ──────────────────────────────────────

    def _classify_tier2_llm(self, text: str) -> Optional[ClassificationResult]:
        """
        Use LLM (Gemma 4) for scam type classification when keywords are insufficient.
        """
        if not self.llm_enhancer:
            return None

        try:
            analysis = self.llm_enhancer.analyze_message(text)
            scam_type = normalize_campaign_type(analysis.scam_type)
            confidence = analysis.confidence

            return ClassificationResult(
                campaign_type=scam_type,
                confidence=min(confidence, 0.90),  # Cap LLM confidence
                tier="llm",
                matched_keywords=[],
                source=getattr(analysis, "model_used", "gemma4"),
            )
        except Exception as e:
            log.warning(f"LLM classification failed: {e}")
            return None

    # ── Tier 3: Cross-Reference Classification ────────────────────────────────

    # Mapping from cross-reference database source to scam type.
    # Extend this dict to add new cross-reference sources without code changes.
    CROSS_REF_TYPE_MAP: dict[str, str] = {
        "bnm": "investment",         # BNM Alert List: typically investment scams
        "sc": "investment",          # Securities Commission: investment/securities fraud
        "semakmule": "macau",        # SemakMule: typically macau/job-task scams
        # Add new sources here, e.g.:
        # "fca": "investment",       # UK FCA warnings
        # "police_report": "other",  # Local police report matches
    }

    def _classify_from_cross_reference(self, cross_ref_result) -> Optional[str]:
        """
        Derive scam type from cross-reference match.
        Uses CROSS_REF_TYPE_MAP for extensible source→type mapping.
        Falls back to None for unrecognized sources (e.g. 'internal').
        """
        if not cross_ref_result or not cross_ref_result.sources:
            return None

        for source in cross_ref_result.sources:
            mapped_type = self.CROSS_REF_TYPE_MAP.get(source.database)
            if mapped_type:
                return mapped_type
            # Internal matches: can't determine type from match alone
            continue

        return None

    def get_type_label(self, campaign_type: str) -> str:
        """Get human-readable label for a campaign type."""
        type_def = self.type_definitions.get(campaign_type, {})
        return type_def.get("label", "Unknown Scam")

    def get_type_description(self, campaign_type: str) -> str:
        """Get description for a campaign type."""
        type_def = self.type_definitions.get(campaign_type, {})
        return type_def.get("description", "Unclassified scam activity.")

    def get_common_entities(self, campaign_type: str) -> list[str]:
        """Get common entity types for a campaign type."""
        type_def = self.type_definitions.get(campaign_type, {})
        return type_def.get("common_entities", [])