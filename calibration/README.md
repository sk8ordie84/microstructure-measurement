# Calibration — Three-Layer Binary Signal Validation

Outcome measurement framework for binary scored systems.

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
