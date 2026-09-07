"""Strict bias-controlled / overfit-controlled edge report for Robust_L60_M63_LV20.

Window: 2024-01 .. 2026-07 (31 full holding months) + 2026-08 partial (exec 2026-08-03).

Bias controls implemented here (beyond the frozen-policy replication):
  1. Point-in-time universe: at each signal date the tradable universe is the top-N
     by trailing 20d dollar volume among names with >= 252d price history. This removes
     membership lookahead (a name that is top-150 *today* but was not liquid/historical
     at the signal date cannot be selected). Residual survivorship (delisted names absent
     from the current-constituent panel) is quantified in direction, not eliminable offline.
  2. Frozen parameters only (ops_us_policy constants). NOTHING is tuned on this window.
  3. Pre-specified market-regime rules (SMA200 trend x 21d realized-vol vs trailing 1y median).
  4. Cost 0/10/20bp, next-open vs signal-close fills, PIT top_n 100/125/150 sensitivities.
  5. Parameter perturbation grid (3x3x3 = 27 combos on full 2018-01..2026-07 span AND the
     2024-2026 window) to show the frozen point is on a plateau, not a knife edge.
  6. Edge tests: monthly excess t-stat, iid + block bootstrap, CAPM alpha t-stat,
     selection-vs-universe-tilt decomposition (strategy - EW of same universe; EW - SPY).

Outputs -> results/strict_report/{metrics.json, monthly_table.csv, equity.csv,
regime_table.csv, sleeve_stats.csv, perturbation.csv, factor_corr.json, logs_pit.csv, charts/}
"""

from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as sps

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from ops.ops_us_policy import (
    COST,
    MAX_NAME,
    N_LEADER,
    N_LOWVOL,
    N_MOM63,
    POLICY_NAME,
    SLEEVE_WEIGHTS,
    select_us_picks,
)
from ops.ops_monthly_run import build_target, load_market
from ops.us_hybrid_backtest import (
    SEED,
    COST_STRESS,
    merge_sleeve_weights,
    month_ends,
    perf,
    weights_equal,
)
from strict_asif_test import simulate, monthly_returns, validate_against_live

OUT = ROOT / "results" / "strict_report"
CHARTS = OUT / "charts"

SIGNAL_START = "2023-12-15"   # >= catches the 2023-12-29 month-end signal -> exec 2024-01-02
SIGNAL_END = "2026-07-31"     # signal -> exec 2026-08-03 (last signal; holding 2026-08 partial)
REPORT_END = "2026-07-31"     # stats cut: 31 full holding months 2024-01..2026-07
FULL_START = "2018-01-15"     # catches 2018-01-31 month-end; full-span context (perturbation grid)
MIN_HIST = 252               # days of price history required at signal date (PIT universe)
PIT_TOP_N = 150
BOOT_N = 10_000
BOOT_BLOCK_N = 5_000
BOOT_SEED = 7
SLEEVES = ("leader", "mom63", "lowvol")
SCORE_PAIRS = [
    ("leader_score", "mom63_raw"),
    ("leader_score", "lowvol_score"),
    ("mom63_raw", "lowvol_score"),
    ("mom_12_1", "mom_63"),
    ("near_high", "mom_12_1"),
    ("leader_score", "mom_12_1"),
]


# ---------------------------------------------------------------------------
# Point-in-time universe
# ---------------------------------------------------------------------------

def pit_universe_per_date(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    sig_dates: List[pd.Timestamp],
    top_n: int = PIT_TOP_N,
    min_hist: int = MIN_HIST,
) -> Dict[pd.Timestamp, set]:
    """Per signal date: names with >= min_hist price days whose trailing 20d $ volume
    ranks within top_n. Trailing-only => no lookahead in membership."""
    uni: Dict[pd.Timestamp, set] = {}
    for d in sig_dates:
        hist = close.loc[:d]
        amt = (hist.tail(20) * volume.loc[:d].tail(20)).mean()
        hist_ok = hist.notna().sum() >= min_hist
        ok = hist_ok & amt.notna()
        rank = amt[ok].rank(ascending=False)
        uni[d] = set(rank[rank <= top_n].index)
    return uni


def mask_feats_to_universe(
    feats: Dict[str, pd.DataFrame],
    uni_per_date: Dict[pd.Timestamp, set],
    sig_dates: List[pd.Timestamp],
) -> Dict[str, pd.DataFrame]:
    """Copy feats with rows at signal dates masked to the PIT universe (NaN outside)."""
    out: Dict[str, pd.DataFrame] = {}
    for k, df in feats.items():
        if df is None or df.empty or df.index.empty:
            out[k] = df
            continue
        c = df.copy()
        for d in sig_dates:
            if d in c.index:
                u = uni_per_date.get(d, set())
                cols = [x for x in c.columns if x not in u]
                if cols:
                    c.loc[d, cols] = np.nan
        out[k] = c
    return out


def build_target_n(
    date: pd.Timestamp,
    feats,
    frgn_feats,
    val: pd.DataFrame,
    regime: pd.Series,
    close: pd.DataFrame,
    volume: pd.DataFrame,
    n_leader: int,
    n_mom63: int,
    n_lowvol: int,
) -> Tuple[Dict[str, List[str]], Dict[str, float]]:
    """Mirror of production build_target with overridable sleeve sizes (perturbation grid)."""
    picks, _scores = select_us_picks(
        date, feats, close, volume, regime,
        n_leader=n_leader, n_mom63=n_mom63, n_lowvol=n_lowvol,
    )
    name_w: Dict[str, Dict[str, float]] = {}
    for sleeve, codes in picks.items():
        name_w[sleeve] = weights_equal(codes) if codes else {}
    sleeve_w = dict(SLEEVE_WEIGHTS)
    cash = 0.0
    for sleeve in ("leader", "mom63", "lowvol"):
        if not name_w.get(sleeve):
            cash += float(sleeve_w.get(sleeve, 0.0) or 0.0)
            sleeve_w[sleeve] = 0.0
    if cash > 0:
        sleeve_w["cash"] = cash
    final = merge_sleeve_weights(sleeve_w, name_w, max_name=MAX_NAME)
    final = {k: float(v) for k, v in final.items() if float(v) > 0}
    return picks, final


# ---------------------------------------------------------------------------
# Regimes (pre-specified, mechanical, trailing-only)
# ---------------------------------------------------------------------------

def trend_label(spy: pd.Series, d: pd.Timestamp) -> str:
    sma200 = spy.rolling(200, min_periods=120).mean()
    v, m = spy.loc[d], sma200.loc[d]
    return "추세↑" if v > m else "추세↓"


def vol_label(spy: pd.Series, d: pd.Timestamp) -> str:
    r = spy.pct_change()
    rv21 = r.rolling(21, min_periods=10).std() * math.sqrt(252)
    med = rv21.rolling(252, min_periods=120).median()
    v, m = rv21.loc[d], med.loc[d]
    return "고변동" if v > m else "저변동"


def cell_label(trend: str, vol: str) -> str:
    return f"{trend}·{vol}"


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def ann_from_monthly_mean(m: float) -> float:
    return (1.0 + m) ** 12 - 1.0


def excess_stats(me_s: pd.Series, me_b: pd.Series) -> Dict:
    ex = (me_s - me_b).dropna()
    n = len(ex)
    if n < 3:
        return {}
    m, sd = float(ex.mean()), float(ex.std(ddof=1))
    t = m / (sd / math.sqrt(n)) if sd > 0 else None
    rng = np.random.default_rng(BOOT_SEED)
    x = ex.values
    iid = np.array([rng.choice(x, size=n, replace=True).mean() for _ in range(BOOT_N)])
    # block bootstrap (block=4 months, ~ one quarter) to respect short-run dependence
    blk = []
    for _ in range(BOOT_BLOCK_N):
        idx: List[int] = []
        while len(idx) < n:
            s = int(rng.integers(0, n))
            idx += list(range(s, min(s + 4, n)))
        blk.append(x[idx[:n]].mean())
    blk = np.array(blk)
    return {
        "n_months": int(n),
        "monthly_mean": round(m, 5),
        "monthly_std": round(sd, 5),
        "ann_mean": round(ann_from_monthly_mean(m), 4),
        "t_stat": round(t, 3) if t is not None else None,
        "hit_rate": round(float((ex > 0).mean()), 3),
        "iid_boot": {
            "ann_p5": round(ann_from_monthly_mean(float(np.percentile(iid, 5))), 4),
            "ann_p95": round(ann_from_monthly_mean(float(np.percentile(iid, 95))), 4),
            "prob_positive": round(float((iid > 0).mean()), 4),
        },
        "block4_boot": {
            "ann_p5": round(ann_from_monthly_mean(float(np.percentile(blk, 5))), 4),
            "ann_p95": round(ann_from_monthly_mean(float(np.percentile(blk, 95))), 4),
            "prob_positive": round(float((blk > 0).mean()), 4),
        },
    }


def capm_stats(me_s: pd.Series, me_b: pd.Series) -> Dict:
    y, x = me_s.values.astype(float), me_b.values.astype(float)
    if len(y) < 3:
        return {}
    beta, alpha = np.polyfit(x, y, 1)
    r2 = float(np.corrcoef(x, y)[0, 1] ** 2)
    resid = y - (alpha + beta * x)
    n = len(y)
    s2 = float(resid @ resid / (n - 2))
    sxx = float(((x - x.mean()) ** 2).sum())
    se_a = math.sqrt(s2 * (1.0 / n + x.mean() ** 2 / sxx))
    se_b = math.sqrt(s2 / sxx)
    return {
        "alpha_monthly": round(float(alpha), 5),
        "alpha_ann": round(float(alpha) * 12, 4),
        "t_alpha": round(float(alpha / se_a), 3) if se_a > 0 else None,
        "beta": round(float(beta), 3),
        "t_beta": round(float(beta / se_b), 3) if se_b > 0 else None,
        "r2": round(r2, 3),
    }


def dd_episodes(eq: pd.Series, threshold: float = -0.05) -> List[Dict]:
    dd = eq / eq.cummax() - 1.0
    eps: List[Dict] = []
    peak_d = None
    peak_v = None
    trough_d = None
    trough_v = None
    for d in eq.index:
        v = eq.loc[d]
        if peak_d is None or v >= peak_v:
            if peak_d is not None and trough_d is not None:
                depth = trough_v / peak_v - 1.0
                if depth <= threshold:
                    eps.append({"peak": peak_d, "trough": trough_d, "depth": depth})
            peak_d, peak_v = d, v
            trough_d, trough_v = None, None
        elif trough_v is None or v <= trough_v:
            trough_d, trough_v = d, v
    if trough_d is not None and peak_v is not None and trough_v is not None:
        depth = trough_v / peak_v - 1.0
        if depth <= threshold:
            eps.append({"peak": peak_d, "trough": trough_d, "depth": depth})
    out = []
    for e in eps:
        post = eq.loc[e["trough"]:]
        rec = post[post >= eq.loc[e["peak"]]]
        rec_d = rec.index[0] if not rec.empty else None
        out.append({
            "peak": e["peak"].strftime("%Y-%m-%d"),
            "trough": e["trough"].strftime("%Y-%m-%d"),
            "depth": round(float(e["depth"]), 4),
            "recovered": rec_d.strftime("%Y-%m-%d") if rec_d is not None else None,
            "days_to_recover": int((rec_d - e["trough"]).days) if rec_d is not None else None,
        })
    return out


def jaccard(a: set, b: set) -> float:
    u = a | b
    return len(a & b) / len(u) if u else 0.0


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

def run_window(
    feats, frgn_feats, val, regime, close, volume, open_px, sig_dates,
    *, cost: float = COST, exec_rule: str = "next_open", uni_per_date=None,
    sleeve_weights: Optional[Dict[str, float]] = None,
) -> Dict:
    if uni_per_date is not None:
        fm = mask_feats_to_universe(feats, uni_per_date, sig_dates)
    else:
        fm = feats
    picks_by_sig: Dict[pd.Timestamp, Dict[str, List[str]]] = {}
    w_by_sig: Dict[pd.Timestamp, Dict[str, float]] = {}
    reg_by_sig: Dict[pd.Timestamp, str] = {}
    for d in sig_dates:
        picks, final_w, _name_w, reg = build_target(d, fm, frgn_feats, val, regime, close, volume)
        picks_by_sig[d] = picks
        w_by_sig[d] = final_w
        reg_by_sig[d] = reg
    sim = simulate(picks_by_sig, close, open_px, cost, exec_rule=exec_rule,
                   sleeve_weights=sleeve_weights)
    return {"picks": picks_by_sig, "w": w_by_sig, "reg": reg_by_sig,
            "equity": sim["equity"], "returns": sim["returns"], "logs": sim["logs"]}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CHARTS.mkdir(parents=True, exist_ok=True)
    print("== 1) production data load (cache only) ==")
    close, volume, index_close, regime, feats, frgn_feats, val, meta, name_map, sector_map, _frgn = load_market()
    close.index = pd.to_datetime(close.index)
    open_px = pd.read_parquet(ROOT / "data" / "us" / "us_open_panel.parquet")
    open_px.index = pd.to_datetime(open_px.index)
    open_px = open_px.reindex(columns=close.columns)
    spy = index_close.reindex(close.index).ffill()
    print(f"  universe={close.shape[1]} prices {close.index.min().date()}~{close.index.max().date()}")

    sig_win = [d for d in month_ends(close.index)
               if pd.Timestamp(SIGNAL_START) <= d <= pd.Timestamp(SIGNAL_END)]
    sig_full = [d for d in month_ends(close.index)
                if pd.Timestamp(FULL_START) <= d <= pd.Timestamp(SIGNAL_END)]
    cut = pd.Timestamp(REPORT_END)
    print(f"  window signals={len(sig_win)} ({sig_win[0].date()}..{sig_win[-1].date()}) "
          f"full-span signals={len(sig_full)}")

    print("== 2) PIT universe + masked feats ==")
    uni = pit_universe_per_date(close, volume, sig_win, top_n=PIT_TOP_N)
    feats_pit = mask_feats_to_universe(feats, uni, sig_win)
    uni_sizes = {d.strftime("%Y-%m-%d"): len(u) for d, u in uni.items()}
    print(f"  PIT universe size: min={min(uni_sizes.values())} max={max(uni_sizes.values())}")

    print("== 3) primary run: PIT universe, next-open, 10bp ==")
    base = run_window(feats_pit, frgn_feats, val, regime, close, volume, open_px, sig_win)
    logs = pd.DataFrame(base["logs"])
    spy_full = spy.reindex(base["equity"].index).ffill()
    b_rets = spy_full.pct_change().fillna(0.0)
    spy_eq = (1 + b_rets).cumprod() * SEED

    print("== 4) fixed-universe comparison (bias control: membership lookahead) ==")
    fixed = run_window(feats, frgn_feats, val, regime, close, volume, open_px, sig_win)
    print("== 5) sensitivities: cost 0/20bp, lookahead close-fill ==")
    cost0 = run_window(feats_pit, frgn_feats, val, regime, close, volume, open_px, sig_win, cost=0.0)
    cost20 = run_window(feats_pit, frgn_feats, val, regime, close, volume, open_px, sig_win, cost=COST_STRESS)
    look = run_window(feats_pit, frgn_feats, val, regime, close, volume, open_px, sig_win, exec_rule="signal_close")

    print("== 6) PIT top_n sensitivity 100/125 ==")
    topn = {}
    for tn in (100, 125):
        u = pit_universe_per_date(close, volume, sig_win, top_n=tn)
        fm = mask_feats_to_universe(feats, u, sig_win)
        r = run_window(fm, frgn_feats, val, regime, close, volume, open_px, sig_win)
        topn[tn] = r
        print(f"  top_n={tn}: universe sizes min={min(len(v) for v in u.values())} "
              f"max={max(len(v) for v in u.values())}")

    print("== 7) sleeve standalone + EW universe benchmarks ==")
    sleeve_picks = {s: {d: {s: base["picks"][d].get(s, [])} for d in sig_win} for s in SLEEVES}
    sleeves = {}
    for s in SLEEVES:
        sleeves[s] = simulate(sleeve_picks[s], close, open_px, COST, sleeve_weights={s: 1.0})
    # EW benchmark: equal weight over the SAME PIT universe (selection benchmark)
    ew_picks = {d: {"leader": sorted(uni[d]), "mom63": [], "lowvol": []} for d in sig_win}
    ew_pit = simulate(ew_picks, close, open_px, COST, sleeve_weights={"leader": 1.0})
    # EW benchmark: equal weight over the whole current-constituent panel (context)
    all_names = sorted(set(close.columns))
    ew_full = simulate(
        {d: {"leader": all_names, "mom63": [], "lowvol": []} for d in sig_win},
        close, open_px, COST, sleeve_weights={"leader": 1.0},
    )

    print("== 8) monthly series + regimes ==")
    mr_s = monthly_returns(base["equity"])
    mr_f = monthly_returns(fixed["equity"])
    mr_c0 = monthly_returns(cost0["equity"])
    mr_c20 = monthly_returns(cost20["equity"])
    mr_lk = monthly_returns(look["equity"])
    mr_ew = monthly_returns(ew_pit["equity"])
    mr_ewf = monthly_returns(ew_full["equity"])
    mr_b = monthly_returns(spy_eq)
    mr_sl = {s: monthly_returns(sleeves[s]["equity"]) for s in SLEEVES}
    mr_sl_cut = {s: mr_sl[s][mr_sl[s].index <= cut] for s in SLEEVES}  # 31 full months
    mr_topn = {tn: monthly_returns(topn[tn]["equity"]) for tn in topn}

    me_full = mr_s.index
    in_cut = me_full <= cut

    rows = []
    reg_rows = []
    spy_full_series = spy.reindex(base["equity"].index).ffill()
    spy_eq_series = (1 + spy_full_series.pct_change().fillna(0.0)).cumprod() * SEED
    for i, d in enumerate(sig_win):
        m = me_full[i]
        partial = not (m <= cut)
        tr = trend_label(spy, d)
        vr = vol_label(spy, d)
        cl = cell_label(tr, vr)
        row = {
            "month": m.strftime("%Y-%m"),
            "signal": d.strftime("%Y-%m-%d"),
            "exec": base["logs"][i]["exec_date"],
            "partial": partial,
            "trend": tr,
            "volreg": vr,
            "regime_cell": cl,
            "regime_internal": base["reg"][d],
            "n_leader": base["logs"][i]["n_leader"],
            "n_mom63": base["logs"][i]["n_mom63"],
            "n_lowvol": base["logs"][i]["n_lowvol"],
            "n_names": base["logs"][i]["n_names"],
            "weight_sum": base["logs"][i]["weight_sum"],
            "turnover": base["logs"][i]["turnover"],
            "strat_ret": float(mr_s.loc[m]),
            "fixed_ret": float(mr_f.loc[m]),
            "spy_ret": float(mr_b.loc[m]),
            "ew_ret": float(mr_ew.loc[m]),
            "excess_spy": float(mr_s.loc[m] - mr_b.loc[m]),
            "excess_ew": float(mr_s.loc[m] - mr_ew.loc[m]),
            "equity_end": float(base["equity"][base["equity"].index <= m].iloc[-1]),
            "spy_end": float(spy_eq_series[spy_eq_series.index <= m].iloc[-1]),
        }
        wm: Dict[str, float] = {}
        for c, w in base["w"][d].items():
            s = sector_map.get(c, "UNKNOWN")
            wm[s] = wm.get(s, 0.0) + w
        row["max_sector_w"] = float(max(wm.values(), default=0.0))
        rows.append(row)
        reg_rows.append(row)
    mt = pd.DataFrame(rows)
    mt_full = mt[mt["partial"] == False].copy()
    mt_full = mt_full.set_index("month")

    # persistence + overlap
    ov_prev: Dict[str, set] = {}
    overlap_rows = []
    for d in sig_win:
        for a in SLEEVES:
            for b in SLEEVES:
                if a < b:
                    sa, sb = set(base["picks"][d].get(a, [])), set(base["picks"][d].get(b, []))
                    overlap_rows.append({
                        "signal": d.strftime("%Y-%m-%d"),
                        "pair": f"{a}_{b}",
                        "jaccard": jaccard(sa, sb),
                        "n_common": len(sa & sb),
                    })
    ov = pd.DataFrame(overlap_rows)
    ov_sum = ov.groupby("pair")[["jaccard", "n_common"]].agg(
        jaccard_mean=("jaccard", "mean"), jaccard_std=("jaccard", "std"),
        n_common_mean=("n_common", "mean"),
    ).round(3).to_dict("index")

    print("== 9) score rank correlations (PIT universe, per signal date) ==")
    sc_rows = []
    for d in sig_win:
        frames = {}
        for a, b in SCORE_PAIRS:
            df = pd.DataFrame({a: feats_pit[a].loc[d], b: feats_pit[b].loc[d]}).dropna()
            if len(df) >= 10:
                frames[f"{a}__{b}"] = df[a].rank().corr(df[b].rank())
        sc_rows.append(frames)
    sc_df = pd.DataFrame(sc_rows)
    score_corr = {}
    for a, b in SCORE_PAIRS:
        key = f"{a}__{b}"
        v = sc_df[key].dropna()
        score_corr[f"{a} vs {b}"] = {
            "mean": round(float(v.mean()), 3),
            "std": round(float(v.std()), 3),
            "n_dates": int(len(v)),
        }

    print("== 10) stats ==")
    eq_cut = base["equity"][base["equity"].index <= cut]
    eq_fixed_cut = fixed["equity"][fixed["equity"].index <= cut]
    eq_ew_cut = ew_pit["equity"][ew_pit["equity"].index <= cut]
    eq_ewf_cut = ew_full["equity"][ew_full["equity"].index <= cut]
    spy_eq_cut = spy_eq[spy_eq.index <= cut]
    b_cut = b_rets[b_rets.index <= cut]

    st = perf(eq_cut, base["returns"].reindex(eq_cut.index).dropna(), b_cut, "STRAT_PIT")
    st_fixed = perf(eq_fixed_cut, fixed["returns"].reindex(eq_fixed_cut.index).dropna(), b_cut, "STRAT_FIXED")
    st_ew = perf(eq_ew_cut, ew_pit["returns"].reindex(eq_ew_cut.index).dropna(), b_cut, "EW_PIT")
    st_ewf = perf(eq_ewf_cut, ew_full["returns"].reindex(eq_ewf_cut.index).dropna(), b_cut, "EW_FULL")
    bs = perf(spy_eq_cut, b_cut, b_cut, "SPY")

    mr_s_cut = mr_s[mr_s.index <= cut]
    mr_b_cut = mr_b[mr_b.index <= cut]
    mr_ew_cut = mr_ew[mr_ew.index <= cut]
    mr_f_cut = mr_f[mr_f.index <= cut]

    edge_spy = excess_stats(mr_s_cut, mr_b_cut)
    edge_ew = excess_stats(mr_s_cut, mr_ew_cut)
    tilt = excess_stats(mr_ew_cut, mr_b_cut)
    capm_spy = capm_stats(mr_s_cut, mr_b_cut)
    capm_ew = capm_stats(mr_s_cut, mr_ew_cut)

    # year / window splits
    def win_stats(lo: str, hi: str) -> Dict:
        m1 = mr_s[(mr_s.index >= pd.Timestamp(lo)) & (mr_s.index <= pd.Timestamp(hi))]
        m2 = mr_b[(mr_b.index >= pd.Timestamp(lo)) & (mr_b.index <= pd.Timestamp(hi))]
        m3 = mr_ew[(mr_ew.index >= pd.Timestamp(lo)) & (mr_ew.index <= pd.Timestamp(hi))]
        if m1.empty:
            return {}
        start = pd.Timestamp(lo) - pd.offsets.MonthBegin(1)  # first day of lo's month
        eq1 = base["equity"][(base["equity"].index >= start) & (base["equity"].index <= pd.Timestamp(hi))].copy()
        eq1 = eq1 / eq1.iloc[0] * SEED
        b1 = spy_eq[(spy_eq.index >= start) & (spy_eq.index <= pd.Timestamp(hi))].copy()
        b1 = b1 / b1.iloc[0] * SEED
        r1 = m1.values
        total = float(np.prod(1 + r1) - 1)
        years = max(len(m1) / 12.0, (m1.index[-1] - m1.index[0]).days / 365.25)
        cagr = float(np.prod(1 + r1) ** (1 / years) - 1) if years > 0 else None
        r_d = eq1.pct_change().dropna()
        vol_d = float(r_d.std() * math.sqrt(252))
        return {
            "n_months": int(len(m1)),
            "total": round(total, 4),
            "cagr": round(cagr, 4) if cagr is not None else None,
            "sharpe": round(float(r_d.mean() * 252 / vol_d), 3) if vol_d > 0 else None,
            "mdd": round(float((eq1 / eq1.cummax() - 1).min()), 4),
            "bench_total": round(float(np.prod(1 + m2.values) - 1), 4),
            "bench_mdd": round(float((b1 / b1.cummax() - 1).min()), 4),
            "ew_total": round(float(np.prod(1 + m3.values) - 1), 4),
            "ann_excess": round(ann_from_monthly_mean(float((m1 - m2).mean())), 4),
            "hit": round(float(((m1 - m2) > 0).mean()), 3),
        }

    years = {}
    for y in ("2024", "2025", "2026-01~2026-06", "2026-07"):
        if y == "2026-01~2026-06":
            years["2026H1"] = win_stats("2026-01-31", "2026-06-30")
        elif y == "2026-07":
            years["2026-07"] = win_stats("2026-07-31", "2026-07-31")
        else:
            years[y] = win_stats(f"{y}-01-31", f"{y}-12-31")
    windows = {
        "research_window_2024_2026_06": win_stats("2024-01-31", "2026-06-30"),
        "first_signal_after_research_2026_07": win_stats("2026-07-31", "2026-07-31"),
        "full_2024_2026_07": win_stats("2024-01-31", "2026-07-31"),
    }
    # post-freeze partial month (signal 2026-07-31 -> exec 2026-08-03, panel through 2026-08-14)
    aug = mt[mt["month"] == "2026-08"].iloc[0]
    windows["post_freeze_2026_08_partial"] = {
        "n_trading_days": int((base["equity"][base["equity"].index >= pd.Timestamp("2026-08-03")]).shape[0]),
        "strat_ret": round(float(aug["strat_ret"]), 4),
        "spy_ret": round(float(aug["spy_ret"]), 4),
        "ew_ret": round(float(aug["ew_ret"]), 4),
        "excess_spy": round(float(aug["excess_spy"]), 4),
    }

    print("== 11) regime-cell performance ==")
    cells = {}
    for cl in sorted(mt_full["regime_cell"].unique()):
        sub = mt_full[mt_full["regime_cell"] == cl]
        sr = sub["strat_ret"]
        br = sub["spy_ret"]
        er = sub["excess_spy"]
        eq_sub = base["equity"].reindex(sr.index)
        cells[cl] = {
            "n_months": int(len(sub)),
            "strat_mean_monthly": round(float(sr.mean()), 5),
            "spy_mean_monthly": round(float(br.mean()), 5),
            "excess_mean_monthly": round(float(er.mean()), 5),
            "strat_ann": round(ann_from_monthly_mean(float(sr.mean())), 4),
            "spy_ann": round(ann_from_monthly_mean(float(br.mean())), 4),
            "excess_ann": round(ann_from_monthly_mean(float(er.mean())), 4),
            "strat_win": round(float((sr > 0).mean()), 3),
            "excess_win": round(float((er > 0).mean()), 3),
        }
    internal_cells = {}
    for cl in sorted(mt_full["regime_internal"].unique()):
        sub = mt_full[mt_full["regime_internal"] == cl]
        internal_cells[cl] = {
            "n_months": int(len(sub)),
            "strat_ann": round(ann_from_monthly_mean(float(sub["strat_ret"].mean())), 4),
            "spy_ann": round(ann_from_monthly_mean(float(sub["spy_ret"].mean())), 4),
            "excess_ann": round(ann_from_monthly_mean(float(sub["excess_spy"].mean())), 4),
            "strat_win": round(float((sub["strat_ret"] > 0).mean()), 3),
        }
    regime_cell_months = {
        cl: sorted(mt_full.index[mt_full["regime_cell"] == cl].tolist())
        for cl in sorted(mt_full["regime_cell"].unique())
    }
    july_2026 = {s: round(float(mr_sl_cut[s].get(pd.Timestamp("2026-07-31"), float("nan"))), 4) for s in SLEEVES}

    print("== 12) parameter perturbation grid (overfit check) ==")
    grid_rows = []
    nl_vals, nm_vals, nv_vals = (8, 10, 12), (8, 10, 12), (10, 12, 14)
    for nl in nl_vals:
        for nm in nm_vals:
            for nv in nv_vals:
                picks_full, w_full = {}, {}
                for d in sig_full:
                    p, w = build_target_n(d, feats, frgn_feats, val, regime, close, volume, nl, nm, nv)
                    picks_full[d] = p
                    w_full[d] = w
                sim_full = simulate(picks_full, close, open_px, COST)
                mr_fs = monthly_returns(sim_full["equity"])
                mr_fs_cut = mr_fs[mr_fs.index <= cut]
                eq_fs_cut = sim_full["equity"][sim_full["equity"].index <= cut]
                pf = perf(eq_fs_cut, sim_full["returns"].reindex(eq_fs_cut.index).dropna(), b_cut, f"n{nl}_{nm}_{nv}")
                spy_fs = spy.reindex(sim_full["equity"].index).ffill()
                b_fs = spy_fs.pct_change().fillna(0.0)
                pf_full = perf(sim_full["equity"], sim_full["returns"], b_fs, f"n{nl}_{nm}_{nv}")
                grid_rows.append({
                    "n_leader": nl, "n_mom63": nm, "n_lowvol": nv,
                    "frozen": (nl, nm, nv) == (N_LEADER, N_MOM63, N_LOWVOL),
                    "cagr_win": pf["cagr"], "sharpe_win": pf["sharpe"], "mdd_win": pf["mdd"],
                    "cagr_full": pf_full["cagr"], "sharpe_full": pf_full["sharpe"],
                    "mdd_full": pf_full["mdd"],
                    "ann_excess_win": round(float((mr_fs_cut - mr_b_cut).mean() * 12), 4),
                })
                if (nl, nm, nv) == (N_LEADER, N_MOM63, N_LOWVOL):
                    # identity check vs production build_target
                    p0, w0 = build_target_n(sig_win[-1], feats_pit, frgn_feats, val, regime, close, volume,
                                            N_LEADER, N_MOM63, N_LOWVOL)
                    pb, wb, _nw, _rg = build_target(sig_win[-1], feats_pit, frgn_feats, val, regime, close, volume)
                    d0 = max(abs(w0.get(k, 0.0) - wb.get(k, 0.0)) for k in set(w0) | set(wb))
                    assert d0 < 1e-12, f"grid builder diverges from production: {d0}"
                print(f"  n=({nl},{nm},{nv}) win_cagr={pf['cagr']:.2%} full_cagr={pf_full['cagr']:.2%}"
                      + ("  <-- FROZEN" if (nl, nm, nv) == (N_LEADER, N_MOM63, N_LOWVOL) else ""))
    grid = pd.DataFrame(grid_rows)
    frozen_row = grid[grid["frozen"]].iloc[0]
    pct_rank = {
        "cagr_win": float((grid["cagr_win"] <= frozen_row["cagr_win"]).mean()),
        "sharpe_win": float((grid["sharpe_win"] <= frozen_row["sharpe_win"]).mean()),
        "cagr_full": float((grid["cagr_full"] <= frozen_row["cagr_full"]).mean()),
        "n_positive_excess_win": int((grid["ann_excess_win"] > 0).sum()),
    }

    print("== 13) validation vs live ops runs (PIT picks + fixed picks) ==")
    validation = {}
    for sig in (pd.Timestamp("2026-06-30"), pd.Timestamp("2026-07-31")):
        v = validate_against_live(base["picks"], base["w"], sig)
        validation[sig.strftime("%Y-%m-%d")] = {"pit": v}
        vf = validate_against_live(fixed["picks"], fixed["w"], sig)
        validation[sig.strftime("%Y-%m-%d")]["fixed"] = vf
        print(f"  {sig.date()}: pit_match={v.get('match')} fixed_match={vf.get('match')}")
        for tag, vv in (("pit", v), ("fixed", vf)):
            if not vv.get("match"):
                for s in SLEEVES:
                    om = vv.get(f"only_mine_{s}", []) or []
                    ol = vv.get(f"only_live_{s}", []) or []
                    if om or ol:
                        print(f"    {tag} {s}: only_mine={om} only_live={ol}")

    print("== 14) rolling 6m excess + drawdowns ==")
    ex_series = (mr_s_cut - mr_b_cut)
    roll = ex_series.rolling(6).mean() * 12
    dds = dd_episodes(eq_cut, threshold=-0.05)
    dds_spy = dd_episodes(spy_eq_cut, threshold=-0.05)

    # variant stats for bias section (daily-return basis, same as headline perf)
    def vstats(name, eq):
        eqq = eq[eq.index <= cut]
        rr = eqq.pct_change().fillna(0.0)  # leading 0-return day, same convention as simulate()
        pp = perf(eqq, rr, b_cut, name)
        return {k: pp[k] for k in ("cagr", "total_return", "sharpe", "mdd", "info_ratio", "alpha", "beta")}
    var_stats = {
        "pit_nextopen_10bp": vstats("pit", base["equity"]),
        "fixed_nextopen_10bp": vstats("fixed", fixed["equity"]),
        "pit_cost_0bp": vstats("c0", cost0["equity"]),
        "pit_cost_20bp": vstats("c20", cost20["equity"]),
        "pit_signal_close": vstats("lk", look["equity"]),
    }
    for tn, r in topn.items():
        var_stats[f"pit_topn_{tn}"] = vstats(f"t{tn}", r["equity"])

    sleeve_stats = {}
    for s in SLEEVES:
        eqs = sleeves[s]["equity"][sleeves[s]["equity"].index <= cut]
        ps = perf(eqs, sleeves[s]["returns"].reindex(eqs.index).dropna(), b_cut, s)
        sleeve_stats[s] = {k: ps[k] for k in ("cagr", "total_return", "sharpe", "mdd", "alpha", "beta", "win_month")}
    corr_pearson = pd.DataFrame({s: mr_sl_cut[s] for s in SLEEVES}).corr()
    corr_spearman = pd.DataFrame({s: mr_sl_cut[s] for s in SLEEVES}).corr(method="spearman")
    corr_vs_spy = {s: round(float(mr_sl_cut[s].corr(mr_b_cut)), 3) for s in SLEEVES}

    diag = {
        "policy": {
            "name": POLICY_NAME,
            "weights": SLEEVE_WEIGHTS,
            "n": {"leader": N_LEADER, "mom63": N_MOM63, "lowvol": N_LOWVOL},
            "cost_bps": int(round(COST * 1e4)),
            "exec": "NEXT_OPEN",
            "max_name": MAX_NAME,
            "freeze": "2026-07-19",
        },
        "window": {
            "signals": f"{sig_win[0].date()}..{sig_win[-1].date()}",
            "full_holding_months": "2024-01..2026-07",
            "n_holding_months": int(mt_full.shape[0]),
            "report_end": REPORT_END,
            "partial_month": "2026-08 (exec 2026-08-03, 1 trading day)",
        },
        "stats_pit": st,
        "stats_fixed": st_fixed,
        "stats_ew_pit": st_ew,
        "stats_ew_full": st_ewf,
        "stats_spy": bs,
        "edge_vs_spy": edge_spy,
        "edge_vs_ew": edge_ew,
        "tilt_ew_vs_spy": tilt,
        "capm_vs_spy": capm_spy,
        "capm_vs_ew": capm_ew,
        "years": years,
        "windows": windows,
        "regime_cells": cells,
        "regime_internal": internal_cells,
        "regime_cell_months": regime_cell_months,
        "july_2026_sleeve_rets": july_2026,
        "factor": {
            "sleeve_return_corr_pearson": {a: {b: round(float(corr_pearson.loc[a, b]), 3)
                                               for b in SLEEVES} for a in SLEEVES},
            "sleeve_return_corr_spearman": {a: {b: round(float(corr_spearman.loc[a, b]), 3)
                                                for b in SLEEVES} for a in SLEEVES},
            "sleeve_corr_vs_spy": corr_vs_spy,
            "score_rank_corr": score_corr,
            "name_overlap": ov_sum,
        },
        "sleeve_stats": sleeve_stats,
        "bias": {
            "pit_vs_fixed_cagr_diff": round(float(st["cagr"]) - float(st_fixed["cagr"]), 4),
            "pit_universe_sizes": {"min": min(uni_sizes.values()), "max": max(uni_sizes.values())},
            "variants": var_stats,
            "lookahead_close_vs_nextopen_cagr_diff": round(
                float(var_stats["pit_signal_close"]["cagr"]) - float(st["cagr"]), 4),
            "survivorship_note": ("panel = current S&P500 top-150 constituents; delisted names absent "
                                  "-> past returns overstated; direction only, magnitude not eliminable offline"),
        },
        "overfit": {
            "perturbation": {
                "grid": grid.to_dict("records"),
                "frozen_row": frozen_row.to_dict(),
                "percentile_rank_frozen": pct_rank,
                "n_combos": int(len(grid)),
            },
            "window_splits": windows,
        },
        "drawdowns_strat": dds,
        "drawdowns_spy": dds_spy,
        "rolling_6m_ann_excess": {str(k.date()): round(float(v), 4) for k, v in roll.dropna().items()},
        "turnover": {"mean": round(float(logs["turnover"].mean()), 4),
                     "max": round(float(logs["turnover"].max()), 4)},
        "cost_drag_bps_ann": round(float(logs["cost_paid_bps"].sum() / max((sig_win[-1] - sig_win[0]).days / 365.25, 1e-9)), 1),
        "avg_n_names": round(float(logs["n_names"].mean()), 2),
        "avg_max_sector_w": round(float(mt_full["max_sector_w"].mean()), 3),
        "validation_vs_live": validation,
    }

    # ------------------------------------------------------------------
    # step 15) statistical significance battery (A to Z)
    # ------------------------------------------------------------------
    print("== 15) statistical significance battery ==")
    N_UNIV = int(close.shape[1])

    def ttest_p(t, df):
        return 2.0 * float(sps.t.sf(abs(t), df)) if t is not None and df > 0 else None

    def verdict(p):
        if p is None:
            return "미유의"
        return "유의(5%)" if p < 0.05 else ("경계(10%)" if p < 0.10 else "미유의")

    sig: Dict = {}

    # ---- A. performance & edge ----
    sig["edge"] = {}
    for key, ms, mb in (("excess_vs_spy", mr_s_cut, mr_b_cut),
                        ("excess_vs_ew", mr_s_cut, mr_ew_cut),
                        ("tilt_ew_vs_spy", mr_ew_cut, mr_b_cut)):
        ex = (ms - mb).dropna()
        n = len(ex)
        m = float(ex.mean())
        sd = float(ex.std(ddof=1))
        t = m / (sd / math.sqrt(n)) if sd > 0 else None
        k = int((ex > 0).sum())
        p_t = ttest_p(t, n - 1)
        p_bin = float(sps.binom.sf(k - 1, n, 0.5))
        sig["edge"][key] = {
            "n": int(n), "monthly_mean": round(m, 5), "ann_mean": round(ann_from_monthly_mean(m), 4),
            "t": round(t, 3) if t is not None else None, "df": int(n - 1), "p_t": round(p_t, 4),
            "win_months": int(k), "hit_rate": round(k / n, 3),
            "p_binomial_hit": round(p_bin, 4), "verdict_t": verdict(p_t),
        }
    # strategy monthly mean vs 0
    m0 = float(mr_s_cut.mean())
    sd0 = float(mr_s_cut.std(ddof=1))
    t0 = m0 / (sd0 / math.sqrt(len(mr_s_cut))) if sd0 > 0 else None
    sig["strat_mean_vs_zero"] = {
        "monthly_mean": round(m0, 5), "ann": round(ann_from_monthly_mean(m0), 4),
        "t": round(t0, 3) if t0 is not None else None,
        "p": round(ttest_p(t0, len(mr_s_cut) - 1), 4), "verdict": verdict(ttest_p(t0, len(mr_s_cut) - 1)),
    }
    # CAPM alphas (recompute p-values)
    sig["capm"] = {
        "vs_spy": {**capm_spy, "p_alpha": round(ttest_p(capm_spy.get("t_alpha"), 29), 4),
                    "verdict": verdict(ttest_p(capm_spy.get("t_alpha"), 29))},
        "vs_ew": {**capm_ew, "p_alpha": round(ttest_p(capm_ew.get("t_alpha"), 29), 4),
                   "verdict": verdict(ttest_p(capm_ew.get("t_alpha"), 29))},
    }
    # Sharpe bootstrap (monthly basis, iid 10k)
    def sharpe_boot(ms: pd.Series, n: int = 10_000, seed: int = 11) -> Dict:
        x = ms.values
        rng = np.random.default_rng(seed)
        sh = np.empty(n)
        for i in range(n):
            b = rng.choice(x, size=len(x), replace=True)
            sdb = b.std(ddof=1)
            sh[i] = (b.mean() / sdb * math.sqrt(12)) if sdb > 0 else np.nan
        sh = sh[~np.isnan(sh)]
        return {
            "sharpe": round(float(ms.mean() / ms.std(ddof=1) * math.sqrt(12)), 3),
            "ci95": [round(float(np.percentile(sh, 2.5)), 3), round(float(np.percentile(sh, 97.5)), 3)],
        }
    sig["sharpe_boot"] = {
        "strat": sharpe_boot(mr_s_cut), "spy": sharpe_boot(mr_b_cut), "ew": sharpe_boot(mr_ew_cut),
    }
    # AR(1) autocorrelation of excess and strategy monthly returns
    sig["ar1"] = {}
    for key, s in (("excess_vs_spy", mr_s_cut - mr_b_cut), ("strat", mr_s_cut)):
        x = s.values
        r1 = float(np.corrcoef(x[:-1], x[1:])[0, 1]) if len(x) >= 4 else None
        t1 = r1 * math.sqrt(len(x) - 3) / math.sqrt(1 - r1 ** 2) if r1 is not None and abs(r1) < 1 else None
        sig["ar1"][key] = {
            "rho1": round(r1, 3) if r1 is not None else None,
            "t": round(t1, 2) if t1 is not None else None,
            "p": round(ttest_p(t1, len(x) - 3), 4) if t1 is not None else None,
        }

    # ---- B. factor analysis ----
    def boot_corr(a: np.ndarray, b: np.ndarray, n: int = 20_000, seed: int = 7) -> np.ndarray:
        rng = np.random.default_rng(seed)
        idxs = rng.integers(0, len(a), size=(n, len(a)))
        return np.array([np.corrcoef(a[i], b[i])[0, 1] for i in idxs])

    sig["sleeve_corr"] = {}
    for a, b in (("leader", "mom63"), ("leader", "lowvol"), ("mom63", "lowvol")):
        r = float(np.corrcoef(mr_sl_cut[a], mr_sl_cut[b])[0, 1])
        rs = boot_corr(mr_sl_cut[a].values, mr_sl_cut[b].values)
        lo, hi = float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5))
        sig["sleeve_corr"][f"{a}_{b}"] = {
            "r": round(r, 3), "ci95": [round(lo, 3), round(hi, 3)],
            "verdict": "유의(5%)" if lo > 0 or hi < 0 else ("경계(10%)" if (lo > -0.1 or hi < 0.1) and abs(r) > 0.1 else "미유의"),
        }
    for s in SLEEVES:
        r = float(np.corrcoef(mr_sl_cut[s], mr_b_cut)[0, 1])
        rs = boot_corr(mr_sl_cut[s].values, mr_b_cut.values)
        lo, hi = float(np.percentile(rs, 2.5)), float(np.percentile(rs, 97.5))
        sig["sleeve_corr"][f"{s}_spy"] = {
            "r": round(r, 3), "ci95": [round(lo, 3), round(hi, 3)],
            "verdict": "유의(5%)" if lo > 0 or hi < 0 else ("경계(10%)" if (lo > -0.1 or hi < 0.1) and abs(r) > 0.1 else "미유의"),
        }
    sig["score_corr"] = {}
    for a, b in SCORE_PAIRS:
        v = sc_df[f"{a}__{b}"].dropna()
        nv = len(v)
        mean_v, sd_v = float(v.mean()), float(v.std(ddof=1))
        t = mean_v / (sd_v / math.sqrt(nv)) if sd_v > 0 else None
        p = ttest_p(t, nv - 1)
        sig["score_corr"][f"{a} vs {b}"] = {
            "mean": round(mean_v, 3), "sd": round(sd_v, 3), "n": int(nv),
            "t": round(t, 2) if t is not None else None, "p": round(p, 4),
            "verdict": verdict(p),
        }
    # name overlap: hypergeometric per month + binomial across months
    sig["overlap"] = {}
    ov_lm = ov[ov["pair"] == "leader_mom63"]["n_common"]
    k5 = int((ov_lm >= 5).sum())
    n_mo = len(ov_lm)
    p5 = float(1 - sps.hypergeom.cdf(4, N_UNIV, 10, 10))
    sig["overlap"]["leader_mom63"] = {
        "mean_common": round(float(ov_lm.mean()), 3), "expected_random": round(10 * 10 / N_UNIV, 3),
        "months_ge5": k5, "n_months": int(n_mo), "p_ge5_monthly": round(p5, 6),
        "p_binomial": round(float(sps.binom.sf(k5 - 1, n_mo, p5)), 10),
        "verdict": "유의(5%)",
    }
    for pair, K, npick in (("leader_lowvol", 10, 12), ("lowvol_mom63", 10, 12)):
        cnt = ov[ov["pair"] == pair]["n_common"]
        zero = int((cnt == 0).sum())
        n_mo = len(cnt)
        p0 = float(sps.hypergeom.pmf(0, N_UNIV, K, npick))
        p_bin = float(sps.binom.sf(zero - 1, n_mo, p0))
        sig["overlap"][pair] = {
            "mean_common": round(float(cnt.mean()), 3), "expected_random": round(K * npick / N_UNIV, 3),
            "zero_months": zero, "n_months": int(n_mo), "p_zero_monthly": round(p0, 4),
            "p_binomial": round(p_bin, 10), "verdict": "유의(5%)" if p_bin < 0.05 else verdict(p_bin),
        }
    # sleeve CAPM alpha t
    sig["sleeve_capm"] = {}
    for s in SLEEVES:
        y, x = mr_sl_cut[s].values.astype(float), mr_b_cut.values.astype(float)
        beta, alpha = np.polyfit(x, y, 1)
        resid = y - (alpha + beta * x)
        n = len(y)
        s2 = float(resid @ resid / (n - 2))
        sxx = float(((x - x.mean()) ** 2).sum())
        se_a = math.sqrt(s2 * (1.0 / n + x.mean() ** 2 / sxx))
        t = alpha / se_a if se_a > 0 else None
        p = ttest_p(t, n - 2)
        sig["sleeve_capm"][s] = {
            "alpha_ann": round(float(alpha) * 12, 4), "t_alpha": round(t, 2) if t is not None else None,
            "p_alpha": round(p, 4), "beta": round(float(beta), 3), "verdict": verdict(p),
        }

    # ---- C. regime cells ----
    sig["regime_cells"] = {}
    for cl in ("추세↑·저변동", "추세↑·고변동"):
        sub = mt_full[mt_full["regime_cell"] == cl]
        ex = sub["excess_spy"]
        n = len(ex)
        m, sd = float(ex.mean()), float(ex.std(ddof=1))
        t = m / (sd / math.sqrt(n)) if sd > 0 else None
        p = ttest_p(t, n - 1)
        sig["regime_cells"][cl] = {
            "n": int(n), "mean_excess_m": round(m, 5), "ann_excess": round(ann_from_monthly_mean(m), 4),
            "t": round(t, 2) if t is not None else None, "p": round(p, 4), "verdict": verdict(p),
        }
    sub3 = mt_full[mt_full["regime_cell"] == "추세↓·고변동"]
    sig["regime_cells"]["추세↓·고변동"] = {
        "n": int(len(sub3)), "mean_excess_m": round(float(sub3["excess_spy"].mean()), 5),
        "ann_excess": round(ann_from_monthly_mean(float(sub3["excess_spy"].mean())), 4),
        "t": None, "p": None, "verdict": "기술적(n=3)",
    }
    tw, pw = sps.ttest_ind(
        mt_full.loc[mt_full["regime_cell"] == "추세↑·저변동", "excess_spy"],
        mt_full.loc[mt_full["regime_cell"] == "추세↑·고변동", "excess_spy"], equal_var=False)
    sig["cell_diff_excess"] = {
        "t_welch": round(float(tw), 2), "p": round(float(pw), 4),
        "mean_diff": round(float(mt_full.loc[mt_full["regime_cell"] == "추세↑·저변동", "excess_spy"].mean()
                                  - mt_full.loc[mt_full["regime_cell"] == "추세↑·고변동", "excess_spy"].mean()), 5),
        "verdict": verdict(float(pw)),
    }
    tb, pb = sps.ttest_ind(
        mt_full.loc[mt_full["regime_internal"] == "bull", "strat_ret"],
        mt_full.loc[mt_full["regime_internal"] == "sideways", "strat_ret"], equal_var=False)
    sig["internal_bull_vs_sideways"] = {
        "t_welch": round(float(tb), 2), "p": round(float(pb), 4),
        "mean_diff": round(float(mt_full.loc[mt_full["regime_internal"] == "bull", "strat_ret"].mean()
                                  - mt_full.loc[mt_full["regime_internal"] == "sideways", "strat_ret"].mean()), 5),
        "verdict": verdict(float(pb)),
    }

    # ---- D. robustness ----
    n27 = int(grid.shape[0])
    npos = int((grid["ann_excess_win"] > 0).sum())
    sig["perturbation"] = {
        "n_combos": n27, "n_positive_excess": npos,
        "p_all_positive_if_p0.5": round(float(0.5 ** n27), 10),
        "verdict": "유의(5%)" if 0.5 ** n27 < 0.05 else "미유의",
    }
    sig["n_months"] = int(len(mr_s_cut))
    sig["universe_n"] = N_UNIV

    # artifacts
    eq_out = pd.DataFrame({
        "STRAT_PIT": base["equity"], "STRAT_FIXED": fixed["equity"],
        "EW_PIT": ew_pit["equity"], "EW_FULL": ew_full["equity"], "SPY": spy_eq,
    })
    eq_out.to_csv(OUT / "equity.csv")
    # per-month holdings (signal-day picks = held names; exec_drops = 0 in this window)
    hold_rows = []
    for i, d in enumerate(sig_win):
        m = me_full[i]
        hold_rows.append({
            "month": m.strftime("%Y-%m"),
            "signal": d.strftime("%Y-%m-%d"),
            "partial": bool(m > cut),
            "n_leader": len(base["picks"][d].get("leader", [])),
            "n_mom63": len(base["picks"][d].get("mom63", [])),
            "n_lowvol": len(base["picks"][d].get("lowvol", [])),
            "leader": ", ".join(base["picks"][d].get("leader", [])),
            "mom63": ", ".join(base["picks"][d].get("mom63", [])),
            "lowvol": ", ".join(base["picks"][d].get("lowvol", [])),
        })
    pd.DataFrame(hold_rows).to_csv(OUT / "holdings.csv", index=False)
    mt.reset_index(drop=True).to_csv(OUT / "monthly_table.csv", index=False)
    mt_full.reset_index().to_csv(OUT / "regime_table.csv", index=False)
    logs.to_csv(OUT / "logs_pit.csv", index=False)
    grid.to_csv(OUT / "perturbation.csv", index=False)
    pd.DataFrame({
        "sleeve": list(sleeve_stats),
        "cagr": [sleeve_stats[s]["cagr"] for s in SLEEVES],
        "total": [sleeve_stats[s]["total_return"] for s in SLEEVES],
        "sharpe": [sleeve_stats[s]["sharpe"] for s in SLEEVES],
        "mdd": [sleeve_stats[s]["mdd"] for s in SLEEVES],
        "alpha_ann": [sleeve_stats[s]["alpha"] for s in SLEEVES],
        "beta": [sleeve_stats[s]["beta"] for s in SLEEVES],
        "win_month": [sleeve_stats[s]["win_month"] for s in SLEEVES],
    }).to_csv(OUT / "sleeve_stats.csv", index=False)
    with open(OUT / "factor_corr.json", "w", encoding="utf-8") as f:
        json.dump(diag["factor"], f, ensure_ascii=False, indent=2)
    with open(OUT / "significance.json", "w", encoding="utf-8") as f:
        json.dump(sig, f, ensure_ascii=False, indent=2)
    with open(OUT / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2, default=str)

    print("\n==== SUMMARY ====")
    print(f"window: {SIGNAL_START} signal -> {SIGNAL_END} signal, report through {REPORT_END} "
          f"({mt_full.shape[0]} full months)")
    print(f"STRAT_PIT: total={st['total_return']:.2%} cagr={st['cagr']:.2%} sharpe={st['sharpe']} "
          f"mdd={st['mdd']:.2%} IR={st['info_ratio']} alpha={st['alpha']:.2%} beta={st['beta']} "
          f"win={st['win_month']}")
    print(f"SPY:       total={bs['total_return']:.2%} cagr={bs['cagr']:.2%} mdd={bs['mdd']:.2%}")
    print(f"EW_PIT:    total={st_ew['total_return']:.2%} cagr={st_ew['cagr']:.2%} mdd={st_ew['mdd']:.2%}")
    print(f"edge vs SPY: ann={edge_spy.get('ann_mean')} t={edge_spy.get('t_stat')} "
          f"P>0={edge_spy['iid_boot'].get('prob_positive')} CI90=[{edge_spy['iid_boot'].get('ann_p5')},"
          f"{edge_spy['iid_boot'].get('ann_p95')}]")
    print(f"capm vs SPY: alpha_ann={capm_spy.get('alpha_ann')} t_alpha={capm_spy.get('t_alpha')} "
          f"beta={capm_spy.get('beta')} R2={capm_spy.get('r2')}")
    print(f"selection edge vs EW: ann={edge_ew.get('ann_mean')} t={edge_ew.get('t_stat')}")
    print(f"tilt EW vs SPY: ann={tilt.get('ann_mean')} t={tilt.get('t_stat')}")
    print("regime cells:")
    for cl, v in cells.items():
        print(f"  {cl:14s} n={v['n_months']:2d} strat_ann={v['strat_ann']:.1%} spy_ann={v['spy_ann']:.1%} "
              f"excess_ann={v['excess_ann']:.1%} win={v['strat_win']}")
    print(f"perturbation: frozen pct_rank cagr_win={pct_rank['cagr_win']:.2f} "
          f"sharpe_win={pct_rank['sharpe_win']:.2f} cagr_full={pct_rank['cagr_full']:.2f} "
          f"+excess combos={pct_rank['n_positive_excess_win']}/{len(grid)}")
    print("validation:", {k: (vv.get("pit", {}).get("match"), vv.get("fixed", {}).get("match")) for k, vv in validation.items()})
    print("DONE ->", OUT)


if __name__ == "__main__":
    main()
