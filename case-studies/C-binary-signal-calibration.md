# Case Study C — Three-Layer Calibration Framework for Binary Signal Systems

**Principled outcome measurement for scored binary predictions, with deduplication, Wilson CI, and tier stratification**

---

## Problem

Most scored signal or alert systems report performance using raw output counts. If the same underlying market or event is scanned 10 times, it contributes 10 observations to the hit rate calculation. This is not wrong — it measures throughput. But it answers the wrong question if the buyer wants to know whether the *scoring model* identified correct decisions.

Three distinct questions require three distinct aggregation levels:
1. How often did the system produce a correct output? (observation-level)
2. How often did the system correctly score a unique market? (market-level)
3. How often did the system correctly identify a unique event? (event-level)

Conflating these three produces numbers that are accurate but misleading. A system with 413 observations, 85 unique markets, and 40 unique events can report three materially different hit rates — all from the same underlying data.

---

## What was built

**Three-layer validation engine (`validate.py`)**

*Layer 1 — OBSERVATION*
Every logged entry counted independently. Measures raw system throughput and output frequency. Appropriate for evaluating collection reliability and scoring consistency across repeated scans.

*Layer 2 — MARKET*
Deduplicated by market slug. One representative entry per unique market: the first scan chronologically, or the scan with the highest score (configurable). Hit rate at this level answers: "Of the unique markets the system scored as ACTIONABLE, what fraction resolved favorably?"

*Layer 3 — EVENT*
Deduplicated by normalized event title (trimmed, lowercased, whitespace-collapsed). One representative per event group. Within a group: YES-resolution winner is preferred; all-NO fallback used when no YES winner exists. Representative selection reason is recorded explicitly (`yes_winner` or `all_no_fallback`).

**Statistical outputs**
- Wilson 95% confidence interval for hit rates at each layer
- Spearman rank correlation between daily_score and binary outcome
- t-test approximation via `NormalDist` for p-value estimation
- Tier stratification: separate hit rates and sample sizes for A / B / C tiers
- Domain stratification with minimum sample size threshold (n ≥ 15 required to report)

**Dashboard integration**
- 3-way toggle: OBSERVATION / MARKET / EVENT mode
- Event group table: event title, market count, representative slug, has_yes_winner flag, representative_reason
- All-NO fallback banner: explicit disclosure when no YES-winner exists in group
- Graceful fallback: old reports without event summary fields show informational message rather than breaking

**Reporting discipline**
- Wilson CI always shown alongside point estimate
- Sample size shown for every reported rate
- Domains with n < 15 not reported (labeled "insufficient sample")
- No smoothing, no imputation, no backfill

---

## Technical stack

Python 3 · standard library statistics · NormalDist (for p-value approximation without scipy dependency) · JSON output pipeline · React dashboard toggle integration

---

## Scale characteristics

At 30 days of operation, the system processed:
- 413 logged observations
- 85 unique resolved markets (deduplicated by slug)
- 2 domains with n ≥ 15 for domain-level reporting

These numbers reflect a calibration and measurement system in early operation — not a mature dataset. The methodology is correct regardless of scale; the statistical power increases as data accumulates.

---

## What was learned

**Deduplication layer choice is a methodology decision that must be explicit, not an implementation detail.**
In the 30-day dataset, observation-level and market-level counts differed by a factor of nearly 5 (413 vs. 85). Reporting one without disclosing the other is misleading by construction. The correct approach is to report all three and let the buyer choose which question they are answering.

**Domain stratification requires minimum sample sizes to be meaningful.**
With 85 total resolved markets spread across 9 domains, only 2 domains had n ≥ 15 at the market level. Reporting hit rates for n=4 or n=7 domains would generate numbers with confidence intervals spanning the entire [0,1] range — not useful and potentially misleading. The threshold must be set before looking at the data, not after.

**Wilson CI is more honest than a point estimate for small samples.**
At n=22, a 50% hit rate has a Wilson 95% CI of approximately [31%, 69%]. The interval is the real answer. Reporting "50% hit rate" without the interval implies precision the data does not support.

**Building calibration infrastructure after the fact is recoverable but creates gaps.**
If outcome labeling is not built from the first resolved market, historical outcomes must be reconstructed — a laborious and error-prone process. The correct time to build the calibration layer is before any outcomes have resolved.

**NormalDist suffices for p-value approximation when scipy is not available.**
Standard library `statistics.NormalDist` provides accurate normal CDF evaluation. For large-sample Spearman correlation tests, the normal approximation is adequate. Dependency on scipy is unnecessary for this use case.

---

## What is not claimed

This framework measures what happened. It does not validate that the scoring model has predictive value. A well-calibrated framework that accurately measures a 50% hit rate on 50% base-rate markets is reporting correctly — the model has no value, and the framework correctly shows that.

The framework's value is not in the numbers it produces. It is in the methodology: principled deduplication, honest interval estimation, and the discipline to report sample sizes and thresholds explicitly.

---

## Why this matters to a buyer

Any team operating a scored alert or signal system — in prediction markets, compliance, credit, operations, or research — needs this class of measurement. The failure mode of not having it is not zero performance reporting; it is *false* performance reporting due to implicit deduplication choices, missing confidence intervals, and domain aggregation without sample size discipline.

The three-layer framework, Wilson CI implementation, and event-level grouping logic are directly adaptable to any binary scored system where the underlying unit of analysis is events or entities rather than raw outputs.
