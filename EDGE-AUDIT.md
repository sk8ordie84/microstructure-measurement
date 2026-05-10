# Edge Audit — Engagement Specification

A fixed-scope, 4-week independent measurement audit by STUDIO11 for operators of systematic or scored systems on Polymarket, Kalshi, prediction markets, and DEX perpetuals.

This document is the operator-facing spec: scope, schedule, deliverables, data handling, price band, and what we will not do.

For the methodology that produces the audit, see this repository.

For the negative result we ran on our own thesis, see [`status/outcome-report.md`](./status/outcome-report.md).

---

## Who this is for

- Operators running live capital on a scored or systematic basis
- Solo quants or small teams without a dedicated measurement function
- Operators who suspect their internal validation is not surveying the questions they actually need answered before scaling
- Operators preparing for an LP or allocator conversation who need an independent measurement read on their stack

We work with operators across:

- Prediction markets — Polymarket, Kalshi, Manifold, Augur-class DePMs
- DEX perpetuals — Hyperliquid, dYdX, Drift, GMX-class
- Binary contract trading systems and scored prediction operators
- Adjacent event-driven or calibration-sensitive systems on request

If you are a retail trader, a strategy advisory shopper, or seeking signals or forward calls, this is not the engagement.

---

## Schedule — 4 weeks, fixed

**Week 1 — Scoping and data access**
Kickoff call. Confirm scope, venue list, and forward cohort boundary date. Operator provides structured data access per the input list. We confirm scope and flag any data gaps within 48 hours of the kickoff.

**Week 2 — Instrumentation audit**
We map existing measurement against five audit dimensions: fill quality and execution leakage, signal stability and regime sensitivity, capacity and market impact, measurement layer completeness, and operational consistency. Binary scoring at each checkpoint: covered, partially covered, not covered. No qualitative hedging.

**Week 3 — Forward cohort benchmark and gap analysis**
Forward cohort benchmark of the operator's scored system against `BASELINE_NAIVE` on a locked, post-boundary cohort. Event-level clustered uncertainty, three-layer outcome validation, spread and fill cost decomposition. Gap register against what the logging stack can and cannot answer retrospectively.

**Week 4 — Report assembly and review**
Draft report delivered for principal review at the start of week 4. One revision cycle. Final report and decision-ready summary issued at end of week 4.

---

## What we deliver

1. **Measurement audit report** — structured document mapping current measurement coverage against the five audit dimensions, with binary scoring at each checkpoint and the underlying evidence for each score.

2. **Gap register** — explicit list of instrumentation gaps, ranked by operational risk and reconstruction difficulty.

3. **Logging specification** — what should be captured, at what granularity, to enable the retrospective analysis the strategy requires.

4. **Decision-ready summary** — one-page principal-facing summary suitable for internal review or LP/allocator reporting. No editorial opinion on whether to run the strategy. Only on whether the measurement layer supports that decision.

5. **Forward cohort benchmark output** — full benchmark notebook artefact (CSV, plots, summary tables) showing SYSTEM vs `BASELINE_NAIVE` PnL deltas, hit rate deltas, clustered CIs, and cost decomposition.

A redacted sample audit report is available on request after a scoping call.

---

## What we do not deliver

- Strategy opinions or signal review
- Threshold tuning, parameter optimization, or model selection
- Forward-looking projections or backtest extensions
- Live monitoring, dashboards, or ongoing alerts
- Implementation services or strategy code

If the answer to the measurement question requires changing the strategy, that is the operator's call to make. We do not advise on it.

---

## Data handling

**You provide, we receive (read-only):**
- Resolved outcome data on a locked forward cohort
- Execution logs covering the same window
- Strategy parameter set (the configuration that was live during the cohort window)
- Optional: prior internal validation reports

**Where data sits:**
- Encrypted at rest on engagement-specific storage
- No raw fill data, account credentials, or strategy code is retained after engagement close
- Aggregate methodology artefacts (anonymized cohort statistics, audit framework outputs) may be retained for internal methodology development unless specifically excluded by the engagement contract

**Read-only access:**
- API keys, where required, must be read-only and venue-scoped
- We do not require any account capable of placing orders, withdrawing funds, or modifying account state

**NDA:**
- Mutual NDA executed at kickoff if requested by the operator
- Default position is that engagement existence and high-level scope are confidential; methodology is public via this repository

**Post-engagement:**
- Raw fill and outcome data deleted within 30 days of engagement close
- Final deliverables retained by the operator; STUDIO11 retains only redacted methodology artefacts

---

## Price band

Engagements start at four figures USD for a single-venue scope. Multi-venue, multi-strategy, or multi-cohort scopes are quoted on the scoping call.

Pricing is fixed at scoping. There is no per-hour charge, no scope creep mechanism, and no upsell to ongoing services.

**Payment:**
- 50% on Week 1 kickoff
- 50% on Week 4 final report delivery

**Accepted payment methods:**
- USDC on Polygon (preferred, instant settlement)
- USD or EUR wire via Wise Business (issued on request, 2-3 day settlement)

**Refund clause:** if at the end of Week 1 the data structure or scope makes the engagement unworkable in the planned 4-week window, the engagement is closed and the kickoff payment is refunded in full.

**No-finding guarantee:** if the final report does not surface at least one actionable finding the operator did not already know, the engagement fee is refunded in full at the operator's request, no questions asked. The operator decides after reading the report. We back the methodology, not a feel-good outcome.

---

## Application

[studio-11.co/audit.html](https://studio-11.co/audit.html)

We review applications within 3 business days. If the engagement is not a fit, we say so directly.

---

## Contact

**Enquiries:** hello@studio-11.co
