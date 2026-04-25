# Phone / Bank Account Misidentification Fix — Summary

**Date:** 2026-04-10  
**Status:** ✅ Implemented & All Tests Passing (46/46)

---

## Problem Statement

The fraud alert system was misidentifying phone numbers as bank accounts, producing alerts like:

```
📱 Australia +617900052144 (seen 47x)
🏦 17900052144 (Savings/Current (HLB some)) (seen 47x)
🏦 26700077605 (Savings/Current (HLB some)) (seen 47x)
🏦 5128-0277-4281 (Savings/Current (Maybank, HSBC personal...)) (seen 47x)
🏦 1013-0411-0008 (Savings/Card (BSN savings, MBSB Bank, HP accounts)) (seen 47x)
🏦 2644-4100-0225 (Savings/Current (Alliance Bank some...)) (seen 47x)
```

**5 out of 5 "bank accounts" had no valid Malaysian bank prefix.** They were misidentified phone numbers or other numeric strings.

---

## Root Causes Identified

### 1. `BANK_ACCOUNT_RE` Matches Phone Numbers
- Regex `\b\d{10,19}\b` matches **any** 10–19 digit number
- Phone numbers with country codes (e.g., `+617900052144` = 12 digits) fall in the same range as Malaysian bank accounts (10–19 digits)
- **Overlap zone:** 10–12 digits where phones and banks look identical

### 2. Cross-Type Dedup Only Checks Exact Match
- `add()` function only deduped when `digits are EXACTLY equal`
- Missed pairs like phone `+617900052144` vs bank `17900052144` (same number, different country code representation)

### 3. `_identify_bank()` Returns Length-Based Guesses Without Valid Prefix
- 12-digit number → "Maybank" (guessed by length)
- 11-digit number → "Hong Leong Bank (probable)" (guessed by length)
- These guesses gave **false credibility** to misidentified phone numbers

### 4. Malaysian Mobile Prefixes 010/011 Excluded
- Regex patterns used `[2-9]` which excluded valid prefixes `010` and `011`
- Malaysian mobile prefixes range from `010` to `019`, all valid

### 5. Alert Formatter Labels Invalid Banks with Generic Types
- `MALAYSIAN_ACCOUNT_LENGTHS` mapped length → generic type label
- e.g., 12 digits → "Savings/Current (Maybank, HSBC personal, Standard Chartered, AEON Bank, KAF, GX Bank, BSN card)"
- This gave **false confidence** to misidentified phone numbers

### 6. Telco-Specific Mapping Despite Number Portability
- `MALAYSIAN_MOBILE_PREFIXES` mapped 2-digit prefixes to specific telcos (Maxis, Celcom, DiGi, etc.)
- In Malaysia, number portability means any prefix can be any telco — the mapping was misleading

---

## Specific Entity Analysis from Alert

| Entity | Digits | Length | Valid Bank Prefix? | Actual Identity | Problem |
|---|---|---|---|---|---|
| `+617900052144` (phone) | `617900052144` | 12 | N/A | Australian phone (+61) | Correctly identified as phone |
| `17900052144` (bank) | `17900052144` | 11 | ❌ `1790` not valid | Same phone without +61 | Misidentified as bank |
| `26700077605` (bank) | `26700077605` | 11 | ❌ `2670` not valid | Likely misidentified phone | No valid bank prefix |
| `5128-0277-4281` (bank) | `512802774281` | 12 | ❌ `5128` not valid | Likely misidentified phone | No valid bank prefix |
| `1013-0411-0008` (bank) | `101304110008` | 12 | ❌ `1013` not valid | Likely misidentified phone | Looks like Malaysian mobile `010` |
| `2644-4100-0225` (bank) | `264441000225` | 12 | ❌ `2644` not valid | Likely misidentified phone | No valid bank prefix |

---

## Changes Made

### `agents/extractor.py`

#### 1. Added `_looks_like_phone()` method
```python
def _looks_like_phone(self, digits: str) -> bool:
```
- Detects Malaysian mobile patterns (`6?01[0-9]`, `1[0-9]`, `01[0-9]`)
- Checks international country codes against `COUNTRY_CODES` dict
- Validates national number lengths against `PHONE_LENGTH_BY_CODE` data
- Returns `True` if digits match known phone patterns

#### 2. Added `_strip_country_code()` helper
```python
def _strip_country_code(self, digits: str) -> str | None:
```
- Strips known country codes (60, 61, 65, 86, 91, 95, 855, etc.) from digit strings
- Returns national number or `None` if no known country code found
- Used for cross-type dedup comparison

#### 3. Added `COUNTRY_CODES` dict
- Maps 30+ country codes to country names
- Used by `_looks_like_phone()` and `_strip_country_code()`
- Sorted by length (descending) for greedy matching (e.g., `855` before `85`)

#### 4. Added `PHONE_LENGTH_BY_CODE` data loader
```python
PHONE_LENGTH_BY_CODE: dict[str, tuple[int, int]] = _load_phone_length_data()
```
- Loads `_docs/data/phone-number-length-by-country-2026.json` and `_docs/data/phone-number-code-by-country-2026.json`
- Maps country codes → (min_length, max_length) for national phone numbers
- Used by `_looks_like_phone()` for data-driven validation

#### 5. Enhanced bank extraction to reject phone-like numbers
```python
# Before: bank_name = self._identify_bank(stripped)
#         add("bank_account", val, val, bank_name=bank_name)

# After:
bank_name = self._identify_bank(stripped)
has_valid_prefix = False
for key_len in [4, 3]:
    if stripped[:key_len] in BANK_CODE_PREFIXES:
        has_valid_prefix = True
        break
if self._looks_like_phone(stripped) and not has_valid_prefix:
    log.debug(f"Rejected phone-like number as bank_account: {val}")
    continue
add("bank_account", val, val, bank_name=bank_name)
```
- **Key insight:** Only accepts phone-like numbers as bank accounts if they have a **valid bank prefix** (not just a length-based guess)
- Numbers like `617900052144` (Australian phone) are now rejected because they have no valid prefix AND look like a phone

#### 6. Enhanced cross-type dedup with country-code stripping
```python
# Before: if prev_type != type_ and self._digits(prev_val) == digits: return

# After: Also checks:
# - Phone national number == bank digits (after stripping country code)
# - Significant substring overlap (>80% of shorter string)
```
- Catches pairs like phone `+617900052144` vs bank `17900052144`
- Phone national `7900052144` is contained in bank `17900052144`

#### 7. Fixed Malaysian mobile prefix regex
- Changed `[2-9]` to `[0-9]` in `_looks_like_phone()` and `BANK_ACCOUNT_RE` skip pattern
- Now correctly handles prefixes `010` and `011` (Maxis/Hotlink)

### `services/alert_formatter.py`

#### 8. Simplified `MALAYSIAN_MOBILE_PREFIXES`
```python
# Before: 50+ entries mapping to specific telcos
# "10": "Maxis/Hotlink", "11": "Maxis/Hotlink", "13": "Celcom/U Mobile", ...

# After: 10 entries, all mapped to "Malaysian mobile"
# "10": "Malaysian mobile", "11": "Malaysian mobile", ...
```
- Number portability means any prefix can be any telco
- Removed landline/satellite entries (31-39, 50, 55-69, 70-99, 88, 89)

#### 9. Enhanced `_is_plausible_phone()`
```python
# Before: Only checked 10-12 digit numbers starting with 1 or 6
# After: Also checks:
# - Malaysian mobile patterns (6?01[0-9], 1[0-9])
# - International country codes (855, 856, 95, 61, 65, etc.)
# - 10-11 digit numbers starting with 1
# - 12-digit numbers starting with 6
```

#### 10. Fixed `_is_plausible_bank()` check order
```python
# Before: Checked bank prefix → length → phone check (phone check came LAST)
# After:  Checks bank prefix → phone check → length (phone check BEFORE length acceptance)
```
- Numbers like `17900052144` (11 digits, starts with 1) are now correctly identified as phone-like
- Only numbers with valid bank prefixes bypass the phone-like check

#### 11. Flagged unverified banks in alert output
```python
# Before:
bank_tag = f"({acct_type})" if acct_type else ""

# After:
if bank_name != "Unknown":
    bank_tag = f"({bank_name})"
elif acct_type and is_plausible:
    bank_tag = f"({acct_type})"
elif acct_type and not is_plausible:
    bank_tag = f"({acct_type}, ⚠️ NO VALID BANK PREFIX)"
else:
    bank_tag = "(⚠️ UNVERIFIED)" if not is_plausible else ""
```
- Banks without valid prefixes are now flagged with `⚠️ NO VALID BANK PREFIX` or `⚠️ UNVERIFIED`

### `CLAUDE.md`

#### 12. Updated telco mapping reference
- Changed: `Phone carriers: 2-digit prefix lookup (MALAYSIAN_MOBILE_PREFIXES)`
- To: `Phone carriers: 2-digit prefix lookup (MALAYSIAN_MOBILE_PREFIXES) — simplified to "Malaysian mobile" since number portability means any prefix can be any telco`

### `tests/test_phone_bank_dedup.py` (New File)

27 tests covering:
- `TestLooksLikePhone` — 12 tests for Malaysian, Australian, Singapore, Myanmar, Cambodia phones + valid bank accounts
- `TestStripCountryCode` — 5 tests for country code stripping (MY, AU, SG, KH, none)
- `TestBankExtractionRejectsPhones` — 6 tests for extraction rejection of phone-like numbers + acceptance of valid banks
- `TestCrossTypeDedup` — 2 tests for cross-type dedup with country code differences
- `TestAlertFormatter` — 2 tests for `_is_plausible_bank` and `_is_plausible_phone`

---

## Test Results

```
46 passed in 0.62s

All existing tests (19) + new tests (27) pass.
No regressions detected.
```

---

## Data Sources Used

| File | Purpose |
|---|---|
| `_docs/data/phone-number-length-by-country-2026.json` | National phone number length ranges by country |
| `_docs/data/phone-number-code-by-country-2026.json` | Country calling codes for phone number validation |

These are loaded at module init time by `_load_phone_length_data()` and stored in `PHONE_LENGTH_BY_CODE`.

---

## Priority of Fixes Implemented

| Priority | Fix | Status |
|---|---|---|
| 🔴 CRITICAL | Bank extraction requires valid prefix for phone-like numbers | ✅ Done |
| 🔴 CRITICAL | `_looks_like_phone()` heuristic with country code detection | ✅ Done |
| 🟠 HIGH | Cross-type dedup with country-code stripping | ✅ Done |
| 🟠 HIGH | `_strip_country_code()` helper | ✅ Done |
| 🟡 MEDIUM | Flag unverified banks in alert output (⚠️ labels) | ✅ Done |
| 🟡 MEDIUM | Phone number length data loading for validation | ✅ Done |
| 🟢 LOW | `_is_plausible_bank()` improvement in formatter | ✅ Done |
| 🟢 LOW | Simplify `MALAYSIAN_MOBILE_PREFIXES` (number portability) | ✅ Done |

---

## Verification Checklist

After deploying, verify with these test cases:

| Input | Expected Type | Reason |
|---|---|---|
| `+617900052144` | phone | Australian phone (+61) |
| `17900052144` | **rejected** (not bank) | Phone-like, no valid bank prefix |
| `+601161051865` | phone | Malaysian mobile |
| `022712345678` | bank_account | Valid Maybank prefix (0227) |
| `020512345678` | bank_account | Valid CIMB prefix (0205) |
| `1620123456789012` | bank_account | Valid BSN (16 digits) |
| `101304110008` | **rejected** (not bank) | Starts with 10 (Malaysian mobile 010), no valid prefix |
| `264441000225` | **rejected** (not bank) | No valid bank prefix, phone-like |