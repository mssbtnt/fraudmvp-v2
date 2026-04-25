"""
LLM Enhancer for FraudMVP

Uses Gemma 4 (31B) for advanced scam analysis:
- Scam type classification
- Risk assessment with reasoning
- Entity extraction validation
- Campaign narrative analysis

Fallback: Uses nemotron-cascade-2 if Gemma unavailable.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx
from dotenv import load_dotenv

from services.campaign_types import normalize_campaign_type

load_dotenv()
log = logging.getLogger("llm_enhancer")

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
GEMMA_MODEL = os.getenv("FRAUD_LLM_MODEL", "gemma4:31b-cloud")
FALLBACK_MODEL = "nemotron-cascade-2:latest"
LLM_ENABLED = os.getenv("FRAUD_LLM_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
LLM_TIMEOUT_SECONDS = float(os.getenv("FRAUD_LLM_TIMEOUT_SECONDS", "20"))
LLM_MAX_FAILURES = max(1, int(os.getenv("FRAUD_LLM_MAX_FAILURES", "2")))


@dataclass
class LLMAnalysis:
    """Result from LLM-enhanced scam analysis."""
    scam_type: str
    risk_level: str  # low, medium, high, critical
    confidence: float  # 0.0 - 1.0
    red_flags: list[str]
    reasoning: str
    model_used: str


class FraudLLMEnhancer:
    """
    LLM-powered scam analysis using Gemma 4.
    
    Usage:
        enhancer = FraudLLMEnhancer()
        analysis = enhancer.analyze_message("Jawatan kosong! WhatsApp 012-3456789...")
        print(analysis.scam_type, analysis.risk_level)
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model or GEMMA_MODEL
        self.fallback = FALLBACK_MODEL
        self.enabled = LLM_ENABLED
        self.max_failures = LLM_MAX_FAILURES
        self.failure_count = 0
        self._client = httpx.Client(
            timeout=httpx.Timeout(LLM_TIMEOUT_SECONDS, connect=min(5.0, LLM_TIMEOUT_SECONDS)),
        )

    def analyze_message(
        self,
        text: str,
        entities: Optional[list[dict]] = None,
        keyword_score: int = 0,
    ) -> LLMAnalysis:
        """
        Analyze a message for scam indicators using LLM.
        
        Args:
            text: Message text to analyze
            entities: List of extracted entities (optional, for context)
            keyword_score: Pre-computed keyword score (optional)
        
        Returns:
            LLMAnalysis with scam type, risk level, and reasoning
        """
        if not self.enabled:
            return self._default_analysis("LLM disabled", "disabled")

        prompt = self._build_prompt(text, entities, keyword_score)

        primary_response = self._generate(prompt, self.model)
        primary_analysis = self._parse_response(primary_response, self.model)
        if self._is_usable_analysis(primary_analysis):
            self.failure_count = 0
            return primary_analysis

        log.warning("Primary LLM failed or returned unusable output; trying fallback %s", self.fallback)
        fallback_response = self._generate(prompt, self.fallback)
        fallback_analysis = self._parse_response(fallback_response, self.fallback)
        if self._is_usable_analysis(fallback_analysis):
            self.failure_count = 0
            return fallback_analysis

        self.failure_count += 1
        if self.failure_count >= self.max_failures:
            self.enabled = False
            log.error(
                "Disabling LLM enhancement for the rest of this run after %s consecutive failures",
                self.failure_count,
            )

        return self._default_analysis("LLM analysis failed", fallback_analysis.model_used)

    def _build_prompt(
        self,
        text: str,
        entities: Optional[list[dict]],
        keyword_score: int,
    ) -> str:
        """Build analysis prompt for LLM."""
        entity_context = ""
        if entities:
            entity_str = ", ".join([f"{e.get('type', 'unknown')}: {e.get('value', '')}" for e in entities[:5]])
            entity_context = f"\nExtracted entities: {entity_str}"
        
        score_context = f"\nKeyword-based risk score: {keyword_score}/100" if keyword_score > 0 else ""
        
        return f"""You are a Malaysian fraud detection expert. Analyze this Telegram message for scam indicators.

Message:
{text}{entity_context}{score_context}

Identify:
1. Scam type (choose one: job_scam, deposit_scam, investment_scam, phishing, qr_scam, romance_scam, shopping_scam, other)
2. Risk level (low, medium, high, critical)
3. Confidence score (0.0 to 1.0)
4. Key red flags (list 2-5 specific indicators from the message)
5. Brief reasoning (1-2 sentences explaining the classification)

Respond in JSON format only:
{{
  "scam_type": "...",
  "risk_level": "...",
  "confidence": 0.0,
  "red_flags": ["...", "..."],
  "reasoning": "..."
}}"""

    def _generate(self, prompt: str, model: str) -> str:
        """Call Ollama generate API."""
        try:
            resp = self._client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 500,
                    }
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:
            log.error(f"LLM generate failed ({model}): {e}")
            return ""

    def _parse_response(self, response_text: str, model_used: str) -> LLMAnalysis:
        """Parse LLM response into LLMAnalysis."""
        default = self._default_analysis("LLM analysis failed", model_used)
        
        if not response_text:
            return default
        
        # Try to extract JSON from response
        try:
            # Handle markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            
            data = json.loads(response_text)
            
            return LLMAnalysis(
                scam_type=normalize_campaign_type(data.get("scam_type", "unknown")),
                risk_level=data.get("risk_level", "low"),
                confidence=float(data.get("confidence", 0.5)),
                red_flags=data.get("red_flags", []),
                reasoning=data.get("reasoning", ""),
                model_used=model_used,
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            log.warning(f"Failed to parse LLM response: {e}")
            log.debug(f"Raw response: {response_text[:500]}")
            
            # Fallback: extract risk level from text
            risk_level = "low"
            if "critical" in response_text.lower():
                risk_level = "critical"
            elif "high" in response_text.lower():
                risk_level = "high"
            elif "medium" in response_text.lower():
                risk_level = "medium"
            
            return LLMAnalysis(
                scam_type="unknown",
                risk_level=risk_level,
                confidence=0.0,
                red_flags=[],
                reasoning="Parsing failed, used fallback extraction",
                model_used=model_used,
            )

    @staticmethod
    def _is_usable_analysis(analysis: LLMAnalysis) -> bool:
        """Treat only confident, structured output as a successful LLM response."""
        return bool(
            analysis
            and analysis.model_used != "disabled"
            and analysis.confidence > 0.0
            and analysis.reasoning
            and "failed" not in analysis.reasoning.lower()
        )

    @staticmethod
    def _default_analysis(reason: str, model_used: str) -> LLMAnalysis:
        return LLMAnalysis(
            scam_type="unknown",
            risk_level="low",
            confidence=0.0,
            red_flags=[],
            reasoning=reason,
            model_used=model_used,
        )

    def classify_scam_type(self, text: str) -> str:
        """Quick scam type classification only."""
        prompt = f"""Classify this Malaysian scam message into ONE category:
- job_scam
- deposit_scam
- investment_scam
- phishing
- qr_scam
- romance_scam
- shopping_scam
- other

Message: {text}

Respond with ONE word only (e.g., "job_scam")."""
        
        response = self._generate(prompt, self.model)
        if not response:
            return "unknown"
        
        # Extract first word, clean up
        scam_type = response.strip().lower().split()[0]
        return normalize_campaign_type(scam_type)

    def batch_analyze(
        self,
        messages: list[dict],
        max_batch: int = 10,
    ) -> list[LLMAnalysis]:
        """
        Analyze multiple messages (rate-limited).
        
        Args:
            messages: List of dicts with 'text' and optional 'entities'
            max_batch: Max messages to analyze (avoid rate limits)
        
        Returns:
            List of LLMAnalysis results
        """
        import time
        
        results = []
        for i, msg in enumerate(messages[:max_batch]):
            if i > 0:
                time.sleep(0.5)  # Rate limit: 2 req/sec
            
            analysis = self.analyze_message(
                text=msg.get("text", ""),
                entities=msg.get("entities"),
                keyword_score=msg.get("keyword_score", 0),
            )
            results.append(analysis)
        
        return results

    def close(self):
        """Close HTTP client."""
        self._client.close()


# ─── Integration Helper ───────────────────────────────────────────────────────


def enhance_scorer_result(
    text: str,
    base_score: int,
    entities: Optional[list[dict]] = None,
    model: Optional[str] = None,
) -> dict:
    """
    Enhance existing scorer result with LLM analysis.
    
    Usage in scorer.py:
        from services.llm_enhancer import enhance_scorer_result
        
        llm_result = enhance_scorer_result(message_text, base_score, entities)
        final_score = llm_result['enhanced_score']
        scam_type = llm_result['scam_type']
    """
    enhancer = FraudLLMEnhancer(model)
    
    try:
        analysis = enhancer.analyze_message(text, entities, base_score)
        
        # Boost score based on LLM confidence and risk level
        llm_boost = 0
        if analysis.risk_level == "critical":
            llm_boost = 20
        elif analysis.risk_level == "high":
            llm_boost = 15
        elif analysis.risk_level == "medium":
            llm_boost = 10
        
        # Scale by confidence
        llm_boost = int(llm_boost * analysis.confidence)
        
        enhanced_score = min(base_score + llm_boost, 100)
        
        return {
            "original_score": base_score,
            "enhanced_score": enhanced_score,
            "llm_boost": llm_boost,
            "scam_type": analysis.scam_type,
            "risk_level": analysis.risk_level,
            "confidence": analysis.confidence,
            "red_flags": analysis.red_flags,
            "reasoning": analysis.reasoning,
            "model_used": analysis.model_used,
        }
    finally:
        enhancer.close()


# ─── CLI Entry Point ──────────────────────────────────────────────────────────


if __name__ == "__main__":
    import sys
    
    enhancer = FraudLLMEnhancer()
    
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        print(f"Analyzing: {text[:100]}...\n")
        
        analysis = enhancer.analyze_message(text)
        
        print(f"Scam Type:    {analysis.scam_type}")
        print(f"Risk Level:   {analysis.risk_level}")
        print(f"Confidence:   {analysis.confidence:.0%}")
        print(f"Model Used:   {analysis.model_used}")
        print(f"\nRed Flags:")
        for flag in analysis.red_flags:
            print(f"  • {flag}")
        print(f"\nReasoning: {analysis.reasoning}")
    else:
        print("LLM Enhancer CLI")
        print("Usage: python -m services.llm_enhancer <message text>")
        print("\nExample:")
        print("  python -m services.llm_enhancer 'Jawatan kosong! WhatsApp 012-3456789'")
    
    enhancer.close()
