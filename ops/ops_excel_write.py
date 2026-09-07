"""Fill a dated US Robust ops Excel book from monthly runner outputs.

Live sheets (01/02/05) are rebuilt from scratch every run so template merges,
demo dates, row heights, and sample holdings cannot leak into production books.
"""

from __future__ import annotations

import calendar
import json
import os
from datetime import date, datetime, time, timedelta, timezone
import re
import shutil
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.chart.data_source import AxDataSource, StrRef
from openpyxl.chart.series import DataPoint

from ops.ops_us_policy import normalize_symbol
from ops.ops_live_safety import sanitize_excel_value

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "results" / "ops_excel" / "US_Robust_Ops_Template_v1.xlsx"
CACHE_PRICES = ROOT / "data" / "us" / "us_prices_panel.parquet"
NY = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

NAVY = "0F2744"
BLUE = "1F4E79"
LIGHT = "F4F7FB"
SOFT_GREEN = "DCFCE7"
SOFT_RED = "FEE2E2"
SOFT_AMBER = "FFEDD5"
GRID = "D0D7E2"
GRAY = "666666"

thin = Border(
    left=Side(style="thin", color=GRID),
    right=Side(style="thin", color=GRID),
    top=Side(style="thin", color=GRID),
    bottom=Side(style="thin", color=GRID),
)

_STALE_DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
_SLEEVE_ORDER = {"leader": 0, "mom63": 1, "lowvol": 2}


def _sleeve_sort_key(sleeve_label: str) -> int:
    s = str(sleeve_label or "")
    parts = [p.strip() for p in s.replace("/", "+").split("+") if p.strip()]
    if not parts:
        return 9
    return min(_SLEEVE_ORDER.get(p, 9) for p in parts)


def _sort_target_df(target: pd.DataFrame) -> pd.DataFrame:
    if target.empty:
        return target
    t = target.copy()
    t["code"] = t["code"].map(normalize_symbol)
    if "sleeve" in t.columns:
        t["_so"] = t["sleeve"].map(_sleeve_sort_key)
    else:
        t["_so"] = 9
    t["_w"] = t["final_w"] if "final_w" in t.columns else 0.0
    return t.sort_values(["_so", "_w", "code"], ascending=[True, False, True]).drop(columns=["_so", "_w"])


def _sort_orders_df(orders: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return orders
    o = orders.copy()
    o["code"] = o["code"].map(normalize_symbol)
    sleeve_map = {}
    if not target.empty and "sleeve" in target.columns:
        tt = target.copy()
        tt["code"] = tt["code"].map(normalize_symbol)
        sleeve_map = dict(zip(tt["code"], tt["sleeve"]))
    if "sleeve" not in o.columns:
        o["sleeve"] = o["code"].map(lambda c: sleeve_map.get(c, ""))
    side_prio = {"SELL": 0, "HOLD": 1, "BUY": 2}
    o["_sp"] = o["side"].map(lambda x: side_prio.get(str(x), 9)) if "side" in o.columns else 9
    o["_so"] = o["sleeve"].map(_sleeve_sort_key)
    o["_tw"] = o["target_w"] if "target_w" in o.columns else 0.0
    o = o.sort_values(["_sp", "_so", "_tw", "code"], ascending=[True, True, False, True])
    o = o.drop(columns=[c for c in ["_sp", "_so", "_tw"] if c in o.columns])
    # resequence prio for display
    o = o.reset_index(drop=True)
    o["prio"] = range(1, len(o) + 1)
    return o



def _font(size: int = 8, bold: bool = False, color: str = "000000") -> Font:
    return Font(name="Malgun Gothic", size=size, bold=bold, color=color)


def _fill(rgb: str) -> PatternFill:
    return PatternFill("solid", fgColor=rgb)


def _set_cell(ws, r: int, c: int, value):
    cell = ws.cell(r, c)
    if type(cell).__name__ == "MergedCell":
        return None
    cell.value = sanitize_excel_value(value)
    cell.alignment = Alignment(horizontal="general", vertical="center", wrap_text=False)
    return cell


def _set_widths(ws, widths: List[float]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _banner(ws, title: str, subtitle: str, last_col: int = 12) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    c = ws.cell(1, 1, title)
    c.font = _font(16, True, "FFFFFF")
    c.fill = _fill(NAVY)
    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
    for col in range(1, last_col + 1):
        ws.cell(1, col).fill = _fill(NAVY)
    ws.row_dimensions[1].height = 30

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    c = ws.cell(2, 1, subtitle)
    c.font = _font(9, False, "D7E3F4")
    c.fill = _fill(BLUE)
    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
    for col in range(1, last_col + 1):
        ws.cell(2, col).fill = _fill(BLUE)
    ws.row_dimensions[2].height = 18


def _section(ws, row: int, text: str, last_col: int = 12) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    cell = ws.cell(row, 1, text)
    cell.font = _font(11, True, "FFFFFF")
    cell.fill = _fill(NAVY)
    cell.alignment = Alignment(vertical="center", wrap_text=False)
    for c in range(1, last_col + 1):
        ws.cell(row, c).fill = _fill(NAVY)
        ws.cell(row, c).border = thin
    ws.row_dimensions[row].height = 20


def _holding_month(signal_date: Optional[str]) -> Optional[str]:
    """Calendar month AFTER the signal date — the period the book is actually held.

    Packages are named by SIGNAL month (e.g. 2026-07 signal -> US_Robust_Ops_2026-07.xlsx)
    while the positions are held during the FOLLOWING month (2026-08).
    """
    if not signal_date:
        return None
    try:
        ts = pd.Timestamp(signal_date)
    except Exception:
        return None
    nxt = ts + pd.offsets.MonthEnd(0) + pd.Timedelta(days=1)
    return f"{nxt.year:04d}-{nxt.month:02d}"


def _header_row(ws, row: int, headers: List[str], start: int = 1) -> None:
    for i, h in enumerate(headers):
        cell = ws.cell(row, start + i, h)
        cell.font = _font(9, True, "FFFFFF")
        cell.fill = _fill(NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
        cell.border = thin
    ws.row_dimensions[row].height = 22


def _write_row(
    ws,
    r: int,
    vals: List[Any],
    *,
    pct_cols: Optional[Set[int]] = None,
    num_cols: Optional[Set[int]] = None,
    fill: Optional[PatternFill] = None,
) -> None:
    pct_cols = pct_cols or set()
    num_cols = num_cols or set()
    for c, v in enumerate(vals, 1):
        cell = ws.cell(r, c, sanitize_excel_value(v))
        cell.border = thin
        cell.font = _font(8)
        cell.alignment = Alignment(horizontal="general", vertical="center", wrap_text=False)
        if fill is not None:
            cell.fill = fill
        elif r % 2 == 0:
            cell.fill = _fill(LIGHT)
        if c in pct_cols and isinstance(v, float):
            cell.number_format = "0.0%"
        if c in num_cols and isinstance(v, float):
            cell.number_format = "0.000"


def _rebuild_sheet(wb, title: str):
    if title in wb.sheetnames:
        del wb[title]
    return wb.create_sheet(title)


def _assert_no_stale_signal_banners(wb, asof: str) -> None:
    if not asof:
        return
    bad: List[str] = []
    for sheet in (
        "01_Portfolio_Now",
        "02_Screen_Select",
        "04_Health",
        "05_Trade",
        "00_Config_Log",
        "03_Results",
    ):
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        for addr in ("A1", "A2"):
            val = ws[addr].value
            if val is None:
                continue
            for m in _STALE_DATE_RE.findall(str(val)):
                if m != asof:
                    bad.append(f"{sheet}!{addr} has {m} (signal={asof})")
    if bad:
        raise RuntimeError("stale demo date leaked into live workbook: " + "; ".join(bad))




def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    # Anonymous Gregorian algorithm; avoids adding a calendar dependency.
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _us_market_holidays(year: int) -> Set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),       # MLK
        _nth_weekday(year, 2, 0, 3),       # Presidents Day
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),         # Memorial Day
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),       # Labor Day
        _nth_weekday(year, 11, 3, 4),      # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    # A following year's New Year can be observed on Dec 31.
    holidays.add(_observed(date(year + 1, 1, 1)))
    return holidays


def _expected_month_end_close(year: int, month: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    holidays = _us_market_holidays(year)
    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)
    return d


def _parquet_latest_date(path: Path) -> Optional[date]:
    try:
        frame = pd.read_parquet(path)
        if frame is None or len(frame.index) == 0:
            return None
        idx = pd.to_datetime(frame.index, errors="coerce")
        idx = idx[~pd.isna(idx)]
        return pd.Timestamp(idx.max()).date() if len(idx) else None
    except Exception:
        return None


def compute_month_end_readiness(
    run_dir: Path,
    health: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    prices_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Check package readiness against the actual close-panel index, not health.json dates."""
    run_dir = Path(run_dir)
    signal_raw = str(health.get("signal_date") or "")
    try:
        signal = pd.Timestamp(signal_raw).date()
    except Exception:
        signal = None
    try:
        period = pd.Period(signal_raw[:7] or run_dir.name[:7], freq="M")
        expected = _expected_month_end_close(period.year, period.month)
    except Exception:
        expected = None

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    now_ny = instant.astimezone(NY)
    actual = _parquet_latest_date(Path(prices_path or CACHE_PRICES))

    reasons: List[str] = []
    if expected is None:
        reasons.append("EXPECTED_CLOSE_UNKNOWN")
    else:
        close_complete = now_ny.date() > expected or (
            now_ny.date() == expected and now_ny.timetz().replace(tzinfo=None) >= time(16, 0)
        )
        if not close_complete:
            reasons.append("WAIT_FOR_CLOSE")
        if actual is None or actual < expected:
            reasons.append("PRICE_BEHIND" if actual is not None else "PRICE_DATA_UNAVAILABLE")
        if signal != expected:
            reasons.append("PACKAGE_SIGNAL_MISMATCH")

    return {
        "expected_close": expected.isoformat() if expected else None,
        "actual_prices": actual.isoformat() if actual else None,
        "package_signal": signal.isoformat() if signal else signal_raw or None,
        "status": "READY" if not reasons else "BLOCK",
        "checked_kst": instant.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "reasons": reasons,
        "reason": " | ".join(reasons) if reasons else "READY",
    }


def _normalize_execution_status(value: Any) -> str:
    if value is None or value == "":
        return "NOT_SENT"
    if isinstance(value, dict):
        status = str(value.get("status") or "").strip()
        terminal = str(value.get("terminal") or "").strip()
        error = value.get("error")
        if status.upper() in {"FILLED", "FULL_FILL"} or terminal.upper() == "FULL_FILL":
            return "FILLED"
        if status.upper().startswith("FAIL:"):
            return status
        failure = terminal or status
        if failure:
            return f"FAIL:{failure}"
        return "FAIL:ERROR" if error else "NOT_SENT"
    status = str(value).strip()
    upper = status.upper()
    if upper in {"FULL_FILL", "FILLED"}:
        return "FILLED"
    if upper.startswith("FAIL:") or upper in {"NOT_SENT", "PENDING"}:
        return status
    if upper in {"PARTIAL", "PARTIAL_FILLED", "TIMEOUT_OPEN", "CANCELED", "CANCELLED", "ERROR"}:
        return f"FAIL:{upper}"
    return status


def _load_execution_status(run_dir: Path) -> Dict[str, str]:
    path = Path(run_dir) / "execute_status.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    codes = raw.get("codes") if isinstance(raw, dict) else {}
    if not isinstance(codes, dict):
        return {}
    return {normalize_symbol(k): _normalize_execution_status(v) for k, v in codes.items()}


def _execution_results(run_dir: Path, orders: pd.DataFrame) -> List[Dict[str, Any]]:
    groups: Dict[tuple, Dict[str, Any]] = {}
    est_map: Dict[tuple, float] = {}
    side_map: Dict[str, str] = {}
    if not orders.empty:
        for row in orders.itertuples():
            code = normalize_symbol(getattr(row, "code", ""))
            side = str(getattr(row, "side", "") or "").upper()
            side_map.setdefault(code, side)
            try:
                est_map[(code, side)] = float(getattr(row, "est_px", 0) or 0)
            except (TypeError, ValueError):
                pass

    for path in sorted(Path(run_dir).glob("fills_*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                item = json.loads(line)
            except Exception:
                continue
            code = normalize_symbol(item.get("code") or "")
            if not code or str(item.get("event") or "").upper() not in {"FILL", "ERROR"}:
                continue
            side = str(item.get("side") or side_map.get(code) or "").upper()
            key = (code, side)
            g = groups.setdefault(key, {
                "code": code, "side": side, "requested_qty": 0.0, "filled_qty": 0.0,
                "fill_value": 0.0, "status": "NOT_SENT", "terminal": "",
                "order_ids": [], "client_order_ids": [], "updated_utc": "", "errors": [],
            })
            try:
                g["requested_qty"] = max(float(g["requested_qty"]), float(item.get("qty") or 0))
            except (TypeError, ValueError):
                pass
            try:
                fq = float(item.get("filled_qty") or 0)
                ap = float(item.get("avg_price") or 0)
            except (TypeError, ValueError):
                fq, ap = 0.0, 0.0
            if fq > 0:
                g["filled_qty"] += fq
                if ap > 0:
                    g["fill_value"] += fq * ap
            for field, dest in (("order_id", "order_ids"), ("client_order_id", "client_order_ids")):
                value = str(item.get(field) or "").strip()
                if value and value not in g[dest]:
                    g[dest].append(value)
            utc = str(item.get("utc") or "")
            if utc >= g["updated_utc"]:
                g["updated_utc"] = utc
                terminal = str(item.get("terminal") or "").strip()
                status = str(item.get("status") or "").strip()
                if str(item.get("event") or "").upper() == "ERROR":
                    g["status"] = "FAIL:ERROR"
                    g["terminal"] = "ERROR"
                elif terminal == "FULL_FILL" or status.upper() == "FILLED":
                    g["status"] = "FILLED"
                    g["terminal"] = terminal or status
                else:
                    g["status"] = _normalize_execution_status(terminal or status)
                    g["terminal"] = terminal or status
            for field in ("error", "cancel_error", "cancellation_error"):
                error = str(item.get(field) or "").strip()
                if error and error not in g["errors"]:
                    g["errors"].append(error)

    persisted = _load_execution_status(Path(run_dir))
    for code, status in persisted.items():
        matches = [g for (c, _), g in groups.items() if c == code]
        if matches:
            for g in matches:
                g["status"] = status
        elif status != "NOT_SENT":
            side = side_map.get(code, "")
            groups[(code, side)] = {
                "code": code, "side": side, "requested_qty": 0.0, "filled_qty": 0.0,
                "fill_value": 0.0, "status": status, "terminal": "",
                "order_ids": [], "client_order_ids": [], "updated_utc": "", "errors": [],
            }

    results: List[Dict[str, Any]] = []
    for key in sorted(groups):
        g = groups[key]
        filled = float(g["filled_qty"] or 0)
        avg = float(g["fill_value"] or 0) / filled if filled > 0 else None
        est = est_map.get(key)
        slippage = None
        if avg is not None and est and est > 0:
            raw = (avg - est) / est if key[1] == "BUY" else (est - avg) / est
            slippage = max(0.0, raw)
        results.append({
            **g,
            "avg_price": avg,
            "est_price": est,
            "adverse_slippage": slippage,
            "order_ids_text": "\n".join(g["order_ids"]),
            "client_order_ids_text": "\n".join(g["client_order_ids"]),
            "errors_text": "\n".join(g["errors"]),
        })
    return results


def _publish_workbook(tmp_path: Path, out_path: Path, *, now: Optional[datetime] = None) -> Path:
    """Publish main, then updated, then timestamped recovery without losing a locked result."""
    tmp_path, out_path = Path(tmp_path), Path(out_path)
    updated = out_path.with_name(out_path.stem + "_updated" + out_path.suffix)
    instant = now or datetime.now()
    recovery = out_path.with_name(
        out_path.stem + instant.strftime("_recovery_%Y%m%d_%H%M%S") + out_path.suffix
    )
    for destination in (out_path, updated, recovery):
        try:
            os.replace(tmp_path, destination)
        except (PermissionError, OSError):
            continue
        if destination == out_path:
            cleanup = [updated]
            cleanup.extend(out_path.parent.glob(out_path.stem + "_recovery_*" + out_path.suffix))
            cleanup.extend(out_path.parent.glob(".~tmp_*"))
            for stale in cleanup:
                if stale == out_path or stale == tmp_path:
                    continue
                try:
                    stale.unlink()
                except OSError:
                    pass
        return destination
    raise PermissionError(f"could not publish workbook: {out_path}")


def _publish_holding_copy(published: Path, asof: str) -> Optional[Path]:
    """Mirror the workbook into the HOLDING-month folder (signal 2026-07 -> results/ops_runs/2026-08/).

    The signal package keeps its signal-month name (execute validation enforces
    run-dir name == signal month); the holding copy is what the operator opens
    during the holding month. It is overwritten by the real package workbook
    when the next monthly signal lands. Never fails the caller (locked file).
    """
    hm = _holding_month(asof)
    if not hm or not published.exists():
        return None
    if hm == (asof[:7] if asof else None):
        return None
    dest_dir = published.parent.parent / hm
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"US_Robust_Ops_{hm}.xlsx"
        if dest.exists():
            dest.unlink()
        shutil.copy2(published, dest)
        print(f"  holding copy -> {dest}")
        return dest
    except OSError as exc:
        print(f"  holding copy skipped (locked?): {exc}")
        return None



def _add_portfolio_visuals(ws, *, live_source: str, book, live_rows: List[Dict[str, Any]], target: pd.DataFrame, asof: str, health: Dict[str, Any]) -> None:
    """Right-side snapshot: refresh time + allocation pie data/chart."""
    # layout on the right of holdings table
    left = 17  # col Q
    ws.column_dimensions[get_column_letter(left)].width = 16
    ws.column_dimensions[get_column_letter(left + 1)].width = 14
    ws.column_dimensions[get_column_letter(left + 2)].width = 12

    now = datetime.now().astimezone()
    asof_utc = None
    if book and book.get("asof_utc"):
        asof_utc = str(book.get("asof_utc"))
    title = ws.cell(3, left, "B. SNAPSHOT / VISUAL")
    title.font = _font(11, True, "FFFFFF")
    title.fill = _fill(NAVY)
    ws.merge_cells(start_row=3, start_column=left, end_row=3, end_column=left + 2)
    for c in range(left, left + 3):
        ws.cell(3, c).fill = _fill(NAVY)

    meta = [
        ("Updated (local)", now.strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("Toss pull (UTC)", asof_utc or "n/a"),
        ("Signal asof", asof or "n/a"),
        ("Source", "STALE / REFRESH ERROR" if (book or {}).get("_stale") else ("Toss" if live_source == "toss" else "offline")),
        ("Health", "BLOCK" if (book or {}).get("_stale") else (health.get("status") or "n/a")),
        ("Cash USD", float((book or {}).get("cash_usd") or 0.0) if live_source == "toss" else "n/a"),
        ("Equity USD", float((book or {}).get("equity_usd") or 0.0) if live_source == "toss" else "n/a"),
        ("Total USD", (float((book or {}).get("total_usd") or 0.0) or (float((book or {}).get("equity_usd") or 0.0)+float((book or {}).get("cash_usd") or 0.0))) if live_source == "toss" else "n/a"),
        ("US names", len(live_rows) if live_source == "toss" else len(target)),
    ]
    r = 4
    for k, v in meta:
        ws.cell(r, left, k).font = _font(8, True, GRAY)
        ws.cell(r, left).fill = _fill(LIGHT)
        ws.cell(r, left).border = thin
        cell = ws.cell(r, left + 1, v)
        cell.font = _font(9, True, NAVY)
        cell.border = thin
        if isinstance(v, (int, float)) and k.endswith("KRW"):
            cell.number_format = "#,##0"
        r += 1

    # allocation color-key + clean pie (no per-slice labels; the color-key table below maps color -> name -> weight)
    r += 1
    ws.cell(r, left, "Allocation").font = _font(10, True, "FFFFFF")
    ws.cell(r, left).fill = _fill(BLUE)
    ws.merge_cells(start_row=r, start_column=left, end_row=r, end_column=left + 1)
    chart_top = r + 1

    rows = []
    if live_source == "toss":
        cash = float((book or {}).get("cash_usd") or 0.0)
        if cash > 0:
            rows.append(("CASH_USD", cash))
        # all holdings by weight/value (full Current Mix, not top-8 only)
        tops = sorted(live_rows, key=lambda x: -float(x.get("weight") or 0.0))
        for h in tops:
            name = str(h.get("name") or h.get("code") or "")
            val = float(h.get("mkt_value") or 0.0)
            if val <= 0 and h.get("weight") is not None:
                # fallback synthetic value from weight if needed
                total_eq = float((book or {}).get("equity_usd") or 0.0)
                val = total_eq * float(h.get("weight") or 0.0)
            if val > 0:
                rows.append((name[:12], val))
        if not live_rows and cash <= 0:
            usd = float((book or {}).get("equity_usd") or 0.0)
            if usd > 0:
                rows.append(("NON_KR_USD", usd))
            else:
                rows.append(("EMPTY", 1.0))
    else:
        if not target.empty:
            t2 = _sort_target_df(target)
            for row in t2.head(30).itertuples():
                rows.append((str(getattr(row, "name", row.code))[:12], float(row.final_w)))
        else:
            rows.append(("EMPTY", 1.0))
    total = sum(v for _, v in rows) or 1.0

    # deterministic slice colors: cash gray, holdings golden-angle spread (matches pie dPt fills)
    import colorsys
    colors: List[str] = ["6B7280"] if rows else []
    for i in range(max(0, len(rows) - 1)):
        hue = ((i * 137.508) % 360) / 360.0
        rr_, gg, bb = colorsys.hsv_to_rgb(hue, 0.65, 0.92)
        colors.append(f"{int(round(rr_ * 255)):02X}{int(round(gg * 255)):02X}{int(round(bb * 255)):02X}")

    # color-key table below the chart area (swatch | name | value | weight %)
    table_top = chart_top + 20
    for c, htxt in zip(range(left, left + 4), ("color", "name", "value", "weight %")):
        cell = ws.cell(table_top, c, htxt)
        cell.font = _font(8, True, "FFFFFF")
        cell.fill = _fill(NAVY)
    data_start = table_top + 1
    for i, (label, val) in enumerate(rows):
        rr = data_start + i
        sw = ws.cell(rr, left)
        sw.fill = _fill(colors[i])
        sw.border = thin
        ws.cell(rr, left + 1, label).border = thin
        vcell = ws.cell(rr, left + 2, round(float(val), 2))
        vcell.border = thin
        vcell.number_format = "#,##0.00"
        pcell = ws.cell(rr, left + 3, float(val) / total * 100.0)
        pcell.border = thin
        pcell.number_format = "0.00"
    data_end = data_start + len(rows) - 1

    # pie: colors only (no per-slice labels, no legend); color-key table below maps color -> name -> weight
    if rows:
        pie = PieChart()
        pie.title = "Current Mix"
        labels = Reference(ws, min_col=left + 1, min_row=data_start, max_row=data_end)
        data = Reference(ws, min_col=left + 2, min_row=table_top, max_row=data_end)
        pie.add_data(data, titles_from_data=True)
        pie.series[0].cat = AxDataSource(strRef=StrRef(f=str(labels)))
        for i in range(len(rows)):
            dp = DataPoint(idx=i)
            dp.graphicalProperties.solidFill = colors[i]
            pie.series[0].data_points.append(dp)
        pie.legend = None
        pie.width = 12
        pie.height = 8
        ws.add_chart(pie, f"Q{chart_top}")


def _build_portfolio_sheet(wb, *, asof: str, health: Dict[str, Any], book, target: pd.DataFrame, orders: pd.DataFrame) -> None:
    ws = _rebuild_sheet(wb, "01_Portfolio_Now")
    _set_widths(ws, [10, 16, 14, 10, 8, 10, 10, 12, 9, 9, 9, 10, 8, 12, 12])
    _banner(
        ws,
        "01  PORTFOLIO NOW  ·  LIVE BOOK",
        f"Current holdings from Toss US (live) · no demo numbers  |  Signal {asof or 'n/a'} → Holding {_holding_month(asof) or 'n/a'}",
        15,
    )

    readiness = health.get("_month_end_readiness") or {}
    is_stale = bool((book or {}).get("_stale") or (book or {}).get("error"))
    live_rows: List[Dict[str, Any]] = []
    live_source = "target_only"
    if book is not None:
        live_source = "toss"
        for h in book.get("us_holdings") or []:
            code = normalize_symbol(h.get("symbol_raw") or h.get("code") or "")
            if not code or code.isdigit():
                continue
            live_rows.append(
                {
                    "code": code,
                    "name": h.get("name") or code,
                    "qty": h.get("qty"),
                    "avg_px": h.get("avg_price"),
                    "last_px": h.get("last_price"),
                    "mkt_value": h.get("mkt_value"),
                    "weight": float(h.get("weight") or 0.0),
                }
            )

    labels = ["Cash USD", "Buying Power USD", "Equity USD", "Total USD", "Gross", "#Names", "Max Name", "Max Sector", "Action Today", "Health"]
    for c, lab in enumerate(labels, 1):
        cell = ws.cell(4, c, lab)
        cell.font = _font(8, True, GRAY)
        cell.fill = _fill(LIGHT)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center")

    n_live = len(live_rows)
    max_w = max((float(r.get("weight") or 0.0) for r in live_rows), default=0.0)
    cash_usd = float((book or {}).get("cash_usd") or 0.0) if live_source == "toss" else None
    bp_usd = float((book or {}).get("cash_buying_power_usd") or cash_usd or 0.0) if live_source == "toss" else None
    eq_usd = float((book or {}).get("equity_usd") or 0.0) if live_source == "toss" else None
    total_usd = float((book or {}).get("total_usd") or 0.0) if live_source == "toss" else None
    if live_source == "toss" and (not total_usd) and (cash_usd is not None or eq_usd is not None):
        total_usd = float(eq_usd or 0.0) + float(cash_usd or 0.0)
    gross = None
    if live_source == "toss" and total_usd and total_usd > 0:
        gross = float(eq_usd or 0.0) / total_usd

    vals = [
        cash_usd,
        bp_usd,
        eq_usd,
        total_usd,
        gross,
        n_live if live_source == "toss" else (len(target) if not target.empty else 0),
        f"{max_w * 100:.1f}%",
        None,
        ("BLOCK" if is_stale or readiness.get("status") != "READY" or health.get("status") == "BLOCK"
         else ("FLAT" if (live_source == "toss" and not live_rows) else "REBALANCE")),
        "STALE / REFRESH ERROR" if is_stale else (health.get("status") if isinstance(health, dict) else None),
    ]
    subs = [
        "buying power" if live_source == "toss" else None,
        "buying power" if live_source == "toss" else None,
        "stock mkt" if live_source == "toss" else None,
        "equity+cash" if live_source == "toss" else None,
        "equity/total" if live_source == "toss" else None,
        "US live" if live_source == "toss" else "target",
        "OK <15%" if max_w <= 0.15 + 1e-12 else "BREACH",
        "n/a",
        "STALE / REFRESH ERROR" if is_stale else ("no US equity" if (live_source == "toss" and not live_rows) else ("live" if live_source == "toss" else "offline")),
        "status",
    ]
    for c, v in enumerate(vals, 1):
        cell = ws.cell(5, c, v)
        cell.font = _font(12, True, NAVY)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center", wrap_text=False)
        if c in (1, 3, 5) and isinstance(v, (int, float)):
            cell.number_format = "#,##0"
        if c in (2, 4) and isinstance(v, (int, float)):
            cell.number_format = "0.00"
        if c == 6 and isinstance(v, float):
            cell.number_format = "0.0%"
    for c, v in enumerate(subs, 1):
        cell = ws.cell(6, c, v)
        cell.font = _font(7, False, GRAY)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center", wrap_text=False)

    ws.cell(8, 1, "Source").font = _font(8, True, GRAY)
    ws.cell(8, 2, "STALE / REFRESH ERROR" if is_stale else ("Toss" if live_source == "toss" else "offline")).font = _font(10, True, SOFT_RED if is_stale else BLUE)
    ws.cell(8, 3, (book or {}).get("error") if is_stale else ("flat / no US book" if (live_source == "toss" and not live_rows) else f"US names={n_live}"))
    if live_source == "toss" and book is not None:
        n_us = int(book.get("n_us") or book.get("n_non_kr") or 0)
        ws.cell(
            9,
            1,
            f"acct ...{book.get('account_no_tail')} | US={n_us} | KR ignored={int(book.get('n_kr') or 0)} | "
            f"cash_usd={float(book.get('cash_usd') or 0):.2f} | "
            f"equity_usd={float(book.get('equity_usd') or 0):.2f}",
        )

    _section(ws, 10, "A. CURRENT HOLDINGS (Toss US only)", 15)
    _header_row(
        ws,
        11,
        [
            "code",
            "name",
            "sleeve",
            "sector",
            "qty",
            "avg_px",
            "last_px",
            "mkt_value",
            "weight",
            "target_w",
            "gap_w",
            "pnl",
            "pnl_%",
            "status",
            "asof",
        ],
    )

    tw = {normalize_symbol(r.code): float(r.final_w) for r in target.itertuples()} if not target.empty else {}
    tname = {normalize_symbol(r.code): getattr(r, "name", "") for r in target.itertuples()} if not target.empty else {}
    tsleeve = {normalize_symbol(r.code): getattr(r, "sleeve", "") for r in target.itertuples()} if not target.empty else {}
    act_map: Dict[str, str] = {}
    if not orders.empty and "code" in orders.columns:
        for r in orders.itertuples():
            act_map[normalize_symbol(r.code)] = str(getattr(r, "action", "") or "")

    live_w = {r["code"]: r for r in live_rows}
    all_codes = (
        [c for c, _ in sorted(live_w.items(), key=lambda kv: -float(kv[1].get("weight") or 0.0))]
        if live_source == "toss" else sorted(tw.keys(), key=lambda x: -tw[x])
    )
    r = 12
    if live_source == "toss" and not live_rows:
        _write_row(
            ws,
            r,
            ["-", "STALE / REFRESH ERROR" if is_stale else "NO US HOLDINGS (Toss flat)", "refresh blocked" if is_stale else "cash-only / flat", "", "", "", "", "", 0.0, "", "", "", "", "BLOCK" if is_stale else "FLAT", asof],
            pct_cols={9},
        )
    else:
        for code in all_codes:
            live = live_w.get(code, {})
            cw = float(live.get("weight") or 0.0)
            tgt = float(tw.get(code) or 0.0)
            gap = tgt - cw if live_source == "toss" else 0.0
            action = act_map.get(code, "") or ("ACTIVE" if live else "TARGET")
            vals = [
                code,
                live.get("name") or tname.get(code, ""),
                tsleeve.get(code, ""),
                "",
                live.get("qty") if live else "",
                live.get("avg_px") if live else "",
                live.get("last_px") if live else "",
                live.get("mkt_value") if live else "",
                cw if live else (0.0 if live_source == "toss" else tgt),
                tgt if (live or live_source != "toss") else "",
                gap if live else "",
                "",
                "",
                action,
                asof,
            ]
            fill = _fill(SOFT_AMBER) if action in ("SELL_EXIT", "EXIT_PENDING") else None
            _write_row(ws, r, vals, pct_cols={9, 10, 11}, fill=fill)
            r += 1
            if r > 120:
                break

    # right-side snapshot + pie chart
    _add_portfolio_visuals(
        ws,
        live_source=live_source,
        book=book,
        live_rows=live_rows,
        target=target,
        asof=asof,
        health=health,
    )


def _build_screen_sheet(wb, *, asof: str, signals: pd.DataFrame, target: pd.DataFrame, orders: pd.DataFrame) -> None:
    ws = _rebuild_sheet(wb, "02_Screen_Select")
    _set_widths(ws, [12, 10, 16, 10, 10, 8, 10, 10, 12, 12, 12, 10])
    _banner(
        ws,
        "02  SCREEN & SELECTION",
        f"Universe/sleeve screens · Selected book  |  Signal as-of {asof or 'n/a'}",
        12,
    )

    tw = {normalize_symbol(r.code): float(r.final_w) for r in target.itertuples()} if not target.empty else {}
    act: Dict[str, tuple] = {}
    if not orders.empty:
        for r in orders.itertuples():
            act[normalize_symbol(r.code)] = (getattr(r, "action", ""), getattr(r, "reason", ""))

    n_leader = int((signals["sleeve"] == "leader").sum()) if not signals.empty and "sleeve" in signals.columns else 0
    n_mom = int((signals["sleeve"] == "mom63").sum()) if not signals.empty and "sleeve" in signals.columns else 0
    n_lv = int((signals["sleeve"] == "lowvol").sum()) if not signals.empty and "sleeve" in signals.columns else 0
    n_selected = int(signals["code"].astype(str).nunique()) if not signals.empty and "code" in signals.columns else len(signals)
    n_new = int((orders["action"] == "BUY_NEW").sum()) if not orders.empty and "action" in orders.columns else 0
    n_exit = int((orders["action"] == "SELL_EXIT").sum()) if not orders.empty and "action" in orders.columns else 0
    n_hold = int((orders["side"] == "HOLD").sum()) if not orders.empty and "side" in orders.columns else 0

    labels = ["Universe", "Leader", "Mom63", "LowVol", "Selected", "New", "Exit", "Hold"]
    values = [None, n_leader, n_mom, n_lv, n_selected, n_new, n_exit, n_hold]
    subs = ["top-n", "sleeve", "sleeve", "sleeve", "unique", "BUY_NEW", "SELL_EXIT", "HOLD"]
    for c, lab in enumerate(labels, 1):
        cell = ws.cell(4, c, lab)
        cell.font = _font(8, True, GRAY)
        cell.fill = _fill(LIGHT)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center", wrap_text=False)
        cell = ws.cell(5, c, values[c - 1])
        cell.font = _font(12, True, NAVY)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center", wrap_text=False)
        cell = ws.cell(6, c, subs[c - 1])
        cell.font = _font(7, False, GRAY)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center", wrap_text=False)

    _section(ws, 8, "A. FINAL SELECTED", 12)
    headers = ["sleeve", "code", "name", "sector", "score", "rank", "target_w", "prev_hold", "action", "reason", "key_factor", "note"]
    _header_row(ws, 9, headers)

    r = 10
    if not signals.empty:
        sig = signals.copy()
        sleeve_order = {"leader": 0, "mom63": 1, "lowvol": 2}
        if "sleeve" in sig.columns:
            sig["_so"] = sig["sleeve"].map(lambda x: sleeve_order.get(str(x), 9))
        else:
            sig["_so"] = 9
        if "rank" in sig.columns:
            sig = sig.sort_values(["_so", "rank"], ascending=[True, True])
        elif "score" in sig.columns:
            sig = sig.sort_values(["_so", "score"], ascending=[True, False])
        for row in sig.itertuples():
            code = normalize_symbol(getattr(row, "code", ""))
            action, reason = act.get(code, ("", ""))
            vals = [
                getattr(row, "sleeve", ""),
                code,
                getattr(row, "name", ""),
                getattr(row, "sector", ""),
                getattr(row, "score", None),
                getattr(row, "rank", None),
                tw.get(code),
                "",
                action,
                reason,
                "",
                "auto",
            ]
            fill = _fill(SOFT_RED) if action == "SELL_EXIT" else (_fill(SOFT_GREEN) if action == "BUY_NEW" else None)
            _write_row(ws, r, vals, pct_cols={7}, num_cols={5}, fill=fill)
            r += 1

    b0 = r + 2
    _section(ws, b0, "B. TARGET BOOK (unique codes / final weights)", 6)
    _header_row(ws, b0 + 1, ["code", "name", "sleeve", "final_w", "action", "reason"])
    rr = b0 + 2
    if not target.empty:
        for row in _sort_target_df(target).itertuples():
            code = normalize_symbol(row.code)
            action, reason = act.get(code, ("", ""))
            _write_row(
                ws,
                rr,
                [code, getattr(row, "name", ""), getattr(row, "sleeve", ""), float(row.final_w), action, reason],
                pct_cols={4},
            )
            rr += 1


def _build_trade_sheet(
    wb,
    *,
    run_dir: Path,
    asof: str,
    health: Dict[str, Any],
    orders: pd.DataFrame,
    target: pd.DataFrame,
) -> None:
    ws = _rebuild_sheet(wb, "05_Trade")
    widths = [6, 10, 16, 9, 13, 10, 10, 10, 11, 12, 12, 13, 12, 11, 11, 12, 18, 13, 18, 34]
    _set_widths(ws, widths)
    readiness = health.get("_month_end_readiness") or {}
    reason_text = str(readiness.get("reason") or "")
    _banner(
        ws,
        "05  TRADE  ·  TARGET -> ORDER -> FILL",
        f"Sell-first · Next-open · Signal {asof or 'n/a'} → Holding {_holding_month(asof) or 'n/a'} · Month-End {readiness.get('status', 'BLOCK')} · {reason_text}",
        20,
    )

    sizing = health.get("sizing") or {}
    toss = health.get("toss") if isinstance(health.get("toss"), dict) else {}
    n_orders = 0 if orders.empty else len(orders)
    n_sell = int((orders["side"] == "SELL").sum()) if not orders.empty and "side" in orders.columns else 0
    n_buy = int((orders["side"] == "BUY").sum()) if not orders.empty and "side" in orders.columns else 0
    n_action = n_sell + n_buy
    cap = health.get("capital_usd")
    if cap is None:
        cap = sizing.get("capital_usd")
    if cap is None and toss:
        cap = toss.get("total_usd") or toss.get("cash_usd")
    cash_usd = sizing.get("cash_usd")
    if cash_usd is None and toss:
        cash_usd = toss.get("cash_buying_power_usd")
        if cash_usd is None:
            cash_usd = toss.get("cash_usd")
    buy_n = sizing.get("buy_notional")
    if buy_n is None:
        buy_n = sizing.get("spent_notional")
    sell_n = sizing.get("sell_notional")
    net_need = sizing.get("net_cash_need")
    if net_need is None and buy_n is not None:
        net_need = float(buy_n) - float(sell_n or 0.0)
    cash_cover = sizing.get("cash_coverage")
    shortfall = sizing.get("cash_shortfall")
    if shortfall is None and cash_usd is not None and net_need is not None:
        shortfall = max(0.0, float(net_need) - float(cash_usd))
    cover_disp = f"{float(cash_cover) * 100:.1f}%" if cash_cover is not None else "n/a"

    qty_sendable = False
    if not orders.empty and "side" in orders.columns and "qty" in orders.columns:
        qty = pd.to_numeric(orders["qty"], errors="coerce").fillna(0.0)
        qty_sendable = bool(((orders["side"].isin(["BUY", "SELL"])) & (qty > 0)).any())
    sized = n_action == 0 or (cap is not None and float(cap or 0) > 0 and qty_sendable)
    if readiness.get("status") != "READY":
        send_status, approved = "MONTH_END_BLOCK", "N"
    elif health.get("status") == "BLOCK":
        send_status, approved = "BLOCK", "N"
    elif n_action == 0:
        send_status, approved = "NO_ACTION", "N"
    elif not sized:
        send_status, approved = "NOT_SIZED", "N"
    else:
        send_status, approved = "READY_TO_SEND", "CLI_REQUIRED"

    labels = [
        "Trade/Signal", "Signal Date", "Sell N", "Buy N", "Capital", "Cash USD",
        "Buy USD", "Sell USD", "Net Need", "Cash Cover", "Shortfall", "Orders",
        "Approved", "Status",
    ]
    values = [
        asof, asof, n_sell, n_buy, cap, cash_usd, buy_n, sell_n if sell_n is not None else 0,
        net_need, cover_disp, shortfall if shortfall is not None else 0, n_orders, approved, send_status,
    ]
    for c, lab in enumerate(labels, 1):
        cell = ws.cell(4, c, lab)
        cell.font = _font(8, True, GRAY)
        cell.fill = _fill(LIGHT)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center")
        cell = ws.cell(5, c, values[c - 1])
        cell.font = _font(11, True, NAVY)
        cell.border = thin
        cell.alignment = Alignment(horizontal="center")

    warning = (
        f"MONTH-END BLOCK | Expected Close {readiness.get('expected_close') or 'n/a'} | "
        f"Actual Prices {readiness.get('actual_prices') or 'n/a'} | Package Signal {readiness.get('package_signal') or 'n/a'} | "
        f"Reason {reason_text}"
        if send_status == "MONTH_END_BLOCK"
        else ("ORDER NOT SENDABLE | capital or positive qty is missing" if send_status == "NOT_SIZED"
              else ("ORDER NOT SENDABLE | package/health BLOCK" if send_status == "BLOCK"
                    else ("NO ACTION | no BUY/SELL quantity" if send_status == "NO_ACTION"
                          else "READY TO SEND VIA ops.py execute ONLY | human risk-mode decision required")))
    )
    ws.merge_cells(start_row=7, start_column=1, end_row=7, end_column=20)
    ws.cell(7, 1, warning)
    ws.cell(7, 1).font = _font(9, True, "9C0006" if send_status != "READY_TO_SEND" else NAVY)
    ws.cell(7, 1).fill = _fill(SOFT_RED if send_status in {"MONTH_END_BLOCK", "BLOCK", "NOT_SIZED"} else SOFT_AMBER)
    ws.cell(7, 1).alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[7].height = 34

    _section(ws, 9, "A. ORDER TICKET (sell-first · qty shares · CSV/package is order source of truth)", 20)
    headers = [
        "prio", "code", "name", "side", "action", "current_w", "target_w", "delta_w", "est_px",
        "px_source", "qty", "notional", "cash_need", "cash_%cap", "cash_%cash", "target_qty",
        "qty_note", "type", "status", "reason",
    ]
    _header_row(ws, 10, headers)
    status_map = _load_execution_status(run_dir)
    r = 11
    if not orders.empty:
        for i, row in enumerate(_sort_orders_df(orders, target).itertuples(), 1):
            side = str(getattr(row, "side", "") or "")
            notional = getattr(row, "notional", None)
            cash_need = getattr(row, "cash_need", None)
            if cash_need is None and notional is not None:
                try:
                    cash_need = float(notional) if side == "BUY" else (-float(notional) if side == "SELL" else 0.0)
                except (TypeError, ValueError):
                    cash_need = None
            cash_pct_cap = getattr(row, "cash_pct_of_capital", None)
            if cash_pct_cap is None and notional is not None and cap:
                try:
                    cash_pct_cap = float(notional) / float(cap)
                except (TypeError, ValueError, ZeroDivisionError):
                    cash_pct_cap = None
            cash_pct_cash = getattr(row, "cash_pct_of_cash", None)
            if cash_pct_cash is None and notional is not None and cash_usd:
                try:
                    cash_pct_cash = float(notional) / float(cash_usd) if side == "BUY" else 0.0
                except (TypeError, ValueError, ZeroDivisionError):
                    cash_pct_cash = None
            code = normalize_symbol(getattr(row, "code", ""))
            vals = [
                getattr(row, "prio", i), code, getattr(row, "name", ""), side, getattr(row, "action", ""),
                getattr(row, "current_w", None), getattr(row, "target_w", None), getattr(row, "delta_w", None),
                getattr(row, "est_px", None), getattr(row, "px_source", ""), getattr(row, "qty", None),
                notional, cash_need, cash_pct_cap, cash_pct_cash, getattr(row, "target_qty", None),
                getattr(row, "qty_note", ""), "MARKET_OPEN", status_map.get(code, "NOT_SENT"),
                getattr(row, "reason", ""),
            ]
            fill = _fill(SOFT_RED) if side == "SELL" else (_fill(SOFT_GREEN) if side == "BUY" else None)
            _write_row(ws, r, vals, pct_cols={6, 7, 8, 14, 15}, fill=fill)
            for c in (4, 5, 18, 19):
                ws.cell(r, c).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for c in (17, 20):
                ws.cell(r, c).alignment = Alignment(vertical="center", wrap_text=True)
            ws.row_dimensions[r].height = 30
            r += 1

    sum_row = r + 1
    _section(ws, sum_row, "B. CASH PLAN (보유현금 대비 얼마 사야 하나)", 20)
    _header_row(ws, sum_row + 1, [
        "capital_usd", "cash_usd", "buy_notional", "sell_notional", "net_cash_need",
        "cash_coverage", "cash_shortfall", "residual_vs_capital", "n_buy_qty", "note",
    ])
    cash_note = (
        "MONTH_END_NOT_READY" if send_status == "MONTH_END_BLOCK" else
        ("ORDER_NOT_SENDABLE" if send_status in {"NOT_SIZED", "BLOCK"} else
         ("NO_ACTION" if send_status == "NO_ACTION" else
          ("OK" if shortfall is None or float(shortfall or 0) <= 1.0 else "NEED_MORE_CASH_OR_SELL_FIRST")))
    )
    _write_row(ws, sum_row + 2, [
        cap, cash_usd, buy_n, sell_n if sell_n is not None else 0, net_need,
        float(cash_cover) if cash_cover is not None else None,
        shortfall if shortfall is not None else 0, sizing.get("residual_cash"),
        n_buy - int(sizing.get("n_buy_zero_qty") or 0) if n_buy else 0, cash_note,
    ], pct_cols={6})

    result_row = sum_row + 5
    _section(ws, result_row, "C. EXECUTION RESULTS (cumulative across fills_*.jsonl)", 20)
    result_headers = [
        "code", "side", "status", "terminal", "requested_qty", "cum_filled_qty", "actual_avg_px",
        "est_px", "adverse_slippage", "all_order_ids", "all_clientOrderIds", "updated_utc", "errors/cancel_errors",
    ]
    _header_row(ws, result_row + 1, result_headers)
    execution = _execution_results(run_dir, orders)
    rr = result_row + 2
    if not execution:
        _write_row(ws, rr, ["No automated execution records", "", "NOT_SENT"])
    else:
        for item in execution:
            _write_row(ws, rr, [
                item["code"], item["side"], item["status"], item["terminal"], item["requested_qty"],
                item["filled_qty"], item["avg_price"], item["est_price"], item["adverse_slippage"],
                item["order_ids_text"], item["client_order_ids_text"], item["updated_utc"], item["errors_text"],
            ], pct_cols={9})
            for c in (10, 11, 12, 13):
                ws.cell(rr, c).alignment = Alignment(vertical="top", wrap_text=True)
            ws.row_dimensions[rr].height = 42
            rr += 1


def _build_health_sheet(wb, *, asof: str, health: Dict[str, Any]) -> None:
    ws = _rebuild_sheet(wb, "04_Health")
    _set_widths(ws, [18, 16, 16, 16, 22, 50, 12, 14, 12, 16])
    readiness = health.get("_month_end_readiness") or {}
    _banner(
        ws,
        "04  HEALTH  ·  DATA & SYSTEM CONTROL",
        f"Actual parquet readiness · Signal {asof or 'n/a'} · {readiness.get('status', 'BLOCK')}",
        10,
    )
    labels = ["Expected Close", "Actual Prices", "Package Signal", "Month-End Ready", "Checked KST", "Reason"]
    values = [
        readiness.get("expected_close"), readiness.get("actual_prices"), readiness.get("package_signal"),
        readiness.get("status"), readiness.get("checked_kst"), readiness.get("reason"),
    ]
    for c, (label, value) in enumerate(zip(labels, values), 1):
        ws.cell(4, c, label).font = _font(8, True, GRAY)
        ws.cell(4, c).fill = _fill(LIGHT)
        ws.cell(4, c).border = thin
        ws.cell(5, c, value).font = _font(10, True, "9C0006" if readiness.get("status") != "READY" else NAVY)
        ws.cell(5, c).border = thin
        ws.cell(5, c).alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[5].height = 34

    status = str(health.get("status") or "")
    last = health.get("last_dates") or {}
    lags = health.get("lag_days") or {}
    toss = health.get("toss") or {}
    _section(ws, 8, "A. DATA FRESHNESS (latest date is read directly from parquet)", 10)
    _header_row(ws, 9, ["source", "last_date", "signal", "lag_days", "status", "note"])
    rows = [
        ("prices_parquet", readiness.get("actual_prices"), None),
        ("spy_index", last.get("index") or last.get("spy"), lags.get("index") or lags.get("spy")),
        ("valuation", last.get("valuation"), lags.get("valuation")),
        ("universe", last.get("universe") or last.get("meta"), lags.get("universe") or lags.get("meta")),
    ]
    r = 10
    for src, ld, lag in rows:
        st, note = "OK", ""
        if src == "prices_parquet":
            st = "OK" if readiness.get("actual_prices") and "PRICE_BEHIND" not in readiness.get("reasons", []) else "FAIL"
            note = "actual parquet index"
        elif src == "valuation" and (lag is None or (isinstance(lag, int) and lag > 40)):
            st, note = "WARN", "valuation lag"
        elif lag is None or (isinstance(lag, int) and lag > 5 and src != "valuation"):
            st, note = "WARN", "lag"
        _write_row(ws, r, [src, ld, asof, lag, st, note], fill=_fill(SOFT_GREEN if st == "OK" else (SOFT_AMBER if st == "WARN" else SOFT_RED)))
        r += 1

    _section(ws, 15, "B. POLICY / BOOK CHECK", 10)
    _header_row(ws, 16, ["item", "value", "limit", "status"])
    checks = [
        ("month_end_ready", readiness.get("status"), "READY", readiness.get("status")),
        ("health_status", status, "not BLOCK", status or "n/a"),
        ("weight_sum", health.get("weight_sum"), 1.0, "OK" if abs(float(health.get("weight_sum") or 0) - 1.0) <= 1e-4 else "FAIL"),
        ("max_name_w", health.get("max_name_w"), 0.15, "OK" if health.get("max_name_w") is None or float(health.get("max_name_w")) <= 0.15 + 1e-9 else "FAIL"),
        ("n_names", health.get("n_names"), "-", "OK" if health.get("n_names") else "FAIL"),
        ("sector_cap", health.get("sector_cap"), 0.40, str(health.get("sector_cap") or "SKIPPED")),
        ("reasons", ",".join(health.get("reasons") or []) or "none", "-", status or "n/a"),
    ]
    for r, item in enumerate(checks, 17):
        _write_row(ws, r, list(item))

    _section(ws, 25, "C. TOSS PORTFOLIO STATUS", 10)
    _header_row(ws, 26, ["field", "value"])
    toss_rows = [
        ("status", toss.get("status") or ("error" if toss.get("error") else "n/a")),
        ("account_tail", toss.get("account_no_tail")), ("n_us", toss.get("n_us")),
        ("n_kr", toss.get("n_kr")), ("ops_ready", toss.get("ops_ready")),
        ("flat", toss.get("flat")), ("cash_usd", toss.get("cash_usd")),
        ("cash_buying_power_usd", toss.get("cash_buying_power_usd")),
        ("equity_usd", toss.get("equity_usd")), ("total_usd", toss.get("total_usd")),
        ("error", toss.get("error") or ""),
    ]
    for r, (key, value) in enumerate(toss_rows, 27):
        _write_row(ws, r, [key, value])
def _prior_anchor(d: str, dates: list) -> Optional[str]:
    """Previous weekly anchor date strictly before ``d`` (``dates`` must be ascending)."""
    from ops.ops_daily import prior_anchor

    return prior_anchor(d, dates)


def _build_weekly_sheet(wb) -> None:
    """06_Weekly_Trend: portfolio summary table + per-stock value trend matrix + total-NAV line chart."""
    from ops.ops_daily import load_close_panel, load_daily, load_holdings

    ws = _rebuild_sheet(wb, "06_Weekly_Trend")
    _set_widths(ws, [12, 12, 12, 11, 11, 11, 12, 13, 13, 13])
    _banner(
        ws,
        "06  WEEKLY TREND · LIVE NAV vs SPY",
        "Toss total_usd (live snapshot) · skipped weekly anchors backfilled from last holdings x close · "
        "deposits/withdrawals distort those days",
        15,
    )
    df = load_daily()
    if df.empty:
        ws.cell(4, 1, "No weekly snapshots yet — run: python ops.py weekly").font = _font(10, True, GRAY)
        return

    # A. portfolio summary table
    _section(ws, 4, "A. PORTFOLIO SUMMARY", 10)
    headers = ["date", "total_usd", "equity_usd", "cash_usd", "spy_close",
               "ret_1d", "cum_ret", "spy_cum_ret"]
    _header_row(ws, 5, headers)
    r = 6
    for _, row in df.iterrows():
        vals = [
            str(row["date"]),
            float(row["total_usd"]),
            float(row["equity_usd"]),
            float(row["cash_usd"]),
            float(row["spy_close"]),
            None if pd.isna(row["ret_1d"]) else float(row["ret_1d"]),
            float(row["cum_ret"]),
            float(row["spy_cum_ret"]),
        ]
        _write_row(ws, r, vals, pct_cols={6, 7, 8})
        for c in (2, 3, 4, 5):
            ws.cell(r, c).number_format = "#,##0.00"
        r += 1
    summary_end = r - 1

    # B. weekly portfolio return bar chart (ret_1d per recorded anchor)
    ret_ref = Reference(ws, min_col=6, min_row=5, max_row=summary_end)
    cats_ref = Reference(ws, min_col=1, min_row=6, max_row=summary_end)
    bar = BarChart()
    bar.type = "col"
    bar.title = "주간 포트폴리오 수익률 (ret_1d)"
    bar.add_data(ret_ref, titles_from_data=True)
    bar.series[0].cat = AxDataSource(strRef=StrRef(f=str(cats_ref)))
    bar.y_axis.number_format = "0.0%"
    bar.y_axis.title = "weekly return"
    bar.x_axis.title = "date"
    bar.width = 16
    bar.height = 8
    ws.add_chart(bar, f"A{summary_end + 2}")

    # C/D/E. per-stock trend matrices (rows=tickers, cols=dates)
    holdings = load_holdings()
    panel = load_close_panel()
    dates = [str(d) for d in df["date"]]
    matrix_top = summary_end + 20
    matrix_end = matrix_top + 1
    if holdings.empty or panel is None:
        _section(ws, matrix_top, "B. PER-STOCK TREND", 10)
        ws.cell(matrix_top + 1, 1, "no holdings snapshots yet").font = _font(9, True, GRAY)
    else:
        h = holdings.sort_values(["date", "code"])
        qty_by_date: Dict[str, Dict[str, float]] = {}
        w_by_date: Dict[str, Dict[str, Optional[float]]] = {}
        cur: Dict[str, float] = {}
        cur_w: Dict[str, Optional[float]] = {}
        for d in dates:
            for _, hr in h[h["date"].astype(str) == d].iterrows():
                cur[str(hr["code"])] = float(hr["qty"])
                wv = hr.get("weight")
                cur_w[str(hr["code"])] = None if wv is None or pd.isna(wv) else float(wv)
            qty_by_date[d] = dict(cur)
            w_by_date[d] = dict(cur_w)
        codes = sorted(cur.keys())

        def stock_value(code: str, d: str) -> Optional[float]:
            ts = pd.Timestamp(d)
            if code not in panel.columns or ts not in panel.index:
                return None
            px = panel.at[ts, code]
            q = qty_by_date.get(d, {}).get(code, 0.0)
            if q <= 0 or px is None or pd.isna(px):
                return None
            return round(q * float(px), 2)

        def stock_weekly_return(code: str, d: str) -> Optional[float]:
            """Week-over-week return (fraction) vs the previous weekly anchor close (not prior trading day)."""
            ts = pd.Timestamp(d)
            if code not in panel.columns or ts not in panel.index:
                return None
            prior = _prior_anchor(d, dates)
            if prior is None:
                return None
            p0 = panel.at[pd.Timestamp(prior), code]
            p1 = panel.at[ts, code]
            if p0 is None or p1 is None or pd.isna(p0) or pd.isna(p1) or p0 <= 0:
                return None
            return p1 / p0 - 1.0

        last_d = dates[-1]
        codes = sorted(codes, key=lambda c: -(stock_value(c, last_d) or 0.0))
        sleeve_by_code: Dict[str, str] = {}
        cost_by_code: Dict[str, Optional[float]] = {}
        for _, hr in h[h["date"].astype(str) == last_d].iterrows():
            code = str(hr["code"])
            sleeve_by_code[code] = str(hr.get("sleeve") or "")
            ac = hr.get("avg_cost")
            cost_by_code[code] = None if ac is None or pd.isna(ac) else float(ac)

        def write_matrix(top: int, title: str, cell_value, is_pct: bool) -> int:
            _section(ws, top, title, 10)
            hdr_row = top + 1
            _header_row(ws, hdr_row, ["code", "sleeve", "avg_cost"] + dates)
            mr = hdr_row + 1
            for code in codes:
                vals = [code, sleeve_by_code.get(code, ""), cost_by_code.get(code)] + [cell_value(code, d) for d in dates]
                pct_cols = {c for c in range(4, len(vals) + 1)} if is_pct else None
                _write_row(ws, mr, vals, pct_cols=pct_cols)
                ws.cell(mr, 3).number_format = "#,##0.00"
                if not is_pct:
                    for c in range(4, len(vals) + 1):
                        ws.cell(mr, c).number_format = "#,##0.00"
                mr += 1
            return mr - 1

        matrix_end = write_matrix(
            matrix_top, "C. PER-STOCK WEEKLY RETURN TREND (anchor-to-anchor)", stock_weekly_return, True,
        )
        matrix_end = write_matrix(
            matrix_end + 2, "D. PER-STOCK VALUE TREND (qty x close, USD)", stock_value, False,
        )
        matrix_end = write_matrix(
            matrix_end + 2,
            "E. PER-STOCK WEIGHT TREND (share of equity)",
            lambda code, d: w_by_date.get(d, {}).get(code),
            True,
        )

    # F. total portfolio NAV line chart (single series)

    nav_ref = Reference(ws, min_col=2, min_row=5, max_row=summary_end)
    cats = Reference(ws, min_col=1, min_row=6, max_row=summary_end)
    chart = LineChart()
    chart.title = "총 포트폴리오 NAV 추이 (total_usd)"
    chart.add_data(nav_ref, titles_from_data=True)
    chart.series[0].cat = AxDataSource(strRef=StrRef(f=str(cats)))
    chart.y_axis.number_format = "#,##0"
    chart.y_axis.title = "total USD"
    chart.x_axis.title = "date"
    chart.width = 18
    chart.height = 8
    ws.add_chart(chart, f"A{matrix_end + 2}")


def write_ops_xlsx(
    run_dir: Path,
    *,
    master: Path = MASTER,
    out_name: Optional[str] = None,
    positions: Optional[str] = "toss",
    toss_book: Optional[Dict[str, Any]] = None,
    prices_path: Optional[Path] = None,
) -> Path:
    run_dir = Path(run_dir)
    if not master.exists():
        raise FileNotFoundError(master)

    health = json.loads((run_dir / "health.json").read_text(encoding="utf-8"))
    health["_month_end_readiness"] = compute_month_end_readiness(run_dir, health, prices_path=prices_path)
    signals = pd.read_csv(run_dir / "signals.csv")
    target = pd.read_csv(run_dir / "target.csv")
    orders = (
        pd.read_csv(run_dir / "orders_preview.csv")
        if (run_dir / "orders_preview.csv").exists()
        else pd.DataFrame()
    )

    # live Toss book (read-only)
    book = toss_book
    if book is None and positions and str(positions).strip().lower() in {"toss", "toss://", "toss:live"}:
        try:
            from ops.toss_portfolio import fetch_portfolio

            book = fetch_portfolio()
        except Exception as e:
            book = {
                "error": str(e),
                "_stale": True,
                "us_holdings": [],
                "ops_ready": False,
                "flat": True,
                "n_us": 0,
                "n_kr": 0,
            }
    if book is not None:
        health["toss"] = {
            "status": book.get("status") or ("error" if book.get("error") else "ok"),
            "account_no_tail": book.get("account_no_tail"),
            "n_us": book.get("n_us"),
            "n_kr": book.get("n_kr"),
            "ops_ready": book.get("ops_ready"),
            "flat": book.get("flat"),
            "equity_usd": book.get("equity_usd"),
            "cash_usd": book.get("cash_usd"),
            "cash_buying_power_usd": book.get("cash_buying_power_usd"),
            "total_usd": book.get("total_usd"),
            "error": book.get("error"),
            "stale": bool(book.get("_stale")),
        }

    asof = str(health.get("signal_date") or "")
    yyyymm = asof[:7] if asof else run_dir.name
    out_path = run_dir / (out_name or f"US_Robust_Ops_{yyyymm}.xlsx")
    tmp_path = run_dir / f".~tmp_{out_path.name}"
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except OSError:
        pass
    shutil.copy2(master, tmp_path)
    wb = load_workbook(tmp_path)

    # Config log (keep sheet, stamp live asof only)
    if "00_Config_Log" in wb.sheetnames:
        ws = wb["00_Config_Log"]
        try:
            ws["A1"].value = "US-ROBUST OPS  ·  CONFIG & AUDIT LOG"
        except Exception:
            pass
        for r in range(6, 40):
            key = ws.cell(r, 1).value
            if key == "asof_policy":
                ws.cell(r, 2).value = asof
            if key == "version":
                ws.cell(r, 2).value = f"v1-ops-{yyyymm}"
        ws["A2"] = f"Auto-filled from ops.ops_monthly_run · signal {asof} · status {health.get('status')}"
        # Template checklist/audit rows are examples only; never carry them into live workbooks.
        for r in range(39, 80):
            for c in range(1, 11):
                if r >= 51 or c in (6, 8):
                    cell = ws.cell(r, c)
                    if type(cell).__name__ != "MergedCell":
                        cell.value = None
        ws.cell(39, 6).value = "CLI_REQUIRED"

    # Live sheets: full rebuild (no template residue)
    _build_health_sheet(wb, asof=asof, health=health)
    _build_portfolio_sheet(wb, asof=asof, health=health, book=book, target=target, orders=orders)
    _build_screen_sheet(wb, asof=asof, signals=signals, target=target, orders=orders)
    _build_trade_sheet(wb, run_dir=run_dir, asof=asof, health=health, orders=orders, target=target)
    _build_weekly_sheet(wb)

    if "03_Results" in wb.sheetnames:
        del wb["03_Results"]
    ws_results = wb.create_sheet("03_Results")
    ws_results["A1"] = "03 RESULTS · READ-ONLY"
    ws_results["A2"] = f"No synthetic live performance is shown · signal {asof}"
    ws_results["A3"] = "Research results remain under results/us_robust and are not live ledger data."

    # Keep a stable sheet order
    order = [
        "00_Config_Log",
        "01_Portfolio_Now",
        "02_Screen_Select",
        "03_Results",
        "04_Health",
        "05_Trade",
        "06_Weekly_Trend",
    ]
    for i, name in enumerate(order):
        if name in wb.sheetnames:
            wb.move_sheet(name, offset=i - wb.sheetnames.index(name))

    _assert_no_stale_signal_banners(wb, asof)

    wb.save(tmp_path)
    wb.close()
    published = _publish_workbook(tmp_path, out_path)
    _publish_holding_copy(published, asof)
    return published


def main():
    import argparse

    p = argparse.ArgumentParser(description="Fill US Robust ops Excel from run dir")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--master", default=None)
    p.add_argument(
        "--positions",
        default="toss",
        help="default 'toss' live book; CSV path; or 'none'",
    )
    args = p.parse_args()
    master = Path(args.master) if args.master else MASTER
    out = write_ops_xlsx(Path(args.run_dir), master=master, positions=args.positions)
    print("WROTE", out)


if __name__ == "__main__":
    main()
