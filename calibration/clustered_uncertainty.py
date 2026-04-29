#!/usr/bin/env python3
"""
clustered_uncertainty.py — Clustered Bootstrap Uncertainty Analysis
====================================================================

Computes statistically honest confidence intervals for binary-outcome
measurement systems where observations are not independent.

THE CORE PROBLEM
----------------
In binary scored systems, multiple rows often belong to the same underlying
event or entity. Treating these as independent samples overstates precision:
the naive ±1.96σ/√n CI can be 3–5× too tight when events cluster.

This tool bootstraps at the cluster level: it resamples CLUSTERS (events,
entities, or whatever grouping unit applies) rather than individual rows.
The resulting CI reflects the true independent evidence in the data.

THREE SAMPLE-SIZE COUNTS
-------------------------
Row N     — total rows in cohort. NOT the independent evidence count.
Slug/ID N — unique market/asset identifiers. Better than row N.
Cluster N — unique event/entity groups. Most conservative, most honest.

Always use cluster N for headline uncertainty statements.

INPUT SCHEMA (edit FIELD_CONFIG and COHORT_FILTERS below)
----------------------------------------------------------
Ledger file must be JSON with a top-level "rows" array. Each row should have:

  Required:
    pnl_field          float   realized PnL per unit (positive = win, negative = loss)
    cluster_field      str     grouping identifier (e.g. event title, entity name)

  Optional:
    baseline_pnl_field float   baseline PnL per unit at the same row (for delta CI)
                               If absent, set BASELINE_PNL_FIELD = None below.
    slug_field         str     unique market/asset identifier
    outcome_field      str     "YES" / "NO" for cohort filtering

  For cohort filtering (set COHORT_FILTERS to match your schema):
    source             str     e.g. "forward_live"
    eligible           bool    True/False

OUTPUT
------
  logs/clustered_uncertainty_latest.json — full results in JSON
  Terminal report with absolute PnL CI and (if configured) baseline delta CI

USAGE
-----
  1. Edit FIELD_CONFIG and COHORT_FILTERS below.
  2. python3 clustered_uncertainty.py

NO PRODUCTION LOGIC IS CHANGED BY THIS SCRIPT. Read-only measurement.
"""

import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration — edit these to match your schema ──────────────────────────

LEDGER_PATH = Path("logs/forward_benchmark_ledger.json")
OUT_PATH    = Path("logs/clustered_uncertainty_latest.json")

FIELD_CONFIG = {
    # Core metric field: the per-row PnL / score value being analyzed
    "pnl_field":           "realized_pnl_per_1_unit",

    # Cluster grouping field: rows are grouped by this for bootstrap resampling
    "cluster_field":       "event_title",

    # Optional: baseline PnL field for computing SYSTEM - BASELINE delta CI
    # Set to None to skip the delta CI section entirely
    "baseline_pnl_field":  "gross_edge_vs_mid",

    # Unique identifier field (for slug-level count)
    "slug_field":          "slug",

    # Outcome field (used for strict cohort filtering)
    "outcome_field":       "outcome",
}

# Cohort filters — only rows matching ALL conditions are included (strict cohort)
# The tool will fall back to a wider cohort if strict yields < 2 rows
COHORT_FILTERS_STRICT = {
    "source":                 "forward_live",
    "resolved":               True,
    "actionable_eligible":    True,
    "execution_price_source": "actual_l1",
    "policy_status":          "ACTIONABLE_ELIGIBLE",
}

# Wider cohort fallback — fewer filters, used when strict cohort is too small
COHORT_FILTERS_WIDE = {
    "source":              "forward_live",
    "resolved":            True,
    "actionable_eligible": True,
}

# Bootstrap parameters
N_BOOTSTRAP = 5_000
SEED        = 42
CI_LEVEL    = 0.95


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path):
    with open(path) as f:
        return json.load(f)


def normalize_cluster_key(value):
    """Consistent grouping key: strip, lowercase, collapse whitespace."""
    if not value:
        return "__unknown__"
    return " ".join(str(value).strip().lower().split())


def passes_filters_strict(row, filters):
    for field, expected in filters.items():
        if row.get(field) != expected:
            return False
    return True


def filter_cohort(rows, strict=True):
    """Filter rows to the configured cohort."""
    filters = COHORT_FILTERS_STRICT if strict else COHORT_FILTERS_WIDE
    outcome_field = FIELD_CONFIG["outcome_field"]
    out = []
    for r in rows:
        if not passes_filters_strict(r, filters):
            continue
        # Resolved means outcome must be YES or NO
        if r.get(outcome_field) not in ("YES", "NO"):
            continue
        out.append(r)
    return out


def cluster_rows(rows):
    """Group rows by normalized cluster_field. Returns dict: key → list[row]."""
    cf = FIELD_CONFIG["cluster_field"]
    clusters = defaultdict(list)
    for r in rows:
        key = normalize_cluster_key(r.get(cf))
        clusters[key].append(r)
    return dict(clusters)


# ── Metrics ───────────────────────────────────────────────────────────────────

def avg_metric(rows, field):
    vals = [r[field] for r in rows if r.get(field) is not None]
    return statistics.mean(vals) if vals else None


def event_level_avg(clusters, field):
    """Mean of per-cluster means — one weight per cluster, not per row."""
    cluster_means = []
    for rows in clusters.values():
        m = avg_metric(rows, field)
        if m is not None:
            cluster_means.append(m)
    return statistics.mean(cluster_means) if cluster_means else None


def per_row_delta(r):
    """
    SYSTEM minus BASELINE delta for a single row.
    = pnl_field - baseline_pnl_field
    If BASELINE_PNL_FIELD is None, returns None everywhere.
    """
    pf = FIELD_CONFIG["pnl_field"]
    bf = FIELD_CONFIG["baseline_pnl_field"]
    if bf is None:
        return None
    pnl      = r.get(pf)
    baseline = r.get(bf)
    if pnl is None or baseline is None:
        return None
    return pnl - baseline


def avg_delta(rows):
    vals = [per_row_delta(r) for r in rows]
    vals = [v for v in vals if v is not None]
    return statistics.mean(vals) if vals else None


def event_level_avg_delta(clusters):
    cluster_means = []
    for rows in clusters.values():
        m = avg_delta(rows)
        if m is not None:
            cluster_means.append(m)
    return statistics.mean(cluster_means) if cluster_means else None


# ── Clustered bootstrap CI ────────────────────────────────────────────────────

def clustered_bootstrap_ci(clusters, stat_fn, n_boot, rng, ci_level):
    """
    Bootstrap by resampling CLUSTERS (not rows) with replacement.
    stat_fn: function(list_of_rows) → scalar.
    Returns (lower, upper, boot_mean, boot_std) or (None, None, None, None).
    """
    event_keys = list(clusters.keys())
    n_events   = len(event_keys)
    if n_events < 2:
        return None, None, None, None

    boot_stats = []
    for _ in range(n_boot):
        sampled_keys = rng.choices(event_keys, k=n_events)
        sampled_rows = []
        for k in sampled_keys:
            sampled_rows.extend(clusters[k])
        val = stat_fn(sampled_rows)
        if val is not None:
            boot_stats.append(val)

    if len(boot_stats) < 10:
        return None, None, None, None

    boot_stats.sort()
    alpha  = (1.0 - ci_level) / 2
    lo_idx = max(0, int(alpha * len(boot_stats)))
    hi_idx = min(len(boot_stats) - 1, int((1 - alpha) * len(boot_stats)))
    return (
        round(boot_stats[lo_idx], 5),
        round(boot_stats[hi_idx], 5),
        round(statistics.mean(boot_stats), 5),
        round(statistics.stdev(boot_stats), 5) if len(boot_stats) > 1 else None,
    )


# ── Precision verdict ─────────────────────────────────────────────────────────

def precision_verdict(cluster_n):
    if cluster_n == 0:
        return "NO_DATA", "Zero clusters in cohort — no conclusions possible"
    if cluster_n < 5:
        return "EXTREMELY_LOW", f"Only {cluster_n} clusters — any estimate is very unreliable"
    if cluster_n < 10:
        return "LOW", f"{cluster_n} clusters — directional signal possible but wide uncertainty"
    if cluster_n < 20:
        return "MODERATE", f"{cluster_n} clusters — moderate precision; CI meaningful but not tight"
    return "ADEQUATE", f"{cluster_n} clusters — adequate for directional conclusions"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pnl_field  = FIELD_CONFIG["pnl_field"]
    slug_field = FIELD_CONFIG["slug_field"]
    bf         = FIELD_CONFIG["baseline_pnl_field"]

    data     = load_json(LEDGER_PATH)
    all_rows = data.get("rows", [])

    # Try strict cohort, fall back to wide
    strict_rows = filter_cohort(all_rows, strict=True)
    if len(strict_rows) >= 2:
        cohort_rows   = strict_rows
        cohort_label  = "STRICT cohort (all configured filters applied)"
        cohort_strict = True
    else:
        cohort_rows   = filter_cohort(all_rows, strict=False)
        cohort_label  = "WIDE cohort (strict cohort too small, fewer filters applied)"
        cohort_strict = False

    clusters    = cluster_rows(cohort_rows)
    unique_slugs = list({r.get(slug_field, "") for r in cohort_rows if r.get(slug_field)})

    row_n     = len(cohort_rows)
    slug_n    = len(unique_slugs)
    cluster_n = len(clusters)

    row_pnls    = [r[pnl_field] for r in cohort_rows if r.get(pnl_field) is not None]
    row_avg     = statistics.mean(row_pnls) if row_pnls else None
    cluster_avg = event_level_avg(clusters, pnl_field)

    # Concentration
    cluster_sizes = {k: len(v) for k, v in clusters.items()}
    top_cluster   = max(cluster_sizes, key=lambda k: cluster_sizes[k]) if cluster_sizes else None
    top_n         = cluster_sizes.get(top_cluster, 0)
    top_share     = top_n / row_n if row_n > 0 else None

    # Slug-level avg for reference
    slug_clusters = defaultdict(list)
    for r in cohort_rows:
        slug_clusters[r.get(slug_field, "__none__")].append(r)
    slug_avgs   = {s: avg_metric(rows, pnl_field) for s, rows in slug_clusters.items()}
    slug_avgs   = {s: v for s, v in slug_avgs.items() if v is not None}
    slug_level_avg = statistics.mean(slug_avgs.values()) if slug_avgs else None

    # Naïve row-level CI (for comparison — shows what overstated precision looks like)
    if row_pnls and len(row_pnls) > 1:
        row_std     = statistics.stdev(row_pnls)
        se          = row_std / math.sqrt(len(row_pnls))
        naive_lo    = round((row_avg or 0) - 1.96 * se, 5)
        naive_hi    = round((row_avg or 0) + 1.96 * se, 5)
    else:
        naive_lo = naive_hi = None

    # Clustered bootstrap CI — absolute PnL
    rng = random.Random(SEED)

    def stat_cluster_avg(rows):
        c = cluster_rows(rows)
        return event_level_avg(c, pnl_field)

    ci_lo, ci_hi, boot_mean, boot_std = clustered_bootstrap_ci(
        clusters, stat_cluster_avg, N_BOOTSTRAP, rng, CI_LEVEL
    )
    ci_contains_zero = (
        ci_lo is not None and ci_hi is not None and ci_lo <= 0.0 <= ci_hi
    )

    # Clustered bootstrap CI — baseline delta (optional)
    delta_output = None
    if bf is not None:
        # Use wide cohort for delta (more rows have both fields)
        wide_rows     = filter_cohort(all_rows, strict=False)
        wide_clusters = cluster_rows(wide_rows)
        delta_rows_n  = sum(1 for r in wide_rows if per_row_delta(r) is not None)
        delta_row_vals = [per_row_delta(r) for r in wide_rows if per_row_delta(r) is not None]
        delta_row_mean = statistics.mean(delta_row_vals) if delta_row_vals else None
        delta_ev_mean  = event_level_avg_delta(wide_clusters) if wide_clusters else None

        rng2 = random.Random(SEED + 1)

        def stat_delta(rows):
            c = cluster_rows(rows)
            return event_level_avg_delta(c)

        dci_lo, dci_hi, dboot_mean, dboot_std = clustered_bootstrap_ci(
            wide_clusters, stat_delta, N_BOOTSTRAP, rng2, CI_LEVEL
        )
        delta_contains_zero = (
            dci_lo is not None and dci_hi is not None and dci_lo <= 0.0 <= dci_hi
        )
        delta_output = {
            "description": (
                f"SYSTEM minus BASELINE delta per row = {pnl_field} - {bf}. "
                "Clustered CI answers: is the delta distinguishable from zero?"
            ),
            "cohort":              "WIDE (more rows have both fields)",
            "delta_row_n":         delta_rows_n,
            "delta_unique_clusters": len(wide_clusters),
            "delta_row_mean":      round(delta_row_mean, 5) if delta_row_mean is not None else None,
            "delta_cluster_mean":  round(delta_ev_mean, 5)  if delta_ev_mean  is not None else None,
            "clustered_bootstrap": {
                "method":       "Resample clusters, compute cluster-level avg delta per resample",
                "n_bootstrap":  N_BOOTSTRAP,
                "ci_level":     CI_LEVEL,
                "ci_lo":        dci_lo,
                "ci_hi":        dci_hi,
                "boot_mean":    dboot_mean,
                "boot_std":     dboot_std,
                "contains_zero": delta_contains_zero,
            },
            "verdict": (
                "CI excludes zero — delta is systematic, not sampling noise."
                if not delta_contains_zero else
                "CI contains zero — delta is indistinguishable from zero at current N."
            ),
        }

    pv, pn = precision_verdict(cluster_n)

    output = {
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "schema_version":   "1.0",
        "framework":        "generic-clustered-uncertainty",
        "MEASUREMENT_NOTE": (
            "READ-ONLY statistical analysis. No production logic changes. "
            "Clustered bootstrap resamples CLUSTERS not rows to preserve correlation structure. "
            "Always report cluster N as the independent evidence count."
        ),
        "cohort": {
            "label":               cohort_label,
            "strict_cohort_used":  cohort_strict,
        },
        "field_config": {
            "pnl_field":           pnl_field,
            "cluster_field":       FIELD_CONFIG["cluster_field"],
            "baseline_pnl_field":  bf,
            "slug_field":          slug_field,
        },
        "sample_size": {
            "row_n":      row_n,
            "slug_n":     slug_n,
            "cluster_n":  cluster_n,
            "independence_note": (
                "Row N is NOT independent evidence — multiple rows share the same cluster. "
                "Slug N is better (unique assets). Cluster N is most conservative and most honest."
            ),
        },
        "concentration": {
            "top_cluster":          top_cluster,
            "top_cluster_row_count": top_n,
            "top_cluster_share":    round(top_share, 4) if top_share is not None else None,
            "cluster_sizes":        dict(sorted(cluster_sizes.items(), key=lambda x: -x[1])),
        },
        "metric_estimates": {
            "row_level_avg":     round(row_avg, 5)        if row_avg        is not None else None,
            "slug_level_avg":    round(slug_level_avg, 5) if slug_level_avg is not None else None,
            "cluster_level_avg": round(cluster_avg, 5)    if cluster_avg    is not None else None,
            "note": (
                "Row-level is most optimistic (double-counts correlated clusters). "
                "Cluster-level is most conservative and most honest. "
                "Report cluster-level as the headline estimate."
            ),
        },
        "confidence_intervals": {
            "clustered_bootstrap": {
                "method":        "Resample clusters with replacement, compute cluster-level avg metric per resample",
                "n_bootstrap":   N_BOOTSTRAP,
                "ci_level":      CI_LEVEL,
                "ci_lo":         ci_lo,
                "ci_hi":         ci_hi,
                "boot_mean":     boot_mean,
                "boot_std":      boot_std,
                "contains_zero": ci_contains_zero,
            },
            "naive_row_level_ci": {
                "method":  "±1.96 × stdev / √row_n — OVERSTATES precision (ignores clustering)",
                "ci_lo":   naive_lo,
                "ci_hi":   naive_hi,
                "warning": (
                    "Do not use naive CI for decisions. It ignores within-cluster correlation "
                    "and will be 2–5× too tight when cluster sizes are unequal."
                ),
            },
        },
        "precision_verdict": pv,
        "precision_note":    pn,
        "baseline_delta_ci": delta_output,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Console report
    print("=" * 62)
    print("CLUSTERED UNCERTAINTY ANALYSIS")
    print("=" * 62)
    print(f"Cohort         : {'STRICT' if cohort_strict else 'WIDE'}")
    print(f"Row N          : {row_n}  (naive — NOT independent evidence)")
    print(f"Slug N         : {slug_n}  (unique assets)")
    print(f"Cluster N      : {cluster_n}  (independent evidence — USE THIS)")
    print(f"Metric field   : {pnl_field}")
    print(f"Cluster field  : {FIELD_CONFIG['cluster_field']}")
    print()

    print("Metric estimates:")
    if row_avg is not None:
        print(f"  Row-level avg     : {row_avg:+.5f}  (overstates precision)")
    if cluster_avg is not None:
        print(f"  Cluster-level avg : {cluster_avg:+.5f}  (most honest)")
    print()

    print(f"Clustered Bootstrap CI ({CI_LEVEL:.0%}) — absolute metric:")
    if ci_lo is not None:
        sign = "CONTAINS ZERO" if ci_contains_zero else "EXCLUDES ZERO"
        print(f"  [{ci_lo:+.5f}, {ci_hi:+.5f}]  →  {sign}")
        if boot_mean is not None:
            print(f"  Boot mean: {boot_mean:+.5f}  |  Boot std: {boot_std:.5f}")
    else:
        print("  Insufficient data (need ≥ 2 clusters)")

    if delta_output:
        print()
        print("── BASELINE DELTA CI ────────────────────────────────────────")
        print(f"Cohort         : WIDE (N rows={delta_output['delta_row_n']}, clusters={delta_output['delta_unique_clusters']})")
        drm = delta_output["delta_row_mean"]
        dem = delta_output["delta_cluster_mean"]
        if drm is not None:
            print(f"Delta row mean    : {drm:+.5f}")
        if dem is not None:
            print(f"Delta cluster mean: {dem:+.5f}  (most honest)")
        cb = delta_output["clustered_bootstrap"]
        if cb["ci_lo"] is not None:
            sign2 = "CONTAINS ZERO" if cb["contains_zero"] else "EXCLUDES ZERO"
            print(f"Delta CI ({CI_LEVEL:.0%})    : [{cb['ci_lo']:+.5f}, {cb['ci_hi']:+.5f}]  →  {sign2}")
            if cb["boot_mean"] is not None:
                print(f"Boot mean: {cb['boot_mean']:+.5f}  |  Boot std: {cb['boot_std']:.5f}")
        else:
            print("  Insufficient data for delta CI")
        print(f"Verdict: {delta_output['verdict']}")

    print()
    print(f"Concentration  : top cluster = '{top_cluster}' ({top_n} rows, {(top_share or 0):.1%})")
    print(f"Precision      : {pv} — {pn}")
    print(f"Output         : {OUT_PATH}")
    print()


if __name__ == "__main__":
    main()
