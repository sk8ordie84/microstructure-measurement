# Case Study A — Prediction Market Data Pipeline

**Collection, scoring, and outcome calibration for a binary prediction market exchange**

---

## Problem

Prediction market data arrives in unstructured form across multiple API endpoints with no native infrastructure for systematic analysis. Event titles are inconsistent. Markets for the same underlying event are not grouped. There is no time-series layer for tracking how markets evolve between scans. Without a purpose-built pipeline, the data is analytically unusable at scale.

Specific gaps addressed:
- No cross-event grouping (multiple markets per event had to be discovered and linked manually)
- No category-aware fetching (API returns a flat global pool; domain filtering required custom logic)
- No outcome tracking infrastructure (resolved markets needed to be captured and deduped before analysis was possible)
- No calibration layer (scoring systems without outcome measurement are unfalsifiable)

---

## What was built

**Collection layer**
- Gamma API client with category-aware fetching across 6 topic categories, each with configurable liquidity floors and CLOB slot budgets
- Two-pass allocation: Pass 1 fills per-category reserves; Pass 2 fills remaining capacity from the merged pool sorted by days remaining
- Each candidate carries `intake_source` (primary or category) and `intake_tags` (list of matched category keys)
- Deduplication by market slug across the merged pool

**Scoring engine**
- Multi-factor `daily_score`: days remaining, liquidity depth, effective spread, price momentum
- Tier classification: A / B / C by configurable thresholds in `config.json`
- Label assignment: ACTIONABLE / WATCH / THIN by CLOB depth and spread criteria
- All parameters externalized — no magic numbers in code

**Event graph**
- Relational structure connecting markets → events → clusters
- 4 edge types: `same_cluster` (0.9), `complement` (0.85), `same_domain_week` (0.6), `topic_bridge` (0.5)
- Graceful degradation: client-side graph construction from daily data when backend file is absent
- Signal lifecycle tracking: per-slug state machine across dated daily snapshots (7 states: new, stable, strengthening, fading, persistent, recurring, re-entered)

**Validation and calibration framework** *(see Case Study C for full detail)*
- 3-layer outcome tracking built in from the start
- Outcome labeling on resolution, not retrospectively

**Dashboard**
- Single-file React SPA, 8 screens, no build step
- Live JSON polling, animated components, HTML Canvas visualization
- Screens: Workspace, Daily board, Research, Expression Map, Validation, Ledger, Event Graph, Delta

---

## Technical stack

Python 3 · Gamma API REST client · GraphQL · rolling statistics · JSON pipeline · React (in-browser Babel, no build step) · HTML Canvas · cron orchestration via shell script

---

## Scale and cadence

- Daily collection runs: 2 per day (morning + afternoon)
- Typical output: 14–20 actionable markets per scan across 6 domains
- Validation tracked: 413 observations over 30 days, 85 unique resolved markets

---

## What was learned

**Deduplication is a methodology decision, not an implementation detail.**
The same slug can appear in 10 consecutive daily scans. Counting 10 observations vs. 1 unique market produces materially different performance numbers. Neither is wrong — they answer different questions. The system tracks all three levels explicitly.

**Category API endpoints are less stable than primary endpoints.**
Aggressive per-category fetching exposed rate limit behavior not present in the primary pool endpoint. Retry logic and silent fallback are necessary from the start, not as afterthoughts.

**A single-file React SPA is maintainable up to approximately 7,000 lines** with disciplined component structure. Above that, a build step is necessary. This one reached that boundary.

**Signal scoring without outcome tracking produces unfalsifiable systems.** Outcome labeling infrastructure needs to be built before the first resolved market, not when the question is first asked.

---

## What is not claimed

This pipeline did not produce statistically validated predictive performance above base rate. Hit rates across the full resolved market set were not distinguishable from chance given sample sizes and domain stratification. The system is a data engineering and measurement artifact, not a trading system.

---

## Why this matters to a buyer

Any team ingesting unstructured event or market data — prediction markets, binary alerts, compliance signals, operational triggers — needs this class of infrastructure: systematic collection, configurable scoring, cross-event grouping, and honest outcome tracking. The measurement framework is domain-agnostic and directly reusable.
