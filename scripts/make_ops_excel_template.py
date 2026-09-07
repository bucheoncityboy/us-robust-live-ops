"""US-Robust Ops Excel template (asset-manager style, 6 sheets)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parent.parent / "results" / "ops_excel" / "US_Robust_Ops_Template_v1.xlsx"

NAVY = "0F2744"
BLUE = "1F4E79"
ACCENT = "C45C26"
LIGHT = "F4F7FB"
GRID = "D0D7E2"
GRAY = "5B6573"
GREEN = "1B7F4C"
RED = "B91C1C"
YELLOW = "FEF3C7"
LOCKED = "F1F5F9"
SOFT_GREEN = "DCFCE7"
SOFT_RED = "FEE2E2"
SOFT_BLUE = "DBEAFE"
SOFT_AMBER = "FFEDD5"
INPUT_BLUE = "1D4ED8"

thin = Border(
    left=Side(style="thin", color=GRID),
    right=Side(style="thin", color=GRID),
    top=Side(style="thin", color=GRID),
    bottom=Side(style="thin", color=GRID),
)


def ffill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def fnt(size=10, bold=False, color="1E2430") -> Font:
    return Font(name="Malgun Gothic", size=size, bold=bold, color=color)


def set_widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def banner(ws, title: str, subtitle: str, last_col: int = 12):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    c = ws.cell(1, 1, title)
    c.font = fnt(16, True, "FFFFFF")
    c.fill = ffill(NAVY)
    c.alignment = Alignment(vertical="center", horizontal="left")
    ws.row_dimensions[1].height = 30
    for col in range(1, last_col + 1):
        ws.cell(1, col).fill = ffill(NAVY)

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    c = ws.cell(2, 1, subtitle)
    c.font = fnt(9, False, "D7E3F4")
    c.fill = ffill(BLUE)
    for col in range(1, last_col + 1):
        ws.cell(2, col).fill = ffill(BLUE)
    ws.row_dimensions[2].height = 18


def section(ws, row: int, col: int, text: str, span: int = 8):
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
    cell = ws.cell(row, col, text)
    cell.font = fnt(11, True, "FFFFFF")
    cell.fill = ffill(NAVY)
    cell.alignment = Alignment(vertical="center")
    for i in range(span):
        ws.cell(row, col + i).fill = ffill(NAVY)
        ws.cell(row, col + i).border = thin
    ws.row_dimensions[row].height = 20


def header_row(ws, row: int, headers, start: int = 1):
    for i, h in enumerate(headers):
        cell = ws.cell(row, start + i, h)
        cell.font = fnt(9, True, "FFFFFF")
        cell.fill = ffill(NAVY)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin
    ws.row_dimensions[row].height = 26


def kpi(ws, r: int, c: int, label: str, value, sub: str = "", color: str = NAVY):
    a = ws.cell(r, c, label)
    a.font = fnt(8, True, GRAY)
    a.fill = ffill(LIGHT)
    a.alignment = Alignment(horizontal="center")
    a.border = thin
    b = ws.cell(r + 1, c, value)
    b.font = fnt(13, True, color)
    b.alignment = Alignment(horizontal="center", vertical="center")
    b.border = thin
    ws.row_dimensions[r + 1].height = 22
    d = ws.cell(r + 2, c, sub)
    d.font = fnt(7, False, GRAY)
    d.alignment = Alignment(horizontal="center")
    d.border = thin


def put_rows(ws, start_row: int, rows, pct_cols=None, money_cols=None, input_cols=None):
    pct_cols = pct_cols or set()
    money_cols = money_cols or set()
    input_cols = input_cols or set()
    for i, row in enumerate(rows):
        r = start_row + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(8)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if c in input_cols:
                cell.font = fnt(8, True, INPUT_BLUE)
                cell.fill = ffill(YELLOW)
            elif r % 2 == 0:
                cell.fill = ffill(LIGHT)
            if c in pct_cols and isinstance(v, float):
                cell.number_format = "0.0%"
            if c in money_cols and isinstance(v, (int, float)):
                cell.number_format = "#,##0"


def finish_sheet(ws, tab_color: str):
    ws.freeze_panes = "A3"
    ws.print_title_rows = "1:2"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = tab_color


def build_config(wb: Workbook):
    ws = wb.active
    ws.title = "00_Config_Log"
    set_widths(ws, [24, 20, 28, 12, 16, 16, 16, 16, 18, 14])
    banner(
        ws,
        "US-ROBUST OPS  ·  CONFIG & AUDIT LOG",
        "Policy constitution · Checklist · Reason codes · Exception log  |  Internal use only",
        10,
    )

    section(ws, 4, 1, "A. STRATEGY CONSTITUTION (버전업 시에만 변경)", 4)
    header_row(ws, 5, ["parameter", "value", "description", "editable"])
    cfg = [
        ("strategy_id", "US-Robust-L60-M63-LV20", "표준 전략 코드", "NO"),
        ("version", "v1.0.0", "라이브 규칙 버전", "NO"),
        ("asof_policy", "(filled by ops)", "정책 동결일", "NO"),
        ("sleeve_leader", 0.60, "Leader target weight", "NO"),
        ("sleeve_mom63", 0.20, "Mom63 target weight", "NO"),
        ("sleeve_lowvol", 0.20, "LowVol target weight", "NO"),
        ("weighting", "EQUAL", "equal-within-sleeve", "NO"),
        ("cap_name", 0.15, "단일 종목 상한", "NO"),
        ("cap_sector", 0.40, "단일 섹터 상한", "NO"),
        ("rebalance", "MONTHLY_NAMES", "종목 월 1회", "NO"),
        ("exec_rule", "NEXT_OPEN", "월말 신호 → 다음 시가", "NO"),
        ("cost_bps_rt", 10, "왕복 비용 가정(bp)", "NO"),
        ("mdd_L1", -0.15, "MDD -15% → 주식 50%", "NO"),
        ("mdd_L2", -0.25, "MDD -25% → 방어/신규중단", "NO"),
        ("exit_core", "SIGNAL_DROP", "본체 청산=월말 신호 탈락", "NO"),
        ("event_exit", "OFF", "이벤트 해석 청산 안 함", "NO"),
        ("hard_stop", "OFF", "개별 하드스탑 기본 OFF", "NO"),
        ("weekly_name_refresh", "OFF", "주간 종목 재선정 금지", "NO"),
        ("drift_band", 0.03, "옵션: 주간 비중 밴드", "NO"),
        ("benchmark", "SPY", "벤치마크", "NO"),
        ("pm_owner", "PM", "최종 승인자", "YES"),
    ]
    for i, row in enumerate(cfg):
        r = 6 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c == 2 and isinstance(v, float) and abs(v) <= 1:
                cell.number_format = "0.00%"
            if row[3] == "NO" and c == 2:
                cell.fill = ffill(LOCKED)
            if row[3] == "YES" and c == 2:
                cell.fill = ffill(YELLOW)
                cell.font = fnt(9, True, INPUT_BLUE)
            if r % 2 == 0 and not (row[3] == "NO" and c == 2):
                if c != 2 or row[3] != "YES":
                    cell.fill = ffill(LIGHT)

    section(ws, 28, 1, "B. STANDING PROHIBITIONS", 8)
    for i, t in enumerate(
        [
            "1) 물타기 / 평단 맞추기 추가매수 금지",
            "2) 이벤트·뉴스 해석 기반 중간 청산 금지",
            "3) 타이트 개별 손절(-5~-10%) 금지",
            "4) 주간 종목 재선정 금지",
            "5) 레짐 자동 전량 청산 / 과스위치 금지",
            "6) 라이브 월중 파라미터 즉석 변경 금지",
            "7) 엑셀에서 팩터 점수 재계산 금지 (Python only)",
        ]
    ):
        ws.merge_cells(start_row=29 + i, start_column=1, end_row=29 + i, end_column=8)
        cell = ws.cell(29 + i, 1, t)
        cell.font = fnt(9, True, RED)

    section(ws, 37, 1, "C. REASON CODES", 2)
    header_row(ws, 38, ["code", "meaning"])
    codes = [
        ("NEW_ENTRY", "신규 편입"),
        ("EXIT_SIGNAL", "월말 신호 탈락 청산"),
        ("REWEIGHT", "목표 비중 재설정"),
        ("TRIM_CAP15", "종목 15% 상한 trim"),
        ("TRIM_SECTOR40", "섹터 40% 상한 trim"),
        ("MDD_DELEVERAGE_15", "MDD -15% 서킷"),
        ("MDD_DELEVERAGE_25", "MDD -25% 방어"),
        ("DRIFT_REBALANCE", "주간 3% 드리프트(옵션)"),
        ("DATA_DELAY", "데이터 지연 리밸 연기"),
        ("MANUAL_EXCEPTION", "예외(로그 필수)"),
    ]
    put_rows(ws, 39, codes)

    section(ws, 37, 4, "D. MONTH-END CHECKLIST", 5)
    header_row(ws, 38, ["#", "check_item", "pass", "owner", "timestamp"], start=4)
    checks = [
        (1, "Data health OK", "Y", "PM", ""),
        (2, "Signals import done", "Y", "PM", ""),
        (3, "Target sum = 1.00", "Y", "PM", ""),
        (4, "Caps 15%/40% pass", "Y", "PM", ""),
        (5, "Sleeve ~60/20/20", "Y", "PM", ""),
        (6, "Orders sell-first built", "Y", "PM", ""),
        (7, "No exception trade", "Y", "PM", ""),
        (8, "PM final approval", "", "PM", ""),
    ]
    for i, row in enumerate(checks):
        r = 39 + i
        for c, v in enumerate(row, 4):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c == 6:
                cell.fill = ffill(YELLOW)
                cell.font = fnt(9, True, INPUT_BLUE)

    section(ws, 49, 1, "E. AUDIT / EXCEPTION LOG", 9)
    header_row(
        ws,
        50,
        ["datetime", "actor", "action", "object", "before", "after", "reason_code", "rule_break", "note"],
    )
    logs = [
        ("", "PM", "APPROVE_TARGET", "2026-06", "-", "Approved", "", "N", "월말 목표 승인"),
        ("", "PM", "SEND_ORDERS", "batch", "Ready", "Sent", "EXIT_SIGNAL", "N", "매도 우선"),
        ("", "PM", "FILLS_POSTED", "batch", "-", "Done", "REWEIGHT", "N", "체결 반영"),
        ("", "PM", "DAILY_REVIEW", "portfolio", "-", "NONE", "", "N", "breach 없음"),
    ]
    put_rows(ws, 51, logs)
    ws.cell(56, 1, "NOTE: 노란 칸=수동 입력 · 회색=정책 잠금 · 예외는 반드시 rule_break=Y 로 기록").font = fnt(8, False, GRAY)
    finish_sheet(ws, NAVY)


def build_portfolio(wb: Workbook):
    ws = wb.create_sheet("01_Portfolio_Now")
    set_widths(ws, [10, 14, 10, 12, 8, 10, 10, 12, 9, 9, 9, 11, 8, 13, 12])
    banner(
        ws,
        "01  PORTFOLIO NOW  ·  LIVE BOOK & RISK STATE",
        "Current holdings from Toss US (live) · blank KPIs until ops fill · no demo numbers",
        15,
    )
    # IMPORTANT: do NOT put sample NAV/PnL/holdings here.
    # ops_excel_write copies this master every run; fake numbers confuse live ops.
    kpis = [
        (1, "NAV", "", "live only"),
        (2, "Day PnL", "", "live only"),
        (3, "MTD", "", "live only"),
        (4, "YTD", "", "live only"),
        (5, "MDD", "", "live only"),
        (6, "Gross", "", "live only"),
        (7, "#Names", "", "Toss US"),
        (8, "Max Name", "", "cap 15%"),
        (9, "Max Sector", "", "cap 40%"),
        (10, "Action Today", "", "FLAT/REBALANCE"),
    ]
    for col, label, val, sub in kpis:
        kpi(ws, 4, col, label, val, sub, ACCENT if col == 10 else NAVY)

    ws.cell(8, 1, "Sleeve L/M63/LV").font = fnt(8, True, GRAY)
    ws.cell(8, 2, "").font = fnt(10, True, BLUE)
    ws.cell(8, 4, "Target 60/20/20").font = fnt(8, False, GRAY)
    ws.cell(8, 6, "Data Health").font = fnt(8, True, GRAY)
    cell = ws.cell(8, 7, "")
    cell.font = fnt(11, True, GREEN)
    cell.fill = ffill(SOFT_GREEN)

    section(ws, 10, 1, "A. CURRENT HOLDINGS (Toss US live only; empty = FLAT)", 15)
    header_row(
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
            "entry_date",
        ],
    )
    # No demo holdings rows — filled by ops_excel_write from Toss / targets.
    ws.cell(12, 1, "-").font = fnt(8, False, GRAY)
    ws.cell(12, 2, "NO DEMO HOLDINGS").font = fnt(8, False, GRAY)
    ws.cell(12, 14, "EMPTY").font = fnt(8, False, GRAY)

    ws.cell(25, 1, "* Live ops fills this table from Toss US holdings. Demo stocks removed on purpose.").font = fnt(8, False, GRAY)

    section(ws, 27, 1, "B. SLEEVE / SECTOR SNAPSHOT", 10)
    header_row(ws, 28, ["sleeve", "weight", "target", "gap", "n"])
    put_rows(
        ws,
        29,
        [
            ("Leader", "", 0.60, "", ""),
            ("Mom63", "", 0.20, "", ""),
            ("LowVol", "", 0.20, "", ""),
            ("Cash", "", 0.00, "", ""),
        ],
        pct_cols={3},
    )
    header_row(ws, 28, ["sector", "weight", "limit", "OK"], start=7)
    # no demo sector weights
    for i, row in enumerate([("—", "", 0.40, "")]):
        for c, v in enumerate(row, 7):
            cell = ws.cell(29 + i, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c in (8, 9) and isinstance(v, float):
                cell.number_format = "0.0%"

    section(ws, 35, 1, "C. LIMIT MONITOR", 6)
    header_row(ws, 36, ["item", "limit", "current", "buffer", "breach", "action"])
    limits = [
        ("max_name_weight", "15%", "", "", "N", "—"),
        ("max_sector_weight", "40%", "", "", "N", "—"),
        ("mdd_L1", "-15%", "", "", "N", "—"),
        ("mdd_L2", "-25%", "", "", "N", "—"),
        ("signal_exit_pending", "—", "", "—", "N", "—"),
    ]
    put_rows(ws, 37, limits)
    for r in range(37, 42):
        if ws.cell(r, 5).value == "N":
            ws.cell(r, 5).fill = ffill(SOFT_GREEN)
    ws.cell(
        43,
        1,
        "ACTION RULE: no breach → NONE | name>15% or sector>40% → TRIM | MDD≤-15% → DELEVERAGE | month-end → REBALANCE",
    ).font = fnt(8, False, GRAY)
    finish_sheet(ws, GREEN)


def build_screen(wb: Workbook):
    ws = wb.create_sheet("02_Screen_Select")
    set_widths(ws, [10, 10, 14, 12, 10, 8, 10, 10, 12, 12, 14, 24])
    banner(
        ws,
        "02  SCREEN & SELECTION  ·  CANDIDATES → FINAL PICKS",
        "Universe/sleeve screens · Selected book · Reject reasons  |  Signal as-of (filled by ops)",
        12,
    )
    for col, label, val, sub in [
        (1, "Universe", "312", "pass"),
        (2, "Leader Pass", "48", "eligible"),
        (3, "Mom63 Pass", "36", "eligible"),
        (4, "LowVol Pass", "29", "eligible"),
        (5, "Selected", "24", "final"),
        (6, "New", "4", "entries"),
        (7, "Exit", "3", "drops"),
        (8, "Hold", "17", "keep"),
    ]:
        kpi(ws, 4, col, label, val, sub)

    section(ws, 8, 1, "A. FINAL SELECTED (승인 대상)", 12)
    header_row(
        ws,
        9,
        [
            "sleeve",
            "code",
            "name",
            "sector",
            "score",
            "rank",
            "target_w",
            "prev_hold",
            "action",
            "reason",
            "key_factor",
            "note",
        ],
    )
    selected = [
        ("Leader", "AMAT", "Applied Materials", "Info Tech", 0.92, 1, 0.086, "Y", "REWEIGHT", "REWEIGHT", "leader+mom", "core"),
        ("Leader", "NVDA", "NVIDIA", "Info Tech", 0.90, 2, 0.086, "Y", "HOLD", "REWEIGHT", "leader strength", ""),
        ("Leader", "AVGO", "Broadcom", "Info Tech", 0.86, 3, 0.060, "Y", "BUY_ADD", "REWEIGHT", "leader", ""),
        ("Mom63", "MRVL", "Marvell Technology", "Info Tech", 0.81, 1, 0.020, "Y", "BUY_NEW", "NEW_ENTRY", "mom63", "new"),
        ("Mom63", "MU", "Micron Technology", "Info Tech", 0.78, 2, 0.020, "N", "BUY_NEW", "NEW_ENTRY", "mom63", ""),
        ("LowVol", "JNJ", "Johnson & Johnson", "Health Care", 0.74, 1, 0.017, "Y", "HOLD", "REWEIGHT", "lowvol", ""),
        ("LowVol", "PG", "Procter & Gamble", "Consumer Staples", 0.71, 2, 0.017, "Y", "HOLD", "REWEIGHT", "lowvol", ""),
        ("LowVol", "KO", "Coca-Cola", "Consumer Staples", 0.68, 3, 0.017, "Y", "HOLD", "REWEIGHT", "lowvol", ""),
        ("Leader", "META", "Meta Platforms", "Comm Services", 0.66, 4, 0.060, "Y", "REWEIGHT", "REWEIGHT", "leader", ""),
        ("Mom63", "CRWD", "CrowdStrike", "Info Tech", 0.63, 3, 0.020, "N", "BUY_NEW", "NEW_ENTRY", "mom63", ""),
        ("LowVol", "WMT", "Walmart", "Consumer Staples", 0.60, 4, 0.017, "Y", "HOLD", "REWEIGHT", "lowvol", ""),
        ("Leader", "OLD1", "Legacy Exit Co", "Info Tech", 0.20, 99, 0.000, "Y", "SELL_EXIT", "EXIT_SIGNAL", "rank drop", "exit"),
    ]
    for i, row in enumerate(selected):
        r = 10 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(8)
            if c == 5 and isinstance(v, float):
                cell.number_format = "0.00"
            if c == 7 and isinstance(v, float):
                cell.number_format = "0.0%"
            if row[8] == "SELL_EXIT":
                cell.fill = ffill(SOFT_RED)
            elif row[8] == "BUY_NEW":
                cell.fill = ffill(SOFT_GREEN)
            elif r % 2 == 0:
                cell.fill = ffill(LIGHT)

    section(ws, 24, 1, "B. SCREEN PASS SAMPLE (선정 실패 포함)", 12)
    header_row(
        ws,
        25,
        [
            "code",
            "name",
            "sector",
            "universe",
            "leader",
            "vm",
            "div",
            "best_sleeve",
            "best_score",
            "rank",
            "selected",
            "reject_reason",
        ],
    )
    screen = [
        ("AAPL", "Apple", "Info Tech", "Y", "Y", "N", "N", "Leader", 0.92, 1, "Y", ""),
        ("NVDA", "NVIDIA", "Info Tech", "Y", "Y", "N", "Y", "Leader", 0.88, 2, "Y", ""),
        ("MRVL", "Marvell Technology", "Info Tech", "Y", "N", "N", "Y", "LowVol", 0.84, 1, "Y", ""),
        ("JNJ", "Johnson & Johnson", "Health Care", "Y", "N", "Y", "N", "Mom63", 0.71, 1, "Y", ""),
        ("LLY", "Eli Lilly", "Health Care", "Y", "Y", "Y", "N", "Leader", 0.69, 8, "N", "outside top N"),
        ("AMD", "AMD", "Info Tech", "Y", "N", "Y", "N", "Mom63", 0.58, 11, "N", "rank cutoff"),
        ("LLY", "Eli Lilly", "Health Care", "Y", "N", "N", "Y", "LowVol", 0.55, 9, "N", "rank cutoff"),
        ("WMT", "Walmart", "Consumer Staples", "Y", "N", "N", "N", "—", 0.33, "—", "N", "no sleeve pass"),
        ("CRWD", "CrowdStrike", "Info Tech", "Y", "N", "N", "N", "—", 0.42, "—", "N", "signal drop"),
        ("INTC", "LG", "Consumer Staples", "Y", "N", "Y", "N", "Mom63", 0.52, 14, "N", "score low"),
    ]
    for i, row in enumerate(screen):
        r = 26 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(8)
            if c == 11 and v == "Y":
                cell.fill = ffill(SOFT_GREEN)
            elif c == 11 and v == "N":
                cell.fill = ffill(SOFT_RED)
            elif r % 2 == 0:
                cell.fill = ffill(LIGHT)
    ws.cell(37, 1, "월말: Python export → 이 시트 import → selected=Y 를 Trade로 승격 → PM 승인").font = fnt(8, False, GRAY)
    finish_sheet(ws, "4C78A8")


def build_results(wb: Workbook):
    ws = wb.create_sheet("03_Results")
    set_widths(ws, [12, 12, 12, 12, 12, 12, 12, 12, 16, 14, 12, 12])
    banner(
        ws,
        "03  RESULTS  ·  PERFORMANCE & ATTRIBUTION",
        "Return · Active return · Monthly track · Sleeve contribution  |  as-of filled by ops",
        12,
    )
    for col, label, val, sub in [
        (1, "Long CAGR", "+44.8%", "research ref"),
        (2, "Sharpe", "1.60", "long strict"),
        (3, "Alpha", "+22.6%", "vs bench"),
        (4, "MaxDD", "-24.1%", "long sample"),
        (5, "MTD", "+2.1%", "live"),
        (6, "YTD", "+18.4%", "live"),
        (7, "Active YTD", "+5.2%", "vs SPY"),
        (8, "Hit M", "6/8", "monthly >0"),
    ]:
        kpi(ws, 4, col, label, val, sub)

    section(ws, 8, 1, "A. PERIOD SUMMARY", 8)
    header_row(ws, 9, ["period", "port", "bench", "active", "sharpe", "mdd", "turnover", "note"])
    periods = [
        ("MTD", 0.021, 0.015, 0.006, "—", -0.019, 0.00, "live"),
        ("QTD", 0.067, 0.041, 0.026, "—", -0.034, 0.18, "live"),
        ("YTD", 0.184, 0.132, 0.052, "—", -0.087, 0.41, "live"),
        ("1Y", 0.312, 0.198, 0.114, 1.55, -0.162, 0.39, "mixed"),
        ("Long Strict", 0.448, 0.218, 0.226, 1.60, -0.241, 0.39, "2019-07~"),
    ]
    for i, row in enumerate(periods):
        r = 10 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c in (2, 3, 4, 6, 7) and isinstance(v, float):
                cell.number_format = "0.0%"
            if r % 2 == 0:
                cell.fill = ffill(LIGHT)

    section(ws, 17, 1, "B. MONTHLY TRACK (SAMPLE)", 9)
    header_row(ws, 18, ["month", "port_ret", "bench_ret", "active", "turnover", "cost_bps", "mdd_eom", "n_names", "comment"])
    months = [
        ("2026-01", 0.042, 0.021, 0.021, 0.36, 24, -0.051, 23, "Leader strong"),
        ("2026-02", 0.018, 0.009, 0.009, 0.33, 22, -0.048, 24, "stable"),
        ("2026-03", -0.027, -0.019, -0.008, 0.41, 28, -0.071, 24, "risk-off"),
        ("2026-04", 0.055, 0.031, 0.024, 0.38, 26, -0.044, 25, "recovery"),
        ("2026-05", 0.029, 0.017, 0.012, 0.35, 23, -0.039, 24, ""),
        ("2026-06", 0.037, 0.022, 0.015, 0.40, 27, -0.042, 24, "rebalance ok"),
        ("2026-07*", 0.021, 0.015, 0.006, 0.00, 0, -0.019, 24, "MTD"),
    ]
    for i, row in enumerate(months):
        r = 19 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(8)
            if c in (2, 3, 4, 5, 7) and isinstance(v, float):
                cell.number_format = "0.0%"
            if c in (2, 4) and isinstance(v, float):
                cell.font = fnt(8, True, GREEN if v >= 0 else RED)

    section(ws, 28, 1, "C. SLEEVE CONTRIBUTION (YTD)", 5)
    header_row(ws, 29, ["sleeve", "avg_w", "ret", "contrib", "vs_target"])
    put_rows(
        ws,
        30,
        [
            ("Leader", 0.60, 0.221, 0.121, "inline"),
            ("Mom63", 0.20, 0.142, 0.036, "inline"),
            ("LowVol", 0.20, 0.168, 0.034, "inline"),
            ("Cash/Other", 0.03, 0.012, 0.000, "—"),
        ],
        pct_cols={2, 3, 4},
    )

    section(ws, 28, 7, "D. WINNERS / LOSERS (YTD)", 4)
    header_row(ws, 29, ["side", "code", "name", "contrib"], start=7)
    wl = [
        ("WIN", "NVDA", "NVIDIA", 0.028),
        ("WIN", "MRVL", "Marvell Technology", 0.019),
        ("WIN", "AAPL", "Apple", 0.017),
        ("LOSE", "CRWD", "CrowdStrike", -0.011),
        ("LOSE", "META", "Meta Platforms", -0.006),
    ]
    for i, row in enumerate(wl):
        for c, v in enumerate(row, 7):
            cell = ws.cell(30 + i, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c == 10 and isinstance(v, float):
                cell.number_format = "0.0%"
                cell.font = fnt(9, True, GREEN if v > 0 else RED)

    ws.cell(
        36,
        1,
        "NOTE: 장기 수치는 research long-strict 참고. 라이브와 연구 트랙 분리. 절대 CAGR 과신 금지.",
    ).font = fnt(8, False, GRAY)
    finish_sheet(ws, ACCENT)


def build_health(wb: Workbook):
    ws = wb.create_sheet("04_Health")
    set_widths(ws, [18, 14, 14, 10, 10, 12, 10, 24, 12, 12])
    banner(
        ws,
        "04  HEALTH  ·  DATA & SYSTEM CONTROL",
        "Freshness · Missingness · Pipeline gates · Rebalance blocker  |  Signal date filled by ops",
        10,
    )
    for col, label, val, sub, color in [
        (1, "Overall", "READY", "리밸 가능", GREEN),
        (2, "Data", "OK", "5 sources", NAVY),
        (3, "Pipeline", "OK", "signal→target", NAVY),
        (4, "Limits Pre", "OK", "caps ok", NAVY),
        (5, "Blockers", "0", "none", NAVY),
        (6, "Last Import", "", "signal asof", NAVY),
        (7, "Next Signal", "07-31", "calendar", NAVY),
        (8, "Owner", "PM", "sign-off", NAVY),
    ]:
        kpi(ws, 4, col, label, val, sub, color)

    section(ws, 8, 1, "A. DATA FRESHNESS", 9)
    header_row(ws, 9, ["source", "last_date", "expected", "lag_days", "rows", "missing_%", "status", "action", "owner"])
    data_rows = [
        ("prices", "", "", 0, 185432, 0.002, "OK", "—", "sys"),
        ("spy_index", "", "", 0, 92410, 0.011, "OK", "—", "sys"),
        ("valuation", "", "", "", "", "", "", "-", "sys"),
        ("universe_meta", "", "", 0, 890, 0.000, "OK", "—", "sys"),
        ("spy_index", "", "", 0, 2850, 0.000, "OK", "—", "sys"),
    ]
    for i, row in enumerate(data_rows):
        r = 10 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c == 6 and isinstance(v, float):
                cell.number_format = "0.0%"
            if c == 7:
                if v == "OK":
                    cell.fill = ffill(SOFT_GREEN)
                    cell.font = fnt(9, True, GREEN)
                elif v == "WARN":
                    cell.fill = ffill(SOFT_AMBER)
                    cell.font = fnt(9, True, ACCENT)

    section(ws, 17, 1, "B. SYSTEM / PROCESS CHECKS", 4)
    header_row(ws, 18, ["check", "status", "detail", "blocker?"])
    sys_checks = [
        ("signal_engine_run", "OK", "monthly job success", "N"),
        ("target_sum_is_1", "OK", "sum(final_w)=1.000", "N"),
        ("name_cap_applied", "OK", "max name 9.8% < 15%", "N"),
        ("sector_cap_applied", "OK", "max sector 28.4% < 40%", "N"),
        ("code_format_6digit", "OK", "no leading-zero loss", "N"),
        ("prev_positions_loaded", "OK", "24 names matched", "N"),
        ("orders_built", "OK", "sell-first priority", "N"),
        ("python_excel_import", "OK", "18:20 import complete", "N"),
        ("no_manual_override", "OK", "exceptions empty", "N"),
        ("calendar_status", "READY", "approved pending trade", "N"),
    ]
    for i, row in enumerate(sys_checks):
        r = 19 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c == 2 and v in ("OK", "READY"):
                cell.fill = ffill(SOFT_GREEN if v == "OK" else SOFT_BLUE)

    section(ws, 17, 6, "C. ALERTS", 4)
    header_row(ws, 18, ["time", "level", "message", "resolved"], start=6)
    alerts = [
        ("", "YELLOW", "valuation lag 2d", "Y"),
        ("", "INFO", "target package ready", "Y"),
    ]
    for i, row in enumerate(alerts):
        for c, v in enumerate(row, 6):
            cell = ws.cell(19 + i, c, v)
            cell.border = thin
            cell.font = fnt(8)
            if c == 7 and v == "YELLOW":
                cell.fill = ffill(SOFT_AMBER)

    ws.cell(31, 1, "GATE RULE").font = fnt(10, True, NAVY)
    ws.cell(32, 1, "RED (data FAIL / invalid target / code error) → 리밸 금지 (DELAYED)").font = fnt(9, True, RED)
    ws.cell(33, 1, "YELLOW → 진행 가능, 로그 필수").font = fnt(9, True, ACCENT)
    ws.cell(34, 1, "ALL OK/READY → Trade 시트 승인 가능").font = fnt(9, True, GREEN)
    finish_sheet(ws, "B279A2")


def build_trade(wb: Workbook):
    ws = wb.create_sheet("05_Trade")
    set_widths(ws, [6, 10, 12, 8, 11, 10, 10, 10, 8, 12, 10, 10, 10, 12, 10])
    banner(
        ws,
        "05  TRADE  ·  TARGET → ORDER → FILL",
        "Sell-first · Next-open protocol · Maker-checker  |  Signal/trade dates filled by ops",
        15,
    )
    for col, label, val, sub in [
        (1, "Trade Date", "", "D+1 open"),
        (2, "Signal Date", "", "month-end"),
        (3, "Sell Notional", "86.4M", "first"),
        (4, "Buy Notional", "84.1M", "after sells"),
        (5, "Turnover", "0.18", "est."),
        (6, "Fill Rate", "100%", "sample"),
        (7, "Approved", "Y", "PM"),
        (8, "Status", "DONE", "synced"),
    ]:
        kpi(ws, 4, col, label, val, sub, GREEN if col in (7, 8) else NAVY)

    section(ws, 8, 1, "A. ORDER TICKET (매도 우선)", 15)
    header_row(
        ws,
        9,
        [
            "prio",
            "code",
            "name",
            "side",
            "action",
            "current_w",
            "target_w",
            "delta_w",
            "qty",
            "order_type",
            "status",
            "fill_px",
            "fill_qty",
            "reason",
            "approved",
        ],
    )
    orders = [
        (1, "CRWD", "CrowdStrike", "SELL", "SELL_EXIT", 0.008, 0.000, -0.008, 80, "MARKET_OPEN", "FILLED", 127500, 80, "EXIT_SIGNAL", "Y"),
        (2, "META", "Meta Platforms", "SELL", "SELL_TRIM", 0.018, 0.016, -0.002, 55, "VWAP", "FILLED", 45200, 55, "REWEIGHT", "Y"),
        (3, "AAPL", "Apple", "BUY", "REWEIGHT", 0.075, 0.078, 0.003, 40, "VWAP", "FILLED", 78100, 40, "REWEIGHT", "Y"),
        (4, "AVGO", "Broadcom", "BUY", "BUY_ADD", 0.071, 0.068, -0.003, 0, "—", "SKIP", "-", 0, "REWEIGHT", "Y"),
        (5, "AMAT", "Applied Materials", "BUY", "BUY_NEW", 0.000, 0.024, 0.024, 950, "MARKET_OPEN", "FILLED", 30900, 950, "NEW_ENTRY", "Y"),
        (6, "MRVL", "Marvell Technology", "BUY", "BUY_ADD", 0.061, 0.058, -0.003, 0, "—", "SKIP", "-", 0, "REWEIGHT", "Y"),
        (7, "KO", "Coca-Cola", "BUY", "REWEIGHT", 0.028, 0.030, 0.002, 15, "LIMIT", "FILLED", 160500, 15, "REWEIGHT", "Y"),
    ]
    for i, row in enumerate(orders):
        r = 10 + i
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            cell.border = thin
            cell.font = fnt(8)
            if c in (6, 7, 8) and isinstance(v, float):
                cell.number_format = "0.0%"
            if c == 4 and v == "SELL":
                cell.fill = ffill(SOFT_RED)
            if c == 4 and v == "BUY":
                cell.fill = ffill(SOFT_GREEN)
            if c == 11 and v == "FILLED":
                cell.fill = ffill(SOFT_GREEN)
                cell.font = fnt(8, True, GREEN)
            if c == 11 and v == "SKIP":
                cell.fill = ffill(LOCKED)
            if c == 15:
                cell.fill = ffill(YELLOW)
                cell.font = fnt(8, True, INPUT_BLUE)

    ws.cell(18, 1, "EXEC RULES: 1) SELL first  2) BUY later  3) NEXT_OPEN/VWAP  4) no discretionary adds  5) same-day residual handling").font = fnt(
        8, False, GRAY
    )

    section(ws, 20, 1, "B. CASH IMPACT", 2)
    header_row(ws, 21, ["item", "value"])
    cash = [
        ("gross_sell_cash_in", "10,200,000"),
        ("gross_buy_cash_out", "-38,835,000"),
        ("fees_taxes", "-182,000"),
        ("net_cash_change", "-28,817,000"),
        ("post_trade_cash_w", "2.8%"),
        ("holdings_sync", ""),
    ]
    put_rows(ws, 22, cash)

    section(ws, 20, 4, "C. MAKER-CHECKER", 4)
    header_row(ws, 21, ["role", "name", "sign", "time"], start=4)
    mc = [
        ("Maker (prepare)", "Analyst/PM", "Y", ""),
        ("Checker (approve)", "PM", "Y", ""),
        ("Trader (execute)", "PM", "Y", ""),
        ("Post-trade review", "PM", "Y", ""),
    ]
    for i, row in enumerate(mc):
        for c, v in enumerate(row, 4):
            cell = ws.cell(22 + i, c, v)
            cell.border = thin
            cell.font = fnt(9)
            if c == 6:
                cell.fill = ffill(YELLOW)
                cell.font = fnt(9, True, INPUT_BLUE)

    section(ws, 28, 1, "D. POST-TRADE CHECK", 4)
    for i, t in enumerate(
        [
            "[Y] Fills posted to Holdings",
            "[Y] NAV/Cash reconciled",
            "[Y] No orphan orders",
            "[Y] Log updated in 00_Config_Log",
            "[Y] Snapshot path ready (/snapshots/YYYY-MM/)",
        ]
    ):
        ws.cell(29 + i, 1, t).font = fnt(9, True, GREEN)
    finish_sheet(ws, "E45756")


def main():
    wb = Workbook()
    build_config(wb)
    build_portfolio(wb)
    build_screen(wb)
    build_results(wb)
    build_health(wb)
    build_trade(wb)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print("WROTE", OUT)
    print("sheets", wb.sheetnames)
    print("size_kb", round(OUT.stat().st_size / 1024, 1))


if __name__ == "__main__":
    main()
