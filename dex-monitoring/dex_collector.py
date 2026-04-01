#!/usr/bin/env python3
"""
dex_collector.py — DEX CLOB L2 book snapshot collector

Fetches top-of-book L2 data from Hyperliquid and dYdX for BTC-PERP and ETH-PERP.
Computes raw features per snapshot. Writes per-venue/pair JSON files + daily JSONL.

Run every 5 minutes via cron:
  */5 * * * * cd <your-project-dir> && python3 dex_collector.py >> logs/dex/collector.log 2>&1

No API keys required. No external dependencies beyond requests.
"""

import json
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

import requests

# ── Config ────────────────────────────────────────────────────────────
CFG = json.loads(Path("config_dex.json").read_text())
LOGS = Path("logs/dex")
LOGS.mkdir(parents=True, exist_ok=True)

TOP_LEVELS = CFG["collection"]["top_levels"]
NEAR_TOUCH = CFG["collection"]["near_touch_levels"]
REQ_DELAY  = CFG["collection"]["request_delay_seconds"]
TIMEOUT    = 10  # seconds


# ── API Fetchers ──────────────────────────────────────────────────────

def fetch_hyperliquid(coin: str) -> dict:
    """Fetch L2 book from Hyperliquid. Returns {bids, asks, source_ts_ms}.
    source_ts_ms: native Unix millisecond timestamp from Hyperliquid 'time' field.
    """
    url = CFG["venues"]["hyperliquid"]["api_url"]
    resp = requests.post(url, json={"type": "l2Book", "coin": coin}, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    levels = data.get("levels", [[], []])
    bids = [{"px": float(e["px"]), "sz": float(e["sz"])} for e in levels[0][:TOP_LEVELS]]
    asks = [{"px": float(e["px"]), "sz": float(e["sz"])} for e in levels[1][:TOP_LEVELS]]
    # HL provides native 'time' in Unix ms — capture for freshness tracking
    source_ts_ms = data.get("time")  # integer or None
    return {"bids": bids, "asks": asks, "source_ts_ms": source_ts_ms}


def fetch_dydx(symbol: str) -> dict:
    """Fetch L2 book from dYdX v4. Returns {bids, asks, source_ts_ms}.
    source_ts_ms: None — dYdX v4 orderbook endpoint does not expose a native timestamp.
    Local collection time is used for all freshness calculations on this venue.
    """
    base = CFG["venues"]["dydx"]["api_url"]
    url = f"{base}/{symbol}"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    bids = [{"px": float(e["price"]), "sz": float(e["size"])} for e in data.get("bids", [])[:TOP_LEVELS]]
    asks = [{"px": float(e["price"]), "sz": float(e["size"])} for e in data.get("asks", [])[:TOP_LEVELS]]
    return {"bids": bids, "asks": asks, "source_ts_ms": None}


# ── Feature Computation ──────────────────────────────────────────────

def compute_features(book: dict) -> dict:
    """Compute raw features from L2 book snapshot."""
    bids = book["bids"]
    asks = book["asks"]

    if not bids or not asks:
        return {"error": "empty_book"}

    best_bid = bids[0]["px"]
    best_ask = asks[0]["px"]
    mid = (best_bid + best_ask) / 2.0

    if mid == 0:
        return {"error": "zero_mid"}

    eff_spread_bps = (best_ask - best_bid) / mid * 10000

    # Top-of-book depth (USD)
    top_depth_bid = best_bid * bids[0]["sz"]
    top_depth_ask = best_ask * asks[0]["sz"]

    # Near-touch depth: sum of top N levels (USD)
    near_touch_bid = sum(b["px"] * b["sz"] for b in bids[:NEAR_TOUCH])
    near_touch_ask = sum(a["px"] * a["sz"] for a in asks[:NEAR_TOUCH])

    # Full captured depth (all fetched levels)
    full_depth_bid = sum(b["px"] * b["sz"] for b in bids)
    full_depth_ask = sum(a["px"] * a["sz"] for a in asks)

    # Depth ratio and imbalance
    total_near = near_touch_bid + near_touch_ask
    depth_ratio = near_touch_bid / near_touch_ask if near_touch_ask > 0 else None
    depth_imbalance = (near_touch_bid - near_touch_ask) / total_near if total_near > 0 else 0.0

    return {
        "mid_price": round(mid, 2),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "eff_spread_bps": round(eff_spread_bps, 4),
        "top_depth_bid_usd": round(top_depth_bid, 2),
        "top_depth_ask_usd": round(top_depth_ask, 2),
        "near_touch_bid_usd": round(near_touch_bid, 2),
        "near_touch_ask_usd": round(near_touch_ask, 2),
        "full_depth_bid_usd": round(full_depth_bid, 2),
        "full_depth_ask_usd": round(full_depth_ask, 2),
        "depth_ratio": round(depth_ratio, 6) if depth_ratio is not None else None,
        "depth_imbalance": round(depth_imbalance, 6),
    }


def compute_delta_features(current: dict, prior: Optional[dict]) -> dict:
    """Compute delta features vs prior snapshot. Returns empty dict if no prior."""
    if prior is None or "error" in current or "error" in (prior or {}):
        return {
            "spread_change_5m_bps": None,
            "book_thinning_5m_pct": None,
            "quote_instability": None,
        }

    spread_change = current["eff_spread_bps"] - prior.get("eff_spread_bps", current["eff_spread_bps"])

    prior_near_bid = prior.get("near_touch_bid_usd", 0)
    if prior_near_bid > 0:
        book_thinning = (current["near_touch_bid_usd"] - prior_near_bid) / prior_near_bid * 100
    else:
        book_thinning = None

    # Quote instability: count bid price level changes in top 3
    prior_bid_prices = prior.get("_bid_prices_top3", [])
    current_bid_prices = current.get("_bid_prices_top3", [])
    if prior_bid_prices and current_bid_prices:
        changes = sum(1 for a, b in zip(current_bid_prices, prior_bid_prices) if a != b)
        # Also count if lengths differ
        changes += abs(len(current_bid_prices) - len(prior_bid_prices))
    else:
        changes = None

    return {
        "spread_change_5m_bps": round(spread_change, 4) if spread_change is not None else None,
        "book_thinning_5m_pct": round(book_thinning, 4) if book_thinning is not None else None,
        "quote_instability": changes,
    }


# ── Prior Snapshot Loading ────────────────────────────────────────────

def load_prior_features(venue_prefix: str, pair_label: str, today_str: str) -> Optional[dict]:
    """Load most recent prior snapshot features for delta computation."""
    jsonl_path = LOGS / f"dex_snapshots_{today_str}.jsonl"
    if not jsonl_path.exists():
        return None

    last_match = None
    target_key = f"{venue_prefix}_{pair_label}"
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("venue_pair") == target_key:
                    last_match = entry.get("features")
            except json.JSONDecodeError:
                continue
    return last_match


# ── Snapshot Writer ───────────────────────────────────────────────────

def write_snapshot(venue: str, pair: str, prefix: str, book: dict, features: dict,
                   delta: dict, ts: str, today_str: str, hhmm: str,
                   source_ts_ms: Optional[int] = None):
    """Write individual snapshot JSON + append to daily JSONL.
    source_ts_ms: venue-native timestamp in Unix ms (HL only). None for dYdX.
    """
    pair_label = pair.lower().replace("-", "")

    # Compute freshness delta if source timestamp available
    freshness_delta_s = None
    if source_ts_ms is not None:
        try:
            local_epoch_s = datetime.fromisoformat(ts).timestamp()
            freshness_delta_s = round(local_epoch_s - source_ts_ms / 1000.0, 3)
        except Exception:
            pass

    # Individual snapshot file
    snap = {
        "timestamp": ts,
        "venue": venue,
        "pair": pair,
        "source_ts_ms": source_ts_ms,
        "freshness_delta_s": freshness_delta_s,
        "features": {**features, **delta},
        "raw_book": {
            "bids": book["bids"][:NEAR_TOUCH],  # store only top 3 for reference
            "asks": book["asks"][:NEAR_TOUCH],
        },
    }
    snap_file = LOGS / f"{prefix}_{pair_label}_{today_str}_{hhmm}.json"
    with open(snap_file, "w") as f:
        json.dump(snap, f, indent=2)

    # Append to daily JSONL (for aggregator + monitor)
    jsonl_path = LOGS / f"dex_snapshots_{today_str}.jsonl"
    entry = {
        "timestamp": ts,
        "venue_pair": f"{prefix}_{pair_label}",
        "venue": venue,
        "pair": pair,
        "source_ts_ms": source_ts_ms,
        "freshness_delta_s": freshness_delta_s,
        "features": {
            **features,
            **delta,
            # Store bid prices for quote instability in next run
            "_bid_prices_top3": [b["px"] for b in book["bids"][:NEAR_TOUCH]],
        },
    }
    with open(jsonl_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    today_str = now.strftime("%Y%m%d")
    hhmm = now.strftime("%H%M")

    print(f"[{ts}] dex_collector run start")

    results = []
    errors = []

    # ── Hyperliquid ───────────────────────────────────────────────
    hl_cfg = CFG["venues"]["hyperliquid"]
    for pair_name, pair_params in hl_cfg["pairs"].items():
        try:
            book = fetch_hyperliquid(pair_params["coin"])
            source_ts_ms = book.pop("source_ts_ms", None)  # extract before feature compute
            features = compute_features(book)

            if "error" not in features:
                # Attach top3 bid prices for instability tracking
                features["_bid_prices_top3"] = [b["px"] for b in book["bids"][:NEAR_TOUCH]]

            prior = load_prior_features(hl_cfg["prefix"], pair_name.lower().replace("-", ""), today_str)
            delta = compute_delta_features(features, prior)

            # Remove internal field before writing snapshot
            feat_clean = {k: v for k, v in features.items() if not k.startswith("_")}
            write_snapshot("hyperliquid", pair_name, hl_cfg["prefix"], book,
                           feat_clean, delta, ts, today_str, hhmm, source_ts_ms=source_ts_ms)
            results.append(f"  ✓ HL {pair_name}: spread={features.get('eff_spread_bps','?')}bps mid={features.get('mid_price','?')}")
        except Exception as e:
            errors.append(f"  ✗ HL {pair_name}: {e}")

        time.sleep(REQ_DELAY)

    # ── dYdX ──────────────────────────────────────────────────────
    dx_cfg = CFG["venues"]["dydx"]
    for pair_name, pair_params in dx_cfg["pairs"].items():
        try:
            book = fetch_dydx(pair_params["symbol"])
            book.pop("source_ts_ms", None)  # dYdX always None — discard cleanly
            features = compute_features(book)

            if "error" not in features:
                features["_bid_prices_top3"] = [b["px"] for b in book["bids"][:NEAR_TOUCH]]

            prior = load_prior_features(dx_cfg["prefix"], pair_name.lower().replace("-", ""), today_str)
            delta = compute_delta_features(features, prior)

            feat_clean = {k: v for k, v in features.items() if not k.startswith("_")}
            write_snapshot("dydx", pair_name, dx_cfg["prefix"], book,
                           feat_clean, delta, ts, today_str, hhmm, source_ts_ms=None)
            results.append(f"  ✓ DX {pair_name}: spread={features.get('eff_spread_bps','?')}bps mid={features.get('mid_price','?')}")
        except Exception as e:
            errors.append(f"  ✗ DX {pair_name}: {e}")

        time.sleep(REQ_DELAY)

    # ── Summary ───────────────────────────────────────────────────
    for r in results:
        print(r)
    for e in errors:
        print(e, file=sys.stderr)

    ok = len(results)
    fail = len(errors)
    print(f"[{ts}] dex_collector done: {ok}/4 ok, {fail}/4 failed")

    if fail == 4:
        sys.exit(1)


if __name__ == "__main__":
    main()
