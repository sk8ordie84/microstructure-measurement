#!/usr/bin/env python3
"""
dex_aggregator.py — DEX CLOB toxicity scoring engine

Reads raw snapshots from dex_collector.py, computes 1-hour rolling windows,
assigns toxicity scores and bands per venue/pair.

Outputs:
  logs/dex/dex_toxicity_latest.json     — current scores (overwritten)
  logs/dex/dex_toxicity_YYYYMMDD.jsonl  — daily timeseries (append)
  logs/dex/baseline_spread_latest.json  — rolling 7-day p25 per venue/pair

Run after collector, or on same cron schedule.
"""

import json
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict

# ── Config ────────────────────────────────────────────────────────────
CFG = json.loads(Path("config_dex.json").read_text())
LOGS = Path("logs/dex")
LOGS.mkdir(parents=True, exist_ok=True)

WINDOW = CFG["scoring"]["rolling_window_snapshots"]  # 12 = 1 hour
BASELINE_DAYS = CFG["scoring"]["baseline_window_days"]  # 7

SPREAD_MAX   = CFG["scoring"]["spread_score_max"]
THIN_MAX     = CFG["scoring"]["thin_score_max"]
IMBAL_MAX    = CFG["scoring"]["imbalance_score_max"]
INSTAB_MAX   = CFG["scoring"]["instab_score_max"]
THIN_THRESH  = CFG["scoring"]["book_thin_threshold_pct"]
SPREAD_THRESH = CFG["scoring"]["spread_expansion_threshold_bps"]
IMBAL_SCALE  = CFG["scoring"]["imbalance_scale_factor"]
INSTAB_SCALE = CFG["scoring"]["instab_scale_factor"]

BANDS = CFG["bands"]
VENUE_PAIRS = [
    ("hyperliquid", "BTC-PERP", "hl_btcperp"),
    ("hyperliquid", "ETH-PERP", "hl_ethperp"),
    ("dydx", "BTC-PERP", "dx_btcperp"),
    ("dydx", "ETH-PERP", "dx_ethperp"),
]


# ── Data Loading ──────────────────────────────────────────────────────

def load_snapshots(days_back: int = 7) -> Dict[str, List[dict]]:
    """Load JSONL snapshots for the last N days, grouped by venue_pair key."""
    now = datetime.now(timezone.utc)
    groups = {}  # key -> [entries sorted by timestamp]

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
                    if key not in groups:
                        groups[key] = []
                    groups[key].append(entry)
                except json.JSONDecodeError:
                    continue

    # Sort each group by timestamp
    for key in groups:
        groups[key].sort(key=lambda e: e.get("timestamp", ""))

    return groups


# ── Baseline Computation ──────────────────────────────────────────────

def compute_baselines(groups: Dict[str, List[dict]]) -> Dict[str, float]:
    """Compute rolling 7-day p25 of eff_spread_bps per venue/pair."""
    baselines = {}
    for key, entries in groups.items():
        spreads = [
            e["features"]["eff_spread_bps"]
            for e in entries
            if "features" in e and "eff_spread_bps" in e.get("features", {})
               and e["features"]["eff_spread_bps"] is not None
        ]
        if spreads:
            spreads_sorted = sorted(spreads)
            idx25 = max(0, int(len(spreads_sorted) * 0.25))
            baselines[key] = spreads_sorted[idx25]
        else:
            baselines[key] = 1.0  # fallback: 1 bps if no data
    return baselines


# ── Rolling Window Aggregation ────────────────────────────────────────

def aggregate_window(entries: List[dict]) -> Optional[dict]:
    """Compute 1-hour rolling window stats from last WINDOW entries."""
    if len(entries) < 2:
        return None

    window = entries[-WINDOW:]  # last 12 snapshots (or fewer if early)
    n = len(window)

    spreads = [e["features"]["eff_spread_bps"] for e in window
               if e.get("features", {}).get("eff_spread_bps") is not None]
    thinnings = [e["features"]["book_thinning_5m_pct"] for e in window
                 if e.get("features", {}).get("book_thinning_5m_pct") is not None]
    imbalances = [abs(e["features"]["depth_imbalance"]) for e in window
                  if e.get("features", {}).get("depth_imbalance") is not None]
    instabs = [e["features"]["quote_instability"] for e in window
               if e.get("features", {}).get("quote_instability") is not None]
    spread_changes = [e["features"]["spread_change_5m_bps"] for e in window
                      if e.get("features", {}).get("spread_change_5m_bps") is not None]

    if not spreads:
        return None

    spreads_sorted = sorted(spreads)
    p25_idx = max(0, int(len(spreads_sorted) * 0.25))
    p75_idx = min(len(spreads_sorted) - 1, int(len(spreads_sorted) * 0.75))

    spread_expansion_rate = (
        sum(1 for sc in spread_changes if sc > SPREAD_THRESH) / len(spread_changes)
        if spread_changes else 0
    )
    book_thin_rate = (
        sum(1 for bt in thinnings if bt < THIN_THRESH) / len(thinnings)
        if thinnings else 0
    )
    imbalance_abs_mean = statistics.mean(imbalances) if imbalances else 0
    instab_mean = statistics.mean(instabs) if instabs else 0

    return {
        "window_snapshots": n,
        "spread_bps_p25": round(spreads_sorted[p25_idx], 4),
        "spread_bps_p75": round(spreads_sorted[p75_idx], 4),
        "spread_bps_mean": round(statistics.mean(spreads), 4),
        "spread_expansion_rate": round(spread_expansion_rate, 4),
        "book_thin_rate": round(book_thin_rate, 4),
        "imbalance_abs_mean": round(imbalance_abs_mean, 6),
        "quote_instab_mean": round(instab_mean, 4),
        "near_touch_bid_latest": window[-1].get("features", {}).get("near_touch_bid_usd"),
        "near_touch_ask_latest": window[-1].get("features", {}).get("near_touch_ask_usd"),
        "mid_price_latest": window[-1].get("features", {}).get("mid_price"),
        "eff_spread_latest": window[-1].get("features", {}).get("eff_spread_bps"),
    }


# ── Toxicity Scoring ─────────────────────────────────────────────────

def compute_toxicity_score(window_stats: dict, baseline_spread: float) -> dict:
    """Compute additive toxicity score (0-100) from window stats."""
    # Component: spread stress
    p75 = window_stats["spread_bps_p75"]
    if baseline_spread > 0:
        spread_score = min(SPREAD_MAX, max(0, (p75 - baseline_spread) / baseline_spread * SPREAD_MAX))
    else:
        spread_score = 0

    # Component: book thinning
    thin_score = min(THIN_MAX, window_stats["book_thin_rate"] * 100)

    # Component: imbalance stress
    imbal_score = min(IMBAL_MAX, window_stats["imbalance_abs_mean"] * IMBAL_MAX * IMBAL_SCALE)

    # Component: quote instability
    instab_score = min(INSTAB_MAX, window_stats["quote_instab_mean"] * INSTAB_SCALE)

    total = round(spread_score + thin_score + imbal_score + instab_score, 2)
    total = min(100, max(0, total))

    # Band assignment — half-open intervals prevent float gap (e.g. 74.6 matched neither 50-74 nor 75-100)
    if total >= 75:
        band = "TOXIC"
    elif total >= 50:
        band = "ELEVATED"
    elif total >= 25:
        band = "NORMAL"
    else:
        band = "LOW"

    return {
        "toxicity_score": round(total, 1),
        "toxicity_band": band,
        "components": {
            "spread_score": round(spread_score, 2),
            "thin_score": round(thin_score, 2),
            "imbalance_score": round(imbal_score, 2),
            "instab_score": round(instab_score, 2),
        },
    }


# ── Main ──────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    today_str = now.strftime("%Y%m%d")

    print(f"[{ts}] dex_aggregator run start")

    # Load all snapshots (up to 7 days)
    groups = load_snapshots(BASELINE_DAYS)

    if not groups:
        print("  No snapshot data found. Run dex_collector.py first.")
        return

    # Compute baselines
    baselines = compute_baselines(groups)

    # Write baselines
    baseline_path = LOGS / "baseline_spread_latest.json"
    baseline_out = {
        "timestamp": ts,
        "window_days": BASELINE_DAYS,
        "baselines": {k: round(v, 4) for k, v in baselines.items()},
    }
    with open(baseline_path, "w") as f:
        json.dump(baseline_out, f, indent=2)

    # Score each venue/pair
    scores = {}
    for venue, pair, key in VENUE_PAIRS:
        entries = groups.get(key, [])
        if not entries:
            print(f"  ⚠ {key}: no data")
            continue

        window_stats = aggregate_window(entries)
        if window_stats is None:
            print(f"  ⚠ {key}: insufficient window data")
            continue

        baseline = baselines.get(key, 1.0)
        tox = compute_toxicity_score(window_stats, baseline)

        score_entry = {
            "timestamp": ts,
            "venue": venue,
            "pair": pair,
            "toxicity_score": tox["toxicity_score"],
            "toxicity_band": tox["toxicity_band"],
            "components": tox["components"],
            "inputs": {
                **window_stats,
                "baseline_spread": round(baseline, 4),
            },
        }
        scores[key] = score_entry
        print(f"  {key}: score={tox['toxicity_score']:.1f} band={tox['toxicity_band']} "
              f"[sp={tox['components']['spread_score']:.1f} th={tox['components']['thin_score']:.1f} "
              f"im={tox['components']['imbalance_score']:.1f} qi={tox['components']['instab_score']:.1f}]")

    # ── Write latest snapshot ─────────────────────────────────────
    latest = {
        "timestamp": ts,
        "venue_pair_count": len(scores),
        "scores": scores,
    }
    latest_path = LOGS / "dex_toxicity_latest.json"
    with open(latest_path, "w") as f:
        json.dump(latest, f, indent=2)

    # ── Append to daily timeseries ────────────────────────────────
    ts_path = LOGS / f"dex_toxicity_{today_str}.jsonl"
    for key, score_entry in scores.items():
        with open(ts_path, "a") as f:
            f.write(json.dumps(score_entry) + "\n")

    print(f"[{ts}] dex_aggregator done: {len(scores)}/4 scored")
    print(f"  Latest : {latest_path}")
    print(f"  Series : {ts_path}")
    print(f"  Baseline: {baseline_path}")


if __name__ == "__main__":
    main()
