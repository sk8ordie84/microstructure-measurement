# Edge Audit — Sample Report

**Client:** Operator A (redacted)
**Asset class:** Polymarket political event binaries
**Sample:** 247 resolved positions across 89 unique events
**Window:** 90 days, ending boundary date T-0
**Prepared by:** STUDIO11

---

## Page 1 — Executive Summary

**Engagement scope.** Operator A submitted 247 resolved positions on political-event binary contracts (election outcomes, vote-margin thresholds, nomination markets) traded on Polymarket over a 90-day window. We were asked three questions: is the operator's stated probability well-calibrated, does the live PnL exceed a naive baseline once we lock a forward cohort, and where is execution leaking. We received fills, timestamps, stated_p at entry, market mid at entry, and resolution. We did not receive the model itself and did not need to.

**Top three findings.**
- Calibration is tight on mid-probability bets (0.40–0.65) but Brier rises 38% on stated_p > 0.70, driven by 19 overconfident favorites.
- Forward-cohort SYSTEM beats BASELINE_NAIVE by +3.1 cents per dollar staked, 95% CI [+0.6, +5.7], event-clustered.
- 71% of the gap to baseline disappears when holding period exceeds 8 days; the edge is concentrated in same-day entries.

**Top three recommendations.**
- Cap or down-weight stakes when stated_p > 0.72 until the favorite bucket is recalibrated on a fresh cohort.
- Restrict the strategy to entries with holding period under 8 days; the 31+ day cohort is a coin flip after fees.
- Begin logging market mid, best bid, best ask, and fill price separately so spread cost can be isolated from selection cost.

**Decision summary.** The measurement layer can answer the three questions asked. The edge is real but narrower than the operator's internal tracking suggested (operator reported +5.2 c/$, audited figure is +3.1 c/$). The delta is execution drag plus one miscounted resolution. Recommend continuing the strategy on the constrained cohort defined on Page 4.

---

## Page 2 — Calibration Analysis

**Headline metrics.**

| Metric | Value | Reference |
|---|---|---|
| Brier score (n=247) | 0.214 | 0.25 = always-50% prior; 0.18 = strong skill |
| Log-loss | 0.612 | 0.693 = uninformed |
| Mean stated_p | 0.547 | |
| Mean realized | 0.534 | |

A Brier of 0.214 on binary political contracts is in the band where a model is doing real work but is not exceptional. The 13 bps gap between stated and realized is within sampling noise on n=247.

**10-bucket calibration curve.** Buckets are deciles of stated_p. Wilson 95% CI shown.

```
stated_p   n    realized   Wilson 95% CI       gap
0.05-0.15   8    0.125     [0.02, 0.47]        -0.02
0.15-0.25  14    0.214     [0.08, 0.45]        +0.01
0.25-0.35  22    0.318     [0.17, 0.51]        +0.02
0.35-0.45  31    0.419     [0.27, 0.58]        +0.02
0.45-0.55  44    0.523     [0.39, 0.66]        +0.02
0.55-0.65  39    0.615     [0.46, 0.75]        +0.01
0.65-0.75  35    0.629     [0.47, 0.77]       -0.07
0.75-0.85  28    0.643     [0.46, 0.79]       -0.16
0.85-0.95  19    0.737     [0.51, 0.88]       -0.18
0.95-1.00   7    0.857     [0.49, 0.97]       -0.10
```

**Visual shape.** Below 0.65 the realized rate tracks the diagonal within one Wilson half-width. Above 0.70 the curve flattens; the 0.85–0.95 bucket realizes at 0.74 instead of the stated ~0.90. Brier decomposed by region: 0.187 on stated_p ≤ 0.65 (n=158), 0.258 on stated_p > 0.65 (n=89). The favorite-side error contributes 61% of total Brier mass on 36% of positions.

**Specific finding.** Calibration is well-anchored on the 0.40–0.65 range. It drifts above 0.70 — overconfidence on heavy favorites. The five worst calibration losses in the sample are all stated_p ≥ 0.78 picks that resolved against. None of these are concentrated in a single player or team, so the failure is structural, not adversarial selection by a counterparty.

---

## Page 3 — Forward Cohort Benchmark

**Cohort definition.** Boundary date locked at T-45. Forward cohort is the 121 positions resolved after that date across 47 events. Backward cohort (used only for calibration above) is the 126 positions before. Boundary was set before we saw any forward results.

**Baseline.** BASELINE_NAIVE = take the same side at the market mid at entry timestamp, hold to resolution, no model. This is the price you would pay to express the same directional view without the model.

**Forward PnL, in cents per dollar staked.**

| Cut | SYSTEM | BASELINE_NAIVE | Delta | 95% CI (event-clustered bootstrap, 5000 reps) |
|---|---|---|---|---|
| Row-level (n=121) | +4.8 | +1.7 | +3.1 | [+0.9, +5.4] |
| Event-level (n=47) | +4.6 | +1.5 | +3.1 | [+0.6, +5.7] |

The event-level CI excludes zero. The row-level CI also excludes zero but understates uncertainty because positions on the same game are correlated; we report the event-level number as the headline.

**Hit rate delta.** SYSTEM wins 56.2% of resolved positions; BASELINE_NAIVE wins 51.8% on the same positions sized identically. Delta is +4.4 percentage points. On n=121 the Wilson 95% CI on the delta is [+0.7, +8.0].

**Spread cost decomposition.** Average half-spread at entry was 2.1 cents. SYSTEM crossed the spread on 88% of entries (no resting orders). Reconstructing fills at mid instead of fill price lifts SYSTEM PnL from +4.8 to +6.7 c/$. The same adjustment lifts BASELINE_NAIVE from +1.7 to +1.7 (it was already specced at mid). So 1.9 c/$ of the 3.1 c/$ headline gap is selection; the operator is paying back 1.9 c/$ in spread that a passive execution would not. Roughly 38% of the realized edge is being given back at the point of execution.

---

## Page 4 — Edge Decay by Holding Period

Positions split by time between entry and resolution. PnL in cents per dollar staked, net of fill spread.

| Holding period | n | Hit rate | SYSTEM PnL | BASELINE_NAIVE PnL | Delta |
|---|---|---|---|---|---|
| Intra-day (< 24h) | 58 | 60.3% | +7.9 | +1.9 | +6.0 |
| 1–7 days | 41 | 56.1% | +4.2 | +1.4 | +2.8 |
| 8–30 days | 16 | 50.0% | +0.6 | +1.6 | -1.0 |
| 31+ days | 6 | 50.0% | -1.4 | +0.8 | -2.2 |

**Where the edge concentrates.** 82% of the forward-cohort PnL is generated in positions held under 7 days, and 64% in intra-day positions, despite intra-day being only 48% of position count. The 8+ day cohort is indistinguishable from baseline at this sample size and slightly negative on point estimate.

**Where it decays.** At 8+ days, the operator's stated_p edge appears to be priced in by the market before resolution. Either the model's information is short-lived or longer-dated contracts attract more informed flow. We cannot distinguish these without more data.

**Recommendation on cohort selection.** Restrict deployment to entries with expected holding period under 8 days. This drops 22 of 121 forward positions (18% of count) and removes 6.7% of gross stake but improves PnL per dollar staked from +4.8 to +6.4 c/$. The 8+ day book is not paying for the capital it consumes.

---

## Page 5 — Three Failure Modes (Ranked)

**1. Stale stated_p on heavy favorites.** Most operationally severe. The 0.85–0.95 bucket realized at 0.74 (Wilson [0.51, 0.88]). Surfaced from the calibration table on Page 2 plus a check that none of the 19 misses cluster in a single market category, time horizon, or resolution source. The operator's model is confidently wrong on a structural slice, not unlucky on a few events. What to do: hold the strategy out on stated_p > 0.72 for one full cycle, then refit the favorite head on the held-out cohort. This is a calibration repair, not a strategy change.

**2. Spread is eating 38% of the edge.** Surfaced from the decomposition on Page 3 — fills reconstructed at mid lift gross PnL from +4.8 to +6.7 c/$. The operator is crossing the spread on 88% of entries. Average half-spread is 2.1 cents on contracts where the model is claiming a 4–6 cent edge. What to do: log best bid and best ask at decision time, then measure resting-fill rate when posting one tick inside. Even partial conversion to maker fills is worth ~1 c/$.

**3. One resolution disagreement and four duplicate-event entries.** On reconciling the 247 positions to public Polymarket resolutions, one position the operator marked as a win was a market that resolved NO on a resolution-source amendment (the operator's internal log was not updated after the official correction). Four pairs of positions were entered on the same market on the same day from what appears to be two separate processes; these were treated as independent in the operator's internal PnL but are not independent for risk. Surfaced by joining position_id to event_id and counting (event_id, side, day) tuples. What to do: add a uniqueness check on (event_id, side, day) at entry and a post-resolution reconciliation step against the public resolution feed. This is bookkeeping, not strategy, but the operator's self-reported PnL was off by 2.1 c/$ because of it.

---

## Page 6 — Gap Register, Logging Spec, Decision Summary

**What the current logging stack cannot answer.**
1. What was the best bid and best ask at the moment of decision? (Only fill price is logged.)
2. Was the position entered as a marketable order or did it rest? (Order type is not logged.)
3. What was the model's stated_p one hour before resolution versus at entry? (Only entry stated_p is stored.)
4. Were there other positions open on the same player on the same day? (No same-player aggregation key.)
5. What was the operator's intended size versus filled size? (Partial fills are silently merged.)

**Logging spec going forward.**
1. `decision_ts`, `entry_ts`, `resolution_ts` as separate UTC fields.
2. `best_bid`, `best_ask`, `mid`, `fill_price` at decision_ts and entry_ts.
3. `order_type` (marketable, post-only, IOC), `intended_size`, `filled_size`.
4. `stated_p_decision`, `stated_p_entry`, and an optional `stated_p_T_minus_1h` snapshot.
5. `event_id`, `market_category`, `resolution_source`, `side` as a composite uniqueness key.
6. `resolution_source` and `resolution_correction_ts` if the official resolution is later amended.
7. `model_version` and `feature_set_hash` so cohorts can be cut by model generation.

**Decision summary for LP / principal.** Operator A's strategy generates a measurable edge over a naive same-side baseline of +3.1 cents per dollar staked on the locked forward cohort, 95% CI [+0.6, +5.7], event-clustered. The edge is concentrated in positions held under 8 days and is partially eroded by a 38% spread tax at execution. Calibration is sound on mid-probability bets and broken on heavy favorites. The headline number the operator was tracking internally (+5.2 c/$) was inflated by one mis-marked resolution and four double-counted positions; the audited figure is the one to use. The strategy is fit to deploy on the constrained cohort and warrants the bookkeeping and execution fixes specified above before any size increase.

---

*Edge Audit by STUDIO11 · 2026 · Sample report for illustration. All numbers fictional.*
