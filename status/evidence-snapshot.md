# DEX Monitoring — Evidence Snapshot

Current as of: April 2026
Status: ACCUMULATING (calibration phase)

---

## System coverage

| Venue | Pair | Collection method |
|-------|------|-------------------|
| Hyperliquid | BTC-PERP | REST POST `/info` — native ms timestamp from venue |
| Hyperliquid | ETH-PERP | REST POST `/info` — native ms timestamp from venue |
| dYdX v4 | BTC-PERP | REST GET — collection timestamp used (no source timestamp) |
| dYdX v4 | ETH-PERP | REST GET — collection timestamp used (no source timestamp) |

---

## Collection cadence

- Interval: every 5 minutes
- Target per stream per day: 288 snapshots
- Current 24h actual: ~263 per stream (collector in stabilization phase)
- Scheduler: launchd user agent (macOS), 300-second interval

---

## Metrics captured per snapshot

| Metric | Description |
|--------|-------------|
| `effective_spread_bps` | Bid/ask spread in basis points at near touch |
| `book_thinning_rate` | 5-minute percentage change in total book depth |
| `depth_imbalance` | Absolute bid vs. ask depth ratio, mean over rolling window |
| `quote_instability` | Count of bid price level changes per window |
| `mid_price` | (bid + ask) / 2 at near touch |
| `near_bid_usd`, `near_ask_usd` | Best bid and ask in USD |

---

## Toxicity scoring

- 4 additive components, each scored 0–25. Total score: 0–100.
- Rolling window: 12 snapshots = 1 hour at 5-minute cadence
- Baseline: 7-day p25 of effective spread per stream, recomputed each cycle
- Bands: LOW (0–24), NORMAL (25–49), ELEVATED (50–74), TOXIC (75–100)

---

## Health monitoring outputs

| File | What it tracks |
|------|----------------|
| `completeness_latest.json` | Expected vs. actual snapshot counts per stream; flag at <95% |
| `timestamp_gap_latest.json` | Freshness delta and cross-venue timestamp gap |
| `correlation_latest.json` | Pearson r between HL and dYdX toxicity series (24h window) |
| `band_health_latest.json` | 24h band distribution per stream |
| `data_health_latest.json` | Umbrella readiness summary — 4-item checklist |

---

## Current calibration status

Overall system status: **ACCUMULATING**

| Readiness check | Current |
|-----------------|---------|
| collector_stable (≥95% completeness, 24h continuous) | false — stabilizing |
| data_integrity_ok | true |
| cross_venue_correlation_computed | true |
| backtest_scaffold_populated (≥50 lag-pairs) | true — 860 pairs |

**Band distribution — current (24h window, April 8 2026):**

| Stream | LOW | NORMAL | ELEVATED | TOXIC | Avg score |
|--------|-----|--------|----------|-------|-----------|
| HL BTC-PERP | 0% | 0% | 97.0% | 3.0% | 65.5 |
| HL ETH-PERP | 0% | 0% | 100% | 0% | 64.4 |
| dYdX BTC-PERP | 0% | 0% | 68.1% | 31.9% | 72.3 |
| dYdX ETH-PERP | 0% | 0% | 39.9% | 60.1% | 73.6 |

**Why distributions look like this:**
The 7-day baseline spread is computed from whatever history is available. In the first 7 days of a fresh deployment, that history includes early accumulation periods and any collection gaps. The baseline p25 is therefore lower than it will be on stable data, making normal sessions appear elevated against it. This is expected cold-start behavior, not a claim about actual market conditions.

**Target distribution after baseline stabilizes (Day 7–10 under normal conditions):**

| Band | Expected range |
|------|----------------|
| LOW | 60–70% |
| NORMAL | 20–25% |
| ELEVATED | 8–12% |
| TOXIC | 2–5% |

These targets are a reasonableness check on baseline stability, not a scoring claim.

---

## What is not claimed

This system does not predict price direction, identify adversely selected trades, or generate any form of actionable signal. It measures orderbook conditions at collection time and produces structured health metrics. Interpretation is outside the scope of this system.

---

*Studio11*
