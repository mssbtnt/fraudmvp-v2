# ISSUE: Phone Numbers Misidentified as Bank Accounts — Cross-Type Deduplication Failure

## Alert Output (Original)

```
🔴 SCAM ALERT — Unknown Scam (CRITICAL)
📌 24 key entities flagged across 1 source
 └─ 📱 10 phones └─ 🏦 14 bank accounts

📋 What we found:
 └─ 📱 Australia +617900052144 (seen 47x)
 └─ 📱 Unknown +601161051865 (seen 47x)
 └─ 📱 Unknown +60163411403 (seen 47x)
 └─ 📱 Unknown +60142897177 (seen 47x)
 └─ 📱 Unknown +60142472412 (seen 47x)
 └─ 🏦 5128-0277-4281 (Savings/Current (Maybank, HSBC personal, Standard Chartered, AEON Bank, KAF, GX Bank, BSN card)) (seen 47x)
 └─ 🏦 17900052144 (Savings/Current (HLB some)) (seen 47x)
 └─ 🏦 26700077605 (Savings/Current (HLB some)) (seen 47x)
 └─ 🏦 1013-0411-0008 (Savings/Card (BSN savings, MBSB Bank, HP accounts)) (seen 47x)
 └─ 🏦 2644-4100-0225 (Savings/Current (Alliance Bank some, Bank Islam, Bank Muamalat, Bank Rakyat some, RHB, Al Rajhi some)) (seen 47x)
```

---

## Root Cause Analysis

### Problem 1: `BANK_ACCOUNT_RE` Matches Phone Numbers

**File:** `agents/extractor.py` — `BANK_ACCOUNT_RE = re.compile(r"\b\d{10,19}\b")`

This regex matches **any** 10–19 digit number, including phone numbers with country codes:

| Phone (with country code) | Digits | Length | Also matched by `BANK_ACCOUNT_RE`? |
|---|---|---|---|
| `+617900052144` (Australia) | `617900052144` | 12 | ✅ YES |
| `+601161051865` (Malaysia) | `601161051865` | 12 | ✅ YES |
| `+60163411403` (Malaysia) | `60163411403` | 11 | ✅ YES |

The **overlap zone** is 10–12 digits, where Malaysian/international phone numbers (with country code) and Malaysian bank accounts share the same digit length range.

### Problem 2: Cross-Type Dedup Only Checks Exact Match

**File:** `agents/extractor.py` — `add()` function, lines ~220–228:

```python
if len(digits) >= 9:
    for (prev_type, prev_val) in list(seen):
        if prev_type != type_ and self._digits(prev_val) == digits:
            return
```

This only deduplicates when `digits are EXACTLY equal`. It does NOT catch:
- **Substring containment**: phone `617900052144` contains bank `17900052144` as a substring
- **Country-code stripping**: phone `+617900052144` → national `7900052144` vs bank `17900052144`
- **Leading-zero variants**: phone `01790005214` vs bank `17900052144`

### Problem 3: Bank Prefix Validation Is Too Weak

**File:** `agents/extractor.py` — `_identify_bank()` method:

```python
def _identify_bank(self, account_digits: str) -> str | None:
    n = len(account_digits)
    for key_len in [4, 3]:
        prefix = account_digits[:key_len]
        if prefix in BANK_CODE_PREFIXES:
            return BANK_CODE_PREFIXES[prefix]
    if n == 12: return "Maybank"
    if n == 16: return "Bank Simpanan Nasional (BSN)"
    if n == 10: return "Public Bank (probable)"
    if n == 11: return "Hong Leong Bank (probable)"
    if n in (13, 14, 15): return f"Unknown (valid {n}-digit account)"
    return None
```

**Critical issue:** When `_identify_bank()` returns `None` (no matching prefix), the entity is **still added as a bank account**. The `add()` function doesn't reject entities with `bank_name=None`. This means any 10–19 digit number with no valid bank prefix is still classified as a bank account.

### Problem 4: Extraction Order Creates Asymmetric Dedup

**File:** `agents/extractor.py` — `extract_from_text()` method:

```python
# 1. BANK_ACCOUNT_RE runs FIRST
for m in BANK_ACCOUNT_RE.finditer(text):
    ...
    add("bank_account", val, val, bank_name=bank_name)

# 2. MY_PHONE_RE and PHONE_RE run SECOND
for m in MY_PHONE_RE.finditer(text):
    phone = self._normalize_phone(m.group())
    add("phone", phone, m.group())
for m in PHONE_RE.finditer(text):
    phone = self._normalize_phone(m.group())
    add("phone", phone, m.group())
```

Banks are extracted **before** phones. When a phone number like `617900052144` is matched by `BANK_ACCOUNT_RE` first, it's added as a bank account. Then when `PHONE_RE` matches it, the cross-type dedup checks `self._digits(prev_val) == digits` — but the bank was stored as `512802774281` (formatted) while the phone is `+617900052144` (normalized). The digit strings differ, so **both are kept**.

### Problem 5: No Phone Number Length/Country Validation

**File:** `agents/extractor.py` — `add()` function:

```python
# Guard: Malaysian phones are 9-12 digits max
if type_ == "phone" and len(digits) > 12:
    return
```

This guard only rejects phones > 12 digits. It does NOT validate that:
- A 12-digit number starting with `61` is a valid Australian phone (national: 7–15 digits)
- A 12-digit number starting with `60` is a valid Malaysian phone (national: 7–9 digits)
- A number starting with `01` or `1` could be a Malaysian mobile

### Problem 6: Alert Formatter Labels Invalid Banks with Generic Types

**File:** `services/alert_formatter.py` — `_identify_bank()` and `MALAYSIAN_ACCOUNT_LENGTHS`:

When a bank account has no valid prefix, the formatter falls back to `MALAYSIAN_ACCOUNT_LENGTHS` which maps length → generic type:

```python
12: "Savings/Current (Maybank, HSBC personal, Standard Chartered, AEON Bank, KAF, GX Bank, BSN card)"
11: "Savings/Current (HLB some)"
16: "Savings/Card (BSN savings, MBSB Bank, HP accounts)"
```

This gives **false credibility** to misidentified phone numbers by labeling them as plausible bank accounts.

---

## Specific Entity Analysis

| Entity | Digits | Length | Valid Bank Prefix? | Likely Identity | Problem |
|---|---|---|---|---|---|
| `+617900052144` (phone) | `617900052144` | 12 | N/A (phone) | Australian phone (+61) | Correctly identified as phone |
| `17900052144` (bank) | `17900052144` | 11 | ❌ `1790` not valid | **Same phone without +61** | Misidentified as bank; `1790` is not a bank prefix |
| `26700077605` (bank) | `26700077605` | 11 | ❌ `2670` not valid | Likely misidentified phone | `2670` is not a bank prefix |
| `5128-0277-4281` (bank) | `512802774281` | 12 | ❌ `5128` not valid | Likely misidentified phone | `5128` is not a bank prefix (closest: `0227`=Maybank) |
| `1013-0411-0008` (bank) | `101304110008` | 12 | ❌ `1013` not valid | Likely misidentified phone | `1013` looks like Malaysian mobile prefix `010` |
| `2644-4100-0225` (bank) | `264441000225` | 12 | ❌ `2644` not valid | Likely misidentified phone | `2644` is not a bank prefix |

**5 out of 5 "bank accounts" in the alert have NO valid Malaysian bank prefix.** They are almost certainly misidentified phone numbers or other numeric strings.

---

## Comprehensive Fix Plan

### Fix 1: Require Valid Bank Prefix for Bank Account Extraction (CRITICAL)

**File:** `agents/extractor.py` — `extract_from_text()`, bank extraction loop

**Current:**
```python
for m in BANK_ACCOUNT_RE.finditer(text):
    val = m.group()
    stripped = self._digits(val)
    if re.match(r"^6?01[2-9]\d{7,9}$", stripped): continue
    if not re.match(r"^(19|20)\d{2}$", stripped):
        bank_name = self._identify_bank(stripped)
        add("bank_account", val, val, bank_name=bank_name)
```

**Proposed:** Add a validation that rejects numbers without a valid bank prefix AND that look like phone numbers:

```python
for m in BANK_ACCOUNT_RE.finditer(text):
    val = m.group()
    stripped = self._digits(val)
    if re.match(r"^6?01[2-9]\d{7,9}$", stripped): continue  # already skips Malaysian phones
    if not re.match(r"^(19|20)\d{2}$", stripped):
        bank_name = self._identify_bank(stripped)
        # NEW: Reject if no valid bank prefix AND looks like a phone number
        if bank_name is None and self._looks_like_phone(stripped):
            log.debug(f"Rejected phone-like number as bank_account: {val}")
            continue
        add("bank_account", val, val, bank_name=bank_name)
```

### Fix 2: Add `_looks_like_phone()` Heuristic (CRITICAL)

**File:** `agents/extractor.py` — new method on `FraudExtractorAgent`

```python
def _looks_like_phone(self, digits: str) -> bool:
    """Check if a digit string is more likely a phone number than a bank account."""
    n = len(digits)
    
    # Malaysian phone: starts with 601, 01, or 1 (mobile)
    if re.match(r"^6?01[2-9]\d{7,9}$", digits):
        return True
    
    # International phone patterns (common scam source countries)
    # +61 (Australia), +65 (Singapore), +86 (China), +91 (India), +95 (Myanmar), +855 (Cambodia)
    international_prefixes = ["61", "65", "86", "91", "95", "855", "856", "62", "66", "63", "84", "81"]
    for prefix in sorted(international_prefixes, key=len, reverse=True):
        if digits.startswith(prefix) and 10 <= n <= 15:
            return True
    
    # Malaysian mobile without country code: 01x-xxxxxxx (10-11 digits)
    if re.match(r"^01[2-9]\d{7,8}$", digits):
        return True
    
    # Starts with 1 and is 10-11 digits (Malaysian mobile without leading 0)
    if digits.startswith("1") and 10 <= n <= 11:
        return True
    
    return False
```

### Fix 3: Enhanced Cross-Type Dedup with Country-Code Stripping (HIGH)

**File:** `agents/extractor.py` — `add()` function

**Current:** Only exact digit match:
```python
if len(digits) >= 9:
    for (prev_type, prev_val) in list(seen):
        if prev_type != type_ and self._digits(prev_val) == digits:
            return
```

**Proposed:** Also check after stripping common country codes:

```python
if len(digits) >= 9:
    for (prev_type, prev_val) in list(seen):
        if prev_type != type_:
            prev_digits = self._digits(prev_val)
            if prev_digits == digits:
                return
            # Also check after stripping country codes
            # If one is a phone with country code and the other is a bank,
            # strip the country code and compare national numbers
            if prev_type == "phone" and type_ == "bank_account":
                phone_national = self._strip_country_code(prev_digits)
                if phone_national and phone_national == digits:
                    return  # bank is same as phone's national number
            if prev_type == "bank_account" and type_ == "phone":
                bank_digits = prev_digits
                phone_national = self._strip_country_code(digits)
                if phone_national and phone_national == bank_digits:
                    return  # phone's national number matches bank
                # Also check if bank digits are contained in phone digits
                # (handles cases like phone +617900052144 vs bank 17900052144)
                if bank_digits in digits or digits in bank_digits:
                    return
```

### Fix 4: Add `_strip_country_code()` Helper (HIGH)

**File:** `agents/extractor.py` — new method

```python
COUNTRY_CODES = {
    "60": "Malaysia", "61": "Australia", "65": "Singapore", "62": "Indonesia",
    "63": "Philippines", "66": "Thailand", "86": "China", "91": "India",
    "95": "Myanmar", "855": "Cambodia", "856": "Laos", "81": "Japan",
    "82": "South Korea", "84": "Vietnam", "1": "US/Canada", "44": "UK",
}

def _strip_country_code(self, digits: str) -> str | None:
    """Strip international country code from digit string, return national number."""
    for code in sorted(self.COUNTRY_CODES.keys(), key=len, reverse=True):
        if digits.startswith(code):
            national = digits[len(code):]
            if 7 <= len(national) <= 15:  # reasonable national number length
                return national
    return None
```

### Fix 5: Require Bank Prefix Validation in Alert Formatter (MEDIUM)

**File:** `services/alert_formatter.py` — `_identify_bank()` and `format_alert()`

When `_identify_bank()` returns `("Unknown", None, type_hint)`, the alert should flag this as **unverified** rather than showing a generic bank type:

```python
if bank_name != "Unknown":
    bank_tag = f"({bank_name})"
else:
    if acct_type:
        bank_tag = f"({acct_type}, ⚠️ NO VALID BANK PREFIX)"
    else:
        bank_tag = "(⚠️ UNVERIFIED — may not be a bank account)"
```

### Fix 6: Use Phone Number Length Data for Validation (MEDIUM)

**File:** `agents/extractor.py` — load `_docs/data/phone-number-length-by-country-2026.json` and `_docs/data/phone-number-code-by-country-2026.json`

Use this data to:
1. Validate phone numbers against known country lengths (Malaysia: 7–9 national digits, Australia: 4–15, etc.)
2. Reject numbers that are valid phone lengths for their country code but NOT valid bank accounts
3. When a number could be either a phone or bank account, prefer phone classification if it matches a known country code pattern

### Fix 7: Improve `_is_plausible_phone()` and `_is_plausible_bank()` in Alert Formatter (LOW)

**File:** `services/alert_formatter.py`

Current `_is_plausible_bank()` accepts any 10–19 digit number. Add bank prefix validation:

```python
def _is_plausible_bank(digits: str) -> bool:
    if len(digits) < 10 or len(digits) > 19:
        return False
    # Check for valid Malaysian bank prefix
    for key_len in [4, 3]:
        if digits[:key_len] in MALAYSIAN_BANKS:
            return True
    # Accept known-length accounts even without prefix match
    if len(digits) in MALAYSIAN_ACCOUNT_LENGTHS:
        return True
    # Reject numbers that look like phone numbers
    if _is_plausible_phone(digits):
        return False
    return True
```

### Fix 8: Reorder Extraction — Phones Before Banks (LOW PRIORITY, RISKY)

**File:** `agents/extractor.py` — `extract_from_text()`

Currently banks are extracted before phones. If we extract phones first, then when a bank account regex matches the same digits, the cross-type dedup would catch it. However, this could cause **legitimate bank accounts that look like phone numbers** to be misclassified as phones. This is why **Fix 1 + Fix 2** (bank prefix validation) is preferred over reordering.

---

## Priority Summary

| Priority | Fix | Impact | Effort |
|---|---|---|---|
| 🔴 CRITICAL | Fix 1: Require valid bank prefix or pass phone heuristic | Eliminates ~80% of false bank accounts | Low |
| 🔴 CRITICAL | Fix 2: Add `_looks_like_phone()` heuristic | Catches phone-like numbers before they become banks | Low |
| 🟠 HIGH | Fix 3: Enhanced cross-type dedup with country-code stripping | Catches phone/bank pairs that differ by country code | Medium |
| 🟠 HIGH | Fix 4: Add `_strip_country_code()` helper | Required for Fix 3 | Low |
| 🟡 MEDIUM | Fix 5: Flag unverified banks in alert output | Prevents false confidence in alerts | Low |
| 🟡 MEDIUM | Fix 6: Use phone length data for validation | Data-driven validation | Medium |
| 🟢 LOW | Fix 7: Improve `_is_plausible_bank()` in formatter | Defense in depth | Low |
| 🟢 LOW | Fix 8: Reorder extraction (phones before banks) | Risky, could cause regressions | Medium |

---

## Quick Verification Test

After implementing fixes, verify with these test cases:

```python
# Should be classified as PHONE, not bank_account:
"+617900052144"  # Australian phone
"17900052144"    # Same phone without +61
"601161051865"   # Malaysian phone with country code
"01161051865"    # Malaysian phone local format

# Should be classified as BANK_ACCOUNT (valid prefix):
"512802774281"   # Wait — prefix 5128 is NOT valid! Should be phone or rejected
"022712345678"   # Maybank (prefix 0227) — VALID bank
"020512345678"   # CIMB (prefix 0205) — VALID bank
"1620123456789012" # BSN (16 digits) — VALID bank

# Edge cases:
"101304110008"   # Starts with 10 (Malaysian mobile prefix 010) — likely phone
"264441000225"   # No valid bank prefix — likely phone
```

----

# FIX MADE

