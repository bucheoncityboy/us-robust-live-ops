"""Strict as-if monthly test of the frozen Robust_L60_M63_LV20 (2025-01 ~ 2026-07).

Question: if the frozen live-ops policy had been executed every month, what would
2025-01 .. 2026-07 performance have been?

Method: reproduce the production pipeline EXACTLY.
  - Universe / prices / regime / features: ops.ops_monthly_run.load_market (cache only, no network)
  - Per-month signals + targets: ops.ops_monthly_run.build_target (the live-ops target builder)
  - Execution: signal at month-end Close -> fill at next trading day Open (policy NEXT_OPEN)
  - Weights: equal-within-sleeve 60/20/20, name cap 15%, empty sleeve / cap leftover -> cash
  - Cost: 10bp round-trip base (policy COST), 20bp stress, 0bp isolation

Bias / overfit controls:
  - Frozen parameters only; NOTHING re-tuned on this window.
  - All features are trailing rolling windows (point-in-time by construction); signal uses
    only data <= month-end close; fills use next-day opens only (no lookahead).
  - Validation: recomputed picks must equal the LIVE ops_runs signals (2026-06 / 2026-07)
    and target.csv weights.
  - Lookahead sensitivity: same picks filled at signal-day CLOSE (quantifies the bias the
    NEXT_OPEN rule avoids).
  - Cost sensitivity: 0 / 10 / 20 bp.
  - Universe sensitivity: top 100 / 125 / 150 (survivorship is current-constituent based;
    direction and magnitude are reported, not hidden).
  - Block bootstrap of monthly excess returns (small-sample caveat stated).

Known limits (documented, not eliminated):
  - Universe = current S&P500 top-150 by recent $ volume -> survivorship bias.
  - 2025-01..2026-06 OVERLAPS the frozen research window (research ended 2026-06-29,
    freeze 2026-07-19). Only 2026-07 (signal 2026-07-31 -> exec 2026-08-03) is
    genuinely post-freeze OOS. This script is an as-if counterfactual, not a clean OOS test.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ops.ops_us_policy import (
    COST,
    MAX_NAME,
    N_LEADER,
    N_LOWVOL,
    N_MOM63,
    POLICY_NAME,
    SLEEVE_WEIGHTS,
)
from ops.ops_monthly_run import build_target, load_market
from ops.us_hybrid_backtest import (
    SEED,
    COST_BASE,
    COST_STRESS,
    merge_sleeve_weights,
    month_ends,
    next_open_map,
    perf,
    turnover,
    weights_equal,
)

OUT = ROOT / "results" / "strict_asif"

SIGNAL_START = "2024-12-31"   # signal -> exec 2025-01-02 (first holding month 2025-01)
SIGNAL_END = "2026-07-31"     # signal -> exec 2026-08-03 (last signal of requested window)
REPORT_END = "2026-07-31"     # primary stats cut (through July 2026)
BOOT_N = 2000
BOOT_SEED = 42
SLEEVES = ("leader", "mom63", "lowvol")


def build_signal_targets(feats, frgn_feats, val, regime, close, volume, signal_dates):
    """Per-signal-date picks + targets via the production builder (build_target)."""
    picks_by_sig: Dict[pd.Timestamp, Dict[str, List[str]]] = {}
    w_by_sig: Dict[pd.Timestamp, Dict[str, float]] = {}
    reg_by_sig: Dict[pd.Timestamp, str] = {}
    for d in signal_dates:
        picks, final_w, _name_w, reg = build_target(
            d, feats, frgn_feats, val, regime, close, volume
        )
        picks_by_sig[d] = picks
        w_by_sig[d] = final_w
        reg_by_sig[d] = reg
    return picks_by_sig, w_by_sig, reg_by_sig


def simulate(
    picks_by_sig: Dict[pd.Timestamp, Dict[str, List[str]]],
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    cost: float,
    exec_rule: str = "next_open",
    sleeve_weights: Optional[Dict[str, float]] = None,
) -> Dict:
    """Daily equity simulation mirroring the research run_portfolio mechanics.

    exec_rule:
      next_open     -> policy: fill at next trading day open
      signal_close  -> lookahead sensitivity: fill at signal-day close
    """
    sleeve_weights = dict(sleeve_weights or SLEEVE_WEIGHTS)
    exec_map = next_open_map(close.index, open_px)
    sig_to_exec: Dict[pd.Timestamp, pd.Timestamp] = {}
    for sig in sorted(picks_by_sig):
        if exec_rule == "next_open":
            ex = exec_map.get(sig)
            if ex is not None and ex in close.index:
                sig_to_exec[sig] = ex
        else:
            if sig in close.index:
                sig_to_exec[sig] = sig
    if not sig_to_exec:
        raise RuntimeError("no executable signal dates")

    rebal_on = {ex: sig for sig, ex in sig_to_exec.items()}
    all_days = close.index[close.index >= min(rebal_on.keys())]
    cash = float(SEED)
    shares: Dict[str, float] = {}
    prev_w: Dict[str, float] = {}
    equity_rows = []
    rets = []
    logs = []
    for d in all_days:
        port_val = cash
        for c, sh in shares.items():
            px = close.at[d, c] if c in close.columns else np.nan
            if pd.notna(px):
                port_val += sh * px

        if d in rebal_on:
            sig = rebal_on[d]
            picks = picks_by_sig[sig]
            name_w: Dict[str, Dict[str, float]] = {}
            dropped = 0
            for s in SLEEVES:
                codes = []
                for c in picks.get(s, []):
                    if exec_rule == "next_open":
                        px = open_px.at[d, c] if c in open_px.columns else np.nan
                    else:
                        px = close.at[d, c] if c in close.columns else np.nan
                    if pd.notna(px) and px > 0:
                        codes.append(c)
                    else:
                        dropped += 1
                name_w[s] = weights_equal(codes)
            sw = dict(sleeve_weights)
            cash_w = 0.0
            for s in SLEEVES:
                if not name_w.get(s):
                    cash_w += sw.pop(s, 0.0)
            if cash_w > 0:
                sw["cash"] = sw.get("cash", 0.0) + cash_w
            target = merge_sleeve_weights(sw, name_w, max_name=MAX_NAME)
            to = turnover(prev_w, target)
            port_val = max(port_val * (1 - to * cost), 0.0)

            shares = {}
            invested = 0.0
            for c, w in target.items():
                px = open_px.at[d, c] if exec_rule == "next_open" else close.at[d, c]
                if pd.isna(px) or px <= 0 or w <= 0:
                    continue
                sh = (port_val * w) / px
                shares[c] = sh
                invested += sh * px
            cash = port_val - invested
            prev_w = target
            logs.append(
                {
                    "signal_date": sig.strftime("%Y-%m-%d"),
                    "exec_date": d.strftime("%Y-%m-%d"),
                    "n_leader": len(picks.get("leader", [])),
                    "n_mom63": len(picks.get("mom63", [])),
                    "n_lowvol": len(picks.get("lowvol", [])),
                    "n_names": len(shares),
                    "weight_sum": round(float(sum(target.values())), 6),
                    "turnover": round(float(to), 4),
                    "cost_paid_bps": round(float(to * cost * 1e4), 2),
                    "exec_drops": dropped,
                    "top3": [f"{c}:{w:.3f}" for c, w in sorted(target.items(), key=lambda x: -x[1])[:3]],
                }
            )
            port_val = cash
            for c, sh in shares.items():
                px = close.at[d, c] if c in close.columns else np.nan
                if pd.notna(px):
                    port_val += sh * px

        equity_rows.append({"date": d, "equity": port_val})
        if len(equity_rows) >= 2:
            prev = equity_rows[-2]["equity"]
            rets.append(port_val / prev - 1 if prev > 0 else 0.0)
        else:
            rets.append(0.0)

    eq = pd.DataFrame(equity_rows).set_index("date")["equity"]
    r = pd.Series(rets, index=eq.index)
    return {"equity": eq, "returns": r, "logs": logs}


def monthly_returns(eq: pd.Series) -> pd.Series:
    ends = eq.resample("ME").last()
    r = ends.pct_change()
    if len(r) >= 1 and pd.isna(r.iloc[0]) and len(ends) >= 1 and len(eq) >= 1:
        r.iloc[0] = ends.iloc[0] / eq.iloc[0] - 1.0  # first month incl. initial cost
    return r.dropna()


def bootstrap_excess(me_strat: pd.Series, me_spy: pd.Series,
                     n: int = BOOT_N, seed: int = BOOT_SEED) -> Dict:
    ex = (me_strat - me_spy).dropna().values
    if len(ex) < 6:
        return {}
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(ex, size=len(ex), replace=True).mean() for _ in range(n)])
    return {
        "n_months": int(len(ex)),
        "obs_ann_excess": round(float(ex.mean() * 12), 4),
        "t_stat": round(float(ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex)))), 3)
        if len(ex) > 1 and ex.std(ddof=1) > 0 else None,
        "boot_mean": round(float(means.mean() * 12), 4),
        "boot_p5": round(float(np.percentile(means, 5) * 12), 4),
        "boot_p95": round(float(np.percentile(means, 95) * 12), 4),
        "prob_positive": round(float((means > 0).mean()), 4),
        "method": "iid_monthly_block_bootstrap",
    }


def validate_against_live(picks_by_sig, w_by_sig, sig) -> Dict:
    """Compare recomputed signal against the live ops_runs artifacts."""
    run_dir = ROOT / "results" / "ops_runs" / f"{sig.year:04d}-{sig.month:02d}"
    if not (run_dir / "signals.csv").exists():
        return {"available": False}
    live = pd.read_csv(run_dir / "signals.csv")
    live = live[live["asof"] == sig.strftime("%Y-%m-%d")]
    out: Dict = {"available": True, "signal_date": sig.strftime("%Y-%m-%d")}
    ok = True
    for s in SLEEVES:
        mine = set(picks_by_sig[sig].get(s, []))
        theirs = set(live[live["sleeve"] == s]["code"].astype(str))
        out[f"n_{s}"] = {"mine": len(mine), "live": len(theirs)}
        only_mine = sorted(mine - theirs)
        only_theirs = sorted(theirs - mine)
        out[f"only_mine_{s}"] = only_mine
        out[f"only_live_{s}"] = only_theirs
        if only_mine or only_theirs:
            ok = False
    # target weights vs live target.csv
    tp = run_dir / "target.csv"
    if tp.exists():
        t = pd.read_csv(tp)
        live_w = {str(r["code"]): float(r["final_w"]) for _, r in t.iterrows()}
        keys = set(live_w) | set(w_by_sig[sig])
        maxdiff = max(abs(live_w.get(k, 0.0) - w_by_sig[sig].get(k, 0.0)) for k in keys)
        out["target_max_abs_diff"] = float(maxdiff)
        if maxdiff > 1e-9:
            ok = False
    out["match"] = ok
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("== 1) production data load (cache only) ==")
    close, volume, index_close, regime, feats, frgn_feats, val, meta, name_map, sector_map, _frgn = load_market()
    close.index = pd.to_datetime(close.index)
    open_px = pd.read_parquet(ROOT / "data" / "us" / "us_open_panel.parquet")
    open_px.index = pd.to_datetime(open_px.index)
    open_px = open_px.reindex(columns=close.columns)
    print(f"  universe={close.shape[1]} prices {close.index.min().date()}~{close.index.max().date()}")

    me = [d for d in month_ends(close.index)
          if pd.Timestamp(SIGNAL_START) <= d <= pd.Timestamp(SIGNAL_END)]
    print(f"== 2) signals: {len(me)} months  {me[0].date()}..{me[-1].date()} ==")

    print("== 3) production targets per month ==")
    picks_by_sig, w_by_sig, reg_by_sig = build_signal_targets(
        feats, frgn_feats, val, regime, close, volume, me
    )

    print("== 4) next-open simulation (10bp base) ==")
    base = simulate(picks_by_sig, close, open_px, COST)
    logs_list = base["logs"]
    logs = pd.DataFrame(logs_list)

    spy = index_close.reindex(base["equity"].index).ffill()
    b_rets = spy.pct_change().fillna(0.0)
    spy_eq = (1 + b_rets).cumprod() * SEED

    eq_cut = base["equity"][base["equity"].index <= pd.Timestamp(REPORT_END)]
    b_rets_cut = b_rets[b_rets.index <= pd.Timestamp(REPORT_END)]
    spy_eq_cut = spy_eq[spy_eq.index <= pd.Timestamp(REPORT_END)]

    st = perf(eq_cut, base["returns"].reindex(eq_cut.index).dropna(), b_rets_cut, "STRAT_2025_2026")
    bs = perf(spy_eq_cut, b_rets_cut, b_rets_cut, "SPY_2025_2026")

    mr_s_full = monthly_returns(base["equity"])   # 2025-01 .. 2026-08(partial)
    mr_b_full = monthly_returns(spy_eq)
    mr_s = mr_s_full[mr_s_full.index <= pd.Timestamp(REPORT_END)]  # through 2026-07
    mr_b = mr_b_full[mr_b_full.index <= pd.Timestamp(REPORT_END)]
    boot = bootstrap_excess(mr_s, mr_b)

    print(f"  strat total={st['total_return']:.2%} cagr={st['cagr']:.2%} "
          f"sharpe={st['sharpe']} mdd={st['mdd']:.2%} IR={st['info_ratio']} alpha={st['alpha']:.2%}")
    print(f"  SPY   total={bs['total_return']:.2%} cagr={bs['cagr']:.2%} mdd={bs['mdd']:.2%}")
    print(f"  monthly hit={st['win_month']} boot P(excess>0)={boot.get('prob_positive')}")

    print("== 5) sensitivity runs ==")
    variants: Dict[str, Dict] = {
        "base_10bp": base,
        "cost_0bp": simulate(picks_by_sig, close, open_px, 0.0),
        "cost_20bp": simulate(picks_by_sig, close, open_px, COST_STRESS),
        "signal_close_10bp": simulate(picks_by_sig, close, open_px, COST, exec_rule="signal_close"),
    }
    # sleeve attribution (single-sleeve full-budget portfolios, same exec protocol)
    sleeve_picks = {s: {d: {s: picks_by_sig[d].get(s, [])} for d in picks_by_sig} for s in SLEEVES}
    for s in SLEEVES:
        variants[f"sleeve_{s}"] = simulate(
            sleeve_picks[s], close, open_px, COST,
            sleeve_weights={s: 1.0},
        )

    print("== 6) universe sensitivity (top_n 100 / 125 / 150) ==")
    uni_stats = {}
    for tn in (100, 125, 150):
        cl2, vol2, idx2, reg2, ft2, fr2, val2, meta2, nm2, sec2, _f2 = load_market(top_n=tn)
        cl2.index = pd.to_datetime(cl2.index)
        op2 = pd.read_parquet(ROOT / "data" / "us" / "us_open_panel.parquet")
        op2.index = pd.to_datetime(op2.index)
        op2 = op2.reindex(columns=cl2.columns)
        me2 = [d for d in month_ends(cl2.index)
               if pd.Timestamp(SIGNAL_START) <= d <= pd.Timestamp(SIGNAL_END)]
        p2, w2, r2 = build_signal_targets(ft2, fr2, val2, reg2, cl2, vol2, me2)
        res2 = simulate(p2, cl2, op2, COST)
        eq2 = res2["equity"][res2["equity"].index <= pd.Timestamp(REPORT_END)]
        b2 = index_close.reindex(eq2.index).ffill().pct_change().fillna(0.0)
        st2 = perf(eq2, res2["returns"].reindex(eq2.index).dropna(), b2, f"top{tn}")
        uni_stats[tn] = {"cagr": st2["cagr"], "mdd": st2["mdd"], "sharpe": st2["sharpe"],
                         "total": st2["total_return"]}
        print(f"  top_n={tn}: cagr={st2['cagr']:.2%} mdd={st2['mdd']:.2%} sharpe={st2['sharpe']}")

    print("== 7) validation vs live ops runs ==")
    validation = {}
    for sig in (pd.Timestamp("2026-06-30"), pd.Timestamp("2026-07-31")):
        v = validate_against_live(picks_by_sig, w_by_sig, sig)
        validation[sig.strftime("%Y-%m-%d")] = v
        print(f"  {sig.date()}: match={v.get('match')} "
              f"target_diff={v.get('target_max_abs_diff')} "
              f"leader={v.get('n_leader')} mom63={v.get('n_mom63')} lowvol={v.get('n_lowvol')}")
        if not v.get("match"):
            for s in SLEEVES:
                om = v.get(f"only_mine_{s}", []) or []
                ol = v.get(f"only_live_{s}", []) or []
                if om or ol:
                    print(f"    {s}: only_mine={om} only_live={ol}")

    # regime share on signal dates
    reg_share = pd.Series([reg_by_sig[d] for d in me]).value_counts(normalize=True).to_dict()

    # monthly table: row j = holding month j, signal[j] drives it (1:1; last row = 2026-08 partial)
    n_row = len(mr_s_full)
    mt = pd.DataFrame({
        "month": [m.strftime("%Y-%m") for m in mr_s_full.index],
        "signal": [me[i].strftime("%Y-%m-%d") for i in range(n_row)],
        "exec": [logs_list[i]["exec_date"] for i in range(n_row)],
        "regime": [reg_by_sig[me[i]] for i in range(n_row)],
        "n_leader": [logs_list[i]["n_leader"] for i in range(n_row)],
        "n_mom63": [logs_list[i]["n_mom63"] for i in range(n_row)],
        "n_lowvol": [logs_list[i]["n_lowvol"] for i in range(n_row)],
        "n_names": [logs_list[i]["n_names"] for i in range(n_row)],
        "weight_sum": [logs_list[i]["weight_sum"] for i in range(n_row)],
        "turnover": [logs_list[i]["turnover"] for i in range(n_row)],
        "strat_ret": [float(mr_s_full.loc[m]) for m in mr_s_full.index],
        "spy_ret": [float(mr_b_full.loc[m]) for m in mr_b_full.index],
        "excess": [float(mr_s_full.loc[m] - mr_b_full.loc[m]) for m in mr_s_full.index],
        "equity_end": [float(base["equity"][base["equity"].index <= m].iloc[-1]) for m in mr_s_full.index],
        "spy_end": [float(spy_eq[spy_eq.index <= m].iloc[-1]) for m in mr_b_full.index],
    })
    mt = mt.set_index("month")

    # persistence (name overlap between consecutive targets)
    ov = []
    prev = set()
    for d in me:
        cur = set(w_by_sig[d])
        ov.append(len(prev & cur) / max(len(prev | cur), 1) if prev else float("nan"))
        prev = cur

    # sector concentration per month (best-effort sector map)
    sec_w_max = []
    for d in me:
        wm: Dict[str, float] = {}
        for c, w in w_by_sig[d].items():
            s = sector_map.get(c, "UNKNOWN")
            wm[s] = wm.get(s, 0.0) + w
        sec_w_max.append(max(wm.values(), default=0.0))

    # variant stats summary (all variants, same report cut)
    var_stats = {}
    for k, v in variants.items():
        eqv = v["equity"][v["equity"].index <= pd.Timestamp(REPORT_END)]
        rv = v["returns"].reindex(eqv.index).dropna()
        pv = perf(eqv, rv, b_rets_cut, k)
        var_stats[k] = {kk: pv[kk] for kk in
                        ("cagr", "total_return", "sharpe", "mdd", "info_ratio", "alpha", "vol")}

    diag = {
        "window": {"signals": f"{me[0].date()}..{me[-1].date()}",
                   "report_end": REPORT_END,
                   "n_months": int(len(me))},
        "stats": st,
        "bench": bs,
        "bootstrap_monthly_excess": boot,
        "monthly_returns": {str(k.date()): {"strat": float(mr_s.loc[k]), "spy": float(mr_b.loc[k])}
                            for k in mr_s.index},
        "turnover": {"mean": float(logs["turnover"].mean()), "max": float(logs["turnover"].max())},
        "cost_drag_bps_ann": float(logs["cost_paid_bps"].sum() / max((me[-1] - me[0]).days / 365.25, 1e-9)),
        "avg_n_names": float(logs["n_names"].mean()),
        "avg_n_by_sleeve": {s: float(logs[f"n_{s}"].mean()) for s in SLEEVES},
        "empty_sleeve_months": int((logs[["n_leader", "n_mom63", "n_lowvol"]] == 0).any(axis=1).sum()),
        "regime_share_signal_dates": {str(k): round(float(v), 3) for k, v in reg_share.items()},
        "persistence_mean_overlap": round(float(np.nanmean(ov)), 3),
        "max_sector_w_mean": round(float(np.mean(sec_w_max)), 3),
        "exec_drops_total": int(logs["exec_drops"].sum()),
        "sensitivity": {
            "lookahead_close_vs_nextopen_cagr_diff": round(
                float(var_stats["signal_close_10bp"]["cagr"]) - st["cagr"], 4),
        },
        "universe_sensitivity": {str(k): v for k, v in uni_stats.items()},
        "validation_vs_live_ops": validation,
        "variant_stats": var_stats,
        "policy": {
            "name": POLICY_NAME,
            "weights": {k: v for k, v in SLEEVE_WEIGHTS.items()},
            "cost_bps": int(round(COST * 1e4)),
            "exec": "NEXT_OPEN",
            "max_name": MAX_NAME,
            "n": {"leader": N_LEADER, "mom63": N_MOM63, "lowvol": N_LOWVOL},
        },
    }

    # data artifacts
    eq_out = pd.DataFrame({"STRAT": base["equity"], "SPY": spy_eq})
    eq_out.to_csv(OUT / "equity.csv")
    logs.to_csv(OUT / "rebalance_log.csv", index=False)
    mt.reset_index().to_csv(OUT / "monthly_table.csv", index=False)
    mr_out = pd.DataFrame({"strat_ret": mr_s, "spy_ret": mr_b, "excess": mr_s - mr_b})
    mr_out.to_csv(OUT / "monthly_returns.csv")
    with open(OUT / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2, default=str)

    print("\n==== SUMMARY ====")
    print(f"window: {me[0].date()} signal -> {me[-1].date()} signal, report through {REPORT_END}")
    print(f"STRAT: total={st['total_return']:.2%} cagr={st['cagr']:.2%} sharpe={st['sharpe']} "
          f"mdd={st['mdd']:.2%} win_m={st['win_month']} IR={st['info_ratio']} alpha={st['alpha']:.2%} "
          f"beta={st['beta']} vol={st['vol']:.2%}")
    print(f"SPY:   total={bs['total_return']:.2%} cagr={bs['cagr']:.2%} mdd={bs['mdd']:.2%}")
    print(f"bootstrap: ann_excess={boot.get('obs_ann_excess')} t={boot.get('t_stat')} "
          f"P>0={boot.get('prob_positive')} 90%CI=[{boot.get('boot_p5')},{boot.get('boot_p95')}]")
    print(f"turnover mean={logs['turnover'].mean():.3f} max={logs['turnover'].max():.3f} "
          f"cost_drag_bps_ann={diag['cost_drag_bps_ann']:.1f}")
    print("variants (cagr / mdd):")
    for k, v in var_stats.items():
        print(f"  {k:20s} {v['cagr']:.2%} / {v['mdd']:.2%}  sharpe={v['sharpe']}")
    print("universe sensitivity:", {k: (f"{v['cagr']:.2%}", f"{v['mdd']:.2%}") for k, v in uni_stats.items()})
    print("validation:", {k: vv.get("match") for k, vv in validation.items()})
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
