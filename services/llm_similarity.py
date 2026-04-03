"""
LLM Similarity — Local LLM-based text similarity for scam script matching.

Uses Ollama API to compare message texts and detect similar scam narratives.
Threshold: ≥80% similarity = same campaign script (+20 score).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("llm_similarity")

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-cascade-2:latest")
SIMILARITY_THRESHOLD = 0.80


# ─── Ollama API helpers ────────────────────────────────────────────────────────

def _ollama_generate(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """Call Ollama /api/generate endpoint."""
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as e:
        log.warning(f"Ollama generate failed: {e}")
        return ""


def _ollama_embed(text: str, model: str = OLLAMA_MODEL) -> Optional[list[float]]:
    """Get embedding vector from Ollama /api/embeddings endpoint."""
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{OLLAMA_BASE}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception as e:
        log.warning(f"Ollama embedding failed: {e}")
        return None


# ─── Cosine similarity ─────────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─── Similarity scorer ──────────────────────────────────────────────────────────

class ScriptSimilarityScorer:
    """
    Detect scam script reuse across messages using embeddings.

    Usage:
        scorer = ScriptSimilarityScorer()
        score = scorer.similarity_score(text_a, text_b)  # 0.0 – 1.0
        if scorer.is_same_campaign(text_a, text_b):
            print("Same scam campaign!")
    """

    def __init__(self, threshold: float = SIMILARITY_THRESHOLD):
        self.threshold = threshold
        self._cache: dict[str, list[float]] = {}

    def _normalize(self, text: str) -> str:
        """Strip personal info, normalizes whitespace."""
        text = re.sub(r"\+60\d[\d\-]{7,}", "[PHONE]", text)
        text = re.sub(r"\b\d{10,16}\b", "[ACCOUNT]", text)
        text = re.sub(r"https?://\S+", "[URL]", text)
        text = re.sub(r"\s+", " ", text).strip().lower()
        return text

    def _get_embedding(self, text: str) -> Optional[list[float]]:
        """Get embedding (with caching)."""
        key = self._normalize(text)
        if key not in self._cache:
            self._cache[key] = _ollama_embed(key) or []
        return self._cache[key]

    def similarity_score(self, text_a: str, text_b: str) -> float:
        """
        Return similarity score 0.0–1.0 between two texts.
        Falls back to 0.0 if embeddings unavailable.
        """
        emb_a = self._get_embedding(text_a)
        emb_b = self._get_embedding(text_b)

        if not emb_a or not emb_b:
            return 0.0
        return cosine_similarity(emb_a, emb_b)

    def is_same_campaign(self, text_a: str, text_b: str) -> bool:
        """True if similarity ≥ threshold."""
        return self.similarity_score(text_a, text_b) >= self.threshold

    def cluster_messages(self, texts: list[str], min_similarity: float = 0.80) -> list[list[int]]:
        """
        Group messages into clusters by script similarity.
        Returns list of clusters, each cluster is a list of message indices.
        Simple greedy clustering algorithm.
        """
        n = len(texts)
        clusters: list[list[int]] = []
        assigned = [False] * n

        for i in range(n):
            if assigned[i]:
                continue
            cluster = [i]
            assigned[i] = True

            for j in range(i + 1, n):
                if assigned[j]:
                    continue
                if self.similarity_score(texts[i], texts[j]) >= min_similarity:
                    cluster.append(j)
                    assigned[j] = True

            clusters.append(cluster)

        return clusters


# ─── Keyword extraction ───────────────────────────────────────────────────────

class KeywordExtractor:
    """
    Extract scam-relevant keywords from text using the LLM.
    Falls back to regex-based extraction when LLM is unavailable.
    """

    CATEGORIES = ["investment", "job_task", "aid_gov", "phishing", "urgency"]

    def __init__(self):
        self._keyword_map: dict[str, float] = {}
        self._load_yaml_keywords()

    def _load_yaml_keywords(self):
        """Load keywords from config/keywords.yaml."""
        import yaml
        from pathlib import Path
        cfg = Path(__file__).parent.parent / "config" / "keywords.yaml"
        if not cfg.exists():
            return
        data = yaml.safe_load(cfg.read_text())
        for cat, cat_data in data.get("categories", {}).items():
            for kw_entry in cat_data.get("keywords", []):
                if isinstance(kw_entry, list) and len(kw_entry) >= 2:
                    keyword, weight = kw_entry[0], kw_entry[1]
                    self._keyword_map[keyword.lower()] = (cat, weight)
                elif isinstance(kw_entry, str):
                    self._keyword_map[kw_entry.lower()] = (cat, 10)

    def extract(self, text: str) -> dict[str, list[tuple[str, float]]]:
        """
        Extract keywords from text, grouped by category.
        Returns: {category: [(keyword, weight), ...]}
        """
        text_lower = text.lower()
        found: dict[str, list[tuple[str, float]]] = {c: [] for c in self.CATEGORIES}

        for keyword, (cat, weight) in self._keyword_map.items():
            if keyword in text_lower:
                found[cat].append((keyword, weight))

        return {k: v for k, v in found.items() if v}

    def keyword_score(self, text: str) -> float:
        """Sum of all matched keyword weights."""
        total = 0.0
        for matches in self.extract(text).values():
            total += sum(w for _, w in matches)
        return total

    def top_category(self, text: str) -> tuple[str, float]:
        """Return the highest-scoring category and its score."""
        by_cat = self.extract(text)
        if not by_cat:
            return "unknown", 0.0
        best = max(by_cat.items(), key=lambda x: sum(w for _, w in x[1]))
        return best[0], sum(w for _, w in best[1])


if __name__ == "__main__":
    scorer = ScriptSimilarityScorer()
    extractor = KeywordExtractor()

    test_texts = [
        "Hai, tawaran pelaburan crypto dengan profit 30% sebulan. WhatsApp saya: +60123456789",
        "FREE RM50 untuk subscriber baru! Tekan link: https://bit.ly/free50",
        "Bantuan kerajaan RM500 akan diagihkan. Register di: https://bantuan-kerajaan.my/register",
    ]

    for t in test_texts:
        cat, score = extractor.top_category(t)
        matches = extractor.extract(t)
        print(f"\nText: {t[:60]}...")
        print(f"  Category: {cat} | Keyword score: {score}")
        print(f"  Matches: {matches}")
