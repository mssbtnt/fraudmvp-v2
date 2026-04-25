"""
Victim Signal Detector — Extract evidence of financial loss from message text.

Detects patterns like:
- "kena tipu RM50K" → financial_loss, amount: 50000
- "dah buat police report" → police_report
- "jangan bayar, ni scam" → community_warning
- "sedih, hilang semua duit" → emotional_distress

Each signal has a weight that contributes to the entity's risk score.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger("victim_signal")


# ─── Signal Patterns ──────────────────────────────────────────────────────────

SIGNAL_PATTERNS = {
    "financial_loss": [
        (r'\b(kena|telah|da|dah|sudah)\s+(tipu|scam|con|penipu)\b', 40),
        (r'\b(hilang|kehilangan|rugi)\s+(duit|wang|RM|ringgit|money)\b', 45),
        (r'\b(sudah|da|telah)\s+(transfer|bank\s*in|hantar)\s+(duit|RM|wang)\b', 35),
        (r'\b(duit|wang|money)\s+(hilang|rugi|tipu|scammed)\b', 35),
        (r'\b(tipu|scam|con)\s+(RM|ringgit|duit|wang)\b', 40),
        (r'\bscammed\b', 35),
        (r'\bkena\s+scam\b', 40),
        (r'\bfraud\b', 30),
        (r'\bdefrauded\b', 35),
    ],
    "police_report": [
        (r'\b(police|polis)\s+(report|laporan|aduan)\b', 35),
        (r'\b(buat|filed|made)\s+(laporan|report|aduan)\b', 30),
        (r'\bpolis\s+report\b', 35),
        (r'\blaporan\s+polis\b', 35),
        (r'\breport\s+to\s+(pdrm|polis|bukit\s+aman)\b', 30),
    ],
    "amount_mentioned": [
        (r'\bRM[\d,]+(?:\.\d{2})?\b', 30),
        (r'\bRM\s*[\d,]+(?:\.\d{2})?\b', 30),
        (r'\brm\s*[\d,]+(?:\.\d{2})?\b', 30),
        (r'\b([\d,]+(?:\.\d{2})?)\s*(ringgit|RM)\b', 30),
        (r'\bRM\s*\d+[Kk]\b', 30),
        (r'\brm\s*\d+[Kk]\b', 25),
        (r'\bRM\s*\d+[Mm]\b', 30),
    ],
    "community_warning": [
        (r'\b(jangan|don\'t|dont)\s+(bayar|pay|transfer|hantar|beli)\b', 25),
        (r'\b(beware|amaran|warning|awas|perhatian)\b', 20),
        (r'\b(scam|tipu|penipu|con)\b', 30),
        (r'\b(jangan\s+kena)\s+(tipu|scam)\b', 35),
        (r'\bharap\s+banci\b', 20),
        (r'\bforward\s+ini\b', 15),
        (r'\bsila\s+share\b', 15),
        (r'\bsedar\s+diri\b', 20),
    ],
    "emotional_distress": [
        (r'\b(sedih|devastated|teruk|terrible|stress|depressed)\b', 15),
        (r'\b(sakit|sakit\s*hati|heartbroken|heartbreak)\b', 15),
        (r'\b(hilang\s+semua|hancur|binasa|musnah)\b', 20),
        (r'\b(tak\s+tahu\s+apa\s+nak\s+buat)\b', 15),
        (r'\b(suicide|bunuh\s*diri|tak\s+nak\s+hidup)\b', 25),
    ],
}


# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class VictimSignal:
    """A detected victim signal in a message."""
    signal_type: str           # 'financial_loss', 'police_report', etc.
    pattern_matched: str       # The regex pattern that matched
    extracted_text: str        # The matching text snippet
    extracted_amount: float    # Monetary amount (if detected)
    weight: int                # Score boost value
    start_pos: int             # Position in original text
    end_pos: int               # End position in original text


@dataclass
class VictimSignalResult:
    """Complete victim signal detection result for a message."""
    signals: list[VictimSignal] = field(default_factory=list)
    total_weight: int = 0
    categories: list[str] = field(default_factory=list)
    has_financial_loss: bool = False
    has_police_report: bool = False
    has_community_warning: bool = False
    amounts_mentioned: list[float] = field(default_factory=list)
    max_amount: float = 0.0


# ─── Victim Signal Detector ───────────────────────────────────────────────────


class VictimSignalDetector:
    """
    Detect victim signals in message text near flagged entities.
    
    Uses regex patterns with weighted scoring to identify:
    - Financial loss ("kena tipu RM50K")
    - Police reports ("dah buat police report")
    - Community warnings ("jangan bayar, ni scam")
    - Emotional distress ("sedih, hilang semua duit")
    """

    # Score caps by category
    CATEGORY_CAPS = {
        "financial_loss": 25,
        "police_report": 20,
        "community_warning": 15,
        "amount_mentioned": 10,
        "emotional_distress": 5,
    }

    # Threshold for "high amount" boost
    HIGH_AMOUNT_THRESHOLD = 10_000

    def __init__(self, patterns: dict | None = None):
        """Initialise with custom or default patterns."""
        self.patterns = patterns or SIGNAL_PATTERNS
        # Compile patterns for performance
        self._compiled: dict[str, list[tuple[re.Pattern, int]]] = {}
        for category, pattern_list in self.patterns.items():
            self._compiled[category] = [
                (re.compile(p, re.IGNORECASE), w) for p, w in pattern_list
            ]

    def detect_signals(self, text: str) -> VictimSignalResult:
        """
        Detect all victim signals in a message text.
        
        Args:
            text: The message text to analyse.
            
        Returns:
            VictimSignalResult with all detected signals and aggregate scores.
        """
        result = VictimSignalResult()
        category_weights: dict[str, int] = {}

        for category, compiled_patterns in self._compiled.items():
            for pattern, weight in compiled_patterns:
                for match in pattern.finditer(text):
                    signal = VictimSignal(
                        signal_type=category,
                        pattern_matched=pattern.pattern,
                        extracted_text=match.group(0),
                        extracted_amount=0.0,
                        weight=weight,
                        start_pos=match.start(),
                        end_pos=match.end(),
                    )
                    result.signals.append(signal)

                    # Track categories
                    if category not in result.categories:
                        result.categories.append(category)

                    # Track weights (capped per category)
                    category_weights[category] = min(
                        category_weights.get(category, 0) + weight,
                        self.CATEGORY_CAPS.get(category, weight)
                    )

        # Extract monetary amounts
        amounts = self._extract_amounts(text)
        result.amounts_mentioned = amounts
        result.max_amount = max(amounts) if amounts else 0.0

        # Add amount weight
        if result.max_amount >= self.HIGH_AMOUNT_THRESHOLD:
            category_weights["amount_mentioned"] = self.CATEGORY_CAPS["amount_mentioned"]

        # Calculate total weight (capped)
        result.total_weight = sum(category_weights.values())
        result.total_weight = min(result.total_weight, 50)  # Max 50 total boost

        # Set boolean flags
        result.has_financial_loss = "financial_loss" in result.categories
        result.has_police_report = "police_report" in result.categories
        result.has_community_warning = "community_warning" in result.categories

        return result

    def _extract_amounts(self, text: str) -> list[float]:
        """
        Extract monetary amounts from text.
        e.g., "RM50,000" → 50000.0, "RM500" → 500.0, "RM3K" → 3000.0
        """
        amounts = []
        # RM followed by amount
        for match in re.finditer(r'\bRM\s*([\d,]+(?:\.\d{2})?)\b', text, re.IGNORECASE):
            try:
                amount_str = match.group(1).replace(",", "")
                amounts.append(float(amount_str))
            except ValueError:
                continue

        # Amount followed by ringgit/RM
        for match in re.finditer(r'\b([\d,]+(?:\.\d{2})?)\s*(?:ringgit|RM)\b', text, re.IGNORECASE):
            try:
                amount_str = match.group(1).replace(",", "")
                amounts.append(float(amount_str))
            except ValueError:
                continue

        # RM with K suffix (e.g., RM3K, rm5k)
        for match in re.finditer(r'\b[Rr][Mm]\s*(\d+)[Kk]\b', text):
            try:
                base = float(match.group(1))
                amounts.append(base * 1000)
            except ValueError:
                continue

        # RM with M suffix (e.g., RM5M, rm2m)
        for match in re.finditer(r'\b[Rr][Mm]\s*(\d+)[Mm]\b', text):
            try:
                base = float(match.group(1))
                amounts.append(base * 1_000_000)
            except ValueError:
                continue

        return amounts

    def compute_victim_score(self, result: VictimSignalResult) -> int:
        """
        Compute the victim impact score (0-50) for use in alert scoring.
        
        The score is the total_weight from detected signals,
        with additional boost for high amounts.
        """
        score = result.total_weight

        # Additional boost for very high amounts
        if result.max_amount >= 100_000:
            score += 10
        elif result.max_amount >= 50_000:
            score += 5

        return min(score, 50)  # Cap at 50

    # ── LLM-Enhanced Detection (Phase 3) ──────────────────────────────────

    def detect_signals_llm(
        self, text: str, model: str = "gemma4:31b"
    ) -> VictimSignalResult:
        """
        Use LLM (Gemma 4 via Ollama) for victim signal detection.
        Runs as a SECOND PASS when regex finds nothing but the message is suspicious.
        
        Args:
            text: Message text to analyze
            model: Ollama model name
        
        Returns:
            VictimSignalResult with LLM-detected signals
        """
        import json as json_mod

        prompt = f"""Analyse this Malaysian scam-related message for victim signals.
Look for: financial loss admissions, police reports, monetary amounts, emotional distress, community warnings.

Consider: Malay slang (kena tipu, dah kena), English mix (scam, fraud), creative spellings (sc4m, $cam, t1pu), indirect references.

Message: "{text}"

Return ONLY valid JSON:
{{"signals": [{{"type": "financial_loss|police_report|community_warning|amount_mentioned|emotional_distress", "text": "exact quote", "confidence": 0.0-1.0}}], "amount_mentioned": 0.0}}"""

        try:
            import urllib.request
            import urllib.error

            payload = json_mod.dumps({
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 256},
            }).encode("utf-8")

            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                response = json_mod.loads(resp.read().decode("utf-8"))

            raw_response = response.get("response", "")

            # Parse JSON from LLM response
            # The LLM may wrap JSON in markdown code blocks
            json_match = re.search(r'\{[\s\S]*\}', raw_response)
            if not json_match:
                log.debug(f"LLM response not valid JSON: {raw_response[:100]}")
                return VictimSignalResult(signals=[], categories=[], total_weight=0,
                                          amounts_mentioned=[], max_amount=0.0)

            llm_data = json_mod.loads(json_match.group())

            # Convert LLM signals to VictimSignal objects
            signals = []
            categories = set()
            amounts = []

            for sig in llm_data.get("signals", []):
                sig_type = sig.get("type", "")
                sig_text = sig.get("text", "")
                sig_conf = sig.get("confidence", 0.5)

                # Map LLM types to our categories
                type_map = {
                    "financial_loss": "financial_loss",
                    "police_report": "police_report",
                    "community_warning": "community_warning",
                    "amount_mentioned": "amount_mentioned",
                    "emotional_distress": "emotional_distress",
                }

                mapped_type = type_map.get(sig_type, "")
                if mapped_type:
                    # Weight based on confidence and category
                    weight = int(self.CATEGORY_CAPS.get(mapped_type, 10) * sig_conf)
                    signals.append(VictimSignal(
                        signal_type=mapped_type,
                        pattern_matched="llm_detection",
                        extracted_text=sig_text,
                        extracted_amount=0.0,
                        weight=weight,
                        start_pos=0,
                        end_pos=len(sig_text),
                    ))
                    categories.add(mapped_type)

            # Extract amount if provided
            llm_amount = llm_data.get("amount_mentioned", 0)
            if llm_amount and llm_amount > 0:
                amounts.append(float(llm_amount))

            total_weight = sum(s.weight for s in signals)

            return VictimSignalResult(
                signals=signals,
                categories=list(categories),
                total_weight=total_weight,
                amounts_mentioned=amounts,
                max_amount=max(amounts) if amounts else 0.0,
            )

        except urllib.error.URLError as e:
            log.debug(f"Ollama not available for LLM victim signal detection: {e}")
            return VictimSignalResult(signals=[], categories=[], total_weight=0,
                                      amounts_mentioned=[], max_amount=0.0)
        except Exception as e:
            log.warning(f"LLM victim signal detection failed: {e}")
            return VictimSignalResult(signals=[], categories=[], total_weight=0,
                                      amounts_mentioned=[], max_amount=0.0)

    def detect_signals_enhanced(
        self, text: str, keyword_score: int = 0, enable_llm: bool = False,
        llm_model: str = "gemma4:31b",
    ) -> VictimSignalResult:
        """
        Two-pass victim signal detection:
        1. Regex (fast, cheap)
        2. LLM (when regex finds nothing but message is suspicious)
        
        Args:
            text: Message text
            keyword_score: Keyword extraction score (used to decide LLM pass)
            enable_llm: Whether to enable LLM second pass
            llm_model: Ollama model for LLM pass
        
        Returns:
            Best available VictimSignalResult
        """
        # Pass 1: Regex (always)
        regex_result = self.detect_signals(text)

        # If regex found signals, use those (no need for LLM)
        if regex_result.signals:
            return regex_result

        # Pass 2: LLM (only if regex found nothing AND message seems suspicious)
        if enable_llm and keyword_score >= 1:
            llm_result = self.detect_signals_llm(text, model=llm_model)
            if llm_result.signals:
                log.info(f"LLM detected {len(llm_result.signals)} signals missed by regex")
                return llm_result

        return regex_result


# ─── Convenience ──────────────────────────────────────────────────────────────

def create_victim_signal_detector() -> VictimSignalDetector:
    """Create a VictimSignalDetector with default patterns."""
    return VictimSignalDetector()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    detector = create_victim_signal_detector()
    
    # Test cases
    test_messages = [
        "Kena tipu RM50,000 oleh abang ni. Dah buat police report.",
        "Jangan bayar! Ni scam. Hilang duit RM3,000.",
        "Saya dah transfer RM10,000 ke akaun yang diberi. Sekarang hilang semua.",
        "Bro, jangan kena scam. Forward ni kat kawan-kawan.",
        "Sedih... sakit hati. Hilang semua duit saya.",
        "RM500 je, tak sebesar mana pun tipu ni.",
        "Normal message about meeting at 3pm.",
    ]
    
    for msg in test_messages:
        result = detector.detect_signals(msg)
        score = detector.compute_victim_score(result)
        print(f"\n📝: {msg}")
        print(f"   Signals: {len(result.signals)}, Weight: {result.total_weight}, Score: {score}")
        print(f"   Categories: {result.categories}")
        if result.amounts_mentioned:
            print(f"   Amounts: {result.amounts_mentioned} (max: {result.max_amount})")
        for s in result.signals:
            print(f"   [{s.signal_type}] \"{s.extracted_text}\" (+{s.weight})")
