"""
Alert Formatter — Formatting logic for Telegram fraud alert messages.

Exported symbols: MALAYSIAN_BANKS, MALAYSIAN_ACCOUNT_LENGTHS, MALAYSIAN_MOBILE_PREFIXES,
PHONE_RISK_CODES, format_alert, format_summary, send_telegram_message

Usage:
    from services.alert_formatter import format_alert, send_telegram_message
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import threading
import time
import yaml
from dotenv import load_dotenv

from services.campaign_types import campaign_type_label, normalize_campaign_type

load_dotenv()
log = logging.getLogger("alert_formatter")

DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN", "")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "")

# ─── Risk emoji & labels ───────────────────────────────────────────────────────

RISK_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "log_only": "⚪",
}

CAMPAIGN_TYPE_LABEL = {
    "investment": "Investment Scam",
    "job_task": "Job / Task Scam",
    "aid_gov": "Gov Aid Scam",
    "phishing": "Phishing Scam",
    "unknown": "Unknown Scam",
}


# ─── Malaysian Bank Codes ───────────────────────────────────────────────────────

MALAYSIAN_BANKS: dict[str, tuple[str, str, str]] = {
    "1601": ("Bank Simpanan Nasional (BSN)",     "BSNAMYK1", "savings/card"),
    "1602": ("Bank Rakyat",                      "BKRMMYKL", "current/savings"),
    "0204": ("Bangkok Bank",                     "BOTKMYKP", "current/savings"),
    "0205": ("CIMB Bank",                        "CIBBMYKL", "current/savings"),
    "0207": ("Bank of America",                  "BOFAMY2X", "current/savings"),
    "0208": ("AmBank",                           "ARBKMYKL", "current/savings"),
    "0210": ("MUFG Bank",                        "BOTKMYKX", "current/savings"),
    "0212": ("Alliance Bank",                     "MFBBMYKL", "current/savings"),
    "0214": ("Standard Chartered Bank",          "SCBLMYKX", "personal/corporate"),
    "0215": ("JP Morgan Chase",                   "CHASMYKX", "current/savings"),
    "0217": ("Citibank Malaysia",                 "CITIMYKL", "corporate"),
    "0218": ("RHB Bank",                         "RHBBMYKL", "current/savings"),
    "0219": ("Deutsche Bank",                     "DEUTMYKL", "current/savings"),
    "0222": ("HSBC Bank Malaysia",                "HBMBMYKL", "personal/corporate"),
    "0224": ("Hong Leong Bank",                  "HLBBMYKL", "current/savings"),
    "0226": ("UOB Bank Malaysia",                 "UOVBMYKL", "current/savings"),
    "0227": ("Maybank",                           "MBBEMYKL", "current/savings"),
    "0229": ("OCBC Bank Malaysia",                "OCBCMYKL", "current/savings"),
    "0232": ("Affin Bank",                        "PHBMMYKL", "current/savings"),
    "0233": ("Public Bank",                       "PBBEMYKL", "current/savings"),
    "0242": ("Bank of China",                     "BKCHMYKL", "current/savings"),
    "0245": ("Bank Islam",                        "BIMBMYKL", "current/savings"),
    "0259": ("ICBC Malaysia",                     "ICBKMYKL", "current/savings"),
    "0261": ("Mizuho Bank",                       "MHCBMYKA", "current/savings"),
    "0262": ("Sumitomo Mitsui (SMBC)",            "SMBCMYKL", "current/savings"),
    "0263": ("BNP Paribas",                        "BNPAMYKL", "current/savings"),
    "0265": ("China Construction Bank",            "PCBCMYKL", "current/savings"),
    "3306": ("Agrobank",                          "AGOBMYKL", "savings"),
    "0341": ("Bank Muamalat",                     "BMMBMYKL", "current/savings"),
    "0346": ("Kuwait Finance House (KFH)",        "KFHOMYKL", "current/savings"),
    "0350": ("Al Rajhi Bank",                     "RJHIMYKL", "current/savings"),
    "0352": ("MBSB Bank",                         "AFBQMYKL", "current/savings"),
    "ACDB": ("AEON Bank",                         "ACDBMYK2", "digital savings"),
    "SCCH": ("Ryt Bank",                          "SCCHMYKL", "digital savings"),
    "KAFB": ("KAF Digital Bank",                  "KAFBMYK2", "digital savings"),
    "GXSP": ("GX Bank Berhad",                    "GXSPMYKL", "digital savings"),
    "BOBE": ("Boost Bank Berhad",                 "BOBEMYK2", "digital savings"),
    "TNGD": ("Touch 'n Go Digital (TNG)",         "TNGDMYNB", "e-wallet"),
    "BGPY": ("BigPay Malaysia",                   "BGPYMYNB", "e-wallet"),
    "BOST": ("Boost eWallet",                     "BOSTMYNB", "e-wallet"),
    "ARPY": ("ShopeePay",                         "ARPYMYNB", "e-wallet"),
    "MASB": ("GrabPay / Merchantrade Asia",        "MASBMYNB", "e-wallet"),
    "SVS B": ("Setel Pay",                        "SVSBMYNB", "e-wallet"),
    "FSPY": ("Fass Payment Solutions",              "FSPYMYNB", "e-wallet"),
    "FNXS": ("Finexus Cards",                     "FNXSMYNB", "e-wallet"),
}

MALAYSIAN_ACCOUNT_LENGTHS: dict[int, str] = {
    10: "Savings/Current (Public Bank, CIMB some, Bank Rakyat some)",
    11: "Savings/Current (HLB some)",
    12: "Savings/Current (Maybank, HSBC personal, Standard Chartered, AEON Bank, KAF, GX Bank, BSN card)",
    13: "Savings/Current (HLB some, Bangkok Bank, Bank of China)",
    14: "Savings/Current (Alliance Bank some, Bank Islam, Bank Muamalat, Bank Rakyat some, RHB, Al Rajhi some)",
    15: "Savings/Current (Alliance Bank some, Al Rajhi Bank, Standard Chartered corporate)",
    16: "Savings/Card (BSN savings, MBSB Bank, HP accounts)",
    17: "Loan/HP (CIMB, Bank of America, various international banks)",
    18: "HP/Corporate (Fass Payment Solutions)",
    19: "Corporate/ICBC (ICBC actual — IBG strips '01' prefix → 17 digits)",
}

MALAYSIAN_MOBILE_PREFIXES: dict[str, str] = {
    # Malaysian mobile prefixes — number portability means any prefix can be any telco
    "10": "Malaysian mobile",  "11": "Malaysian mobile",
    "12": "Malaysian mobile",  "13": "Malaysian mobile",
    "14": "Malaysian mobile",  "15": "Malaysian mobile",
    "16": "Malaysian mobile",  "17": "Malaysian mobile",
    "18": "Malaysian mobile",  "19": "Malaysian mobile",
}

PHONE_RISK_CODES: dict[str, tuple[str, str, str]] = {
    "95":  ("Myanmar",         "critical", "Scam compound: pig butchering, romance, crypto fraud"),
    "855": ("Cambodia",         "critical", "Scam compound: pig butchering, investment fraud"),
    "856": ("Laos",            "critical", "Scam compound: Golden Triangle SEZ fraud"),
    "853": ("Macau",           "critical", "Macau scam: impersonates PDRM/BNM/LHDN"),
    "222": ("Mauritania",      "high",     "Wangiri/IRSF: one-ring premium rate fraud"),
    "232": ("Sierra Leone",    "high",     "Wangiri: FCC-cited robocall campaigns"),
    "233": ("Ghana",           "high",     "Wangiri/romance scam: FTC-cited"),
    "234": ("Nigeria",          "high",     "419 scam, romance fraud, BEC follow-up"),
    "243": ("DR Congo",         "high",     "High-cost IRSF termination destination"),
    "245": ("Guinea-Bissau",    "high",     "IRSF/Wangiri: high per-minute rates"),
    "226": ("Burkina Faso",     "high",     "IRSF/Wangiri: FCC-cited"),
    "228": ("Togo",             "high",     "IRSF revenue share schemes"),
    "235": ("Chad",             "high",     "Missed-call fraud campaigns"),
    "255": ("Tanzania",         "high",     "IRSF: victim-reported missed-call scam"),
    "257": ("Burundi",          "high",     "Carrier-level fraud reports"),
    "265": ("Malawi",           "high",     "Missed-call fraud campaigns"),
    "1268":("Antigua & Barbuda","high",    "NANP lookalike: FTC one-ring scam code"),
    "1284":("British Virgin Is.","high",   "NANP lookalike: FTC one-ring scam code"),
    "1345":("Cayman Islands",   "high",     "NANP lookalike: premium rate fraud"),
    "1473":("Grenada",          "high",     "NANP lookalike: FTC one-ring scam code"),
    "1649":("Turks & Caicos",   "high",     "NANP lookalike: FTC one-ring scam code"),
    "1664":("Montserrat",        "high",     "NANP lookalike: FTC one-ring scam code"),
    "1767":("Dominica",          "high",     "NANP lookalike: FTC one-ring scam code"),
    "1809":("Dominican Republic","high",    "NANP one-ring scam (very common)"),
    "1829":("Dominican Republic","high",    "NANP one-ring scam (alternate)"),
    "1849":("Dominican Republic","high",    "NANP one-ring scam (alternate)"),
    "1876":("Jamaica",           "high",     "NANP lookalike: FTC lottery scam code"),
    "4470":("United Kingdom (70-range)", "high", "UK premium rate; romance scam callbacks"),
    "91":  ("India",             "medium",   "Tech support scams, IRS impersonation, bank fraud"),
    "92":  ("Pakistan",          "medium",   "Missed-call fraud, phishing campaigns"),
    "7":   ("Russia/Kazakhstan","medium",   "Phishing, customer support impersonation"),
    "375": ("Belarus",           "medium",   "Missed-call and phishing campaigns"),
    "370": ("Lithuania",         "medium",   "FCC Wangiri: consumer fraud reports"),
    "381": ("Serbia",            "medium",   "Burst robocall campaigns"),
    "380": ("Ukraine",            "medium",   "VoIP infrastructure abuse by third parties"),
    "212": ("Morocco",           "medium",   "Wangiri/missed-call campaigns"),
    "213": ("Algeria",           "medium",   "Missed-call scam victim reports"),
    "216": ("Tunisia",           "medium",   "Wangiri fraud campaigns"),
    "20":  ("Egypt",             "medium",   "Romance scam phone follow-ups"),
    "44":  ("United Kingdom",    "low",      "Widely spoofed by India/scam operations"),
    "1":   ("US/Canada",         "low",      "Spoofed by international scam operations"),
    "61":  ("Australia",         "low",      "Spoofed in APAC-targeted campaigns"),
    "65":  ("Singapore",         "low",      "Generally low fraud; verify independently"),
    "62":  ("Indonesia",         "low",      "Some regional fraud; low density"),
    "66":  ("Thailand",          "low",      "Cross-border routing; some scam centres"),
    "63":  ("Philippines",       "medium",   "Call centre romance scams; pig butchering operations"),
    "86":  ("China",             "medium",   "Voice phishing targeting overseas Chinese communities"),
}


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_phone_country_info(e164: str) -> tuple[str, str, str]:
    """Return (country_name, country_code, country_flag_emoji) for a phone number."""
    digits = re.sub(r"\D", "", e164.lstrip("+"))
    for code, (name, risk, _) in sorted(PHONE_RISK_CODES.items(), key=lambda x: -len(x[0])):
        if digits.startswith(code):
            flag = f"\U0001F1F2\U0001F1FE"  # 🇲🇾 for MY fallback only
            if name == "Malaysia":
                flag = "\U0001F1F2\U0001F1FE"
            elif name == "Myanmar":
                flag = "\U0001F1F2\U0001F3E8"
            elif name == "Cambodia":
                flag = "\U0001F1F0\U0001F1ED"
            elif name == "Laos":
                flag = "\U0001F1F1\U0001F1ED"
            elif name == "Nigeria":
                flag = "\U0001F1F3\U0001F1EC"
            elif name == "India":
                flag = "\U0001F1EE\U0001F1F3"
            elif name == "Indonesia":
                flag = "\U0001F1EE\U0001F1E9"
            else:
                flag = "\U0001F3F3"
            return name, f"+{code}", flag
    return "Unknown", "", "\U0001F3F3"


def _get_malaysian_carrier(national_digits: str) -> str | None:
    if len(national_digits) < 3:
        return None
    prefix2 = national_digits[1:3]
    return MALAYSIAN_MOBILE_PREFIXES.get(prefix2)


def _parse_phone(value: str) -> tuple[str, str, str, str]:
    """Parse a phone into (national, e164, country_name, carrier)."""
    digits = re.sub(r"\D", "", value.lstrip("+"))
    if digits.startswith("6"):
        digits = digits[2:]
    national = digits
    if len(national) < 7:
        return value, value, "Unknown", None
    country_info = _get_phone_country_info(value)
    carrier = _get_malaysian_carrier(digits) if not country_info[1] or country_info[0] == "Malaysia" else None
    return national, value, country_info[0], carrier


def _format_phone(value: str) -> str:
    national, e164, country, carrier = _parse_phone(value)
    if len(national) >= 7:
        return f"{national[:3]}-{national[3:6]}-{national[6:]}"
    return e164


def _is_plausible_phone(digits: str) -> bool:
    """Check if a digit string looks like a phone number rather than a bank account."""
    if len(digits) < 9 or len(digits) > 15:
        return False
    # Malaysian mobile: +601x, 601x, 01x, or just 1x
    if re.match(r"^6?01[0-9]\d{7,8}$", digits):
        return True
    if re.match(r"^1[0-9]\d{7,9}$", digits):
        return True
    # International phone patterns (common scam source countries)
    international_prefixes = ["855", "856", "95", "61", "65", "62", "66", "63", "86", "91", "1", "44", "7", "20"]
    for prefix in sorted(international_prefixes, key=len, reverse=True):
        if digits.startswith(prefix) and 10 <= len(digits) <= 15:
            return True
    # 10-11 digit numbers starting with 1 (Malaysian mobile without leading 0)
    if len(digits) in (10, 11) and digits.startswith("1"):
        return True
    # 12-digit numbers starting with 6 (Malaysian/Asian international format)
    if len(digits) == 12 and digits.startswith("6"):
        return True
    return False


def _is_plausible_bank(digits: str) -> bool:
    if len(digits) < 10 or len(digits) > 19:
        return False
    # Check for valid Malaysian bank prefix (strong signal — always accept)
    for key_len in [4, 3]:
        if digits[:key_len] in MALAYSIAN_BANKS:
            return True
    # Reject numbers that look like phone numbers before accepting length-based matches
    if _is_plausible_phone(digits):
        return False
    # Accept known-length accounts even without prefix match (only if not phone-like)
    if len(digits) in MALAYSIAN_ACCOUNT_LENGTHS:
        return True
    return True


def _identify_bank(acct: str) -> tuple[str, str, str | None]:
    """Return (bank_name, swift_code, account_type_hint)."""
    digits = re.sub(r"\D", "", acct)
    for key_len in [4, 3]:
        prefix = digits[:key_len]
        if prefix in MALAYSIAN_BANKS:
            bank_name, swift, acct_type = MALAYSIAN_BANKS[prefix]
            return bank_name, swift, acct_type
    n = len(digits)
    type_hint = MALAYSIAN_ACCOUNT_LENGTHS.get(n)
    return "Unknown", None, type_hint


def _get_account_type_hint(acct: str) -> str | None:
    _, _, hint = _identify_bank(acct)
    return hint


def _format_bank_account(acct: str) -> str:
    digits = re.sub(r"\D", "", acct)
    if len(digits) >= 12:
        return f"{digits[:4]}-{digits[4:8]}-{digits[8:12]}"
    return acct


# ─── Semakmule checks ───────────────────────────────────────────────────────────
# (Stub implementations — replace with actual PDRM API calls in production)

def _check_semakmule_banks(accounts: list[str]) -> dict[str, int]:
    return {}


def _check_semakmule_phones(phones: list[str]) -> dict[str, int]:
    return {}


# ─── Actionable advice ─────────────────────────────────────────────────────────

SEMAKMULE_URL = "https://semakmule.rmp.gov.my"

def _action_advice(campaign: dict, semakmule_banks: dict = None) -> str:
    """Generate a short actionable advice paragraph."""
    entity_values = campaign.get("entity_values", [])
    has_bank = any(ev.get("type") == "bank_account" for ev in entity_values)
    has_phone = any(ev.get("type") == "phone" for ev in entity_values)

    lines = [
        "✅ <b>Verify at SemakMule:</b>",
        f"   {SEMAKMULE_URL}",
    ]
    if has_bank:
        lines.append("   • Paste bank account number → check if reported")
    if has_phone:
        lines.append("   • Paste phone number → check if reported")
    lines.append("")
    lines.append("📱 <b>Block calls/SMS</b> from unknown overseas numbers.")
    lines.append("🏦 <b>Never transfer</b> to an account that hasn't been verified.")
    lines.append("⚠️  <b>Report to PDRM</b> immediately if you already transferred.")
    return "\n".join(lines)


# ─── Formatters ────────────────────────────────────────────────────────────────

def _shorten_source(channel: str) -> str:
    """Truncate a channel/source name for display."""
    if len(channel) > 40:
        return channel[:37] + "..."
    return channel


def format_summary(count_by_risk: dict) -> str:
    """Format a summary line from a {risk_level: count} dict."""
    total = sum(count_by_risk.values())
    parts = []
    for risk in ["critical", "high", "medium", "low"]:
        n = count_by_risk.get(risk, 0)
        if n:
            emoji = RISK_EMOJI.get(risk, "⚪")
            parts.append(f"{emoji} {risk.upper()}: {n}")
    if not parts:
        parts = ["No alerts"]
    return f"Alerts: {total} total — " + " | ".join(parts)


def format_alert(campaign: dict) -> str:
    """
    Format a campaign dict into a user-friendly Telegram alert.
    """
    def _parse(val, default=None):
        if val is None:
            return default
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return default
        return val

    entity_ids = _parse(campaign.get("entity_ids"), [])
    channel_ids = _parse(campaign.get("channel_ids"), [])
    keywords = _parse(campaign.get("keywords"), [])
    entity_values = _parse(campaign.get("entity_values"), [])

    risk = campaign.get("risk_level", "unknown")
    ctype = normalize_campaign_type(campaign.get("campaign_type", "unknown"))
    emoji = RISK_EMOJI.get(risk, "⚠️")
    type_label = campaign_type_label(ctype)

    phones = [ev for ev in entity_values if ev.get("type") == "phone"]
    banks = [ev for ev in entity_values if ev.get("type") == "bank_account"]
    domains = [ev for ev in entity_values if ev.get("type") == "domain"]
    urls = [ev for ev in entity_values if ev.get("type") == "url"]
    emails = [ev for ev in entity_values if ev.get("type") == "email"]

    semakmule_verified_banks = _check_semakmule_banks([b["value"] for b in banks[:10]])
    semakmule_verified_phones = _check_semakmule_phones([p["value"] for p in phones[:10]])

    lines = []
    lines.append(f"{emoji} SCAM ALERT — {type_label} ({risk.upper()})")

    total_display = len(phones) + len(banks) + len(domains) + len(urls) + len(emails)
    summary_parts = []
    if phones:
        summary_parts.append(f"📱 {len(phones)} phone{'s' if len(phones) != 1 else ''}")
    if banks:
        summary_parts.append(f"🏦 {len(banks)} bank account{'s' if len(banks) != 1 else ''}")
    if domains:
        summary_parts.append(f"🌐 {len(domains)} domain{'s' if len(domains) != 1 else ''}")
    if urls:
        summary_parts.append(f"🔗 {len(urls)} URL{'s' if len(urls) != 1 else ''}")
    if emails:
        summary_parts.append(f"✉️  {len(emails)} email{'s' if len(emails) != 1 else ''}")

    summary = f"📌 {total_display} key entities flagged across {len(channel_ids)} source{'s' if len(channel_ids) != 1 else ''}"
    if summary_parts:
        summary += "\n └─ " + " └─ ".join(summary_parts)
    lines.append(summary)

    has_details = phones or banks or domains or urls or emails
    if has_details:
        lines.append("")
        lines.append("📋 What we found:")

        for p in phones[:5]:
            _, e164, country, _ = _parse_phone(p["value"])
            count_str = f" (seen {p['count']}x)" if p.get("count", 1) > 1 else ""
            sm_check = semakmule_verified_phones.get(p["value"])
            sm_suffix = f" [PDRM VERIFIED — {sm_check}x 🚨]" if sm_check else ""
            country_flag = f"🇲🇾 " if country == "Malaysia" else f"{country} "
            lines.append(f" └─ 📱 {country_flag}{e164}{count_str}{sm_suffix}")

        for b in banks[:5]:
            bank_name, swift, acct_type = _identify_bank(b["value"])
            fmt_acct = _format_bank_account(b["value"])
            count_str = f" (seen {b['count']}x)" if b.get("count", 1) > 1 else ""
            sm_check = semakmule_verified_banks.get(b["value"])
            sm_suffix = f" [PDRM VERIFIED — {sm_check}x 🚨]" if sm_check else ""
            b_digits = re.sub(r"\D", "", b["value"])
            is_plausible = _is_plausible_bank(b_digits)
            if bank_name != "Unknown":
                bank_tag = f"({bank_name})"
            elif acct_type and is_plausible:
                bank_tag = f"({acct_type})"
            elif acct_type and not is_plausible:
                bank_tag = f"({acct_type}, ⚠️ NO VALID BANK PREFIX)"
            else:
                bank_tag = "(⚠️ UNVERIFIED)" if not is_plausible else ""
            lines.append(f" └─ 🏦 {fmt_acct} {bank_tag}{count_str}{sm_suffix}")

        for d in domains[:5]:
            count_str = f" (seen {d['count']}x)" if d.get("count", 1) > 1 else ""
            lines.append(f" └─ 🌐 {d['value']}{count_str}")

        for u in urls[:5]:
            count_str = f" (seen {u['count']}x)" if u.get("count", 1) > 1 else ""
            lines.append(f" └─ 🔗 {u['value'][:60]}{'...' if len(u['value']) > 60 else ''}{count_str}")

        for e in emails[:3]:
            lines.append(f" └─ ✉️  {e['value']}")

    lines.append("")
    lines.append(_action_advice(campaign))

    if keywords:
        top_kw = ", ".join(keywords[:8])
        lines.append("")
        lines.append(f"🔍 <i>Matched: {top_kw}</i>")

    return "\n".join(lines)


# ─── Telegram delivery with rate limiting ────────────────────────────────────────

_log = logging.getLogger("alert_formatter")

# Module-level rate limiter: thread-safe, enforces minimum interval between sends.
class _TelegramRateLimiter:
    """Thread-safe rate limiter for Telegram Bot API sends.

    Enforces a minimum interval between consecutive sends and handles 429
    retry-after backoff automatically.
    """

    def __init__(self, min_interval: float = 1.0, max_retries: int = 3):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._last_send = 0.0

    def _throttle(self):
        """Block until min_interval has elapsed since last send."""
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_send)
            if wait > 0:
                time.sleep(wait)
            self._last_send = time.monotonic()

    def _parse_retry_after(self, response: httpx.Response) -> int:
        """Extract retry_after seconds from a 429 response.

        Tries parameters.retry_after first, then falls back to parsing
        the description string.
        """
        try:
            body = response.json()
            # Structured field (preferred)
            params = body.get("parameters", {})
            if isinstance(params, dict) and "retry_after" in params:
                return int(params["retry_after"])
            # Fallback: parse description
            desc = body.get("description", "")
            m = re.search(r"retry after (\d+)", desc, re.IGNORECASE)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return 30  # Safe default if we can't parse


_rate_limiter = _TelegramRateLimiter(min_interval=1.0, max_retries=3)


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> dict:
    """Send a message via Telegram Bot API with rate limiting and 429 retry.

    Enforces ≥1s between consecutive sends. On 429, reads retry_after
    from the response and sleeps before retrying (up to max_retries=3).
    Returns response dict or error dict.
    """
    limiter = _rate_limiter
    last_error = None

    for attempt in range(1 + limiter.max_retries):
        limiter._throttle()

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )

                # Handle 429 Too Many Requests
                if resp.status_code == 429:
                    retry_after = limiter._parse_retry_after(resp)
                    wait = retry_after + 1  # +1s buffer
                    _log.warning(
                        "Telegram 429 rate limit — sleeping %ds (retry_after=%d, attempt=%d/%d)",
                        wait, retry_after, attempt + 1, 1 + limiter.max_retries,
                    )
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp.json()

        except httpx.HTTPStatusError as e:
            try:
                err_body = e.response.json()
                tg_error = err_body.get("description", str(e))
                return {"error": tg_error, "status_code": e.response.status_code}
            except Exception:
                return {"error": str(e), "status_code": e.response.status_code}
        except Exception as e:
            last_error = e
            _log.warning("Telegram send failed (attempt %d): %s", attempt + 1, e)
            time.sleep(2)  # Brief pause before retry on non-429 errors

    # All retries exhausted
    return {"error": f"Failed after {limiter.max_retries + 1} attempts: {last_error}"}
