"""
QueueHandler — Redis queue utilities for agent communication.

Queue names:
  raw_messages        — raw scraped messages from any platform
  extracted_entities  — extracted entities ready for scoring
  scored_entities     — scored entities ready for campaign detection
  alerts              — campaigns that breached threshold

Usage:
    q = QueueHandler()
    q.push_to_queue("raw_messages", json.dumps(data))
    item = q.pop_from_queue("raw_messages")  # returns str or None
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import redis
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("queue_handler")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QUEUE_PREFIX = "fraud_mvp:queue:"


class QueueHandler:
    """
    Redis-backed queue handler with json serialization.

    Uses LPUSH + RPOP (FIFO) pattern.
    """

    def __init__(self, redis_url: str = REDIS_URL):
        try:
            self.client = redis.from_url(redis_url, decode_responses=True)
            self.client.ping()
            log.info(f"Connected to Redis at {redis_url}")
        except redis.ConnectionError as e:
            log.warning(f"Redis unavailable ({e}) — running in no-op mode")
            self.client = None

    def _key(self, queue_name: str) -> str:
        return f"{QUEUE_PREFIX}{queue_name}"

    # ── Core queue ops ────────────────────────────────────────────────────────

    def push_to_queue(self, queue_name: str, data: str) -> bool:
        """LPUSH a JSON-encoded string to a queue. Returns True on success."""
        if self.client is None:
            return False
        try:
            self.client.lpush(self._key(queue_name), data)
            return True
        except redis.RedisError as e:
            log.error(f"Queue push failed: {e}")
            return False

    def push_to_queue_batch(self, queue_name: str, items: list[str]) -> int:
        """LPUSH multiple items. Returns count pushed."""
        if self.client is None or not items:
            return 0
        try:
            key = self._key(queue_name)
            self.client.lpush(key, *items)
            return len(items)
        except redis.RedisError as e:
            log.error(f"Batch push failed: {e}")
            return 0

    def pop_from_queue(self, queue_name: str, timeout: int = 0) -> Optional[str]:
        """
        Blocking pop (BRPOP) if timeout > 0, else immediate RPOP.
        Returns the item string or None.
        """
        if self.client is None:
            return None
        key = self._key(queue_name)
        try:
            if timeout > 0:
                result = self.client.brpop(key, timeout=timeout)
                return result[1] if result else None
            return self.client.rpop(key)
        except redis.RedisError as e:
            log.error(f"Queue pop failed: {e}")
            return None

    def peek_queue(self, queue_name: str, count: int = 10) -> list[str]:
        """LRANGE to peek at queue items without popping."""
        if self.client is None:
            return []
        try:
            return self.client.lrange(self._key(queue_name), -count, -1)
        except redis.RedisError as e:
            log.error(f"Queue peek failed: {e}")
            return []

    def get_queue_length(self, queue_name: str) -> int:
        """LLEN — number of items in queue."""
        if self.client is None:
            return 0
        try:
            return self.client.llen(self._key(queue_name))
        except redis.RedisError as e:
            log.error(f"Queue length failed: {e}")
            return 0

    def clear_queue(self, queue_name: str) -> bool:
        """Delete a queue entirely."""
        if self.client is None:
            return False
        try:
            self.client.delete(self._key(queue_name))
            return True
        except redis.RedisError as e:
            log.error(f"Queue clear failed: {e}")
            return False

    # ── Convenience ──────────────────────────────────────────────────────────

    def push_json(self, queue_name: str, obj: dict) -> bool:
        """Serialize a dict as JSON and push."""
        return self.push_to_queue(queue_name, json.dumps(obj, ensure_ascii=False))

    def pop_json(self, queue_name: str) -> Optional[dict]:
        """Pop and deserialize a JSON dict."""
        raw = self.pop_from_queue(queue_name)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.error(f"Invalid JSON in queue: {raw[:100]}")
            return None

    def drain_queue(self, queue_name: str, max_items: int = 1000) -> list[dict]:
        """Pop up to max_items from a queue, deserializing JSON."""
        results = []
        for _ in range(max_items):
            item = self.pop_json(queue_name)
            if item is None:
                break
            results.append(item)
        return results


if __name__ == "__main__":
    q = QueueHandler()
    q.push_json("test", {"hello": "world", "count": 42})
    q.push_json("test", {"msg": "second item"})
    print(f"Queue length: {q.get_queue_length('test')}")
    print(f"Peek: {q.peek_queue('test')}")
    item = q.pop_json("test")
    print(f"Popped: {item}")
    print(f"Remaining: {q.get_queue_length('test')}")
