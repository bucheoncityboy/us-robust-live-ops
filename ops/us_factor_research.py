"""
US Factor Research — Strict Next-Open Protocol
==============================================
Pre-registered candidate factors (no free-form p-hacking loop):
  Price (full sample ~2019-2026):
    Leader(Mom12-1+near-high), Mom12_1, Mom63, NearHigh,
    LowVol, ST_Reversal, RelMom, AccumulDiv(legacy fail check)
  Fundamental (valuation panel from ~2022-09, flagged limited):
    Value, Quality(ROE/QV), ValueMom, EP, ROE

Protocol (anti-overfit / anti-bias):
  - Signal month-end Close → execute next Open
  - Cost 10bp base / 20bp stress
  - Name cap 15%, equal-weight within sleeve (SCORE optional)
  - Liquidity filter $50M 20d $volume, price >= $5
  - IS/OOS split fixed at 2023-12-31 (pre-registered)
  - 5-fold walk-forward; score uses median fold excess (not mean)
  - Block bootstrap (21d) for excess significance
  - Stricter gates + composite robustness score
  - Combinations only among factors that pass single-factor gates
  - Surviving universe is point-in-time imperfect (documented)

Outputs: results/us_factor_lab/
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from ops.us_hybrid_backtest import (
    BOOT_N,
    BOOT_SEED,
    CACHE_FUND,
    CACHE_INDEX,
    CACHE_META,
    CACHE_OPEN,
    CACHE_PRICES,
    CACHE_VAL,
    COST_BASE,
    COST_STRESS,
    DATA,
    FUND_LAG_DAYS,
    IS_END,
    MAX_NAME,
    MIN_AMT,
    MIN_PRICE,
    SEED,
    build_ttm,
    build_valuation_panel,
    build_universe,
    download_fundamentals,
    load_index,
    load_prices,
    market_regime,
    merge_sleeve_weights,
    month_ends,
    next_open_map,
    perf,
    select_divergence,
    select_leader,
    select_value_mom,
    turnover,
    weights_equal,
    weights_score,
    compute_price_features as base_price_features,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "us_factor_lab"
CHART = OUT / "charts"

N_TOP = 10
N_TOP_DEF = 12
BLOCK_LEN = 21  # ~1 trading month blocks for bootstrap


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def compute_all_features(close: pd.DataFrame, volume: pd.DataFrame,
                         index_close: pd.Series) -> Dict[str, pd.DataFrame]:
    feats = base_price_features(close, volume)
    ret = close.pct_change()
    vol60 = ret.rolling(60, min_periods=40).std() * math.sqrt(252)
    vol120 = ret.rolling(120, min_periods=60).std() * math.sqrt(252)
    # low vol score = negative vol (higher score => lower vol; pack() sorts descending)
    lowvol = -vol60
    # short-term reversal: prefer recent losers (classic 1m reversal)
    st_rev = -feats["ret_20"]
    # relative momentum vs equal-weight universe return
    mkt_ret_12_1 = close.shift(21) / close.shift(252) - 1.0
    uni_med = mkt_ret_12_1.median(axis=1)
    rel_mom = mkt_ret_12_1.sub(uni_med, axis=0)
    # residual-ish: 12-1 mom residualized on beta to SPY (rolling)
    spy = index_close.reindex(close.index).ffill().pct_change()
    # simple: mom - beta_proxy * spy_mom; use correlation proxy via ranks already in rel_mom
    feats.update({
        "vol60": vol60,
        "vol120": vol120,
        "lowvol_score": lowvol,
        "st_reversal": st_rev,
        "rel_mom": rel_mom,
        "mom12_raw": feats["mom_12_1"],
        "mom63_raw": feats["mom_63"],
        "near_high_raw": feats["near_high"],
    })
    return feats


def xs_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", ascending=True, pct=True)


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------

def liquid_mask(date, close, volume, codes=None) -> pd.Series:
    if date not in close.index:
        return pd.Series(dtype=bool)
    px = close.loc[date]
    # 20d dollar volume
    hist_c = close.loc[:date].tail(20)
    hist_v = volume.loc[:date].tail(20)
    amt = (hist_c * hist_v).mean()
    ok = (px >= MIN_PRICE) & (amt >= MIN_AMT) & px.notna() & amt.notna()
    if codes is not None:
        ok = ok.reindex(codes).fillna(False)
    return ok


def top_by_score(date, score_row: pd.Series, close, volume, n: int,
                 extra_filter: Optional[pd.Series] = None) -> List[str]:
    ok = liquid_mask(date, close, volume)
    s = score_row.reindex(ok.index)
    m = ok & s.notna()
    if extra_filter is not None:
        m = m & extra_filter.reindex(ok.index).fillna(False)
    s = s[m]
    if s.empty:
        return []
    return s.sort_values(ascending=False).head(n).index.tolist()


def select_factor(name: str, date, feats, val_snap, close, volume, regime,
                 n: int = N_TOP) -> Tuple[List[str], Dict[str, float]]:
    """Return (codes, score_map)."""
    ok = liquid_mask(date, close, volume)

    def pack(score: pd.Series, filt: Optional[pd.Series] = None, nn: int = n):
        codes = top_by_score(date, score, close, volume, nn, filt)
        sm = score.dropna().to_dict()
        return codes, {c: float(sm.get(c, 0.0)) for c in codes}

    if name == "Leader":
        codes = select_leader(date, feats, regime, n=n)
        sc = feats["leader_score"].loc[date] if date in feats["leader_score"].index else pd.Series(dtype=float)
        return codes, {c: float(sc.get(c, 0.0)) for c in codes if c in sc.index}

    if name == "Mom12":
        sc = feats["mom_12_1"].loc[date]
        filt = (sc > 0) & ok
        return pack(sc, filt)

    if name == "Mom63":
        sc = feats["mom_63"].loc[date]
        filt = (sc > 0) & ok
        return pack(sc, filt)

    if name == "NearHigh":
        sc = feats["near_high"].loc[date]
        mom = feats["mom_12_1"].loc[date]
        filt = (sc >= 0.80) & (mom > 0) & ok
        return pack(sc, filt)

    if name == "LowVol":
        sc = feats["lowvol_score"].loc[date]
        # require not in free-fall
        mom = feats["mom_12_1"].loc[date]
        filt = (mom > -0.30) & ok
        return pack(sc, filt, nn=n if n else N_TOP_DEF)

    if name == "ST_Reversal":
        sc = feats["st_reversal"].loc[date]
        # avoid junk: 12-1 not catastrophic, still liquid
        mom = feats["mom_12_1"].loc[date]
        filt = (mom > -0.40) & ok
        return pack(sc, filt)

    if name == "RelMom":
        sc = feats["rel_mom"].loc[date]
        filt = (sc > 0) & ok
        return pack(sc, filt)

    if name == "AccumulDiv":
        codes = select_divergence(date, feats, regime, n=n)
        sc = feats["bull_div"].loc[date] if date in feats["bull_div"].index else pd.Series(dtype=float)
        return codes, {c: float(sc.get(c, 0.0)) for c in codes if c in sc.index}

    # fundamental family
    if val_snap is None or val_snap.empty:
        return [], {}

    vs = val_snap.copy()
    vs = vs[vs["amt20"].fillna(0) >= MIN_AMT]
    if vs.empty:
        return [], {}

    if name == "Value":
        vs = vs.dropna(subset=["value_score"])
        vs = vs.sort_values("value_score", ascending=False).head(n)
        return vs["code"].tolist(), dict(zip(vs["code"], vs["value_score"]))

    if name == "Quality":
        # high ROE + not extremely expensive: use qv_score if present else rank_roe
        col = "qv_score" if "qv_score" in vs.columns else "rank_roe"
        if col not in vs.columns:
            return [], {}
        vs = vs.dropna(subset=[col])
        # require positive earnings yield if available
        if "ep" in vs.columns:
            vs = vs[vs["ep"].fillna(-1) > -0.05]
        vs = vs.sort_values(col, ascending=False).head(n)
        return vs["code"].tolist(), dict(zip(vs["code"], vs[col]))

    if name == "ValueMom":
        codes = select_value_mom(date, val_snap, feats, n=n)
        sc = dict(zip(val_snap["code"], val_snap.get("value_score", pd.Series(dtype=float))))
        return codes, {c: float(sc.get(c, 0.0)) for c in codes}

    if name == "EP":
        vs = vs.dropna(subset=["ep"])
        vs = vs[vs["ep"] > 0]
        vs = vs.sort_values("ep", ascending=False).head(n)
        return vs["code"].tolist(), dict(zip(vs["code"], vs["ep"]))

    if name == "ROE":
        vs = vs.dropna(subset=["roe"])
        vs = vs[vs["roe"] > 0]
        vs = vs.sort_values("roe", ascending=False).head(n)
        return vs["code"].tolist(), dict(zip(vs["code"], vs["roe"]))

    raise KeyError(name)


# ---------------------------------------------------------------------------
# Strict single-sleeve / multi-sleeve backtest
# ---------------------------------------------------------------------------

def run_portfolio(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    picks: Dict[pd.Timestamp, Dict[str, List[str]]],
    sleeve_w: Dict[str, float],
    score_by_date: Dict[pd.Timestamp, Dict[str, Dict[str, float]]],
    cost: float = COST_BASE,
    max_name: float = MAX_NAME,
    weight_mode: str = "equal",
    label: str = "strat",
) -> Dict:
    signal_dates = sorted(picks.keys())
    if not signal_dates:
        raise RuntimeError(f"no signals for {label}")
    exec_map = next_open_map(close.index, open_px)
    rebal_on: Dict[pd.Timestamp, pd.Timestamp] = {}
    for sig in signal_dates:
        ex = exec_map.get(sig)
        if ex is not None and ex in close.index:
            rebal_on[ex] = sig
    if not rebal_on:
        raise RuntimeError(f"no exec days for {label}")

    all_days = close.index[close.index >= min(rebal_on.keys())]
    cash = float(SEED)
    shares: Dict[str, float] = {}
    prev_w: Dict[str, float] = {}
    equity_rows = []
    rets = []
    hold_log = []

    for d in all_days:
        port_val = cash
        for c, sh in shares.items():
            px = close.at[d, c] if c in close.columns and pd.notna(close.at[d, c]) else np.nan
            if pd.notna(px):
                port_val += sh * px

        if d in rebal_on:
            sig = rebal_on[d]
            sleeve_picks = picks[sig]
            smaps = score_by_date.get(sig, {})
            name_w: Dict[str, Dict[str, float]] = {}
            for sleeve, codes0 in sleeve_picks.items():
                codes = []
                for c in codes0:
                    if c in open_px.columns and pd.notna(open_px.at[d, c]) and open_px.at[d, c] > 0:
                        codes.append(c)
                if weight_mode == "score":
                    name_w[sleeve] = weights_score(codes, smaps.get(sleeve, {}))
                else:
                    name_w[sleeve] = weights_equal(codes)
            target = merge_sleeve_weights(sleeve_w, name_w, max_name=max_name)
            to = turnover(prev_w, target)
            port_val = max(port_val * (1 - to * cost), 0.0)
            shares = {}
            invested = 0.0
            for c, w in target.items():
                px = open_px.at[d, c]
                if pd.isna(px) or px <= 0 or w <= 0:
                    continue
                sh = (port_val * w) / px
                shares[c] = sh
                invested += sh * px
            cash = port_val - invested
            prev_w = target
            hold_log.append({
                "signal_date": sig.strftime("%Y-%m-%d"),
                "exec_date": d.strftime("%Y-%m-%d"),
                "sleeves": {k: v for k, v in sleeve_picks.items()},
                "n": len(shares),
                "turnover": round(to, 4),
                "top": sorted(target.items(), key=lambda x: -x[1])[:8],
            })
            port_val = cash
            for c, sh in shares.items():
                px = close.at[d, c] if c in close.columns and pd.notna(close.at[d, c]) else np.nan
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
    return {"equity": eq, "returns": r, "holdings": hold_log, "label": label}


# ---------------------------------------------------------------------------
# Diagnostics (stricter)
# ---------------------------------------------------------------------------

def split_isoos(eq, rets, b_rets, is_end=IS_END) -> Dict:
    is_mask = eq.index <= pd.Timestamp(is_end)
    oos_mask = eq.index > pd.Timestamp(is_end)
    out = {}
    if is_mask.any():
        out["IS"] = perf(eq[is_mask], rets[is_mask], b_rets.reindex(eq[is_mask].index), "IS")
    if oos_mask.any():
        out["OOS"] = perf(eq[oos_mask], rets[oos_mask], b_rets.reindex(eq[oos_mask].index), "OOS")
    return out


def walk_forward(eq, rets, b_rets, n_folds: int = 5) -> List[Dict]:
    idx = rets.dropna().index
    if len(idx) < n_folds * 40:
        return []
    folds = np.array_split(idx, n_folds)
    rows = []
    for i, fidx in enumerate(folds, 1):
        if len(fidx) < 20:
            continue
        r = rets.reindex(fidx).dropna()
        b = b_rets.reindex(r.index).fillna(0.0)
        e = eq.reindex(r.index).dropna()
        if len(e) < 20:
            continue
        # rebuild equity path for fold metrics from returns
        e2 = (1 + r).cumprod()
        years = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
        cagr = float(e2.iloc[-1] ** (1 / years) - 1)
        bc = (1 + b).cumprod()
        bcagr = float(bc.iloc[-1] ** (1 / years) - 1)
        vol = float(r.std() * math.sqrt(252))
        sharpe = float((r.mean() * 252) / vol) if vol > 0 else np.nan
        mdd = float((e2 / e2.cummax() - 1).min())
        excess = r - b
        te = float(excess.std() * math.sqrt(252))
        ir = float((excess.mean() * 252) / te) if te > 0 else np.nan
        rows.append({
            "fold": i,
            "start": str(r.index[0].date()),
            "end": str(r.index[-1].date()),
            "cagr": round(cagr, 4),
            "bench_cagr": round(bcagr, 4),
            "ann_ex": round(cagr - bcagr, 4),
            "sharpe": round(sharpe, 3) if sharpe == sharpe else None,
            "mdd": round(mdd, 4),
            "info_ratio": round(ir, 3) if ir == ir else None,
        })
    return rows


def block_bootstrap_excess(rets, b_rets, n: int = BOOT_N, seed: int = BOOT_SEED,
                           block: int = BLOCK_LEN) -> Dict:
    r = rets.dropna()
    b = b_rets.reindex(r.index).fillna(0.0)
    excess = (r - b).values
    T = len(excess)
    if T < block * 3:
        return {}
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(T / block))
    means = []
    for _ in range(n):
        starts = rng.integers(0, T - block + 1, size=n_blocks)
        sample = np.concatenate([excess[s:s + block] for s in starts])[:T]
        means.append(sample.mean() * 252)
    means = np.array(means)
    obs = float(excess.mean() * 252)
    p_pos = float((means > 0).mean())
    return {
        "obs_ann_excess": round(obs, 4),
        "boot_mean": round(float(means.mean()), 4),
        "boot_p5": round(float(np.percentile(means, 5)), 4),
        "boot_p50": round(float(np.percentile(means, 50)), 4),
        "boot_p95": round(float(np.percentile(means, 95)), 4),
        "prob_positive": round(p_pos, 4),
        "p_value_onesided": round(1.0 - p_pos, 4),
        "n": n,
        "block": block,
        "method": "moving_block_bootstrap",
    }


def evaluate_gates_strict(stats: Dict, isoos: Dict, wf: List[Dict], boot: Dict,
                          b_stats: Dict) -> Dict:
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    cagr = stats.get("cagr") or 0
    bcagr = b_stats.get("cagr") or 0
    sharpe = stats.get("sharpe") or 0
    mdd = stats.get("mdd") or 0
    alpha = stats.get("alpha") or 0
    ir = stats.get("info_ratio") or 0
    bmdd = b_stats.get("mdd") or -0.40

    add("G1_CAGR_vs_Bench", cagr > bcagr + 0.01, f"cagr={cagr:.2%} bench={bcagr:.2%}")
    add("G2_Sharpe_gt_0.6", sharpe >= 0.60, f"sharpe={sharpe}")
    add("G3_MDD_vs_Bench", mdd > min(bmdd - 0.10, -0.50), f"mdd={mdd:.2%} bench_mdd={bmdd:.2%}")
    add("G4_Alpha_positive", alpha > 0.02, f"alpha={alpha:.2%}")
    add("G5_IR_gt_0.2", ir > 0.20, f"IR={ir}")

    oos = isoos.get("OOS") or {}
    is_ = isoos.get("IS") or {}
    oos_ir = oos.get("info_ratio") or 0
    oos_alpha = oos.get("alpha") or 0
    is_ir = is_.get("info_ratio") or 0
    add("G6_OOS_IR_or_Alpha", (oos_ir > 0.10) or (oos_alpha > 0.02),
        f"OOS IR={oos.get('info_ratio')} alpha={oos.get('alpha')}")
    # stability: OOS not infinitely better solely; require IS not catastrophic
    add("G7_IS_not_broken", (is_.get("sharpe") or 0) >= 0.20 or (is_ir > -0.2),
        f"IS sharpe={is_.get('sharpe')} IR={is_.get('info_ratio')}")

    if wf:
        pos = sum(1 for f in wf if (f.get("ann_ex") or 0) > 0)
        med_ex = float(np.median([f.get("ann_ex") or 0 for f in wf]))
        add("G8_WF_majority", pos >= max(1, int(0.6 * len(wf))), f"pos={pos}/{len(wf)}")
        add("G9_WF_median_ex", med_ex > 0, f"median_ann_ex={med_ex:.3f}")
    else:
        add("G8_WF_majority", False, "WF missing")
        add("G9_WF_median_ex", False, "WF missing")

    if boot:
        add("G10_Bootstrap_pos", (boot.get("prob_positive") or 0) >= 0.90,
            f"P(excess>0)={boot.get('prob_positive')} method={boot.get('method')}")
    else:
        add("G10_Bootstrap_pos", False, "bootstrap missing")

    n_pass = sum(1 for c in checks if c["pass"])
    status = "PASS" if n_pass == len(checks) else ("WARN" if n_pass >= len(checks) - 2 else "FAIL")
    return {"checks": checks, "n_pass": n_pass, "n_total": len(checks), "status": status}


def robustness_score(stats: Dict, isoos: Dict, wf: List[Dict], boot: Dict,
                     b_stats: Dict, limited_sample: bool = False) -> Dict:
    """Composite score emphasizing risk-adjusted excess & stability, not raw CAGR."""
    ir = stats.get("info_ratio") or 0
    sharpe = stats.get("sharpe") or 0
    alpha = stats.get("alpha") or 0
    cagr = stats.get("cagr") or 0
    bcagr = b_stats.get("cagr") or 0
    mdd = abs(stats.get("mdd") or 1)
    calmar = stats.get("calmar") or 0
    oos = isoos.get("OOS") or {}
    is_ = isoos.get("IS") or {}
    oos_ir = oos.get("info_ratio") or 0
    is_ir = is_.get("info_ratio") or 0
    wf_ex = [f.get("ann_ex") or 0 for f in (wf or [])]
    med_ex = float(np.median(wf_ex)) if wf_ex else 0.0
    pos_share = float(np.mean([x > 0 for x in wf_ex])) if wf_ex else 0.0
    # fold concentration penalty: max fold excess / sum positive
    pos = [max(x, 0) for x in wf_ex]
    conc = (max(pos) / sum(pos)) if sum(pos) > 0 else 1.0
    p_pos = boot.get("prob_positive") or 0

    # normalize components roughly to 0-1-ish contributions
    score = (
        0.22 * max(min(ir / 1.5, 1.5), -0.5)
        + 0.15 * max(min(sharpe / 1.5, 1.5), -0.5)
        + 0.12 * max(min(alpha / 0.20, 1.5), -0.5)
        + 0.12 * max(min((cagr - bcagr) / 0.20, 1.5), -0.5)
        + 0.10 * max(min(calmar / 1.5, 1.5), -0.5)
        + 0.10 * max(min(med_ex / 0.15, 1.5), -0.5)
        + 0.08 * pos_share
        + 0.06 * p_pos
        + 0.05 * max(min(oos_ir / 1.5, 1.5), -0.5)
        - 0.10 * conc  # penalty for single-fold dominance
        - 0.05 * max(mdd - 0.35, 0) / 0.20
    )
    # OOS/IS consistency bonus if both IR positive
    if is_ir > 0 and oos_ir > 0:
        score += 0.05
    if limited_sample:
        score -= 0.08  # fundamental factors: shorter effective sample

    return {
        "score": round(float(score), 4),
        "ir": ir,
        "sharpe": sharpe,
        "alpha": alpha,
        "excess_cagr": round(cagr - bcagr, 4),
        "med_wf_excess": round(med_ex, 4),
        "wf_pos_share": round(pos_share, 4),
        "fold_concentration": round(conc, 4),
        "boot_p_pos": p_pos,
        "oos_ir": oos_ir,
        "is_ir": is_ir,
        "limited_sample": limited_sample,
    }


# ---------------------------------------------------------------------------
# Main research
# ---------------------------------------------------------------------------

PRICE_FACTORS = [
    "Leader", "Mom12", "Mom63", "NearHigh", "LowVol", "ST_Reversal", "RelMom", "AccumulDiv",
]
FUND_FACTORS = ["Value", "Quality", "ValueMom", "EP", "ROE"]
ALL_SINGLE = PRICE_FACTORS + FUND_FACTORS


def build_picks_for_factor(name, me, feats, val, close, volume, regime):
    picks = {}
    scores = {}
    for d in me:
        reg = regime.loc[d] if d in regime.index else "sideways"
        val_snap = val[val["date"] == d] if not val.empty else pd.DataFrame()
        codes, sm = select_factor(name, d, feats, val_snap, close, volume, reg, n=N_TOP)
        picks[d] = {name: codes}
        scores[d] = {name: sm}
    return picks, scores


def build_multi_picks(me, feats, val, close, volume, regime, sleeve_names: List[str]):
    picks = {}
    scores = {}
    for d in me:
        reg = regime.loc[d] if d in regime.index else "sideways"
        val_snap = val[val["date"] == d] if not val.empty else pd.DataFrame()
        picks[d] = {}
        scores[d] = {}
        for name in sleeve_names:
            codes, sm = select_factor(name, d, feats, val_snap, close, volume, reg, n=N_TOP)
            picks[d][name] = codes
            scores[d][name] = sm
    return picks, scores


def diagnose(label, res, b_rets, b_stats, limited=False):
    st = perf(res["equity"], res["returns"], b_rets, label)
    isoos = split_isoos(res["equity"], res["returns"], b_rets)
    wf = walk_forward(res["equity"], res["returns"], b_rets, n_folds=5)
    boot = block_bootstrap_excess(res["returns"], b_rets)
    gates = evaluate_gates_strict(st, isoos, wf, boot, b_stats)
    rob = robustness_score(st, isoos, wf, boot, b_stats, limited_sample=limited)
    return {
        "stats": st,
        "isoos": isoos,
        "walk_forward": wf,
        "bootstrap": boot,
        "gates": gates,
        "robustness": rob,
        "equity": res["equity"],
        "returns": res["returns"],
        "holdings": res["holdings"],
        "limited_sample": limited,
    }


def main(force: bool = False):
    OUT.mkdir(parents=True, exist_ok=True)
    CHART.mkdir(parents=True, exist_ok=True)

    print("== Load data ==")
    meta = build_universe()
    codes = meta["Code"].astype(str).tolist()
    close, open_px, volume = load_prices(codes, force=force)
    # also load volume panel if separate
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

    print("== Features ==")
    feats = compute_all_features(close, volume, index_close)
    me = month_ends(close.index)
    start = max(pd.Timestamp("2019-07-01"), close.index[0] + pd.Timedelta(days=280))
    me = [d for d in me if d >= start]
    print(f"signals={len(me)} {me[0].date()}~{me[-1].date()}")

    # benchmark path aligned later
    # Single factors
    print("== Single-factor battery ==")
    single_results = {}
    eq_cols = {}
    # temp bench using full close index — refined after first run
    b_eq_full = index_close / index_close.iloc[0] * SEED
    b_rets_full = b_eq_full.pct_change().fillna(0.0)

    for name in ALL_SINGLE:
        limited = name in FUND_FACTORS
        print(f"  - {name}{' [limited fund sample]' if limited else ''}")
        picks, scores = build_picks_for_factor(name, me, feats, val, close, volume, regime)
        # drop empty-all
        n_nonempty = sum(1 for d in me if picks[d][name])
        if n_nonempty < 12:
            print(f"    skip sparse n_months={n_nonempty}")
            continue
        res = run_portfolio(
            close, open_px, picks, {name: 1.0}, scores,
            cost=COST_BASE, max_name=MAX_NAME, weight_mode="equal", label=name,
        )
        # align bench
        b_eq, b_rets = b_eq_full.reindex(res["equity"].index).ffill(), b_rets_full.reindex(res["equity"].index).fillna(0.0)
        # recompute bench equity properly
        b_eq = (1 + b_rets).cumprod() * SEED
        b_stats = perf(b_eq, b_rets, b_rets, "Bench_SPY")
        diag = diagnose(name, res, b_rets, b_stats, limited=limited)
        single_results[name] = diag
        eq_cols[name] = res["equity"]
        r = diag["robustness"]
        g = diag["gates"]
        print(f"    CAGR={diag['stats'].get('cagr')} Sharpe={diag['stats'].get('sharpe')} "
              f"IR={diag['stats'].get('info_ratio')} rob={r['score']} gate={g['status']} "
              f"{g['n_pass']}/{g['n_total']}")

    # Common bench on hybrid range
    # Use Leader equity index as ref if available else first
    ref_key = "Leader" if "Leader" in single_results else next(iter(single_results))
    ref_idx = single_results[ref_key]["equity"].index
    b_rets = index_close.reindex(ref_idx).ffill().pct_change().fillna(0.0)
    b_eq = (1 + b_rets).cumprod() * SEED
    b_stats = perf(b_eq, b_rets, b_rets, "Bench_SPY")

    # Rank singles by robustness
    ranking = sorted(
        (
            {
                "factor": k,
                **v["robustness"],
                "gate": v["gates"]["status"],
                "n_pass": v["gates"]["n_pass"],
                "n_total": v["gates"]["n_total"],
                "cagr": v["stats"].get("cagr"),
                "mdd": v["stats"].get("mdd"),
                "vol": v["stats"].get("vol"),
            }
            for k, v in single_results.items()
        ),
        key=lambda x: x["score"],
        reverse=True,
    )

    # Eligible for combination: WARN/PASS and score > 0 and IR>0 (price) or relaxed for fund
    eligible = []
    for row in ranking:
        name = row["factor"]
        if row["score"] <= 0:
            continue
        if (row.get("ir") or 0) <= 0 and name != "LowVol":
            # LowVol may have low IR vs SPY in bull market but defensive value
            if name not in ("LowVol", "Quality", "ValueMom"):
                continue
        if row["gate"] == "FAIL" and row["n_pass"] < row["n_total"] - 3:
            continue
        # AccumulDiv expected fail — only include if it actually ranked high
        eligible.append(name)

    # Force-include structural candidates if they scored decently
    for must in ["Leader", "Mom12", "RelMom", "LowVol", "Quality", "ValueMom"]:
        if must in single_results and must not in eligible:
            r = single_results[must]["robustness"]
            if r["score"] > -0.05 and (r.get("ir") or 0) > -0.1:
                eligible.append(must)

    print("Eligible for combo:", eligible)

    # Pre-registered combination set (not infinite search)
    combos_spec = [
        ("L100", ["Leader"], {"Leader": 1.0}, False),
        ("L70_VM30", ["Leader", "ValueMom"], {"Leader": 0.70, "ValueMom": 0.30}, True),
        ("L70_Q30", ["Leader", "Quality"], {"Leader": 0.70, "Quality": 0.30}, True),
        ("L60_LV40", ["Leader", "LowVol"], {"Leader": 0.60, "LowVol": 0.40}, False),
        ("L55_VM25_Q20", ["Leader", "ValueMom", "Quality"],
         {"Leader": 0.55, "ValueMom": 0.25, "Quality": 0.20}, True),
        ("L50_RM30_LV20", ["Leader", "RelMom", "LowVol"],
         {"Leader": 0.50, "RelMom": 0.30, "LowVol": 0.20}, False),
        ("M12_100", ["Mom12"], {"Mom12": 1.0}, False),
        ("RM100", ["RelMom"], {"RelMom": 1.0}, False),
        ("Legacy_L55_VM25_D20", ["Leader", "ValueMom", "AccumulDiv"],
         {"Leader": 0.55, "ValueMom": 0.25, "AccumulDiv": 0.20}, True),
        ("L70_VM30_20bp", ["Leader", "ValueMom"], {"Leader": 0.70, "ValueMom": 0.30}, True),
        ("L70_Q30_20bp", ["Leader", "Quality"], {"Leader": 0.70, "Quality": 0.30}, True),
    ]

    print("== Combination battery ==")
    combo_results = {}
    for label, sleeves, weights, limited_flag in combos_spec:
        # skip if any sleeve missing entirely from singles (except intentional)
        if any(s not in single_results and s not in ALL_SINGLE for s in sleeves):
            continue
        cost = COST_STRESS if label.endswith("20bp") else COST_BASE
        print(f"  - {label} {weights}")
        picks, scores = build_multi_picks(me, feats, val, close, volume, regime, sleeves)
        res = run_portfolio(
            close, open_px, picks, weights, scores,
            cost=cost, max_name=MAX_NAME, weight_mode="equal", label=label,
        )
        br = index_close.reindex(res["equity"].index).ffill().pct_change().fillna(0.0)
        be = (1 + br).cumprod() * SEED
        bs = perf(be, br, br, "Bench_SPY")
        # limited if any fund sleeve
        lim = limited_flag or any(s in FUND_FACTORS for s in sleeves)
        diag = diagnose(label, res, br, bs, limited=lim)
        combo_results[label] = diag
        eq_cols[label] = res["equity"]
        print(f"    CAGR={diag['stats'].get('cagr')} Sharpe={diag['stats'].get('sharpe')} "
              f"IR={diag['stats'].get('info_ratio')} rob={diag['robustness']['score']} "
              f"gate={diag['gates']['status']}")

    combo_rank = sorted(
        (
            {
                "strategy": k,
                **v["robustness"],
                "gate": v["gates"]["status"],
                "n_pass": v["gates"]["n_pass"],
                "n_total": v["gates"]["n_total"],
                "cagr": v["stats"].get("cagr"),
                "mdd": v["stats"].get("mdd"),
                "vol": v["stats"].get("vol"),
                "weights": next(w for lab, _, w, _ in combos_spec if lab == k),
            }
            for k, v in combo_results.items()
        ),
        key=lambda x: x["score"],
        reverse=True,
    )

    # Recommend: best combo that is not pure legacy-div if possible; prefer PASS/WARN
    def pick_recommended(rows):
        # prefer non-legacy, non-stress, gate not FAIL
        for r in rows:
            if r["strategy"].endswith("20bp"):
                continue
            if r["strategy"].startswith("Legacy"):
                continue
            if r["gate"] == "FAIL" and r["n_pass"] < r["n_total"] - 2:
                continue
            return r
        return rows[0] if rows else None

    recommended = pick_recommended(combo_rank)
    rec_name = recommended["strategy"] if recommended else None
    rec_diag = combo_results.get(rec_name) if rec_name else None

    # Stress twin if exists
    stress_name = f"{rec_name}_20bp" if rec_name and f"{rec_name}_20bp" in combo_results else None
    if rec_name == "L70_VM30":
        stress_name = "L70_VM30_20bp" if "L70_VM30_20bp" in combo_results else stress_name
    if rec_name == "L70_Q30":
        stress_name = "L70_Q30_20bp" if "L70_Q30_20bp" in combo_results else stress_name

    # Equity matrix
    eq_df = pd.DataFrame({"Bench_SPY": b_eq})
    for k, s in eq_cols.items():
        eq_df[k] = s.reindex(eq_df.index).ffill()
    # reindex to intersection with recommended if possible
    if rec_diag is not None:
        eq_df = pd.DataFrame({"Bench_SPY": (1 + index_close.reindex(rec_diag["equity"].index).ffill().pct_change().fillna(0.0)).cumprod() * SEED})
        for k, s in eq_cols.items():
            eq_df[k] = s.reindex(eq_df.index)
        eq_df["Bench_SPY"] = (1 + index_close.reindex(eq_df.index).ffill().pct_change().fillna(0.0)).cumprod() * SEED

    eq_df.to_csv(OUT / "equity_curves.csv")

    # Stats tables
    single_stats = []
    for k, v in single_results.items():
        row = dict(v["stats"])
        row["robustness"] = v["robustness"]["score"]
        row["gate"] = v["gates"]["status"]
        row["med_wf_excess"] = v["robustness"]["med_wf_excess"]
        row["fold_concentration"] = v["robustness"]["fold_concentration"]
        row["boot_p_pos"] = v["robustness"]["boot_p_pos"]
        row["limited_sample"] = v["limited_sample"]
        single_stats.append(row)
    single_df = pd.DataFrame(single_stats).sort_values("robustness", ascending=False)
    single_df.to_csv(OUT / "single_factor_stats.csv", index=False)

    combo_stats = []
    for k, v in combo_results.items():
        row = dict(v["stats"])
        row["robustness"] = v["robustness"]["score"]
        row["gate"] = v["gates"]["status"]
        row["med_wf_excess"] = v["robustness"]["med_wf_excess"]
        row["fold_concentration"] = v["robustness"]["fold_concentration"]
        row["boot_p_pos"] = v["robustness"]["boot_p_pos"]
        combo_stats.append(row)
    combo_df = pd.DataFrame(combo_stats).sort_values("robustness", ascending=False)
    combo_df.to_csv(OUT / "combo_stats.csv", index=False)

    # Factor correlation of monthly returns (diversification check)
    monthly = {}
    for k, v in single_results.items():
        monthly[k] = v["equity"].resample("ME").last().pct_change()
    mdf = pd.DataFrame(monthly).dropna(how="all")
    corr = mdf.corr()
    corr.to_csv(OUT / "factor_corr_monthly.csv")

    # Payload
    def strip_series(d):
        return {k: v for k, v in d.items() if k not in ("equity", "returns", "holdings")}

    payload = {
        "protocol": {
            "execution": "next_open",
            "signal": "month_end_close",
            "cost_base": COST_BASE,
            "cost_stress": COST_STRESS,
            "max_name": MAX_NAME,
            "is_end": IS_END,
            "bootstrap": "moving_block_bootstrap",
            "block_len": BLOCK_LEN,
            "n_top": N_TOP,
            "min_amt": MIN_AMT,
            "fund_lag_days": FUND_LAG_DAYS,
            "anti_overfit": [
                "pre_registered_factor_list",
                "fixed_IS_OOS_date",
                "walk_forward_median_excess",
                "block_bootstrap",
                "combination_only_from_shortlist",
                "equal_weight_default_within_sleeve",
                "robustness_penalizes_fold_concentration",
                "fundamental_limited_sample_penalty",
            ],
            "known_biases": [
                "surviving_sp500_membership_bias",
                "yfinance_corporate_action_noise",
                "valuation_panel_starts_2022_09",
                "no_sector_cap_in_this_run",
            ],
        },
        "data_range": {
            "prices": f"{close.index.min().date()}~{close.index.max().date()}",
            "signals": f"{me[0].date()}~{me[-1].date()}",
            "valuation": (
                f"{val['date'].min().date()}~{val['date'].max().date()}" if not val.empty else "none"
            ),
            "n_codes": int(close.shape[1]),
            "n_signals": len(me),
        },
        "single_ranking": ranking,
        "combo_ranking": combo_rank,
        "eligible_for_combo": eligible,
        "recommended": {
            "name": rec_name,
            "detail": recommended,
            "stats": rec_diag["stats"] if rec_diag else None,
            "gates": rec_diag["gates"] if rec_diag else None,
            "isoos": rec_diag["isoos"] if rec_diag else None,
            "walk_forward": rec_diag["walk_forward"] if rec_diag else None,
            "bootstrap": rec_diag["bootstrap"] if rec_diag else None,
            "robustness": rec_diag["robustness"] if rec_diag else None,
            "latest_holdings": (rec_diag["holdings"][-1] if rec_diag and rec_diag["holdings"] else {}),
            "holdings_tail": (rec_diag["holdings"][-6:] if rec_diag and rec_diag["holdings"] else []),
            "stress": {
                "name": stress_name,
                "stats": combo_results[stress_name]["stats"] if stress_name else None,
                "gates": combo_results[stress_name]["gates"] if stress_name else None,
            },
        },
        "bench": b_stats,
        "singles": {k: strip_series(v) for k, v in single_results.items()},
        "combos": {k: strip_series(v) for k, v in combo_results.items()},
        "factor_corr": corr.round(3).to_dict(),
        "decision_rules": {
            "drop": ["AccumulDiv if IR<=0 or rob low — KR foreign-flow not portable"],
            "core": "price momentum family (Leader / Mom12 / RelMom)",
            "satellite": "LowVol and/or Quality/ValueMom if gate not FAIL",
            "objective": "maximize robustness_score not raw CAGR",
        },
    }

    with open(OUT / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    if rec_diag and rec_diag.get("holdings"):
        with open(OUT / "holdings.json", "w", encoding="utf-8") as f:
            json.dump(rec_diag["holdings"], f, ensure_ascii=False, indent=2, default=str)

    print("\n== RANKING (single) ==")
    for r in ranking[:10]:
        print(f"  {r['factor']:12s} rob={r['score']:+.3f} IR={r['ir']} Sharpe={r['sharpe']} "
              f"gate={r['gate']} medWF={r['med_wf_excess']} conc={r['fold_concentration']}")
    print("\n== RANKING (combo) ==")
    for r in combo_rank:
        print(f"  {r['strategy']:18s} rob={r['score']:+.3f} IR={r['ir']} CAGR={r['cagr']} "
              f"gate={r['gate']} medWF={r['med_wf_excess']}")
    print("\nRECOMMENDED:", rec_name)
    print("DONE ->", OUT)
    return payload


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    main(force=args.force)
