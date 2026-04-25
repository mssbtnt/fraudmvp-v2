# International Phone Number Format: Scam & Fraud Patterns
**Research Report — As of April 2026**

> ⚠️ **Disclaimer:** This document is compiled for **awareness, fraud prevention, and system validation purposes only**. Country codes and number formats listed here are associated with scam activity based on regulatory reports and cybersecurity sources. Not every call from these origins is fraudulent — the underlying infrastructure is often abused via spoofing. Always verify independently before taking action.

---

## 1. Overview

Phone-based fraud is a global epidemic. Based on data compiled through early 2026:

- Over **56 million Americans** were impacted by scam calls in a single year, losing **USD 25.4 billion** (Truecaller Insights 2024)
- Malaysians lost **RM 54.02 billion** (approx. 3% of GDP) to scams in 2024, with **35,368 cases** reported — and 70% of victims never reporting at all
- In February 2025 alone, US consumers received approximately **4.5 billion robocalls**
- Ireland's regulator blocked over **131 million scam calls** between February 2023 and October 2025, with over **18 million blocked in September 2025** alone
- Global Anti-Scam Alliance (GASA) reports that Malaysians face an average of **140 scam attempts per person per year**, with 85% of adults exposed to such attempts

Scammers exploit the international phone numbering system (E.164) and VoIP infrastructure to impersonate trusted numbers, charge premium rates, and harvest personal data.

---

## 2. How International Phone Number Scams Work

### 2.1 Core Technical Mechanisms

#### Caller ID Spoofing
The most fundamental technique. Using VoIP services (e.g., SIP-based platforms, open-source software like Asterisk or FreeSWITCH), a scammer configures the displayed caller ID to be **any number they choose**, regardless of where the call actually originates. The originating VoIP provider often does not validate this data, so the falsified number is passed through the Public Switched Telephone Network (PSTN) to the recipient's phone.

- Tools: VoIP platforms, PRI lines, SIP providers, web-based spoofing services
- Cost: Very low — thousands of calls can be made per hour for minimal expense
- Detection: STIR/SHAKEN (a US/Canada authentication protocol) partially mitigates this, but is not globally adopted

#### Wangiri (One Ring and Cut) Scam
Originating in Japan (name means "one ring and cut" in Japanese), this scam uses automated dialers to:
1. Call thousands of numbers, each ringing only once before disconnecting
2. Induce curiosity — the victim sees a missed call from an "unknown international number"
3. The victim calls back → connected to a scammer-controlled **International Premium Rate Number (IPRN)**
4. The victim is billed at high per-minute international rates; the scammer earns a revenue share

A variant, **Wangiri 2.0**, targets businesses by submitting premium-rate numbers to online contact forms, hoping staff will call back.

#### International Revenue Share Fraud (IRSF)
The scammer rents an International Premium Rate Number (IPRN) from a local carrier in a jurisdiction with high termination rates, then routes calls to that number. They earn a portion of the call revenue billed to the victim's phone account. Often combined with CLI spoofing and Wangiri.

#### Vishing (Voice Phishing)
Scammers call posing as banks, government agencies, law enforcement, or tech support. They use:
- Pre-recorded IVR scripts to sound official
- Caller ID spoofed to match the legitimate institution's number
- Urgency and fear tactics ("your account has been compromised", "you are under investigation")
- AI deepfake voices and voice cloning (increasingly common from 2024 onward)

#### Neighbor Spoofing
Scammers spoof numbers that share the same area code or first few digits as the victim's own number, making the call appear local and trustworthy.

#### SIM Farming / Bulk SIM Acquisition
Scam operations acquire hundreds or thousands of legitimate SIM cards (often using fraudulent identities) in multiple countries to generate calls that appear to come from real, registered numbers, bypassing many spoofing filters.

---

## 3. High-Risk Country Codes Commonly Associated with Fraud

> ⚠️ **Important Caveat:** Due to caller ID spoofing, these country codes may appear on your device even if the call does not actually originate from that country. The code is often chosen to maximise per-minute charges or to appear deceptively local. Treat **any unexpected call from an unrecognised international number** with suspicion, regardless of origin.

### 3.1 West Africa — Wangiri & Premium Rate Fraud

| Country Code | Country | Notes |
|---|---|---|
| `+222` | Mauritania | Most cited in FCC Wangiri alerts; frequently used in one-ring campaigns targeting the US |
| `+232` | Sierra Leone | Flagged by FCC; used in burst robocall campaigns targeting US area codes |
| `+234` | Nigeria | Long-associated with advance fee fraud (419 scams), romance scams, business email compromise with phone follow-ups |
| `+233` | Ghana | Used in Wangiri and romance scam campaigns; FCC specifically cited West African country codes |
| `+245` | Guinea-Bissau | High-cost termination destination; used in IRSF and Wangiri |
| `+224` | Guinea | Less common but reported in IRSF routing |
| `+226` | Burkina Faso | Reported in premium-rate scam routing |
| `+228` | Togo | Used in IRSF revenue share schemes |
| `+235` | Chad | Reported in missed-call fraud campaigns |
| `+243` | DR Congo | High per-minute international rate; used in IRSF |
| `+255` | Tanzania | Reported in missed-call scam victim accounts |
| `+257` | Burundi | Flagged in carrier-level fraud reports |
| `+265` | Malawi | Flagged in missed-call fraud campaigns |

### 3.2 Caribbean — NANP-Lookalike Fraud

Caribbean nations participate in the **North American Numbering Plan (NANP)** with country code `+1`, using 10-digit numbers identical in format to US/Canada numbers. Scammers exploit this because victims may assume these are domestic calls.

| Area Code (within +1) | Country | Risk Profile |
|---|---|---|
| `+1-268` | Antigua & Barbuda | FTC-listed one-ring scam area code |
| `+1-284` | British Virgin Islands | FTC-listed one-ring scam area code |
| `+1-345` | Cayman Islands | Premium rate fraud routing |
| `+1-473` | Grenada | FTC-listed one-ring scam area code |
| `+1-649` | Turks & Caicos Islands | FTC-listed one-ring scam area code |
| `+1-664` | Montserrat | FTC-listed one-ring scam area code |
| `+1-767` | Dominica | FTC-listed one-ring scam area code |
| `+1-809` | Dominican Republic | FTC-listed; very common in US one-ring scam complaints |
| `+1-829` | Dominican Republic (alternate) | FTC-listed one-ring scam area code |
| `+1-849` | Dominican Republic (alternate) | FTC-listed one-ring scam area code |
| `+1-876` | Jamaica | FTC-listed; used in lottery scam phone operations |

> **Why This Matters:** When displayed without the `+1` prefix, `268`, `284`, `809`, `876` etc. look like ordinary US area codes. Many victims dial back without realising they are making an international call with premium charges.

### 3.3 Eastern Europe & Russia

| Country Code | Country | Notes |
|---|---|---|
| `+7` | Russia / Kazakhstan | Used for phishing, customer support impersonation, tech support scams; flagged by Cybernews and consumer protection agencies |
| `+375` | Belarus | Flagged in missed-call and phishing campaigns |
| `+370` | Lithuania | Cited in FCC Wangiri alert coverage |
| `+380` | Ukraine | VoIP infrastructure sometimes abused by third-party fraud operations |
| `+381` | Serbia | Reported in burst robocall campaigns (consumer victim reports) |

### 3.4 South & Southeast Asia

| Country Code | Country | Notes |
|---|---|---|
| `+91` | India | Major origin of tech support scams, IRS impersonation (targeting US victims), bank fraud, fake customer service calls |
| `+92` | Pakistan | Flagged in missed-call fraud and phishing campaigns |
| `+95` | Myanmar | Home to large-scale organised scam compound operations (pig butchering, romance scams targeting global victims) |
| `+855` | Cambodia | Major scam compound country; pig butchering and investment fraud operations |
| `+856` | Laos | Scam compound country; Golden Triangle Special Economic Zone operations |
| `+63` | Philippines | SCAM call centres; romance scam operations |
| `+66` | Thailand | Cross-border scam routing; some scam centres near Myanmar border |
| `+853` | Macau | Origin of "Macau Scam" impersonation tactic (impersonating police/government) |
| `+86` | China | Voice phishing targeting overseas Chinese communities; loan scams |

### 3.5 North Africa & Middle East

| Country Code | Country | Notes |
|---|---|---|
| `+212` | Morocco | Reported in Wangiri and missed-call campaigns |
| `+213` | Algeria | Reported by victim communities in missed-call scam accounts |
| `+216` | Tunisia | Flagged in missed-call fraud campaigns |
| `+20` | Egypt | Used in romance scam phone follow-ups |

### 3.6 United Kingdom & Western Europe (Spoofed/Abused)

| Country Code | Country | Notes |
|---|---|---|
| `+44` | United Kingdom | Heavily spoofed; scam operations (often originating in India or Southeast Asia) use `+44` to appear legitimate to UK victims; reported surge of spoofed `+44` calls in Ireland in late 2025 |
| `+44 70xxxx` | UK Personal Numbers | `+44 70` is a premium-rate range; commonly used in romance scam callback numbers and Wangiri |
| `+31` | Netherlands | Spoofed in European Wangiri campaigns |
| `+32` | Belgium | Cited in FCC Wangiri bulletin coverage |
| `+33` | France | Spoofed by scam operations targeting French-speaking communities |

### 3.7 Pacific / Oceania

| Country Code | Country | Notes |
|---|---|---|
| `+679` | Fiji | Reported in victim accounts of missed-call scams |
| `+685` | Samoa | Reported in missed-call scam accounts |

---

## 4. Scam Types & Associated Number Patterns

### 4.1 Macau Scam (Prevalent in Malaysia & Southeast Asia)

**How it works:** Callers impersonate Malaysian police (PDRM), Bank Negara Malaysia, customs, or health authorities. They claim the victim is under criminal investigation and demand immediate wire transfers or sensitive financial data.

**Number patterns observed:**
- Spoofed Malaysian landline numbers (e.g., `03-xxxx xxxx`) to appear as official government lines
- Spoofed numbers matching real PDRM or BNM hotline numbers
- International call-back numbers with `+853` (Macau) or `+86` (China) routing
- Malaysian mobile numbers (`01x-xxxxxxx`) acquired via SIM farming

**Scale (Malaysia 2025):** Telecom fraud and Macau scam led all categories with **28,698 incidents** and **RM 715 million in losses**.

### 4.2 Pig Butchering (殺豬盤) — Investment / Romance Scam

**How it works:** Scammers build prolonged fake romantic or friendship relationships online, then guide victims into fraudulent cryptocurrency investment platforms. Victims "invest" increasingly large sums before the platform vanishes.

**Number patterns observed:**
- WhatsApp or Telegram contact initiated via `+60`, `+65`, `+886` (Taiwan), or `+1` numbers
- Numbers are often real SIMs acquired by trafficked scam compound workers
- Calls/messages originate from Myanmar (`+95`), Cambodia (`+855`), Laos (`+856`), or Philippines (`+63`) but displayed numbers may be from any country

**Global scale:** Between 2020–2024, victims worldwide lost approximately **USD 75 billion** to Southeast Asian-based pig butchering scams.

### 4.3 Tech Support Scams

**How it works:** Callers claim to be from Microsoft, Apple, Google, or a telco. They claim the victim's device is infected or account compromised, requesting remote access or payment.

**Number patterns observed:**
- Heavily uses `+91` (India) as origin country, spoofed to appear as `+1` (US/Canada) or `+44` (UK)
- Spoofed Microsoft/Apple support line numbers
- Toll-free lookalike numbers (`1-800-xxx-xxxx`) spoofed

### 4.4 Government Impersonation / Tax Scams

**How it works:** Callers impersonate tax authorities (IRB/LHDN in Malaysia; IRS in USA; HMRC in UK), immigration (JIM), police, or customs. They threaten arrest or legal action unless payment is made immediately.

**Number patterns observed:**
- Spoofed local government agency hotlines
- `+91` origin (India-based call centres targeting US/UK/AU victims)
- Spoofed Malaysian `03-` landline numbers for Macau scam variant

### 4.5 Lottery / Prize Scams

**How it works:** Victim is told they've won a prize but must pay upfront fees to claim it. Often uses `+1-876` (Jamaica) numbers for targeting US victims.

**Number patterns observed:**
- `+1-876` (Jamaica) — specifically associated with lottery scams
- `+1-649` (Turks & Caicos)
- Spoofed local numbers with follow-up from international numbers

### 4.6 Romance Scams

**Number patterns observed:**
- First contact via WhatsApp, Telegram, or social media — often displaying `+44`, `+1`, or local Malaysian (`+60`) numbers
- Photos stolen from real social media profiles
- Pivot to video call refusals or deepfake video
- Eventual request involving international wire transfers or cryptocurrency

### 4.7 Job Scams & Forced Labour Recruitment

**How it works:** Victims are offered high-paying overseas jobs. Upon arrival, they are trafficked to scam compounds in Myanmar, Cambodia, or Laos and forced to operate phone scams themselves.

**Number patterns observed:**
- Recruitment via WhatsApp with local-looking numbers
- Job offer messages from `+60` (Malaysia) numbers controlled by syndicates
- Onward contact from `+95`, `+855`, or `+856` numbers once victim is in the compound

**Malaysia scale (2025):** Over **750 Malaysians rescued** from Myanmar/Cambodia compounds; **8,484 job scam cases** reported with RM 202.58 million in losses; 146% surge year-on-year.

---

## 5. How Scammers Obtain & Abuse Phone Numbers

| Method | Description |
|---|---|
| **Caller ID Spoofing** | VoIP software allows any number to be displayed as caller ID; no physical SIM required |
| **SIM Farming** | Bulk acquisition of real SIM cards using fraudulent identities to generate calls that bypass spoofing filters |
| **Data Breaches** | Stolen phone number lists from carrier portals, CRM databases, social media platforms traded on dark web markets |
| **Number Generation** | Automated tools randomly dial through a country's valid numbering range to find active numbers |
| **Social Engineering & Scraping** | Public directories, business listings, social media, WHOIS records harvested for phone numbers |
| **IPRN Rental** | Scammers legally rent International Premium Rate Numbers (IPRNs) from carriers in high-rate countries, then route victims there |
| **Online Form Abuse (Wangiri 2.0)** | Bots submit premium-rate numbers in business contact forms, hoping staff will return the call |
| **SIM Swap** | Fraudster convinces carrier to port victim's number to a new SIM, intercepting OTP/2FA codes |

---

## 6. Red Flags — Number Format Indicators

### 6.1 Universal Red Flags

| Signal | What It Suggests |
|---|---|
| Unknown international number rings once and disconnects | Classic Wangiri; do not call back |
| Caller claims to be from a government agency or bank | Almost always spoofed; verify independently |
| Number looks like a local number but has international routing cost | NANP Caribbean codes or spoofed local numbers |
| Call comes from a country you have no known contacts in | High suspicion |
| Caller requests you stay on the line (music, hold) | Maximising IPRN charges |
| WhatsApp/Telegram contact from unknown `+44` or `+1` number | Likely scam; UK/US numbers widely used for impersonation |
| Caller requests remote access, gift cards, or crypto payment | Almost always fraud |
| Caller ID shows a number identical to your bank or a known institution | Spoofed — hang up and call the official number directly |

### 6.2 Malaysia-Specific Red Flags

| Signal | What It Suggests |
|---|---|
| Call from `03-xxxx xxxx` claiming to be PDRM, BNM, or LHDN | Macau scam spoofing official lines |
| WhatsApp from `+60 1x` with investment opportunity in crypto | Pig butchering or investment scam |
| SMS from a "bank" containing a link — number is a `01x` mobile | Phishing; legitimate banks use short codes or landlines |
| Caller pressures you to stay on the line "for security" | Classic Macau scam tactic |
| Job offer via WhatsApp with overseas placement | Potential forced labour recruitment scam |
| `010` prepaid number claiming to be official institution | High suspicion; real government offices use landlines |

### 6.3 Premium-Rate Number Patterns to Avoid Calling Back

| Pattern | Description |
|---|---|
| `+44 70xx xxxxxx` | UK personal number range — premium rate; widely used in romance scam callbacks |
| `+1 900 xxx xxxx` | US premium-rate (900 numbers); not as common now but still exists |
| `+xx 9xx xxxxxx` | Many countries use 9xx prefixes for premium/special services |
| Any 3-digit code matching a Caribbean nation | `268, 284, 345, 473, 649, 664, 767, 809, 829, 849, 876` |
| `+222`, `+232`, `+234`, `+245` etc. | West African codes heavily used in IRSF |

---

## 7. The Southeast Asia Scam Compound Ecosystem

As of 2026, Southeast Asia has become the global epicentre of organised phone fraud, operating through industrial-scale forced-labour compounds:

| Country | Key Areas | Operations |
|---|---|---|
| **Myanmar** | Shan State, Karen State, Kayin State border areas | Largest compound concentration; pig butchering, romance scams, crypto fraud; estimated 100,000–120,000 people in forced labour |
| **Cambodia** | Sihanoukville, Phnom Penh outskirts | Pig butchering, investment fraud; some Chinese criminal groups displaced post-crackdown |
| **Laos** | Golden Triangle Special Economic Zone | Cross-border scam operations |
| **Philippines** | Metro Manila, Cebu | Call centres; romance scams |

**Phone number strategy of compound operations:**
- Workers are given scripted personas with phone numbers from multiple countries (`+1`, `+44`, `+60`, `+65`, `+852`, `+886`)
- Numbers sourced via SIM farming, VoIP rental, or stolen accounts
- WhatsApp and Telegram used as primary channels to avoid call-log scrutiny
- Calls spoofed through cascading VoIP providers across multiple jurisdictions to evade attribution

---

## 8. Regulatory & Technical Countermeasures

| Measure | Region | Details |
|---|---|---|
| **STIR/SHAKEN** | USA, Canada | Cryptographic call authentication standard; carriers must sign/verify caller ID; partially deployed |
| **Voice Firewall** | Ireland (ComReg) | AI/ML-based real-time call analytics to detect spoofed international numbers; deploying H1 2026 |
| **NSRC (National Scam Response Centre)** | Malaysia | Hotline `997`; coordinates between banks, PDRM, MCMC to freeze mule accounts and block scam calls |
| **SemakMule / CCID Portal** | Malaysia (PDRM) | Public portal to check if a phone number, bank account, or company name has been flagged for fraud |
| **Anti-Spoofing Measures (MCMC)** | Malaysia | MCMC directives requiring telcos to implement CLI authentication and block suspicious international spoofed calls |
| **ScamCheck (scamcheck.my)** | Malaysia | AI-powered free tool to verify if a phone number is associated with known scam activity |
| **Truecaller / Hiya / Nomorobo** | Global | Community-sourced caller ID apps that flag known scam numbers in real time |
| **FCC STIR/SHAKEN mandate** | USA | All major US carriers required to implement; reduces but does not eliminate spoofed calls |
| **Operation Northern Star** | Malaysia | Led to RM 3.17 billion in MBI Ponzi scheme assets seized |

---

## 9. What to Do If You Receive a Suspicious Call

1. **Do not answer** unknown international numbers you are not expecting — especially if you have no contacts in that country.
2. **Do not call back** a number that rang once and disconnected — this is the Wangiri trigger.
3. **Do not press any keys** on pre-recorded IVR prompts — this confirms your number is active.
4. **Do not share** any personal information, OTP, or financial details over an unsolicited call.
5. **Hang up immediately** if the caller claims to be from police, BNM, LHDN, or any government agency and demands immediate payment.
6. **Verify independently** — call the institution's official number (from their official website or the back of your card), not the number that called you.
7. **Report** the number:
   - Malaysia: **NSRC 997** or CCID/SemakMule portal (`ccid.rmp.gov.my`)
   - Malaysia (cyber incidents): **MyCERT** at `1-300-88-2999` or `cyber999@cybersecurity.my`
   - USA: FTC (`reportfraud.ftc.gov`) and FCC (`fcc.gov/complaints`)
   - UK: Action Fraud (`actionfraud.police.uk`)
8. **Block the number** and report to your carrier.
9. **Check your bill** for unexpected international charges.

---

## 10. Developer & System Integration Notes

When building fraud detection or phone number validation systems:

### Blocklist / Risk Scoring Logic

```
HIGH RISK — Flag for manual review or block:
- Country code: +222, +232, +233, +234, +245, +95, +855, +853
- NANP area codes: 268, 284, 345, 473, 649, 664, 767, 809, 829, 849, 876
- UK personal numbers: +44 70xxxxxxxx

MEDIUM RISK — Flag for awareness:
- Country code: +7, +91, +92, +375, +370, +381, +216, +212, +265, +257
- Unknown +44, +1 numbers initiating first contact via OTT (WhatsApp/Telegram)

CONTEXT-DEPENDENT:
- +60 (Malaysia) spoofed as government — flag if caller ID matches known agency number verbatim
- +86 (China), +63 (Philippines), +66 (Thailand) — legitimate but high fraud density
```

### Recommended Validation Libraries

| Library | Languages | Notes |
|---|---|---|
| `google/libphonenumber` | Java, JS, Python, C++ | Parses and validates E.164 format; can flag region |
| `twilio-lookup` | REST API | Real-time carrier lookup; identifies VoIP/virtual numbers |
| `abstract-api` Phone Validation | REST API | Flags line type (mobile/landline/VoIP) |
| Truecaller Business API | REST API | Community-sourced scam flagging data |

---

## 11. References

| Source | URL | Date |
|---|---|---|
| Cybernews — Common Scam Call Numbers | https://cybernews.com/identity-theft-protection/scam-call-numbers-what-they-are-how-to-spot-them-what-to-do/ | November 2025 |
| Panda Security — Scam Phone Numbers 2025 | https://www.pandasecurity.com/en/mediacenter/scam-phone-numbers/ | June 2025 |
| Chapman University — Understanding the One Ring Scam | https://blogs.chapman.edu/information-systems/2025/08/05/understanding-the-one-ring-scam/ | August 2025 |
| Neuralt — Wangiri Scam Overview | https://www.neuralt.com/news-insights/wangiri-scam-missed-call-from-unknown-or-international-number | April 2025 |
| TechRepublic — VoIP Fraud Tactics | https://www.techrepublic.com/article/voip-fraud/ | November 2024 |
| FBI Law Enforcement Bulletin — Investigating Scam Phone Calls | https://leb.fbi.gov/articles/featured-articles/investigating-scam-phone-calls | 2020 (foundational) |
| ScamWatchHQ — Malaysia Scams 2025 | https://scamwatchhq.com/malaysia-scams-2025-the-rm54-billion-crisis-where-macau-scams-romance-syndicates-and-human-trafficking-collide/ | January 2026 |
| BusinessToday — Biggest Scams In Malaysia 2025 | https://www.businesstoday.com.my/2025/12/24/biggest-scams-in-malaysia-in-2025/ | December 2025 |
| Malay Mail — Malaysians Face 140 Scam Attempts Per Year | https://www.malaymail.com/news/malaysia/2025/10/02/with-malaysians-each-facing-140-scam-bids-a-year-experts-call-for-urgent-and-concerted-response/193091 | October 2025 |
| Council on Foreign Relations — Myanmar Scam Centers | https://www.cfr.org/in-brief/how-myanmar-became-global-center-cyber-scams | May 2024 |
| ComReg Ireland — Voice Firewall & Scam Call Interventions | https://www.rte.ie/news/ireland/2025/1212/1548711-scam-phone-calls/ | December 2025 |
| FCC — Caller ID Spoofing | https://www.fcc.gov/consumers/guides/spoofing | Ongoing |
| FTC — One Ring Scam Area Codes | https://clark.com/scams-rip-offs/one-ring-scam-area-codes/ | FTC data referenced |
| MyCERT — Scam Call Impersonation Advisory | https://www.mycert.org.my/portal/advisory?id=MA-1028.022024 | February 2024 |
| NordProtect — Scam Numbers Reference | https://nordprotect.com/blog/scam-numbers/ | September 2025 |

---

*Document compiled: April 2026. Scam tactics, country codes, and fraud ecosystems evolve rapidly. This document should be reviewed and updated at least quarterly. Always cross-reference with live threat intelligence feeds and regulatory advisories for production systems.*
