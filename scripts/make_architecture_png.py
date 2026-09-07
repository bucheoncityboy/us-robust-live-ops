# -*- coding: utf-8 -*-
"""Generate docs/architecture.png for the README (Korean, Malgun Gothic)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

_FP = font_manager.FontProperties(fname=r"C:/Windows/Fonts/malgun.ttf")

NAVY = "#0F2744"; BLUE = "#1F4E79"
ACCENT = "#C45C26"
GREEN = "#2E7D32"
GRAY = "#595959"

def box(x, y, w, h, fc, ec, title, sub=None, tc="#FFFFFF", fs=11.0, subfs=8.8):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06,rounding_size=0.15",
                       fc=fc, ec=ec, lw=1.5, mutation_aspect=1, zorder=2)
    ax.add_patch(p)
    cx = x + w / 2
    if sub:
        ax.text(cx, y + h * 0.63, title, ha="center", va="center",
                fontproperties=_FP, fontsize=fs, color=tc, fontweight="bold", linespacing=1.25, zorder=3)
        ax.text(cx, y + h * 0.26, sub, ha="center", va="center",
                fontproperties=_FP, fontsize=subfs, color="#EAF1F8", linespacing=1.4, zorder=3)
    else:
        ax.text(cx, y + h / 2, title, ha="center", va="center",
                fontproperties=_FP, fontsize=fs, color=tc, fontweight="bold", linespacing=1.3, zorder=3)

def arrow(x1, y1, x2, y2, color=BLUE, lw=2.0, rad=0.0, ls="-"):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=16,
                        color=color, lw=lw, linestyle=ls,
                        connectionstyle=f"arc3,rad={rad}", zorder=4)
    ax.add_patch(a)

def cap(x, y, text, fs=11.5, color=GRAY):
    ax.text(x, y, text, ha="left", va="center", fontproperties=_FP, fontsize=fs, color=color)

fig, ax = plt.subplots(figsize=(13.0, 7.9), dpi=200)
ax.set_xlim(0, 13.0); ax.set_ylim(0, 7.9); ax.axis("off")

# ---------------- zone captions ----------------
cap(0.25, 7.62, "입력 · 데이터", fs=12, color="#333333")
cap(0.25, 5.90, "Python — Single Source of Truth", fs=12.5, color=NAVY)
cap(0.25, 2.02, "소비자 UI (읽기 전용 · 계산 없음)", fs=12, color="#333333")

# ---------------- top inputs ----------------
box(0.30, 6.30, 3.50, 1.10, "#F2F2F2", "#A6A6A6", "data/us parquet", tc=NAVY,
    sub="yfinance 패널 · refresh로 생성", subfs=8.6, )
box(4.00, 6.30, 4.10, 1.10, "#FBE5D6", ACCENT, "Toss 브로커 잔고", tc=NAVY,
    sub="포지션·현금 조회 (읽기 전용)", subfs=8.6)
box(8.40, 6.30, 4.30, 1.10, "#E2EFDA", GREEN, "SPY 지수 (벤치마크)", tc=NAVY,
    sub="주간 앵커 종가 대비 수익률", subfs=8.6)

# ---------------- python zone frame ----------------
zf = FancyBboxPatch((0.25, 2.45), 12.50, 3.30, boxstyle="round,pad=0.08,rounding_size=0.15",
                    fc="#F7F9FC", ec=NAVY, lw=1.8, linestyle=(0, (6, 3)), zorder=1)
ax.add_patch(zf)
ax.text(0.48, 5.52, "ops/  (운용 엔진 14개 모듈)", ha="left", va="center",
        fontproperties=_FP, fontsize=10.0, color=BLUE, fontweight="bold", zorder=3)

# row A
box(0.55, 4.20, 4.60, 1.05, NAVY, NAVY, "정책 · 팩터", sub="ops_us_policy (60/20/20 동결)\nus_factor_research (신호·유니버스)")
box(5.45, 4.20, 4.80, 1.05, BLUE, BLUE, "월간 운용", sub="ops_monthly_run\n월말 종가 신호 → 목표·주문 CSV (원천)")
box(10.55, 4.20, 2.15, 1.05, "#375623", GREEN, "안전 가드", sub="ops_live_safety\n매니페스트·해시\n월말 완료 확인")

# row B
box(0.55, 2.80, 6.20, 1.00, "#8A2E2E", "#8A2E2E", "실행", sub="ops_execute_gates → ops_execute\nNORMAL/L1/L2 위험모드 게이트 → 실주문")
box(7.05, 2.80, 5.70, 1.00, "#1A5276", BLUE, "주간 원장", sub="ops_daily (python ops.py weekly)\n주간 앵커 NAV + SPY → daily_nav.csv")

# ---- arrows inside python ----
# inputs into python
arrow(1.50, 6.30, 2.20, 5.30, rad=-0.05)     # parquet -> policy (features)
arrow(2.05, 6.30, 2.90, 5.30, rad=-0.12)     # parquet -> policy (prices)
arrow(5.80, 6.30, 5.80, 5.30)               # toss book -> monthly
arrow(10.55, 6.30, 10.55, 3.82)              # spy -> weekly (direct down)

# policy/factor -> monthly
arrow(4.30, 4.20, 5.45, 4.40, rad=-0.08)
# monthly -> safety (package hash/guard verification)
arrow(10.25, 4.40, 10.55, 4.45)
# monthly -> execute (down)
arrow(7.30, 4.20, 6.60, 3.82, rad=0.15)
# monthly -> weekly (down-right)
arrow(9.60, 4.20, 9.60, 3.82)

# ---------------- bottom UI zone ----------------
box(0.55, 0.55, 6.00, 1.30, NAVY, NAVY, "엑셀 원장 워크북", sub="openpyxl · 6시트 (00_Config~05_Trade + 06_Weekly_Trend)\n주문 티켓은 CLI_REQUIRED · 수식 재계산 금지")
box(6.85, 0.55, 5.90, 1.30, "#4A4A4A", "#666666", "Notion 대시보드", sub="scripts/make_weekly_notion_assets\n주간 수익률 조회용 (읽기 전용)")

# python -> UI
arrow(2.80, 2.80, 3.20, 1.88)          # execute -> excel (order/approval mirror)
arrow(1.00, 2.80, 1.00, 1.88)          # monthly/execute -> excel (left side)
arrow(8.80, 2.80, 8.80, 1.88)          # weekly -> notion (주간 수익률)

# ---------------- legend / footnote ----------------
ax.text(0.25, 0.12, "실선: 데이터·제어 흐름    점선 프레임: Python 계산 영역 (CSV·패키지가 유일한 원천, 엑셀/Notion은 그리는 화면일 뿐)",
        ha="left", va="center", fontproperties=_FP, fontsize=9.0, color="#666666")

out = r"C:/Users/PC/Desktop/AI/us-robust-live-ops/docs/architecture.png"
fig.savefig(out, bbox_inches="tight", pad_inches=0.12, facecolor="white")
print("saved", out)
