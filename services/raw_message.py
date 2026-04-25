"""
Shared raw message contract for collector outputs.

All collectors should serialize the same envelope before persisting to
`scraped_messages` and publishing to Redis.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


def normalize_text(text: str) -> str:
    """Normalize free text before hashing."""
    return " ".join((text or "").lower().split())


def stable_message_hash(text: str, fallback_seed: str = "") -> str:
    """Create a stable hash from normalized text or a deterministic fallback."""
    normalized = normalize_text(text)
    seed = normalized or fallback_seed.strip()
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


@dataclass
class RawMessage:
    platform: str
    channel: str
    channel_id: str | None
    sender_id: str | None
    text: str
    member_count: int | None
    timestamp: str
    message_hash: str
    raw_json: str
    message_id: str | None = None

    def ensure_message_hash(self) -> "RawMessage":
        """Populate a stable message hash if the message is missing one."""
        if not self.message_hash:
            fallback_seed = "|".join(
                [
                    self.platform or "",
                    self.channel or "",
                    self.channel_id or "",
                    self.message_id or "",
                    self.timestamp or "",
                ]
            )
            self.message_hash = stable_message_hash(self.text, fallback_seed=fallback_seed)
        return self

    def to_dict(self) -> dict[str, Any]:
        self.ensure_message_hash()
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @staticmethod
    def from_json(data: str) -> "RawMessage":
        return RawMessage(**json.loads(data)).ensure_message_hash()

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "RawMessage":
        payload = dict(data)
        return RawMessage(**payload).ensure_message_hash()
