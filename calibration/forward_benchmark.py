#!/usr/bin/env python3
"""
forward_benchmark.py — Generic Binary-Outcome Cohort Benchmark
==============================================================

Compares a measured cohort against a naive baseline on any binary scored
ledger where entries have an actual entry price and a mid/fair-value price.

WHAT THIS MEASURES
------------------
For a resolved cohort of binary-outcome observations:
  - System arm:   PnL = outcome_value - entry_price_actual
  - Baseline arm: PnL = outcome_value - entry_price_mid

The gap between arms isolates the cost of buying the spread (entering at ask
rather than mid). A system that adds no selection value will show a negative
gap equal to roughly half the spread. Any positive gap above zero requires
selection value that more than offsets execution cost.

This does NOT measure signal quality, predictive power, or whether to act.
It measures whether a selection system produces better outcomes than a
naive baseline after accounting for execution cost.

INPUT SCHEMA (edit FIELD_CONFIG and COHORT_FILTERS below)
----------------------------------------------------------
Ledger file must be JSON with a top-level "rows" array. Each row should have:

  Required:
    outcome              str        "YES" or "NO" (binary outcome)
    entry_price_actual   float      actual executable entry price (e.g. ask)
    entry_price_mid      float      mid/fair-value price at collection time

  Recommended (for stratification):
    event_group_id       str        event or cluster identifier for dedup
    tier                 str        quality tier label (e.g. "A_TIER")
    bucket               str        time-bucket label (e.g. "week")
    scan_date            str        ISO date of collection

  For cohort filtering (set COHORT_FILTERS to match your schema):
    source               str        e.g. "forward_live"
    execution_quality    str        e.g. "actual_l1"
    eligible             bool       True/False

Outcome values:
  "YES"  — the positive outcome occurred (payout = 1.0)
  "NO"   — the positive outcome did not occur (payout = 0.0)

Rows with outcome == null or any other value are excluded from analysis.

OUTPUT
------
  logs/forward_benchmark_latest.json — full metrics in JSON
  Terminal report with arm comparison, tier/bucket breakdown, verdict

USAGE
-----
  1. Edit FIELD_CONFIG and COHORT_FILTERS below to match your ledger schema.
  2. Set LEDGER_PATH to your ledger file.
  3. python3 forward_benchmark.py

NO PRODUCTION LOGIC IS CHANGED BY THIS SCRIPT. Read-only measurement.
"""

import json
import statistics
import sys
from pathlib import Path
from datetime import datetime, timezone

# ── Configuration — edit these to match your schema ──────────────────────────

LEDGER_PATH = Path("logs/forward_benchmark_ledger.json")
OUT_JSON    = Path("logs/forward_benchmark_latest.json")

FIELD_CONFIG = {
    # Outcome field — values must be "YES" or "NO"
    "outcome":             "outcome",

    # Entry price fields
    "entry_price_actual":  "entry_price_executable",   # measured/actual (e.g. ask)
    "entry_price_mid":     "yes_price",                # mid/fair-value (naive baseline)

    # Grouping and stratification
    "event_group_id":      "event_title",              # for event-level dedup
    "tier":                "priority_tier",            # for tier stratification
    "bucket":              "bucket",                   # for bucket stratification
    "scan_date":           "scan_date",                # for sorting
    "scan_time":           "scan_time",                # for tie-breaking
    "slug":                "slug",                     # unique market identifier

    # Optional: cost field (spread paid vs. mid)
    "spread_cost":         "spread_cost",              # set to None if absent
    "gross_edge_vs_mid":   "gross_edge_vs_mid",        # set to None if absent
    "days_held":           "days_held",                # set to None if absent
}

# Cohort filters — only rows matching ALL conditions are included
# Format: {field_name: expected_value}
# Set to {} to include all resolved rows
COHORT_FILTERS = {
    "source":                   "forward_live",
    "execution_price_source":   "actual_l1",
    "actionable_eligible":      True,
    "policy_status":            "ACTIONABLE_ELIGIBLE",
}

# Arm labels — shown in output
SYSTEM_LABEL   = "SYSTEM"        # the measured arm (actual entry price)
BASELINE_LABEL = "BASELINE_NAIVE"  # the naive arm (mid price)

# Stage thresholds (resolved row counts)
STAGE_THRESHOLDS = {"stage_1": 20, "stage_2": 50, "stage_3": 100}

# Tier ranking for deterministic dedup (highest priority first)
TIER_RANK = {"A_TIER": 0, "B_TIER": 1, "C_TIER": 2}


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def payout(row):
    """1.0 if positive outcome (YES), 0.0 if negative (NO)."""
    return 1.0 if row.get(FIELD_CONFIG["outcome"]) == "YES" else 0.0


def passes_filters(row, filters):
    """Return True if row matches all COHORT_FILTERS."""
    for field, expected in filters.items():
        if row.get(field) != expected:
            return False
    return True


def determine_stage(n):
    if n >= STAGE_THRESHOLDS["stage_3"]:
        return "stage_3", f"n={n} >= {STAGE_THRESHOLDS['stage_3']} — stronger evidence tier"
    if n >= STAGE_THRESHOLDS["stage_2"]:
        return "stage_2", f"n={n} >= {STAGE_THRESHOLDS['stage_2']} — first serious review"
    if n >= STAGE_THRESHOLDS["stage_1"]:
        return "stage_1", f"n={n} >= {STAGE_THRESHOLDS['stage_1']} — early signal, directional only"
    if n == 0:
        return "empty", "n=0 — no resolved rows in cohort"
    return "pre_stage_1", f"n={n} < {STAGE_THRESHOLDS['stage_1']} — sample too small for conclusions"


# ── Cohort stats ──────────────────────────────────────────────────────────────

def cohort_stats(rows, entry_key, label):
    """
    Compute per-arm statistics for a cohort using entry_key as the entry price field.

    entry_key maps to:
      FIELD_CONFIG["entry_price_actual"] for the SYSTEM arm
      FIELD_CONFIG["entry_price_mid"]    for the BASELINE_NAIVE arm
    """
    if not rows:
        return {
            "label": label, "n": 0,
            "yes_rate": None, "avg_mid_at_scan": None,
            "avg_entry_price": None, "avg_pnl_per_unit": None,
            "calibration_gap": None, "avg_spread_cost": None,
            "avg_gross_edge_vs_mid": None, "avg_days_to_resolve": None,
            "by_tier": {}, "by_bucket": {},
        }

    n = len(rows)
    yes_count = sum(1 for r in rows if r.get(FIELD_CONFIG["outcome"]) == "YES")
    yes_rate = yes_count / n

    mids = [r[FIELD_CONFIG["entry_price_mid"]] for r in rows
            if r.get(FIELD_CONFIG["entry_price_mid"]) is not None]
    avg_mid = statistics.mean(mids) if mids else None
    cal_gap = (yes_rate - avg_mid) if avg_mid is not None else None

    pnls, entry_prices = [], []
    for r in rows:
        ep = safe_float(r.get(entry_key))
        if ep is not None:
            pnls.append(payout(r) - ep)
            entry_prices.append(ep)

    avg_pnl   = statistics.mean(pnls) if pnls else None
    avg_entry = statistics.mean(entry_prices) if entry_prices else None

    sc_field = FIELD_CONFIG.get("spread_cost")
    scs = [r[sc_field] for r in rows if sc_field and r.get(sc_field) is not None]
    avg_sc = statistics.mean(scs) if scs else None

    gem_field = FIELD_CONFIG.get("gross_edge_vs_mid")
    gems = [r[gem_field] for r in rows if gem_field and r.get(gem_field) is not None]
    avg_gem = statistics.mean(gems) if gems else None

    dh_field = FIELD_CONFIG.get("days_held")
    dhs = [r[dh_field] for r in rows
           if dh_field and r.get(dh_field) is not None and r[dh_field] > 0]
    avg_dtr = statistics.mean(dhs) if dhs else None

    tier_field   = FIELD_CONFIG["tier"]
    bucket_field = FIELD_CONFIG["bucket"]

    by_tier = {}
    for tier in sorted(set(r.get(tier_field) for r in rows if r.get(tier_field))):
        sub = [r for r in rows if r.get(tier_field) == tier]
        sub_n   = len(sub)
        sub_yes = sum(1 for r in sub if r.get(FIELD_CONFIG["outcome"]) == "YES") / sub_n
        sub_pnls = [payout(r) - ep for r in sub
                    for ep in [safe_float(r.get(entry_key))] if ep is not None]
        sub_avg  = statistics.mean(sub_pnls) if sub_pnls else None
        sub_mids = [r[FIELD_CONFIG["entry_price_mid"]] for r in sub
                    if r.get(FIELD_CONFIG["entry_price_mid"]) is not None]
        sub_amm  = statistics.mean(sub_mids) if sub_mids else None
        sub_cg   = (sub_yes - sub_amm) if sub_amm is not None else None
        by_tier[tier] = {
            "n": sub_n,
            "yes_rate":         round(sub_yes, 4),
            "avg_pnl_per_unit": round(sub_avg, 4) if sub_avg is not None else None,
            "calibration_gap":  round(sub_cg, 4)  if sub_cg  is not None else None,
        }

    by_bucket = {}
    for bkt in sorted(set(r.get(bucket_field) for r in rows if r.get(bucket_field))):
        sub = [r for r in rows if r.get(bucket_field) == bkt]
        sub_n   = len(sub)
        sub_yes = sum(1 for r in sub if r.get(FIELD_CONFIG["outcome"]) == "YES") / sub_n
        sub_pnls = [payout(r) - ep for r in sub
                    for ep in [safe_float(r.get(entry_key))] if ep is not None]
        sub_avg  = statistics.mean(sub_pnls) if sub_pnls else None
        sub_mids = [r[FIELD_CONFIG["entry_price_mid"]] for r in sub
                    if r.get(FIELD_CONFIG["entry_price_mid"]) is not None]
        sub_amm  = statistics.mean(sub_mids) if sub_mids else None
        sub_cg   = (sub_yes - sub_amm) if sub_amm is not None else None
        by_bucket[bkt] = {
            "n": sub_n,
            "yes_rate":         round(sub_yes, 4),
            "avg_pnl_per_unit": round(sub_avg, 4) if sub_avg is not None else None,
            "calibration_gap":  round(sub_cg, 4)  if sub_cg  is not None else None,
        }

    return {
        "label": label, "n": n,
        "yes_rate":             round(yes_rate, 4),
        "avg_mid_at_scan":      round(avg_mid, 4)   if avg_mid   is not None else None,
        "avg_entry_price":      round(avg_entry, 4) if avg_entry is not None else None,
        "avg_pnl_per_unit":     round(avg_pnl, 4)   if avg_pnl   is not None else None,
        "calibration_gap":      round(cal_gap, 4)   if cal_gap   is not None else None,
        "avg_spread_cost":      round(avg_sc, 4)    if avg_sc    is not None else None,
        "avg_gross_edge_vs_mid":round(avg_gem, 4)   if avg_gem   is not None else None,
        "avg_days_to_resolve":  round(avg_dtr, 2)   if avg_dtr   is not None else None,
        "by_tier": by_tier,
        "by_bucket": by_bucket,
    }


# ── Event-level dedup ─────────────────────────────────────────────────────────

def build_event_level_cohort(cohort):
    """
    Deduplicate cohort to one representative row per event/cluster group.

    Grouping key: FIELD_CONFIG["event_group_id"] (normalized: strip, lowercase).
    Representative selection (deterministic):
      1. Tier rank (A_TIER > B_TIER > C_TIER > other)
      2. Earliest scan_time (ISO sort)
      3. Slug ascending (final tie-break)

    Returns:
      deduped_rows — list of one representative row per group
      event_meta   — dict: norm_key → {title, row_count, slug_count, slugs}
    """
    group_field = FIELD_CONFIG["event_group_id"]
    slug_field  = FIELD_CONFIG["slug"]
    tier_field  = FIELD_CONFIG["tier"]
    time_field  = FIELD_CONFIG["scan_time"]
    date_field  = FIELD_CONFIG["scan_date"]

    groups = {}
    for r in cohort:
        raw = r.get(group_field) or r.get(slug_field) or "UNKNOWN"
        key = raw.strip().lower()
        groups.setdefault(key, []).append(r)

    deduped_rows, event_meta = [], {}
    for key, rows in groups.items():
        def sort_key(r):
            tr  = TIER_RANK.get(r.get(tier_field), 9)
            ts  = r.get(time_field) or r.get(date_field) or ""
            slg = r.get(slug_field) or ""
            return (tr, ts, slg)
        rep = sorted(rows, key=sort_key)[0]
        deduped_rows.append(rep)
        slugs = sorted(set(r.get(slug_field, "") for r in rows if r.get(slug_field)))
        event_meta[key] = {
            "group_title":        rep.get(group_field) or rep.get(slug_field) or key,
            "row_count":          len(rows),
            "slug_count":         len(slugs),
            "slugs":              slugs,
            "representative_slug": rep.get(slug_field),
            "representative_tier": rep.get(tier_field),
        }
    return deduped_rows, event_meta


# ── Hit-rate / payoff decomposition ──────────────────────────────────────────

def hit_rate_decomposition(rows, entry_key, label):
    """
    Win  : pnl_per_unit > 0
    Loss : pnl_per_unit < 0
    Flat : pnl_per_unit == 0

    NOTE: For a fixed resolved cohort, hit_rate is IDENTICAL for both arms because
    both operate on the same rows with the same outcomes. The only difference
    between arms is entry price, which shifts avg_win and avg_loss but not
    which rows win. A non-zero hit_rate_delta signals a data integrity issue.
    """
    pnl_list = []
    for r in rows:
        ep = safe_float(r.get(entry_key))
        if ep is not None:
            pnl_list.append(payout(r) - ep)

    if not pnl_list:
        return {"label": label, "n": 0,
                "profitable_count": None, "profitable_share": None,
                "loss_count": None, "loss_share": None, "flat_count": None,
                "avg_win_pnl": None, "avg_loss_pnl": None,
                "payoff_ratio": None, "expectancy_per_unit": None}

    n      = len(pnl_list)
    wins   = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p < 0]
    flats  = [p for p in pnl_list if p == 0]
    win_s  = len(wins)  / n
    loss_s = len(losses) / n
    avg_w  = statistics.mean(wins)   if wins   else None
    avg_l  = statistics.mean(losses) if losses else None
    payoff = (round(abs(avg_w / avg_l), 4)
              if avg_w is not None and avg_l is not None and avg_l != 0 else None)
    expect = (round(win_s * avg_w + loss_s * avg_l, 4)
              if avg_w is not None and avg_l is not None else None)
    return {
        "label":             label,
        "n":                 n,
        "profitable_count":  len(wins),
        "profitable_share":  round(win_s, 4),
        "loss_count":        len(losses),
        "loss_share":        round(loss_s, 4),
        "flat_count":        len(flats),
        "avg_win_pnl":       round(avg_w, 4) if avg_w is not None else None,
        "avg_loss_pnl":      round(avg_l, 4) if avg_l is not None else None,
        "payoff_ratio":      payoff,
        "expectancy_per_unit": expect,
    }


def hit_rate_comparison(sys_hrd, base_hrd):
    def delta(a, b):
        return round(a - b, 4) if a is not None and b is not None else None
    return {
        "hit_rate_delta":     delta(sys_hrd["profitable_share"], base_hrd["profitable_share"]),
        "avg_win_delta":      delta(sys_hrd["avg_win_pnl"],  base_hrd["avg_win_pnl"]),
        "avg_loss_delta":     delta(sys_hrd["avg_loss_pnl"], base_hrd["avg_loss_pnl"]),
        "payoff_ratio_delta": delta(sys_hrd["payoff_ratio"], base_hrd["payoff_ratio"]),
        "expectancy_delta":   delta(sys_hrd["expectancy_per_unit"], base_hrd["expectancy_per_unit"]),
        "interpretation_note": (
            "hit_rate_delta == 0 is expected when both arms operate on the same resolved cohort "
            "(same outcomes, same rows). The only arm-level difference is entry price. "
            "A non-zero hit_rate_delta indicates a data integrity problem."
        ),
    }


# ── Verdict ───────────────────────────────────────────────────────────────────

def build_verdict(system, baseline, stage):
    n = system["n"]
    stage_name, stage_desc = stage
    lines = []

    if n == 0:
        return (
            "VERDICT: Cohort is empty. Zero resolved rows satisfy the configured "
            "cohort filters. Check COHORT_FILTERS and your ledger source field values."
        )

    stage_msgs = {
        "pre_stage_1": f"VERDICT: Sample too small (n={n}). All findings are provisional.",
        "stage_1":     f"VERDICT: Early signal only (n={n}). Directional, not conclusive.",
        "stage_2":     f"VERDICT: First serious review (n={n}). Patterns may be meaningful.",
        "stage_3":     f"VERDICT: Stronger evidence tier (n={n}).",
    }
    lines.append(stage_msgs.get(stage_name, f"VERDICT: n={n}."))

    j_pnl = system["avg_pnl_per_unit"]
    b_pnl = baseline["avg_pnl_per_unit"]
    if j_pnl is not None and b_pnl is not None:
        diff = j_pnl - b_pnl
        if abs(diff) < 0.005:
            lines.append(f"PnL: SYSTEM ({j_pnl:+.4f}) and BASELINE ({b_pnl:+.4f}) are effectively tied.")
        elif diff > 0:
            lines.append(f"PnL: SYSTEM ({j_pnl:+.4f}) outperforms BASELINE ({b_pnl:+.4f}) by {diff:+.4f}.")
        else:
            lines.append(
                f"PnL: SYSTEM ({j_pnl:+.4f}) underperforms BASELINE ({b_pnl:+.4f}) by {diff:+.4f}. "
                "Gap is likely execution cost (SYSTEM enters at ask, BASELINE at mid)."
            )

    if stage_name in ("empty", "pre_stage_1"):
        lines.append("Conclusion: NONE. Sample too small or empty.")
    elif stage_name == "stage_1":
        lines.append("Conclusion: Provisional only. Do not act on these numbers.")
    else:
        lines.append("Conclusion: Review warranted. Cross-check with demotion/filter anatomy.")

    return " ".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not LEDGER_PATH.exists():
        print(f"ERROR: Ledger not found at {LEDGER_PATH}")
        print("Set LEDGER_PATH at the top of this script to your ledger file.")
        sys.exit(1)

    data = json.loads(LEDGER_PATH.read_text())
    rows = data.get("rows", [])

    outcome_field = FIELD_CONFIG["outcome"]

    # Build resolved cohort (matches COHORT_FILTERS + has a YES/NO outcome)
    cohort = [
        r for r in rows
        if passes_filters(r, COHORT_FILTERS)
        and r.get(outcome_field) in ("YES", "NO")
    ]

    # Open positions in cohort (for context)
    cohort_open = [
        r for r in rows
        if passes_filters(r, COHORT_FILTERS)
        and r.get(outcome_field) not in ("YES", "NO")
    ]

    n     = len(cohort)
    stage = determine_stage(n)

    entry_actual = FIELD_CONFIG["entry_price_actual"]
    entry_mid    = FIELD_CONFIG["entry_price_mid"]

    # Row-level arms
    system   = cohort_stats(cohort, entry_actual, SYSTEM_LABEL)
    baseline = cohort_stats(cohort, entry_mid,    BASELINE_LABEL)
    verdict  = build_verdict(system, baseline, stage)

    # Hit-rate decomposition
    hrd_sys  = hit_rate_decomposition(cohort, entry_actual, SYSTEM_LABEL)
    hrd_base = hit_rate_decomposition(cohort, entry_mid,    BASELINE_LABEL)
    hrd_cmp  = hit_rate_comparison(hrd_sys, hrd_base)

    # Event-level dedup
    deduped, event_meta = build_event_level_cohort(cohort)
    ev_n     = len(deduped)
    ev_sys   = cohort_stats(deduped, entry_actual, SYSTEM_LABEL)
    ev_base  = cohort_stats(deduped, entry_mid,    BASELINE_LABEL)
    ev_delta = (
        round(ev_sys["avg_pnl_per_unit"] - ev_base["avg_pnl_per_unit"], 4)
        if ev_sys["avg_pnl_per_unit"] is not None and ev_base["avg_pnl_per_unit"] is not None
        else None
    )
    all_slugs = set(r.get(FIELD_CONFIG["slug"]) for r in cohort if r.get(FIELD_CONFIG["slug"]))

    ev_hrd_sys  = hit_rate_decomposition(deduped, entry_actual, SYSTEM_LABEL)
    ev_hrd_base = hit_rate_decomposition(deduped, entry_mid,    BASELINE_LABEL)
    ev_hrd_cmp  = hit_rate_comparison(ev_hrd_sys, ev_hrd_base)

    now_iso = datetime.now(timezone.utc).isoformat()

    report = {
        "report":           "forward_benchmark",
        "generated_at":     now_iso,
        "schema_version":   "1.0",
        "framework":        "generic-binary-outcome-cohort-benchmark",
        "cohort_definition": {
            "filters_applied": COHORT_FILTERS,
            "n_resolved":      n,
            "n_open":          len(cohort_open),
            "note": (
                "Cohort is defined by COHORT_FILTERS. Do not change filters after first "
                "production run — post-hoc filter changes invalidate the comparison."
            ),
        },
        "baseline_definition": {
            "name":        BASELINE_LABEL,
            "description": (
                f"For every row in the cohort, enter at {entry_mid} (mid/fair-value). "
                "PnL = payout - mid_price. This is the naive cost-of-ignorance baseline."
            ),
            "entry_price_field": entry_mid,
            "note": (
                "Fixed naive baseline. Do not add variants or optimize after seeing results."
            ),
        },
        "stage": {
            "current":      stage[0],
            "description":  stage[1],
            "thresholds":   STAGE_THRESHOLDS,
        },
        "arms": {
            SYSTEM_LABEL:   system,
            BASELINE_LABEL: baseline,
        },
        "comparison": {
            "pnl_delta": (
                round(system["avg_pnl_per_unit"] - baseline["avg_pnl_per_unit"], 4)
                if system["avg_pnl_per_unit"] is not None
                and baseline["avg_pnl_per_unit"] is not None
                else None
            ),
            "pnl_delta_note": (
                "Negative means SYSTEM underperforms BASELINE. "
                "Expected to be slightly negative when SYSTEM enters at ask and BASELINE at mid "
                "(gap = half-spread per unit). A system that adds no selection value will "
                "show a gap equal to approximately the spread cost."
            ),
            "calibration_gap_note": (
                "Calibration gap is identical for both arms on the same cohort. "
                "It measures selection power (did the system pick markets that resolved "
                "YES more often than price implied?), not entry pricing."
            ),
        },
        "verdict": verdict,
        "hit_rate_decomposition": {
            "_note": (
                "Hit-rate / payoff-ratio decomposition. Row-level cohort. "
                "hit_rate is structurally identical for both arms on the same cohort — "
                "any difference signals a data problem, not a system property."
            ),
            SYSTEM_LABEL:   hrd_sys,
            BASELINE_LABEL: hrd_base,
            "comparison":   hrd_cmp,
        },
        "event_level": {
            "_note": (
                "Event-level dedup — for independence hygiene. One representative per "
                f"{FIELD_CONFIG['event_group_id']} group. Row-level benchmark above is primary."
            ),
            "_method": (
                "Representative selected by: (1) tier rank A>B>C, "
                "(2) earliest scan_time, (3) slug ascending. Deterministic."
            ),
            "unique_group_count": ev_n,
            "unique_slug_count":  len(all_slugs),
            "arms": {
                SYSTEM_LABEL:   ev_sys,
                BASELINE_LABEL: ev_base,
            },
            "comparison": {
                "pnl_delta": ev_delta,
                "pnl_delta_note": (
                    "Event-level delta. Same interpretation as row-level. "
                    "Negative = SYSTEM underperforms at the event-resolution level."
                ),
            },
            "groups": event_meta,
            "hit_rate_decomposition": {
                "_note": "Same decomposition on event-level dedup cohort.",
                SYSTEM_LABEL:   ev_hrd_sys,
                BASELINE_LABEL: ev_hrd_base,
                "comparison":   ev_hrd_cmp,
            },
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2))
    print(f"  Written: {OUT_JSON}")

    # Console summary
    W = 72
    print()
    print("=" * W)
    print("FORWARD BENCHMARK — BINARY COHORT COMPARISON")
    print("=" * W)
    print(f"  Generated : {now_iso[:19]}Z")
    print(f"  Cohort    : {n} resolved  /  {len(cohort_open)} open")
    print(f"  Stage     : {stage[0]} — {stage[1]}")
    print()

    if n == 0:
        print(f"  {verdict}")
        print("=" * W)
        return

    hdr = f"  {'Arm':<25} {'n':>4} {'YES%':>6} {'avg_mid':>8} {'cal_gap':>8} {'avg_pnl':>8} {'spread':>7}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))

    def fmt(v, w=7):
        return f"{v:>{w}.4f}" if v is not None else f"{'—':>{w}}"

    for arm in [system, baseline]:
        print(
            f"  {arm['label']:<25} {arm['n']:>4d} "
            f"{fmt(arm['yes_rate'], 6)} "
            f"{fmt(arm['avg_mid_at_scan'])} "
            f"{fmt(arm['calibration_gap'], 8)} "
            f"{fmt(arm['avg_pnl_per_unit'], 8)} "
            f"{fmt(arm['avg_spread_cost'])}"
        )

    delta = report["comparison"]["pnl_delta"]
    if delta is not None:
        print()
        print(f"  PnL delta (SYSTEM - BASELINE): {delta:+.4f}")

    print()
    print(f"  {verdict}")
    print()

    # Event-level summary
    ev_d = event_level = report["event_level"]
    print(f"  EVENT-LEVEL DEDUP: {ev_n} groups  /  {len(all_slugs)} unique slugs")
    if ev_delta is not None:
        print(f"  PnL delta (event-level): {ev_delta:+.4f}")
    print()

    # Hit-rate decomposition
    print("  HIT-RATE / PAYOFF DECOMPOSITION (row-level)")
    print(f"  {'Arm':<25} {'hit%':>6} {'avg_win':>8} {'avg_loss':>9} {'payoff':>7} {'expect':>8}")
    print("  " + "─" * 65)
    for h in [hrd_sys, hrd_base]:
        ps  = f"{h['profitable_share']:.3f}" if h['profitable_share'] is not None else "—"
        aw  = f"{h['avg_win_pnl']:+.4f}"  if h['avg_win_pnl']  is not None else "—"
        al  = f"{h['avg_loss_pnl']:+.4f}" if h['avg_loss_pnl'] is not None else "—"
        pr  = f"{h['payoff_ratio']:.3f}"   if h['payoff_ratio'] is not None else "—"
        ex  = f"{h['expectancy_per_unit']:+.4f}" if h['expectancy_per_unit'] is not None else "—"
        print(f"  {h['label']:<25} {ps:>6} {aw:>8} {al:>9} {pr:>7} {ex:>8}")

    c = hrd_cmp
    print()
    print(f"  DELTA (SYSTEM − BASELINE, row-level):")
    for k, v in [
        ("hit_rate_delta",     c["hit_rate_delta"]),
        ("avg_win_delta",      c["avg_win_delta"]),
        ("avg_loss_delta",     c["avg_loss_delta"]),
        ("payoff_ratio_delta", c["payoff_ratio_delta"]),
        ("expectancy_delta",   c["expectancy_delta"]),
    ]:
        vs = f"{v:+.4f}" if v is not None else "—"
        print(f"    {k:<22}: {vs}")

    print()
    print(f"  NOTE: {c['interpretation_note']}")
    print("=" * W)


if __name__ == "__main__":
    main()
