"""Build weekly portfolio return chart + per-stock weekly return table from daily_nav/daily_holdings.

NAV/holdings rows are weekly anchors (one per ISO week, last US trading day of
the week); weekly rows are stored under the legacy daily_* filenames.
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ops.ops_daily import _extend_close_panel, load_close_panel, load_daily, load_holdings, prior_anchor

OUT_DIR = Path(__file__).resolve().parent.parent / "results" / "ops_runs"

# Korean font
for fp in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"):
    try:
        font_manager.fontManager.addfont(fp)
    except Exception:
        pass
plt.rcParams["font.family"] = ["Malgun Gothic"]
plt.rcParams["axes.unicode_minus"] = False

# 1) portfolio weekly returns from daily_nav (union of months)
nav = load_daily()
if nav.empty:
    print("no daily_nav rows")
    sys.exit(1)
nav["date"] = nav["date"].astype(str)
nav["ret_1d"] = pd.to_numeric(nav["ret_1d"], errors="coerce")

# 2) per-stock anchor-to-anchor weekly returns (held codes x recorded anchors)
hold = load_holdings()
panel = load_close_panel()
# guard: a weekly ledger holds exactly one row per ISO week (the anchor, dated Friday or
# holiday-adjacent). Multiple rows in one week = legacy daily rows that must be compressed
# by the first real `python ops.py weekly` record (anchor day or weekend) before the
# weekly view is built.
from collections import Counter
week_counts = Counter()
for d in nav["date"]:
    iso = pd.Timestamp(d).isocalendar()
    week_counts[(iso.year, iso.week)] += 1
if any(n > 1 for n in week_counts.values()):
    print(
        "WARNING: daily_nav still holds legacy daily rows (multiple rows per ISO week) - "
        "run `python ops.py weekly` once (on an anchor day or weekend) to compress them, "
        "then re-run this script."
    )
    sys.exit(1)
dates = sorted(nav["date"].unique())
codes = sorted(hold["code"].astype(str).unique()) if not hold.empty else []
# cached panel may lag the recorded NAV dates (full refresh is not required for weekly
# tracking): extend it in-memory with yfinance closes for the held codes, as ops_daily does
if panel is not None and codes and dates:
    panel_max = panel.index.max()
    nav_max = pd.Timestamp(dates[-1])
    if panel_max < nav_max:
        panel = _extend_close_panel(panel, codes, panel_max, nav_max)
rows = []
for code in codes:
    row = {"code": code}
    last_held = None
    if not hold.empty:
        hh = hold[hold["code"].astype(str) == code]
        hh = hh.sort_values("date")
        if len(hh):
            sv = hh["sleeve"].iloc[-1]
            row["sleeve"] = "" if sv is None or pd.isna(sv) else str(sv)
            last_held = pd.Timestamp(str(hh["date"].iloc[-1]))
    for d in dates:
        ts = pd.Timestamp(d)
        # broker book (Toss) is the holdings SoT: once a code is out of the book,
        # later weeks are labeled as sold instead of showing a blank cell
        if last_held is not None and ts > last_held:
            row[d] = "매도"
            continue
        ret = None
        if panel is not None and code in panel.columns and ts in panel.index:
            # week-over-week: compare against the previous weekly anchor, never a prior trading day
            prior = prior_anchor(d, dates)
            if prior is not None and pd.Timestamp(prior) in panel.index:
                p0 = panel.at[pd.Timestamp(prior), code]
                p1 = panel.at[ts, code]
                if p0 is not None and p1 is not None and not pd.isna(p0) and not pd.isna(p1) and p0 > 0:
                    ret = round(p1 / p0 - 1.0, 6)
        row[d] = ret
    rows.append(row)

ret_df = pd.DataFrame(rows)
if dates:
    sort_col = pd.to_numeric(ret_df[dates[-1]], errors="coerce")
    ret_df = ret_df.loc[sort_col.sort_values(ascending=False).index].reset_index(drop=True)
csv_path = OUT_DIR / "2026-08" / "weekly_returns.csv"
ret_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
print("weekly_returns.csv ->", csv_path, "| rows:", len(ret_df))

# 3) chart: weekly portfolio return bars
fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
x = list(range(len(nav)))
vals = nav["ret_1d"].fillna(0.0).tolist()
colors = ["#C62828" if v < 0 else "#1B7F4C" for v in vals]
ax.bar(x, [v * 100 for v in vals], color=colors, width=0.6)
ax.axhline(0, color="#334155", linewidth=0.8)
ax.set_xticks(x)
ax.set_xticklabels(nav["date"].tolist(), rotation=30, ha="right", fontsize=8)
ax.set_ylabel("주간 수익률 (%)")
ax.set_title("주간 포트폴리오 수익률 (daily_nav.csv 기준)", fontsize=12)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
chart_path = OUT_DIR / "2026-08" / "weekly_return_chart.png"
fig.savefig(chart_path)
plt.close(fig)
print("chart ->", chart_path)
