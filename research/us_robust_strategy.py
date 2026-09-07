"""
US Robust Strategy — Frozen construction from factor lab
========================================================
Design principles (from ops.us_factor_research results):
  1) Momentum core only from PASS factors (Leader / Mom63 / Mom12 / RelMom / NearHigh)
  2) Drop AccumulDiv (FAIL) and pure fundamental sleeves (weak IR / short sample)
  3) Avoid double-counting Mom12≈RelMom (corr~1.0): at most ONE pure 12-1 sleeve
  4) Leader already embeds near_high + mom63 tilt → prefer Leader as primary core
  5) LowVol failed standalone but corr~0.39 vs Leader → defensive satellite only
  6) Optimize robustness_score, not raw CAGR
  7) Pre-registered small variant set only (no free search)

Frozen candidates (equal-weight within sleeve, name cap 15%):
  A  Robust_L70_LV30        Leader 70 / LowVol 30
  B  Robust_L60_M63_LV20    Leader 60 / Mom63 20 / LowVol 20
  C  Robust_L50_RM_LV20     Leader 50 / RelMom 30 / LowVol 20  (lab winner)
  D  Robust_L55_NH_LV25     Leader 55 / NearHigh 20 / LowVol 25
  E  Aggressive_L100        Leader 100 (reference)
  + 20bp stress twin of the selected robust book

Protocol: identical to factor lab (next-open, IS/OOS, WF, block bootstrap, gates).
Outputs: results/us_robust/
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# repo-root import bootstrap (research modules live one level below the root)
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from ops.us_hybrid_backtest import (
    COST_BASE,
    COST_STRESS,
    DATA,
    IS_END,
    MAX_NAME,
    SEED,
    build_ttm,
    build_valuation_panel,
    build_universe,
    download_fundamentals,
    load_index,
    load_prices,
    market_regime,
    month_ends,
    perf,
)
from ops.us_factor_research import (
    ALL_SINGLE,
    BLOCK_LEN,
    N_TOP,
    block_bootstrap_excess,
    build_multi_picks,
    compute_all_features,
    diagnose,
    evaluate_gates_strict,
    robustness_score,
    run_portfolio,
    split_isoos,
    walk_forward,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "us_robust"
CHART = OUT / "charts"

# Pre-registered robust books only
VARIANTS = [
    {
        "name": "Robust_L70_LV30",
        "sleeves": ["Leader", "LowVol"],
        "weights": {"Leader": 0.70, "LowVol": 0.30},
        "thesis": "코어 Leader + 저상관 방어. RelMom 중복 제거.",
        "family": "robust",
    },
    {
        "name": "Robust_L60_M63_LV20",
        "sleeves": ["Leader", "Mom63", "LowVol"],
        "weights": {"Leader": 0.60, "Mom63": 0.20, "LowVol": 0.20},
        "thesis": "Leader 주력 + 강건 1위 Mom63 위성(상한 20) + LowVol.",
        "family": "robust",
    },
    {
        "name": "Robust_L50_RM_LV20",
        "sleeves": ["Leader", "RelMom", "LowVol"],
        "weights": {"Leader": 0.50, "RelMom": 0.30, "LowVol": 0.20},
        "thesis": "팩터랩 강건성 1위 조합. Leader–RelMom 상관 높음 주의.",
        "family": "robust",
    },
    {
        "name": "Robust_L55_NH_LV25",
        "sleeves": ["Leader", "NearHigh", "LowVol"],
        "weights": {"Leader": 0.55, "NearHigh": 0.20, "LowVol": 0.25},
        "thesis": "안정형 NearHigh + LowVol 비중 확대. 낙폭 우선.",
        "family": "robust",
    },
    {
        "name": "Aggressive_L100",
        "sleeves": ["Leader"],
        "weights": {"Leader": 1.0},
        "thesis": "순수 Leader 벤치(공격 참고).",
        "family": "reference",
    },
]


def pick_recommended(rows: List[Dict]) -> Dict:
    """Prefer robust family, non-stress, best robustness; require not hard FAIL."""
    robust = [r for r in rows if r.get("family") == "robust" and not str(r["name"]).endswith("20bp")]
    pool = robust or [r for r in rows if not str(r["name"]).endswith("20bp")]
    pool = sorted(pool, key=lambda x: x["score"], reverse=True)
    for r in pool:
        if r.get("gate") == "FAIL" and r.get("n_pass", 0) < r.get("n_total", 10) - 2:
            continue
        return r
    return pool[0]


def main(force: bool = False):
    OUT.mkdir(parents=True, exist_ok=True)
    CHART.mkdir(parents=True, exist_ok=True)

    print("== Data ==")
    meta = build_universe()
    codes = meta["Code"].astype(str).tolist()
    close, open_px, volume = load_prices(codes, force=force)
    vol_path = DATA / "us_volume_panel.parquet"
    if vol_path.exists():
        volume = pd.read_parquet(vol_path)
        volume.index = pd.to_datetime(volume.index)
        volume = volume.reindex(close.index)
    index_close = load_index(force=force).reindex(close.index).ffill()
    regime = market_regime(index_close)

    fund = download_fundamentals(close.columns.tolist(), force=force)
    fund_ttm = build_ttm(fund) if not fund.empty else pd.DataFrame()
    val = build_valuation_panel(close, volume, fund_ttm, force=force)
    if not val.empty:
        val["date"] = pd.to_datetime(val["date"])
        val["code"] = val["code"].astype(str)

    print("== Features / calendar ==")
    feats = compute_all_features(close, volume, index_close)
    me = month_ends(close.index)
    start = max(pd.Timestamp("2019-07-01"), close.index[0] + pd.Timedelta(days=280))
    me = [d for d in me if d >= start]
    print(f"signals={len(me)} {me[0].date()}~{me[-1].date()}")

    results = {}
    eq_cols = {}

    print("== Robust variants ==")
    for spec in VARIANTS:
        name = spec["name"]
        print(f"  - {name} {spec['weights']}")
        picks, scores = build_multi_picks(
            me, feats, val, close, volume, regime, spec["sleeves"]
        )
        res = run_portfolio(
            close, open_px, picks, spec["weights"], scores,
            cost=COST_BASE, max_name=MAX_NAME, weight_mode="equal", label=name,
        )
        br = index_close.reindex(res["equity"].index).ffill().pct_change().fillna(0.0)
        be = (1 + br).cumprod() * SEED
        bs = perf(be, br, br, "Bench_SPY")
        diag = diagnose(name, res, br, bs, limited=False)
        diag["spec"] = spec
        results[name] = diag
        eq_cols[name] = res["equity"]
        print(
            f"    CAGR={diag['stats'].get('cagr')} Sharpe={diag['stats'].get('sharpe')} "
            f"IR={diag['stats'].get('info_ratio')} MDD={diag['stats'].get('mdd')} "
            f"rob={diag['robustness']['score']} gate={diag['gates']['status']}"
        )

    # Rank
    ranking = []
    for name, diag in results.items():
        ranking.append({
            "name": name,
            "family": diag["spec"]["family"],
            "thesis": diag["spec"]["thesis"],
            "weights": diag["spec"]["weights"],
            "sleeves": diag["spec"]["sleeves"],
            **diag["robustness"],
            "gate": diag["gates"]["status"],
            "n_pass": diag["gates"]["n_pass"],
            "n_total": diag["gates"]["n_total"],
            "cagr": diag["stats"].get("cagr"),
            "vol": diag["stats"].get("vol"),
            "mdd": diag["stats"].get("mdd"),
            "calmar": diag["stats"].get("calmar"),
            "win_month": diag["stats"].get("win_month"),
            "beta": diag["stats"].get("beta"),
        })
    ranking = sorted(ranking, key=lambda x: x["score"], reverse=True)
    rec_row = pick_recommended(ranking)
    rec_name = rec_row["name"]
    rec = results[rec_name]

    # Stress twin of recommended
    stress_name = f"{rec_name}_20bp"
    print(f"== Stress {stress_name} ==")
    picks, scores = build_multi_picks(
        me, feats, val, close, volume, regime, rec["spec"]["sleeves"]
    )
    res_s = run_portfolio(
        close, open_px, picks, rec["spec"]["weights"], scores,
        cost=COST_STRESS, max_name=MAX_NAME, weight_mode="equal", label=stress_name,
    )
    br = index_close.reindex(res_s["equity"].index).ffill().pct_change().fillna(0.0)
    be = (1 + br).cumprod() * SEED
    bs = perf(be, br, br, "Bench_SPY")
    diag_s = diagnose(stress_name, res_s, br, bs, limited=False)
    diag_s["spec"] = {
        **rec["spec"],
        "name": stress_name,
        "thesis": "20bp 비용 스트레스",
        "family": "stress",
    }
    results[stress_name] = diag_s
    eq_cols[stress_name] = res_s["equity"]
    print(
        f"    CAGR={diag_s['stats'].get('cagr')} Sharpe={diag_s['stats'].get('sharpe')} "
        f"IR={diag_s['stats'].get('info_ratio')} gate={diag_s['gates']['status']}"
    )

    # Bench aligned to recommended
    ref_idx = rec["equity"].index
    b_rets = index_close.reindex(ref_idx).ffill().pct_change().fillna(0.0)
    b_eq = (1 + b_rets).cumprod() * SEED
    b_stats = perf(b_eq, b_rets, b_rets, "Bench_SPY")

    # Equity matrix
    eq_df = pd.DataFrame({"Bench_SPY": b_eq})
    for k, s in eq_cols.items():
        eq_df[k] = s.reindex(eq_df.index)
    eq_df.to_csv(OUT / "equity_curves.csv")

    # Stats CSV
    stats_rows = []
    for name, diag in results.items():
        row = dict(diag["stats"])
        row["robustness"] = diag["robustness"]["score"]
        row["gate"] = diag["gates"]["status"]
        row["med_wf_excess"] = diag["robustness"]["med_wf_excess"]
        row["fold_concentration"] = diag["robustness"]["fold_concentration"]
        row["boot_p_pos"] = diag["robustness"]["boot_p_pos"]
        row["family"] = diag["spec"]["family"]
        stats_rows.append(row)
    # insert bench
    stats_rows.insert(0, {**b_stats, "robustness": None, "gate": None,
                          "med_wf_excess": None, "fold_concentration": None,
                          "boot_p_pos": None, "family": "bench"})
    stats_df = pd.DataFrame(stats_rows)
    stats_df.to_csv(OUT / "stats.csv", index=False)

    # Monthly return corr among sleeves used in recommended
    sleeve_rets = {}
    for sleeve in rec["spec"]["sleeves"]:
        picks, scores = build_multi_picks(me, feats, val, close, volume, regime, [sleeve])
        res_sl = run_portfolio(
            close, open_px, picks, {sleeve: 1.0}, scores,
            cost=COST_BASE, max_name=MAX_NAME, weight_mode="equal", label=sleeve,
        )
        sleeve_rets[sleeve] = res_sl["equity"].resample("ME").last().pct_change()
    sleeve_corr = pd.DataFrame(sleeve_rets).corr()
    sleeve_corr.to_csv(OUT / "sleeve_corr_monthly.csv")

    def strip(d):
        return {k: v for k, v in d.items() if k not in ("equity", "returns", "holdings")}

    payload = {
        "title": "US Robust Strategy",
        "design_principles": [
            "PASS price factors only for alpha engines",
            "Drop AccumulDiv and weak fundamental sleeves",
            "At most one pure 12-1 sleeve (Mom12/RelMom redundant)",
            "Leader is primary filtered core",
            "LowVol satellite for correlation diversify",
            "Maximize robustness_score not CAGR",
            "Pre-registered variants only",
        ],
        "protocol": {
            "execution": "next_open",
            "cost_base": COST_BASE,
            "cost_stress": COST_STRESS,
            "max_name": MAX_NAME,
            "is_end": IS_END,
            "bootstrap": "moving_block_bootstrap",
            "block_len": BLOCK_LEN,
            "weight_mode": "equal_within_sleeve",
            "n_top": N_TOP,
        },
        "data_range": {
            "prices": f"{close.index.min().date()}~{close.index.max().date()}",
            "signals": f"{me[0].date()}~{me[-1].date()}",
            "n_codes": int(close.shape[1]),
            "n_signals": len(me),
        },
        "variants": VARIANTS,
        "ranking": ranking,
        "recommended": {
            "name": rec_name,
            "row": rec_row,
            "stats": rec["stats"],
            "gates": rec["gates"],
            "isoos": rec["isoos"],
            "walk_forward": rec["walk_forward"],
            "bootstrap": rec["bootstrap"],
            "robustness": rec["robustness"],
            "latest_holdings": rec["holdings"][-1] if rec["holdings"] else {},
            "holdings_tail": rec["holdings"][-6:] if rec["holdings"] else [],
            "stress": {
                "name": stress_name,
                "stats": diag_s["stats"],
                "gates": diag_s["gates"],
                "robustness": diag_s["robustness"],
            },
        },
        "bench": b_stats,
        "all": {k: {**strip(v), "spec": v["spec"]} for k, v in results.items()},
        "sleeve_corr": sleeve_corr.round(3).to_dict(),
        "ops_rule": {
            "signal": "month_end_close",
            "exec": "next_open",
            "rebalance": "monthly",
            "exit": "signal_drop_only",
            "forbidden": [
                "AccumulDiv sleeve",
                "weekly name refresh",
                "averaging down",
                "event NLP exits",
                "post-hoc weight optimization",
            ],
        },
    }

    with open(OUT / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    with open(OUT / "holdings.json", "w", encoding="utf-8") as f:
        json.dump(rec["holdings"], f, ensure_ascii=False, indent=2, default=str)

    print("\n== RANKING ==")
    for r in ranking:
        print(
            f"  {r['name']:22s} rob={r['score']:+.3f} CAGR={r['cagr']} "
            f"Sh={r['sharpe']} IR={r['ir']} MDD={r['mdd']} gate={r['gate']}"
        )
    print("\nRECOMMENDED:", rec_name, rec_row["weights"])
    print("STRESS:", stress_name, diag_s["stats"].get("cagr"), diag_s["gates"]["status"])
    print("DONE ->", OUT)
    return payload


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    main(force=args.force)
