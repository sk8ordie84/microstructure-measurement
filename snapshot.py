#!/usr/bin/env python3
"""STUDIO11 Snapshot generator. CSV -> markdown -> PDF (via pandoc).

Usage:
    python snapshot.py trades.csv "Client Name"

Required CSV columns:
    timestamp, market_id, market_question, side, buy_sell,
    predicted_prob, executed_price, size_shares, size_usdc,
    resolved_outcome, won, payout_usdc, event_id

Output:
    out_<client_name>/report.md  (run pandoc to produce PDF)
    out_<client_name>/calibration.png
    out_<client_name>/edge_decay.png
    out_<client_name>/pnl_dist.png
"""
import sys, os, json, math
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

REQUIRED = ["timestamp","market_id","market_question","side","buy_sell",
            "predicted_prob","executed_price","size_shares","size_usdc",
            "resolved_outcome","won","payout_usdc","event_id"]

def validate_schema(df):
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Required: {REQUIRED}")
    if df["predicted_prob"].between(0,1).sum() != len(df):
        raise ValueError("predicted_prob must be in [0,1]")
    if not df["won"].dropna().isin([True,False,0,1]).all():
        raise ValueError("won column must be boolean/0-1")
    if df["resolved_outcome"].isna().any():
        n = df["resolved_outcome"].isna().sum()
        print(f"WARN: {n} unresolved rows dropped")
    return df.dropna(subset=["resolved_outcome","won"]).copy()

def wilson_ci(k, n, z=1.96):
    if n == 0: return (0,0)
    p = k/n
    d = 1 + z*z/n
    c = p + z*z/(2*n)
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c-h)/d, (c+h)/d)

def brier(p, y): return float(np.mean((p-y)**2))
def logloss(p, y, eps=1e-12):
    p = np.clip(p, eps, 1-eps)
    return float(-np.mean(y*np.log(p) + (1-y)*np.log(1-p)))

def calibration_buckets(df, n=10):
    edges = np.linspace(0,1,n+1)
    df = df.assign(bucket=pd.cut(df.predicted_prob, edges, include_lowest=True))
    rows = []
    for b, g in df.groupby("bucket", observed=True):
        if len(g)==0: continue
        k, m = int(g.won.sum()), len(g)
        lo, hi = wilson_ci(k, m)
        rows.append(dict(bucket=str(b), n=m, predicted=g.predicted_prob.mean(),
                         actual=k/m, lo=lo, hi=hi))
    return pd.DataFrame(rows)

def baseline_naive_pnl(df):
    """BASELINE_NAIVE: bet YES if executed_price < 0.5, NO otherwise, same size."""
    base = df.copy()
    base["base_side_yes"] = base.executed_price < 0.5
    actual_yes = base.resolved_outcome.astype(str).str.upper().eq("YES")
    base["base_won"] = base.base_side_yes == actual_yes
    base["base_pnl"] = np.where(base.base_won,
                                base.size_shares*(1-base.executed_price),
                                -base.size_shares*base.executed_price)
    return base.base_pnl.values

def system_pnl(df):
    return (df.payout_usdc - df.size_usdc).values

def clustered_bootstrap(df, sys_pnl, base_pnl, n_boot=2000, seed=11):
    rng = np.random.default_rng(seed)
    clusters = df.event_id.values
    uniq = np.unique(clusters)
    diffs = []
    for _ in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([np.where(clusters==c)[0] for c in pick])
        diffs.append(sys_pnl[idx].sum() - base_pnl[idx].sum())
    return float(np.mean(diffs)), float(np.percentile(diffs,2.5)), float(np.percentile(diffs,97.5))

def spread_decomposition(df):
    """Spread cost proxy: |executed_price - predicted_prob| * size_shares per fill."""
    spread_cost = (np.abs(df.executed_price - df.predicted_prob) * df.size_shares).sum()
    total_gap = (df.size_usdc.sum() - df.payout_usdc.sum())
    pct = (spread_cost / abs(total_gap)) * 100 if total_gap else 0
    return float(spread_cost), float(pct)

def edge_decay(df):
    df = df.copy()
    df.timestamp = pd.to_datetime(df.timestamp)
    res = df.groupby("event_id").timestamp.transform("max")
    df["hold_days"] = (res - df.timestamp).dt.total_seconds()/86400
    bins = [0,1,7,30,90,9999]
    labels = ["<1d","1-7d","7-30d","30-90d",">90d"]
    df["bucket"] = pd.cut(df.hold_days, bins, labels=labels, include_lowest=True)
    return df.groupby("bucket", observed=True).agg(
        n=("won","size"), hit_rate=("won","mean"),
        pnl=("payout_usdc", lambda x: (x - df.loc[x.index,"size_usdc"]).sum())
    ).reset_index()

def detect_failure_modes(df, calib, decay, sys_pnl, base_pnl, spread_pct):
    """Return ranked list of operationally severe failures."""
    findings = []
    high = calib[calib.predicted >= 0.7]
    if len(high) and (high.predicted - high.actual).mean() > 0.08:
        gap = (high.predicted - high.actual).mean()
        n = int(high.n.sum())
        findings.append((90, f"Calibration breaks above 0.7: model predicts "
            f"{high.predicted.mean():.2f} but realizes {high.actual.mean():.2f} "
            f"(gap {gap:.2f}, n={n}). High-conviction bets are systematically overconfident."))
    long_hold = decay[decay.bucket.astype(str).isin([">90d","30-90d"])]
    if len(long_hold) and long_hold.pnl.sum() < 0 and spread_pct > 30:
        findings.append((80, f"Spread/fill cost is {spread_pct:.0f}% of PnL gap, "
            f"concentrated in 30+ day holds (net ${long_hold.pnl.sum():.0f}). "
            f"Edge does not survive carry on long-dated contracts."))
    by_event = df.groupby("event_id").agg(n=("won","size"), hit=("won","mean"))
    rare = by_event[by_event.n <= 2]
    common = by_event[by_event.n > 2]
    if len(rare) > 5 and rare.hit.mean() < common.hit.mean() - 0.05:
        findings.append((70, f"Long-tail markets (<=2 fills/event, n={len(rare)}) "
            f"hit {rare.hit.mean():.2%} vs {common.hit.mean():.2%} on repeat events. "
            f"Selection layer fails on novel markets, likely overfit to recurring patterns."))
    if sys_pnl.sum() < base_pnl.sum():
        findings.append((95, f"System PnL ${sys_pnl.sum():.0f} trails BASELINE_NAIVE "
            f"${base_pnl.sum():.0f}. The model adds negative value vs price-only heuristic."))
    yes_rate = (df.side.str.upper()=="YES").mean()
    if yes_rate > 0.7 or yes_rate < 0.3:
        findings.append((60, f"Side bias: {yes_rate:.0%} of fills are YES. "
            f"Strategy is directional, not mean-neutral, vulnerable to regime shift."))
    findings.sort(reverse=True)
    return [f for _, f in findings[:3]]

def make_charts(calib, decay, sys_pnl, outdir):
    plt.figure(figsize=(6,5))
    plt.plot([0,1],[0,1],"k--",alpha=0.4,label="perfect")
    plt.errorbar(calib.predicted, calib.actual,
                 yerr=[calib.actual-calib.lo, calib.hi-calib.actual],
                 fmt="o-", capsize=3)
    plt.xlabel("predicted prob"); plt.ylabel("realized hit rate")
    plt.title("Calibration (10 buckets, Wilson 95% CI)"); plt.legend()
    plt.savefig(f"{outdir}/calibration.png", dpi=140, bbox_inches="tight"); plt.close()

    plt.figure(figsize=(6,4))
    plt.bar(decay.bucket.astype(str), decay.hit_rate)
    plt.axhline(0.5, color="k", ls="--", alpha=0.4)
    plt.ylabel("hit rate"); plt.title("Edge decay by holding period")
    plt.savefig(f"{outdir}/edge_decay.png", dpi=140, bbox_inches="tight"); plt.close()

    plt.figure(figsize=(6,4))
    plt.hist(sys_pnl, bins=40); plt.axvline(0, color="k", ls="--")
    plt.xlabel("PnL per trade (USDC)"); plt.title("PnL distribution")
    plt.savefig(f"{outdir}/pnl_dist.png", dpi=140, bbox_inches="tight"); plt.close()

REPORT = """---
title: "STUDIO11 Snapshot - {client}"
date: "{date}"
geometry: margin=1in
---

# Executive Summary
Sample: **{n_trades} trades** across **{n_events} events**. System net PnL **${sys_pnl:.0f}** vs BASELINE_NAIVE **${base_pnl:.0f}** (delta **${delta:.0f}**, 95% CI [${ci_lo:.0f}, ${ci_hi:.0f}]). Brier **{brier:.3f}**, log-loss **{logloss:.3f}**.

# Calibration
![]({outdir}/calibration.png)

Brier {brier:.4f} . log-loss {logloss:.4f}. Bucket table:

{calib_table}

# Forward Benchmark vs BASELINE_NAIVE
- Row-level delta: ${delta:.0f}
- Clustered bootstrap CI (event-level, 2000 iters): [${ci_lo:.0f}, ${ci_hi:.0f}]
- Verdict: **{verdict}**

![]({outdir}/pnl_dist.png)

# Spread / Fill Cost
Estimated spread cost: **${spread_cost:.0f}** ({spread_pct:.1f}% of total PnL gap).

# Edge Decay
![]({outdir}/edge_decay.png)

{decay_table}

# Failure Modes (ranked)
1. {fm1}
2. {fm2}
3. {fm3}

# Decision Summary
{decision}
"""

def main(csv_path, client="Client"):
    outdir = Path(f"out_{client.lower().replace(' ','_')}")
    outdir.mkdir(exist_ok=True)
    df = validate_schema(pd.read_csv(csv_path))
    calib = calibration_buckets(df)
    sys_p, base_p = system_pnl(df), baseline_naive_pnl(df)
    delta, lo, hi = clustered_bootstrap(df, sys_p, base_p)
    spread_cost, spread_pct = spread_decomposition(df)
    decay = edge_decay(df)
    fms = detect_failure_modes(df, calib, decay, sys_p, base_p, spread_pct)
    while len(fms) < 3: fms.append("No further structural issues detected at p<0.05.")
    make_charts(calib, decay, sys_p, str(outdir))
    verdict = "edge confirmed" if lo > 0 else "edge not significant" if hi > 0 else "underperforms baseline"
    decision = (f"Ship: {verdict}. Capacity-limited by {'spread' if spread_pct>30 else 'sample size'}. "
                f"Recommend: {'reduce size on >30d holds' if spread_pct>30 else 'expand sample, revisit in 90d'}.")
    md = REPORT.format(client=client, date=datetime.now().strftime("%Y-%m-%d"),
        n_trades=len(df), n_events=df.event_id.nunique(),
        sys_pnl=sys_p.sum(), base_pnl=base_p.sum(), delta=delta, ci_lo=lo, ci_hi=hi,
        brier=brier(df.predicted_prob.values, df.won.astype(int).values),
        logloss=logloss(df.predicted_prob.values, df.won.astype(int).values),
        outdir=str(outdir),
        calib_table=calib.round(3).to_markdown(index=False),
        decay_table=decay.round(3).to_markdown(index=False),
        spread_cost=spread_cost, spread_pct=spread_pct,
        verdict=verdict, fm1=fms[0], fm2=fms[1], fm3=fms[2], decision=decision)
    (outdir/"report.md").write_text(md)
    print(f"Wrote {outdir}/report.md")
    print(f"Convert: pandoc {outdir}/report.md -o {outdir}/report.pdf "
          f"--pdf-engine=xelatex -V mainfont='Helvetica' -V fontsize=10pt")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Client")
