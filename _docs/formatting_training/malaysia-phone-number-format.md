# Malaysia Phone Number Format
**Research Report — As of April 2026**

---

## 1. Overview

Malaysian telephone numbers are regulated by the **Malaysian Communications and Multimedia Commission (MCMC)**. The numbering system follows an **open numbering plan** with a National Significant Number (NSN) length of 8 to 10 digits (excluding the country code).

The system distinguishes three primary number types:
- **Fixed-line (landline)** — geographically assigned, area-code based
- **Mobile** — carrier-assigned, 01X prefix
- **Special / non-geographic** — toll-free, premium rate, short codes, and service numbers

**Key identifiers:**
| Attribute | Value |
|---|---|
| Country Code | +60 |
| International Access Code (IDD) | 00 |
| Trunk Prefix (domestic) | 0 |
| Regulator | MCMC (Malaysian Communications and Multimedia Commission) |
| Numbering Plan Type | Open |
| NSN Length | 8–10 digits |
| Standard | E.164 (for international/system use) |

---

## 2. Number Structure

A Malaysian phone number is composed of four components:

```
[Country Code] [Trunk Prefix] [Area/Mobile Code] [Subscriber Number]
     +60             0            (1–2 digits)        (6–8 digits)
```

- The **trunk prefix `0`** is used for all domestic calls and is **dropped** when dialling internationally or using E.164 format.
- The **country code `+60`** replaces the leading `0` for international calls and E.164 format.

### Format Examples

| Type | Local (Domestic) | International / E.164 |
|---|---|---|
| Mobile (010–019) | `012-345 6789` | `+60 12-345 6789` |
| Mobile 011/015 (8-digit) | `011-1234 5678` | `+60 11-1234 5678` |
| Landline — KL (03) | `03-2345 6789` | `+60 3-2345 6789` |
| Landline — Penang (04) | `04-234 5678` | `+60 4-234 5678` |
| Landline — Kuching (082) | `082-23 4567` | `+60 82-23 4567` |
| Toll-Free | `1800-12-3456` | Not accessible from outside Malaysia |
| Local Rate | `1300-12-3456` | Not accessible from outside Malaysia |

---

## 3. Fixed-Line (Landline) Numbers

### 3.1 Structure
- **Area code:** 1 digit in Peninsular Malaysia (excluding the `0` prefix); 2 digits in East Malaysia (Sabah, Sarawak, Labuan)
- **Subscriber number:** 8 digits for area code `03` (Klang Valley); 7 digits for other Peninsular Malaysia areas; 6 digits for East Malaysia
- **Total number length (including `0`):** 10 digits for area code `03`; 9 digits for all other areas

### 3.2 Area Code Reference Table (Peninsular Malaysia)

| Area Code (with 0) | Region / State |
|---|---|
| `02` | *(Discontinued — formerly domestic access code to Singapore; discontinued July 2017)* |
| `03` | Selangor, Kuala Lumpur, Putrajaya, Genting Highlands (Pahang) |
| `04` | Perlis, Kedah, Penang, Pengkalan Hulu (Perak) |
| `05` | Perak, Cameron Highlands (Pahang), Hulu Bernam (Selangor) |
| `06` | Negeri Sembilan, Malacca, Muar, Tangkak, Batu Anam/Segamat (Johor) |
| `07` | Johor (except Muar & Ledang), Gemas (Negeri Sembilan) |
| `09` | Pahang, Terengganu, Kelantan |

### 3.3 Area Code Reference Table (East Malaysia & Special)

| Area Code (with 0) | Region |
|---|---|
| `080` | Domestic access code from East Malaysia to Brunei |
| `081` | Reserved for future use |
| `082` | Sarawak — Kuching, Samarahan, Serian |
| `083` | Sarawak — Sri Aman, Betong |
| `084` | Sarawak — Sibu, Sarikei, Mukah, Kapit |
| `085` | Sarawak — Miri, Limbang, Lawas |
| `086` | Sarawak — Bintulu, Belaga |
| `087` | Labuan, Interior Division (Sabah) |
| `088` | Sabah — Kota Kinabalu, Kudat |
| `089` | Sabah — Lahad Datu, Sandakan, Tawau |

> **Note:** Calls from Peninsular Malaysia to Brunei require the full international prefix `00673`. The `080` domestic access code for Brunei only works from East Malaysia.

### 3.4 Number Length Summary (Landline)

| Area Code | Subscriber Digits | Full Number Length (incl. trunk `0`) |
|---|---|---|
| `03` (Klang Valley) | 8 digits | 10 digits |
| `04`–`07`, `09` (Peninsular) | 7 digits | 9 digits |
| `08x` (East Malaysia) | 6 digits | 9 digits |

---

## 4. Mobile Numbers

### 4.1 Structure

All Malaysian mobile numbers begin with `01`, followed by one more digit (making a 3-digit mobile prefix, written as `01X`), then a subscriber number.

- **Prefixes 010, 012–014, 016–019:** Subscriber number is **7 digits** → Total national number = **10 digits** (incl. trunk `0`)
- **Prefixes 011, 015:** Subscriber number is **8 digits** → Total national number = **11 digits** (incl. trunk `0`)

Mobile calls always require **full national dialling** even between phones on the same network.

### 4.2 Mobile Prefix Allocation by Original Operator

> ⚠️ **Important:** Since Mobile Number Portability (MNP) was introduced on **1 October 2008**, these prefixes only indicate the **original** carrier assignment. The current operator of a number may differ. Always use a carrier lookup service for accurate routing.

> ⚠️ **Celcom–Digi Merger:** On **1 December 2022**, Celcom (Axiata) and Digi merged to form **CelcomDigi Berhad**, Malaysia's largest telco. Both brands continue operating under the merged entity.

| Prefix | Subscriber Digits | Original Carrier(s) |
|---|---|---|
| `010` | 7 | CelcomDigi (Celcom), XOX, Unifi Mobile (TM), Maxis, Tune Talk |
| `011` | 8 | Multiple — Maxis, U Mobile, CelcomDigi, Tune Talk, XOX, DiGi, Yes 4G, Telekom Malaysia, redONE, UniFi Mobile, and others |
| `012` | 7 | Maxis |
| `013` | 7 | CelcomDigi (Celcom) |
| `014` | 7 | Maxis (014-2, 014-7), DiGi (014-3, 014-6, 014-9), Tune Talk (014-4), CelcomDigi (014-5, 014-8) |
| `015` | 8 | Broadband/VoIP — DiGi, CelcomDigi, Onesmart, Telekom Malaysia (TM), Time Fibre, RedTone, and others |
| `016` | 7 | DiGi (now CelcomDigi) |
| `017` | 7 | Maxis |
| `018` | 7 | U Mobile, Yes 4G |
| `019` | 7 | CelcomDigi (Celcom) |

### 4.3 Active Mobile Network Operators (MNOs) as of April 2026

| Operator | Status | Notes |
|---|---|---|
| **CelcomDigi** | Active (merged Dec 2022) | Largest MNO; operates Celcom & Digi brands; prefixes 010, 013, 016, 019 (and shared 011, 014) |
| **Maxis / Hotlink** | Active | Operates prepaid under Hotlink brand; prefixes 012, 017 (and shared 011, 014) |
| **U Mobile** | Active | Operates 5G standalone network (launched Aug 2025); prefixes 018 (and shared 011) |
| **Unifi Mobile (TM)** | Active | Part of Telekom Malaysia; prefix 010 (shared range) and 011 |
| **Yes (YTL Communications)** | Active | 5G Advanced commercially launched; prefix 018 (shared) and 011 |

### 4.4 Active MVNOs (Mobile Virtual Network Operators) as of April 2026

| MVNO | Host Network |
|---|---|
| Tune Talk | CelcomDigi |
| XOX / OneXOX | CelcomDigi |
| redONE | CelcomDigi |
| Altel | CelcomDigi |
| Merchant Trade (Merchantrade) | — |

> **Yoodo** was **discontinued on 29 August 2024** as a condition of the Celcom-Digi merger.

---

## 5. Special & Non-Geographic Numbers

### 5.1 Service Number Formats

| Format | Type | Accessibility |
|---|---|---|
| `1300-XX-XXXX` | Local rate (caller pays local rate) | Within Malaysia only |
| `1800-XX-XXXX` | Toll-free (free from fixed line; local rate from mobile) | Within Malaysia only |
| `1700-XX-XXXX` | Personal numbering service | Within Malaysia only |
| `1900-XX-XXXX` | Multimedia / premium-rate service | Within Malaysia only |
| `600-XX-XXXX` | Audiotext / premium-rate (planned renumbering) | Within Malaysia only |

> **Note:** Toll-free (`1800`) numbers **cannot** be dialled from outside Malaysia. Dialling with `+60` prefix will not connect.

### 5.2 Emergency & Important Short Codes

| Code | Service |
|---|---|
| `999` | Malaysian General Emergency Service (MERS 999) — Police, Fire, Ambulance |
| `112` | International emergency number (works on all GSM networks including without SIM) |
| `994` | Fire brigade *(now replaced by 999)* |
| `991` | Civil Defence *(now replaced by 999)* |
| `997` | National Scam Response Centre (NSRC) |
| `15999` | Talian Kasih — emotional support & counselling |
| `1066` | Earthquakes and Tsunami Alert Centre |
| `103` | Fixed telephone line directory assistance |
| `108` | Operator assistance for international calls |

### 5.3 IDD (International Direct Dialling) Access Codes

| Code | Service | Carrier |
|---|---|---|
| `00` | Standard international prefix | All operators |
| `120` | Tune Talk IDD | Tune Talk |
| `1310` | U Mobile IDD | U Mobile |
| `13100` | Celcom Budget IDD | CelcomDigi |
| `13200` | Maxis IDD | Maxis |
| `13300` | DiGi IDD | CelcomDigi (Digi) |

---

## 6. E.164 Standard & Compliance

### 6.1 What is E.164?

E.164 is the ITU-T international standard for phone number formatting. All compliant numbers:
- Begin with `+` followed by the country code
- Contain digits only (no spaces, hyphens, or parentheses)
- Have a maximum length of 15 digits (country code + subscriber number)

**Malaysian E.164 format:**
```
+60[area/mobile code][subscriber number]
```

**Conversion rule:** Remove the trunk prefix `0`, then prepend `+60`.

| Local Format | E.164 Format |
|---|---|
| `012-345 6789` | `+60123456789` |
| `03-8765 4321` | `+60387654321` |
| `011-1234 5678` | `+601112345678` |
| `088-234 567` | `+60882234567` |

### 6.2 IRBM E-Invoice Compliance (Effective 12 April 2025)

Malaysia's **Inland Revenue Board (IRBM)** now mandates E.164 format for all phone numbers submitted in e-invoices via the **MyInvois** system. Requirements:
- Must start with `+`
- Must include country code `+60`
- **No spaces, hyphens, or parentheses** (e.g., `+60123456789`, not `012-345 6789`)
- Submissions with spaces or incorrect formatting will be **rejected**

This affects all businesses required to issue e-invoices under the phased rollout:
- Businesses with turnover > RM100M: from **1 August 2024**
- Turnover > RM25M to RM100M: from **1 January 2025**
- All other businesses: from **1 July 2025**

### 6.3 Database Storage Recommendation

Always store Malaysian phone numbers in E.164 format (`+60XXXXXXXXXX`) for:
- International compatibility
- Consistent validation and querying
- IRBM e-invoice compliance
- Integration with messaging APIs (WhatsApp, SMS, Twilio, etc.)

Store the human-readable local format in a separate field if needed for display purposes.

---

## 7. Validation Rules for Developers / System Integrators

### 7.1 Structural Rules Summary

| Type | Prefix | Subscriber Digits | Total Length (local, incl. 0) | Total Length (E.164, incl. +60) |
|---|---|---|---|---|
| Mobile (general) | `01[0,2-4,6-9]` | 7 | 10 | 11–12 |
| Mobile (011 / 015) | `011` or `015` | 8 | 11 | 13 |
| Landline — KL/Selangor | `03` | 8 | 10 | 12 |
| Landline — Peninsular (other) | `04`–`07`, `09` | 7 | 9 | 11 |
| Landline — East Malaysia | `08x` | 6 | 9 | 11 |

### 7.2 Regex Patterns

**Mobile numbers (local format):**
```regex
^01[0-9]-?\d{7,8}$
```

**Mobile numbers (E.164 format):**
```regex
^\+601[0-9]\d{7,8}$
```

**Landline numbers (local format):**
```regex
^0[3-9][0-9]?-?\d{6,8}$
```

**All Malaysian numbers (local format — general):**
```regex
^0[1-9][0-9]?-?\d{6,8}$
```

**All Malaysian numbers (E.164 — recommended for system storage):**
```regex
^\+60[1-9][0-9]{7,9}$
```

### 7.3 Conversion — Local to E.164 (Pseudocode)

```
1. Strip all spaces, hyphens, parentheses from the input
2. If number starts with '0': replace leading '0' with '+60'
3. If number starts with '60': prepend '+'
4. If number already starts with '+60': use as-is
5. Validate final string matches ^\+60[1-9][0-9]{7,9}$
```

### 7.4 Important Edge Cases

| Scenario | Handling |
|---|---|
| `011` and `015` prefixes | Subscriber number is 8 digits, not 7 — use `{7,8}` range in regex |
| MNP (number portability) | Prefix does not reliably identify current carrier — use lookup API if carrier routing is needed |
| Toll-free / 1800 numbers | Not in E.164 format; not dialable internationally; store separately if needed |
| East Malaysia area codes | Two-digit area codes (08x) — do not confuse with mobile prefix `08` (not allocated) |
| Legacy 015 VoIP/data-only numbers | May not receive voice calls — treat as data/broadband numbers |

---

## 8. 5G Network Context (April 2026)

Malaysia's 5G rollout is under a **dual-network model** (effective from Ministerial Direction No. 4 of 2024):

- **Network 1:** Digital Nasional Berhad (DNB) — wholesale 5G provider, wholly owned by Ministry of Finance. Launched 5G Advanced (5G-A) in partnership with Ericsson in February 2025.
- **Network 2:** U Mobile — second 5G network; launched 5G Standalone (SA) in August 2025; targeting 80% population coverage by H2 2026.

5G does not introduce new number prefixes — all 5G users retain their existing mobile numbers.

---

## 9. International Calling Context

### Calling Malaysia from Abroad

```
[Your country's exit code] + 60 + [Malaysian number without leading 0]
```

**Example (from US):** To call `03-2345 6789`:
```
011 + 60 + 3 + 2345 6789 = 011-60-3-2345-6789
```

**Example (from UK/Europe):** To call `012-345 6789`:
```
00 + 60 + 12 + 345 6789 = 0060-12-345-6789
```

Using a mobile phone with `+` support:
```
+60 + [number without leading 0]
```

### Calling from Malaysia to Singapore

Since July 2017, calls to Singapore require the full international prefix:
```
+65 [8-digit Singapore number]
```
The former domestic access code `02` has been fully discontinued.

### Calling from East Malaysia to Brunei

- **From East Malaysia:** `080` + [Brunei number] (domestic access code)
- **From Peninsular Malaysia:** `00673` + [Brunei number]

---

## 10. References

| Source | URL | Date |
|---|---|---|
| Wikipedia — Telephone Numbers in Malaysia | https://en.wikipedia.org/wiki/Telephone_numbers_in_Malaysia | Updated April 2026 |
| MCMC — Malaysian Communications and Multimedia Commission | https://www.mcmc.gov.my | Regulator (ongoing) |
| CallHippo — Malaysia Phone Number Format Guide | https://callhippo.com/blog/general/malaysia-phone-number-format | Updated March 2026 |
| Calilio — Malaysia Phone Number Format | https://www.calilio.com/blogs/malaysia-phone-number-format | February 2026 |
| sent.dm — Malaysia Phone Number Validation Guide | https://www.sent.dm/en/resources/phone-number-standards/my | May 2025 |
| Nebula ERP — IRBM e-Invoice Phone Number Requirement | https://nebulaerpsolution.com/5-mins-read-important-update-irbm-e-invoice-new-requirement-on-phone-number-format-effective-12-april-2025/ | April 2025 |
| Lightspark — Instant Payments Malaysia | https://www.lightspark.com/knowledge/instant-payments-malaysia | October 2025 |
| Opensignal — Malaysia Mobile Network Experience, Nov 2025 | https://insights.opensignal.com/reports/2025/11/malaysia/mobile-network-experience | November 2025 |
| U Mobile — Wikipedia | https://en.wikipedia.org/wiki/U_Mobile | Updated Feb 2026 |

---

*Document compiled: April 2026. Prefix allocations and operator assignments are subject to change. Always verify against MCMC's official numbering plan or use a real-time carrier lookup service for production systems.*
