# Outcome Report — Prediction Market Pipeline Extraction

**Date:** 2026-04-29  
**Classification:** Internal factual record

---

## What was tested

A multi-month prediction market data pipeline was operated on Polymarket binary markets. The pipeline scanned near-term markets daily, scored them on urgency, liquidity depth, spread quality, and price momentum, assigned priority tiers, applied rule-based demotion filters, and tracked signal evolution across scans. A paper ledger recorded every selected market at collection time with full metadata.

The core question: does selection by this scoring system produce better outcomes than a naive baseline after accounting for execution cost?

The evaluation used a locked forward cohort — observations collected after a defined boundary date with clean executable entry price data — and compared it against `BASELINE_NAIVE` (entering every selected market at the mid price, no selection model).

---

## Result

The thesis was closed on 2026-04-29.

**Forward benchmark findings (resolved cohort):**

| Metric | Value |
|---|---|
| Cohort | n = 53 resolved rows, 16 unique events |
| Row-level PnL delta (SYSTEM − BASELINE) | −0.01142 |
| Event-level PnL delta | −0.01298 |
| 95% CI (event-level, clustered bootstrap) | [−0.01520, −0.01066] |
| CI excludes zero | Yes — gap is systematic |
| Hit-rate delta | 0.0 — identical selection as naive baseline |
| Cause of gap | Spread cost: SYSTEM enters at ask, BASELINE at mid |

The gap between the system arm and the naive baseline is approximately equal to the half-spread at entry. There is no selection advantage at the outcome level — the system picks the same winners and losers as a naive "always enter" approach. The entire underperformance is execution cost.

A mechanical exit-rule supplement (3 frozen rules, defined prospectively) was evaluated over the same window. None of the three rules showed `avg_net_vs_hold > 0` at sufficient trigger rate. Exit-rule supplementation did not reverse the finding.

**Decision applied:** ARCHIVE_NOW. Daily pipeline stopped. No further scanning.

---

## What was not tested and remains open

This evaluation is specific to the hold-to-expiry and mechanical exit-rule paths on this dataset. It does not evaluate:

- Intraday or continuous monitoring strategies
- Different market types or exchange structures
- Other selection criteria or cohort definitions
- DEX perpetuals microstructure (independent system, not part of this evaluation)

These are separate questions requiring separate data and separate hypotheses.

---

## What was extracted and retained

The measurement infrastructure produced during this project is generic and reusable. It has been extracted into this repository's `calibration/` directory, stripped of pipeline-specific field names, and documented independently.

**Retained components:**

| Component | File | What it provides |
|---|---|---|
| Three-layer calibration | `calibration/validate.py` | Observation / market / event-level outcome validation with Wilson CI |
| Forward cohort benchmark | `calibration/forward_benchmark.py` | SYSTEM vs BASELINE_NAIVE comparison for any binary ledger |
| Clustered uncertainty | `calibration/clustered_uncertainty.py` | Bootstrapped CI at cluster level; avoids naïve row-count inflation |
| DEX monitoring pipeline | `dex-monitoring/` | Independent orderbook toxicity scoring, Hyperliquid + dYdX v4 |

These components are field-name-configurable and applicable to any binary scored system where the unit of analysis is events or entities rather than raw row counts.

**Not retained:**

- The scanner and scoring logic (prediction-market-specific, not generalized)
- The policy/demotion engine (tied to specific market characteristics)
- The paper ledger and operational data (pipeline-specific records)
- Exit-rule tracking and open-position monitoring (experiment artifacts)

---

## What this report is not

This is a factual measurement record, not a post-mortem narrative. No pivot framing, no rescue plan, no revised hypothesis. The finding is documented as-is.

The infrastructure that was built is accurate and honest. A measurement framework that correctly identifies no edge is working correctly.
