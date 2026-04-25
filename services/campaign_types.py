"""
Canonical campaign-type mapping for FraudMVP.

Expanded from 5 to 10 canonical types in Phase 2:
- investment, job_task, aid_gov, phishing (original)
- loan_shark, romance, ecommerce, qr, macau (promoted from aliases)
- unknown (fallback)

The stored/API-facing campaign_type contract uses these 10 types.
Newer subtype labels from keyword extraction or LLM analysis are normalized
into this contract to avoid breaking DB constraints, alert formatting, or API
consumers.
"""

from __future__ import annotations

CANONICAL_CAMPAIGN_TYPES = {
    "investment",
    "job_task",
    "aid_gov",
    "phishing",
    "loan_shark",
    "romance",
    "ecommerce",
    "qr",
    "macau",
    "unknown",
}

CAMPAIGN_TYPE_ALIASES = {
    # Investment
    "investment": "investment",
    "investment_scam": "investment",
    "forex": "investment",
    "crypto": "investment",
    "stock_scam": "investment",
    "trading_scam": "investment",
    "ponzi": "investment",
    "pyramid": "investment",
    "skimming": "investment",
    # Job / Task
    "job_task": "job_task",
    "job_scam": "job_task",
    "deposit_scam": "job_task",
    "task_scam": "job_task",
    "commission_scam": "job_task",
    # Government Aid
    "aid_gov": "aid_gov",
    "government_aid": "aid_gov",
    "gov_aid": "aid_gov",
    "bantuan": "aid_gov",
    # Phishing
    "phishing": "phishing",
    "smishing": "phishing",
    "vishing": "phishing",
    "bank_phishing": "phishing",
    "clone_website": "phishing",
    # Loan Shark
    "loan_shark": "loan_shark",
    "ah_long": "loan_shark",
    "illegal_lending": "loan_shark",
    "usury": "loan_shark",
    "pinjaman": "loan_shark",
    # Romance
    "romance": "romance",
    "romance_scam": "romance",
    "love_scam": "romance",
    "sweetheart_scam": "romance",
    "sugar_daddy": "romance",
    # E-Commerce
    "ecommerce": "ecommerce",
    "shopping_scam": "ecommerce",
    "online_purchase_scam": "ecommerce",
    "marketplace_scam": "ecommerce",
    "cod_scam": "ecommerce",
    # QR
    "qr": "qr",
    "qr_scam": "qr",
    "qr_code_scam": "qr",
    # Macau
    "macau": "macau",
    "macau_scam": "macau",
    "call_center_scam": "macau",
    # Unknown / fallback
    "other": "unknown",
    "urgency": "unknown",
}

CAMPAIGN_TYPE_LABELS = {
    "investment": "Investment Scam",
    "job_task": "Job / Task Scam",
    "aid_gov": "Government Aid Scam",
    "phishing": "Phishing Scam",
    "loan_shark": "Loan Shark / Ah Long",
    "romance": "Romance / Love Scam",
    "ecommerce": "E-Commerce Scam",
    "qr": "QR Code Scam",
    "macau": "Macau Scam",
    "unknown": "Unknown Scam",
}

CAMPAIGN_TYPE_DESCRIPTIONS = {
    "investment": "Promises of high returns on investments in forex, crypto, stocks, or other financial instruments.",
    "job_task": "Fake job offers or task-based scams requiring upfront deposits.",
    "aid_gov": "Impersonates government aid programmes to collect personal data or money.",
    "phishing": "Fake bank portals, login pages, or OTP requests to steal credentials.",
    "loan_shark": "Illegal money lenders (Ah Long) offering quick loans with exorbitant interest.",
    "romance": "Online relationship scams to extract money through emotional manipulation.",
    "ecommerce": "Online purchase scams where goods are never delivered or are counterfeit.",
    "qr": "Malicious QR codes that redirect to phishing pages or fake payment portals.",
    "macau": "Call center scams impersonating authorities to extort money through fear.",
    "unknown": "Suspicious activity that doesn't fit any known scam category.",
}

CAMPAIGN_TYPE_SEVERITY = {
    "investment": "critical",
    "macau": "critical",
    "phishing": "critical",
    "loan_shark": "high",
    "romance": "high",
    "job_task": "high",
    "aid_gov": "high",
    "qr": "high",
    "ecommerce": "medium",
    "unknown": "low",
}


def normalize_campaign_type(value: str | None) -> str:
    """Normalize a campaign type string to one of the 10 canonical types."""
    if not value:
        return "unknown"
    normalized = CAMPAIGN_TYPE_ALIASES.get(value.strip().lower(), "unknown")
    return normalized if normalized in CANONICAL_CAMPAIGN_TYPES else "unknown"


def campaign_type_label(value: str | None) -> str:
    """Get human-readable label for a campaign type."""
    normalized = normalize_campaign_type(value)
    return CAMPAIGN_TYPE_LABELS.get(normalized, "Unknown Scam")


def campaign_type_description(value: str | None) -> str:
    """Get description for a campaign type."""
    normalized = normalize_campaign_type(value)
    return CAMPAIGN_TYPE_DESCRIPTIONS.get(normalized, "Unclassified scam activity.")


def campaign_type_severity(value: str | None) -> str:
    """Get default severity for a campaign type."""
    normalized = normalize_campaign_type(value)
    return CAMPAIGN_TYPE_SEVERITY.get(normalized, "low")