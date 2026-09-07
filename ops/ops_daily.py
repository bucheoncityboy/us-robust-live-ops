"""Weekly live NAV/return tracker for US-Robust ops.

Snapshots the live Toss book (total/equity/cash USD) plus the SPY close into
``results/ops_runs/YYYY-MM/daily_nav.csv`` and per-holding quantities into
``results/ops_runs/YYYY-MM/daily_holdings.csv`` (per-month files; readers
union all months) — one row per ISO week, anchored on the last US trading
day of the week (Friday, or earlier if holiday).  Weekly rows are stored
under the legacy daily_* filenames for backward compatibility.
Idempotent per weekly anchor: re-running the same week overwrites that
week's anchor row.

Run-day classification (python ops.py weekly):
- US trading day before the week's anchor (Mon-Thu, or early-week holiday):
  clean no-op with reason ``not_weekly_anchor_day``.
- The anchor day itself (normally Friday): live snapshot at the anchor.
- Saturday/Sunday after the anchor: records the anchor (Friday) row in
  place — row date = anchor, SPY close at the anchor, live Toss book
  fetched on the run day (market closed; reflects Friday close).
- Monday after a missed Friday: no-op; the gap week is backfilled on the
  next anchor run.

Gap handling: if one or more weekly anchors were skipped, those anchor
rows are backfilled from the last recorded holdings (quantities are
unchanged between monthly rebalances) priced at the panel close, with cash
carried forward, so the weekly return series stays continuous and all
earlier returns are recomputed.

Legacy migration: on first run after this change, any existing daily rows
(one row per trading day) are compressed to weekly anchors once
(``compress_daily_to_weekly``) with ``.bak`` backups; the first anchor's
``ret_1d`` is seeded from the week's first recorded total to the anchor
close so the real first-week return is preserved.

Note: total_usd is a live intraday snapshot; deposits/withdrawals distort
weekly returns on those days (not flow-adjusted).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OPS_RUNS = ROOT / "results" / "ops_runs"
COLS = [
    "date", "total_usd", "equity_usd", "cash_usd", "spy_close",
    "ret_1d", "cum_ret", "spy_ret_1d", "spy_cum_ret",
]
HOLD_COLS = ["date", "code", "qty", "weight", "avg_cost", "sleeve"]


def _daily_path(month: str) -> Path:
    """results/ops_runs/YYYY-MM/daily_nav.csv (per-month file; readers union all months)."""
    return OPS_RUNS / month / "daily_nav.csv"


def _holdings_path(month: str) -> Path:
    """results/ops_runs/YYYY-MM/daily_holdings.csv (per-month file)."""
    return OPS_RUNS / month / "daily_holdings.csv"


def _sleeve_map() -> Dict[str, str]:
    """code -> joined signal sleeves (e.g. 'leader+mom63') from the latest completed-month signals.csv."""
    candidates = sorted(
        (p for p in OPS_RUNS.glob("*/signals.csv") if p.parent.joinpath("health.json").exists()),
        key=lambda p: p.parent.name,
    )
    if not candidates:
        return {}
    df = pd.read_csv(candidates[-1])
    out: Dict[str, str] = {}
    for code, grp in df.groupby(df["code"].astype(str)):
        out[code] = "+".join(sorted(str(s) for s in grp["sleeve"]))
    return out

_CLOSE_PANEL: Optional[pd.DataFrame] = None


def _spy_series() -> Optional[pd.Series]:
    """SPY close series (index=datetime, values=Close).

    Uses the cached spy.parquet and, if today (or recent days) is missing,
    fetches the SPY tail directly from yfinance in-memory — weekly tracking does
    NOT require a full `python ops.py refresh`.
    """
    from ops.ops_live_safety import ny_today
    from ops.us_hybrid_backtest import CACHE_INDEX

    base = None
    if CACHE_INDEX.exists():
        df = pd.read_parquet(CACHE_INDEX)
        if not df.empty:
            s = df.iloc[:, 0].astype(float)
            s.index = pd.to_datetime(df.index)
            base = s
    today = pd.Timestamp(str(ny_today()))
    if base is not None and base.index.max() >= today:
        return base
    try:
        import yfinance as yf

        start = (base.index.max() if base is not None else today - pd.Timedelta(days=35))
        raw = yf.download(
            "SPY", start=start.strftime("%Y-%m-%d"),
            end=(today + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            progress=False, auto_adjust=True,
        )
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        tail = raw["Close"].astype(float).sort_index()
        if base is None:
            return tail
        out = pd.concat([base, tail]).sort_index()
        return out[~out.index.duplicated(keep="last")]
    except Exception as exc:
        print(f"  [weekly] SPY tail fetch failed ({type(exc).__name__}); using cached panel")
        return base


def load_close_panel() -> Optional[pd.DataFrame]:
    """US close-price panel (index=datetime, columns=ticker, values=close)."""
    global _CLOSE_PANEL
    if _CLOSE_PANEL is not None:
        return _CLOSE_PANEL
    from ops.us_hybrid_backtest import CACHE_PRICES

    if not CACHE_PRICES.exists():
        return None
    df = pd.read_parquet(CACHE_PRICES)
    df.index = pd.to_datetime(df.index)
    df.columns = [str(c) for c in df.columns]
    _CLOSE_PANEL = df
    return df


def _extend_close_panel(
    panel: Optional[pd.DataFrame],
    codes: List[str],
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> Optional[pd.DataFrame]:
    """Fetch missing close prices for the held codes from yfinance (in-memory only).

    Lets weekly backfill cover gap weeks without a full `python ops.py refresh`.
    The cached panels are never modified here — refresh remains their owner.
    """
    if not codes or start_dt >= end_dt:
        return panel
    try:
        import yfinance as yf

        raw = yf.download(
            codes, start=start_dt.strftime("%Y-%m-%d"),
            end=(end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            group_by="ticker", threads=True, progress=False, auto_adjust=True,
        )
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        close_cols: Dict[str, pd.Series] = {}
        for c in codes:
            try:
                if len(codes) == 1:
                    if "Close" in raw.columns:
                        close_cols[c] = raw["Close"]
                elif c in raw.columns.get_level_values(0):
                    sub = raw[c]
                    if isinstance(sub, pd.DataFrame) and "Close" in sub.columns:
                        close_cols[c] = sub["Close"].astype(float)
                    elif isinstance(sub, pd.Series):
                        close_cols[c] = sub.astype(float)
            except Exception:
                continue
        if not close_cols:
            print("  [weekly] close tail fetch returned nothing; using cached panel")
            return panel
        ext = pd.DataFrame(close_cols).sort_index()
        if panel is not None:
            new_rows = ext.loc[ext.index.difference(panel.index)]
            if new_rows.empty:
                return panel
            return pd.concat([panel, new_rows]).sort_index()
        return ext
    except Exception as exc:
        print(f"  [weekly] close tail fetch failed ({type(exc).__name__}); using cached panel")
        return panel


def _read_csv(path: Path, cols: list) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]
def _weekly_anchor_map(trading_days) -> Dict[Tuple[int, int], pd.Timestamp]:
    """ISO-week (year, week) -> last US trading day of that week.

    The weekly anchor is the last trading day of the ISO week (Friday, or
    the preceding trading day when Friday is a US market holiday).  Weekend
    days share the ISO week with the preceding Friday, so Saturday/Sunday
    resolve to the same anchor.
    """
    out: Dict[Tuple[int, int], pd.Timestamp] = {}
    for ts in trading_days:
        iso = ts.isocalendar()
        wk = (iso.year, iso.week)
        prev = out.get(wk)
        if prev is None or ts > prev:
            out[wk] = ts
    return out


def _is_weekly_anchor(ts: pd.Timestamp, anchor_map: Dict[Tuple[int, int], pd.Timestamp]) -> bool:
    """True if ts is the last US trading day of its ISO week."""
    iso = ts.isocalendar()
    return anchor_map.get((iso.year, iso.week)) == ts
def prior_anchor(d: str, dates: list) -> Optional[str]:
    """Previous weekly anchor date strictly before ``d`` (``dates`` must be ascending)."""
    prior = None
    for prev_d in dates:
        if prev_d >= d:
            break
        prior = prev_d
    return prior
def _classify_run_day(t: pd.Timestamp, spy: Optional[pd.Series]) -> Tuple[Optional[str], Optional[str]]:
    """Run-day classification -> (refusal_reason_or_None, row_date_or_None).

    Returns (reason, None) for a refusal/no-op, or (None, row_date) when a
    row should be recorded:
    - US trading day before the week's anchor (Mon-Thu): no-op
      ``not_weekly_anchor_day:<today>:<anchor>``.
    - The anchor day itself (normally Friday): record at today.
    - Saturday/Sunday after the anchor: record the anchor row in place
      (row_date = the week's anchor date).
    - Non-trading weekday (holiday) or missing SPY data: no-op
      ``not_a_us_trading_day_or_missing_spy``.
    """
    weekend = t.weekday() >= 5  # Sat/Sun: record the week's anchor row in place
    if spy is None:
        return f"not_a_us_trading_day_or_missing_spy:{str(t.date())}", None
    if not weekend and t not in spy.index:
        return f"not_a_us_trading_day_or_missing_spy:{str(t.date())}", None
    anchor = _weekly_anchor_map(spy.index).get((t.isocalendar().year, t.isocalendar().week))
    if anchor is None:
        return f"not_a_us_trading_day_or_missing_spy:{str(t.date())}", None
    if not weekend and t < anchor:
        return f"not_weekly_anchor_day:{str(t.date())}:{str(anchor.date())}", None
    return None, str(anchor.date()) if weekend else str(t.date())


def load_daily() -> pd.DataFrame:
    """Union of per-month weekly NAV rows (stored under daily_nav.csv for compatibility)."""
    frames = [_read_csv(p, COLS) for p in sorted(OPS_RUNS.glob("*/daily_nav.csv"))]
    if not frames:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = df["date"].astype(str)
    return df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def load_holdings() -> pd.DataFrame:
    """Union of per-month weekly holdings rows (long format: date, code, qty)."""
    frames = [_read_csv(p, HOLD_COLS) for p in sorted(OPS_RUNS.glob("*/daily_holdings.csv"))]
    if not frames:
        return pd.DataFrame(columns=HOLD_COLS)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = df["date"].astype(str)
    return df.sort_values(["date", "code"]).drop_duplicates(["date", "code"], keep="last").reset_index(drop=True)


def recompute_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by date and recompute week-over-week/cumulative returns vs SPY benchmark."""
    df = df.copy()
    df["date"] = df["date"].astype(str)
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("total_usd", "spy_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ret_1d"] = df["total_usd"].pct_change()
    first_total = float(df["total_usd"].iloc[0])
    first_spy = float(df["spy_close"].iloc[0])
    df["cum_ret"] = df["total_usd"] / first_total - 1.0
    df["spy_ret_1d"] = df["spy_close"].pct_change()
    df["spy_cum_ret"] = df["spy_close"] / first_spy - 1.0
    return df


def backfill_missing_weeks(
    df: pd.DataFrame,
    holdings: pd.DataFrame,
    spy: pd.Series,
    close_panel: Optional[pd.DataFrame],
    through_date: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, int]:
    """Fill missed weekly anchors in (last recorded date, through_date) using last-known qty x close.

    Only weekly anchor days (the last US trading day of each skipped ISO
    week) are synthesized, so the series stays at weekly granularity while
    cumulative returns remain continuous.  Quantities are taken from the
    most recent recorded holdings (unchanged between rebalances); cash is
    carried forward; per-stock value = qty x panel close.
    Returns (nav_df, holdings_df, n_weeks_backfilled).
    """
    if close_panel is None or spy is None or df.empty:
        return df, holdings, 0
    last_date = str(df["date"].max())
    start = pd.Timestamp(last_date)
    end = pd.Timestamp(through_date)
    if start >= end:
        return df, holdings, 0
    anchor_map = _weekly_anchor_map(spy.index)

    cur_qty: Dict[str, float] = {}
    cur_cost: Dict[str, float] = {}
    last_rows = holdings[holdings["date"].astype(str) == last_date]
    for _, r in last_rows.iterrows():
        code = str(r["code"])
        cur_qty[code] = float(r["qty"])
        ac = r.get("avg_cost")
        if ac is not None and not pd.isna(ac) and float(ac) > 0:
            cur_cost[code] = float(ac)
    cash_carry = float(df.loc[df["date"].astype(str) == last_date, "cash_usd"].iloc[0])
    if not cur_qty:
        return df, holdings, 0

    new_rows: list = []
    new_hold: list = []
    n = 0
    for ts in spy.index:
        ds = str(ts.date())
        if ds <= last_date or ts.date() >= end.date():
            continue
        if not _is_weekly_anchor(ts, anchor_map):
            continue  # weekly cadence: only anchor days are backfilled
        if ts not in close_panel.index:
            continue  # panel gap: leave that week missing rather than guess
        eq = 0.0
        code_vals: Dict[str, float] = {}
        for code, q in cur_qty.items():
            if code not in close_panel.columns:
                continue
            px = close_panel.at[ts, code]
            if px is not None and not pd.isna(px):
                v = q * float(px)
                code_vals[code] = v
                eq += v
        tot = eq + cash_carry
        spy_px = float(spy.loc[ts])
        new_rows.append({
            "date": ds, "total_usd": round(tot, 6), "equity_usd": round(eq, 6),
            "cash_usd": round(cash_carry, 6), "spy_close": round(spy_px, 6),
        })
        for c, q in cur_qty.items():
            if q <= 0:
                continue
            v = code_vals.get(c, 0.0)
            new_hold.append({
                "date": ds, "code": c, "qty": q,
                "weight": round(v / eq, 6) if eq > 0 else None,
                "avg_cost": cur_cost.get(c),
            })
        n += 1

    if not new_rows:
        return df, holdings, 0
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    holdings = pd.concat([holdings, pd.DataFrame(new_hold)], ignore_index=True)
    return df, holdings, n

def _sleeve_fill(sv, default: str) -> str:
    """Return sv unless it is None/NaN/blank, then fall back to default."""
    if sv is None or pd.isna(sv) or not str(sv).strip():
        return default
    return str(sv)
def compress_daily_to_weekly(
    df: pd.DataFrame,
    holdings: pd.DataFrame,
    spy: pd.Series,
    close_panel: Optional[pd.DataFrame],
) -> Tuple[pd.DataFrame, pd.DataFrame, int]:
    """Compress legacy daily rows (one row per trading day) to weekly anchors.

    One-time migration for pre-cadence-change data: each ISO week collapses
    to its anchor row (last US trading day of the week).  Weeks whose anchor
    close is unavailable in the close panel are left untouched and retried
    on a later run (no data is dropped).  Idempotent: a fully compressed
    series passes through unchanged.

    The first synthesized anchor's ``ret_1d`` is seeded from the week's
    first recorded ``total_usd`` to the anchor close so the real first-week
    return is preserved; ``cum_ret`` is recomputed from the first anchor
    starting at 0.  Holdings rows are kept at their anchor date when present,
    otherwise synthesized from the week's last known quantities priced at
    the anchor close (avg_cost/sleeve carried forward).

    Returns (nav_df, holdings_df, n_weeks_compressed).
    """
    if df.empty or spy is None or spy.empty:
        return df, holdings, 0
    anchor_map = _weekly_anchor_map(spy.index)
    if not anchor_map:
        return df, holdings, 0
    df = df.copy()
    df["date"] = df["date"].astype(str)
    holdings = holdings.copy()
    holdings["date"] = holdings["date"].astype(str)

    # legacy daily rows = trading days that are not weekly anchors
    trading = {str(ts.date()) for ts in spy.index}
    anchor_dates = {str(ts.date()) for ts in anchor_map.values()}
    if not any(ds in trading and ds not in anchor_dates for ds in df["date"]):
        return df, holdings, 0

    def week_key(ds: str) -> Tuple[int, int]:
        iso = pd.Timestamp(ds).isocalendar()
        return (iso.year, iso.week)
    def row_dict(r) -> dict:
        """Normalize a pandas Series row (or dict) to a plain dict.

        out_nav/out_hold can mix deferred weeks (Series rows) with synthesized
        weeks (dict rows); DataFrame() over mixed types crashes on modern pandas.
        """
        return dict(r) if isinstance(r, dict) else {k: r.get(k) for k in r.index}

    nav_by_week: Dict[Tuple[int, int], list] = {}
    for _, r in df.iterrows():
        nav_by_week.setdefault(week_key(str(r["date"])), []).append(r)
    hold_by_week: Dict[Tuple[int, int], list] = {}
    for _, r in holdings.iterrows():
        hold_by_week.setdefault(week_key(str(r["date"])), []).append(r)

    out_nav: list = []
    out_hold: list = []
    n_compressed = 0
    seed_ret: Optional[float] = None
    seed_date: Optional[str] = None
    for wk in sorted(nav_by_week):
        rows = nav_by_week[wk]
        anchor = anchor_map.get(wk)
        a_date = str(anchor.date()) if anchor is not None else None
        existing = [r for r in rows if a_date is not None and str(r["date"]) == a_date]
        if existing:
            # a real anchor snapshot already exists: keep it and its holdings
            out_nav.append(row_dict(existing[-1]))
            out_hold.extend(
                row_dict(hr) for hr in hold_by_week.get(wk, []) if a_date is not None and str(hr["date"]) == a_date
            )
            continue
        if anchor is None or close_panel is None or anchor not in close_panel.index:
            out_nav.extend(row_dict(r) for r in rows)  # cannot price the anchor: defer this week
            out_hold.extend(row_dict(r) for r in hold_by_week.get(wk, []))
            continue
        # synthesize the anchor row from the week's last daily row at the anchor close
        last_row = max(rows, key=lambda r: str(r["date"]))
        hrows = hold_by_week.get(wk, [])
        last_hdate = max((str(r["date"]) for r in hrows), default=None)
        code_qty: Dict[str, float] = {}
        code_cost: Dict[str, float] = {}
        code_sleeve: Dict[str, str] = {}
        for hr in hrows:
            if last_hdate is not None and str(hr["date"]) == last_hdate:
                c = str(hr["code"])
                code_qty[c] = float(hr["qty"])
                ac = hr.get("avg_cost")
                if ac is not None and not pd.isna(ac) and float(ac) > 0:
                    code_cost[c] = float(ac)
                sv = hr.get("sleeve")
                if sv is not None and not pd.isna(sv):
                    code_sleeve[c] = str(sv)
        if not code_qty:
            out_nav.extend(row_dict(r) for r in rows)  # cannot synthesize without quantities: defer
            out_hold.extend(row_dict(r) for r in hrows)
            continue
        cash_carry = pd.to_numeric(last_row["cash_usd"], errors="coerce")
        if pd.isna(cash_carry):
            cash_carry = 0.0
        eq = 0.0
        val_by_code: Dict[str, float] = {}
        for c, q in code_qty.items():
            if q <= 0 or c not in close_panel.columns:
                continue
            px = close_panel.at[anchor, c]
            if px is not None and not pd.isna(px):
                v = q * float(px)
                val_by_code[c] = v
                eq += v
        tot = eq + cash_carry
        if seed_ret is None:
            # preserve the real first-week return: week's first recorded total -> anchor close
            week_first_total = pd.to_numeric(rows[0]["total_usd"], errors="coerce")
            if not pd.isna(week_first_total) and week_first_total > 0:
                seed_ret = tot / week_first_total - 1.0
                seed_date = a_date
        out_nav.append({
            "date": a_date, "total_usd": round(tot, 6), "equity_usd": round(eq, 6),
            "cash_usd": round(cash_carry, 6), "spy_close": round(float(spy.loc[anchor]), 6),
        })
        if eq > 0:
            for c, q in code_qty.items():
                if q <= 0:
                    continue
                out_hold.append({
                    "date": a_date, "code": c, "qty": q,
                    "weight": round(val_by_code.get(c, 0.0) / eq, 6),
                    "avg_cost": code_cost.get(c),
                    "sleeve": code_sleeve.get(c, ""),
                })
        n_compressed += 1

    if not out_nav:
        return df, holdings, 0
    out_df = pd.DataFrame(out_nav)
    out_df = recompute_returns(out_df)
    if seed_ret is not None and seed_date is not None:
        # apply the preserved first-week return to the FIRST synthesized anchor row
        # (recompute_returns would otherwise chain it from a deferred daily row)
        m = out_df["date"] == seed_date
        if m.any():
            out_df.loc[m, "ret_1d"] = round(seed_ret, 6)
    out_hold_df = pd.DataFrame(out_hold, columns=HOLD_COLS) if out_hold else holdings.iloc[0:0].copy()
    return out_df, out_hold_df, n_compressed

def record(book: Optional[Dict] = None) -> Dict:
    """Snapshot the week's NAV + holdings at the weekly anchor; backfill skipped weekly anchors.

    Run-day classification:
    - US trading day before the week's anchor (Mon-Thu): clean no-op
      (reason ``not_weekly_anchor_day:<today>:<anchor>``).
    - The anchor day itself (normally Friday): live snapshot at the anchor.
    - Saturday/Sunday after the anchor: records the anchor row in place
      (row date = anchor, SPY close at the anchor, live Toss book fetched
      on the run day).
    - Monday after a missed Friday: no-op; the gap week is backfilled on
      the next anchor run.
    """
    from ops.ops_live_safety import atomic_write_csv, ny_today

    spy = _spy_series()
    today = str(ny_today())
    reason, row_date = _classify_run_day(pd.Timestamp(today), spy)
    if reason is not None:
        return {"recorded": False, "reason": reason}

    if book is None:
        from ops.toss_portfolio import fetch_portfolio, toss_qty_map

        book = fetch_portfolio()
        qty_map = {str(k): float(v) for k, v in toss_qty_map(book).items()}
    else:
        qty_map = {str(k): float(v) for k, v in (book.get("qty_map") or {}).items()}
    total = float(book.get("total_usd") or 0.0)
    if total <= 0:
        return {"recorded": False, "reason": "zero_or_missing_total_usd"}
    equity = float(book.get("equity_usd") or 0.0)
    cash = float(book.get("cash_usd") or 0.0)
    spy_close = float(spy.loc[pd.Timestamp(row_date)])

    df = load_daily()
    holdings = load_holdings()
    df = df[df["date"].astype(str) != row_date]
    holdings = holdings[holdings["date"].astype(str) != row_date]

    panel = load_close_panel()
    # gap days the price panel cannot cover: try fetching held-code closes from
    # yfinance (in-memory) so backfill still covers them without a full refresh
    missing_days: list = []
    if not df.empty:
        last_date = str(df["date"].max())
        missing_days = [
            ts for ts in spy.index
            if last_date < str(ts.date()) < row_date and (panel is None or ts not in panel.index)
        ]
    panel_gap_days = len(missing_days)
    if missing_days and qty_map:
        fetch_codes = set(qty_map.keys())
        # backfill values positions that are already out of the current book too
        # (e.g. a code sold today but held during the gap days)
        if not holdings.empty:
            last_hold_date = str(holdings["date"].max())
            lh = holdings[holdings["date"].astype(str) == last_hold_date]
            fetch_codes |= {str(r["code"]) for _, r in lh.iterrows()}
        panel = _extend_close_panel(
            panel, sorted(fetch_codes),
            pd.Timestamp(last_date), pd.Timestamp(row_date),
        )
        panel_gap_days = sum(
            1 for ts in spy.index
            if last_date < str(ts.date()) < row_date and (panel is None or ts not in panel.index)
        )
    # one-time legacy migration: compress pre-cadence daily rows to weekly anchors
    n_compressed = 0
    seed_first_total: Optional[float] = None
    if not df.empty:
        # capture the series' first recorded total so the real first-week return
        # survives compression + the final recompute (recompute wipes ret_1d of row 0)
        seed_first_total = pd.to_numeric(df["total_usd"].iloc[0], errors="coerce")
        df, holdings, n_compressed = compress_daily_to_weekly(df, holdings, spy, panel)
    df, holdings, n_backfilled = backfill_missing_weeks(df, holdings, spy, panel, row_date)
    # compression may have synthesized the current week's anchor: the live row below
    # replaces it, so drop the anchor date again before appending (no duplicates)
    df = df[df["date"].astype(str) != row_date]
    holdings = holdings[holdings["date"].astype(str) != row_date]

    live_row = pd.DataFrame([{
        "date": row_date, "total_usd": round(total, 6), "equity_usd": round(equity, 6),
        "cash_usd": round(cash, 6), "spy_close": round(spy_close, 6),
    }])
    df = live_row if df.empty else pd.concat([df, live_row], ignore_index=True)
    if row_date is not None and pd.Timestamp(row_date).weekday() != 4:
        # a non-Friday anchor on a weekend run usually means the SPY series is
        # truncated/stale (the real Friday is missing); holiday weeks are legitimately
        # Thursday-anchored, so warn instead of refusing
        print(
            f"WARNING: recorded anchor {row_date} is not a Friday - the SPY series may be "
            "truncated/stale; run `python ops.py refresh` if this is unexpected."
        )
    # per-code market values + weights + avg cost from the live book
    mkt_map: Dict[str, float] = {}
    cost_map: Dict[str, float] = {}
    for h in book.get("us_holdings") or []:
        code = str(h.get("symbol_raw") or h.get("code") or "").strip().upper()
        if not code or code.isdigit():
            continue
        mv = float(h.get("mkt_value") or 0.0)
        if mv > 0:
            mkt_map[code] = mv
        ap = float(h.get("avg_price") or 0.0)
        if ap > 0:
            cost_map[code] = ap
    eq_denom = equity if equity > 0 else float(sum(mkt_map.values()) or 1.0)
    sleeve_map = _sleeve_map()
    hold_rows = pd.DataFrame([
        {"date": row_date, "code": c, "qty": q,
         "weight": round(mkt_map.get(c, 0.0) / eq_denom, 6),
         "avg_cost": cost_map.get(c),
         "sleeve": sleeve_map.get(c, "")}
        for c, q in qty_map.items() if q > 0
    ], columns=HOLD_COLS)
    holdings = hold_rows if holdings.empty else pd.concat([holdings, hold_rows], ignore_index=True)
    # fill signal sleeve + carry avg cost forward for any rows that lack them (e.g. backfilled/legacy)
    if "sleeve" not in holdings.columns:
        holdings["sleeve"] = ""
    if "avg_cost" not in holdings.columns:
        holdings["avg_cost"] = None
    holdings["sleeve"] = holdings.apply(
        lambda r: _sleeve_fill(r["sleeve"], sleeve_map.get(str(r["code"]), "")),
        axis=1,
    )
    last_cost: Dict[str, float] = {}
    filled_cost: Dict[tuple, Optional[float]] = {}
    for _, r in holdings.sort_values(["date", "code"], kind="stable").iterrows():
        ac = r.get("avg_cost")
        if ac is None or pd.isna(ac) or float(ac) <= 0:
            ac = last_cost.get(str(r["code"]))
        if ac is not None and not pd.isna(ac) and float(ac) > 0:
            last_cost[str(r["code"])] = float(ac)
        filled_cost[(str(r["date"]), str(r["code"]))] = None if ac is None or pd.isna(ac) else float(ac)
    holdings["avg_cost"] = holdings.apply(
        lambda r: filled_cost.get((str(r["date"]), str(r["code"]))), axis=1,
    )
    if n_compressed:
        # pre-migration backups of the legacy per-month files (one-time)
        import shutil

        months = sorted(
            set(df["date"].astype(str).str[:7]) | set(holdings["date"].astype(str).str[:7])
        )
        for month in months:
            for path in (_daily_path(month), _holdings_path(month)):
                if path.exists() and not path.with_name(path.name + ".bak").exists():
                    try:
                        shutil.copy2(path, path.with_name(path.name + ".bak"))
                    except OSError:
                        pass

    df = recompute_returns(df)
    if n_compressed and seed_first_total is not None and seed_first_total > 0 and not df.empty:
        # the final recompute wiped ret_1d of the first row: re-apply the preserved
        # real first-week return (first legacy total -> first anchor total). Only when
        # the first row is a weekly anchor (a deferred first week stays daily).
        anchor_map = _weekly_anchor_map(spy.index)
        if _is_weekly_anchor(pd.Timestamp(df["date"].iloc[0]), anchor_map):
            first_anchor_total = float(df["total_usd"].iloc[0])
            df.loc[df.index[0], "ret_1d"] = round(first_anchor_total / seed_first_total - 1.0, 6)
    holdings = holdings.sort_values(["date", "code"]).reset_index(drop=True)
    # per-month storage: each date's row goes to its own YYYY-MM folder (readers union all);
    # dates present on disk but absent from the union are stale (e.g. legacy daily rows
    # compressed away) and are cleaned so the migration is complete on the first run
    all_dates = set(df["date"].astype(str))
    for month, chunk in df.groupby(df["date"].astype(str).str[:7], sort=True):
        mdf = _read_csv(_daily_path(month), COLS)
        drop_days = set(chunk["date"].astype(str)) | {
            d for d in mdf["date"].astype(str) if d not in all_dates
        }
        mdf = mdf[~mdf["date"].astype(str).isin(drop_days)]
        mdf = chunk.reset_index(drop=True) if mdf.empty else pd.concat([mdf, chunk.reset_index(drop=True)], ignore_index=True)
        mdf = mdf.sort_values("date").reset_index(drop=True)
        atomic_write_csv(mdf, _daily_path(month))
    all_hold_dates = set(holdings["date"].astype(str))
    for month, chunk in holdings.groupby(holdings["date"].astype(str).str[:7], sort=True):
        mdf = _read_csv(_holdings_path(month), HOLD_COLS)
        drop_days = set(chunk["date"].astype(str)) | {
            d for d in mdf["date"].astype(str) if d not in all_hold_dates
        }
        mdf = mdf[~mdf["date"].astype(str).isin(drop_days)]
        mdf = chunk.reset_index(drop=True) if mdf.empty else pd.concat([mdf, chunk.reset_index(drop=True)], ignore_index=True)
        mdf = mdf.sort_values(["date", "code"]).reset_index(drop=True)
        atomic_write_csv(mdf, _holdings_path(month))

    last = df.iloc[-1]
    return {
        "recorded": True,
        "date": row_date,
        "total_usd": total,
        "equity_usd": equity,
        "cash_usd": cash,
        "spy_close": spy_close,
        "ret_1d": None if pd.isna(last["ret_1d"]) else float(last["ret_1d"]),
        "cum_ret": float(last["cum_ret"]),
        "spy_cum_ret": float(last["spy_cum_ret"]),
        "n_rows": int(len(df)),
        "n_backfilled": n_backfilled,
        "panel_gap_days": panel_gap_days,
        "n_holdings": int(len(qty_map)),
    }


def main() -> int:
    try:
        res = record()
    except Exception as exc:
        print(f"weekly record failed: {type(exc).__name__}: {exc}")
        return 1
    if not res.get("recorded"):
        print(f"weekly: skipped ({res.get('reason')})")
        return 0
    ret = "n/a" if res["ret_1d"] is None else f"{res['ret_1d'] * 100:.2f}%"
    print(
        f"weekly: {res['date']}  total_usd={res['total_usd']:.2f}  "
        f"equity={res['equity_usd']:.2f}  cash={res['cash_usd']:.2f}  "
        f"spy_close={res['spy_close']:.2f}\n"
        f"  ret_1d={ret}  cum_ret={res['cum_ret'] * 100:.2f}%  "
        f"spy_cum_ret={res['spy_cum_ret'] * 100:.2f}%  "
        f"rows={res['n_rows']}  backfilled={res['n_backfilled']}  holdings={res['n_holdings']}\n"
        f"  -> {_daily_path(res['date'][:7])} / {_holdings_path(res['date'][:7])}\n"
        f"  refresh workbook: python ops.py excel --run-dir results/ops_runs/YYYY-MM"
    )
    if res.get("panel_gap_days"):
        print(
            f"WARNING: {res['panel_gap_days']} trading day(s) in the gap are missing from the price panel -\n"
            f"  run `python ops.py refresh` first, then `python ops.py weekly` again, so they get backfilled."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
