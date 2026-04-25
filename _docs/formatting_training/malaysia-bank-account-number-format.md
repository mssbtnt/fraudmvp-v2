# Malaysia Bank Account Number Format
**Research Report — As of April 2026**

---

## 1. Overview

Malaysia does not use a single standardised bank account number format. Instead, each bank defines its own account number structure based on its internal systems and historical development. Account numbers typically range from **6 to 19 digits**, depending on the institution and account type (current, savings, loan, hire purchase, credit card, or e-wallet).

All inter-bank transfers in Malaysia are routed through **PayNet (Payments Network Malaysia Sdn Bhd)**, the national payments infrastructure operator. PayNet manages the key payment rails: **IBG (Interbank GIRO)**, **DuitNow**, **FPX**, **JomPAY**, and **MyDebit**.

---

## 2. Payment Rails & Their Relationship to Account Numbers

### 2.1 IBG — Interbank GIRO
- Scheduled (non-real-time) interbank fund transfer system.
- Requires the **full recipient bank account number**.
- Supports transfers across **42+ participating banks**.
- Processing windows are batch-based (multiple settlement cycles per day).

### 2.2 IBFT — Instant Interbank Fund Transfer
- Real-time, direct bank-to-bank transfer.
- Launched in 2006; requires the recipient's **full account number**.
- Still functional but largely superseded by DuitNow for new use cases.

### 2.3 DuitNow — Real-Time Payments Platform (RPP)
- Launched in December 2018 by PayNet, under Bank Negara Malaysia's initiative.
- Built on the **ISO 20022** messaging standard.
- Operates **24/7** with instant fund crediting.
- Allows transfers using a **DuitNow ID (proxy)** instead of a bank account number, or directly via account number.

**Supported DuitNow ID (Proxy) Types:**
| Proxy Type | Who Can Use It |
|---|---|
| Mobile Number | Individuals |
| MyKad / NRIC Number | Individuals |
| Passport Number | Foreign individuals |
| Army / Police Number | Security personnel |
| Business Registration Number (BRN) | Businesses / companies |

Each DuitNow ID can only be linked to **one bank account** at a time, though a single account can be linked to multiple IDs.

### 2.4 FPX — Financial Process Exchange
- Online payment gateway for e-commerce and government portals.
- Customer is redirected to their bank's portal to authorise payment.
- No direct account number entry by the payer — authentication is done via online banking credentials.

### 2.5 JomPAY
- Nationwide bill payment platform.
- Uses a **Biller Code** and **Reference Number** (Ref-1, Ref-2) — not a traditional bank account number.

---

## 3. Account Number Format by Bank (IBG & DuitNow Reference)

The following table is based on UOB's official **IBG & DuitNow Participating Bank Code & Account Length** reference, which consolidates data from PayNet's participating institutions. Both conventional and Islamic arms of each bank share the same bank code.

### 3.1 Local & Major Commercial Banks

| # | Bank | IBG Code | DuitNow Code | Current Acct | Saving Acct | Credit Card | Loan Acct | HP Acct |
|---|---|---|---|---|---|---|---|---|
| 1 | Affin Bank | 0232 | PHBMMYKL | 12 digits | 12 digits | 16 digits | 12 digits | 12 digits |
| 2 | Alliance Bank | 0212 | MFBBMYKL | 15 digits | 15 digits | 16 digits | 15 digits | 15 digits |
| 3 | AmBank | 0208 | ARBKMYKL | 13 digits | 13 digits | 16 digits | 13–14 digits | 14 digits |
| 4 | CIMB Bank | 0205 | CIBBMYKL | 10 or 14 digits | 10 or 14 digits | 16 digits | 10, 14, or 17 digits | 10, 12, or 17 digits |
| 5 | Hong Leong Bank | 0224 | HLBBMYKL | 11 or 13 digits | 11 or 13 digits | 15–16 digits | 11 or 13 digits | 11 or 13 digits |
| 6 | Maybank | 0227 | MBBEMYKL | 12 digits | 12 digits | 15–16 digits | 12 digits | 12 digits |
| 7 | Public Bank | 0233 | PBBEMYKL | 10 digits | 10 digits | 16 digits | 15 digits | 15 digits |
| 8 | RHB Bank | 0218 | RHBBMYKL | 14 digits | 14 digits | 16 digits | 14 digits | 12 digits |
| 9 | UOB Bank | 0226 | UOVBMYKL | 7, 9–14, or 17 digits | 10 or 11 digits | 16 digits | 10 or 15 digits | — |

### 3.2 Islamic Banks

| # | Bank | IBG Code | DuitNow Code | Current Acct | Saving Acct | Credit Card | Loan Acct | HP Acct |
|---|---|---|---|---|---|---|---|---|
| 1 | Bank Islam | 0245 | BIMBMYKL | 14 digits | 14 digits | 16 digits | 14 digits | 14 digits |
| 2 | Bank Muamalat | 0341 | BMMBMYKL | 14 digits | 14 digits | — | 14 or 17 digits | 14 or 17 digits |
| 3 | Bank Kerjasama Rakyat (Bank Rakyat) | 1602 | BKRMMYKL | 10 or 12 digits | 10 or 12 digits | 16 digits | 10 or 12 digits | 10 or 12 digits |
| 4 | Al Rajhi Bank | 0350 | RJHIMYKL | 15 digits | 15 digits | 16 digits | 17 digits | 17 digits |
| 5 | Kuwait Finance House (KFH) | 0346 | KFHOMYKL | 12 digits | 12 digits | 16 digits | 12 digits | 12 digits |

### 3.3 Government / Development Banks

| # | Bank | IBG Code | DuitNow Code | Current Acct | Saving Acct | Credit Card | Loan Acct | HP Acct |
|---|---|---|---|---|---|---|---|---|
| 1 | Bank Simpanan Nasional (BSN) | 1601 | BSNAMYK1 | — | 16 digits | 16 digits | 15 digits | 15 digits |
| 2 | Agrobank | 3306 | AGOBMYKL | — | 16 digits | — | 17 digits | — |
| 3 | MBSB Bank Berhad | 0352 | AFBQMYKL | 16 digits | 16 digits | — | 17 digits | 17 digits |

### 3.4 International Banks Operating in Malaysia

| # | Bank | IBG Code | DuitNow Code | Current Acct | Saving Acct | Credit Card | Loan Acct |
|---|---|---|---|---|---|---|---|
| 1 | HSBC Bank | 0222 | HBMBMYKL | 12–15 or 17 digits | 12 digits | 16 digits | 12–14 digits |
| 2 | Standard Chartered Bank | 0214 | SCBLMYKX | 12 digits (personal), 5–17 digits (corporate) | 12 digits | 16 digits | 8 digits |
| 3 | Citibank | 0217 | CITIMYKL | 9–16 digits (corporate) | — | — | — |
| 4 | OCBC Bank | 0229 | OCBCMYKL | 9–17 digits | 10 digits | 16 digits | 15 digits |
| 5 | Deutsche Bank | 0219 | DEUTMYKL | 10–17 digits | 10–17 digits | — | 10–17 digits |
| 6 | Bangkok Bank | 0204 | — | 13 digits | 13 digits | — | — |
| 7 | Bank of China | 0242 | BKCHMYKL | 13 or 15 digits | 13 or 15 digits | 16 digits | — |
| 8 | China Construction Bank | 0265 | PCBCMYKL | 12 digits | 12 digits | — | — |
| 9 | ICBC (Malaysia) | 0259 | ICBKMYKL | 19 digits* | 19 digits* | 16 digits | 19 digits* |
| 10 | Bank of America | 0207 | BOFAMY2X | 5–17 digits | 5–17 digits | — | — |
| 11 | BNP Paribas | 0263 | BNPAMYKL | 6–16 digits | — | — | 16 digits |
| 12 | JP Morgan Chase | 0215 | CHASMYKX | 10–17 digits | 10–17 digits | — | 10–17 digits |
| 13 | Mizuho Bank | 0261 | MHCBMYKA | 10 digits | — | — | — |
| 14 | MUFG Bank | 0210 | BOTKMYKX | 6 digits | 6 digits | — | 6 digits |
| 15 | Sumitomo Mitsui (SMBC) | 0262 | SMBCMYKL | 8 digits | — | — | — |

> **\*ICBC Special Rule:** The actual ICBC account number is 19 digits, prefixed with "01". For IBG transfers, the customer must omit the first two digits ("01") and enter only the subsequent 17 digits.
> Example: Actual account `01 29000 1000 0012 3456` → Enter for IBG: `29000 1000 0012 3456`

### 3.5 Digital Banks & E-Wallets (DuitNow Only)

Digital banks and e-wallets participate in DuitNow but **do not have IBG bank codes**. They support Pay-to-Proxy and/or Pay-to-Account-Number as noted.

| # | Institution | DuitNow Code | Saving Acct / E-Wallet | Type | Mode |
|---|---|---|---|---|---|
| 1 | AEON Bank | ACDBMYK2 | 13 digits | Digital Bank | Pay-to-Proxy & Pay-to-Account |
| 2 | Ryt Bank | SCCHMYKL | 10 digits | Digital Bank | Pay-to-Proxy & Pay-to-Account |
| 3 | KAF Digital Bank | KAFBMYK2 | 10 digits | Digital Bank | Pay-to-Proxy & Pay-to-Account |
| 4 | GX Bank Berhad | GXSPMYKL | 11, 13, or 14 digits | Digital Bank | Pay-to-Proxy & Pay-to-Account |
| 5 | Boost Bank Berhad | BOBEMYK2 | 12 digits | Digital Bank | Pay-to-Proxy & Pay-to-Account |
| 6 | TNG Digital (Touch 'n Go) | TNGDMYNB | 12 digits | E-Wallet | Pay-to-Proxy only |
| 7 | BigPay Malaysia | BGPYMYNB | 14 digits | E-Wallet | — |
| 8 | Boost eWallet | BOSTMYNB | 12 digits | E-Wallet | Pay-to-Account only |
| 9 | ShopeePay | ARPYMYNB | — | E-Wallet | Pay-to-Proxy only |
| 10 | GrabPay / Merchantrade Asia | MASBMYNB | 12 digits | E-Wallet | Pay-to-Proxy & Pay-to-Account |
| 11 | Setel Pay | SVSBMYNB | 12 digits | E-Wallet | Pay-to-Account only |
| 12 | Fass Payment Solutions | FSPYMYNB | 18 digits | E-Wallet | Pay-to-Proxy & Pay-to-Account |
| 13 | Finexus Cards | FNXSMYNB | 16 digits | E-Wallet | — |

---

## 4. Credit Card Number Format

Malaysian banks follow international card scheme standards for credit card numbers:

| Scheme | Digits | Banks |
|---|---|---|
| Visa / Mastercard | 16 digits | Most local banks |
| American Express | 15 digits | Maybank, Hong Leong Bank, Hong Leong Islamic |
| Mastercard (Bank Rakyat) | 16 digits | Bank Rakyat |

---

## 5. Key Structural Rules

1. **No leading zeros padding** — Account numbers are stored and entered as-is; formatting without dashes or spaces is standard for IBG/DuitNow.
2. **No national IBAN** — Malaysia does not use the IBAN (International Bank Account Number) format for domestic transfers. IBAN is only used for inbound cross-border EU payments at certain banks (e.g., CIMB for remittances from EU countries).
3. **Account type matters** — Loan and HP (Hire Purchase) accounts often have different digit lengths compared to current/savings accounts within the same bank.
4. **DuitNow ID is not an account number** — It is a proxy alias stored in PayNet's central directory that maps to an underlying account number. The underlying account number retains its bank-specific format.
5. **SWIFT/BIC codes** — For international wire transfers, each participating bank has a SWIFT/BIC code (as listed in the DuitNow Code column above, e.g., `MBBEMYKL` for Maybank).

---

## 6. Transaction Limits (DuitNow / IBG)

| Transfer Type | Typical Daily Limit | Notes |
|---|---|---|
| DuitNow (individual) | Up to RM 50,000/day (combined with IBG) | Free for transfers up to RM 5,000 |
| DuitNow (business) | Up to RM 10,000,000 per transaction | Fee may apply |
| DuitNow cross-border (MY–SG) | RM 3,000/day | Via PayNow-DuitNow linkage; 6 participating banks |
| IBG | Combined within RM 50,000/day limit | Batch settlement; not real-time |

---

## 7. Validation Logic for Developers / System Integrators

When building systems that accept Malaysian bank account numbers, the recommended validation approach:

1. **Identify the bank** — via IBG bank code or DuitNow BIC code.
2. **Identify the account type** — current, savings, loan, HP, or credit card.
3. **Apply the digit length rule** — validate against the known min/max digit range for that bank-type combination.
4. **Numeric-only** — all Malaysian bank account numbers are numeric (digits only, no alphabetic characters).
5. **Handle multi-length banks** — CIMB, UOB, HSBC, and others have multiple valid lengths. Use range validation, not exact match.
6. **ICBC special case** — strip the "01" prefix before IBG submission.

### Sample Regex Patterns (General Guide)

```
Maybank (Current/Savings/Loan):   ^\d{12}$
Public Bank (Current/Savings):    ^\d{10}$
CIMB (Current/Savings):           ^\d{10}$|^\d{14}$
Alliance Bank (All types):        ^\d{15}$
RHB (Current/Savings/Loan):       ^\d{14}$
```

> **Disclaimer:** Always verify account number acceptance with the respective bank's live system or PayNet's IBG validation API before processing transactions.

---

## 8. References

| Source | URL | Date |
|---|---|---|
| UOB — IBG & DuitNow Participating Bank Code & Account Length (Official PDF) | https://www.uob.com.my/assets/web-resources/business/pdf/ibg-duitnow-participating-bank.pdf | Accessed April 2026 |
| logmasuk.my — How Many Digits Is Bank Account Number In Malaysia 2026 | https://logmasuk.my/how-many-digits-is-bank-account-number-in-malaysia/ | December 2024 |
| PayNet / Billplz — Malaysia Payment Network Guide | https://main.billplz.com/blog/insights/paynet-malaysia-payment-network-guide | January 2026 |
| Lightspark — Instant Payments Malaysia: Rails, Fees | https://www.lightspark.com/knowledge/instant-payments-malaysia | October 2025 |
| Maybank — DuitNow Product Page | https://www.maybank2u.com.my/maybank2u/malaysia/en/personal/services/digital_banking/duitnow.page | Accessed April 2026 |
| HSBC — DuitNow Pay-to-Proxy FAQ | http://connect-content.us.hsbc.com/hsbc_pcm/onetime/2018/November/18_my_duitnow_faq.pdf | 2018 (foundational) |
| MBSB Bank — M Journey FAQ | https://www.mbsbbank.com/sites/default/files/2022-10/MJourneyonlinebankingFAQ_1.pdf | 2022 |

---

*Document compiled: April 2026. Data is subject to change — always confirm with the respective bank or PayNet before processing live transactions.*
