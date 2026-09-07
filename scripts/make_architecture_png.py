# -*- coding: utf-8 -*-
"""Generate docs/architecture.png for the README.

Layout is measured against the Malgun Gothic font metrics at render time:
every label is anchored at a fixed offset inside its box and then verified
with shapely (text bbox must stay inside its box). The script exits 1 if any
text pokes out, so an accidental overlap fails the build instead of shipping.
"""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager
from shapely.geometry import box as sbox

_FP = font_manager.FontProperties(fname=r"C:/Windows/Fonts/malgun.ttf")

NAVY = "#0F2744"
BLUE = "#1F4E79"
RED = "#8A2E2E"
DGREEN = "#375623"
GREEN = "#2E7D32"
DARK = "#4A4A4A"

TITLE_FS = 10.8
SUB_FS = 8.4
TITLE_LS = 1.22
SUB_LS = 1.32
# text line heights in data units (1 unit == 1 inch here, axes 13 x 7.9)
LH = lambda fs, ls: (fs * ls) / 72.0
TITLE_H = LH(TITLE_FS, TITLE_LS)
SUB_LH = LH(SUB_FS, SUB_LS)
PAD_X = 0.16
PAD_TOP = 0.12
PAD_SUB_TITLE = 0.045


def _text_w(s, fs, bold=False, renderer=None):
    t = fig.text(0, 0, s, fontproperties=_FP, fontsize=fs,
                 fontweight="bold" if bold else "normal")
    bb = t.get_window_extent(renderer=renderer)
    t.remove()
    return bb.width / 100.0  # px / dpi(100) == inches == data units


def add_box(ax, x, y, w, h, fc, ec, title, sub_lines, tc="#FFFFFF",
            renderer=None):
    """Draw box + anchored title + sub block; return (box_rect, [text_rects])."""
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.14",
                       fc=fc, ec=ec, lw=1.4, mutation_aspect=1, zorder=2)
    ax.add_patch(p)
    rects = []
    cx = x + w / 2
    # title anchored near top
    ty = y + h - PAD_TOP - TITLE_H / 2
    ax.text(cx, ty, title, ha="center", va="center", fontproperties=_FP,
            fontsize=TITLE_FS, color=tc, fontweight="bold", linespacing=TITLE_LS,
            zorder=3)
    tb = sbox(x, ty - TITLE_H / 2, x + w, ty + TITLE_H / 2)
    rects.append(tb)
    # sub lines below title, left-anchored block centered overall
    n = len(sub_lines)
    block_h = n * SUB_LH + (n - 1) * 0.03
    top = ty - TITLE_H / 2 - PAD_SUB_TITLE - block_h
    sub_top = top + block_h
    sub_cx = x + w / 2
    for i, ln in enumerate(sub_lines):
        ly = sub_top - (i + 0.5) * (block_h / n)
        ax.text(sub_cx, ly, ln, ha="center", va="center", fontproperties=_FP,
                fontsize=SUB_FS, color="#EAF1F8", linespacing=SUB_LS, zorder=3)
    rects.append(sbox(x, y, x + w, y + h))
    return sbox(x, y, x + w, y + h), rects


def arrow(ax, x1, y1, x2, y2, color=BLUE, lw=1.8, rad=0.0):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=15,
                        color=color, lw=lw, connectionstyle=f"arc3,rad={rad}",
                        zorder=1)
    ax.add_patch(a)


fig = plt.figure(figsize=(13.0, 7.9), dpi=200)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, 13.0)
ax.set_ylim(0, 7.9)
ax.axis("off")

all_boxes = {}   # name -> (rect, [sub text rects])
all_texts = []   # (text, rect)

def put(name, x, y, w, h, fc, ec, title, sub_lines, tc="#FFFFFF"):
    rect, rects = add_box(ax, x, y, w, h, fc, ec, title, sub_lines, tc=tc)
    all_boxes[name] = (rect, rects)
    all_texts.append((title, rect))

fig.canvas.draw()
renderer = fig.canvas.get_renderer()

# ---------------- zones / captions ----------------
ax.text(0.25, 7.70, "입력 · 데이터", ha="left", va="center", fontproperties=_FP,
        fontsize=12.0, color="#333333", zorder=3)
ax.text(0.25, 6.02, "Python - Single Source of Truth", ha="left", va="center",
        fontproperties=_FP, fontsize=12.5, color=NAVY, fontweight="bold", zorder=3)
ax.text(0.25, 2.12, "소비자 UI (읽기 전용 · 계산 없음)", ha="left", va="center",
        fontproperties=_FP, fontsize=12.0, color="#333333", zorder=3)

# ---------------- top: inputs ----------------
put("parquet", 0.30, 6.55, 3.50, 1.02, "#F2F2F2", "#A6A6A6", "data/us parquet",
    ["yfinance 패널", "refresh로 생성"], tc=NAVY)
put("toss", 4.00, 6.55, 4.10, 1.02, "#FBE5D6", "#C45C26", "Toss 브로커 잔고",
    ["포지션 · 현금 조회 (읽기 전용)"], tc=NAVY)
put("spy", 8.40, 6.55, 4.30, 1.02, "#E2EFDA", GREEN, "SPY 지수 (벤치마크)",
    ["주간 앵커 종가 대비 수익률"], tc=NAVY)

# ---------------- python zone frame ----------------
zf = FancyBboxPatch((0.25, 2.55), 12.50, 3.20, boxstyle="round,pad=0.06,rounding_size=0.15",
                    fc="#F7F9FC", ec=NAVY, lw=1.8, linestyle=(0, (6, 3)), zorder=0)
ax.add_patch(zf)
ax.text(0.48, 5.62, "ops/  (운용 엔진)", ha="left", va="center", fontproperties=_FP,
        fontsize=9.6, color=BLUE, fontweight="bold", zorder=3)

# row A
put("policy", 0.55, 4.35, 4.60, 1.02, NAVY, NAVY, "정책 · 팩터",
    ["ops_us_policy (60/20/20 동결)", "us_factor_research (신호·유니버스)"])
put("monthly", 5.45, 4.35, 4.90, 1.02, BLUE, BLUE, "월간 운용",
    ["ops_monthly_run", "월말 종가 신호 → 목표·주문 CSV"])
put("safety", 10.65, 4.35, 2.10, 1.02, DGREEN, GREEN, "안전 가드",
    ["ops_live_safety", "매니페스트 · 해시"])

# row B
put("execute", 0.55, 2.90, 6.40, 1.00, RED, RED, "실행",
    ["ops_execute_gates → ops_execute", "NORMAL / L1 / L2 게이트 → 실주문"])
put("weekly", 7.25, 2.90, 5.50, 1.00, "#1A5276", BLUE, "주간 원장",
    ["ops_daily (python ops.py weekly)", "주간 앵커 NAV + SPY → daily_nav.csv"])

# ---------------- bottom UI ----------------
put("excel", 0.55, 0.60, 6.00, 1.22, NAVY, NAVY, "엑셀 원장 워크북",
    ["openpyxl 6시트 + 06_Weekly_Trend", "주문 티켓 CLI_REQUIRED · 수식 재계산 금지"])
put("notion", 6.85, 0.60, 5.90, 1.22, DARK, "#666666", "Notion 대시보드",
    ["scripts/make_weekly_notion_assets", "주간 수익률 조회용 (읽기 전용)"])

# ---------------- arrows ----------------
# inputs -> python
arrow(ax, 1.50, 6.55, 2.30, 5.40, rad=-0.08)   # parquet -> policy
arrow(ax, 2.30, 6.55, 3.00, 5.40, rad=-0.10)   # parquet -> policy
arrow(ax, 5.90, 6.55, 5.90, 5.40)              # toss -> monthly
arrow(ax, 10.55, 6.55, 10.55, 3.90)            # spy -> weekly
# inside python
arrow(ax, 4.30, 4.35, 5.45, 4.50, rad=-0.06)   # policy -> monthly
arrow(ax, 10.35, 4.60, 10.65, 4.60)            # monthly -> safety
arrow(ax, 7.40, 4.35, 6.90, 3.92, rad=0.18)    # monthly -> execute
arrow(ax, 9.90, 4.35, 9.90, 3.92)              # monthly -> weekly
# python -> UI
arrow(ax, 2.60, 2.90, 3.10, 1.84)              # execute -> excel
arrow(ax, 9.20, 2.90, 9.20, 1.84)              # weekly -> notion

# ---------------- legend ----------------
ax.text(0.25, 0.14, "실선: 데이터·제어 흐름   점선 프레임: Python 계산 영역 (CSV·패키지가 유일한 원천)",
        ha="left", va="center", fontproperties=_FP, fontsize=8.8, color="#666666", zorder=3)

# ---------------- verification: every text inside its box ----------------
# We re-measure after final layout using actual renderer bboxes.
fig.canvas.draw()
renderer = fig.canvas.get_renderer()
inv = ax.transData.inverted()
problems = []
for t in ax.texts:
    bb = t.get_window_extent(renderer=renderer)
    (x0, y0) = inv.transform((bb.x0, bb.y0))
    (x1, y1) = inv.transform((bb.x1, bb.y1))
    tb = sbox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    cx, cy = t.get_position()
    host = None
    best = 0.0
    for name, (rect, _) in all_boxes.items():
        inter = tb.intersection(rect).area
        if inter > best:
            best = inter
            host = rect
    # require the text to be (mostly) inside one box; zone captions overlap nothing
    if host is not None and best > 0.0 and not host.contains(tb):
        problems.append((t.get_text()[:26], "??", tuple(round(v, 2) for v in tb.bounds)))
    # host is None or tiny overlap => caption/legend: check frame strip + any box
    if host is None or best == 0.0:
        fb = sbox(0.25, 5.72, 12.75, 5.80)
        for _, (rect, _) in all_boxes.items():
            if not tb.intersection(rect).is_empty and not rect.contains(tb):
                problems.append((t.get_text()[:26], "box-collide", tuple(round(v, 2) for v in tb.bounds)))
        if not tb.intersection(fb).is_empty:
            problems.append((t.get_text()[:26], "frame-top", tuple(round(v, 2) for v in tb.bounds)))

out = r"C:/Users/PC/Desktop/AI/us-robust-live-ops/docs/architecture.png"
fig.savefig(out, bbox_inches="tight", pad_inches=0.10, facecolor="white")
print("saved", out)
if problems:
    print("LAYOUT OVERFLOW DETECTED:")
    for p in problems:
        print("  ", p)
    sys.exit(1)
print("layout OK: all text inside boxes")
