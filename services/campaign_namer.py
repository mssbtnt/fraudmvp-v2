"""
CampaignNamer — Auto-generate human-readable campaign names.

Naming patterns:
  {type}-{entity}       e.g., investment-TradeviewCapital
  {type}-{phone_last4}  e.g., macau-5678
  {type}-{domain}       e.g., phishing-maybank-my.com
  {type}-cluster-{id}   e.g., unknown-cluster-47

Names are sanitised for filesystem/URL safety and checked for collisions.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Optional

from db.database import Database
from services.campaign_types import campaign_type_label

log = logging.getLogger("campaign_namer")


class CampaignNamer:
    """Generate memorable, searchable campaign names."""

    def __init__(self, db: Database):
        self.db = db
        self._used_names: set[str] = set()
        self._load_existing_names()

    def _load_existing_names(self):
        """Load existing campaign names to avoid collisions (last 500)."""
        try:
            with self.db.conn() as conn:
                rows = conn.execute(
                    "SELECT name FROM campaigns "
                    "WHERE name IS NOT NULL AND name != '' "
                    "ORDER BY id DESC LIMIT 500"
                ).fetchall()
                self._used_names = {row["name"] for row in rows}
        except sqlite3.OperationalError:
            # Column doesn't exist yet (pre-migration)
            log.debug("Campaign 'name' column not found — names will be collision-free")
            self._used_names = set()

    def name_campaign(
        self,
        campaign_type: str,
        entity_values: list[dict],
        campaign_id: Optional[int] = None,
        cross_references: Optional[list[dict]] = None,
    ) -> str:
        """
        Generate a human-readable campaign name.
        
        Args:
            campaign_type: One of 10 canonical scam types
            entity_values: List of dicts with 'type', 'value', 'count'
            campaign_id: DB campaign ID (for fallback naming)
            cross_references: List of cross-reference match dicts
        
        Returns:
            Sanitised, unique campaign name
        """
        type_prefix = self._sanitise_type(campaign_type)
        
        # Strategy 1: Use cross-reference entity name (highest priority)
        if cross_references:
            for cr in cross_references:
                if cr.get("confidence", 0) >= 0.8:
                    name = f"{type_prefix}-{self._sanitise_entity(cr.get('entity_value', ''))}"
                    return self._ensure_unique(name)
        
        # Strategy 2: Use the most prominent entity (highest count)
        if entity_values:
            # Sort by count descending, then by entity type priority
            priority_order = [
                "company_name", "phone", "domain", "telegram_url",
                "whatsapp_link", "bank_account", "facebook_url", "email"
            ]
            
            # Sort entities: first by type priority, then by count
            sorted_entities = sorted(
                entity_values,
                key=lambda e: (
                    priority_order.index(e.get("type", "unknown"))
                    if e.get("type", "unknown") in priority_order
                    else 99,
                    -e.get("count", 1),
                ),
            )
            
            primary = sorted_entities[0]
            entity_type = primary.get("type", "unknown")
            entity_value = primary.get("value", "")
            
            # Format based on entity type
            if entity_type == "phone":
                # Use last 4 digits of phone
                phone_digits = re.sub(r'\D', '', entity_value)
                last4 = phone_digits[-4:] if len(phone_digits) >= 4 else phone_digits
                name = f"{type_prefix}-{last4}"
                
            elif entity_type == "domain":
                # Use domain name (strip protocol, www)
                domain = entity_value.lower()
                domain = re.sub(r'^https?://', '', domain)
                domain = re.sub(r'^www\.', '', domain)
                domain = domain.split('/')[0]  # Strip path
                name = f"{type_prefix}-{self._sanitise_entity(domain)}"
                
            elif entity_type == "company_name":
                name = f"{type_prefix}-{self._sanitise_entity(entity_value)}"
                
            elif entity_type in ("telegram_url", "whatsapp_link"):
                # Extract channel/group name
                channel = self._extract_channel_name(entity_value)
                name = f"{type_prefix}-{channel}"
                
            elif entity_type == "bank_account":
                # Use last 4 digits
                last4 = entity_value[-4:] if len(entity_value) >= 4 else entity_value
                name = f"{type_prefix}-bank-{last4}"
                
            elif entity_type == "facebook_url":
                # Extract page name from URL
                page = self._extract_facebook_name(entity_value)
                name = f"{type_prefix}-{page}"
                
            else:
                # Generic: use sanitised value
                name = f"{type_prefix}-{self._sanitise_entity(entity_value)}"
            
            return self._ensure_unique(name)
        
        # Strategy 3: Fallback to cluster ID
        if campaign_id:
            name = f"{type_prefix}-cluster-{campaign_id}"
        else:
            name = f"{type_prefix}-cluster"
        
        return self._ensure_unique(name)

    # ── Sanitisation helpers ────────────────────────────────────────────────

    def _sanitise_type(self, campaign_type: str) -> str:
        """Sanitise campaign type for use in name."""
        return campaign_type.lower().replace("_", "-").strip()

    def _sanitise_entity(self, value: str) -> str:
        """
        Sanitise entity value for use in campaign name.
        - Remove special characters
        - Replace spaces with hyphens
        - Truncate to 30 chars
        - Lowercase
        """
        if not value:
            return "unknown"
        
        # Remove protocol, common prefixes
        value = re.sub(r'^https?://', '', value)
        value = re.sub(r'^www\.', '', value)
        
        # Replace spaces and special chars
        value = re.sub(r'[\s/\\&%$#@!()*+=\[\]{}|<>;:",?\']+', '-', value)
        
        # Remove consecutive hyphens
        value = re.sub(r'-+', '-', value)
        
        # Strip leading/trailing hyphens
        value = value.strip('-')
        
        # Truncate
        if len(value) > 30:
            value = value[:30].rstrip('-')
        
        return value.lower()

    def _ensure_unique(self, name: str) -> str:
        """Append numeric suffix if name collides with existing campaign."""
        if name not in self._used_names:
            self._used_names.add(name)
            return name
        
        counter = 2
        while f"{name}-{counter}" in self._used_names:
            counter += 1
        
        unique_name = f"{name}-{counter}"
        self._used_names.add(unique_name)
        return unique_name

    def _extract_channel_name(self, url: str) -> str:
        """Extract channel/group name from Telegram URL or WhatsApp link."""
        # Telegram: t.me/channel_name or @channel_name
        match = re.search(r't\.me/([a-zA-Z0-9_]+)', url)
        if match:
            return self._sanitise_entity(match.group(1))
        
        # WhatsApp: wa.me/number or wasap.my/number
        match = re.search(r'(?:wa\.me|wasap\.my)/?\+?(\d+)', url)
        if match:
            phone = match.group(1)
            last4 = phone[-4:] if len(phone) >= 4 else phone
            return f"wa-{last4}"
        
        return self._sanitise_entity(url.split('/')[-1] if '/' in url else url)

    def _extract_facebook_name(self, url: str) -> str:
        """Extract page/profile name from Facebook URL."""
        # facebook.com/PageName
        match = re.search(r'facebook\.com/([a-zA-Z0-9_.]+)', url)
        if match:
            return self._sanitise_entity(match.group(1))
        return self._sanitise_entity(url)