# Microstructure & Measurement

Orderbook monitoring and calibration infrastructure for DEX perpetuals.

---

## What this is

A live measurement system for DEX perpetuals microstructure. It collects L2 orderbook snapshots from Hyperliquid and dYdX v4 every five minutes, scores each snapshot on four dimensions (spread compression, book depth, depth imbalance, quote instability), and produces structured health outputs.

This repository contains the complete collection, scoring, and monitoring pipeline, plus a separately developed calibration framework for binary scored systems.

**These are measurement and infrastructure systems. They are not trading systems and make no performance or predictive claims.**

---

## What this is not

- Not a trading signal generator or outcome predictor
- Not a finished or externally validated product
- Not ready for deployment without calibration against your own baseline data
- The scoring model is fully configurable; the current thresholds are under active calibration and should not be read as representing stable market norms

---

## Current system status

| Layer | Status |
|-------|--------|
| L2 collection — 4 streams | Live, 5-minute cadence |
| Toxicity scoring | Running, producing JSONL output |
| Health monitoring — 5 output files | Running after each collection cycle |
| 7-day spread baseline | Accumulating — requires ~7 days to stabilize |
| Band calibration | Early stage — distributions not yet representative |
| Outcome validation | Not yet — calibration phase ongoing |

The collection and monitoring infrastructure is operational. The calibration layer is not complete. Band classifications (LOW / NORMAL / ELEVATED / TOXIC) should not be read as meaningful until the 7-day baseline has had time to stabilize on normal market data.

---

## Case Studies

### [A — Prediction Market Data Pipeline](./case-studies/A-prediction-market-pipeline.md)
End-to-end collection, scoring, and outcome-calibration pipeline for a binary prediction market exchange. Configurable category-aware ingestion, multi-factor scoring, 3-layer outcome validation, relational event graph construction, and a React operator dashboard.

### [B — DEX Perpetuals Orderbook Monitoring](./case-studies/B-dex-orderbook-monitoring.md)
CLOB toxicity scoring system across Hyperliquid and dYdX v4. Collects L2 snapshots every 5 minutes, scores across 4 microstructure dimensions, produces 5 structured health outputs. Includes a detailed account of a float boundary classification bug found and fixed in production.

### [C — Three-Layer Calibration Framework for Binary Signal Systems](./case-studies/C-binary-signal-calibration.md)
Outcome validation system for binary scored predictions. Three aggregation layers with Wilson CI hit rates, Spearman correlation, and tier stratification. Designed to report what the data actually shows, not what a naive observation count suggests.

---

## Code

### [`dex-monitoring/`](./dex-monitoring/)
Python pipeline: L2 collector, toxicity scoring aggregator, health monitor, config, and orchestration script. Currently running on Hyperliquid and dYdX v4 BTC/ETH perpetuals.

### [`calibration/`](./calibration/)
3-layer outcome validation engine. Adaptable to any binary scored system where the underlying unit of analysis is events or entities rather than raw output counts.

---

## Technical stack

Python 3 · REST API clients (`requests` only) · rolling window statistics · JSON pipeline architecture · React SPA (no build step) · standard library statistics · cron orchestration

---

## Engagement

Project-based contract work. Typical scope: 3–8 weeks. Deliverable is working, documented code and a handoff session.

Areas: orderbook monitoring and health infrastructure, market-data collection and normalization, binary signal calibration frameworks, operator dashboards for data infrastructure.

---

## Contact

**Enquiries:** hello@studio-11.co
