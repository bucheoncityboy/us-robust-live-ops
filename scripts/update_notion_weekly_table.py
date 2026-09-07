"""Rebuild the Notion 2026-08 '3) 주간 수익률' table with ALL August weekly-anchor columns pre-created.

Weekly anchors = last US trading day of each ISO week overlapping August
(Friday, rolled back on US market holidays), intersected with the month.
Fills recorded anchors from results/ops_runs/2026-08/weekly_returns.csv;
future weeks stay empty.  Re-runnable weekly: it replaces the existing
section each time and sweeps the legacy '3) 일간 수익률' section.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
TOKEN = (Path.home() / ".notion-cli" / "token").read_text(encoding="utf-8").strip()
BASE = "https://api.notion.com/v1"
PAGE = "3b49b33c-1545-8159-bab8-ea89ab811647"  # Notion "2026-08" page (rebuilt 2026-08-07; old id 89fe51d0... in trash)
SECTION_TITLE = "3) 주간 수익률"
LEGACY_SECTION_TITLE = "3) 일간 수익률"  # pre-cadence-change section, swept on first run
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2026-03-11"}

NAV_CSV = ROOT / "results" / "ops_runs" / "2026-08" / "daily_nav.csv"
RET_CSV = ROOT / "results" / "ops_runs" / "2026-08" / "weekly_returns.csv"


def cell(text):
    return [{"type": "text", "text": {"content": str(text)}}]


def fmt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, str):
        try:
            v = float(v)  # mixed-type CSV columns round-trip numbers as strings
        except ValueError:
            return v  # label such as '매도'
    return f"{float(v)*100:+.2f}%"


# US market holidays (used only to roll a weekly anchor back from a holiday Friday)
_US_HOLIDAYS_2026 = {
    pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-19"), pd.Timestamp("2026-02-16"),
    pd.Timestamp("2026-05-25"), pd.Timestamp("2026-06-19"), pd.Timestamp("2026-07-03"),
    pd.Timestamp("2026-09-07"), pd.Timestamp("2026-11-26"), pd.Timestamp("2026-12-25"),
}


def _weekly_anchor_dates(year: int, month: int) -> list:
    """Week-end anchor dates (last US trading day of each ISO week) intersecting the month."""
    week_fridays = {}
    for d in pd.bdate_range(f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-31"):
        iso = d.isocalendar()
        wk = (iso.year, iso.week)
        friday = d + timedelta(days=(4 - d.weekday()))
        while friday in _US_HOLIDAYS_2026:  # holiday Friday -> preceding trading day
            friday -= timedelta(days=1)
        week_fridays[wk] = friday
    return sorted({f.strftime("%Y-%m-%d") for f in week_fridays.values() if f.month == month})


def main():
    # 1) recorded returns (may be missing on first run)
    if RET_CSV.exists():
        df = pd.read_csv(RET_CSV, encoding="utf-8-sig")
        recorded = {c for c in df.columns if c not in ("code", "sleeve")}
    else:
        df = pd.DataFrame(columns=["code", "sleeve"])
        recorded = set()
    if df.empty:
        codes = []
    else:
        last_rec = [c for c in df.columns if c not in ("code", "sleeve")]
        last_rec = last_rec[-1] if last_rec else None
        codes = df["code"].astype(str).tolist()
        if last_rec:
            codes.sort(key=lambda c: -(pd.to_numeric(df.loc[df["code"].astype(str) == c, last_rec].iloc[0], errors="coerce") or 0.0) if df.loc[df["code"].astype(str) == c, last_rec].notna().any() else 0.0)
    sleeve_of = {}
    if not df.empty:
        for _, r in df.iterrows():
            sleeve_of[str(r["code"])] = str(r.get("sleeve") or "")

    # 2) all August 2026 weekly anchors (last US trading day of each ISO week in August)
    aug_days = _weekly_anchor_dates(2026, 8)
    # 2b) validate-before-destroy: refuse to touch the Notion page while the ledger
    # still holds legacy daily rows (a weekly ledger holds exactly one row per ISO week)
    from collections import Counter
    week_counts = Counter()
    if NAV_CSV.exists():
        nav = pd.read_csv(NAV_CSV, encoding="utf-8-sig")
        for d in nav["date"]:
            iso = pd.Timestamp(str(d)).isocalendar()
            week_counts[(iso.year, iso.week)] += 1
        nav_rows = [r for _, r in nav.iterrows() if str(r["date"]) in aug_days]
    else:
        nav_rows = []
    if not nav_rows or any(n > 1 for n in week_counts.values()):
        print(
            "WARNING: no weekly anchor rows in daily_nav.csv yet (or legacy daily rows remain) - "
            "run `python ops.py weekly` once (on an anchor day or weekend) so the legacy daily "
            "rows are compressed, then re-run this script."
        )
        sys.exit(1)

    # 3) locate & delete the existing weekly section (heading .. next heading_3, incl. both tables)
    # also sweeps the legacy "3) 일간 수익률" section and orphaned portfolio heading + table
    r = requests.get(f"{BASE}/blocks/{PAGE}/children", headers=H, timeout=60)
    r.raise_for_status()
    blocks = r.json().get("results", [])
    to_delete = []
    in_section = False
    orphan_pending = False
    for b in blocks:
        rt = b.get(b["type"], {}).get("rich_text", [])
        text = "".join(x.get("plain_text", "") for x in rt)
        is_portfolio_h = b["type"] == "heading_3" and "포트폴리오 전체 수익률" in text
        if b["type"] == "heading_3" and (SECTION_TITLE in text or LEGACY_SECTION_TITLE in text):
            in_section = True
            to_delete.append(b["id"])
            continue
        if in_section:
            if b["type"] == "heading_3" and not is_portfolio_h:
                in_section = False
            else:
                to_delete.append(b["id"])
                continue
        # outside the section: sweep orphaned portfolio heading + its table from older runs
        if is_portfolio_h:
            to_delete.append(b["id"])
            orphan_pending = True
        elif orphan_pending and b["type"] == "table":
            to_delete.append(b["id"])
            orphan_pending = False
        else:
            orphan_pending = False
    for bid in to_delete:
        requests.delete(f"{BASE}/blocks/{bid}", headers=H, timeout=60)
    print("removed old section blocks:", len(to_delete))

    # 4) summary lines from daily_nav (weekly anchor rows only; guard ran in step 2b)
    lines = []
    if NAV_CSV.exists():
        for r in nav_rows:
            ret_s = "" if pd.isna(r.get("ret_1d")) else f"{float(r['ret_1d'])*100:+.2f}%"
            cum_s = "" if pd.isna(r.get("cum_ret")) else f"{float(r['cum_ret'])*100:+.2f}%"
            lines.append(f"{r['date']}: 주간 {ret_s} / 누적 {cum_s} / total ${float(r['total_usd']):,.2f}")

    # 5) build table with ALL August weekly-anchor columns
    header = ["종목", "슬리브"] + aug_days
    rows = []
    for code in codes:
        cells = [cell(code), cell(sleeve_of.get(code, ""))]
        for d in aug_days:
            v = None
            if d in recorded and not df.empty:
                hit = df[df["code"].astype(str) == code]
                if not hit.empty:
                    v = hit.iloc[0].get(d)
            cells.append(cell(fmt(v)))
        rows.append(cells)
    table_block = {
        "object": "block", "type": "table",
        "table": {
            "table_width": len(header), "has_column_header": True, "has_row_header": False,
            "children": [{"object": "block", "type": "table_row", "table_row": {"cells": [cell(h) for h in header]}}]
            + [{"object": "block", "type": "table_row", "table_row": {"cells": c}} for c in rows],
        },
    }

    # 6) portfolio-level weekly return trend table (rows = all August weekly anchors, pre-created)
    nav_map = {}
    if NAV_CSV.exists():
        nav = pd.read_csv(NAV_CSV, encoding="utf-8-sig")
        for _, r in nav.iterrows():
            nav_map[str(r["date"])] = r
    def fmt_pct(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return f"{float(v)*100:+.2f}%"
    def fmt_usd(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return f"{float(v):,.2f}"
    p_header = ["날짜", "total_usd", "equity_usd", "cash_usd", "주간 수익률", "누적 수익률", "SPY 종가", "SPY 누적"]
    p_rows = []
    for d in aug_days:
        r = nav_map.get(d)
        if r is None:
            p_rows.append([cell(d)] + [cell("") for _ in range(len(p_header) - 1)])
        else:
            p_rows.append([
                cell(d), cell(fmt_usd(r.get("total_usd"))), cell(fmt_usd(r.get("equity_usd"))),
                cell(fmt_usd(r.get("cash_usd"))), cell(fmt_pct(r.get("ret_1d"))),
                cell(fmt_pct(r.get("cum_ret"))), cell(fmt_usd(r.get("spy_close"))),
                cell(fmt_pct(r.get("spy_cum_ret"))),
            ])
    portfolio_table = {
        "object": "block", "type": "table",
        "table": {
            "table_width": len(p_header), "has_column_header": True, "has_row_header": False,
            "children": [{"object": "block", "type": "table_row", "table_row": {"cells": [cell(h) for h in p_header]}}]
            + [{"object": "block", "type": "table_row", "table_row": {"cells": c}} for c in p_rows],
        },
    }

    children = [
        {"object": "block", "type": "heading_3",
         "heading_3": {"rich_text": [{"type": "text", "text": {"content": f"{SECTION_TITLE} (daily_nav.csv 기준)"}}]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"type": "text", "text": {"content": "\n".join(lines)}}]}},
        table_block,
        {"object": "block", "type": "heading_3",
         "heading_3": {"rich_text": [{"type": "text", "text": {"content": "포트폴리오 전체 수익률 추이"}}]}},
        portfolio_table,
    ]
    r = requests.patch(f"{BASE}/blocks/{PAGE}/children", headers=H, json={"children": children}, timeout=60)
    r.raise_for_status()
    print("appended: heading + paragraph + stock table + portfolio trend heading/table")
    print(f"stock table: {len(header)} cols, {len(rows)} rows")
    print(f"portfolio table: {len(p_header)} cols, {len(p_rows)} rows (all Aug weekly anchors pre-created)")
    print(f"filled anchors: {sorted(recorded)}")


if __name__ == "__main__":
    sys.exit(main())
