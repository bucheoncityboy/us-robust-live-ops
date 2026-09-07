"""Monthly live ops runner for US Robust (Robust_L60_M63_LV20).

Outputs under results/ops_runs/YYYY-MM/:
  signals.csv, target.csv, orders_preview.csv, health.json

Policy freeze:
  equal-within-sleeve Leader 60 / Mom63 20 / LowVol 20, name cap 15%, NEXT_OPEN.
  US tickers via normalize_symbol (never zfill). No hybrid SCORE selection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import ops.ops_us_policy as uspol
from ops.ops_us_policy import (
    COST,
    EXEC_RULE,
    MAX_NAME,
    MAX_SECTOR,
    N_LEADER,
    N_LOWVOL,
    N_MOM63,
    N_NAMES_WARN_HI,
    N_NAMES_WARN_LO,
    SLEEVE_WEIGHTS,
    TOP_N_DEFAULT,
    WEIGHT_EPS,
    WEIGHT_MODE,
    normalize_symbol,
    select_us_picks,
)
from ops.us_factor_research import compute_all_features
from ops.ops_live_safety import (
    CASH_BUFFER_RATIO,
    MIN_BUY_USD,
    apply_risk_weights,
    atomic_write_csv,
    atomic_write_json,
    completed_month_signal,
    ny_today,
    resolve_risk_mode,
    sanitize_excel_value,
    write_package_manifest,
)
from ops.us_hybrid_backtest import (
    CACHE_VAL,
    DATA,
    build_universe,
    load_index,
    load_prices,
    market_regime,
    merge_sleeve_weights,
    month_ends,
    weights_equal,
)

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "results" / "ops_runs"

# Module cache so build_target keeps the historical 5-arg signature used by callers/tests.
_LAST_CLOSE: Optional[pd.DataFrame] = None
_LAST_VOLUME: Optional[pd.DataFrame] = None
_LAST_OPEN: Optional[pd.DataFrame] = None

FRACTIONAL_SHARES_DEFAULT = True  # US fractional shares; do not floor to whole shares

# Health lag (calendar days vs signal_date)
LAG_BLOCK_PRICES = 3
LAG_WARN_VAL = 40


def load_market(top_n: int = TOP_N_DEFAULT):
    """Load US Robust market panels from data/us (yfinance SoT).

    Returns the historical 11-tuple shape for callers:
      close, volume, index_close, regime, feats, frgn_feats, val, meta, name_map, sector_map, frgn
    frgn / frgn_feats are empty placeholders (no KR foreign path).
    """
    global _LAST_CLOSE, _LAST_VOLUME, _LAST_OPEN

    meta = build_universe(top_n=top_n)
    if meta is None or meta.empty:
        raise FileNotFoundError(f"missing US universe meta under {DATA}")
    meta = meta.copy()
    meta["Code"] = meta["Code"].map(normalize_symbol)
    meta = meta[meta["Code"].astype(bool)].reset_index(drop=True)
    if "Marcap" in meta.columns:
        meta = meta.sort_values("Marcap", ascending=False)
    meta = meta.head(top_n).reset_index(drop=True)
    codes = meta["Code"].tolist()

    close, open_px, volume = load_prices(codes, force=False)
    close = close.copy()
    open_px = open_px.copy()
    volume = volume.copy()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    open_px.index = pd.to_datetime(open_px.index).tz_localize(None)
    volume.index = pd.to_datetime(volume.index).tz_localize(None)
    close.columns = [normalize_symbol(c) for c in close.columns]
    open_px.columns = [normalize_symbol(c) for c in open_px.columns]
    volume.columns = [normalize_symbol(c) for c in volume.columns]
    # drop empty-symbol columns if any
    close = close.loc[:, [c for c in close.columns if c]]
    open_px = open_px.reindex(columns=close.columns)
    volume = volume.reindex(columns=close.columns).fillna(0.0)

    # Sync universe to priced names (prevents silent holes like SNDK-in-meta/no-price)
    priced = set(close.columns)
    miss_px = [c for c in codes if c not in priced]
    if miss_px:
        print(f"[universe] drop unpriced codes n={len(miss_px)} sample={miss_px[:8]}")
        meta = meta[meta["Code"].isin(priced)].reset_index(drop=True)
        codes = meta["Code"].tolist()
        close = close.reindex(columns=codes)
        open_px = open_px.reindex(columns=codes)
        volume = volume.reindex(columns=codes).fillna(0.0)

    valid = close.notna().sum() >= 200
    close = close.loc[:, valid].sort_index()
    open_px = open_px.reindex(columns=close.columns).reindex(close.index)
    volume = volume.reindex(columns=close.columns).reindex(close.index).fillna(0.0)
    meta = meta[meta["Code"].isin(set(close.columns))].reset_index(drop=True)

    index_close = load_index(force=False)
    index_close.index = pd.to_datetime(index_close.index).tz_localize(None)
    index_close = index_close.reindex(close.index).ffill()
    if index_close.isna().all():
        index_close = close.mean(axis=1)

    regime = market_regime(index_close)
    feats = compute_all_features(close, volume, index_close)

    # No KR foreign path required for US Robust
    frgn = pd.DataFrame()
    frgn_feats = {
        "confirm": pd.DataFrame(),
        "bear_div": pd.DataFrame(),
        "bull_div": pd.DataFrame(),
        "frgn_20": pd.DataFrame(),
        "ret_20": pd.DataFrame(),
    }

    val = pd.DataFrame()
    if CACHE_VAL.exists():
        val = pd.read_parquet(CACHE_VAL)
        if not val.empty:
            val = val.copy()
            val["date"] = pd.to_datetime(val["date"])
            if "code" in val.columns:
                val["code"] = val["code"].map(normalize_symbol)

    name_map: Dict[str, str] = {}
    if "Name" in meta.columns:
        name_map = {
            normalize_symbol(c): str(n)
            for c, n in zip(meta["Code"], meta["Name"])
            if normalize_symbol(c)
        }
    sector_map: Dict[str, str] = {}
    for col in ("sector", "Sector", "Industry", "GICS Sector"):
        if col in meta.columns:
            series = meta[col]
            if (
                series.notna().any()
                and series.astype(str).str.strip().ne("").any()
                and series.astype(str).str.lower().ne("none").any()
            ):
                sector_map = {
                    normalize_symbol(c): str(s)
                    for c, s in zip(meta["Code"], series)
                    if normalize_symbol(c)
                    and pd.notna(s)
                    and str(s).strip()
                    and str(s).lower() != "none"
                }
                if sector_map:
                    break

    _LAST_CLOSE = close
    _LAST_VOLUME = volume
    _LAST_OPEN = open_px
    return close, volume, index_close, regime, feats, frgn_feats, val, meta, name_map, sector_map, frgn


def pick_signal_date(close: pd.DataFrame, asof: Optional[str]) -> pd.Timestamp:
    me = list(month_ends(close.index))
    if not me:
        raise RuntimeError("no month_ends available on price calendar")
    if asof:
        cut = pd.Timestamp(asof)
        cand = [d for d in me if d <= cut]
        if not cand:
            raise RuntimeError(f"no month_end <= asof {asof}")
        return cand[-1]
    return me[-1]


def calendar_month_end(signal_date: pd.Timestamp) -> pd.Timestamp:
    """Last calendar day of signal_date's month."""
    sd = pd.Timestamp(signal_date).normalize()
    return (sd + pd.offsets.MonthEnd(0)).normalize()


def is_final_month_end_signal(
    signal_date: pd.Timestamp,
    close: pd.DataFrame,
    *,
    asof: Optional[str] = None,
    today: Optional[pd.Timestamp] = None,
) -> bool:
    """Return True only for a completed New York month.

    ``asof`` only selects historical data; it never advances the live clock or
    makes the current New York month complete.
    """
    ok, _ = completed_month_signal(
        signal_date,
        close.index,
        now=today,
    )
    return ok


def assert_final_month_end_signal(
    signal_date: pd.Timestamp,
    close: pd.DataFrame,
    *,
    asof: Optional[str] = None,
    force_intramonth: bool = False,
) -> None:
    """Refuse incomplete intra-month signals unless explicitly forced."""
    if is_final_month_end_signal(signal_date, close, asof=asof):
        return
    sd = pd.Timestamp(signal_date).normalize()
    cal_me = calendar_month_end(sd)
    msg = (
        f"INTRA_MONTH_SIGNAL: refusing signal {sd.date()} for incomplete month {sd:%Y-%m} "
        f"(calendar month-end {cal_me.date()}). "
        f"Policy is month-end Close only. Use --force-intramonth for research."
    )
    if force_intramonth:
        print("WARN:", msg)
        return
    print("ERROR:", msg)
    raise SystemExit(3)


def val_snap_on(val: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    if val is None or val.empty:
        return pd.DataFrame()
    exact = val[val["date"] == date]
    if not exact.empty:
        return exact
    prior = val[val["date"] <= date]
    if prior.empty:
        return pd.DataFrame()
    dmax = prior["date"].max()
    return prior[prior["date"] == dmax].copy()


def score_maps(date, feats, frgn_feats=None, val_snap: Optional[pd.DataFrame] = None) -> Dict[str, Dict[str, float]]:
    """Score maps for US Robust sleeves (leader / mom63 / lowvol). Equal-weight path does not require these."""
    sm: Dict[str, Dict[str, float]] = {"leader": {}, "mom63": {}, "lowvol": {}}
    if date in feats.get("leader_score", pd.DataFrame()).index:
        sm["leader"] = {
            normalize_symbol(k): float(v)
            for k, v in feats["leader_score"].loc[date].dropna().to_dict().items()
            if normalize_symbol(k)
        }
    if date in feats.get("mom63_raw", pd.DataFrame()).index:
        sm["mom63"] = {
            normalize_symbol(k): float(v)
            for k, v in feats["mom63_raw"].loc[date].dropna().to_dict().items()
            if normalize_symbol(k)
        }
    if date in feats.get("lowvol_score", pd.DataFrame()).index:
        sm["lowvol"] = {
            normalize_symbol(k): float(v)
            for k, v in feats["lowvol_score"].loc[date].dropna().to_dict().items()
            if normalize_symbol(k)
        }
    return sm


def build_target(
    date: pd.Timestamp,
    feats,
    frgn_feats,
    val: pd.DataFrame,
    regime: pd.Series,
    close: Optional[pd.DataFrame] = None,
    volume: Optional[pd.DataFrame] = None,
) -> Tuple[Dict[str, List[str]], Dict[str, float], Dict[str, Dict[str, float]], str]:
    """US Robust equal-within-sleeve target. No hybrid SCORE / select_* path.

    Empty sleeves become cash (do not silently boost other sleeves).
    Name-cap leftovers also remain as residual cash (weights may sum < 1).
    """
    reg = regime.loc[date] if date in regime.index else "sideways"
    if not isinstance(reg, str):
        reg = str(reg)

    close_px = close if close is not None else _LAST_CLOSE
    vol_px = volume if volume is not None else _LAST_VOLUME
    if close_px is None or vol_px is None:
        raise RuntimeError("build_target requires load_market() first (close/volume cache empty)")

    picks, _scores = select_us_picks(
        date,
        feats,
        close_px,
        vol_px,
        regime,
        n_leader=N_LEADER,
        n_mom63=N_MOM63,
        n_lowvol=N_LOWVOL,
    )

    name_w: Dict[str, Dict[str, float]] = {}
    for sleeve, codes in picks.items():
        if not codes:
            name_w[sleeve] = {}
            continue
        w = weights_equal(codes)
        name_w[sleeve] = {normalize_symbol(k): float(v) for k, v in w.items() if normalize_symbol(k)}

    sleeve_w = dict(SLEEVE_WEIGHTS)
    cash = float(sleeve_w.get("cash", 0.0) or 0.0)
    for sleeve in ("leader", "mom63", "lowvol"):
        if not name_w.get(sleeve):
            cash += float(sleeve_w.get(sleeve, 0.0) or 0.0)
            sleeve_w[sleeve] = 0.0
    if cash > 0:
        sleeve_w["cash"] = cash
    final = merge_sleeve_weights(sleeve_w, name_w, max_name=MAX_NAME)
    final = {normalize_symbol(k): float(v) for k, v in final.items() if float(v) > 0 and normalize_symbol(k)}
    return picks, final, name_w, reg

def panel_last_date(df: pd.DataFrame, kind: str) -> Optional[str]:
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return None
    if kind == "prices":
        return str(pd.to_datetime(df.index.max()).date())
    if kind == "foreign":
        if "date" in df.columns:
            return str(pd.to_datetime(df["date"]).max().date())
        return None
    if kind == "val":
        if "date" in df.columns:
            return str(pd.to_datetime(df["date"]).max().date())
        return None
    if kind == "index":
        return str(pd.to_datetime(df.index.max()).date())
    return None


def build_health(
    signal_date: pd.Timestamp,
    close: pd.DataFrame,
    frgn: pd.DataFrame,
    val: pd.DataFrame,
    index_close: pd.Series,
    picks: Dict[str, List[str]],
    final_w: Dict[str, float],
    sector_map: Dict[str, str],
    *,
    reference_date: Optional[Any] = None,
    universe_n: Optional[int] = None,
    universe_target: int = TOP_N_DEFAULT,
) -> Dict:
    sd = pd.Timestamp(signal_date).normalize()
    ref = pd.Timestamp(reference_date or ny_today()).normalize()
    p_last = panel_last_date(close, "prices")
    f_last = panel_last_date(frgn, "foreign")
    v_last = panel_last_date(val, "val")
    i_last = panel_last_date(index_close.to_frame("Close"), "index")

    def lag_days(last: Optional[str]) -> Optional[int]:
        if not last:
            return None
        return max(0, int((ref - pd.Timestamp(last).normalize()).days))

    lags = {"prices": lag_days(p_last), "foreign": lag_days(f_last),
            "valuation": lag_days(v_last), "index": lag_days(i_last)}
    status = "OK"
    reasons: List[str] = []
    if not p_last or (lags["prices"] is not None and lags["prices"] > LAG_BLOCK_PRICES):
        status = "BLOCK"
        reasons.append("prices_missing_or_stale")
    if sum(len(v) for v in picks.values()) == 0 or not final_w:
        status = "BLOCK"
        reasons.append("empty_picks_or_weights")
    wsum = float(sum(final_w.values())) if final_w else 0.0
    if final_w:
        if wsum <= 0 or wsum > 1.0 + 1e-4:
            status = "BLOCK"
            reasons.append(f"weight_sum={wsum:.6f}")
        elif wsum < 1.0 - 1e-4:
            if status == "OK":
                status = "WARN"
            reasons.append(f"cash_residual={1.0 - wsum:.6f}")
    if final_w and max(final_w.values()) > MAX_NAME + 1e-9:
        status = "BLOCK"
        reasons.append("name_cap_breach")
    n_names = len(final_w)
    if status != "BLOCK":
        if lags["valuation"] is not None and lags["valuation"] > LAG_WARN_VAL:
            status = "WARN"
            reasons.append("valuation_lag")
        if n_names and (n_names < N_NAMES_WARN_LO or n_names > N_NAMES_WARN_HI):
            status = "WARN"
            reasons.append(f"n_names_band={n_names}")
    if universe_n is not None and int(universe_n) < int(universe_target):
        if status == "OK":
            status = "WARN"
        reasons.append(f"universe_shortfall={int(universe_n)}/{int(universe_target)}")

    sector_cap = "SKIPPED"
    max_sector_w = None
    if sector_map and final_w:
        sec_w: Dict[str, float] = {}
        for code, weight in final_w.items():
            sec = sector_map.get(code, "UNKNOWN")
            sec_w[sec] = sec_w.get(sec, 0.0) + weight
        max_sector_w = max(sec_w.values()) if sec_w else None
        if max_sector_w is not None and max_sector_w > MAX_SECTOR + 1e-9:
            if status == "OK":
                status = "WARN"
            reasons.append("sector_cap_breach")
            sector_cap = "BREACH"
        else:
            sector_cap = "OK"

    budgets = {s: (float(SLEEVE_WEIGHTS[s]) if picks.get(s) else 0.0)
               for s in ("leader", "mom63", "lowvol")}
    active_sum = sum(budgets.values())
    scale = min(1.0, wsum / active_sum) if active_sum > 0 else 0.0
    sleeve_exposure = {s: w * scale for s, w in budgets.items()}
    sleeve_exposure["cash"] = max(0.0, 1.0 - sum(sleeve_exposure.values()))

    primary = {"leader": 0.0, "mom63": 0.0, "lowvol": 0.0, "other": 0.0}
    sets = {s: set(picks.get(s, [])) for s in ("leader", "mom63", "lowvol")}
    for code, weight in final_w.items():
        if code in sets["leader"]:
            primary["leader"] += weight
        elif code in sets["mom63"]:
            primary["mom63"] += weight
        elif code in sets["lowvol"]:
            primary["lowvol"] += weight
        else:
            primary["other"] += weight

    return {
        "signal_date": str(sd.date()), "reference_date": str(ref.date()),
        "status": status, "reasons": reasons,
        "last_dates": {"prices": p_last, "foreign": f_last, "valuation": v_last, "index": i_last},
        "lag_days": lags, "universe_n": universe_n, "universe_target": universe_target,
        "n_names": n_names, "weight_sum": wsum,
        "max_name_w": max(final_w.values()) if final_w else None,
        "max_sector_w": max_sector_w, "sector_cap": sector_cap,
        "sleeve_exposure": sleeve_exposure, "name_primary_exposure": primary,
        "picks_count": {k: len(v) for k, v in picks.items()},
        "policy": {"name": uspol.POLICY_NAME, "sleeves": dict(SLEEVE_WEIGHTS),
                   "weight_mode": WEIGHT_MODE, "max_name": MAX_NAME,
                   "max_sector": MAX_SECTOR, "exec": EXEC_RULE, "cost": COST,
                   "n_leader": N_LEADER, "n_mom63": N_MOM63, "n_lowvol": N_LOWVOL},
    }


def load_positions(path: Optional[str]) -> Dict[str, float]:
    """Load current weights from CSV path or live Toss ('toss').

    Empty book: None / '' / none / off / empty / flat
    Live Toss: toss (default in CLI)
    """
    if path is None:
        return {}
    src = str(path).strip()
    if not src or src.lower() in {"none", "off", "empty", "flat", "-", "null"}:
        print("  positions=none (empty book)")
        return {}
    if src.lower() in {"toss", "toss://", "toss:live"}:
        from ops.toss_portfolio import fetch_portfolio, us_weights

        book = fetch_portfolio()
        w = us_weights(book)
        print(
            f"  positions=toss account=...{book.get('account_no_tail')} "
            f"n_us={book.get('n_us')} n_kr={book.get('n_kr')} "
            f"ops_ready={book.get('ops_ready')} flat={book.get('flat')} "
            f"cash_usd={float(book.get('cash_usd') or 0):.2f}"
        )
        # stash for excel writer in same process
        load_positions.last_toss_book = book  # type: ignore[attr-defined]
        return w

    p = Path(src)
    if not p.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(p)
    cols = {c.lower(): c for c in df.columns}
    code_col = cols.get("code") or cols.get("ticker")
    if code_col is None:
        raise ValueError("positions csv needs code column")
    if "weight" in cols:
        wcol = cols["weight"]
        out = {normalize_symbol(r[code_col]): float(r[wcol]) for _, r in df.iterrows() if normalize_symbol(r[code_col])}
    elif "qty" in cols and "price" in cols:
        qcol, pcol = cols["qty"], cols["price"]
        vals = {normalize_symbol(r[code_col]): float(r[qcol]) * float(r[pcol]) for _, r in df.iterrows() if normalize_symbol(r[code_col])}
        s = sum(vals.values())
        out = {k: v / s for k, v in vals.items()} if s > 0 else {}
    else:
        raise ValueError("positions csv needs weight or qty+price")
    s = sum(out.values())
    if s > 0 and abs(s - 1.0) > 1e-3:
        out = {k: v / s for k, v in out.items()}
    return out



def scrub_health_legacy(health: dict) -> dict:
    """Remove legacy KR sizing aliases from health snapshots (US ops SoT)."""
    for k in ("capital_krw", "kr_weights", "cash_krw", "equity_krw", "total_krw"):
        health.pop(k, None)
    toss = health.get("toss")
    if isinstance(toss, dict):
        for k in ("capital_krw", "kr_weights", "cash_krw", "equity_krw", "total_krw"):
            toss.pop(k, None)
    return health


def resolve_capital_usd(
    book: Optional[Dict] = None,
    capital_usd: Optional[float] = None,
) -> tuple[Optional[float], str]:
    """USD capital base for share sizing (US Robust SoT).

    Priority:
      1) explicit capital_usd arg / OPS_CAPITAL_USD env
      2) Toss total_usd (equity_usd + cash_usd)
      3) Toss cash_usd / cash_buying_power_usd
      4) None (qty left blank)
    """
    import os
    if capital_usd is not None and float(capital_usd) > 0:
        return float(capital_usd), "arg"
    env = (os.environ.get("OPS_CAPITAL_USD") or "").strip()
    if env:
        try:
            v = float(env.replace(",", ""))
            if v > 0:
                return v, "env:OPS_CAPITAL_USD"
        except ValueError:
            pass
    if book:
        total = float(book.get("total_usd") or 0.0)
        if total <= 0:
            total = float(book.get("equity_usd") or 0.0) + float(book.get("cash_usd") or 0.0)
        if total > 0:
            # Leave the LIVE cash buffer (2%) so execute gate_B (cash*0.98) never
            # blocks a 100%-cash book; residual buffer cash is allowed by policy.
            return total * (1.0 - CASH_BUFFER_RATIO), "toss:total_usd"
        cash = float(book.get("cash_usd") or book.get("cash_buying_power_usd") or 0.0)
        if cash > 0:
            return cash * (1.0 - CASH_BUFFER_RATIO), "toss:cash_usd"
    return None, "none"




def attach_share_sizes(
    orders: List[Dict],
    close: pd.DataFrame,
    capital_usd: Optional[float],
    capital_source: str = "none",
    signal_date: Optional[pd.Timestamp] = None,
    fractional: bool = True,
    qty_decimals: int = 6,
    live_px: Optional[Dict[str, float]] = None,
    live_qty: Optional[Dict[str, float]] = None,
    open_px: Optional[pd.DataFrame] = None,
) -> List[Dict]:
    """Add est_px / qty / notional.

    Price SoT:
      1) Toss live last_price for held names
      2) NEXT_OPEN yfinance open (policy EXEC_RULE)
      3) fallback: signal-date close (or last close)
    SELL qty prefers Toss live share qty when available.
    """
    if not orders:
        return orders

    def _round_qty(x: float) -> float:
        if x is None:
            return None
        if not fractional:
            return float(int(max(0.0, x)))
        q = round(float(x), qty_decimals)
        return q if q > 0 else 0.0

    pxrow = None
    px_kind = "yfinance_close"
    if open_px is not None and signal_date is not None and len(open_px):
        try:
            from ops.us_hybrid_backtest import next_open_map

            op = open_px.copy()
            op.index = pd.to_datetime(op.index).tz_localize(None)
            op.columns = [normalize_symbol(c) for c in op.columns]
            sig = pd.Timestamp(signal_date)
            if getattr(sig, "tzinfo", None) is not None:
                sig = sig.tz_localize(None)
            cal = op.index
            if close is not None and len(close):
                cal = pd.DatetimeIndex(
                    sorted(set(pd.to_datetime(close.index).tz_localize(None)).union(set(op.index)))
                )
            emap = next_open_map(cal, op)
            ex = emap.get(sig.normalize()) or emap.get(sig)
            if ex is not None and ex in op.index:
                pxrow = op.loc[ex].copy()
                px_kind = "yfinance_next_open"
        except Exception:
            pxrow = None
    if pxrow is None and close is not None and len(close):
        if signal_date is not None and signal_date in close.index:
            pxrow = close.loc[signal_date]
        else:
            pxrow = close.iloc[-1]
        pxrow = pxrow.copy()
        px_kind = "yfinance_close"
    if pxrow is not None:
        pxrow.index = [normalize_symbol(c) for c in pxrow.index]

    for o in orders:
        code = normalize_symbol(o.get("code"))
        o["capital_usd"] = float(capital_usd) if capital_usd and capital_usd > 0 else None
        o["capital_source"] = capital_source
        o["fractional"] = bool(fractional)
        px = None
        px_source = "none"
        if live_px and code in live_px and float(live_px.get(code) or 0) > 0:
            px = float(live_px[code])
            px_source = "toss"
        elif pxrow is not None and code in pxrow.index:
            try:
                v = float(pxrow[code])
                if v > 0 and v == v:
                    px = v
                    px_source = px_kind
            except Exception:
                px = None
        o["est_px"] = px
        o["px_source"] = px_source
        tw = float(o.get("target_w") or 0.0)
        cw = float(o.get("current_w") or 0.0)
        if capital_usd and capital_usd > 0 and px and px > 0:
            target_qty = _round_qty((capital_usd * tw) / px)
            if live_qty and code in live_qty:
                current_qty = _round_qty(float(live_qty.get(code) or 0.0))
            else:
                current_qty = _round_qty((capital_usd * cw) / px)
            delta_qty = float(target_qty) - float(current_qty)
            delta_notional = abs(delta_qty) * px if px else 0.0
            # executable-order guard: within weight drift band or below the broker's
            # minimum order size ($1) -> HOLD instead of a meaningless micro trade
            share_w = (
                float(current_qty) * px / float(capital_usd)
                if px and capital_usd and capital_usd > 0 and current_qty > 0 else None
            )
            within_band = (
                share_w is not None and target_qty > 0 and current_qty > 0
                and abs(float(tw) - share_w) <= 0.002
            )
            below_min = delta_notional < MIN_BUY_USD and target_qty > 0 and current_qty > 0
            if abs(delta_qty) <= 10 ** (-qty_decimals) or within_band or below_min:
                o["side"], o["action"], qty = "HOLD", "HOLD", 0.0
            elif delta_qty > 0:
                o["side"] = "BUY"
                o["action"] = "BUY_NEW" if current_qty <= 0 else "BUY_ADD"
                o["reason"] = "NEW_ENTRY" if current_qty <= 0 else "REWEIGHT"
                qty = _round_qty(delta_qty)
            else:
                o["side"] = "SELL"
                o["action"] = "SELL_EXIT" if target_qty <= 0 else "SELL_TRIM"
                o["reason"] = "EXIT_SIGNAL" if target_qty <= 0 else "REWEIGHT"
                qty = _round_qty(-delta_qty)
            o["target_qty"] = target_qty
            o["current_qty"] = current_qty
            o["qty"] = qty
            notional = float(qty) * float(px) if qty is not None else None
            o["notional"] = notional
            # cash impact: BUY consumes cash, SELL frees cash
            if notional is None:
                o["cash_need"] = None
            elif o.get("side") == "BUY":
                o["cash_need"] = float(notional)
            elif o.get("side") == "SELL":
                o["cash_need"] = -float(notional)
            else:
                o["cash_need"] = 0.0
            if capital_usd and notional is not None and capital_usd > 0:
                o["cash_pct_of_capital"] = float(notional) / float(capital_usd)
            else:
                o["cash_pct_of_capital"] = None
            o["qty_note"] = "fractional" if fractional else "whole_share"
            if qty == 0 and o.get("side") == "BUY" and tw > 0:
                o["qty_note"] = "zero_after_round"
        else:
            o["target_qty"] = None
            o["current_qty"] = None
            o["qty"] = None
            o["notional"] = None
            o["cash_need"] = None
            o["cash_pct_of_capital"] = None
            o["qty_note"] = "no_price_or_capital"
    return orders


def validate_share_sizing(
    orders: List[Dict],
    capital_usd: Optional[float],
    cash_usd: Optional[float] = None,
) -> Dict:
    """Summarize sizing quality; never silent about zero-qty BUY names.

    Also surfaces cash vs buy-notional so TRADE can show how much cash is needed.
    """
    buys = [o for o in orders if o.get("side") == "BUY"]
    sells = [o for o in orders if o.get("side") == "SELL"]
    zero_buy = [o for o in buys if o.get("qty") in (0, None)]
    no_px = [o for o in orders if not o.get("est_px")]
    residual = [o for o in buys if o.get("qty_note") == "residual_1share"]
    below = [o for o in buys if o.get("qty_note") in ("below_1share", "zero_after_round")]
    buy_notional = 0.0
    sell_notional = 0.0
    for o in buys:
        if o.get("qty") not in (None, 0) and o.get("est_px"):
            buy_notional += float(o.get("notional") or (float(o["qty"]) * float(o["est_px"])))
    for o in sells:
        if o.get("qty") not in (None, 0) and o.get("est_px"):
            sell_notional += float(o.get("notional") or (float(o["qty"]) * float(o["est_px"])))
    spent = buy_notional
    net_cash_need = buy_notional - sell_notional  # positive = cash out
    cash_val = None
    if cash_usd is not None:
        try:
            cash_val = float(cash_usd)
            if cash_val != cash_val:  # NaN
                cash_val = None
            elif cash_val < 0:
                cash_val = 0.0
        except (TypeError, ValueError):
            cash_val = None
    cash_coverage = None
    cash_shortfall = None
    if cash_val is not None:
        if buy_notional > 0:
            cash_coverage = cash_val / buy_notional
        cash_shortfall = max(0.0, net_cash_need - cash_val)
    if cash_val is not None and cash_val > 0:
        for o in orders:
            n = o.get("notional")
            if n is None:
                o["cash_pct_of_cash"] = None
            elif o.get("side") == "BUY":
                o["cash_pct_of_cash"] = float(n) / cash_val
            else:
                o["cash_pct_of_cash"] = 0.0
    else:
        for o in orders:
            o["cash_pct_of_cash"] = None
    out = {
        "capital_usd": capital_usd,
        "cash_usd": cash_val,
                "n_buy": len(buys),
        "n_sell": len(sells),
        "n_buy_zero_qty": len(zero_buy),
        "n_no_price": len(no_px),
        "n_residual_1share": len(residual),
        "n_below_1share": len(below),
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "spent_notional": spent,
        "net_cash_need": net_cash_need,
        "cash_coverage": cash_coverage,
        "cash_shortfall": cash_shortfall,
        "residual_cash": (float(capital_usd) - spent) if capital_usd else None,
        "zero_buy_names": [str(o.get("name") or o.get("code")) for o in zero_buy[:12]],
        "no_price_codes": [str(o.get("code")) for o in no_px[:12]],
    }
    warns = []
    if capital_usd is None:
        warns.append("capital_missing")
    if no_px:
        warns.append(f"missing_price:{len(no_px)}")
    if below:
        warns.append(f"below_1share:{len(below)}")
    if residual:
        warns.append(f"residual_1share:{len(residual)}")
    if cash_val is not None and cash_shortfall is not None and cash_shortfall > 1.0:
        warns.append(f"cash_shortfall:{cash_shortfall:.0f}")
    out["warnings"] = warns
    return out



def _primary_sleeve(sleeves):
    order = {"leader": 0, "mom63": 1, "lowvol": 2}
    if not sleeves:
        return "other"
    return sorted(sleeves, key=lambda s: order.get(s, 9))[0]


def _sleeve_sort_key(sleeve_label: str) -> int:
    s = str(sleeve_label or "")
    parts = [p.strip() for p in s.replace("/", "+").split("+") if p.strip()]
    order = {"leader": 0, "mom63": 1, "lowvol": 2}
    if not parts:
        return 9
    return min(order.get(p, 9) for p in parts)


def classify_actions(
    target: Dict[str, float],
    current: Dict[str, float],
    band: float = 0.002,
    sleeve_of: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    keys = sorted(set(target) | set(current))
    rows = []
    sleeve_of = sleeve_of or {}
    for c in keys:
        tw = float(target.get(c, 0.0))
        cw = float(current.get(c, 0.0))
        dw = tw - cw
        if cw <= 0 and tw > 0:
            action, reason, side = "BUY_NEW", "NEW_ENTRY", "BUY"
        elif tw <= 0 and cw > 0:
            action, reason, side = "SELL_EXIT", "EXIT_SIGNAL", "SELL"
        elif abs(dw) <= band:
            action, reason, side = "HOLD", "REWEIGHT", "HOLD"
        elif dw > 0:
            action, reason, side = "BUY_ADD", "REWEIGHT", "BUY"
        else:
            # trim vs reweight
            if tw > 0:
                action, reason, side = "SELL_TRIM", "REWEIGHT", "SELL"
            else:
                action, reason, side = "SELL_EXIT", "EXIT_SIGNAL", "SELL"
        if tw > MAX_NAME + 1e-12 and action.startswith("BUY"):
            reason = "TRIM_CAP15"
        rows.append(
            {
                "code": c,
                "side": side,
                "action": action,
                "current_w": cw,
                "target_w": tw,
                "delta_w": dw,
                "reason": reason,
                "sleeve": sleeve_of.get(c, ""),
            }
        )
    # sell-first, then sleeve Leader→VM→Div, then larger target weight, then code
    side_prio = {"SELL": 0, "HOLD": 1, "BUY": 2}
    rows.sort(
        key=lambda r: (
            side_prio.get(r["side"], 9),
            _sleeve_sort_key(r.get("sleeve", "")),
            -float(r.get("target_w") or 0.0),
            r["code"],
        )
    )
    for i, r in enumerate(rows, 1):
        r["prio"] = i
    return rows


def write_outputs(
    out_dir: Path,
    signal_date: pd.Timestamp,
    picks: Dict[str, List[str]],
    final_w: Dict[str, float],
    name_map: Dict[str, str],
    sector_map: Dict[str, str],
    sm: Dict[str, Dict[str, float]],
    orders: List[Dict],
    health: Dict,
    regime: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # signals
    sig_rows = []
    for sleeve, codes in picks.items():
        for i, c in enumerate(codes, 1):
            sig_rows.append(
                {
                    "asof": str(signal_date.date()),
                    "code": c,
                    "name": name_map.get(c, ""),
                    "sector": sector_map.get(c, ""),
                    "sleeve": sleeve,
                    "rank": i,
                    "score": sm.get(sleeve, {}).get(c, np.nan),
                    "selected": "Y",
                    "regime": regime,
                }
            )
    # also mark non-selected current? only selected for now
    atomic_write_csv(pd.DataFrame(sig_rows), out_dir / "signals.csv")

    tgt_rows = []
    for c, w in final_w.items():
        sleeves = [s for s, codes in picks.items() if c in codes]
        primary = _primary_sleeve(sleeves)
        tgt_rows.append(
            {
                "asof": str(signal_date.date()),
                "code": c,
                "name": name_map.get(c, ""),
                "sector": sector_map.get(c, ""),
                "sleeve": "+".join(sleeves) if sleeves else "",
                "primary_sleeve": primary,
                "final_w": w,
            }
        )
    tgt_rows.sort(
        key=lambda r: (
            _sleeve_sort_key(r.get("primary_sleeve", "")),
            -float(r.get("final_w") or 0.0),
            r["code"],
        )
    )
    atomic_write_csv(
        pd.DataFrame(tgt_rows).drop(columns=["primary_sleeve"], errors="ignore"),
        out_dir / "target.csv",
    )

    ord_df = pd.DataFrame(orders)
    if not ord_df.empty:
        ord_df.insert(0, "asof", str(signal_date.date()))
        if "name" not in ord_df.columns:
            ord_df["name"] = ord_df["code"].map(lambda x: name_map.get(x, ""))
    atomic_write_csv(ord_df, out_dir / "orders_preview.csv")
    atomic_write_json(out_dir / "health.json", scrub_health_legacy(health))
    write_package_manifest(out_dir)


def validate_target(final_w: Dict[str, float]) -> None:
    if not final_w:
        raise AssertionError("empty target weights")
    s = float(sum(final_w.values()))
    if s <= 0:
        raise AssertionError(f"weight sum {s} <= 0")
    if s > 1.0 + 1e-4:
        raise AssertionError(f"weight sum {s} > 1")
    # s < 1 is allowed (residual cash from empty sleeve / name-cap leftover)
    mx = max(final_w.values())
    if mx > MAX_NAME + 1e-9:
        raise AssertionError(f"max name weight {mx} > {MAX_NAME}")
    for c in final_w:
        sym = normalize_symbol(c)
        if not sym or not any(ch.isalpha() for ch in sym):
            raise AssertionError(f"bad US symbol {c}")

def rebuild_rebalance_ticket(
    run_dir: Path | str,
    *,
    positions: Optional[str] = "toss",
    capital_usd: Optional[float] = None,
    risk_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Rebuild sell-first order ticket from frozen target + live book.

    Does NOT re-select names (monthly signal stays frozen).
    Updates:
      - orders_preview.csv  (qty / notional / cash_need)
      - health.json         (sizing + toss snapshot)
    Excel is refreshed by caller via write_ops_xlsx / sync_ops_excel.
    """
    run_dir = Path(run_dir)
    target_path = run_dir / "target.csv"
    health_path = run_dir / "health.json"
    if not target_path.exists():
        raise FileNotFoundError(f"missing target.csv in {run_dir} (run monthly first)")
    if not health_path.exists():
        raise FileNotFoundError(f"missing health.json in {run_dir} (run monthly first)")

    target_df = pd.read_csv(target_path)
    if target_df.empty or "code" not in target_df.columns:
        raise ValueError("target.csv empty or missing code")
    wcol = "final_w" if "final_w" in target_df.columns else None
    if wcol is None:
        for c in target_df.columns:
            if c.lower() in {"weight", "w", "target_w"}:
                wcol = c
                break
    if wcol is None:
        raise ValueError("target.csv needs final_w (or weight)")

    target_df["code"] = target_df["code"].map(normalize_symbol)
    final_w: Dict[str, float] = {
        normalize_symbol(r["code"]): float(r[wcol])
        for _, r in target_df.iterrows()
        if float(r[wcol]) > 0 and normalize_symbol(r["code"])
    }
    sleeve_of: Dict[str, str] = {}
    if "sleeve" in target_df.columns:
        for _, r in target_df.iterrows():
            sleeve_of[normalize_symbol(r["code"])] = str(r.get("sleeve") or "")
    name_map: Dict[str, str] = {}
    if "name" in target_df.columns:
        for _, r in target_df.iterrows():
            name_map[normalize_symbol(r["code"])] = str(r.get("name") or "")

    health = json.loads(health_path.read_text(encoding="utf-8"))
    signal_date = pd.Timestamp(health.get("signal_date") or target_df.get("asof", pd.Series([None])).iloc[0])
    if pd.isna(signal_date):
        signal_date = pd.Timestamp.now().normalize()

    # live book -> current weights
    # clear previous process stash
    if hasattr(load_positions, "last_toss_book"):
        try:
            delattr(load_positions, "last_toss_book")
        except Exception:
            pass
    current = load_positions(positions)
    book = getattr(load_positions, "last_toss_book", None)
    live_px = {}
    live_qty = {}
    if book is not None:
        from ops.toss_portfolio import toss_last_prices, toss_qty_map

        live_px = toss_last_prices(book)
        live_qty = toss_qty_map(book)

    applied_risk_mode = None
    if risk_mode is not None:
        applied_risk_mode = resolve_risk_mode(risk_mode, str((book or {}).get("account_no_tail") or "unknown"))
        final_w = apply_risk_weights(final_w, applied_risk_mode)
        health["manual_risk_mode"] = applied_risk_mode

    orders = classify_actions(final_w, current, sleeve_of=sleeve_of)
    for o in orders:
        o["name"] = name_map.get(o["code"], o.get("name") or "")

    # prices for qty sizing (panel: MultiIndex date/Code, OHLCV columns)
    # prices for qty sizing from US close cache / parquet
    if _LAST_CLOSE is not None and not _LAST_CLOSE.empty:
        close = _LAST_CLOSE.copy()
        close.index = pd.to_datetime(close.index)
        close.columns = [normalize_symbol(c) for c in close.columns]
    else:
        from ops.us_hybrid_backtest import CACHE_PRICES

        if not CACHE_PRICES.exists():
            raise FileNotFoundError(f"missing US prices panel: {CACHE_PRICES}")
        close = pd.read_parquet(CACHE_PRICES)
        close.index = pd.to_datetime(close.index)
        close.columns = [normalize_symbol(c) for c in close.columns]

    cap, cap_src = resolve_capital_usd(book=book, capital_usd=capital_usd)
    open_px = None
    try:
        from ops.us_hybrid_backtest import CACHE_OPEN

        if CACHE_OPEN.exists():
            open_px = pd.read_parquet(CACHE_OPEN)
            open_px.index = pd.to_datetime(open_px.index)
            open_px.columns = [normalize_symbol(c) for c in open_px.columns]
    except Exception:
        open_px = _LAST_OPEN

    orders = attach_share_sizes(
        orders,
        close,
        cap,
        capital_source=cap_src,
        signal_date=signal_date if signal_date in close.index else None,
        fractional=FRACTIONAL_SHARES_DEFAULT,
        live_px=live_px,
        live_qty=live_qty,
        open_px=open_px,
    )
    cash_for_size = None
    if book is not None:
        try:
            cash_for_size = float(book.get("cash_usd") or book.get("cash_buying_power_usd") or 0.0)
        except (TypeError, ValueError):
            cash_for_size = None
    sizing = validate_share_sizing(orders, cap, cash_usd=cash_for_size)

    sizing_errors = []
    if cap and sizing["n_buy"] > 0 and sizing["n_buy_zero_qty"] == sizing["n_buy"]:
        sizing_errors.append("all_buy_qty_zero")
    if cap and sizing["n_no_price"] > 0:
        sizing_errors.append("missing_prices")
    if cap and float(sizing.get("spent_notional") or 0) <= 0 and sizing["n_buy"] > 0:
        sizing_errors.append("zero_notional")
    sizing["errors"] = sizing_errors

    # write orders
    ord_df = pd.DataFrame(orders)
    if not ord_df.empty:
        ord_df.insert(0, "asof", str(pd.Timestamp(signal_date).date()))
        if "name" not in ord_df.columns:
            ord_df["name"] = ord_df["code"].map(lambda x: name_map.get(normalize_symbol(x), ""))
    atomic_write_csv(ord_df, run_dir / "orders_preview.csv")

    # patch health (keep selection/lags; refresh sizing + toss)
    health["capital_usd"] = cap
    health["capital_source"] = cap_src
    health["sizing"] = sizing
    health["rebalance"] = {
        "mode": "ticket_rebuild",
        "positions": positions,
        "n_orders": len(orders),
        "n_buy": sizing.get("n_buy"),
        "n_sell": sizing.get("n_sell"),
        "buy_notional": sizing.get("buy_notional"),
        "sell_notional": sizing.get("sell_notional"),
        "net_cash_need": sizing.get("net_cash_need"),
        "cash_usd": sizing.get("cash_usd"),
        "cash_coverage": sizing.get("cash_coverage"),
        "cash_shortfall": sizing.get("cash_shortfall"),
        "updated_local": pd.Timestamp.now().isoformat(timespec="seconds"),
        "no_broker_send": True,
        "exec_rule": EXEC_RULE,
    }
    # drop prior sizing reasons then re-add
    reasons = [r for r in (health.get("reasons") or []) if not str(r).startswith("sizing:")]
    if sizing_errors:
        reasons.extend([f"sizing:{e}" for e in sizing_errors])
        if health.get("status") == "OK":
            health["status"] = "WARN"
    health["reasons"] = reasons

    if positions and str(positions).strip().lower() in {"toss", "toss://", "toss:live"} and book:
        health["toss"] = {
            "status": book.get("status"),
            "account_no_tail": book.get("account_no_tail"),
            "n_us": book.get("n_us"),
            "n_kr": book.get("n_kr"),
            "ops_ready": book.get("ops_ready"),
            "flat": book.get("flat"),
            "equity_usd": book.get("equity_usd"),
            "cash_usd": book.get("cash_usd"),
            "cash_buying_power_usd": book.get("cash_buying_power_usd"),
            "total_usd": book.get("total_usd"),
            "capital_usd": cap,
            "capital_source": cap_src,
        }

    atomic_write_json(health_path, scrub_health_legacy(health))

    n_sell = int(sizing.get("n_sell") or 0)
    n_buy = int(sizing.get("n_buy") or 0)
    summary = {
        "run_dir": str(run_dir),
        "signal_date": str(pd.Timestamp(signal_date).date()),
        "positions": positions,
        "n_target": len(final_w),
        "n_current": len(current),
        "n_sell": n_sell,
        "n_buy": n_buy,
        "n_hold": sum(1 for o in orders if o.get("side") == "HOLD"),
        "capital_usd": cap,
        "capital_source": cap_src,
        "cash_usd": sizing.get("cash_usd"),
        "buy_notional": sizing.get("buy_notional"),
        "sell_notional": sizing.get("sell_notional"),
        "net_cash_need": sizing.get("net_cash_need"),
        "cash_coverage": sizing.get("cash_coverage"),
        "cash_shortfall": sizing.get("cash_shortfall"),
        "health_status": health.get("status"),
        "risk_mode": applied_risk_mode,
        "orders_path": str(run_dir / "orders_preview.csv"),
        "xlsx_hint": str(run_dir / f"US_Robust_Ops_{run_dir.name}.xlsx"),
        "broker_send": False,
        "exec_rule": EXEC_RULE,
        "human_steps": [
            "open Excel 01_Portfolio_Now + 05_Trade",
            "approve ticket",
            "HTS: SELL first, then BUY (NEXT_OPEN)",
            "book fills manually",
        ],
    }
    (run_dir / "rebalance_ticket.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary

def run(
    asof: Optional[str] = None,
    top_n: int = TOP_N_DEFAULT,
    positions: Optional[str] = "toss",
    out_dir: Optional[str] = None,
    refresh_data: bool = False,
    write_xlsx: bool = True,
    capital_usd: Optional[float] = None,
    force_intramonth: bool = False,
) -> Path:
    """Run monthly select/weight/orders/health and autofill Excel by default."""
    if refresh_data:
        print("NOTE: --refresh-data is deprecated here; use `python ops.py refresh` instead.")

    print("step 2/5 종목 선정")
    close, volume, index_close, regime, feats, frgn_feats, val, meta, name_map, sector_map, frgn = load_market(top_n)
    signal_date = pick_signal_date(close, asof)
    assert_final_month_end_signal(
        signal_date,
        close,
        asof=asof,
        force_intramonth=force_intramonth,
    )
    picks, final_w, name_w, reg = build_target(signal_date, feats, frgn_feats, val, regime)
    sm = score_maps(signal_date, feats, frgn_feats, val_snap_on(val, signal_date))
    print(
        f"  signal_date={signal_date.date()}  "
        f"leader={len(picks.get('leader', []))} "
        f"mom63={len(picks.get('mom63', []))} "
        f"lowvol={len(picks.get('lowvol', []))}"
    )

    print("step 3/5 비중 계산 (equal L60/M63/LV20 + cap15)")
    print(f"  n_names={len(final_w)} weight_sum={sum(final_w.values()):.6f} max_name={max(final_w.values()) if final_w else None}")

    print("step 4/5 주문 미리보기")
    current = load_positions(positions)
    sleeve_of = {}
    for c in final_w:
        sleeves = [s for s, codes in picks.items() if c in codes]
        sleeve_of[c] = _primary_sleeve(sleeves)
    orders = classify_actions(final_w, current, sleeve_of=sleeve_of)
    for o in orders:
        o["name"] = name_map.get(o["code"], "")
    book = getattr(load_positions, "last_toss_book", None)
    live_px = {}
    live_qty = {}
    if book is not None:
        from ops.toss_portfolio import toss_last_prices, toss_qty_map

        live_px = toss_last_prices(book)
        live_qty = toss_qty_map(book)
    cap, cap_src = resolve_capital_usd(book=book, capital_usd=capital_usd)
    orders = attach_share_sizes(
        orders, close, cap, capital_source=cap_src, signal_date=signal_date,
        fractional=FRACTIONAL_SHARES_DEFAULT, live_px=live_px, live_qty=live_qty,
        open_px=_LAST_OPEN,
    )
    cash_for_size = None
    if book is not None:
        try:
            cash_for_size = float(book.get("cash_usd") or book.get("cash_buying_power_usd") or 0.0)
        except (TypeError, ValueError):
            cash_for_size = None
    sizing = validate_share_sizing(orders, cap, cash_usd=cash_for_size)
    n_sell = sum(1 for o in orders if o.get("side") == "SELL")
    n_buy = sum(1 for o in orders if o.get("side") == "BUY")
    n_qty = sum(1 for o in orders if o.get("qty") not in (None, 0))
    print(f"  orders sell={n_sell} buy={n_buy} hold/other={len(orders)-n_sell-n_buy}")
    if cap:
        cov = sizing.get("cash_coverage")
        cov_s = f"{cov * 100:.1f}%" if cov is not None else "n/a"
        print(
            "  sizing capital_usd={:,.0f} source={} cash_usd={:,.2f} buy_USD={:,.0f} sell_USD={:,.0f} "
            "net_need={:,.0f} cash_cover={} buy_with_qty={}/{} residual={:,.0f}".format(
                cap,
                cap_src,
                float(sizing.get("cash_usd") or 0.0),
                float(sizing.get("buy_notional") or 0.0),
                float(sizing.get("sell_notional") or 0.0),
                float(sizing.get("net_cash_need") or 0.0),
                cov_s,
                n_qty,
                n_buy,
                sizing["residual_cash"] if sizing["residual_cash"] is not None else 0.0,
            )
        )
    else:
        print("  sizing capital_usd=None (set OPS_CAPITAL_USD or --capital to size shares)")
    if sizing["warnings"]:
        print("  sizing_warn", ",".join(sizing["warnings"]))
    if sizing["zero_buy_names"]:
        print("  zero_qty_buys", ", ".join(sizing["zero_buy_names"]))
    if sizing["no_price_codes"]:
        print("  no_price_codes", ", ".join(sizing["no_price_codes"]))
    # Hard consistency checks (fail loud in health, not silent)
    sizing_errors = []
    if cap and sizing["n_buy"] > 0 and sizing["n_buy_zero_qty"] == sizing["n_buy"]:
        sizing_errors.append("all_buy_qty_zero")
    if cap and sizing["n_no_price"] > 0:
        sizing_errors.append("missing_prices")
    if cap and sizing.get("spent_notional", 0) <= 0 and sizing["n_buy"] > 0:
        sizing_errors.append("zero_notional")
    sizing["errors"] = sizing_errors
    if sizing_errors:
        print("  sizing_ERROR", ",".join(sizing_errors))

    print("step 5/5 헬스 체크 + 산출 저장")
    health = build_health(
        signal_date, close, frgn, val, index_close, picks, final_w, sector_map,
        reference_date=(asof or ny_today()), universe_n=len(meta), universe_target=top_n,
    )
    health["force_intramonth"] = bool(force_intramonth)
    health["capital_usd"] = cap
    health["capital_source"] = cap_src
    health["sizing"] = sizing
    if sizing.get("errors"):
        health.setdefault("reasons", []).extend([f"sizing:{e}" for e in sizing["errors"]])
        # keep status unless already BLOCK; sizing issues are WARN-level by default
        if health.get("status") == "OK":
            health["status"] = "WARN"
    # attach toss status into health for excel (no secrets)
    if positions and str(positions).strip().lower() in {"toss", "toss://", "toss:live"}:
        book = getattr(load_positions, "last_toss_book", None)
    live_px = {}
    live_qty = {}
    if book is not None:
        from ops.toss_portfolio import toss_last_prices, toss_qty_map

        live_px = toss_last_prices(book)
        live_qty = toss_qty_map(book)
        if book:
            health["toss"] = {
                "status": book.get("status"),
                "account_no_tail": book.get("account_no_tail"),
                "n_us": book.get("n_us"),
                "n_kr": book.get("n_kr"),
                "ops_ready": book.get("ops_ready"),
                "flat": book.get("flat"),
                "equity_usd": book.get("equity_usd"),
                "cash_usd": book.get("cash_usd"),
                "cash_buying_power_usd": book.get("cash_buying_power_usd"),
                "total_usd": book.get("total_usd"),
                "capital_usd": cap,
                "capital_source": cap_src,
            }

    yyyymm = f"{signal_date.year:04d}-{signal_date.month:02d}"
    dest = Path(out_dir) if out_dir else (OUT_ROOT / yyyymm)
    write_outputs(dest, signal_date, picks, final_w, name_map, sector_map, sm, orders, health, reg)

    if health["status"] != "BLOCK":
        validate_target(final_w)
    else:
        if final_w:
            try:
                validate_target(final_w)
            except AssertionError as e:
                health["reasons"].append(f"validate:{e}")
                (dest / "health.json").write_text(json.dumps(scrub_health_legacy(health), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  health={health['status']} out={dest}")
    if write_xlsx:
        from ops.ops_excel_write import write_ops_xlsx

        toss_book = getattr(load_positions, "last_toss_book", None)
        xpath = write_ops_xlsx(dest, positions=positions, toss_book=toss_book)
        print(f"  excel={xpath}")
    else:
        print("  excel=skipped (--no-xlsx)")

    if health["status"] == "BLOCK":
        print("HEALTH BLOCK:", ",".join(health["reasons"]))
        raise SystemExit(2)
    return dest


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        description="US Robust monthly ops runner (data/us). Prefer: python ops.py monthly",
    )
    p.add_argument("--asof", default=None, help="YYYY-MM-DD upper bound for signal month-end")
    p.add_argument("--top-n", type=int, default=TOP_N_DEFAULT)
    p.add_argument(
        "--positions",
        default="toss",
        help="default 'toss'; CSV path; or 'none' for empty book",
    )
    p.add_argument("--out-dir", default=None)
    p.add_argument("--refresh-data", action="store_true", default=False, help="deprecated; use ops.py refresh")
    p.add_argument(
        "--force-intramonth",
        action="store_true",
        help="research only: allow incomplete current-month signal (overwrites target)",
    )
    p.add_argument("--capital", type=float, default=None, help="USD capital for share qty sizing")
    p.add_argument(
        "--write-xlsx",
        dest="write_xlsx",
        action="store_true",
        default=True,
        help="fill Excel copy under run dir (default: on)",
    )
    p.add_argument(
        "--no-xlsx",
        dest="write_xlsx",
        action="store_false",
        help="skip Excel autofill",
    )
    args = p.parse_args(argv)
    run(
        asof=args.asof,
        top_n=args.top_n,
        positions=args.positions,
        out_dir=args.out_dir,
        refresh_data=args.refresh_data,
        write_xlsx=args.write_xlsx,
        capital_usd=getattr(args, "capital", None),
        force_intramonth=bool(getattr(args, "force_intramonth", False)),
    )


if __name__ == "__main__":
    main()
