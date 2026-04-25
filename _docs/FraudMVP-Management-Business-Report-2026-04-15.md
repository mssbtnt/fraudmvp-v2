# FraudMVP Business Report for Top Management

**Prepared for:** Top Management  
**Date:** 15 April 2026  
**Prepared by:** Internal Product and Strategy Review  
**Document purpose:** Business-level summary of the FraudMVP opportunity, current problem landscape, solution direction, and management value

## 1. Executive Summary

Malaysia is facing a serious and growing scam problem. Scam losses have continued to rise, and the damage is no longer limited to individual victims. It affects customer trust, brand reputation, operational cost, regulatory pressure, and the wider digital economy.

FraudMVP is our response to this problem. It is an early-warning fraud intelligence system built to detect scam campaigns faster, connect suspicious entities across multiple sources, and deliver clear alerts that can support operational teams before more victims are affected.

In simple terms, FraudMVP helps us move from a reactive position to a proactive one. Instead of waiting for many victims to report the same scam, the system looks for repeated warning signs early, groups them into meaningful campaigns, and highlights what needs attention first.

This report explains:

- why the scam problem in Malaysia is urgent now
- what OpenClaw means in our product context
- how FraudMVP works in business terms
- what core value the solution offers
- why the solution is different from standard blacklist or complaint-based approaches

## 2. Current Problem Statement: Fraud and Scam in Malaysia

### Problem in Plain Language

Scams in Malaysia are becoming more frequent, more organised, and harder to stop using traditional methods.

Most scam cases do not begin with a bank transaction. They start much earlier through social platforms, messaging groups, fake websites, impersonation, and social engineering. By the time funds move, the scam has already matured and victims have already been convinced.

This creates a major gap:

- current action often starts after victims report losses
- scam operators change phone numbers, channels, bank accounts, and domains quickly
- warning signs are spread across different platforms and are rarely connected fast enough
- operational teams can see pieces of the problem, but not the full campaign

### Current Malaysia Context

Recent public information shows the problem is escalating:

- Malaysia recorded **RM1.57 billion** in online fraud losses in **2024**, with **35,368 cases**, according to Home Ministry and police data reported publicly in 2025.
- In **Q1 2025** alone, Bank Negara Malaysia cited **12,110 online fraud cases** involving **RM573.7 million** in losses.
- Public reporting in early **2026** stated that Malaysia’s online and financial fraud losses reached **RM2.77 billion in 2025**, the highest level in the last three years.
- Bank Negara Malaysia has also highlighted that about **95% of online fraud cases in Malaysia are authorised transactions**, meaning victims themselves are manipulated into sending money.

### What This Means for Organisations

This is not only a consumer problem. It is a business and ecosystem problem:

- fraud losses increase pressure on banks, wallets, fintechs, and regulators
- support, dispute, and investigation costs go up
- customers lose confidence in digital payments
- response teams are forced into manual, repetitive, high-volume work
- institutions risk being seen as slow, reactive, or disconnected

## 3. PAS View: Problem, Agitate, Solve

### Problem

Fraud in Malaysia is growing faster than traditional monitoring methods can handle.

### Agitate

If institutions rely only on blacklists, manual complaints, and post-incident review:

- scams will continue to spread before action is taken
- the same scam campaign may hit many victims across different channels
- teams will spend time chasing isolated cases instead of seeing connected patterns
- fraud response will stay expensive, slow, and mostly reactive

In short, the organisation keeps fighting yesterday’s scams while new scam campaigns are already live.

### Solve

FraudMVP addresses this gap by identifying suspicious entities and linking them into campaigns early. It is designed to detect patterns, not just isolated incidents. This creates earlier visibility, better prioritisation, and faster operational response.

## 4. What Is OpenClaw and How It Assists FraudMVP

Based on the repository design and product structure, **OpenClaw** is the collection-first intelligence approach that powers the front end of FraudMVP.

In business language, OpenClaw is the operating model that helps the system:

- continuously gather scam-related signals from multiple external sources
- standardise raw information into usable records
- feed downstream analysis automatically
- support modular growth as new sources or channels are added

Within FraudMVP, OpenClaw helps by acting as the system’s intake and discovery layer. It collects raw scam signals from selected web sources, government-linked alert lists, Telegram, and supporting community intelligence sources. This collected data is then handed to the rest of FraudMVP for extraction, scoring, campaign grouping, and alerting.

Why this matters to management:

- it reduces dependence on a single source of truth
- it creates a repeatable pipeline instead of ad hoc monitoring
- it supports scale as scam patterns and channels evolve
- it gives FraudMVP a stronger foundation for future expansion

Put simply, **OpenClaw helps FraudMVP see earlier, wider, and more consistently**.

## 5. Our Solution: What FraudMVP Provides

FraudMVP is a fraud intelligence and early-warning platform focused on scam detection relevant to Malaysia.

Its role is to help teams identify suspicious scam activity earlier and act with better context.

The solution provides:

- early collection of scam-related data from selected high-value sources
- automatic extraction of useful scam indicators such as phone numbers, bank accounts, websites, domains, and contact references
- grouping of repeated indicators into likely scam campaigns
- scoring and prioritisation so teams can focus on the highest-risk cases first
- alert delivery in a simple and operationally usable format

This means the system does not only answer, "Is this single item suspicious?" It also answers, "Is this part of a wider scam campaign that is spreading now?"

## 6. CAR View: Context, Action, Result

### Context

Malaysia’s scam environment is fast-moving, multi-channel, and highly dependent on manipulation of victims. Existing controls are improving, but many are still strongest after the payment stage or after victims file complaints.

### Action

FraudMVP collects scam-related signals, extracts meaningful indicators, links repeated entities across sources, scores likely campaigns, and delivers alerts for action.

### Result

The expected business result is a stronger early-warning capability that can:

- shorten time to detection
- improve fraud team focus
- reduce reliance on purely manual review
- support faster operational intervention
- strengthen confidence in fraud monitoring and reporting

## 7. FraudMVP Core Features

The current codebase shows the MVP already includes the following core capabilities:

| Core Feature | What It Means for Business Users |
| --- | --- |
| Multi-source monitoring | The system watches more than one source, reducing blind spots |
| Government alert list intake | FraudMVP uses Bank Negara Malaysia and Securities Commission-related alert data through OpenSanctions feeds |
| Telegram and web collection | The system is designed to gather scam signals from channels where scams often begin |
| Entity extraction | It pulls out useful indicators such as phone numbers, URLs, domains, emails, and bank-related references |
| Campaign detection | It groups repeated indicators into broader scam cases instead of treating each signal as separate |
| Risk scoring | It ranks what looks more dangerous so teams can focus on priority cases |
| Alerting | It sends operational alerts in a usable format for response teams |
| API visibility | It can expose system status, entities, campaigns, alerts, and source information through an API |
| Daily reporting | It supports structured reporting on whether alerts were found, no fresh data was available, or pipeline issues occurred |

## 8. Benefits to the Organisation

### Strategic Benefits

- Moves the organisation from reactive response to earlier detection
- Improves visibility across fragmented scam channels
- Builds a stronger local capability focused on Malaysian scam patterns
- Supports future integration into broader fraud operations

### Operational Benefits

- Reduces manual monitoring effort
- Helps investigators focus on the highest-risk campaigns first
- Improves consistency of alert handling
- Gives teams clearer evidence to support follow-up action

### Business Benefits

- Can help reduce fraud-related losses through earlier warning
- Can lower operational cost by improving triage and prioritisation
- Can support customer trust by showing proactive fraud protection
- Can strengthen regulatory and governance positioning through structured monitoring

## 9. Unique Selling Points

FraudMVP is not just another alert list or simple checker. Its main differentiators are:

### 1. Campaign-first detection

Most tools focus on a single suspicious item. FraudMVP is designed to spot connected scam behaviour across multiple indicators and sources.

### 2. Malaysia-relevant intelligence

The product is built around the local scam environment, including Malaysian alert sources, local entity patterns, and common fraud channels relevant to the market.

### 3. Earlier signal capture

FraudMVP is designed to look upstream, where scams are promoted and spread, instead of depending only on downstream complaints or payment disputes.

### 4. Clear operational output

The solution is built to produce usable alerts and summaries, not only raw technical logs.

### 5. Modular and scalable architecture

Because the system uses an OpenClaw-style collection approach and a staged processing pipeline, it can be expanded over time with more sources, rules, and integrations.

## 10. Why This Matters Now

Malaysia is already investing in stronger anti-scam coordination through NSRC, bank controls, mule-account enforcement, and the National Fraud Portal. That is positive, but it also raises the bar for market participants.

The next competitive advantage is not only responding faster after funds move. It is seeing scam campaigns earlier, before the damage becomes larger.

FraudMVP fits this gap well because it is designed to become an intelligence layer that can sit upstream of existing fraud operations.

## 11. Management Takeaway

The management case for FraudMVP is straightforward:

- the scam problem is growing and costly
- current methods still leave an early-detection gap
- FraudMVP addresses that gap with a practical, modular, Malaysia-focused intelligence approach
- OpenClaw strengthens the collection and intake side of the solution
- the MVP already shows the shape of a usable early-warning platform

FraudMVP should be viewed as a strategic capability, not only a technical experiment. Its value lies in helping the organisation detect scam campaigns earlier, act with better context, and build a more proactive fraud response model.

## 12. Recommended Management Position

Top management can position FraudMVP as:

- a proactive fraud intelligence initiative
- a localised scam monitoring capability for Malaysia
- an operational support tool for fraud, compliance, and risk teams
- a foundation for future integration with larger fraud prevention workflows

## 13. Suggested Presentation Closing

Fraud is no longer a problem that starts at the point of payment. It starts earlier, spreads faster, and moves across channels quickly. FraudMVP gives us a way to detect that movement sooner, understand it better, and respond with more confidence.

## 14. Sources and Basis

This report is based on two inputs:

### A. Internal codebase review

- [README.md](/home/mssbai/Desktop/fraud-mvp/README.md)
- [CLAUDE.md](/home/mssbai/Desktop/fraud-mvp/CLAUDE.md)
- [agents/collector.py](/home/mssbai/Desktop/fraud-mvp/agents/collector.py)
- [config/sources.yaml](/home/mssbai/Desktop/fraud-mvp/config/sources.yaml)
- [api/main.py](/home/mssbai/Desktop/fraud-mvp/api/main.py)
- [services/daily_report.py](/home/mssbai/Desktop/fraud-mvp/services/daily_report.py)

### B. External context used to validate the Malaysia fraud landscape

- Bank Negara Malaysia Annual Report 2025: https://www.bnm.gov.my/documents/20124/21185005/ar2025_en_ch1e.pdf
- Bank Negara Malaysia speech on IFCTF 2025 and National Fraud Portal: https://www.bnm.gov.my/-/spch-g-ifctf25
- Bank Negara Malaysia NFP launch page: https://www.bnm.gov.my/-/nfp-launch
- Bank Negara Malaysia Annual Report landing page: https://www.bnm.gov.my/bnm-annual-report
- Association of Banks in Malaysia scam awareness release: https://www.abm.org.my/press-releases/banking-industry-survey-revealed-high-public-awareness-on-scamswith-9-in-10-respondents-saying-that-they-read-scam-alerts-from-banks/
- Public reporting on 2024 and 2025 fraud losses:
  - https://www.thevibes.com/articles/news/112602/total-of-rm1.57-billion-lost-to-online-fraud-in-2024-up-84-from-previous-year
  - https://www.malaymail.com/news/malaysia/2025/10/16/malaysia-records-rm19b-in-scam-losses-as-online-fraud-cases-top-47000-says-deputy-minister/194811
  - https://www.mcpfpg.org/home-ministry-malaysias-online-fraud-surge-drains-rm2-77b-in-2025-the-highest-in-three-years/

## 15. Note on Interpretation

The explanation of **OpenClaw** in this report is an interpretation based on how the current repository describes the platform as "OpenClaw-based" and "OpenClaw-style" in the README and collector module. In this report, the term is used to describe the collection and intelligence-ingestion approach used by the product.
