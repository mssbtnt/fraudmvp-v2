"""
Keyword Scorer for FraudMVP

Scores messages based on keyword matches from config/keywords.yaml.
Combines with entity scores from extractor for final risk classification.

Architecture:
    Raw Message → Keyword Scorer → Risk Score → Alert Threshold?
                                         ↓
                                    Entity Scorer → Combined Score

Risk Thresholds:
    - Low:     < 40
    - Medium:  40-60
    - High:    60-80
    - Critical: > 80
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# ─── Config ───────────────────────────────────────────────────────────────────

load_dotenv()
CONFIG_DIR = Path(__file__).parent.parent / "config"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("keyword_scorer")


# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class KeywordMatch:
    """A matched keyword with its weight."""
    keyword: str
    category: str
    weight: int
    position: int
    context: str = ""  # Surrounding text (50 chars)


@dataclass
class ScoringResult:
    """Result of scoring a message."""
    total_score: int
    risk_level: str  # low, medium, high, critical
    keyword_matches: list[KeywordMatch]
    exclusion_adjustment: int
    entity_bonus: int
    combo_bonus: int = 0
    scam_type: Optional[str] = None
    confidence: float = 0.0


@dataclass
class KeywordConfig:
    """Loaded keyword configuration."""
    primary: list[dict] = field(default_factory=list)
    secondary: list[dict] = field(default_factory=list)
    slang: list[dict] = field(default_factory=list)
    exclusions: list[dict] = field(default_factory=list)
    community_flags: list[dict] = field(default_factory=list)
    regex_patterns: list[dict] = field(default_factory=list)
    scam_types: dict = field(default_factory=dict)


# ─── Keyword Scorer ───────────────────────────────────────────────────────────


class KeywordScorer:
    """
    Scores messages based on keyword matches.
    
    Usage:
        scorer = KeywordScorer()
        result = scorer.score("Jawatan kosong! WhatsApp 012-3456789 untuk interview.")
        print(result.total_score, result.risk_level)
    """

    # Risk thresholds
    THRESHOLD_LOW = 40
    THRESHOLD_MEDIUM = 60
    THRESHOLD_HIGH = 80

    def __init__(self, config_path: Optional[Path] = None):
        self.config = self._load_config(config_path or CONFIG_DIR / "keywords.yaml")
        self._compile_patterns()

    def _load_config(self, path: Path) -> KeywordConfig:
        """Load keyword configuration from YAML."""
        if not path.exists():
            log.warning(f"Config not found: {path}. Using defaults.")
            return KeywordConfig()

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        return KeywordConfig(
            primary=data.get("primary", []),
            secondary=data.get("secondary", []),
            slang=data.get("slang", []),
            exclusions=data.get("exclusions", []),
            community_flags=data.get("community_flags", []),
            regex_patterns=data.get("regex_patterns", []),
            scam_types=data.get("scam_types", {}),
        )

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency."""
        self.compiled_patterns = []
        for pattern_def in self.config.regex_patterns:
            pattern_str = pattern_def.get("pattern", "")
            if pattern_str:
                try:
                    compiled = re.compile(pattern_str, re.IGNORECASE)
                    self.compiled_patterns.append({
                        "name": pattern_def.get("name", "unnamed"),
                        "pattern": compiled,
                        "weight": pattern_def.get("weight", 10),
                        "extract_type": pattern_def.get("extract", {}).get("type"),
                    })
                except re.error as e:
                    log.warning(f"Invalid regex pattern: {pattern_str} — {e}")

    def score(
        self,
        text: str,
        entity_count: int = 0,
        has_suspicious_entities: bool = False,
    ) -> ScoringResult:
        """
        Score a message based on keywords and entities.
        
        Args:
            text: Message text to score
            entity_count: Number of entities extracted (phones, URLs, etc.)
            has_suspicious_entities: Whether any entity is flagged as suspicious
        
        Returns:
            ScoringResult with total score, risk level, and matches
        """
        text_lower = text.lower()
        matches: list[KeywordMatch] = []
        total_weight = 0
        exclusion_adjustment = 0

        # Score primary keywords (highest weight)
        for kw_def in self.config.primary:
            phrase = kw_def.get("phrase", "").lower()
            if phrase and phrase in text_lower:
                weight = kw_def.get("weight", 35)
                pos = text_lower.find(phrase)
                match = KeywordMatch(
                    keyword=phrase,
                    category="primary",
                    weight=weight,
                    position=pos,
                    context=self._get_context(text, pos),
                )
                matches.append(match)
                total_weight += weight

        # Score secondary keywords
        for kw_def in self.config.secondary:
            phrase = kw_def.get("phrase", "").lower()
            if phrase and phrase in text_lower:
                weight = kw_def.get("weight", 15)
                pos = text_lower.find(phrase)
                match = KeywordMatch(
                    keyword=phrase,
                    category="secondary",
                    weight=weight,
                    position=pos,
                    context=self._get_context(text, pos),
                )
                matches.append(match)
                total_weight += weight

        # Score slang terms
        for kw_def in self.config.slang:
            phrase = kw_def.get("phrase", "").lower()
            if phrase and phrase in text_lower:
                weight = kw_def.get("weight", 10)
                pos = text_lower.find(phrase)
                match = KeywordMatch(
                    keyword=phrase,
                    category="slang",
                    weight=weight,
                    position=pos,
                    context=self._get_context(text, pos),
                )
                matches.append(match)
                total_weight += weight

        # Score community flags
        for kw_def in self.config.community_flags:
            phrase = kw_def.get("phrase", "").lower()
            if phrase and phrase in text_lower:
                weight = kw_def.get("weight", 25)
                pos = text_lower.find(phrase)
                match = KeywordMatch(
                    keyword=phrase,
                    category="community_flag",
                    weight=weight,
                    position=pos,
                    context=self._get_context(text, pos),
                )
                matches.append(match)
                total_weight += weight

        # Score regex patterns
        for pattern_def in self.compiled_patterns:
            pattern = pattern_def["pattern"]
            weight = pattern_def["weight"]
            for m in pattern.finditer(text):
                match = KeywordMatch(
                    keyword=m.group(),
                    category="regex",
                    weight=weight,
                    position=m.start(),
                    context=self._get_context(text, m.start()),
                )
                matches.append(match)
                total_weight += weight

        # Apply exclusions (reduce score for legitimate indicators)
        for exc_def in self.config.exclusions:
            phrase = exc_def.get("phrase", "").lower()
            if phrase and phrase in text_lower:
                reduction = exc_def.get("by", 15)
                exclusion_adjustment += reduction
                total_weight = max(0, total_weight - reduction)

        # Entity bonus (structured data = higher confidence)
        entity_bonus = 0
        if entity_count > 0:
            entity_bonus = min(entity_count * 5, 20)  # +5 per entity, max +20
        if has_suspicious_entities:
            entity_bonus += 15  # Significant boost for suspicious entities

        # ── Multi-signal combination bonuses ────────────────────────────────────
        # These detect patterns where multiple high-risk signals appear together,
        # which is much stronger than any single signal alone.
        combo_bonus = 0
        match_keywords_lower = [m.keyword.lower() for m in matches]
        match_categories = set(m.category for m in matches)
        has_phone = any(k in match_keywords_lower for k in ["phone", "whatsapp link", "whatsapp nombor", "whatsapp je"])
        has_url = any("url" in m.keyword.lower() or "http" in m.keyword.lower() or "t.me" in m.keyword.lower() for m in matches)
        has_deposit = any(k in match_keywords_lower for k in ["deposit", "bayar dahulu", "bayar dulu", "transfer dulu", "bank in dulu"])
        has_bank = any(k in match_keywords_lower for k in ["akaun bank", "bank account"])
        has_whatsapp = any("whatsapp" in k for k in match_keywords_lower)
        has_scam_word = any(k in match_keywords_lower for k in ["scam", "penipu", "tipu", "kantoi", "tertipu", "kena tipu"])
        has_urgency = any(k in match_keywords_lower for k in ["sekarang je", "terhad je", "last slot", "slot terhad", "cepat daftar", "daftar sekarang"])

        if has_phone and has_url:
            combo_bonus += 15    # Phone + URL = recruitment funnel
        if has_phone and has_deposit:
            combo_bonus += 20    # Phone + deposit = advance fee scam
        if has_phone and has_bank:
            combo_bonus += 25    # Phone + bank account = financial vector
        if has_url and has_deposit:
            combo_bonus += 15    # URL + deposit = phishing/e-commerce scam
        if has_phone and has_url and has_deposit:
            combo_bonus += 35    # All three = high-confidence scam
        if has_phone and has_urgency:
            combo_bonus += 10    # Phone + urgency = pressure tactic
        if has_whatsapp and has_deposit:
            combo_bonus += 22    # WhatsApp + deposit = common MY scam pattern
        if has_whatsapp and has_bank:
            combo_bonus += 20    # WhatsApp + bank = financial scam
        if has_phone and has_scam_word:
            combo_bonus += 18    # Phone + scam keyword = fraud contact

        total_weight += combo_bonus

        total_weight += entity_bonus

        # Determine risk level
        risk_level = self._get_risk_level(total_weight)

        # Detect scam type
        scam_type = self._detect_scam_type(text_lower, matches)

        # Calculate confidence (based on match count and coverage)
        confidence = min(len(matches) * 0.1 + (entity_count * 0.05), 1.0)

        return ScoringResult(
            total_score=total_weight,
            risk_level=risk_level,
            keyword_matches=matches,
            exclusion_adjustment=exclusion_adjustment,
            entity_bonus=entity_bonus,
            combo_bonus=combo_bonus,
            scam_type=scam_type,
            confidence=round(confidence, 2),
        )

    def _get_context(self, text: str, pos: int, context_len: int = 50) -> str:
        """Get surrounding context for a match position."""
        start = max(0, pos - context_len)
        end = min(len(text), pos + context_len)
        return text[start:end].strip()

    def _get_risk_level(self, score: int) -> str:
        """Determine risk level from score."""
        if score >= self.THRESHOLD_HIGH:
            return "critical"
        elif score >= self.THRESHOLD_MEDIUM:
            return "high"
        elif score >= self.THRESHOLD_LOW:
            return "medium"
        else:
            return "low"

    def _detect_scam_type(self, text_lower: str, matches: list[KeywordMatch]) -> Optional[str]:
        """Detect the type of scam based on keywords."""
        # Check each scam type's keywords
        for scam_type, type_config in self.config.scam_types.items():
            keywords = type_config.get("keywords", [])
            threshold = type_config.get("weight_threshold", 40)
            
            type_weight = 0
            for kw in keywords:
                if kw.lower() in text_lower:
                    type_weight += 10
            
            if type_weight >= threshold:
                return scam_type

        # Heuristic detection based on matches
        match_keywords = [m.keyword for m in matches]
        
        if any(kw in ["jawatan kosong", "whatsapp link", "whatsapp je"] for kw in match_keywords):
            if "deposit" in text_lower or "bayar" in text_lower:
                return "job_scam"

        if any(kw in ["deposit", "bayar dahulu", "bayar dulu"] for kw in match_keywords):
            return "deposit_scam"

        if any(kw in ["scan qr", "qr"] for kw in match_keywords):
            return "qr_scam"

        if any(kw in ["untung", "pulangan", "investasi", "jamin"] for kw in match_keywords):
            return "investment_scam"

        if any(kw in ["link bank", "login", "verify"] for kw in match_keywords):
            return "phishing"

        return None

    def get_summary(self, result: ScoringResult) -> dict:
        """Get a summary dict for logging/alerting."""
        return {
            "score": result.total_score,
            "risk_level": result.risk_level,
            "confidence": result.confidence,
            "scam_type": result.scam_type,
            "keyword_count": len(result.keyword_matches),
            "top_keywords": [
                {"keyword": m.keyword, "category": m.category, "weight": m.weight}
                for m in sorted(result.keyword_matches, key=lambda x: x.weight, reverse=True)[:5]
            ],
            "exclusion_adjustment": result.exclusion_adjustment,
            "entity_bonus": result.entity_bonus,
            "combo_bonus": result.combo_bonus,
        }


# ─── Integration Helper ───────────────────────────────────────────────────────


def combine_scores(keyword_result: ScoringResult, entity_score: int) -> int:
    """
    Combine keyword score with entity-based score.
    
    Args:
        keyword_result: Result from KeywordScorer.score()
        entity_score: Score from entity extractor (based on entity types, counts, suspiciousness)
    
    Returns:
        Combined risk score
    """
    # Base score from keywords
    combined = keyword_result.total_score
    
    # Add entity score (entities are strong indicators)
    combined += entity_score
    
    # Boost if both keyword and entity indicators present
    if keyword_result.keyword_matches and entity_score > 0:
        combined += 10  # Synergy bonus
    
    return combined


# ─── CLI Entry Point ──────────────────────────────────────────────────────────


if __name__ == "__main__":
    import sys

    scorer = KeywordScorer()
    
    if len(sys.argv) > 1:
        # Score text from command line
        text = " ".join(sys.argv[1:])
        result = scorer.score(text)
        print(f"Score: {result.total_score}")
        print(f"Risk Level: {result.risk_level}")
        print(f"Confidence: {result.confidence}")
        print(f"Scam Type: {result.scam_type or 'Unknown'}")
        print(f"Matches: {len(result.keyword_matches)}")
        for m in result.keyword_matches:
            print(f"  - [{m.category}] {m.keyword!r} (+{m.weight})")
    else:
        # Interactive mode
        print("Keyword Scorer CLI")
        print("Enter text to score (or 'quit' to exit)")
        
        while True:
            text = input("\n> ").strip()
            if text.lower() == "quit":
                break
            
            result = scorer.score(text)
            summary = scorer.get_summary(result)
            print(json.dumps(summary, indent=2))