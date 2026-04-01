# Case Study B — DEX Perpetuals Orderbook Monitoring

**Multi-venue CLOB toxicity scoring and health infrastructure for Hyperliquid and dYdX v4**

---

## Problem

DEX perpetuals operators and liquidity providers have no standardized tooling to quantify intraday orderbook stress. Raw L2 data exists at both Hyperliquid and dYdX v4, but the APIs have different schemas, different timestamp conventions, and different precision formats. Without a normalization and aggregation layer, the data cannot be compared across venues or tracked systematically over time.

More specifically: spread widening, book thinning, depth imbalance, and quote instability are four distinct phenomena that tend to co-occur during adverse market conditions. No existing open tooling scores them compositionally or tracks them across a rolling window at the 5-minute cadence that liquidity providers need.

---

## What was built

**Collection layer (`dex_collector.py`)**
- Hyperliquid: REST POST to `/info` with `{"type": "l2Book", "coin": "BTC"}` — native millisecond timestamp from venue
- dYdX v4: REST GET to `/v4/orderbooks/perpetualMarket/{pair}` — no source timestamp; collection timestamp used with documented asymmetry
- Runs every 5 minutes via cron across 2 venues × 2 pairs (BTC-PERP, ETH-PERP)
- Normalized feature schema per snapshot: effective spread (bps), book thinning rate (5m pct), depth imbalance, quote instability, near-touch bid/ask (USD), mid price
- Output: `logs/dex/dex_snapshots_YYYYMMDD.jsonl` (append-mode)

**Toxicity scoring engine (`dex_aggregator.py`)**
- Rolling 7-day p25 baseline spread per venue/pair — normalization anchor
- 1-hour rolling window (12 snapshots) for all component calculations
- 4 additive components, each scored 0–25:
  - **Spread score**: p75 spread vs. baseline, scaled to 25 at `spread_expansion_threshold_bps`
  - **Thin score**: fraction of window snapshots where book thinning exceeds threshold, × 100 capped at 25
  - **Imbalance score**: mean absolute depth imbalance × scale factor, capped at 25
  - **Instability score**: mean quote instability × scale factor, capped at 25
- Total score: 0–100, four bands: LOW (0–24), NORMAL (25–49), ELEVATED (50–74), TOXIC (75–100)
- Band classification uses half-open interval conditionals — not closed-interval loop — to prevent float boundary gaps

**Health monitoring layer (`dex_monitor.py`)**
Five derived JSON outputs:
1. `completeness_latest.json` — expected vs. actual snapshots per stream (288/day target); flag when below 95%
2. `timestamp_gap_latest.json` — freshness per stream + cross-venue timestamp gap
3. `correlation_latest.json` — Pearson r between HL and dYdX spread series (BTC pair, ETH pair) with overlap count
4. `band_health_latest.json` — band distribution per stream (count + pct per band) over trailing window
5. `data_health_latest.json` — overall status + operational readiness checklist (4 binary items)

**Operator dashboard (DEX Ops screen in `index.html`)**
- Native screen in existing React SPA — same nav, same visual language, same routing pattern
- Status header: animated badge (green/amber), snapshot progress bar (n/288), data age timestamp, conditional status note
- Operational readiness tile: 4-item checklist with per-item indicators
- Live toxicity grid: 4-col, one card per stream; 5-segment score bar; inline component decomposition (`sprd:X thin:X imb:X inst:X`)
- Secondary tier: completeness (compact allSame tile or 4-col divergent view) + data integrity (freshness + correlation)
- Diagnostic tier: band distribution grid
- Visual hierarchy: primary / secondary / diagnostic opacity layers (1.0 / 0.9 / 0.75)

---

## Technical stack

Python 3 · Hyperliquid REST API · dYdX v4 REST API · rolling window statistics · JSON pipeline · React component (native integration into SPA) · CSS animation · cron via shell script

---

## Scale and cadence

- Collection: 288 snapshots per stream per day (5-minute cadence, 4 streams)
- Aggregation: runs after each collection cycle; ~0.3s per run
- Health monitoring: runs after aggregation; reads all streams, writes 5 output files
- Data retention: JSONL append per day; 7-day lookback for baseline computation

---

## What was learned

**Float boundary gaps in band classification are a real production failure mode.**
With `ELEVATED max: 74` and `TOXIC min: 75` as integers from config, a score of 74.6 matched neither condition in a closed-interval loop. The default band returned was LOW — factually wrong. Fix: replace the loop with ordered half-open interval conditionals (`>= 75`, `>= 50`, `>= 25`, else). This class of bug is invisible in testing if test cases only use round numbers.

**Cross-venue timestamp alignment requires explicit asymmetry documentation.**
Hyperliquid provides native venue timestamps in milliseconds. dYdX v4 provides no source timestamp on the orderbook endpoint. Treating them as equivalent without documentation creates silent staleness risk. The correct approach: track collection timestamp separately, compute cross-venue gap explicitly, report it in the health layer.

**Operational readiness checklists are more useful than a single pass/fail status.**
A binary "system healthy: yes/no" collapses four distinct conditions (collection stability, data integrity, cross-venue correlation computed, backtest scaffold populated) into one ambiguous signal. Tracking each independently lets an operator identify which specific condition failed and act on it.

**Completeness monitoring at 5-minute cadence catches cron drift that would otherwise go unnoticed.**
At 288 expected snapshots per day, a single missed cron cycle is a 0.35% completeness drop. Over a week, accumulated drift would compromise rolling window calculations. Monitoring at the snapshot level, not just the daily level, is necessary.

---

## What is not claimed

This system does not predict price direction, identify adverse selection sources, or generate trading signals. It measures orderbook conditions at the time of collection and produces structured health metrics. What a buyer does with those metrics is outside the scope of this system.

---

## Why this matters to a buyer

DEX protocols, liquidity managers, and market-making operations running on perpetuals venues need exactly this class of monitoring: systematic, multi-venue, sub-hour cadence, with clean JSON outputs that can feed downstream alerting, dashboards, or risk systems. The architecture is venue-agnostic — adding a third venue requires a new API client module and a config entry, not a structural change. The scoring model is fully configurable via JSON parameters with no code changes required.
