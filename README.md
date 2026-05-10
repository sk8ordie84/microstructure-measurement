# Microstructure & Measurement

Measurement infrastructure for operators of systematic strategies on prediction markets, sports betting exchanges, and DEX perpetuals.

This repository is the methodology STUDIO11 uses for **Edge Audit** — a 4-week independent measurement engagement. The infrastructure was first run on our own prediction market thesis. **The thesis failed.** We documented the negative finding in full and shipped the methodology as a service.

---

## The negative result we shipped publicly

On 2026-04-29 our prediction market scoring pipeline was closed against a locked forward cohort. The result:

| Metric | Value |
|---|---|
| Cohort | n = 53 resolved rows, 16 unique events |
| Event-level PnL delta (SYSTEM − BASELINE_NAIVE) | −0.01298 |
| 95% CI (clustered bootstrap) | [−0.01520, −0.01066] |
| CI excludes zero | Yes — the gap is systematic |
| Hit-rate delta vs naive | 0.0 — identical selections |
| Cause of gap | Spread cost: SYSTEM enters at ask, BASELINE at mid |

The selection model picked the same winners and losers as a naive "always enter" arm. The entire underperformance was execution cost. **Decision applied: ARCHIVE_NOW. Daily pipeline stopped.**

Full outcome report: [`status/outcome-report.md`](./status/outcome-report.md)

This is the outcome our measurement framework was built to surface, and the outcome we publish to demonstrate that the infrastructure does what it claims to do. A measurement framework that correctly identifies no edge is working correctly.

---

## Edge Audit — engagement

A fixed-scope, 4-week independent measurement audit for operators running systematic or scored systems on Polymarket, Kalshi, sports betting exchanges, or DEX perpetuals.

**You provide:** execution logs and resolved outcome data on a locked forward cohort.

**We run:** forward cohort benchmark vs naive baseline, event-level clustered uncertainty, three-layer outcome calibration (observation, market, event), spread/fill cost decomposition, gap register against the logging stack.

**You receive:** written verdict, structured audit report, gap register, logging specification, decision-ready summary.

We do not provide strategy input, signal review, threshold tuning, or live monitoring. We do not retain raw fill data after engagement close.

Engagement spec, data handling, and price band: [`EDGE-AUDIT.md`](./EDGE-AUDIT.md)

Apply: [studio-11.co/audit.html](https://studio-11.co/audit.html)

---

## Methodology — what is in this repository

### [`calibration/`](./calibration/)
Three-layer outcome validation engine. Field-name configurable. Applies to any binary scored system where the unit of analysis is events or entities rather than raw row counts.

- `validate.py` — observation, market, and event-level outcome validation with Wilson CI
- `forward_benchmark.py` — SYSTEM vs BASELINE_NAIVE comparison for any binary ledger
- `clustered_uncertainty.py` — bootstrapped CI at cluster level; avoids naive row-count inflation

### [`dex-monitoring/`](./dex-monitoring/)
Independent CLOB toxicity scoring system across Hyperliquid and dYdX v4. L2 snapshot collection every 5 minutes, scoring across 4 microstructure dimensions (spread compression, book depth, depth imbalance, quote instability), 5 structured health outputs.

### [`status/`](./status/)
Live status of the measurement systems and the outcome report from the prediction market thesis.

---

## Case studies

- [A — Prediction Market Data Pipeline](./case-studies/A-prediction-market-pipeline.md) — collection, scoring, and outcome calibration for binary contracts
- [B — DEX Perpetuals Orderbook Monitoring](./case-studies/B-dex-orderbook-monitoring.md) — toxicity scoring on Hyperliquid and dYdX v4, plus a write-up of a float boundary classification bug found in production
- [C — Three-Layer Calibration Framework](./case-studies/C-binary-signal-calibration.md) — outcome validation for binary scored systems with Wilson CI, Spearman correlation, and tier stratification

---

## Technical stack

Python 3 · `requests` only · rolling window statistics · JSON pipeline architecture · React SPA (no build step) · standard library statistics · cron orchestration

---

## What this is not

- Not a trading signal generator or outcome predictor
- Not a strategy advisory or execution service
- Not a live monitoring product
- The DEX-monitoring band classifications (LOW / NORMAL / ELEVATED / TOXIC) require ~7 days of baseline accumulation per market before they read as meaningful

---

## Contact

**Enquiries:** hello@studio-11.co

**Audit application:** [studio-11.co/audit.html](https://studio-11.co/audit.html)
