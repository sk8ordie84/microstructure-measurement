# DEX Monitoring — Outreach Launch Context

Point-in-time record from early April 2026. Documents the readiness criteria
applied before the first external outreach referencing the live DEX monitoring system.

---

## Criteria applied before outreach

- [x] `collector_stable = true` in `data_health_latest.json`
  Required ≥7 days of continuous collection at ≥95% completeness per stream.

- [x] Band distributions showing non-zero LOW and NORMAL bands
  Baseline stabilized after the first full 7-day accumulation window.

- [x] `evidence-snapshot.md` reflects live outputs at time of outreach

- [x] Contact email active: hello@studio-11.co
- [x] README updated with honest status framing and explicit calibration caveats
- [x] "What this is / What this is not" section present in README
- [x] Case Study B published with accurate technical detail and known limitations
- [x] Calibration case study (C) published
- [x] No personal name in any public-facing copy
- [x] No trading or signal claims in any public copy
- [x] Code published: collector, aggregator, monitor, config
- [x] Scheduler operational — 5-minute cadence, verified firing
- [x] 10+ days of continuous JSONL history accumulated

---

## What to share

- Public repo: https://github.com/sk8ordie84/microstructure-measurement
- Point directly to: Case Study B, `dex-monitoring/` directory

---

## Honest framing for any conversation

The system:
- collects L2 data from two venues, four streams, every 5 minutes
- scores each snapshot on four microstructure dimensions
- produces 5 structured health outputs per collection cycle
- is not a trading signal, not outcome-validated, not deployed externally

The infrastructure works. The measurement framework is sound. Calibration
methodology is transparent and documented.

---

*Studio11*
