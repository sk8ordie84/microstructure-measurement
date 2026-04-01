"""
validate.py — Binary Signal Calibration Framework
===================================================

Reads a scored ledger (logs/actionable_ledger.json) and analyzes resolved
entries to measure whether a scoring system separates outcomes by tier.

This is NOT a signal generator. It measures:
  - Whether priority tiers (A/B/C) separate outcomes
  - Whether scoring calibration improves over time
  - Which scoring inputs carry predictive value

Three analysis layers:
  OBSERVATION-LEVEL — every ledger entry is an independent sample
  MARKET-LEVEL     — grouped by slug, one representative per unique market
  EVENT-LEVEL      — grouped by event_title, one representative per event
                     Collapses complement binary markets under the same event.

NOTE on event-level:
  Event grouping uses lightly normalized event_title (trim, lowercase, collapse
  whitespace).  It does NOT detect semantically related events with different titles.

Run after filling `outcome` fields in the ledger:
  "outcome": "YES"   — YES token resolved to $1.00
  "outcome": "NO"    — NO token resolved, YES went to $0.00
  "outcome": "VOID"  — Market cancelled/unresolved (excluded from analysis)

Usage:
  python3 validate.py

Output:
  Terminal report
  logs/validation_report_latest.json
  logs/validation_report_YYYYMMDD_HHMMSS.json

Confidence thresholds:
  < 10 resolved  → EARLY STAGE: print summary only, skip section analysis
  10-29 resolved → CAUTION: all sections shown with warning
  >= 30 resolved → Full analysis

KEY METRIC — Calibration gap:
  actual_YES_rate − avg_yes_price_at_scan
  > 0  →  YES happened more than the price implied  (scanner found underpriced YES)
  < 0  →  YES happened less than the price implied  (scanner found overpriced YES)
  ≈ 0  →  Well-calibrated, scanner follows market pricing
  This is the most honest long-term signal for scanner quality.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

LOGS_DIR    = Path("logs")
LEDGER_FILE = LOGS_DIR / "actionable_ledger.json"

MIN_SAMPLE_WARN = 10   # below: skip section analysis, just print summary
MIN_SAMPLE_CONF = 30   # below: add caution note to every section

W = 62   # terminal width

# ── Helpers ────────────────────────────────────────────────────────────────────────────
def _yes_rate(subset):
    if not subset:
        return 0, 0, None
    n_yes = sum(1 for e in subset if e.get("outcome") == "YES")
    return n_yes, len(subset), n_yes / len(subset)

def _avg(subset, field):
    vals = [e.get(field) for e in subset if e.get(field) is not None]
    return sum(vals) / len(vals) if vals else None

def _pct(rate):
    return f"{rate:.1%}" if rate is not None else "n/a"

def _fmt(n_yes, n_tot, rate):
    if rate is None:
        return "n/a"
    return f"{n_yes}/{n_tot} YES ({rate:.1%})"

def _beat_market(subset):
    n_yes, n_tot, rate = _yes_rate(subset)
    avg_p = _avg(subset, "yes_price")
    if rate is None or avg_p is None:
        return None
    return rate - avg_p

def _caution(n):
    if n < 5:
        return "  [!! n too small]"
    if n < 10:
        return "  [! small sample]"
    return ""

def _section(title):
    print(f"\n{'─'*W}")
    print(f" {title}")
    print(f"{'─'*W}")

def _status(current, threshold, label):
    mark = "OK" if current >= threshold else f"need +{threshold - current}"
    print(f"  {label:<40} {current:>4} / {threshold}  [{mark}]")


# ── Market-level grouping ────────────────────────────────────────────────────────────

def _entry_resolve_key(e):
    """Sort key for choosing the best representative within a market group.
    Priority: outcome_ts > scan_time > scan_date.  Returns a comparable tuple."""
    return (
        e.get("outcome_ts") or "",
        e.get("scan_time")  or "",
        e.get("scan_date")  or "",
    )


def _group_by_market(entries):
    """Group entries by market identity (observation_group_id → slug fallback).
    Returns dict: group_key → list[entry], each list sorted by scan_date asc."""
    groups = defaultdict(list)
    for e in entries:
        key = e.get("observation_group_id") or e.get("slug") or "unknown"
        groups[key].append(e)
    for k in groups:
        groups[k].sort(key=lambda e: e.get("scan_date", ""))
    return dict(groups)


def _market_level_resolved(groups):
    """One representative per market for resolved markets.
    Picks the entry with highest _entry_resolve_key among resolved entries in group."""
    reps = []
    for _key, entries in groups.items():
        resolved = [e for e in entries if e.get("outcome") in ("YES", "NO")]
        if not resolved:
            continue
        # Best representative: highest (outcome_ts, scan_time, scan_date)
        rep = max(resolved, key=_entry_resolve_key)
        reps.append(rep)
    return reps


def _build_observation_summary(all_groups, n_total):
    """Build the observation_summary dict for JSON output."""
    n_unique    = len(all_groups)
    n_repeated  = sum(1 for g in all_groups.values() if len(g) >= 2)
    n_single    = sum(1 for g in all_groups.values() if len(g) == 1)
    avg_obs     = round(n_total / n_unique, 4) if n_unique else 0
    max_obs     = max((len(g) for g in all_groups.values()), default=0)
    return {
        "total_observations":             n_total,
        "unique_markets":                 n_unique,
        "repeated_markets":               n_repeated,
        "single_observation_markets":     n_single,
        "avg_observations_per_market":    avg_obs,
        "max_observations_single_market": max_obs,
    }


def _build_repeated_markets_list(all_groups):
    """List of repeated markets for JSON output, sorted by count desc."""
    result = []
    for key, entries in sorted(all_groups.items(), key=lambda x: -len(x[1])):
        if len(entries) < 2:
            continue
        first_seen = min(
            (e.get("first_seen_date") or e.get("scan_date") or "" for e in entries),
            default=""
        )
        latest_scan = max(
            (e.get("scan_date") or "" for e in entries),
            default=""
        )
        has_resolved = any(e.get("outcome") in ("YES", "NO") for e in entries)
        result.append({
            "slug":              key,
            "question":          entries[0].get("question", ""),
            "observation_count": len(entries),
            "first_seen":        first_seen or None,
            "latest_scan":       latest_scan or None,
            "resolved":          has_resolved,
        })
    return result


def _build_market_summary(market_resolved, early_stage):
    """Build market_summary dict (deduped metrics) for JSON output."""
    mkt_n_yes, mkt_n_tot, mkt_rate = _yes_rate(market_resolved)
    mkt_avg_price = _avg(market_resolved, "yes_price")
    mkt_avg_score = _avg(market_resolved, "daily_score")
    mkt_cal_gap   = _beat_market(market_resolved)

    summary = {
        "unique_resolved":  mkt_n_tot,
        "n_yes":            mkt_n_yes,
        "n_no":             mkt_n_tot - mkt_n_yes,
        "yes_rate":         round(mkt_rate, 4) if mkt_rate is not None else None,
        "avg_yes_price":    round(mkt_avg_price, 4) if mkt_avg_price is not None else None,
        "avg_score":        round(mkt_avg_score, 4) if mkt_avg_score is not None else None,
        "calibration_gap":  round(mkt_cal_gap, 4)   if mkt_cal_gap   is not None else None,
        "note": (
            "Market-level: one representative per slug/group. "
            "Deduplicates repeated observations but does NOT collapse "
            "complementary markets within the same event."
        ),
        "by_tier":   {},
        "by_bucket": {},
    }

    if not early_stage:
        for tier in ("A_TIER", "B_TIER", "C_TIER"):
            sub = [e for e in market_resolved if e.get("priority_tier") == tier]
            n_y, n_t, r = _yes_rate(sub)
            bm    = _beat_market(sub)
            avg_p = _avg(sub, "yes_price")
            summary["by_tier"][tier] = {
                "n_resolved":    n_t,
                "n_yes":         n_y,
                "yes_rate":      round(r, 4)    if r    is not None else None,
                "avg_yes_price": round(avg_p, 4) if avg_p is not None else None,
                "beat_market":   round(bm, 4)    if bm    is not None else None,
            }
        for bkt in ("today", "week", "twoweek"):
            sub = [e for e in market_resolved if e.get("bucket") == bkt]
            n_y, n_t, r = _yes_rate(sub)
            avg_s = _avg(sub, "daily_score")
            summary["by_bucket"][bkt] = {
                "n_resolved": n_t,
                "n_yes":      n_y,
                "yes_rate":   round(r, 4) if r    is not None else None,
                "avg_score":  round(avg_s, 4) if avg_s is not None else None,
            }

    return summary


# ── Event-level grouping (complement-aware) ───────────────────────────────

def _normalize_event_key(event_title):
    """Lightly normalize event_title for grouping.
    Trim, lowercase, collapse whitespace.  Raw event_title preserved in output."""
    if not event_title:
        return "unknown"
    import re
    return re.sub(r"\s+", " ", event_title.strip().lower())


def _group_by_event(entries):
    """Group entries by normalized event_title.
    Returns dict: event_key → list[entry], sorted by scan_date asc."""
    groups = defaultdict(list)
    for e in entries:
        key = _normalize_event_key(e.get("event_title"))
        groups[key].append(e)
    for k in groups:
        groups[k].sort(key=lambda e: e.get("scan_date", ""))
    return dict(groups)


def _event_level_resolved(event_groups):
    """One representative per event for resolved events.
    An event is resolved when at least one slug has outcome YES or NO.
    Representative priority: YES winner > latest resolved by _entry_resolve_key.
    Returns list of (representative_entry, reason) tuples."""
    reps = []
    for _key, entries in event_groups.items():
        resolved = [e for e in entries if e.get("outcome") in ("YES", "NO")]
        if not resolved:
            continue
        yes_winners = [e for e in resolved if e.get("outcome") == "YES"]
        if yes_winners:
            rep = max(yes_winners, key=_entry_resolve_key)
            reps.append((rep, "yes_winner"))
        else:
            rep = max(resolved, key=_entry_resolve_key)
            reps.append((rep, "all_no_fallback"))
    return reps


def _build_event_summary(event_resolved_pairs, event_groups):
    """Build event_summary dict for JSON output."""
    n_events = len(event_groups)
    slugs_per_event = {}
    for _key, entries in event_groups.items():
        slugs_per_event[_key] = set(e.get("slug") or "" for e in entries)
    complement_events = sum(1 for s in slugs_per_event.values() if len(s) >= 2)
    single_events = sum(1 for s in slugs_per_event.values() if len(s) == 1)
    all_slug_counts = [len(s) for s in slugs_per_event.values()]
    avg_mkts = round(sum(all_slug_counts) / len(all_slug_counts), 2) if all_slug_counts else 0
    max_mkts = max(all_slug_counts, default=0)

    reps_only = [r for r, _ in event_resolved_pairs]
    n_yes = sum(1 for r in reps_only if r.get("outcome") == "YES")
    n_resolved = len(reps_only)
    yes_rate = round(n_yes / n_resolved, 4) if n_resolved else None
    avg_price = _avg(reps_only, "yes_price")
    cal_gap = _beat_market(reps_only)
    n_all_no = sum(1 for _, reason in event_resolved_pairs if reason == "all_no_fallback")

    return {
        "unique_events":          n_events,
        "complement_events":      complement_events,
        "single_market_events":   single_events,
        "avg_markets_per_event":  avg_mkts,
        "max_markets_in_event":   max_mkts,
        "unique_events_resolved": n_resolved,
        "n_yes":                  n_yes,
        "n_no":                   n_resolved - n_yes,
        "yes_rate":               yes_rate,
        "avg_yes_price":          round(avg_price, 4) if avg_price is not None else None,
        "calibration_gap":        round(cal_gap, 4) if cal_gap is not None else None,
        "all_no_events":          n_all_no,
        "note": (
            "Event-level: one representative per normalized event_title. "
            "Picks YES winner when available; falls back to latest resolved "
            "when all slugs in an event resolved NO (winner not in ledger). "
            "Does NOT detect semantically related events with different titles."
        ),
    }


def _build_event_groups_list(event_groups, event_resolved_pairs):
    """List of event groups for JSON output, sorted by slug count desc."""
    resolved_lookup = {}
    for rep, reason in event_resolved_pairs:
        key = _normalize_event_key(rep.get("event_title"))
        resolved_lookup[key] = (rep, reason)

    result = []
    for key, entries in sorted(event_groups.items(),
                               key=lambda x: -len(set(e.get("slug", "") for e in x[1]))):
        slugs = sorted(set(e.get("slug", "") for e in entries))
        raw_title = entries[0].get("event_title", "")
        obs_count = len(entries)
        is_complement = len(slugs) >= 2
        resolved_pair = resolved_lookup.get(key)
        is_resolved = resolved_pair is not None
        rep_slug = resolved_pair[0].get("slug") if resolved_pair else None
        rep_outcome = resolved_pair[0].get("outcome") if resolved_pair else None
        rep_reason = resolved_pair[1] if resolved_pair else None

        result.append({
            "event_title":            raw_title,
            "event_key":              key,
            "slugs":                  slugs,
            "slug_count":             len(slugs),
            "observation_count":      obs_count,
            "is_complement":          is_complement,
            "resolved":               is_resolved,
            "representative_slug":    rep_slug,
            "representative_outcome": rep_outcome,
            "has_yes_winner":         rep_reason == "yes_winner" if rep_reason else None,
            "representative_reason":  rep_reason,
        })
    return result


def _print_obs_vs_market(obs_summary, obs_rate_info, mkt_rate_info, market_resolved,
                         event_summary=None, event_resolved_pairs=None):
    """Print the observation vs market vs event-level comparison block."""
    n_unique   = obs_summary["unique_markets"]
    n_total    = obs_summary["total_observations"]
    n_repeated = obs_summary["repeated_markets"]
    n_single   = obs_summary["single_observation_markets"]
    avg_obs    = obs_summary["avg_observations_per_market"]
    max_obs    = obs_summary["max_observations_single_market"]

    print(f"  Total observations     : {n_total}")
    print(f"  Unique markets         : {n_unique}")
    if n_unique > 0:
        pct_rep = n_repeated / n_unique * 100
        pct_sin = n_single   / n_unique * 100
        print(f"  Repeated markets       : {n_repeated}  ({pct_rep:.1f}%)")
        print(f"  Single-obs markets     : {n_single}  ({pct_sin:.1f}%)")
    else:
        print(f"  Repeated markets       : {n_repeated}")
        print(f"  Single-obs markets     : {n_single}")
    print(f"  Avg obs per market     : {avg_obs:.2f}")
    print(f"  Max obs on one market  : {max_obs}")

    # Event coverage
    if event_summary:
        es = event_summary
        print()
        print(f"  Unique events          : {es['unique_events']}")
        print(f"  Complement events      : {es['complement_events']}  "
              f"({es['complement_events']/es['unique_events']*100:.0f}%)" if es['unique_events'] > 0 else "")
        print(f"  Single-market events   : {es['single_market_events']}")
        print(f"  Avg markets per event  : {es['avg_markets_per_event']:.2f}")
        print(f"  Max markets in event   : {es['max_markets_in_event']}")

    if obs_rate_info is not None and mkt_rate_info is not None:
        obs_ny, obs_nt, obs_r, obs_cg = obs_rate_info
        mkt_ny, mkt_nt, mkt_r, mkt_cg = mkt_rate_info
        print()
        print(f"  --- Observation-level (current) ---")
        print(f"  Resolved observations  : {obs_nt}")
        print(f"  YES rate               : {_pct(obs_r)}")
        cg_s = f"{obs_cg:+.4f}" if obs_cg is not None else "n/a"
        print(f"  Calibration gap        : {cg_s}")
        print()
        print(f"  --- Market-level (deduped) ---")
        print(f"  Resolved unique markets: {mkt_nt}")
        print(f"  YES rate               : {_pct(mkt_r)}")
        mkt_cg_s = f"{mkt_cg:+.4f}" if mkt_cg is not None else "n/a"
        print(f"  Calibration gap        : {mkt_cg_s}")

        # Event-level
        if event_summary and event_summary.get("unique_events_resolved", 0) > 0:
            es = event_summary
            print()
            print(f"  --- Event-level (complement-aware) ---")
            print(f"  Resolved unique events : {es['unique_events_resolved']}")
            print(f"  YES rate               : {_pct(es['yes_rate'])}")
            evt_cg_s = f"{es['calibration_gap']:+.4f}" if es.get('calibration_gap') is not None else "n/a"
            print(f"  Calibration gap        : {evt_cg_s}")
            if es.get("all_no_events", 0) > 0:
                print(f"  All-NO events          : {es['all_no_events']}  (winner not in ledger)")
    elif len(market_resolved) == 0:
        print()
        print("  No resolved entries yet — metrics will appear after outcomes are filled.")

    print()
    print("  NOTE: Market-level deduplicates by slug. Event-level collapses complement")
    print("  markets under the same event_title (e.g. Paxton/Cornyn → one event).")
    print("  Does NOT detect semantically related events with different titles.")


# ── Main ─────────────────────────────────────────────────────────────────────────────

def main():
    now_utc    = datetime.now(timezone.utc)
    current_ts = now_utc.isoformat()

    # ── Load ledger ─────────────────────────────────────────────────────────────
    if not LEDGER_FILE.exists():
        print("No ledger found at logs/actionable_ledger.json")
        print("Run daily_scanner.py first to create the ledger.")
        sys.exit(0)

    with LEDGER_FILE.open("r", encoding="utf-8") as f:
        ledger = json.load(f)

    entries  = ledger.get("entries", [])
    resolved = [e for e in entries if e.get("outcome") in ("YES", "NO")]
    void_e   = [e for e in entries if e.get("outcome") == "VOID"]
    pending  = [e for e in entries if e.get("outcome") is None]

    n_total    = len(entries)
    n_resolved = len(resolved)
    n_void     = len(void_e)
    n_pending  = len(pending)

    # ── Market-level grouping (always computed) ─────────────────────────────
    all_groups      = _group_by_market(entries)
    obs_summary     = _build_observation_summary(all_groups, n_total)
    market_resolved = _market_level_resolved(all_groups)
    repeated_list   = _build_repeated_markets_list(all_groups)

    # ── Event-level grouping (always computed) ───────────────────────────────
    event_groups         = _group_by_event(entries)
    event_resolved_pairs = _event_level_resolved(event_groups)
    event_summary        = _build_event_summary(event_resolved_pairs, event_groups)
    event_groups_list    = _build_event_groups_list(event_groups, event_resolved_pairs)

    # ── Header ────────────────────────────────────────────────────────────────────
    print("=" * W)
    print("  VALIDATION REPORT")
    print(f"  {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * W)
    print(f"\n  Ledger: {n_total} total  |  {n_resolved} resolved  "
          f"|  {n_void} void  |  {n_pending} pending")

    # ── Early stage gate ────────────────────────────────────────────────────────
    early_stage = n_resolved < MIN_SAMPLE_WARN
    caution     = MIN_SAMPLE_WARN <= n_resolved < MIN_SAMPLE_CONF

    if n_resolved == 0:
        print("\n  No resolved entries yet.")
        print("  Fill 'outcome' fields in logs/actionable_ledger.json after markets resolve.")
        print('  Format:  "outcome": "YES"  or  "NO"  or  "VOID"')
        if n_pending:
            print(f"\n  Pending entries ({n_pending}):")
            for e in sorted(pending, key=lambda x: x.get("scan_date", ""))[:10]:
                end = e.get("end_date", "?")[:10] if e.get("end_date") else "?"
                print(f"    [{e.get('priority_tier','?'):<6}] {e.get('scan_date','')}  "
                      f"resolves~{end}  {e.get('question','')[:50]}")
            if len(pending) > 10:
                print(f"    ... and {len(pending)-10} more")

        # Even with 0 resolved, emit observation_summary + market_summary
        market_summary = _build_market_summary(market_resolved, early_stage=True)

        report = {
            "timestamp":  current_ts,
            "status":     "no_resolved_data",
            "n_total":    n_total,
            "n_resolved": 0,
            "n_void":     n_void,
            "n_pending":  n_pending,
            "observation_summary": obs_summary,
            "market_summary":      market_summary,
            "repeated_markets":    repeated_list,
            "event_summary":       event_summary,
            "event_groups":        event_groups_list,
        }

        # Print observation coverage even when 0 resolved
        _section("OBSERVATION vs MARKET vs EVENT SUMMARY")
        _print_obs_vs_market(obs_summary, None, None, market_resolved,
                             event_summary, event_resolved_pairs)

        _ts = now_utc.strftime("%Y%m%d_%H%M%S")
        for fp in [LOGS_DIR / f"validation_report_{_ts}.json",
                   LOGS_DIR / "validation_report_latest.json"]:
            with fp.open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        print(f"\n  Saved: logs/validation_report_{_ts}.json")
        print(f"  Saved: logs/validation_report_latest.json")
        sys.exit(0)

    if early_stage:
        print(f"\n  !! EARLY STAGE — {n_resolved} resolved entries (need >= {MIN_SAMPLE_WARN})")
        print(f"     Section analysis skipped. Numbers below are directional only.")
        print(f"     Do not draw conclusions. Run again after more markets resolve.")
    elif caution:
        print(f"\n  ! CAUTION — {n_resolved} resolved ({MIN_SAMPLE_WARN}–{MIN_SAMPLE_CONF} range).")
        print(f"    All metrics are directional. Confident analysis needs >= {MIN_SAMPLE_CONF} resolved.")

    # ── Section 1: Overall (Observation-level) ───────────────────────────────────────
    _section("OBSERVATION-LEVEL: OVERALL")
    n_yes_all, n_tot_all, rate_all = _yes_rate(resolved)
    avg_price_all = _avg(resolved, "yes_price")
    avg_score_all = _avg(resolved, "daily_score")
    cal_gap       = _beat_market(resolved)

    print(f"  Resolved entries : {n_resolved}")
    print(f"  YES outcomes     : {n_yes_all}  ({_pct(rate_all)})")
    print(f"  NO  outcomes     : {n_tot_all - n_yes_all}  ({_pct(1 - rate_all if rate_all is not None else None)})")
    if avg_price_all is not None:
        print(f"  Avg scan price   : {avg_price_all:.3f}  (YES was priced this high at scan)")
    if avg_score_all is not None:
        print(f"  Avg daily_score  : {avg_score_all:.3f}")
    if cal_gap is not None:
        direction = "underpriced YES (more YES than expected)" if cal_gap > 0 else "overpriced YES (less YES than expected)"
        arrow = "+" if cal_gap >= 0 else ""
        print(f"  Calibration gap  : {arrow}{cal_gap:.3f}  ← {direction}")
        print(f"  [gap = actual_YES_rate − avg_yes_price. Target: near 0.00]")

    if early_stage:
        _section("PENDING ENTRIES")
        for e in sorted(pending, key=lambda x: (x.get("bucket",""), x.get("scan_date","")))[:15]:
            end = e.get("end_date", "?")[:10] if e.get("end_date") else "?"
            print(f"  [{e.get('priority_tier','?'):<6}] {e.get('scan_date','')}  "
                  f"resolves~{end}  p={e.get('yes_price',0):.3f}  "
                  f"{e.get('question','')[:48]}")
        if len(pending) > 15:
            print(f"  ... and {len(pending)-15} more pending")
    else:
        # ── Section 2: By tier ────────────────────────────────────────────────────────────
        _section("BY PRIORITY TIER" + (" [! caution: small samples]" if caution else ""))
        print(f"  {'Tier':<8} {'Resolved':>8} {'YES rate':>10} {'avg_price':>10} "
              f"{'beat_mkt':>10} {'note'}")
        print(f"  {'─'*8} {'─'*8} {'─'*10} {'─'*10} {'─'*10} {'─'*6}")

        for tier in ("A_TIER", "B_TIER", "C_TIER"):
            sub  = [e for e in resolved if e.get("priority_tier") == tier]
            sub_all = [e for e in entries if e.get("priority_tier") == tier]
            n_y, n_t, r = _yes_rate(sub)
            avg_p = _avg(sub, "yes_price")
            bm    = _beat_market(sub)
            caution_note = _caution(n_t)
            bm_str  = f"{bm:+.3f}" if bm is not None else "n/a"
            rate_s  = _fmt(n_y, n_t, r)
            avg_p_s = f"{avg_p:.3f}" if avg_p else "n/a"
            print(f"  {tier:<8} {n_t:>8}   {rate_s:<16} {avg_p_s:>8}   {bm_str:>8}  {caution_note}")
        print()
        print("  beat_market = actual_YES_rate − avg_yes_price")
        print("  Positive: market underpriced YES. Negative: market overpriced YES.")

        # ── Section 3: By bucket ────────────────────────────────────────────────────────
        _section("BY TIME BUCKET" + (" [! caution]" if caution else ""))
        print(f"  {'Bucket':<10} {'Resolved':>8} {'YES rate':>14} {'avg_score':>10}")
        print(f"  {'─'*10} {'─'*8} {'─'*14} {'─'*10}")
        for bkt in ("today", "week", "twoweek"):
            sub  = [e for e in resolved if e.get("bucket") == bkt]
            n_y, n_t, r = _yes_rate(sub)
            avg_s = _avg(sub, "daily_score")
            caution_note = _caution(n_t)
            avg_s_str = f"{avg_s:.3f}" if avg_s is not None else "n/a"
            print(f"  {bkt.upper():<10} {n_t:>8}   {_fmt(n_y, n_t, r):<20} "
                  f"{avg_s_str}{caution_note}")

        # ── Section 4: Depth imbalance signal ─────────────────────────────────────────
        _section("DEPTH IMBALANCE SIGNAL" + (" [! caution]" if caution else ""))
        sub_flag  = [e for e in resolved if (e.get("scan_imbalance") or 0) >= 0.60]
        sub_ok    = [e for e in resolved if e.get("scan_imbalance") is not None
                     and (e.get("scan_imbalance") or 0) < 0.60]
        sub_none  = [e for e in resolved if e.get("scan_imbalance") is None]

        for label_s, sub in [("imbalance < 60% (balanced)", sub_ok),
                              ("imbalance ≥ 60% (flagged !!)", sub_flag),
                              ("no CLOB data", sub_none)]:
            n_y, n_t, r = _yes_rate(sub)
            if n_t == 0: continue
            cn = _caution(n_t)
            print(f"  {label_s:<30} {_fmt(n_y, n_t, r)}{cn}")
        print()
        print("  Does flagged imbalance help predict outcomes? Check gap between rows.")
        print("  High imbalance = one-sided book — may signal informed flow OR thin market.")

        # ── Section 5: Price movement signal ──────────────────────────────────────────
        _section("PRICE MOVEMENT SIGNAL (abs price_1d_at_scan)" + (" [! caution]" if caution else ""))
        has_p1d   = [e for e in resolved if e.get("price_1d_at_scan") is not None]
        no_p1d    = [e for e in resolved if e.get("price_1d_at_scan") is None]
        sub_quiet  = [e for e in has_p1d if abs(e["price_1d_at_scan"]) < 0.01]
        sub_moving = [e for e in has_p1d if 0.01 <= abs(e["price_1d_at_scan"]) < 0.03]
        sub_strong = [e for e in has_p1d if abs(e["price_1d_at_scan"]) >= 0.03]

        if not has_p1d:
            print(f"  No entries with price_1d_at_scan yet ({len(no_p1d)} entries pre-date this field).")
            print("  This section will populate on next scan run.")
        else:
            print(f"  ({len(no_p1d)} older entries without price_1d_at_scan excluded)")
            for label_s, sub in [
                ("|p1d| < 0.01  (quiet / stale)", sub_quiet),
                ("|p1d| 0.01–0.03 (moving)",      sub_moving),
                ("|p1d| >= 0.03 (strong move)",   sub_strong),
            ]:
                n_y, n_t, r = _yes_rate(sub)
                if n_t == 0: continue
                cn = _caution(n_t)
                print(f"  {label_s:<35} {_fmt(n_y, n_t, r)}{cn}")
        print()
        print("  Is price movement at scan time predictive of outcome?")
        print("  Strong move + ACTIONABLE could signal informed flow — watch this metric.")

        # ── Section 6: Calibration bins ─────────────────────────────────────────────
        _section("CALIBRATION BINS (yes_price at scan time)" + (" [! caution]" if caution else ""))
        print("  [Actual YES rate should approximate avg yes_price if market is well-calibrated]")
        bins = [
            (0.10, 0.25, "p  [0.10–0.25]"),
            (0.25, 0.50, "p  [0.25–0.50]"),
            (0.50, 0.75, "p  [0.50–0.75]"),
            (0.75, 0.90, "p  [0.75–0.90]"),
        ]
        print(f"\n  {'Bin':<18} {'n':>4} {'YES rate':>10} {'avg_price':>10} {'cal_gap':>10}")
        print(f"  {'─'*18} {'─'*4} {'─'*10} {'─'*10} {'─'*10}")
        for lo, hi, label_s in bins:
            sub   = [e for e in resolved if lo <= (e.get("yes_price") or 0) < hi]
            n_y, n_t, r = _yes_rate(sub)
            avg_p = _avg(sub, "yes_price")
            if n_t == 0:
                print(f"  {label_s:<18} {0:>4}  {'—':>10}"); continue
            gap     = (r - avg_p) if (r is not None and avg_p is not None) else None
            gap_str = f"{gap:+.3f}" if gap is not None else "n/a"
            rate_s  = f"{n_y}/{n_t} ({_pct(r)})" if r is not None else "n/a"
            avg_s   = f"{avg_p:.3f}" if avg_p else "n/a"
            cn = _caution(n_t)
            print(f"  {label_s:<18} {n_t:>4}  {rate_s:<12} {avg_s:>8}   {gap_str:>8}{cn}")
        print()
        print("  cal_gap = actual_YES_rate − avg_yes_price per bin")
        print("  Persistent gap in a bin → systematic mispricing in that price range.")

        # ── Section 7: Score utility ────────────────────────────────────────────────
        _section("SCORE UTILITY (daily_score vs outcome)" + (" [! caution]" if caution else ""))
        if n_resolved >= 6:
            scored = sorted(resolved, key=lambda e: e.get("daily_score") or 0, reverse=True)
            mid    = len(scored) // 2
            top_h  = scored[:mid]
            bot_h  = scored[mid:]
            n_y_t, n_t_t, r_t = _yes_rate(top_h)
            n_y_b, n_t_b, r_b = _yes_rate(bot_h)
            avg_s_t = _avg(top_h, "daily_score")
            avg_s_b = _avg(bot_h, "daily_score")

            avg_s_t_str = f"{avg_s_t:.3f}" if avg_s_t is not None else "n/a"
            avg_s_b_str = f"{avg_s_b:.3f}" if avg_s_b is not None else "n/a"
            print(f"  Top 50% by score  (n={n_t_t}): {_fmt(n_y_t, n_t_t, r_t)}"
                  f"  avg_score={avg_s_t_str}{_caution(n_t_t)}")
            print(f"  Bot 50% by score  (n={n_t_b}): {_fmt(n_y_b, n_t_b, r_b)}"
                  f"  avg_score={avg_s_b_str}{_caution(n_t_b)}")
            if r_t is not None and r_b is not None:
                gap = r_t - r_b
                direction = "higher score → more YES (check calibration before acting)" if gap > 0 \
                    else "higher score → more NO (check calibration before acting)"
                print(f"  Score-outcome gap : {gap:+.3f}  — {direction}")
            print()
            print("  NOTE: Higher score ≠ 'correct call'. It means more urgency/liquidity,")
            print("  not necessarily meaningful. Check calibration gap per tier to assess scoring utility.")
        else:
            print(f"  Need >= 6 resolved entries to split. Have {n_resolved}.")

    # ── Observation vs Market-level summary (always printed) ──────────────────────
    _section("OBSERVATION vs MARKET vs EVENT SUMMARY")
    obs_rate_info  = (n_yes_all, n_tot_all, rate_all, cal_gap)
    mkt_n_yes_s, mkt_n_tot_s, mkt_rate_s = _yes_rate(market_resolved)
    mkt_cal_gap_s = _beat_market(market_resolved)
    mkt_rate_info  = (mkt_n_yes_s, mkt_n_tot_s, mkt_rate_s, mkt_cal_gap_s)
    _print_obs_vs_market(obs_summary, obs_rate_info, mkt_rate_info, market_resolved,
                         event_summary, event_resolved_pairs)

    # ── Pending list ────────────────────────────────────────────────────────────
    _section("PENDING ENTRIES (not yet resolved)")
    if pending:
        print(f"  {len(pending)} entries waiting for outcome — fill after market resolution")
        print(f"  {'Tier':<8} {'Date':<12} {'Resolves':<12} {'p':>5}  {'Question'}")
        for e in sorted(pending, key=lambda x: (x.get("scan_date",""), x.get("bucket",""))):
            end = e.get("end_date", "")[:10] if e.get("end_date") else "?"
            q   = (e.get("question") or "")[:45]
            print(f"  {(e.get('priority_tier') or '?'):<8} {e.get('scan_date',''):<12} "
                  f"{end:<12} {e.get('yes_price',0):>5.3f}  {q}")
    else:
        print("  No pending entries.")

    # ── Confidence thresholds ─────────────────────────────────────────────────
    _section("CONFIDENCE THRESHOLDS")
    _status(n_resolved, MIN_SAMPLE_WARN, "Meaningful section analysis")
    _status(n_resolved, MIN_SAMPLE_CONF, "Confident directional conclusions")
    _status(n_resolved, 50,              "Calibration bins (5+ per bin typical)")
    _status(
        min(
            min((sum(1 for e in resolved if e.get("priority_tier")==t) for t in ("A_TIER","B_TIER","C_TIER")), default=0),
            999
        ),
        5, "Per-tier minimum (weakest tier)"
    )
    print()
    print(f"  Current: {n_resolved} resolved. Keep running daily_scanner.py and filling outcomes.")

    print()
    print("─" * W)
    print("  VALIDATION COMPLETE")
    print("  Priority tiers = manual review order. Not trade signals.")
    print("  Calibration gap = the honest long-term quality metric.")
    print("─" * W)
    print()

    # ── Build + save report ───────────────────────────────────────────────────────
    n_y_all, n_t_all, r_all = _yes_rate(resolved)
    market_summary = _build_market_summary(market_resolved, early_stage)

    report = {
        "timestamp":  current_ts,
        "status":     "early_stage" if early_stage else ("caution" if caution else "normal"),
        "disclaimer": "Validation metrics only. Not trade signals.",
        "ledger_summary": {
            "total":    n_total,
            "resolved": n_resolved,
            "void":     n_void,
            "pending":  n_pending,
        },
        "overall": {
            "n_yes":          n_y_all,
            "n_no":           n_t_all - n_y_all,
            "yes_rate":       round(r_all, 4)    if r_all is not None    else None,
            "avg_yes_price":  round(avg_price_all, 4) if avg_price_all is not None else None,
            "avg_score":      round(avg_score_all, 4) if avg_score_all is not None else None,
            "calibration_gap": round(cal_gap, 4) if cal_gap is not None else None,
        },
        "by_tier":   {},
        "by_bucket": {},
        "calibration_bins": [],
        "confidence_thresholds": {
            "min_for_sections":   MIN_SAMPLE_WARN,
            "min_for_confidence": MIN_SAMPLE_CONF,
            "current_resolved":   n_resolved,
        },
        # ── NEW: observation/market-level dedup awareness ─────────────────
        "observation_summary": obs_summary,
        "market_summary":      market_summary,
        "repeated_markets":    repeated_list,
        "event_summary":       event_summary,
        "event_groups":        event_groups_list,
    }

    if not early_stage:
        for tier in ("A_TIER", "B_TIER", "C_TIER"):
            sub  = [e for e in resolved if e.get("priority_tier") == tier]
            n_y, n_t, r = _yes_rate(sub)
            bm   = _beat_market(sub)
            avg_p = _avg(sub, "yes_price")
            report["by_tier"][tier] = {
                "n_resolved": n_t,
                "n_yes":      n_y,
                "yes_rate":   round(r, 4) if r is not None else None,
                "avg_yes_price": round(avg_p, 4) if avg_p is not None else None,
                "beat_market":   round(bm, 4) if bm is not None else None,
            }
        for bkt in ("today", "week", "twoweek"):
            sub = [e for e in resolved if e.get("bucket") == bkt]
            n_y, n_t, r = _yes_rate(sub)
            avg_s = _avg(sub, "daily_score")
            report["by_bucket"][bkt] = {
                "n_resolved": n_t,
                "n_yes": n_y,
                "yes_rate": round(r, 4) if r is not None else None,
                "avg_score": round(avg_s, 4) if avg_s is not None else None,
            }
        bins = [
            (0.10, 0.25, "p  [0.10–0.25]"),
            (0.25, 0.50, "p  [0.25–0.50]"),
            (0.50, 0.75, "p  [0.50–0.75]"),
            (0.75, 0.90, "p  [0.75–0.90]"),
        ]
        for lo, hi, label_s in bins:
            sub = [e for e in resolved if lo <= (e.get("yes_price") or 0) < hi]
            n_y, n_t, r = _yes_rate(sub)
            avg_p = _avg(sub, "yes_price")
            gap   = (r - avg_p) if (r is not None and avg_p is not None) else None
            report["calibration_bins"].append({
                "bin":       label_s,
                "n":         n_t,
                "yes_rate":  round(r, 4) if r is not None else None,
                "avg_price": round(avg_p, 4) if avg_p is not None else None,
                "cal_gap":   round(gap, 4) if gap is not None else None,
            })

        # ── Imbalance signal analysis ─────────────────────────────────────────
        IMBAL_THRESHOLD = 0.60
        has_imbal = [e for e in resolved if (e.get("scan_imbalance") or 0) >= IMBAL_THRESHOLD]
        no_imbal  = [e for e in resolved if (e.get("scan_imbalance") or 0) <  IMBAL_THRESHOLD
                     and e.get("scan_imbalance") is not None]
        fi_y, fi_n, fi_r = _yes_rate(has_imbal)
        bi_y, bi_n, bi_r = _yes_rate(no_imbal)
        imbal_gap = ((fi_r or 0) - (bi_r or 0)) if (fi_r is not None and bi_r is not None) else None
        report["imbalance_signal"] = {
            "threshold":          IMBAL_THRESHOLD,
            "flagged_n":          fi_n,
            "flagged_yes":        fi_y,
            "flagged_yes_rate":   round(fi_r, 4) if fi_r is not None else None,
            "balanced_n":         bi_n,
            "balanced_yes":       bi_y,
            "balanced_yes_rate":  round(bi_r, 4) if bi_r is not None else None,
            "gap":                round(imbal_gap, 4) if imbal_gap is not None else None,
            "sufficient_sample":  fi_n >= 10 and bi_n >= 10,
        }

    ts_str   = now_utc.strftime("%Y%m%d_%H%M%S")
    fname_ts = LOGS_DIR / f"validation_report_{ts_str}.json"
    fname_l  = LOGS_DIR / "validation_report_latest.json"

    for fp in [fname_ts, fname_l]:
        with fp.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print(f"Saved: {fname_ts}")
    print(f"Saved: {fname_l}  <- latest pointer")

    # ── Calibration trend log — device-independent history ─────────────────
    # Appends one entry per validate.py run (max 30 kept).
    # Frontend reads logs/calibration_trend.json instead of localStorage.
    trend_file = LOGS_DIR / "calibration_trend.json"
    cal_gap_obs = report.get("overall", {}).get("calibration_gap")
    if cal_gap_obs is not None:
        try:
            existing = json.loads(trend_file.read_text()) if trend_file.exists() else []
        except Exception:
            existing = []
        entry = {
            "ts":           report.get("timestamp", now_utc.isoformat()),
            "gap":          cal_gap_obs,
            "n_resolved":   (report.get("overall", {}).get("n_yes", 0) or 0)
                            + (report.get("overall", {}).get("n_no", 0) or 0),
        }
        updated = (existing + [entry])[-30:]   # keep last 30
        trend_file.write_text(json.dumps(updated, indent=2))
        print(f"Saved: {trend_file}  ({len(updated)} entries)")


if __name__ == "__main__":
    main()
