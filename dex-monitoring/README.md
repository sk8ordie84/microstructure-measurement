# DEX Monitoring — Orderbook Toxicity Scoring

Real-time CLOB toxicity scoring system for DEX perpetuals markets.

Currently running on Hyperliquid and dYdX v4, BTC-PERP and ETH-PERP. Collects L2 snapshots every 5 minutes. Produces rolling toxicity scores and 5 structured health outputs.

---

## Files

| File | Purpose |
|------|---------|
| `dex_collector.py` | L2 book collection from Hyperliquid (POST) and dYdX v4 (GET) |
| `dex_aggregator.py` | Rolling window aggregation and toxicity scoring |
| `dex_monitor.py` | Health and integrity monitoring (5 output files) |
| `config_dex.json` | All scoring parameters, venue endpoints, band thresholds |
| `run_dex.sh` | Orchestration: collect → aggregate → monitor |

---

## How to run

**Dependencies:** `requests` (collection only). Everything else is standard library.

```bash
pip install requests
```

**Single run:**
```bash
python3 dex_collector.py   # collect L2 snapshots
python3 dex_aggregator.py  # score rolling window
python3 dex_monitor.py     # write health outputs
```

**Continuous collection via cron (every 5 minutes):**
```
*/5 * * * * /bin/bash <your-project-dir>/run_dex.sh >> <your-project-dir>/logs/dex/pipeline.log 2>&1
```

**Output directory:** `logs/dex/` (created automatically)

---

## Scoring model

Four additive components, each scored 0–25. Total: 0–100.

| Component | What it measures | Config key |
|-----------|-----------------|------------|
| `spread_score` | p75 spread vs. 7-day baseline | `spread_score_max`, `spread_expansion_threshold_bps` |
| `thin_score` | Fraction of window snapshots where book thinned > threshold | `thin_score_max`, `book_thin_threshold_pct` |
| `imbalance_score` | Mean absolute depth imbalance (bid vs. ask) | `imbalance_score_max`, `imbalance_scale_factor` |
| `instab_score` | Mean quote instability (bid price level changes) | `instab_score_max`, `instab_scale_factor` |

**Bands:**

| Band | Score range |
|------|------------|
| LOW | 0–24 |
| NORMAL | 25–49 |
| ELEVATED | 50–74 |
| TOXIC | 75–100 |

Band classification uses half-open interval conditionals (`>= 75`, `>= 50`, `>= 25`, else) — not closed-interval comparison against integer config bounds — to prevent floating-point boundary gaps.

**Baseline:** Rolling 7-day p25 of effective spread per venue/pair. Recomputed on each aggregator run.

**Window:** 12 snapshots = 1 hour at 5-minute cadence.

---

## Config parameters (`config_dex.json`)

```json
"scoring": {
  "baseline_window_days": 7,          // days of history for spread baseline
  "rolling_window_snapshots": 12,     // window size (12 × 5min = 1h)
  "spread_score_max": 25,             // max contribution of spread component
  "thin_score_max": 25,               // max contribution of thinning component
  "imbalance_score_max": 25,          // max contribution of imbalance component
  "instab_score_max": 25,             // max contribution of instability component
  "book_thin_threshold_pct": -5.0,    // % change triggering "thin" classification
  "spread_expansion_threshold_bps": 0.5, // bps change triggering "expanded" classification
  "imbalance_scale_factor": 2.0,      // scales imbalance_abs_mean into score
  "instab_scale_factor": 5.0          // scales quote_instab_mean into score
}
```

To add a new venue: add an entry under `"venues"` in `config_dex.json` and add the venue to `VENUE_PAIRS` in `dex_collector.py` and `dex_aggregator.py`. No other structural changes required.

---

## Health monitoring outputs (`dex_monitor.py`)

| File | What it contains |
|------|-----------------|
| `completeness_latest.json` | Expected vs. actual snapshot counts per stream; flag when below 95% |
| `timestamp_gap_latest.json` | Freshness delta (HL only, dYdX has no source timestamp); cross-venue gap |
| `correlation_latest.json` | Pearson r between HL and dYdX toxicity scores for same pair (24h window) |
| `band_health_latest.json` | Band distribution per stream (24h): count and % per band |
| `data_health_latest.json` | Umbrella summary: overall status, operational readiness checklist |

**Operational readiness checklist** (in `data_health_latest.json`):
- `collector_stable`: completeness ≥ 95% on all streams
- `data_integrity_ok`: any snapshots present
- `cross_venue_correlation_computed`: Pearson r available for at least one pair
- `backtest_scaffold_populated`: ≥ 50 scored snapshots with 1h future spread available

---

## Known limitations

- **dYdX timestamp asymmetry:** dYdX v4 orderbook endpoint does not expose a native venue timestamp. Collection timestamp is used for freshness calculations on this venue. Cross-venue gap computation accounts for this asymmetry.
- **Baseline cold start:** The 7-day baseline requires 7 days of data to be meaningful. Band classification during the first 7 days uses whatever history is available (p25 of partial data).
- **Completeness expectation:** The 288 snapshots/day target assumes cron runs reliably for a full 24-hour cycle. Partial-day collection produces low completeness numbers that are expected and not indicative of a failure.
