# Microstructure & Measurement

Contract engineering for orderbook monitoring, market-data pipelines, and calibration systems.

---

## What this is

A portfolio of contract engineering work in market-data infrastructure. Three independent systems, each built to production-grade completeness: collection, processing, scoring, monitoring, and a live operator dashboard.

**These are engineering and measurement systems. They are not trading systems. No performance claims are made or implied.**

---

## Case Studies

### [A — Prediction Market Data Pipeline](./case-studies/A-prediction-market-pipeline.md)
End-to-end collection, scoring, and outcome-calibration pipeline for a binary prediction market exchange. Configurable category-aware ingestion, multi-factor scoring, 3-layer outcome validation, relational event graph construction, and a React dashboard with 8 screens.

### [B — DEX Perpetuals Orderbook Monitoring](./case-studies/B-dex-orderbook-monitoring.md)
Real-time CLOB toxicity scoring system across Hyperliquid and dYdX v4. Collects L2 snapshots every 5 minutes, computes rolling toxicity scores across 4 microstructure dimensions, produces 5 structured health outputs, and streams to a live operator dashboard.

### [C — Three-Layer Calibration Framework for Binary Signal Systems](./case-studies/C-binary-signal-calibration.md)
Outcome validation system for binary scored predictions. Three aggregation layers — raw observations, unique markets, event groups — with Wilson CI hit rates, Spearman correlation, and tier stratification. Designed to report what the data actually shows, not what a naive count suggests.

---

## Code

### [`dex-monitoring/`](./dex-monitoring/)
Production Python pipeline: L2 orderbook collector, toxicity scoring aggregator, health monitor, config, and orchestration script. Runs today on Hyperliquid + dYdX v4 BTC/ETH perpetuals.

### [`calibration/`](./calibration/)
3-layer outcome validation engine. Adaptable to any binary scored system where the underlying unit of analysis is events or entities, not raw output counts.

---

## Technical stack

Python 3 · REST API clients (no dependencies beyond `requests`) · rolling window statistics · JSON pipeline architecture · React (single-file SPA, no build step) · standard library statistics · cron orchestration

---

## Engagement

Project-based contract work. Typical scope: 3–8 weeks. Deliverable is working, documented code and a handoff session.

Areas: orderbook monitoring and health infrastructure, market-data collection and normalization, binary signal calibration frameworks, operator dashboards for trading infrastructure.

---

## Contact

**Enquiries:** hello@studio-11.co
