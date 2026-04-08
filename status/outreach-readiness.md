# Outreach Readiness Checklist

Complete all blocking items before any external outreach referencing the live DEX monitoring system.

---

## Blocking — do not outreach until resolved

- [ ] `collector_stable = true` in `data_health_latest.json`
  Requires ≥7 days of continuous collection at ≥95% completeness per stream.
  Current: false. Estimated: ~April 9–10.

- [ ] Band distributions showing non-zero LOW and NORMAL bands
  Current: 0% LOW, 0% NORMAL across all streams — baseline not yet stable.
  Do not share distribution data externally until this resolves.

- [ ] `evidence-snapshot.md` refreshed from live outputs on the day of outreach
  The snapshot contains dated numbers. Update from `band_health_latest.json`
  and `data_health_latest.json` before any external use.

---

## Non-blocking — already done or in progress

- [x] Contact email active: hello@studio-11.co
- [x] README updated with honest status framing and explicit calibration caveats
- [x] "What this is / What this is not" section present in README
- [x] Case Study B published with accurate technical detail and known limitations
- [x] Calibration case study (C) published
- [x] No personal name in any public-facing copy
- [x] No trading or signal claims in any public copy
- [x] Code published: collector, aggregator, monitor, config
- [x] Scheduler operational — launchd, 5-minute cadence, verified firing
- [ ] 10+ days of continuous JSONL history accumulated
  Estimated: ~April 12. Useful for any technical recipient who pulls the repo.

---

## What to share when outreach begins

- Public repo: https://github.com/sk8ordie84/microstructure-measurement
- Point directly to: Case Study B, `dex-monitoring/` directory
- Do not share raw band distribution screenshots until baseline has stabilized
- Do not forward `data_health_latest.json` directly — ACCUMULATING status
  requires verbal context that should not be the first thing a cold contact sees

---

## Honest framing for any conversation

The system:
- collects L2 data from two venues, four streams, every 5 minutes
- scores each snapshot on four microstructure dimensions
- produces 5 structured health outputs per collection cycle
- is currently in calibration — 7-day baseline needs to stabilize before band
  classifications are representative
- is not a trading signal, not outcome-validated, not deployed externally

The honest position: the infrastructure works. The measurement framework is sound.
Calibration is ongoing and we are transparent about it.

---

*Studio11*
