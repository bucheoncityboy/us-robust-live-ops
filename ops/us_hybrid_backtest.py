"""
US Market 3-Sleeve Hybrid — Strict Backtest
===========================================
Architecture mirrored from KR hybrid:
  Leader 55% / ValueMomentum 25% / Accumulation-Divergence 20%

US adaptations:
  - Universe: S&P 500 liquid names (yfinance)
  - Benchmark: SPY
  - Foreign net-buy sleeve → price–volume accumulation divergence
    (smart-money proxy available on US without KR foreign flow data)
  - Cost baseline 10bp round-trip (US liquid large-cap); stress 20bp
  - Signal at month-end Close → execute Next Open
  - SCORE within-sleeve weights, name cap 15%
  - IS/OOS, walk-forward, bootstrap, gate protocol
"""

from __future__ import annotations

import json
import math
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except ImportError as e:
    raise SystemExit("yfinance required: pip install yfinance") from e

try:
    import FinanceDataReader as fdr
except ImportError:
    fdr = None


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "us"
OUT = ROOT / "results" / "us_strict"
CHART = OUT / "charts"

CACHE_META = DATA / "us_universe_meta.parquet"
CACHE_PRICES = DATA / "us_prices_panel.parquet"
CACHE_OPEN = DATA / "us_open_panel.parquet"
CACHE_INDEX = DATA / "spy.parquet"
CACHE_FUND = DATA / "us_fundamentals.parquet"
CACHE_VAL = DATA / "us_valuation_panel.parquet"

SEED = 1_000_000.0  # USD notional
COST_BASE = 0.0010  # 10bp round-trip
COST_STRESS = 0.0020  # 20bp stress
MIN_AMT = 50_000_000  # $50M avg dollar volume
MIN_PRICE = 5.0
TOP_N = 150
N_LEADER = 10
N_VALUE = 10
N_DIV = 8
MAX_NAME = 0.15
W_LEADER = 0.55
W_VALUE = 0.25
W_DIV = 0.20
START = "2018-01-01"
# Live-ops SoT: None => download through latest available session.
# yfinance end is exclusive, so resolved as (today + 1 day).
END = None
RESEARCH_END = "2026-06-30"  # optional frozen research window only
IS_END = "2023-12-31"


def resolve_end(end=None) -> str:
    """Return yfinance-exclusive end date string for live downloads."""
    if end:
        return str(pd.Timestamp(end).date())
    # tomorrow exclusive => includes today's bar when available
    return (pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def cache_is_stale(index, max_lag_days: int = 5) -> bool:
    if index is None or len(index) == 0:
        return True
    last = pd.Timestamp(pd.DatetimeIndex(index).max()).normalize()
    # weekends/holidays: allow a few calendar days; beyond that force refresh
    return (pd.Timestamp.today().normalize() - last).days > int(max_lag_days)
FUND_LAG_DAYS = 90
BOOT_N = 1000
BOOT_SEED = 42


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def month_ends(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(1, index=dates)
    me = s.resample("ME").last().index
    out = []
    for d in me:
        elig = dates[dates <= d]
        if len(elig):
            out.append(elig[-1])
    return pd.DatetimeIndex(sorted(set(out)))


def next_open_map(close_idx: pd.DatetimeIndex, open_px: pd.DataFrame) -> Dict[pd.Timestamp, pd.Timestamp]:
    """Map signal date (close) -> next trading day with usable open prices.

    Uses open_px when provided: skip days where every open is missing/non-positive.
    Falls back to next close-calendar day if open_px is empty/None.
    """
    days = list(pd.DatetimeIndex(close_idx))
    out: Dict[pd.Timestamp, pd.Timestamp] = {}
    has_open = None
    if open_px is not None and len(getattr(open_px, "index", [])) > 0:
        op = open_px.copy()
        op.index = pd.to_datetime(op.index).tz_localize(None)
        has_open = (op.notna() & (op > 0)).any(axis=1)
    for i, d in enumerate(days):
        j = i + 1
        while j < len(days):
            cand = days[j]
            if has_open is None:
                out[d] = cand
                break
            if cand in has_open.index and bool(has_open.loc[cand]):
                out[d] = cand
                break
            j += 1
    return out

def perf(eq: pd.Series, rets: pd.Series, b_rets: pd.Series, label: str) -> Dict:
    if eq is None or len(eq) < 2:
        return {"strategy": label, "cagr": None, "sharpe": None, "mdd": None}
    r = rets.dropna()
    years = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)
    vol = float(r.std() * math.sqrt(252))
    sharpe = float((r.mean() * 252) / vol) if vol > 0 else np.nan
    mdd = float((eq / eq.cummax() - 1).min())
    calmar = float(cagr / abs(mdd)) if mdd < 0 else np.nan
    b = b_rets.reindex(r.index).fillna(0.0)
    excess = r - b
    te = float(excess.std() * math.sqrt(252))
    info = float((excess.mean() * 252) / te) if te > 0 else np.nan
    var_b = float(np.var(b))
    beta = float(np.cov(r, b)[0, 1] / var_b) if var_b > 0 else np.nan
    alpha = float((r.mean() - beta * b.mean()) * 252) if beta == beta else np.nan
    monthly = eq.resample("ME").last().pct_change().dropna()
    win_m = float((monthly > 0).mean()) if len(monthly) else np.nan
    return {
        "strategy": label,
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "years": round(float(years), 2),
        "total_return": round(total, 4),
        "cagr": round(cagr, 4),
        "vol": round(vol, 4),
        "sharpe": round(sharpe, 3) if sharpe == sharpe else None,
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 3) if calmar == calmar else None,
        "win_month": round(win_m, 3) if win_m == win_m else None,
        "info_ratio": round(info, 3) if info == info else None,
        "alpha": round(alpha, 4) if alpha == alpha else None,
        "beta": round(beta, 3) if beta == beta else None,
        "final_equity": round(float(eq.iloc[-1]), 2),
    }


def weights_equal(codes: List[str]) -> Dict[str, float]:
    if not codes:
        return {}
    w = 1.0 / len(codes)
    return {c: w for c in codes}


def weights_score(codes: List[str], score_map: Dict[str, float]) -> Dict[str, float]:
    if not codes:
        return {}
    s = pd.Series({c: float(score_map.get(c, np.nan)) for c in codes}, dtype=float)
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return weights_equal(codes)
    # rank-based positive weights
    r = s.rank(method="average", ascending=True)
    r = r / r.sum()
    return r.to_dict()


def merge_sleeve_weights(sleeve_w: Dict[str, float],
                         name_w: Dict[str, Dict[str, float]],
                         max_name: Optional[float] = None) -> Dict[str, float]:
    """Merge sleeve name-weights.

    Empty sleeves should be zeroed by caller (and moved to cash) - this function
    does NOT silently renormalize missing sleeve mass into other sleeves.

    After name-cap, leftover mass that cannot be redistributed remains as
    residual cash (weights may sum to < 1).
    """
    raw: Dict[str, float] = {}
    for sleeve, sw in sleeve_w.items():
        if sleeve == "cash" or sw <= 0:
            continue
        nw = name_w.get(sleeve, {}) or {}
        if not nw:
            continue
        for c, w in nw.items():
            raw[c] = raw.get(c, 0.0) + float(sw) * float(w)
    if not raw:
        return {}
    cash_w = float(sleeve_w.get("cash", 0.0) or 0.0)
    invested = float(sum(raw.values()))
    target_invest = max(0.0, 1.0 - cash_w)
    if invested > 0 and abs(invested - target_invest) <= 1e-10:
        final = {c: (v / invested) * target_invest for c, v in raw.items()}
    else:
        final = {c: float(v) for c, v in raw.items()}
    if max_name is not None and max_name > 0:
        for _ in range(16):
            over = {c: w for c, w in final.items() if w > max_name + 1e-12}
            if not over:
                break
            excess = sum(w - max_name for w in over.values())
            for c in over:
                final[c] = max_name
            under = {c: w for c, w in final.items() if w < max_name - 1e-12}
            usum = sum(under.values())
            if usum <= 0 or excess <= 0:
                break
            for c in under:
                final[c] += excess * (under[c] / usum)
    return {c: float(w) for c, w in final.items() if float(w) > 0}

def turnover(prev: Dict[str, float], new: Dict[str, float]) -> float:
    keys = set(prev) | set(new)
    return 0.5 * sum(abs(new.get(k, 0.0) - prev.get(k, 0.0)) for k in keys)


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

def build_universe(top_n: int = TOP_N, force_refresh: bool = False) -> pd.DataFrame:
    DATA.mkdir(parents=True, exist_ok=True)
    if CACHE_META.exists() and not force_refresh:
        meta = pd.read_parquet(CACHE_META)
        if len(meta) < top_n:
            print(f"[meta] WARN cached shortfall n={len(meta)}/{top_n}")
        else:
            print(f"[meta] cached n={len(meta)}")
        return meta.head(top_n).reset_index(drop=True)

    if fdr is None:
        raise SystemExit("FinanceDataReader required for S&P500 listing")
    lst = fdr.StockListing("S&P500").copy()
    lst = lst.rename(columns={"Symbol": "Code"})
    lst["Code"] = lst["Code"].astype(str).str.replace(".", "-", regex=False)
    # rough liquidity/marcap proxy via yfinance info is slow; use equal listing order + filter later by amt
    # fetch recent market caps in batches
    codes = lst["Code"].tolist()
    caps = {}
    print(f"[meta] fetching market caps for {len(codes)} names...")
    for i in range(0, len(codes), 40):
        batch = codes[i:i + 40]
        try:
            data = yf.download(
                batch, period="5d", group_by="ticker", threads=True,
                progress=False, auto_adjust=True,
            )
        except Exception as e:
            print(f"  cap batch fail: {e}")
            time.sleep(1)
            continue
        for c in batch:
            try:
                if len(batch) == 1:
                    px = float(data["Close"].dropna().iloc[-1])
                    vol = float(data["Volume"].dropna().iloc[-1]) if "Volume" in data else np.nan
                else:
                    if c not in data.columns.get_level_values(0):
                        continue
                    sub = data[c]
                    px = float(sub["Close"].dropna().iloc[-1])
                    vol = float(sub["Volume"].dropna().iloc[-1]) if "Volume" in sub else np.nan
                caps[c] = px * vol  # dollar volume proxy for ranking
            except Exception:
                continue
        time.sleep(0.2)
    lst["DollarVolProxy"] = lst["Code"].map(caps)
    lst = lst.dropna(subset=["DollarVolProxy"])
    lst = lst.sort_values("DollarVolProxy", ascending=False).head(top_n).reset_index(drop=True)
    if len(lst) < min(top_n, 100):
        raise RuntimeError(f"universe refresh too small: {len(lst)}/{top_n}; existing cache preserved")
    tmp_meta = CACHE_META.with_suffix(CACHE_META.suffix + ".tmp")
    lst.to_parquet(tmp_meta, index=False)
    tmp_meta.replace(CACHE_META)
    print(f"[meta] saved n={len(lst)}")
    return lst


def _download_ohlcv(codes: List[str], start: str, end: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return close/open/volume wide panels.

    yfinance column layouts vary by version/count:
      - flat: Close/Open/Volume
      - MultiIndex ticker-first (group_by=ticker): (Ticker, Price)
      - MultiIndex price-first (default): (Price, Ticker)
    Handle all three; never crash the refresh on a single bad ticker.
    """
    print(f"[prices] downloading {len(codes)} tickers {start}~{end}")
    empty = (
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
    )
    try:
        raw = yf.download(
            codes, start=start, end=end, group_by="ticker",
            threads=True, progress=False, auto_adjust=True,
        )
    except Exception as e:
        print(f"[prices] download failed: {type(e).__name__}: {e}")
        return empty
    if raw is None or getattr(raw, "empty", True):
        print("[prices] download returned empty")
        return empty

    close_cols, open_cols, vol_cols = {}, {}, {}
    price_names = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}

    def _take(frame_or_series, field: str):
        if isinstance(frame_or_series, pd.Series):
            return frame_or_series if field == "Close" else None
        if field in frame_or_series.columns:
            return frame_or_series[field]
        return None

    if not isinstance(raw.columns, pd.MultiIndex):
        # Flat OHLCV — typically one ticker
        if "Close" in raw.columns and len(codes) == 1:
            c = codes[0]
            close_cols[c] = raw["Close"]
            open_cols[c] = raw["Open"] if "Open" in raw.columns else raw["Close"] * np.nan
            vol_cols[c] = raw["Volume"] if "Volume" in raw.columns else raw["Close"] * np.nan
    else:
        lvl0 = set(map(str, raw.columns.get_level_values(0)))
        lvl1 = set(map(str, raw.columns.get_level_values(1)))
        ticker_first = bool(lvl0 & set(map(str, codes))) and not bool(lvl0 & price_names)
        price_first = bool(lvl0 & price_names)
        for c in codes:
            try:
                if ticker_first:
                    if c not in raw.columns.get_level_values(0):
                        continue
                    sub = raw[c]
                    cl = _take(sub, "Close")
                    op = _take(sub, "Open")
                    vo = _take(sub, "Volume")
                elif price_first:
                    if c not in raw.columns.get_level_values(1):
                        continue
                    cl = raw[("Close", c)] if ("Close", c) in raw.columns else None
                    op = raw[("Open", c)] if ("Open", c) in raw.columns else None
                    vo = raw[("Volume", c)] if ("Volume", c) in raw.columns else None
                else:
                    # fallback: try ticker-first then price-first
                    if c in raw.columns.get_level_values(0):
                        sub = raw[c]
                        cl = _take(sub, "Close")
                        op = _take(sub, "Open")
                        vo = _take(sub, "Volume")
                    elif ("Close", c) in raw.columns:
                        cl = raw[("Close", c)]
                        op = raw[("Open", c)] if ("Open", c) in raw.columns else None
                        vo = raw[("Volume", c)] if ("Volume", c) in raw.columns else None
                    else:
                        continue
                if cl is None:
                    continue
                close_cols[c] = cl
                open_cols[c] = op if op is not None else cl * np.nan
                vol_cols[c] = vo if vo is not None else cl * np.nan
            except Exception:
                continue

    if not close_cols:
        print("[prices] no usable Close columns parsed")
        return empty

    close = pd.DataFrame(close_cols).sort_index()
    open_ = pd.DataFrame(open_cols).sort_index()
    volume = pd.DataFrame(vol_cols).sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    open_.index = pd.to_datetime(open_.index).tz_localize(None)
    volume.index = pd.to_datetime(volume.index).tz_localize(None)
    # drop thin history; backfill may keep short IPOs if threshold soft-failed elsewhere
    min_obs = 60 if len(codes) <= 3 else 400
    valid = close.notna().sum() >= min_obs
    dropped = [c for c, ok in valid.items() if not ok]
    if dropped:
        print(f"[prices] drop thin history (<{min_obs} obs): {dropped}")
    close = close.loc[:, valid]
    open_ = open_.reindex(columns=close.columns)
    volume = volume.reindex(columns=close.columns)
    if close.empty:
        print("[prices] all columns dropped as thin")
        return empty
    print(f"[prices] shape={close.shape} {close.index.min().date()}~{close.index.max().date()}")
    return close, open_, volume


def load_prices(codes: List[str], force: bool = False) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load OHLCV panels; on cache-hit still backfill any missing requested codes."""
    DATA.mkdir(parents=True, exist_ok=True)
    end = resolve_end(END)
    codes = [str(c) for c in codes]
    vol_path = DATA / "us_volume_panel.parquet"

    if CACHE_PRICES.exists() and CACHE_OPEN.exists() and not force:
        close = pd.read_parquet(CACHE_PRICES)
        open_ = pd.read_parquet(CACHE_OPEN)
        if vol_path.exists():
            volume = pd.read_parquet(vol_path)
        else:
            volume = close * np.nan
        close.columns = [str(c) for c in close.columns]
        open_.columns = [str(c) for c in open_.columns]
        volume.columns = [str(c) for c in volume.columns]
        use = [c for c in codes if c in close.columns]
        missing = [c for c in codes if c not in close.columns]
        stale = cache_is_stale(close.index)
        if len(use) >= min(80, max(1, len(codes) // 2)) and not stale:
            if missing:
                print(f"[prices] cache hit but missing {len(missing)} codes -> backfill {missing[:8]}")
                add_c, add_o, add_v = _download_ohlcv(missing, START, end)
                if add_c is not None and not add_c.empty:
                    close = close.join(add_c, how="outer")
                    open_ = open_.join(add_o, how="outer")
                    volume = volume.join(add_v, how="outer")
                    close.to_parquet(CACHE_PRICES)
                    open_.to_parquet(CACHE_OPEN)
                    volume.to_parquet(vol_path)
                    use = [c for c in codes if c in close.columns]
                    still = [c for c in codes if c not in close.columns]
                    if still:
                        print(f"[prices] still missing after backfill: {still}")
            print(f"[prices] cache hit cols={len(use)} max={pd.Timestamp(close.index.max()).date()}")
            vol_out = volume[use] if set(use).issubset(set(volume.columns)) else volume.reindex(columns=use)
            return close[use], open_.reindex(columns=use), vol_out
        if len(use) >= min(80, max(1, len(codes) // 2)):
            print(f"[prices] cache stale max={pd.Timestamp(close.index.max()).date()} -> refresh to {end}")

    close, open_, volume = _download_ohlcv(codes, START, end)
    min_cols = min(len(codes), max(80, int(len(codes) * 0.80)))
    if close is None or close.empty or close.shape[1] < min_cols:
        raise RuntimeError(
            f"price refresh validation failed: cols={0 if close is None else close.shape[1]} required={min_cols}; existing cache preserved"
        )
    for frame, path in ((close, CACHE_PRICES), (open_, CACHE_OPEN), (volume, vol_path)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        frame.to_parquet(tmp)
        tmp.replace(path)
    return close, open_, volume

def load_index(force: bool = False) -> pd.Series:
    DATA.mkdir(parents=True, exist_ok=True)
    end = resolve_end(END)
    if CACHE_INDEX.exists() and not force:
        df = pd.read_parquet(CACHE_INDEX)
        s = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        s.index = pd.to_datetime(s.index).tz_localize(None)
        s = s.astype(float).sort_index()
        if not cache_is_stale(s.index):
            return s
        print(f"[index] cache stale max={pd.Timestamp(s.index.max()).date()} -> refresh to {end}")
    raw = yf.download("SPY", start=START, end=end, progress=False, auto_adjust=True)
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    if raw is None or raw.empty or "Close" not in raw.columns:
        raise RuntimeError("SPY refresh returned no usable Close; existing cache preserved")
    out = raw[["Close"]].copy()
    tmp = CACHE_INDEX.with_suffix(CACHE_INDEX.suffix + ".tmp")
    out.to_parquet(tmp)
    tmp.replace(CACHE_INDEX)
    return out["Close"].astype(float)


# ---------------------------------------------------------------------------
# Fundamentals / valuation
# ---------------------------------------------------------------------------

def _pick_row(df: pd.DataFrame, candidates: List[str]) -> Optional[pd.Series]:
    if df is None or getattr(df, "empty", True):
        return None
    idx = {str(i).lower(): i for i in df.index}
    for c in candidates:
        key = c.lower()
        if key in idx:
            return df.loc[idx[key]]
        for k, orig in idx.items():
            if key in k:
                return df.loc[orig]
    return None


def fetch_ticker_fundamentals(code: str) -> pd.DataFrame:
    t = yf.Ticker(code)

    def extract(bs, inc, freq: str) -> pd.DataFrame:
        if bs is None or inc is None or getattr(bs, "empty", True) or getattr(inc, "empty", True):
            return pd.DataFrame()
        cols = sorted(set(bs.columns).union(set(inc.columns)))
        equity = _pick_row(bs, [
            "Common Stock Equity", "Stockholders Equity",
            "Total Equity Gross Minority Interest", "Tangible Book Value",
        ])
        shares = _pick_row(bs, ["Ordinary Shares Number", "Share Issued", "Common Stock"])
        total_debt = _pick_row(bs, ["Total Debt", "Long Term Debt", "Net Debt"])
        cash = _pick_row(bs, [
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents", "Cash Financial",
        ])
        ni = _pick_row(inc, [
            "Net Income Common Stockholders", "Net Income",
            "Net Income Continuous Operations", "Normalized Income",
        ])
        revenue = _pick_row(inc, ["Total Revenue", "Operating Revenue", "Revenue"])
        ebit = _pick_row(inc, ["EBIT", "Operating Income", "Normalized EBITDA"])
        rows = []
        for c in cols:
            period = pd.Timestamp(c)
            row = {
                "code": code,
                "period_end": period,
                "freq": freq,
                "equity": float(equity[c]) if equity is not None and c in equity.index and pd.notna(equity[c]) else np.nan,
                "shares": float(shares[c]) if shares is not None and c in shares.index and pd.notna(shares[c]) else np.nan,
                "total_debt": float(total_debt[c]) if total_debt is not None and c in total_debt.index and pd.notna(total_debt[c]) else np.nan,
                "cash": float(cash[c]) if cash is not None and c in cash.index and pd.notna(cash[c]) else np.nan,
                "ni_q": float(ni[c]) if ni is not None and c in ni.index and pd.notna(ni[c]) else np.nan,
                "rev_q": float(revenue[c]) if revenue is not None and c in revenue.index and pd.notna(revenue[c]) else np.nan,
                "ebit_q": float(ebit[c]) if ebit is not None and c in ebit.index and pd.notna(ebit[c]) else np.nan,
            }
            if freq == "A":
                row["ni_ttm_direct"] = row["ni_q"]
                row["rev_ttm_direct"] = row["rev_q"]
                row["ebit_ttm_direct"] = row["ebit_q"]
            else:
                row["ni_ttm_direct"] = np.nan
                row["rev_ttm_direct"] = np.nan
                row["ebit_ttm_direct"] = np.nan
            rows.append(row)
        return pd.DataFrame(rows)

    frames = []
    try:
        frames.append(extract(getattr(t, "balance_sheet", None), getattr(t, "income_stmt", None), "A"))
    except Exception:
        pass
    try:
        q_bs = getattr(t, "quarterly_balance_sheet", None)
        q_is = getattr(t, "quarterly_income_stmt", None)
        if q_bs is None or getattr(q_bs, "empty", True):
            q_bs = getattr(t, "quarterly_balancesheet", None)
        if q_is is None or getattr(q_is, "empty", True):
            q_is = getattr(t, "quarterly_financials", None)
        frames.append(extract(q_bs, q_is, "Q"))
    except Exception:
        pass
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def download_fundamentals(codes: List[str], force: bool = False, limit: Optional[int] = None) -> pd.DataFrame:
    DATA.mkdir(parents=True, exist_ok=True)
    existing = pd.DataFrame()
    have = set()
    if CACHE_FUND.exists() and not force:
        existing = pd.read_parquet(CACHE_FUND)
        if not existing.empty:
            have = set(existing["code"].astype(str).unique())
    target = codes if limit is None else codes[:limit]
    missing = [c for c in target if c not in have]
    print(f"[fund] cached={len(have)} missing={len(missing)}")
    frames = [existing] if not existing.empty else []
    for i, code in enumerate(missing, 1):
        try:
            df = fetch_ticker_fundamentals(code)
            if not df.empty:
                frames.append(df)
            if i % 10 == 0 or i == len(missing):
                print(f"  fund {i}/{len(missing)} {code} rows={0 if df is None else len(df)}")
                if frames:
                    tmp = pd.concat(frames, ignore_index=True)
                    tmp.to_parquet(CACHE_FUND, index=False)
            time.sleep(0.12)
        except Exception as e:
            print(f"  fund fail {code}: {e}")
            time.sleep(0.3)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["code"] = out["code"].astype(str)
    out["period_end"] = pd.to_datetime(out["period_end"])
    out = out.drop_duplicates(["code", "period_end", "freq"], keep="last")
    out.to_parquet(CACHE_FUND, index=False)
    return out


def build_ttm(fund: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for code, g in fund.groupby("code"):
        g = g.copy()
        if "freq" not in g.columns:
            g["freq"] = "Q"
        pieces = []
        a = g[g["freq"] == "A"].sort_values("period_end").copy()
        q = g[g["freq"] == "Q"].sort_values("period_end").copy()
        if not a.empty:
            a["ni_ttm"] = a.get("ni_ttm_direct", a["ni_q"]).fillna(a["ni_q"])
            a["rev_ttm"] = a.get("rev_ttm_direct", a["rev_q"]).fillna(a["rev_q"])
            a["ebit_ttm"] = a.get("ebit_ttm_direct", a["ebit_q"]).fillna(a["ebit_q"])
            pieces.append(a)
        if not q.empty:
            q["ni_ttm"] = q["ni_q"].rolling(4, min_periods=2).sum()
            q["rev_ttm"] = q["rev_q"].rolling(4, min_periods=2).sum()
            q["ebit_ttm"] = q["ebit_q"].rolling(4, min_periods=2).sum()
            pieces.append(q)
        if not pieces:
            continue
        gg = pd.concat(pieces, ignore_index=True)
        gg = gg.sort_values(["period_end", "freq"]).drop_duplicates("period_end", keep="last")
        rows.append(gg)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def build_valuation_panel(close: pd.DataFrame, volume: pd.DataFrame,
                          fund_ttm: pd.DataFrame, force: bool = False) -> pd.DataFrame:
    if CACHE_VAL.exists() and not force:
        cached = pd.read_parquet(CACHE_VAL)
        if not cached.empty and pd.to_datetime(cached["date"]).max() >= pd.Timestamp("2024-01-01"):
            print(f"[val] cached rows={len(cached)}")
            return cached
    if fund_ttm is None or fund_ttm.empty:
        return pd.DataFrame()

    fund_ttm = fund_ttm.copy()
    fund_ttm["available_from"] = pd.to_datetime(fund_ttm["period_end"]) + pd.Timedelta(days=FUND_LAG_DAYS)
    me_dates = month_ends(close.index)
    me_dates = me_dates[(me_dates >= pd.Timestamp("2019-01-01")) & (me_dates <= close.index.max())]

    records = []
    codes = close.columns.tolist()
    for d in me_dates:
        px = close.loc[d]
        amt20 = (close.loc[:d].tail(20) * volume.loc[:d].tail(20)).mean()
        f_avail = fund_ttm[fund_ttm["available_from"] <= d]
        if f_avail.empty:
            continue
        latest = f_avail.sort_values("period_end").groupby("code").tail(1).set_index("code")
        for code in codes:
            if code not in latest.index:
                continue
            price = px.get(code, np.nan)
            if pd.isna(price) or price <= 0:
                continue
            fr = latest.loc[code]
            shares = fr.get("shares", np.nan)
            if pd.isna(shares) or shares <= 0:
                continue
            mcap = price * shares
            if mcap <= 0:
                continue
            equity = fr.get("equity", np.nan)
            ni = fr.get("ni_ttm", np.nan)
            rev = fr.get("rev_ttm", np.nan)
            ebit = fr.get("ebit_ttm", np.nan)
            debt = fr.get("total_debt", np.nan)
            cash = fr.get("cash", np.nan)
            net_debt = (0 if pd.isna(debt) else debt) - (0 if pd.isna(cash) else cash)
            ev = mcap + net_debt
            ep = ni / mcap if pd.notna(ni) else np.nan
            bp = equity / mcap if pd.notna(equity) and equity > 0 else np.nan
            sp = rev / mcap if pd.notna(rev) and rev > 0 else np.nan
            ebit_y = ebit / ev if pd.notna(ebit) and ev > 0 else np.nan
            roe = ni / equity if pd.notna(ni) and pd.notna(equity) and equity > 0 else np.nan
            records.append({
                "date": d, "code": code, "price": price, "mcap": mcap,
                "amt20": float(amt20.get(code, np.nan)) if code in amt20.index else np.nan,
                "ep": ep, "bp": bp, "sp": sp, "ebit_yield": ebit_y, "roe": roe,
                "ni_ttm": ni, "equity": equity, "period_end": fr.get("period_end"),
            })
    val = pd.DataFrame(records)
    if val.empty:
        return val

    def add_ranks(g: pd.DataFrame) -> pd.DataFrame:
        g = g.copy()
        for col in ["ep", "bp", "sp", "ebit_yield", "roe"]:
            g[f"rank_{col}"] = g[col].rank(method="average", ascending=True, pct=True)
        g["value_score"] = g[["rank_ep", "rank_bp", "rank_sp", "rank_ebit_yield"]].mean(axis=1, skipna=True)
        g["qv_score"] = 0.6 * g["value_score"] + 0.4 * g["rank_roe"]
        return g

    val = val.groupby("date", group_keys=False).apply(add_ranks)
    val["date"] = pd.to_datetime(val["date"])
    val.to_parquet(CACHE_VAL, index=False)
    print(f"[val] rows={len(val)} months={val['date'].nunique()} codes={val['code'].nunique()}")
    return val


# ---------------------------------------------------------------------------
# Features & selection
# ---------------------------------------------------------------------------

def compute_price_features(close: pd.DataFrame, volume: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    mom_12_1 = close.shift(21) / close.shift(252) - 1.0
    mom_63 = close / close.shift(63) - 1.0
    mom_21 = close / close.shift(21) - 1.0
    high_252 = close.rolling(252, min_periods=120).max()
    near_high = close / high_252
    vol_20 = volume.rolling(20, min_periods=10).mean()
    vol_60 = volume.rolling(60, min_periods=30).mean()
    vol_surge = vol_20 / vol_60
    amt_20 = (close * volume).rolling(20, min_periods=10).mean()
    amt_60 = (close * volume).rolling(60, min_periods=30).mean()
    ret_20 = close / close.shift(20) - 1.0
    ret_60 = close / close.shift(60) - 1.0

    def xs(df):
        return df.rank(axis=1, pct=True)

    leader_score = (
        0.45 * xs(mom_12_1)
        + 0.20 * xs(near_high)
        + 0.15 * xs(mom_63)
        + 0.10 * xs(vol_surge)
        + 0.10 * xs(mom_21)
    )

    # Accumulation divergence: high relative $volume / weak relative ST return
    r_amt20 = xs(amt_20)
    r_amt60 = xs(amt_60)
    r_ret20 = xs(ret_20)
    r_ret60 = xs(ret_60)
    r_vol_surge = xs(vol_surge)
    bull_div = (
        0.30 * r_amt20
        + 0.25 * r_amt60
        + 0.20 * r_vol_surge
        + 0.15 * (1.0 - r_ret20)
        + 0.10 * (1.0 - r_ret60)
    )
    # require actual elevated activity vs own history
    bull_div = bull_div.where(vol_surge > 1.0)
    # confirmation: price up + volume up (leader overlay)
    confirm = (
        0.30 * r_amt20
        + 0.20 * r_vol_surge
        + 0.30 * r_ret20
        + 0.20 * r_ret60
    )
    confirm = confirm.where(vol_surge > 1.0)
    # bearish divergence: price strong, activity fading
    bear_div = (ret_20 > 0) & (vol_surge < 0.9) & (r_ret20 > 0.7) & (r_amt20 < 0.4)

    return {
        "mom_12_1": mom_12_1,
        "mom_63": mom_63,
        "mom_21": mom_21,
        "near_high": near_high,
        "vol_surge": vol_surge,
        "amt_20": amt_20,
        "leader_score": leader_score,
        "bull_div": bull_div,
        "confirm": confirm,
        "bear_div": bear_div,
        "ret_20": ret_20,
        "ret_60": ret_60,
    }


def market_regime(index_close: pd.Series) -> pd.Series:
    ma60 = index_close.rolling(60, min_periods=40).mean()
    mom20 = index_close / index_close.shift(20) - 1.0
    slope = ma60 / ma60.shift(20) - 1.0
    reg = pd.Series("sideways", index=index_close.index, dtype=object)
    reg[(index_close > ma60) & (slope > 0) & (mom20 > 0)] = "bull"
    reg[(index_close < ma60) & (slope < 0) & (mom20 < 0)] = "bear"
    return reg


def select_leader(date, feats, regime, n=N_LEADER) -> List[str]:
    """Leader sleeve: price/momentum score only (no AccumulDiv confirm/bear overlay)."""
    score = feats["leader_score"].loc[date]
    mom = feats["mom_12_1"].loc[date]
    near = feats["near_high"].loc[date]
    amt = feats["amt_20"].loc[date]
    df = pd.DataFrame({"score": score, "mom": mom, "near": near, "amt": amt}).dropna()
    df = df[df["amt"] >= MIN_AMT]
    df = df[(df["mom"] > 0) & (df["near"] >= 0.80)]
    if regime == "bear":
        n = min(n, 3)
        df = df[df["near"] >= 0.90]
    elif regime == "sideways":
        n = min(n, 7)
    if df.empty:
        return []
    return df.sort_values("score", ascending=False).head(n).index.tolist()

def select_value_mom(date, val_snap: pd.DataFrame, feats, n=N_VALUE) -> List[str]:
    if val_snap is None or val_snap.empty:
        return []
    df = val_snap.copy()
    df = df[df["amt20"].fillna(0) >= MIN_AMT]
    df = df[df["ep"].fillna(-1) > 0]
    mom_map = feats["mom_12_1"].loc[date].to_dict() if date in feats["mom_12_1"].index else {}
    df["mom"] = df["code"].map(mom_map)
    df = df[df["mom"].fillna(-1) > 0]
    if "value_score" not in df.columns or df.empty:
        return []
    df = df.dropna(subset=["value_score"])
    return df.sort_values("value_score", ascending=False).head(n)["code"].tolist()


def select_divergence(date, feats, regime, n=N_DIV) -> List[str]:
    if date not in feats["bull_div"].index:
        return []
    div = feats["bull_div"].loc[date]
    amt = feats["amt_20"].loc[date]
    mom = feats["mom_12_1"].loc[date]
    ret20 = feats["ret_20"].loc[date]
    df = pd.DataFrame({"div": div, "amt": amt, "mom": mom, "ret20": ret20}).dropna(subset=["div", "amt"])
    df = df[df["amt"] >= MIN_AMT]
    df = df[df["ret20"].fillna(0) < 0.25]
    df = df[df["mom"].fillna(0) > -0.20]
    if regime == "bear":
        n = min(n, 5)
    if df.empty:
        return []
    return df.sort_values("div", ascending=False).head(n).index.tolist()


# ---------------------------------------------------------------------------
# Strict next-open backtest
# ---------------------------------------------------------------------------

def run_strict(
    close: pd.DataFrame,
    open_px: pd.DataFrame,
    picks_by_date: Dict[pd.Timestamp, Dict[str, List[str]]],
    sleeve_w: Dict[str, float],
    feats: Dict[str, pd.DataFrame],
    val: pd.DataFrame,
    cost: float = COST_BASE,
    max_name: float = MAX_NAME,
    weight_mode: str = "score",
    label: str = "strat",
) -> Dict:
    """Signal at month-end close → execute at next open with SCORE weights + name cap."""
    signal_dates = sorted(picks_by_date.keys())
    if not signal_dates:
        raise RuntimeError("no signal dates")
    exec_map = next_open_map(close.index, open_px)
    # map exec_day -> signal_day
    rebal_on: Dict[pd.Timestamp, pd.Timestamp] = {}
    for sig in signal_dates:
        ex = exec_map.get(sig)
        if ex is not None and ex in close.index:
            rebal_on[ex] = sig

    all_days = close.index[close.index >= min(rebal_on.keys())]
    cash = float(SEED)
    shares: Dict[str, float] = {}
    prev_w: Dict[str, float] = {}
    equity_rows = []
    rets = []
    hold_log = []
    weights_hist = []

    for d in all_days:
        # mark-to-market on close for equity curve
        port_val = cash
        for c, sh in shares.items():
            px = close.at[d, c] if c in close.columns and pd.notna(close.at[d, c]) else np.nan
            if pd.notna(px):
                port_val += sh * px

        if d in rebal_on:
            sig = rebal_on[d]
            picks = picks_by_date[sig]
            score_maps = {
                "leader": feats["leader_score"].loc[sig].to_dict() if sig in feats["leader_score"].index else {},
                "value_mom": {},
                "divergence": feats["bull_div"].loc[sig].to_dict() if sig in feats["bull_div"].index else {},
            }
            if not val.empty:
                snap = val[val["date"] == sig]
                if not snap.empty and "value_score" in snap.columns:
                    score_maps["value_mom"] = dict(zip(snap["code"], snap["value_score"]))

            name_w: Dict[str, Dict[str, float]] = {}
            for sleeve in ["leader", "value_mom", "divergence"]:
                codes = []
                for c in picks.get(sleeve, []):
                    if c in open_px.columns and pd.notna(open_px.at[d, c]) and open_px.at[d, c] > 0:
                        codes.append(c)
                if weight_mode == "equal":
                    name_w[sleeve] = weights_equal(codes)
                else:
                    name_w[sleeve] = weights_score(codes, score_maps.get(sleeve, {}))

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
                "leader": picks.get("leader", []),
                "value_mom": picks.get("value_mom", []),
                "divergence": picks.get("divergence", []),
                "n": len(shares),
                "turnover": round(to, 4),
                "top": sorted(target.items(), key=lambda x: -x[1])[:8],
            })
            weights_hist.append({"date": d.strftime("%Y-%m-%d"), "n": len(shares), "turnover": to})

            # re-mark after open fills using close for EOD
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
    return {"equity": eq, "returns": r, "holdings": hold_log, "weights_hist": weights_hist, "label": label}


def run_benchmark(index_close: pd.Series, ref_index: pd.DatetimeIndex, cost: float = 0.0) -> Tuple[pd.Series, pd.Series]:
    s = index_close.reindex(ref_index).ffill()
    rets = s.pct_change().fillna(0.0)
    eq = (1 + rets).cumprod() * SEED
    eq.iloc[0] = SEED
    return eq, rets


# ---------------------------------------------------------------------------
# Diagnostics: IS/OOS, walk-forward, bootstrap, gates
# ---------------------------------------------------------------------------

def split_isoos(eq: pd.Series, rets: pd.Series, b_rets: pd.Series, is_end: str = IS_END) -> Dict:
    is_mask = eq.index <= pd.Timestamp(is_end)
    oos_mask = eq.index > pd.Timestamp(is_end)
    out = {}
    if is_mask.any():
        out["IS"] = perf(eq[is_mask], rets[is_mask], b_rets, "IS")
    if oos_mask.sum() > 20:
        out["OOS"] = perf(eq[oos_mask], rets[oos_mask], b_rets, "OOS")
    return out


def walk_forward(eq: pd.Series, rets: pd.Series, b_rets: pd.Series, n_folds: int = 5) -> List[Dict]:
    idx = rets.dropna().index
    if len(idx) < 300:
        return []
    # equal calendar folds on OOS-capable full sample
    cuts = np.linspace(0, len(idx), n_folds + 1, dtype=int)
    rows = []
    b = b_rets.reindex(idx).fillna(0.0)
    for i in range(n_folds):
        a, z = cuts[i], cuts[i + 1]
        if z - a < 40:
            continue
        sl = idx[a:z]
        r = rets.reindex(sl).fillna(0.0)
        bb = b.reindex(sl).fillna(0.0)
        years = max((sl[-1] - sl[0]).days / 365.25, 1e-9)
        # rebuild fold equity from unit start
        feq = (1 + r).cumprod()
        cagr = float(feq.iloc[-1] ** (1 / years) - 1)
        bcagr = float((1 + bb).cumprod().iloc[-1] ** (1 / years) - 1)
        vol = float(r.std() * math.sqrt(252))
        sharpe = float((r.mean() * 252) / vol) if vol > 0 else np.nan
        mdd = float((feq / feq.cummax() - 1).min())
        excess = r - bb
        te = float(excess.std() * math.sqrt(252))
        ir = float((excess.mean() * 252) / te) if te > 0 else np.nan
        rows.append({
            "fold": i + 1,
            "start": str(sl[0].date()),
            "end": str(sl[-1].date()),
            "cagr": round(cagr, 4),
            "bench_cagr": round(bcagr, 4),
            "ann_ex": round(cagr - bcagr, 4),
            "sharpe": round(sharpe, 3) if sharpe == sharpe else None,
            "mdd": round(mdd, 4),
            "info_ratio": round(ir, 3) if ir == ir else None,
        })
    return rows


def bootstrap_excess(rets: pd.Series, b_rets: pd.Series, n: int = BOOT_N, seed: int = BOOT_SEED) -> Dict:
    r = rets.dropna()
    b = b_rets.reindex(r.index).fillna(0.0)
    excess = (r - b).values
    if len(excess) < 50:
        return {}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n):
        sample = rng.choice(excess, size=len(excess), replace=True)
        means.append(sample.mean() * 252)
    means = np.array(means)
    obs = float(excess.mean() * 252)
    p_pos = float((means > 0).mean())
    p_ge_obs = float((means >= obs).mean())
    return {
        "obs_ann_excess": round(obs, 4),
        "boot_mean": round(float(means.mean()), 4),
        "boot_p5": round(float(np.percentile(means, 5)), 4),
        "boot_p50": round(float(np.percentile(means, 50)), 4),
        "boot_p95": round(float(np.percentile(means, 95)), 4),
        "prob_positive": round(p_pos, 4),
        "p_value_onesided": round(1.0 - p_pos, 4),  # H0: excess<=0 approx
        "n": n,
    }


def evaluate_gates(stats: Dict, isoos: Dict, wf: List[Dict], boot: Dict, b_stats: Dict) -> Dict:
    """Strict gate protocol (PASS/FAIL per check)."""
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    cagr = stats.get("cagr") or 0
    bcagr = b_stats.get("cagr") or 0
    sharpe = stats.get("sharpe") or 0
    mdd = stats.get("mdd") or 0
    alpha = stats.get("alpha") or 0
    ir = stats.get("info_ratio") or 0

    add("G1_CAGR_vs_Bench", cagr > bcagr, f"cagr={cagr:.2%} bench={bcagr:.2%}")
    add("G2_Sharpe_gt_0.4", sharpe >= 0.40, f"sharpe={sharpe}")
    add("G3_MDD_gt_-45pct", mdd > -0.45, f"mdd={mdd:.2%}")
    add("G4_Alpha_positive", alpha > 0, f"alpha={alpha:.2%}")
    add("G5_IR_gt_0", ir > 0, f"IR={ir}")

    oos = isoos.get("OOS")
    if oos:
        oos_ir = oos.get("info_ratio") or 0
        oos_alpha = oos.get("alpha") or 0
        add(
            "G6_OOS_excess",
            oos_ir > 0 or oos_alpha > 0,
            f"OOS cagr={oos.get('cagr')} IR={oos.get('info_ratio')} alpha={oos.get('alpha')}",
        )
    else:
        add("G6_OOS_excess", False, "OOS missing")

    if wf:
        pos = sum(1 for f in wf if (f.get("ann_ex") or 0) > 0)
        add("G7_WF_majority_excess", pos >= max(1, int(0.6 * len(wf))), f"pos_folds={pos}/{len(wf)}")
    else:
        add("G7_WF_majority_excess", False, "WF missing")

    if boot:
        add("G8_Bootstrap_pos", (boot.get("prob_positive") or 0) >= 0.90,
            f"P(excess>0)={boot.get('prob_positive')}")
    else:
        add("G8_Bootstrap_pos", False, "bootstrap missing")

    n_pass = sum(1 for c in checks if c["pass"])
    return {
        "checks": checks,
        "n_pass": n_pass,
        "n_total": len(checks),
        "status": "PASS" if n_pass == len(checks) else ("WARN" if n_pass >= len(checks) - 2 else "FAIL"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(force: bool = False, top_n: int = TOP_N, fund_limit: Optional[int] = None):
    OUT.mkdir(parents=True, exist_ok=True)
    CHART.mkdir(parents=True, exist_ok=True)

    print("== 1) Universe ==")
    meta = build_universe(top_n=top_n)
    codes = meta["Code"].astype(str).tolist()

    print("== 2) Prices / SPY ==")
    close, open_px, volume = load_prices(codes, force=force)
    codes = close.columns.tolist()
    index_close = load_index(force=force)
    index_close = index_close.reindex(close.index).ffill()
    regime = market_regime(index_close)

    print("== 3) Fundamentals / Valuation ==")
    fund = download_fundamentals(codes, force=force, limit=fund_limit)
    fund_ttm = build_ttm(fund) if not fund.empty else pd.DataFrame()
    val = build_valuation_panel(close, volume, fund_ttm, force=force)
    if not val.empty:
        val["date"] = pd.to_datetime(val["date"])
        val["code"] = val["code"].astype(str)

    print("== 4) Features & monthly picks ==")
    feats = compute_price_features(close, volume)
    me = month_ends(close.index)
    # warm-up: need ~1y momentum
    start = max(pd.Timestamp("2019-07-01"), close.index[0] + pd.Timedelta(days=280))
    me = [d for d in me if d >= start]
    picks_by_date = {}
    leader_only, vm_only, div_only = {}, {}, {}
    for d in me:
        reg = regime.loc[d] if d in regime.index else "sideways"
        val_snap = val[val["date"] == d] if not val.empty else pd.DataFrame()
        L = select_leader(d, feats, reg, n=N_LEADER)
        V = select_value_mom(d, val_snap, feats, n=N_VALUE)
        D = select_divergence(d, feats, reg, n=N_DIV)
        picks_by_date[d] = {"leader": L, "value_mom": V, "divergence": D}
        leader_only[d] = {"leader": L, "value_mom": [], "divergence": []}
        vm_only[d] = {"leader": [], "value_mom": V, "divergence": []}
        div_only[d] = {"leader": [], "value_mom": [], "divergence": D}
    print(f"signal months={len(me)} first={me[0].date()} last={me[-1].date()}")

    print("== 5) Strict next-open backtests ==")
    sleeve = {"leader": W_LEADER, "value_mom": W_VALUE, "divergence": W_DIV}
    sleeve_eq = {"leader": 1 / 3, "value_mom": 1 / 3, "divergence": 1 / 3}

    hybrid = run_strict(close, open_px, picks_by_date, sleeve, feats, val,
                        cost=COST_BASE, max_name=MAX_NAME, weight_mode="score", label="US_SCORE_55")
    hybrid_ew = run_strict(close, open_px, picks_by_date, sleeve, feats, val,
                           cost=COST_BASE, max_name=MAX_NAME, weight_mode="equal", label="US_EW_55")
    hybrid_stress = run_strict(close, open_px, picks_by_date, sleeve, feats, val,
                               cost=COST_STRESS, max_name=MAX_NAME, weight_mode="score", label="US_SCORE_55_20bp")
    hybrid_eq = run_strict(close, open_px, picks_by_date, sleeve_eq, feats, val,
                           cost=COST_BASE, max_name=MAX_NAME, weight_mode="score", label="US_SCORE_EQ33")
    s_leader = run_strict(close, open_px, leader_only, {"leader": 1.0}, feats, val,
                          cost=COST_BASE, max_name=MAX_NAME, weight_mode="score", label="US_Leader")
    s_vm = run_strict(close, open_px, vm_only, {"value_mom": 1.0}, feats, val,
                      cost=COST_BASE, max_name=MAX_NAME, weight_mode="score", label="US_ValueMom")
    s_div = run_strict(close, open_px, div_only, {"divergence": 1.0}, feats, val,
                       cost=COST_BASE, max_name=MAX_NAME, weight_mode="score", label="US_Divergence")

    ref = hybrid["equity"].index
    b_eq, b_rets = run_benchmark(index_close, ref)

    stats_list = [
        perf(b_eq, b_rets, b_rets, "Bench_SPY"),
        perf(s_leader["equity"], s_leader["returns"], b_rets, "US_Leader"),
        perf(s_vm["equity"], s_vm["returns"], b_rets, "US_ValueMom"),
        perf(s_div["equity"], s_div["returns"], b_rets, "US_Divergence"),
        perf(hybrid["equity"], hybrid["returns"], b_rets, "US_SCORE_55"),
        perf(hybrid_ew["equity"], hybrid_ew["returns"], b_rets, "US_EW_55"),
        perf(hybrid_eq["equity"], hybrid_eq["returns"], b_rets, "US_SCORE_EQ33"),
        perf(hybrid_stress["equity"], hybrid_stress["returns"], b_rets, "US_SCORE_55_20bp"),
    ]
    stats_df = pd.DataFrame(stats_list)
    print(stats_df[["strategy", "cagr", "sharpe", "mdd", "alpha", "info_ratio", "final_equity"]])

    main_stats = next(s for s in stats_list if s["strategy"] == "US_SCORE_55")
    b_stats = next(s for s in stats_list if s["strategy"] == "Bench_SPY")

    print("== 6) IS/OOS · WF · Bootstrap · Gates ==")
    isoos = split_isoos(hybrid["equity"], hybrid["returns"], b_rets, IS_END)
    wf = walk_forward(hybrid["equity"], hybrid["returns"], b_rets, n_folds=5)
    boot = bootstrap_excess(hybrid["returns"], b_rets, n=BOOT_N, seed=BOOT_SEED)
    gates = evaluate_gates(main_stats, isoos, wf, boot, b_stats)
    print("gates:", gates["status"], f"{gates['n_pass']}/{gates['n_total']}")
    for c in gates["checks"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}: {c['detail']}")

    # regime share
    reg_on_ref = regime.reindex(ref).ffill()
    regime_share = reg_on_ref.value_counts(normalize=True).to_dict()

    eq_df = pd.DataFrame({
        "Bench_SPY": b_eq,
        "US_Leader": s_leader["equity"],
        "US_ValueMom": s_vm["equity"],
        "US_Divergence": s_div["equity"],
        "US_SCORE_55": hybrid["equity"],
        "US_EW_55": hybrid_ew["equity"],
        "US_SCORE_EQ33": hybrid_eq["equity"],
        "US_SCORE_55_20bp": hybrid_stress["equity"],
    })
    eq_df.to_csv(OUT / "equity_curves.csv")
    stats_df.to_csv(OUT / "stats.csv", index=False)

    payload = {
        "stats": stats_list,
        "weights": {"leader": W_LEADER, "value_mom": W_VALUE, "divergence": W_DIV},
        "cost_base": COST_BASE,
        "cost_stress": COST_STRESS,
        "max_name": MAX_NAME,
        "execution": "next_open",
        "universe": "S&P500 top liquid",
        "n_codes": len(codes),
        "n_signals": len(me),
        "data_range": {
            "prices": f"{close.index.min().date()}~{close.index.max().date()}",
            "signals": f"{me[0].date()}~{me[-1].date()}",
            "valuation": (
                f"{val['date'].min().date()}~{val['date'].max().date()}" if not val.empty else "none"
            ),
            "n_val_codes": int(val["code"].nunique()) if not val.empty else 0,
        },
        "isoos": isoos,
        "walk_forward": {"US_SCORE_55": wf},
        "bootstrap": boot,
        "gates": gates,
        "regime_share": {str(k): round(float(v), 4) for k, v in regime_share.items()},
        "latest_holdings": hybrid["holdings"][-1] if hybrid["holdings"] else {},
        "holdings_tail": hybrid["holdings"][-6:] if hybrid["holdings"] else [],
        "notes": {
            "divergence_def": "price-volume accumulation (US substitute for KR foreign net-buy)",
            "fund_lag_days": FUND_LAG_DAYS,
            "is_end": IS_END,
        },
    }
    with open(OUT / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    with open(OUT / "holdings.json", "w", encoding="utf-8") as f:
        json.dump(hybrid["holdings"], f, ensure_ascii=False, indent=2, default=str)

    print("DONE ->", OUT)
    return payload


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    p.add_argument("--top-n", type=int, default=TOP_N)
    p.add_argument("--fund-limit", type=int, default=None,
                   help="optional cap on fundamental downloads for speed")
    args = p.parse_args()
    main(force=args.force, top_n=args.top_n, fund_limit=args.fund_limit)
