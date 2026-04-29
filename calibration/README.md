# Calibration — Binary Outcome Measurement Framework

Measurement tools for binary scored systems: validation, cohort benchmarking,
and statistically honest uncertainty quantification.

---

## What this does

`validate.py` reads a scored ledger of binary predictions with outcomes and produces calibration metrics across three aggregation layers. The key insight: choosing the wrong aggregation layer can produce hit rates that differ by 8–15 percentage points from the same underlying data — not because of model quality, but because of implicit deduplication decisions.

---

## Three layers

**OBSERVATION-LEVEL**
Every logged entry counted independently. Measures raw system throughput and output frequency. Correct unit of analysis when the question is: "How often did the system produce an output?"

**MARKET-LEVEL**
Deduplicated by market identifier (slug). One representative entry per unique market — either the first scan or the highest-scoring scan (configurable). Correct unit of analysis when the question is: "How often did the system correctly score a unique asset?"

**EVENT-LEVEL**
Deduplicated by normalized event title. One representative per event group. Within a group, a YES-resolution outcome is preferred; when all outcomes in the group are NO, the latest resolved entry is used (reason recorded as `all_no_fallback`). Correct unit of analysis when the question is: "How often did the system correctly identify a unique event?"

---

## Statistical outputs

- **Wilson 95% CI** for hit rates at each layer
- **Spearman rank correlation** between daily_score and binary outcome
- **Tier stratification**: separate hit rates and sample sizes for A / B / C tiers
- **Calibration bins**: hit rate vs. average scan price per price range (0.10–0.25, 0.25–0.50, 0.50–0.75, 0.75–0.90)
- **Calibration gap**: `actual_YES_rate − avg_yes_price_at_scan`. Near zero = well-calibrated; positive = system scored events that resolved YES more often than price implied; negative = system scored events that resolved YES less often than price implied.
- **Domain stratification**: minimum n=15 required to report domain-level rates

---

## Input format

The ledger file (`logs/actionable_ledger.json`) has this structure:

```json
{
  "entries": [
    {
      "slug": "example-market-slug",
      "question": "Will X happen?",
      "event_title": "Example Event 2025",
      "yes_price": 0.62,
      "daily_score": 0.78,
      "priority_tier": "A_TIER",
      "bucket": "week",
      "scan_date": "2025-01-15",
      "outcome": "YES"
    }
  ]
}
```

**Outcome values:**
- `"YES"` — the YES outcome occurred
- `"NO"` — the NO outcome occurred (YES did not happen)
- `"VOID"` — market cancelled or unresolved (excluded from all analysis)
- `null` — pending; not yet resolved

---

## Usage

```bash
python3 validate.py
```

**Output:**
- Terminal report (structured sections)
- `logs/validation_report_latest.json` — full metrics in JSON
- `logs/validation_report_YYYYMMDD_HHMMSS.json` — dated snapshot

---

## Adapting to a new data source

The framework requires entries with:
- A unique identifier per underlying asset (`slug` or `observation_group_id`)
- A grouping field for event-level deduplication (`event_title`)
- A numeric score (`daily_score`)
- A tier label (`priority_tier`: A_TIER / B_TIER / C_TIER)
- A price or probability at collection time (`yes_price`)
- A binary outcome field (`outcome`: YES / NO / VOID / null)

Replace these field names in `validate.py` to adapt to any binary scored system. The statistical logic (Wilson CI, Spearman correlation, calibration gap, tier stratification) is field-name-agnostic after that substitution.

---

## What this framework does not do

- It does not generate predictions or scores
- It does not tell you whether a scoring model has value — only whether outcomes correlate with scores
- A well-calibrated framework that accurately reports a 50% hit rate on 50% base-rate markets is working correctly; the model may still have no value

---

## Minimum sample sizes

| Stage | Threshold | Behavior below threshold |
|-------|-----------|------------------------|
| Meaningful section analysis | n ≥ 10 | Summary only, section analysis skipped |
| Confident directional conclusions | n ≥ 30 | All sections shown with caution note |
| Calibration bins (5+ per bin) | n ≥ 50 | Bins populated but may have sparse cells |
| Per-tier analysis | n ≥ 5 per tier | Tiers with n < 5 flagged |
| Domain stratification | n ≥ 15 per domain | Domains with n < 15 not reported |

---

---

# forward_benchmark.py — Binary Cohort Comparison

Compares a measured cohort against a naive baseline on any binary scored ledger
where entries have an actual entry price and a mid/fair-value price.

## What it measures

For a resolved cohort of binary-outcome observations:

- **SYSTEM arm:** PnL = outcome_value − actual_entry_price
- **BASELINE_NAIVE arm:** PnL = outcome_value − mid_price

The gap between arms isolates the cost of entering at a worse price than the
fair-value mid. A system with no selection value will show a negative gap roughly
equal to the spread cost. A positive gap above zero requires selection value that
offsets execution cost.

This does NOT claim to measure signal quality or whether to act. It measures
whether a selection system produces better outcomes than a naive baseline after
execution cost.

## Input schema

Ledger file: JSON with a top-level `"rows"` array.

**Required per row:**

| Field | Type | Description |
|---|---|---|
| `outcome` | `"YES"` / `"NO"` | Binary resolution outcome |
| `entry_price_executable` | float | Actual entry price paid (e.g. ask) |
| `yes_price` | float | Mid / fair-value price at collection time |

**Recommended:**

| Field | Type | Description |
|---|---|---|
| `event_title` | str | Event/cluster grouping for dedup |
| `priority_tier` | str | Quality tier (`A_TIER`, `B_TIER`, `C_TIER`) |
| `bucket` | str | Time-bucket (`today`, `week`, `twoweek`) |
| `slug` | str | Unique market identifier |
| `scan_date` | str | ISO date of collection |

All field names are configurable via `FIELD_CONFIG` at the top of the script.

## Cohort filtering

Set `COHORT_FILTERS` in the script to a dict of `{field: value}` conditions.
Only rows matching all conditions AND having `outcome in ("YES", "NO")` are
included. Set `COHORT_FILTERS = {}` to include all resolved rows.

## Usage

```bash
# 1. Edit LEDGER_PATH, FIELD_CONFIG, and COHORT_FILTERS in the script
# 2. Run:
python3 calibration/forward_benchmark.py
```

**Output:** `logs/forward_benchmark_latest.json` + terminal report

## Output structure

```json
{
  "cohort_definition": { "filters_applied": {}, "n_resolved": 53, "n_open": 12 },
  "arms": {
    "SYSTEM":          { "n": 53, "yes_rate": 0.62, "avg_pnl_per_unit": -0.011 },
    "BASELINE_NAIVE":  { "n": 53, "yes_rate": 0.62, "avg_pnl_per_unit":  0.001 }
  },
  "comparison":   { "pnl_delta": -0.012, "pnl_delta_note": "..." },
  "verdict":      "...",
  "hit_rate_decomposition": { ... },
  "event_level":  { "unique_group_count": 16, "pnl_delta": -0.013 }
}
```

## Key interpretation note

`hit_rate_delta` will be 0.0 for any honest comparison on the same resolved cohort.
Both arms see the same outcomes; only the entry price differs. A non-zero
`hit_rate_delta` indicates a data integrity problem, not a system property.

---

---

# clustered_uncertainty.py — Clustered Bootstrap CI

Computes statistically honest confidence intervals for binary-outcome measurement
systems where observations are not independent.

## The core problem

In binary scored systems, multiple rows often belong to the same underlying event.
Treating them as independent overstates precision. The naïve ±1.96σ/√n CI can be
2–5× too tight when clusters are large. This tool bootstraps at the cluster level.

## Three sample sizes

| Count | Field | Use |
|---|---|---|
| Row N | all rows | Do NOT use for uncertainty statements |
| Slug N | unique market IDs | Better, but still overstates independence |
| Cluster N | unique event groups | Most conservative, most honest — use this |

## Input schema

Same ledger format as `forward_benchmark.py`. Additional required field:

| Field | Type | Description |
|---|---|---|
| `realized_pnl_per_1_unit` | float | Per-unit PnL for the metric being analyzed |
| `gross_edge_vs_mid` | float | Baseline PnL per unit (optional; set `BASELINE_PNL_FIELD = None` to skip) |

All field names are configurable via `FIELD_CONFIG` at the top of the script.

## Usage

```bash
# 1. Edit LEDGER_PATH and FIELD_CONFIG in the script
# 2. Run:
python3 calibration/clustered_uncertainty.py
```

**Output:** `logs/clustered_uncertainty_latest.json` + terminal report

## Output structure

```json
{
  "sample_size": { "row_n": 53, "slug_n": 28, "cluster_n": 16 },
  "metric_estimates": {
    "row_level_avg": -0.0109,
    "cluster_level_avg": -0.0130
  },
  "confidence_intervals": {
    "clustered_bootstrap": { "ci_lo": -0.0152, "ci_hi": -0.0107, "contains_zero": false },
    "naive_row_level_ci":  { "ci_lo": -0.0142, "ci_hi": -0.0076, "warning": "overstated precision" }
  },
  "baseline_delta_ci": { "ci_lo": -0.0152, "ci_hi": -0.0107, "contains_zero": false }
}
```

## Bootstrap parameters

Configurable at top of script: `N_BOOTSTRAP = 5000`, `SEED = 42`, `CI_LEVEL = 0.95`.
Changing `SEED` after first use will shift CI bounds; note it in your records if you do so.
