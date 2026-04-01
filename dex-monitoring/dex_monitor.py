#!/usr/bin/env python3
"""
dex_monitor.py — DEX dataset integrity monitor

Reads existing snapshot and toxicity JSONL files.
Produces structured health outputs for operational monitoring.
Does NOT modify scores, thresholds, bands, or any frozen scoring logic.

Outputs (all to logs/dex/):
  completeness_latest.json    — snapshot counts vs expected 288/day/stream
  timestamp_gap_latest.json   — freshness deltas + cross-venue pairing gaps
  correlation_latest.json     — rolling 24h Pearson r of raw scores per pair
  band_health_latest.json     — 24h band distribution per venue/pair (observational)
  lag_diag_latest.json        — T vs T+1h/2h/4h spread expansion scaffold
  data_health_latest.json     — umbrella summary of all above

IMPORTANT: These outputs are structural integrity checks only.
Completeness and band distribution metrics require at least 5 days of continuous
collection before they are meaningful. Do not adjust scoring thresholds based
on band distribution alone.
"""

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter, defaultdict
from typing import Optional, List, Dict, Tuple

LOGS = Path("logs/dex")
LOGS.mkdir(parents=True, exist_ok=True)

EXPECTED_PER_DAY = 288  # 24h × 12 snapshots/hour (5-min interval)
COMPLETENESS_FLAG_THRESHOLD = 0.95

VENUE_PAIRS = [
    ("hyperliquid", "BTC-PERP", "hl_btcperp"),
    ("hyperliquid", "ETH-PERP", "hl_ethperp"),
    ("dydx",        "BTC-PERP", "dx_btcperp"),
    ("dydx",        "ETH-PERP", "dx_ethperp"),
]

VENUE_KEY_MAP = {
    ("hyperliquid", "BTC-PERP"): "hl_btcperp",
    ("hyperliquid", "ETH-PERP"): "hl_ethperp",
    ("dydx",        "BTC-PERP"): "dx_btcperp",
    ("dydx",        "ETH-PERP"): "dx_ethperp",
}

# Backtest horizons in snapshot units (1 snapshot = 5 min)
LAG_HORIZONS = {"1h": 12, "2h": 24, "4h": 48}


# ── Data Loaders ─────────────────────────────────────────────────────

def load_snapshots(days_back: int = 1) -> Dict[str, List[dict]]:
    """Load raw snapshot JSONL entries for last N days, grouped by venue_pair."""
    now = datetime.now(timezone.utc)
    groups: Dict[str, List[dict]] = defaultdict(list)

    for d in range(days_back + 1):
        dt = now - timedelta(days=d)
        fname = LOGS / f"dex_snapshots_{dt.strftime('%Y%m%d')}.jsonl"
        if not fname.exists():
            continue
        with open(fname) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    key = entry.get("venue_pair", "")
                    groups[key].append(entry)
                except json.JSONDecodeError:
                    continue

    for key in groups:
        groups[key].sort(key=lambda e: e.get("timestamp", ""))

    return dict(groups)


def load_toxicity(days_back: int = 1) -> Dict[str, List[dict]]:
    """Load toxicity JSONL entries for last N days, grouped by canonical venue/pair key."""
    now = datetime.now(timezone.utc)
    groups: Dict[str, List[dict]] = defaultdict(list)

    for d in range(days_back + 1):
        dt = now - timedelta(days=d)
        fname = LOGS / f"dex_toxicity_{dt.strftime('%Y%m%d')}.jsonl"
        if not fname.exists():
            continue
        with open(fname) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    key = VENUE_KEY_MAP.get((entry.get("venue",""), entry.get("pair","")), "")
                    if key:
                        groups[key].append(entry)
                except json.JSONDecodeError:
                    continue

    for key in groups:
        groups[key].sort(key=lambda e: e.get("timestamp", ""))

    return dict(groups)


# ── 1. Completeness ──────────────────────────────────────────────────

def compute_completeness(snap_groups: Dict[str, List[dict]], ts: str) -> dict:
    streams = {}
    all_ok = True

    for _, _, key in VENUE_PAIRS:
        entries = snap_groups.get(key, [])
        actual = len(entries)
        pct = actual / EXPECTED_PER_DAY
        flagged = pct < COMPLETENESS_FLAG_THRESHOLD
        if flagged:
            all_ok = False
        streams[key] = {
            "expected": EXPECTED_PER_DAY,
            "actual": actual,
            "completeness_pct": round(pct * 100, 1),
            "flag_below_95": flagged,
        }

    return {
        "timestamp": ts,
        "window_days": 1,
        "expected_per_stream_per_day": EXPECTED_PER_DAY,
        "all_streams_ok": all_ok,
        "streams": streams,
        "note": (
            "Flag is informational only. "
            "Low completeness in the first 1-5 days is expected — cron may not yet be "
            "running a full 24h cycle. Evaluate completeness from Day 5 onward."
        ),
    }


# ── 2. Timestamp / Freshness ─────────────────────────────────────────

def _percentile(vals: List[float], p: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, int(math.ceil(len(s) * p)) - 1)
    return round(s[max(0, idx)], 3)


def compute_timestamp_gaps(snap_groups: Dict[str, List[dict]], ts: str) -> dict:
    # Per-stream freshness (HL only has source_ts_ms)
    freshness: Dict[str, dict] = {}
    for _, _, key in VENUE_PAIRS:
        entries = snap_groups.get(key, [])
        deltas = [
            e["freshness_delta_s"]
            for e in entries
            if e.get("freshness_delta_s") is not None
        ]
        if deltas:
            freshness[key] = {
                "n": len(deltas),
                "mean_delta_s": round(sum(deltas) / len(deltas), 3),
                "p95_delta_s": _percentile(deltas, 0.95),
                "max_delta_s": round(max(deltas), 3),
            }
        else:
            freshness[key] = {
                "n": 0,
                "mean_delta_s": None,
                "p95_delta_s": None,
                "max_delta_s": None,
                "note": "no source timestamp available for this venue",
            }

    # Cross-venue timestamp gap: for each HL snapshot, find nearest DX snapshot for same pair
    cross_venue: Dict[str, dict] = {}
    for pair_label, hl_key, dx_key in [("BTC-PERP", "hl_btcperp", "dx_btcperp"),
                                         ("ETH-PERP", "hl_ethperp", "dx_ethperp")]:
        hl_entries = snap_groups.get(hl_key, [])
        dx_entries = snap_groups.get(dx_key, [])

        if not hl_entries or not dx_entries:
            cross_venue[pair_label] = {"status": "insufficient_data", "n_pairs": 0}
            continue

        # Build index of dx timestamps for fast nearest-neighbor lookup
        dx_ts_list = []
        for e in dx_entries:
            try:
                dt = datetime.fromisoformat(e["timestamp"]).timestamp()
                dx_ts_list.append(dt)
            except Exception:
                continue

        gaps = []
        for hl_e in hl_entries:
            try:
                hl_t = datetime.fromisoformat(hl_e["timestamp"]).timestamp()
            except Exception:
                continue
            # Find closest dx timestamp
            if not dx_ts_list:
                continue
            closest_gap = min(abs(hl_t - dx_t) for dx_t in dx_ts_list)
            gaps.append(closest_gap)

        if gaps:
            cross_venue[pair_label] = {
                "n_pairs": len(gaps),
                "mean_gap_s": round(sum(gaps) / len(gaps), 3),
                "p95_gap_s": _percentile(gaps, 0.95),
                "max_gap_s": round(max(gaps), 3),
            }
        else:
            cross_venue[pair_label] = {"status": "no_overlap", "n_pairs": 0}

    return {
        "timestamp": ts,
        "source_ts_availability": {
            "hyperliquid": "native_ms_timestamp — field 'time' in l2Book response",
            "dydx": "none — v4 orderbook endpoint does not expose timestamp; local collection time used only",
        },
        "freshness_by_stream": freshness,
        "cross_venue_gap": cross_venue,
        "note": (
            "Freshness delta = local_collection_ts minus HL source_ts. "
            "Negative delta indicates local clock slightly behind HL server clock (normal). "
            "Cross-venue gap = time between nearest HL and DX snapshots for same pair."
        ),
    }


# ── 3. Cross-Venue Raw Score Correlation ────────────────────────────

def _pearson_r(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 4)


def _align_series(a_entries: List[dict], b_entries: List[dict],
                  window_s: float = 180.0) -> Tuple[List[float], List[float]]:
    """Align two time series by nearest timestamp within window_s seconds."""
    xs, ys = [], []
    b_times = [(datetime.fromisoformat(e["timestamp"]).timestamp(), e["toxicity_score"])
               for e in b_entries if "toxicity_score" in e]
    for a_e in a_entries:
        if "toxicity_score" not in a_e:
            continue
        try:
            a_t = datetime.fromisoformat(a_e["timestamp"]).timestamp()
        except Exception:
            continue
        # Find closest b entry
        best = min(b_times, key=lambda bt: abs(bt[0] - a_t), default=None)
        if best and abs(best[0] - a_t) <= window_s:
            xs.append(a_e["toxicity_score"])
            ys.append(best[1])
    return xs, ys


def compute_correlation(tox_groups: Dict[str, List[dict]], ts: str) -> dict:
    pairs_out = {}
    MIN_N = 10  # minimum overlap samples required

    for pair_label, hl_key, dx_key in [("BTC", "hl_btcperp", "dx_btcperp"),
                                         ("ETH", "hl_ethperp", "dx_ethperp")]:
        hl = tox_groups.get(hl_key, [])
        dx = tox_groups.get(dx_key, [])

        if len(hl) < MIN_N or len(dx) < MIN_N:
            pairs_out[f"{pair_label}_hl_vs_dx"] = {
                "status": "insufficient_data",
                "hl_n": len(hl),
                "dx_n": len(dx),
                "min_required": MIN_N,
                "pearson_r": None,
                "n_overlap": 0,
            }
            continue

        xs, ys = _align_series(hl, dx)
        n_overlap = len(xs)

        if n_overlap < MIN_N:
            pairs_out[f"{pair_label}_hl_vs_dx"] = {
                "status": "insufficient_overlap",
                "n_overlap": n_overlap,
                "min_required": MIN_N,
                "pearson_r": None,
            }
            continue

        r = _pearson_r(xs, ys)
        pairs_out[f"{pair_label}_hl_vs_dx"] = {
            "status": "ok" if r is not None else "zero_variance",
            "n_overlap": n_overlap,
            "pearson_r": r,
        }

    return {
        "timestamp": ts,
        "window_hours": 24,
        "alignment_window_s": 180,
        "pairs": pairs_out,
        "note": (
            "Correlation measures co-movement of raw toxicity scores across venues for same asset. "
            "High correlation (>0.7) expected if both venues react to same underlying market conditions. "
            "Low correlation may indicate venue-specific noise or collection timing asymmetry."
        ),
    }


# ── 4. Band Health ───────────────────────────────────────────────────

def compute_band_health(tox_groups: Dict[str, List[dict]], ts: str) -> dict:
    streams = {}
    for _, _, key in VENUE_PAIRS:
        entries = tox_groups.get(key, [])
        n = len(entries)
        if n == 0:
            streams[key] = {"n": 0, "distribution": {}}
            continue
        band_counts = Counter(e.get("toxicity_band", "UNKNOWN") for e in entries)
        scores = [e.get("toxicity_score", 0) for e in entries]
        streams[key] = {
            "n": n,
            "avg_score": round(sum(scores) / len(scores), 1),
            "distribution": {
                band: {
                    "count": band_counts.get(band, 0),
                    "pct": round(band_counts.get(band, 0) / n * 100, 1),
                }
                for band in ["LOW", "NORMAL", "ELEVATED", "TOXIC"]
            },
        }

    return {
        "timestamp": ts,
        "window_hours": 24,
        "streams": streams,
        "target_distribution_note": (
            "After baseline stabilizes (~Day 5): LOW 60-70%, NORMAL 20-25%, "
            "ELEVATED 8-12%, TOXIC 2-5% expected under normal market conditions. "
            "IMPORTANT: Band distribution normalization is observational only. "
            "Do not adjust scoring thresholds based on distribution alone."
        ),
    }


# ── 5. Lag Diagnostic Scaffold ────────────────────────────────────────

def compute_lag_diag(snap_groups: Dict[str, List[dict]],
                     tox_groups: Dict[str, List[dict]], ts: str) -> dict:
    """
    For each scored snapshot, attempt to pair with future spread values at T+1h/2h/4h.
    Pure data pairing scaffold — no analysis performed here.
    """
    pairs_out = []

    for _, _, key in VENUE_PAIRS:
        tox_entries = tox_groups.get(key, [])
        snap_entries = snap_groups.get(key, [])

        # Build lookup: timestamp -> eff_spread_bps from raw snapshots
        spread_lookup: Dict[str, Optional[float]] = {}
        for se in snap_entries:
            spread_lookup[se["timestamp"]] = se.get("features", {}).get("eff_spread_bps")

        # Build ordered spread timeseries for future lookup
        spread_ts_ordered = [
            (datetime.fromisoformat(se["timestamp"]).timestamp(),
             se.get("features", {}).get("eff_spread_bps"),
             se["timestamp"])
            for se in snap_entries
            if "features" in se
        ]
        spread_ts_ordered.sort()

        for tox_e in tox_entries:
            try:
                t0 = datetime.fromisoformat(tox_e["timestamp"]).timestamp()
            except Exception:
                continue

            spread_t = tox_e.get("inputs", {}).get("eff_spread_latest")

            horizon_values: Dict[str, Optional[float]] = {}
            expansion_values: Dict[str, Optional[float]] = {}

            for label, n_snaps in LAG_HORIZONS.items():
                target_t = t0 + n_snaps * 300  # 300s = 5min per snap
                # Find closest snapshot within ±90s of target
                best_spread = None
                best_gap = float("inf")
                for st, sv, _ in spread_ts_ordered:
                    gap = abs(st - target_t)
                    if gap < best_gap and gap <= 90:
                        best_gap = gap
                        best_spread = sv

                horizon_values[f"eff_spread_{label}"] = best_spread
                if spread_t is not None and best_spread is not None:
                    expansion_values[f"spread_expansion_{label}"] = round(
                        best_spread - spread_t, 4
                    )
                else:
                    expansion_values[f"spread_expansion_{label}"] = None

            # Only include if at least T exists
            if spread_t is not None:
                pairs_out.append({
                    "venue_pair": key,
                    "t": tox_e["timestamp"],
                    "toxicity_score_t": tox_e.get("toxicity_score"),
                    "toxicity_band_t": tox_e.get("toxicity_band"),
                    "eff_spread_t": spread_t,
                    **horizon_values,
                    **expansion_values,
                })

    # Summary counts
    with_1h = sum(1 for p in pairs_out if p.get("eff_spread_1h") is not None)
    with_2h = sum(1 for p in pairs_out if p.get("eff_spread_2h") is not None)
    with_4h = sum(1 for p in pairs_out if p.get("eff_spread_4h") is not None)

    return {
        "timestamp": ts,
        "total_scored_snapshots": len(pairs_out),
        "pairs_with_1h_future": with_1h,
        "pairs_with_2h_future": with_2h,
        "pairs_with_4h_future": with_4h,
        "backtest_ready": with_1h >= 50,
        "note": (
            "This file is a data scaffold only. No interpretation performed. "
            "spread_expansion_Xh = eff_spread at T+Xh minus eff_spread at T (bps). "
            "Positive = spread widened. Negative = spread compressed. "
            "Scaffold is ready for analysis when pairs_with_1h_future >= 50."
        ),
        "pairs": pairs_out,
    }


# ── Umbrella Summary ─────────────────────────────────────────────────

def compute_data_health(completeness: dict, ts_gaps: dict,
                        correlation: dict, band_health: dict,
                        lag_diag: dict, ts: str) -> dict:
    total_snaps = sum(
        s["actual"] for s in completeness["streams"].values()
    )
    any_completeness_flag = any(
        s["flag_below_95"] for s in completeness["streams"].values()
    )
    corr_ok = any(
        p.get("status") == "ok"
        for p in correlation["pairs"].values()
    )
    backtest_ready = lag_diag["backtest_ready"]

    status = "ACCUMULATING"
    if total_snaps >= 50 * 4 and not any_completeness_flag:
        status = "HEALTHY"

    return {
        "timestamp": ts,
        "overall_status": status,
        "total_snapshots_24h": total_snaps,
        "completeness_flag": any_completeness_flag,
        "correlation_available": corr_ok,
        "backtest_scaffold_ready": backtest_ready,
        "lag_diag_pairs_1h": lag_diag["pairs_with_1h_future"],
        "gate_day10_checklist": {
            "collector_stable": not any_completeness_flag,
            "data_integrity_ok": total_snaps > 0,
            "cross_venue_correlation_computed": corr_ok,
            "backtest_scaffold_populated": backtest_ready,
        },
        "note": (
            "ACCUMULATING is expected status for the first 1-5 days. "
            "HEALTHY requires 24h of continuous collection with <5% gaps across all streams."
        ),
    }


# ── Main ──────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    ts = now.isoformat()

    print(f"[{ts}] dex_monitor run start")

    snap_groups = load_snapshots(days_back=1)
    tox_groups  = load_toxicity(days_back=1)

    total_snaps = sum(len(v) for v in snap_groups.values())
    total_tox   = sum(len(v) for v in tox_groups.values())
    print(f"  loaded: {total_snaps} snap entries, {total_tox} tox entries")

    # Compute all outputs
    completeness = compute_completeness(snap_groups, ts)
    ts_gaps      = compute_timestamp_gaps(snap_groups, ts)
    correlation  = compute_correlation(tox_groups, ts)
    band_health  = compute_band_health(tox_groups, ts)
    lag_diag     = compute_lag_diag(snap_groups, tox_groups, ts)
    data_health  = compute_data_health(completeness, ts_gaps, correlation,
                                       band_health, lag_diag, ts)

    # Write outputs
    outputs = {
        "completeness_latest.json":    completeness,
        "timestamp_gap_latest.json":   ts_gaps,
        "correlation_latest.json":     correlation,
        "band_health_latest.json":     band_health,
        "lag_diag_latest.json":        lag_diag,
        "data_health_latest.json":     data_health,
    }

    for fname, data in outputs.items():
        path = LOGS / fname
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    # Console summary
    print(f"  status           : {data_health['overall_status']}")
    print(f"  completeness_flag: {data_health['completeness_flag']}")
    print(f"  correlation_ok   : {data_health['correlation_available']}")
    print(f"  backtest_ready   : {data_health['backtest_scaffold_ready']}")
    print(f"  lag_diag pairs   : {lag_diag['pairs_with_1h_future']} with 1h future")
    print(f"  outputs written  : {list(outputs.keys())}")
    print(f"[{ts}] dex_monitor done")


if __name__ == "__main__":
    main()
