"""미국 시장 강건 전략 — 편향 제거 · 과적합 통제 엄격 백테스트 연구 보고서 (2024~2026) PDF.

Reads results/strict_report/* (produced by research/strict_edge_report.py),
builds charts (matplotlib, Malgun Gothic) and renders the Korean PDF (reportlab).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import matplotlib.dates as mdates

_fp = Path(r"C:\Windows\Fonts\malgun.ttf")
if _fp.exists():
    font_manager.fontManager.addfont(str(_fp))
    plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "strict_report"
CHART = RES / "charts"
OUT = RES / "미국시장_강건전략_편향제거_엄격백테스트_보고서_2024_2026.pdf"

NAVY = colors.HexColor("#0F2744")
BLUE = colors.HexColor("#1F4E79")
ACCENT = colors.HexColor("#C45C26")
LIGHT = colors.HexColor("#F4F7FB")
GRID = colors.HexColor("#D0D7E2")
GRAY = colors.HexColor("#5B6573")
GREEN = colors.HexColor("#1B7F4C")
RED = colors.HexColor("#B3392B")


def fonts():
    reg = Path(r"C:\Windows\Fonts\malgun.ttf")
    bold = Path(r"C:\Windows\Fonts\malgunbd.ttf")
    if not reg.exists():
        reg = Path(r"C:\Windows\Fonts\malgunsl.ttf")
    pdfmetrics.registerFont(TTFont("KR", str(reg)))
    if bold.exists():
        pdfmetrics.registerFont(TTFont("KR-Bold", str(bold)))
        return "KR", "KR-Bold"
    return "KR", "KR"


def styles(font, fb):
    s = {}
    s["cover_title"] = ParagraphStyle("ct", fontName=fb, fontSize=17, leading=23, textColor=colors.white)
    s["cover_sub"] = ParagraphStyle("cs", fontName=font, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#D9E2F0"))
    s["h1"] = ParagraphStyle("h1", fontName=fb, fontSize=12.2, leading=16, textColor=NAVY, spaceBefore=2, spaceAfter=3)
    s["h2"] = ParagraphStyle("h2", fontName=fb, fontSize=10, leading=13, textColor=BLUE, spaceBefore=3, spaceAfter=2)
    s["body"] = ParagraphStyle("body", fontName=font, fontSize=8.6, leading=12.2, textColor=colors.HexColor("#1F2933"))
    s["quote"] = ParagraphStyle(
        "q", fontName=font, fontSize=8.8, leading=12.5, textColor=colors.HexColor("#111827"),
        backColor=LIGHT, borderPadding=5,
    )
    s["th"] = ParagraphStyle("th", fontName=fb, fontSize=7.2, leading=9.4, textColor=colors.white)
    s["td"] = ParagraphStyle("td", fontName=font, fontSize=7.2, leading=9.6, textColor=colors.HexColor("#1F2933"), alignment=1)
    s["td_left"] = ParagraphStyle("tdl", fontName=font, fontSize=7.2, leading=9.6, textColor=colors.HexColor("#1F2933"), alignment=0)
    s["kpi"] = ParagraphStyle("kpi", fontName=font, fontSize=7.0, leading=9.2, textColor=GRAY, alignment=1)
    s["kpi_val"] = ParagraphStyle("kpiv", fontName=fb, fontSize=10.2, leading=12.5, textColor=NAVY, alignment=1)
    s["caption"] = ParagraphStyle("cap", fontName=font, fontSize=7.0, leading=9.2, textColor=GRAY, alignment=1)
    s["tdx"] = ParagraphStyle("tdx", fontName=font, fontSize=6.3, leading=8.4, textColor=colors.HexColor("#1F2933"), alignment=0)
    s["small"] = ParagraphStyle("sm", fontName=font, fontSize=7.0, leading=9.5, textColor=GRAY)
    s["warn"] = ParagraphStyle("warn", fontName=font, fontSize=8.0, leading=11.2, textColor=ACCENT)
    return s


def P(text, st):
    t = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
        .replace("&lt;br/&gt;", "<br/>")
    )
    return Paragraph(t, st)


def pct(x, d=1):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "-"
    return f"{float(x) * 100:.{d}f}%"


def num(x, d=2):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "-"
    return f"{float(x):.{d}f}"


def section(title, st):
    t = Table([[P(title, st["h1"])]], colWidths=[182 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 1.5, NAVY),
    ]))
    return t


def table(headers, rows, st, widths, left0=True, highlight_rows=None, cell_map=None):
    head = [P(h, st["th"]) for h in headers]
    body = []
    for r in rows:
        line = []
        for i, c in enumerate(r):
            style = st["td_left"] if (left0 and i == 0) else st["td"]
            if cell_map and i in cell_map:
                style = cell_map[i]
            line.append(P(str(c), style))
        body.append(line)
    data = [head] + body
    t = Table(data, colWidths=widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.28, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    for (ri, _) in highlight_rows or []:
        cmds.append(("BACKGROUND", (0, ri), (-1, ri), colors.HexColor("#FBE9E7")))
        cmds.append(("TEXTCOLOR", (0, ri), (-1, ri), RED))
    t.setStyle(TableStyle(cmds))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(13.5 * mm, 10 * mm, A4[0] - 13.5 * mm, 10 * mm)
    canvas.setFont("KR", 6.5)
    canvas.setFillColor(GRAY)
    canvas.drawString(13.5 * mm, 6.5 * mm, "미국 시장 강건 퀀트 전략 — 편향 제거 · 엄격 백테스트 연구 보고서 (2026-08-15)")
    canvas.drawRightString(A4[0] - 13.5 * mm, 6.5 * mm, f"p. {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def make_charts(m: Dict, eq: pd.DataFrame, mt: pd.DataFrame, grid: pd.DataFrame) -> Dict[str, Path]:
    CHART.mkdir(parents=True, exist_ok=True)
    NAVY_C, BLUE_C, AMBER_C, GREEN_C, RED_C = "#0F2744", "#1F4E79", "#C45C26", "#1B7F4C", "#B3392B"
    out: Dict[str, Path] = {}

    # c1 equity
    fig, ax = plt.subplots(figsize=(7.6, 3.1), dpi=170)
    for col, c, lw in (("STRAT_PIT", NAVY_C, 1.9), ("EW_PIT", GREEN_C, 1.1), ("SPY", AMBER_C, 1.1)):
        s = eq[col] / eq[col].iloc[0]
        ax.plot(s.index, s.values, color=c, lw=lw, label={"STRAT_PIT": "전략 (60/20/20)", "EW_PIT": "EW 동일유니버스", "SPY": "SPY"}[col])
    ax.axvline(pd.Timestamp("2026-06-30"), color=RED_C, lw=0.9, ls="--", alpha=0.8)
    ax.annotate("2026-07 반도체 급락", xy=(pd.Timestamp("2026-06-20"), eq["STRAT_PIT"].max() / eq["STRAT_PIT"].iloc[0] * 1.02),
                fontsize=7, color=RED_C, ha="right")
    ax.set_ylabel("누적배수 (시점 1.0)")
    ax.legend(fontsize=7.5, loc="upper left", frameon=False)
    ax.grid(alpha=0.25, lw=0.5)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    p = CHART / "c1_equity.png"
    fig.savefig(p); plt.close(fig); out["equity"] = p

    # c2 monthly bars
    fig, ax = plt.subplots(figsize=(7.6, 3.0), dpi=170)
    x = np.arange(len(mt))
    w = 0.38
    ax.bar(x - w / 2, mt["strat_ret"], width=w, color=NAVY_C, label="전략")
    ax.bar(x + w / 2, mt["spy_ret"], width=w, color=AMBER_C, label="SPY")
    ax.axhline(0, color="0.4", lw=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels([m.replace("2024-", "'24-").replace("2025-", "'25-").replace("2026-", "'26-") for m in mt["month"]],
                       fontsize=5.6, rotation=60)
    ax.legend(fontsize=7, ncol=2, frameon=False)
    ax.grid(alpha=0.2, lw=0.4, axis="y")
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    p = CHART / "c2_monthly.png"
    fig.savefig(p); plt.close(fig); out["monthly"] = p

    # c3 regime cells
    cells = m["regime_cells"]
    names = list(cells.keys())
    sann = [cells[k]["strat_ann"] * 100 for k in names]
    bann = [cells[k]["spy_ann"] * 100 for k in names]
    fig, ax = plt.subplots(figsize=(7.6, 2.9), dpi=170)
    x = np.arange(len(names))
    w = 0.36
    ax.bar(x - w / 2, sann, width=w, color=NAVY_C, label="전략 (연환산)")
    ax.bar(x + w / 2, bann, width=w, color=AMBER_C, label="SPY (연환산)")
    for i, k in enumerate(names):
        ax.text(i - w / 2, sann[i] + 3, f"n={cells[k]['n_months']}", ha="center", fontsize=6.5, color=NAVY_C)
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=8)
    ax.axhline(0, color="0.4", lw=0.7)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.grid(alpha=0.2, lw=0.4, axis="y")
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    p = CHART / "c3_regime.png"
    fig.savefig(p); plt.close(fig); out["regime"] = p

    # c4 correlations (two heatmaps)
    f = m["factor"]
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 2.9), dpi=170)
    mat1 = pd.DataFrame(f["sleeve_return_corr_pearson"]).reindex(index=["leader", "mom63", "lowvol"], columns=["leader", "mom63", "lowvol"])
    lab = {"leader": "핵심모멘텀", "mom63": "중기모멘텀", "lowvol": "저변동성"}
    im = axes[0].imshow(mat1.values, cmap="RdBu_r", vmin=-1, vmax=1)
    axes[0].set_xticks(range(3)); axes[0].set_yticks(range(3))
    axes[0].set_xticklabels([lab[c] for c in mat1.columns], fontsize=7)
    axes[0].set_yticklabels([lab[c] for c in mat1.index], fontsize=7)
    for i in range(3):
        for j in range(3):
            axes[0].text(j, i, f"{mat1.values[i, j]:.2f}", ha="center", va="center", fontsize=7.5)
    axes[0].set_title("슬리브 월수익률 상관 (Pearson)", fontsize=8.5)
    sc = f["score_rank_corr"]
    pairs = list(sc.keys())
    vals = [sc[k]["mean"] for k in pairs]
    im2 = axes[1].imshow(np.array(vals).reshape(-1, 1), cmap="RdBu_r", vmin=-1, vmax=1)
    axes[1].set_yticks(range(len(pairs)))
    axes[1].set_yticklabels([k.replace(" vs ", " ↔ ") for k in pairs], fontsize=6.6)
    axes[1].set_xticks([])
    for i, v in enumerate(vals):
        axes[1].text(0, i, f"{v:.2f}", ha="center", va="center", fontsize=8)
    axes[1].set_title("팩터 스코어 랭크상관 (월평균)", fontsize=8.5)
    fig.colorbar(im, ax=axes[0], fraction=0.046, pad=0.04)
    fig.tight_layout()
    p = CHART / "c4_corr.png"
    fig.savefig(p); plt.close(fig); out["corr"] = p

    # c5 edge: rolling 6m ann excess + cumulative excess
    roll = {k: v for k, v in m["rolling_6m_ann_excess"].items()}
    ridx = pd.to_datetime(list(roll.keys()))
    rval = np.array(list(roll.values()))
    mt2 = mt[mt["partial"] == False]
    cumex = (1 + (mt2["strat_ret"] - mt2["spy_ret"])).cumprod() - 1
    xd = pd.to_datetime(mt2["month"])
    fig, ax = plt.subplots(figsize=(7.6, 2.9), dpi=170)
    ax2 = ax.twinx()
    ax2.plot(ridx, rval, color=BLUE_C, lw=1.5, label="6개월 이동 연환산 초과 (좌)")
    ax2.axhline(0, color="0.5", lw=0.7, ls=":")
    ax2.set_ylabel("6개월 연환산 초과", fontsize=7.5, color=BLUE_C)
    ax2.tick_params(labelsize=7)
    ax.bar(xd, cumex.values, color=NAVY_C, alpha=0.75, width=25, label="누적 초과 (우)")
    ax.set_ylabel("누적 초과수익", fontsize=7.5)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y-%m"))
    ax.legend(loc="upper left", fontsize=7, frameon=False)
    ax.grid(alpha=0.2, lw=0.4)
    ax.tick_params(labelsize=6)
    fig.tight_layout()
    p = CHART / "c5_edge.png"
    fig.savefig(p); plt.close(fig); out["edge"] = p

    # c6 drawdown
    eq_s = eq["STRAT_PIT"] / eq["STRAT_PIT"].iloc[0]
    eq_b = eq["SPY"] / eq["SPY"].iloc[0]
    dd_s = eq_s / eq_s.cummax() - 1
    dd_b = eq_b / eq_b.cummax() - 1
    fig, ax = plt.subplots(figsize=(7.6, 2.8), dpi=170)
    ax.fill_between(dd_s.index, dd_s.values * 100, 0, color=NAVY_C, alpha=0.55, label="전략")
    ax.plot(dd_b.index, dd_b.values * 100, color=AMBER_C, lw=1.0, label="SPY")
    ax.set_ylabel("낙폭 (%)", fontsize=7.5)
    ax.legend(fontsize=7, frameon=False, loc="lower left")
    ax.grid(alpha=0.2, lw=0.4)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    p = CHART / "c6_dd.png"
    fig.savefig(p); plt.close(fig); out["dd"] = p

    # c7 perturbation grid
    fig, ax = plt.subplots(figsize=(7.6, 2.9), dpi=170)
    g = grid
    ax.scatter(g["cagr_full"] * 100, g["cagr_win"] * 100, s=26, color=BLUE_C, alpha=0.65, label="27 파라미터 조합")
    fz = g[g["frozen"]].iloc[0]
    ax.scatter([fz["cagr_full"] * 100], [fz["cagr_win"] * 100], s=70, marker="*", color=RED_C, zorder=5, label="동결점 (10/10/12)")
    ax.axhline(m["stats_spy"]["cagr"] * 100, color=AMBER_C, lw=0.9, ls="--")
    ax.text(0.02, 0.02, "SPY 연환산", transform=ax.transAxes, fontsize=6.5, color=AMBER_C)
    ax.set_xlabel("전체 기간(2018~2026) 연환산 (%)", fontsize=7.5)
    ax.set_ylabel("2024~2026 연환산 (%)", fontsize=7.5)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    ax.grid(alpha=0.2, lw=0.4)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    p = CHART / "c7_grid.png"
    fig.savefig(p); plt.close(fig); out["grid"] = p
    return out


# ---------------------------------------------------------------------------
# PDF build
# ---------------------------------------------------------------------------

def build():
    m = json.load(open(RES / "metrics.json", encoding="utf-8"))
    eq = pd.read_csv(RES / "equity.csv", index_col=0, parse_dates=True)
    mt = pd.read_csv(RES / "monthly_table.csv")
    grid = pd.read_csv(RES / "perturbation.csv")
    charts = make_charts(m, eq, mt, grid)

    font, fb = fonts()
    st = styles(font, fb)
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=13.5 * mm, rightMargin=13.5 * mm, topMargin=13 * mm, bottomMargin=15 * mm,
        title="미국 시장 강건 퀀트 전략 — 편향 제거 엄격 백테스트 보고서",
        author="Quant Research",
    )
    E = []
    W = 182 * mm

    # ---- cover ----
    banner = Table([
        [P("RLM Quantitative Research  ·  US ROBUST QUANT  ·  STRICT RE-TEST  ·  2026-08-15", st["cover_sub"])],
        [P("미국 시장 강건 퀀트전략<br/>편향 제거 · 엄격 백테스트 연구 보고서", st["cover_title"])],
        [P("2024~2026 레짐별 성과 · 벤치마크 비교 · 팩터 상관 · 엣지 분석 · 과적합 점검", st["cover_sub"])],
    ], colWidths=[A4[0] - 26 * mm])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 11),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ]))
    E.append(banner)
    E.append(Spacer(1, 8 * mm))
    info = Table([
        [P("전략", st["kpi"]), P("Robust_L60_M63_LV20 (2026-07-19 동결)", st["kpi_val"])],
        [P("분석 기간", st["kpi"]), P("2024-01 ~ 2026-07 (31개월) + 2026-08 부분월 (10거래일)", st["kpi_val"])],
        [P("검증 내용", st["kpi"]), P("편향 제거(PIT 유니버스) · 레짐별 성과 · 벤치마크 비교 · 팩터 상관 · 엣지 분석 · 과적합 점검", st["kpi_val"])],
        [P("작성일", st["kpi"]), P("2026-08-15", st["kpi_val"])],
    ], colWidths=[26 * mm, 156 * mm])
    info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.28, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    E.append(info)
    E.append(Spacer(1, 10 * mm))
    E.append(P("본 보고서는 동결된 운용 정책(Robust_L60_M63_LV20)을 그대로 재현하여 2024~2026 구간을 엄격하게 재검증한 연구 자료입니다. "
               "과거 성과는 미래 수익을 보장하지 않으며, 생존 편향 등 데이터 한계가 잔존합니다(본문 §9 참조).", st["small"]))
    E.append(PageBreak())

    # ---- toc ----
    E.append(section("목차", st))
    toc_rows = [
        ["1", "검증 설계 — 무엇을, 어떻게 엄격하게 검증했나", "데이터·프로토콜·편향/과적합 통제 표"],
        ["2", "2024~2026 성과 개요", "누적 곡선 · 연도별 성과 · 월별 수익률"],
        ["3", "월별 상세 (신호·체결·레짐·성과·보유종목)", "31개월 전체 표 + 월별 보유 종목 전부"],
        ["4", "레짐별 성과 (2024~2026)", "추세×변동성 2×2 셀 + 내부 레짐"],
        ["5", "벤치마크 대비 성과와 리스크", "SPY·EW 비교 · 낙폭 에피소드 · 섹터 집중"],
        ["6", "팩터(슬리브) 간 상관관계 분석", "슬리브 상관 · 스코어 랭크상관 · 이름 중첩"],
        ["7", "엣지 분석 — 초과수익은 통계적으로 실재하는가", "t검정·부트스트랩·CAPM·선택/틸트 분해"],
        ["8", "통계적 유의성 검증 (A to Z)", "엣지·팩터·레짐·강건성 전 검정의 판정표 — 신규"],
        ["9", "편향·과적합 점검 결과", "민감도 · 생존 편향 · 파라미터 섭동 · 구간 분할"],
        ["10", "결론과 한계", "요약 · 권고 · 한계 고지"],
    ]
    tbody = []
    for i, (n, t, d) in enumerate(toc_rows, start=1):
        tbody.append([P(n, st["td"]), P(t, st["td_left"]), P(d, st["small"])])
    tt = Table(tbody, colWidths=[10 * mm, 96 * mm, 76 * mm], repeatRows=0)
    cmds = [
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.28, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(len(tbody)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    cmds.append(("BACKGROUND", (0, 7), (-1, 7), colors.HexColor("#FBE9E7")))
    cmds.append(("TEXTCOLOR", (0, 7), (-1, 7), RED))
    tt.setStyle(TableStyle(cmds))
    E.append(tt)
    E.append(Spacer(1, 3 * mm))
    E.append(P("§8은 본 개정판에서 신규 추가된 장: 성과·엣지·팩터·레짐·강건성 전 영역의 통계적 유의성 검정을 한 곳에 모아 판정표로 정리.", st["small"]))
    E.append(PageBreak())

    # ---- executive summary ----
    st_s = m["stats_pit"]; bs = m["stats_spy"]; st_ew = m["stats_ew_pit"]
    E.append(section("요약 — 검증의 결론", st))
    kpi = table(
        ["지표", "전략 (PIT 유니버스)", "SPY (벤치마크)", "EW 동일유니버스"],
        [
            ["총수익률 (2024-01~2026-07)", pct(st_s["total_return"]), pct(bs["total_return"]), pct(st_ew["total_return"])],
            ["연환산 수익률", pct(st_s["cagr"]), pct(bs["cagr"]), pct(st_ew["cagr"])],
            ["샤프 지수 (일별)", num(st_s["sharpe"]), num(bs["sharpe"]), num(st_ew["sharpe"])],
            ["최대 낙폭 (MDD)", pct(st_s["mdd"]), pct(bs["mdd"]), pct(st_ew["mdd"])],
            ["월간 승률", pct(st_s["win_month"], 0), pct(bs["win_month"], 0), pct(st_ew["win_month"], 0)],
            ["정보비율 (vs SPY)", num(st_s["info_ratio"]), "-", "-"],
            ["알파 (연환산, vs SPY)", pct(st_s["alpha"]), "-", "-"],
            ["베타 (vs SPY)", num(st_s["beta"]), "1.00", "-"],
        ],
        st, [34 * mm, 50 * mm, 50 * mm, 48 * mm], left0=True,
    )
    E.append(kpi)
    E.append(Spacer(1, 2.5 * mm))
    E.append(P("<b>1. 성과.</b> 동결 정책을 2024-01부터 매월 그대로 실행했을 때 2024-01~2026-07(31개월) 누적 "
               f"<b>+{st_s['total_return']*100:.0f}%</b> (연환산 {st_s['cagr']*100:.1f}%), 같은 기간 SPY +{bs['total_return']*100:.0f}%. "
               f"월간 초과 +4.0%p(연환산 {m['edge_vs_spy']['ann_mean']*100:.0f}%), t={m['edge_vs_spy']['t_stat']}, "
               f"부트스트랩 P(초과&gt;0)={m['edge_vs_spy']['iid_boot']['prob_positive']*100:.0f}%.", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("<b>2. 엣지의 원천.</b> 초과수익은 종목 선택(동일 유니버스 EW 대비 연환산 +43.7%p, t=2.20)이 약 77%(월평균 기준), "
               "대형주 대비 중형·동일비중 틸트(+11.8%p, t=2.68)가 약 23%를 기여. CAPM 알파는 연환산 36.3%(t=1.72).", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("<b>3. 레짐 의존성.</b> 추세↑·저변동에서 연환산 +175.9%(SPY +23.7%), 추세↑·고변동 +31.5%, 추세↓·고변동(위기·반등 3개월) +165.8% "
               "(방어적 종목 수 조정 효과). 내부 레짐 기준 박스장(-12.2%/년)이 유일한 취약 구간. 추세↓·저변동은 표본에 없음.", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("<b>4. 리스크.</b> 2026-07 한 달 -24.8%(SPY +0.03%) — 평균 최대 섹터 비중 44.5%, 2026-06 신호 시점 71.4%(반도체 집중). "
               "최대 낙폭 -32.2%는 SPY(-18.8%)의 1.7배로, '낙폭이 벤치보다 양호'라는 동결 검증 기준(G3)은 이 구간에서 실패.", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("<b>5. 과적합·편향 점검.</b> 파라미터 27조합 섭동에서 동결점은 CAGR 기준 상위 33% 지점(고원 중앙), 27/27 조합이 초과수익 양(+) — "
               "파라미터 선택이 결과를 좌우하지 않음. PIT 유니버스 적용 시 CAGR 82.5%(고정 유니버스 87.6% 대비 -5.1%p, 방향 일관). "
               "잔존 생존 편향은 과대평가 방향(수준 미제거).", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("<b>6. 진정한 표본 외.</b> 본 구간(2024-01~2026-06)은 동결 연구의 공식 OOS 구간이며, 동결(2026-07-19) 이후 첫 신호 "
               "(2026-07-31 → 8월 체결, 10거래일)는 +2.4%(SPY +3.9%). 향후 라이브 운영이 진짜 판정.", st["body"]))
    E.append(PageBreak())

    # ---- 1. design ----
    E.append(section("1. 검증 설계 — 무엇을, 어떻게 엄격하게 검증했나", st))
    E.append(P("<b>1-1. 재현 대상.</b> 2026-07-19 동결된 운용 정책 <b>Robust_L60_M63_LV20</b>: 핵심모멘텀 60% / 중기모멘텀 20% / 저변동성 20%, "
               "슬리브 내 동일비중, 개별 종목 15% 상한, 월말 종가 신호 → 익영업일 시가 체결, 편도 10bp. 모든 파라미터는 동결 상수만 사용했고 "
               "이 보고서를 위해 어떤 값도 재튜닝하지 않았다.", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("<b>1-2. 데이터.</b> S&amp;P500 현재 구성 종목 중 유동성 상위 148종(운영 유니버스 기준 상위 150), 일별 종가·시가·거래량 "
               "2018-01-02~2026-08-14, 벤치마크 SPY. 신호 32회(2023-12-29~2026-07-31), 보유월 2024-01~2026-07(31개월) + 2026-08 부분월(10거래일).", st["body"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>1-3. 편향 통제 — 이 보고서에서 제거/검증한 편향</b>", st["h2"]))
    E.append(table(
        ["편향", "처리 방법", "결과 요약"],
        [
            ["룩어헤드 (신호-체결)", "익영업일 시가 체결(NEXT_OPEN). 민감도로 신호일 종가 체결 병행", "신호 종가 체결 시 CAGR 76.4% (기준 82.5%) — NEXT_OPEN이 결과를 부풀리지 않음"],
            ["멤버십 룩어헤드", "포인트인타임(PIT) 유니버스: 신호 시점 거래대금 상위 150 + 최소 252일 가격 이력. 고정 유니버스와 비교", "CAGR 82.5% vs 87.6% (-5.1%p) — 방향 일관, 결론 불변"],
            ["생존 편향", "상장폐지 종목이 패널에 없음 — 데이터 한계로 제거 불가", "과거 성과 과대평가 방향. 수준은 미제거, 유니버스 크기 민감도로 부호 확인"],
            ["비용 가정", "편도 10bp 기본 + 0bp/20bp 민감도", "20bp에서도 CAGR 81.6% — 비용 민감도 낮음"],
            ["유니버스 크기", "PIT top_n 100/125/150", "CAGR 61.9%/75.8%/82.5% — 단조 증가, 방향 일관"],
        ],
        st, [30 * mm, 66 * mm, 86 * mm], left0=True,
    ))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>1-4. 과적합 통제</b>", st["h2"]))
    E.append(table(
        ["통제 수단", "설명"],
        [
            ["파라미터 동결", "2026-07-19 동결 값만 사용. 본 윈도우에서 어떤 파라미터도 선택·조정하지 않음"],
            ["레짐 규칙 사전 지정", "추세 = SPY vs 200일 이동평균, 변동성 = 21일 실현변동성 vs 직전 1년 중앙값 — 결과를 본 뒤 만든 규칙 아님"],
            ["파라미터 섭동 그리드", "슬리브 종목 수 3×3×3=27조합을 전체 기간(2018~2026)과 본 윈도우에 전부 실행(§9-3)"],
            ["구간 분할", "연구 기간(2024-01~2026-06) / 연구 종료 직후 신호(2026-07 보유월) / 동결 후(2026-08 부분월)로 나누어 해석"],
            ["통계 검정", "월 초과 t검정 + iid/블록 부트스트랩(4개월 블록) + CAPM 알파 t검정"],
        ],
        st, [38 * mm, 144 * mm], left0=True,
    ))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>1-5. 재현 검증.</b> 신호·비중 재현 파이프라인은 라이브 산출물(2026-06/2026-07 ops_runs)과 교차 검증했다. "
               "PIT/고정 두 경로 모두 잔여 차이는 데이터 패널 드리프트(SNDK 백필 추가, EA 백필 실패로 제외)로만 설명되며 — "
               "PIT와 고정의 차이 목록이 완전히 동일 — 선택 로직 자체의 불일치는 없다(기존 149종 패널 기준 일치 검증은 "
               "results/strict_asif 참조).", st["body"]))
    E.append(PageBreak())

    # ---- 2. performance ----
    E.append(section("2. 2024~2026 성과 개요", st))
    E.append(Image(str(charts["equity"]), width=W, height=W * 0.41))
    E.append(Spacer(1, 2 * mm))
    yrs = m["years"]
    E.append(P("<b>2-1. 연도별 성과</b>", st["h2"]))
    E.append(table(
        ["구간", "개월", "전략 수익", "전략 연환산", "샤프", "전략 MDD", "SPY 수익", "SPY MDD", "연환산 초과", "초과 승률"],
        [
            ["2024", "12", pct(yrs["2024"]["total"]), pct(yrs["2024"]["cagr"]), num(yrs["2024"]["sharpe"]),
             pct(yrs["2024"]["mdd"]), pct(yrs["2024"]["bench_total"]), pct(yrs["2024"]["bench_mdd"]),
             pct(yrs["2024"]["ann_excess"]), pct(yrs["2024"]["hit"], 0)],
            ["2025", "12", pct(yrs["2025"]["total"]), pct(yrs["2025"]["cagr"]), num(yrs["2025"]["sharpe"]),
             pct(yrs["2025"]["mdd"]), pct(yrs["2025"]["bench_total"]), pct(yrs["2025"]["bench_mdd"]),
             pct(yrs["2025"]["ann_excess"]), pct(yrs["2025"]["hit"], 0)],
            ["2026 상반기", "6", pct(yrs["2026H1"]["total"]), pct(yrs["2026H1"]["cagr"]), num(yrs["2026H1"]["sharpe"]),
             pct(yrs["2026H1"]["mdd"]), pct(yrs["2026H1"]["bench_total"]), pct(yrs["2026H1"]["bench_mdd"]),
             pct(yrs["2026H1"]["ann_excess"]), pct(yrs["2026H1"]["hit"], 0)],
            ["2026-07", "1", pct(yrs["2026-07"]["total"]), pct(yrs["2026-07"]["cagr"]), num(yrs["2026-07"]["sharpe"]),
             pct(yrs["2026-07"]["mdd"]), pct(yrs["2026-07"]["bench_total"]), pct(yrs["2026-07"]["bench_mdd"]),
             pct(yrs["2026-07"]["ann_excess"]), pct(yrs["2026-07"]["hit"], 0)],
        ],
        st, [20 * mm, 12 * mm, 18 * mm, 20 * mm, 12 * mm, 18 * mm, 18 * mm, 18 * mm, 20 * mm, 18 * mm],
        left0=True, highlight_rows=[(4, None)],
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("연환산 초과는 월 평균 초과를 복리 연환산한 값, 샤프는 일별 수익률 기준. 2026 상반기(+140.9%)와 2026-07(-24.8%)의 "
               "비대칭이 성과의 본질: 최근 6개월의 과잉 성과가 반도체 집중 리스크의 반대급부.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>2-2. 월별 수익률</b>", st["h2"]))
    E.append(Image(str(charts["monthly"]), width=W, height=W * 0.39))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P(f"월간 승률 {pct(st_s['win_month'], 0)}, SPY 대비 초과 승률 {pct(m['edge_vs_spy']['hit_rate'], 0)}. "
               "최악의 달은 2026-07(-24.8%), 최고의 달은 2026-02(+20.6%).", st["small"]))
    E.append(PageBreak())

    # ---- 3. monthly detail ----
    E.append(section("3. 월별 상세 (신호·체결·레짐·성과·보유종목)", st))
    mtf = mt[mt["partial"] == False]
    mtp = mt[mt["partial"] == True]
    head = ["월", "신호일", "체결일", "레짐 (추세·변동)", "내부", "종목수", "턴오버", "전략", "SPY", "EW", "초과(SPY)", "최대섹터"]
    widths = [13 * mm, 15 * mm, 15 * mm, 21 * mm, 13 * mm, 11 * mm, 11 * mm, 14 * mm, 13 * mm, 13 * mm, 15 * mm, 14 * mm]
    def mrow(r):
        return [r["month"], r["signal"][5:], r["exec"][5:], r["regime_cell"], r["regime_internal"],
                int(r["n_names"]), num(r["turnover"], 2), pct(r["strat_ret"]), pct(r["spy_ret"]),
                pct(r["ew_ret"]), pct(r["excess_spy"]), pct(r["max_sector_w"], 0)]
    rows_a = [mrow(r) for _, r in mtf[mtf["month"] < "2026-01"].iterrows()]
    rows_b = [mrow(r) for _, r in mtf[mtf["month"] >= "2026-01"].iterrows()]
    rows_b.append(mrow(mtp.iloc[0]))
    E.append(P("<b>3-1. 2024~2025</b>", st["h2"]))
    E.append(table(head, rows_a, st, widths, left0=True))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>3-2. 2026 (하단 빨간 행 = 2026-08 부분월, 10거래일)</b>", st["h2"]))
    E.append(table(head, rows_b, st, widths, left0=True, highlight_rows=[(len(rows_b), None)]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("레짐은 신호일(월말) 기준 사전 지정 규칙으로 분류: 추세 = SPY 종가 vs 200일 이동평균, "
               "변동성 = 21일 실현변동성 vs 직전 1년 중앙값. 내부 레짐은 전략 자체의 시장 국면 판단(강세/박스/약세). "
               "2026-08 부분월은 동결 이후 첫 신호의 실적: +2.4%(SPY +3.9%).", st["small"]))
    E.append(Spacer(1, 3 * mm))

    # ---- 3-3. holdings per month ----
    hold = pd.read_csv(RES / "holdings.csv")
    E.append(P("<b>3-3. 월별 보유 종목 (전부 기입)</b>", st["h2"]))
    E.append(P("보유 종목은 해당 월 신호일(월말 종가) 기준 선정 목록이며, 익영업일 시가에 체결되어 다음 리밸런싱까지 보유 "
               "(이 구간 체결 누락 0건 — 선정 목록 = 실제 보유). 슬리브별 스코어 순으로 나열. 핵심모멘텀과 중기모멘텀은 종목이 겹칠 수 있음(§6-2 참조). "
               "2026-08 행은 부분월(10거래일).", st["small"]))
    E.append(Spacer(1, 1.5 * mm))
    hw = [12 * mm, 57 * mm, 57 * mm, 56 * mm]
    hhead = ["월", "핵심모멘텀 (60%, 스코어순)", "중기모멘텀 (20%, 63일 수익률순)", "저변동성 (20%, 변동성 낮은 순)"]
    def hrow(r):
        return [r["month"], r["leader"], r["mom63"], r["lowvol"]]
    hmap = {1: st["tdx"], 2: st["tdx"], 3: st["tdx"]}
    ha = [hrow(r) for _, r in hold[hold["month"] < "2026-01"].iterrows()]
    hb = [hrow(r) for _, r in hold[hold["month"] >= "2026-01"].iterrows()]
    E.append(P("<b>2024~2025</b>", st["h2"]))
    E.append(table(hhead, ha, st, hw, left0=True, cell_map=hmap))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>2026 (하단 빨간 행 = 2026-08 부분월)</b>", st["h2"]))
    E.append(table(hhead, hb, st, hw, left0=True, cell_map=hmap, highlight_rows=[(len(hb), None)]))
    E.append(PageBreak())

    # ---- 4. regime ----
    E.append(section("4. 레짐별 성과 (2024~2026)", st))
    E.append(P("<b>4-1. 레짐 정의 (사전 지정 — 결과 확인 후 조정 없음)</b>", st["h2"]))
    E.append(table(
        ["차원", "규칙", "신호일 기준"],
        [
            ["추세", "SPY 종가 &gt; 200일 이동평균(최소 120일) → 추세↑, 그 외 추세↓", "월말 종가"],
            ["변동성", "21일 실현변동성(연환산) &gt; 직전 252일 중앙값 → 고변동, 그 외 저변동", "월말 종가"],
        ],
        st, [22 * mm, 130 * mm, 30 * mm], left0=True,
    ))
    E.append(Spacer(1, 2 * mm))
    cells = m["regime_cells"]
    cell_order = ["추세↑·저변동", "추세↑·고변동", "추세↓·저변동", "추세↓·고변동"]
    cres = []
    for k in cell_order:
        v = cells.get(k)
        if v is None:
            cres.append([k, "0", "-", "-", "-", "-", "-", "-"])
            continue
        months = m["regime_cell_months"].get(k, [])
        mstr = ", ".join(months[:4]) + (" …" if len(months) > 4 else "")
        cres.append([
            k, str(v["n_months"]), pct(v["strat_mean_monthly"]), pct(v["strat_ann"]),
            pct(v["spy_ann"]), pct(v["excess_ann"]), pct(v["strat_win"], 0), mstr,
        ])
    E.append(P("<b>4-2. 레짐 셀별 성과</b>", st["h2"]))
    E.append(table(
        ["레짐 셀", "월 수", "월평균 전략", "전략 연환산", "SPY 연환산", "초과 연환산", "전략 승률", "해당 월(일부)"],
        cres, st, [24 * mm, 11 * mm, 18 * mm, 20 * mm, 18 * mm, 20 * mm, 14 * mm, 57 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("추세↓·저변동은 2024~2026 표본에 한 번도 발생하지 않음. 추세↓·고변동 3개월(2025-04, 2025-05, 2026-04)은 "
               "위기·급반등 구간으로, 전략의 방어적 종목 수 조정(약세장 코어 최대 3종 + 신고가 근접도 90% 상향)이 반등을 온전히 누리게 한 결과.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(Image(str(charts["regime"]), width=W, height=W * 0.38))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>4-3. 전략 내부 레짐(강세/박스/약세) 기준</b>", st["h2"]))
    intr = m["regime_internal"]
    E.append(table(
        ["내부 레짐", "월 수", "전략 연환산", "SPY 연환산", "해석"],
        [
            ["강세 (bull)", str(intr["bull"]["n_months"]), pct(intr["bull"]["strat_ann"]), pct(intr["bull"]["spy_ann"]),
             "모멘텀 엔진 가동 — 성과의 대부분"],
            ["박스 (sideways)", str(intr["sideways"]["n_months"]), pct(intr["sideways"]["strat_ann"]), pct(intr["sideways"]["spy_ann"]),
             "유일한 마이너스 구간 — 코어 축소(최대 7종)로 인한 회전 손실"],
            ["약세 (bear)", str(intr["bear"]["n_months"]), pct(intr["bear"]["strat_ann"]), pct(intr["bear"]["spy_ann"]),
             "방어 조정 + 반등 포착 — 3개월 모두 양(+)"],
        ],
        st, [30 * mm, 13 * mm, 22 * mm, 22 * mm, 95 * mm], left0=True,
    ))
    E.append(PageBreak())

    # ---- 5. benchmark & risk ----
    E.append(section("5. 벤치마크 대비 성과와 리스크", st))
    E.append(Image(str(charts["dd"]), width=W, height=W * 0.37))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>5-1. 낙폭 에피소드 (전략, -5% 이상)</b>", st["h2"]))
    dds = m["drawdowns_strat"]
    drows = [[d["peak"], d["trough"], pct(d["depth"]), d["recovered"] or "미회복",
              d["days_to_recover"] if d["days_to_recover"] is not None else "-"] for d in dds]
    E.append(table(["피크일", "트로프일", "깊이", "회복일", "회복 소요(일)"], drows, st,
                   [30 * mm, 30 * mm, 22 * mm, 34 * mm, 28 * mm], left0=True))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("2025-04 에피소드(-25.1%, 153일 회복)와 2026-07 에피소드(-32.2%, 미회복)가 핵심. "
               "SPY의 최대 낙폭은 2025-02-19~2025-04-08 -18.8%(79일 회복).", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>5-2. 벤치마크 대비 요약</b>", st["h2"]))
    E.append(table(
        ["지표", "전략", "SPY", "차이/해석"],
        [
            ["연환산 수익률", pct(st_s["cagr"]), pct(bs["cagr"]), f"+{pct(st_s['cagr']-bs['cagr'])}p"],
            ["총수익률", pct(st_s["total_return"]), pct(bs["total_return"]),
             f"{(1 + st_s['total_return']) / (1 + bs['total_return']):.1f}배 (누적배수 기준)"],
            ["샤프", num(st_s["sharpe"]), num(bs["sharpe"]), "-"],
            ["최대 낙폭", pct(st_s["mdd"]), pct(bs["mdd"]), "전략이 1.7배 깊음 — G3 기준 실패"],
            ["베타", num(st_s["beta"]), "1.00", "시장 민감도 1.29 (일별 기준)"],
            ["월간 승률", pct(st_s["win_month"], 0), pct(bs["win_month"], 0), "-"],
            ["초과 승률", pct(m["edge_vs_spy"]["hit_rate"], 0), "-", "31개월 중 22개월 초과"],
            ["정보비율", num(st_s["info_ratio"]), "-", "연환산 초과 대비 변동성"],
        ],
        st, [30 * mm, 24 * mm, 24 * mm, 104 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("섹터 집중: 월별 최대 섹터 비중 평균 44.5% (2026-06 신호 시점 최고 71.4%, 반도체). "
               "동결 정책의 섹터 40% 상한은 best-effort라 2026-07 급락을 막지 못했으며, 실제 게이트 승격이 필요하다.", st["warn"]))
    E.append(PageBreak())

    # ---- 6. factor correlation ----
    E.append(section("6. 팩터(슬리브) 간 상관관계 분석", st))
    f = m["factor"]
    sl = m["sleeve_stats"]
    E.append(P("<b>6-1. 슬리브 단독 성과 (각 슬리브 100% 운용 시, 10bp)</b>", st["h2"]))
    E.append(table(
        ["슬리브", "연환산", "총수익", "샤프", "MDD", "알파(연환산)", "베타", "월간승률", "2026-07 수익"],
        [
            ["핵심모멘텀 (60%)", pct(sl["leader"]["cagr"]), pct(sl["leader"]["total_return"]), num(sl["leader"]["sharpe"]),
             pct(sl["leader"]["mdd"]), pct(sl["leader"]["alpha"]), num(sl["leader"]["beta"]), pct(sl["leader"]["win_month"], 0),
             pct(m["july_2026_sleeve_rets"]["leader"])],
            ["중기모멘텀 (20%)", pct(sl["mom63"]["cagr"]), pct(sl["mom63"]["total_return"]), num(sl["mom63"]["sharpe"]),
             pct(sl["mom63"]["mdd"]), pct(sl["mom63"]["alpha"]), num(sl["mom63"]["beta"]), pct(sl["mom63"]["win_month"], 0),
             pct(m["july_2026_sleeve_rets"]["mom63"])],
            ["저변동성 (20%)", pct(sl["lowvol"]["cagr"]), pct(sl["lowvol"]["total_return"]), num(sl["lowvol"]["sharpe"]),
             pct(sl["lowvol"]["mdd"]), pct(sl["lowvol"]["alpha"]), num(sl["lowvol"]["beta"]), pct(sl["lowvol"]["win_month"], 0),
             pct(m["july_2026_sleeve_rets"]["lowvol"])],
        ],
        st, [24 * mm, 17 * mm, 17 * mm, 12 * mm, 15 * mm, 22 * mm, 12 * mm, 17 * mm, 20 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("2026-07 급락월에 저변동성 슬리브만 유일하게 플러스(+4.2%) — 두 모멘텀 슬리브(-34.1%, -23.4%)와 "
               "수익률 상관이 거의 0(0.01~0.09)인 방어 슬리브가 포트폴리오 분산의 실질적 원천.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>6-2. 슬리브 월수익률 상관</b>", st["h2"]))
    cp = f["sleeve_return_corr_pearson"]
    E.append(table(
        ["", "핵심모멘텀", "중기모멘텀", "저변동성", "SPY와 상관"],
        [
            ["핵심모멘텀", num(cp["leader"]["leader"]), num(cp["leader"]["mom63"]), num(cp["leader"]["lowvol"]),
             num(f["sleeve_corr_vs_spy"]["leader"])],
            ["중기모멘텀", num(cp["mom63"]["leader"]), num(cp["mom63"]["mom63"]), num(cp["mom63"]["lowvol"]),
             num(f["sleeve_corr_vs_spy"]["mom63"])],
            ["저변동성", num(cp["lowvol"]["leader"]), num(cp["lowvol"]["mom63"]), num(cp["lowvol"]["lowvol"]),
             num(f["sleeve_corr_vs_spy"]["lowvol"])],
        ],
        st, [24 * mm, 26 * mm, 26 * mm, 26 * mm, 30 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P(f"두 모멘텀 슬리브 간 상관 {cp['leader']['mom63']:.2f}(스피어만 {f['sleeve_return_corr_spearman']['leader']['mom63']:.2f}) — 사실상 같은 엔진. 중기모멘텀의 '추가 분산 효과'는 기대하기 어렵고, "
               "저변동성 슬리브만이 실질 분산을 제공한다. 슬리브 간 이름 중첩: 핵심∩중기 평균 5.0종(Jaccard 0.37), "
               "핵심∩저변동·중기∩저변동 평균 0.1종(Jaccard ~0.01).", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>6-3. 팩터 스코어 횡단면 랭크상관 (월별 평균)</b>", st["h2"]))
    sc = f["score_rank_corr"]
    E.append(table(
        ["팩터 쌍", "평균 스피어만 상관", "월별 표준편차", "해석"],
        [
            ["핵심모멘텀 점수 ↔ 중기모멘텀", num(sc["leader_score vs mom63_raw"]["mean"]), num(sc["leader_score vs mom63_raw"]["std"]),
             "정보 중복이 높음 — 두 슬리브는 같은 모멘텀 신호의 변형"],
            ["핵심모멘텀 점수 ↔ 저변동성", num(sc["leader_score vs lowvol_score"]["mean"]), num(sc["leader_score vs lowvol_score"]["std"]),
             "부호가 반대 경향 — 방어/성장 구조"],
            ["중기모멘텀 ↔ 저변동성", num(sc["mom63_raw vs lowvol_score"]["mean"]), num(sc["mom63_raw vs lowvol_score"]["std"]),
             "거의 무상관 — 분산 원천"],
            ["12-1개월 모멘텀 ↔ 63일 모멘텀", num(sc["mom_12_1 vs mom_63"]["mean"]), num(sc["mom_12_1 vs mom_63"]["std"]),
             "중간 수준 — 서로 다른 시계(연간/분기)"],
            ["52주 신고가 근접도 ↔ 12-1 모멘텀", num(sc["near_high vs mom_12_1"]["mean"]), num(sc["near_high vs mom_12_1"]["std"]),
             "추세 확인 지표 간 일관"],
        ],
        st, [56 * mm, 30 * mm, 28 * mm, 68 * mm], left0=True,
    ))
    E.append(Spacer(1, 2 * mm))
    E.append(Image(str(charts["corr"]), width=W, height=W * 0.38))
    E.append(PageBreak())

    # ---- 7. edge ----
    E.append(section("7. 엣지 분석 — 초과수익은 통계적으로 실재하는가", st))
    ev = m["edge_vs_spy"]; ee = m["edge_vs_ew"]; tl = m["tilt_ew_vs_spy"]
    capm = m["capm_vs_spy"]
    sel_share = ee["monthly_mean"] / ev["monthly_mean"]
    tilt_share = tl["monthly_mean"] / ev["monthly_mean"]
    E.append(P("<b>7-1. 월별 초과수익 통계 (31개월)</b>", st["h2"]))
    E.append(table(
        ["대상", "월평균 초과", "연환산 초과", "t값", "승률", "iid 부트스트랩 90% CI", "P(초과&gt;0)", "블록(4m) P(초과&gt;0)"],
        [
            ["전략 - SPY", pct(ev["monthly_mean"]), pct(ev["ann_mean"]), num(ev["t_stat"]), pct(ev["hit_rate"], 0),
             f"[{pct(ev['iid_boot']['ann_p5'])}, {pct(ev['iid_boot']['ann_p95'])}]", pct(ev["iid_boot"]["prob_positive"], 1),
             pct(ev["block4_boot"]["prob_positive"], 1)],
            ["전략 - EW 동일유니버스", pct(ee["monthly_mean"]), pct(ee["ann_mean"]), num(ee["t_stat"]), pct(ee["hit_rate"], 0),
             f"[{pct(ee['iid_boot']['ann_p5'])}, {pct(ee['iid_boot']['ann_p95'])}]", pct(ee["iid_boot"]["prob_positive"], 1),
             pct(ee["block4_boot"]["prob_positive"], 1)],
            ["EW 동일유니버스 - SPY", pct(tl["monthly_mean"]), pct(tl["ann_mean"]), num(tl["t_stat"]), pct(tl["hit_rate"], 0),
             f"[{pct(tl['iid_boot']['ann_p5'])}, {pct(tl['iid_boot']['ann_p95'])}]", pct(tl["iid_boot"]["prob_positive"], 1),
             pct(tl["block4_boot"]["prob_positive"], 1)],
        ],
        st, [34 * mm, 18 * mm, 18 * mm, 12 * mm, 12 * mm, 34 * mm, 24 * mm, 24 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("31개월이라는 표본 크기로는 구간 추정 폭이 넓다(연환산 초과 90% CI 약 +17%~+115%). "
               "'엣지가 0이다'는 기각되지만(t=2.49), '엣지의 크기'는 아직 정밀하게 측정되지 않는다.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>7-2. CAPM 회귀 (월 수익률)</b>", st["h2"]))
    E.append(table(
        ["모형", "알파(월)", "알파(연환산)", "알파 t값", "베타", "R²"],
        [
            ["전략 ~ SPY", pct(capm["alpha_monthly"]), pct(capm["alpha_ann"]), num(capm["t_alpha"]),
             num(capm["beta"]), num(capm["r2"])],
        ],
        st, [26 * mm, 20 * mm, 26 * mm, 20 * mm, 16 * mm, 14 * mm], left0=True,
    ))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>7-3. 엣지의 분해 — 선택 vs 유니버스 틸트</b>", st["h2"]))
    E.append(table(
        ["구성 요소", "연환산", "t값", "기여 비중", "의미"],
        [
        ["전체 초과 (전략 - SPY)", pct(ev["ann_mean"]), num(ev["t_stat"]), "100%", "시장 대비 총 엣지"],
            ["선택 엣지 (전략 - EW 동일유니버스)", pct(ee["ann_mean"]), num(ee["t_stat"]),
             f"{pct(sel_share, 0)}", "같은 종목 풀 안에서의 선택 능력"],
            ["틸트 (EW 동일유니버스 - SPY)", pct(tl["ann_mean"]), num(tl["t_stat"]),
             f"{pct(tilt_share, 0)}", "대형주 지수 대비 중형·동일비중 노출의 우연적 이득"],
        ],
        st, [48 * mm, 16 * mm, 14 * mm, 18 * mm, 86 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("기여 비중은 월평균 초과 기준(선택 3.1%p + 틸트 0.9%p = 전체 4.0%p) — 연환산 값은 복리로 합산되지 않음. "
               "선택 엣지가 총 초과의 약 77%를 차지 — 이 전략의 초과수익은 '중형주에 몰아서' 얻는 것이 아니라 "
               "같은 유니버스 안에서의 종목 선정에서 나온다. 다만 틸트도 통계적으로 유의(t=2.68)하며, "
               "운용 시 '동일 유니버스 EW 대비 초과'를 별도로 모니터링할 것을 권고한다.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>7-4. 시간에 따른 엣지</b>", st["h2"]))
    E.append(Image(str(charts["edge"]), width=W, height=W * 0.38))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("6개월 이동 연환산 초과가 2025 하반기~2026 상반기에 +100%를 넘었고, 2026-07에 급락. "
               "엣지는 레짐에 강하게 의존하므로 '평균 엣지'만 보지 말고 레짐 조건부 기대치(§4)를 함께 봐야 한다.", st["small"]))
    E.append(PageBreak())

    # ---- 8. statistical significance (NEW) ----
    s = json.load(open(RES / "significance.json", encoding="utf-8"))
    E.append(section("8. 통계적 유의성 검증 (A to Z)", st))
    E.append(P("<b>8-1. 검정 설계와 판정 기준</b>", st["h2"]))
    E.append(P("① 사전지정 검정(primary): 월별 초과 t검정, 부트스트랩(10,000회), CAPM 알파 — 보고서 설계 시점에 검정 방식을 고정해 두고 결과를 본 뒤 바꾸지 않았다. "
               "② 탐색적 검정(secondary): 팩터 상관·스코어 랭크상관·이름 중첩·레짐 셀 — 결론 보조용이며 해석에만 사용. "
               "③ 판정: 양측 5% 유의수준, 10% 미만은 '경계'로 표기. ④ 표본: 월간 31개(2024-01~2026-07, 2026-08 부분월 제외), 유니버스 148종. "
               "⑤ 다중검정 주의: 아래 검정은 총 25개 내외로, 5% 유의수준에서 우연히 1~2개는 거짓 양성일 수 있다 — 개별 p값보다 '사전지정 검정 + 다중 경로 일관성'을 함께 봐야 한다.", st["body"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>8-2. 성과·엣지 유의성 판정표</b>", st["h2"]))
    e = s["edge"]
    c = s["capm"]
    sb = s["sharpe_boot"]
    a1 = s["ar1"]
    sz = s["strat_mean_vs_zero"]
    E.append(table(
        ["검정", "통계량", "t / CI", "p값", "판정"],
        [
            ["월 초과 vs SPY (t검정)", f"+{pct(e['excess_vs_spy']['monthly_mean'])}/월", num(e["excess_vs_spy"]["t"]), num(e["excess_vs_spy"]["p_t"]), e["excess_vs_spy"]["verdict_t"]],
            ["월 초과 vs EW 동일유니버스 (t검정)", f"+{pct(e['excess_vs_ew']['monthly_mean'])}/월", num(e["excess_vs_ew"]["t"]), num(e["excess_vs_ew"]["p_t"]), e["excess_vs_ew"]["verdict_t"]],
            ["틸트: EW - SPY (t검정)", f"+{pct(e['tilt_ew_vs_spy']['monthly_mean'])}/월", num(e["tilt_ew_vs_spy"]["t"]), num(e["tilt_ew_vs_spy"]["p_t"]), e["tilt_ew_vs_spy"]["verdict_t"]],
            ["전략 월수익률 vs 0 (t검정)", f"+{pct(sz['monthly_mean'])}/월", num(sz["t"]), num(sz["p"]), sz["verdict"]],
            ["초과 승률 vs SPY (이항검정)", f"{e['excess_vs_spy']['win_months']}/{e['excess_vs_spy']['n']}개월", "-", num(e["excess_vs_spy"]["p_binomial_hit"]), "유의(5%)" if e["excess_vs_spy"]["p_binomial_hit"] < 0.05 else "미유의"],
            ["초과 승률 vs EW (이항검정)", f"{e['excess_vs_ew']['win_months']}/{e['excess_vs_ew']['n']}개월", "-", num(e["excess_vs_ew"]["p_binomial_hit"]), "유의(5%)" if e["excess_vs_ew"]["p_binomial_hit"] < 0.05 else "미유의"],
            ["CAPM 알파 (월수익률 ~ SPY)", pct(c["vs_spy"]["alpha_ann"]), f"t={num(c['vs_spy']['t_alpha'])}", num(c["vs_spy"]["p_alpha"]), c["vs_spy"]["verdict"]],
            ["CAPM 알파 (월수익률 ~ EW)", pct(c["vs_ew"]["alpha_ann"]), f"t={num(c['vs_ew']['t_alpha'])}", num(c["vs_ew"]["p_alpha"]), c["vs_ew"]["verdict"]],
            ["샤프 부트스트랩 95% CI", "전략 vs SPY", f"[{num(sb['strat']['ci95'][0])}, {num(sb['strat']['ci95'][1])}] vs [{num(sb['spy']['ci95'][0])}, {num(sb['spy']['ci95'][1])}]", "-", "CI 중첩 — 구분 불가"],
            ["월 초과 자기상관 AR(1)", f"rho={num(a1['excess_vs_spy']['rho1'])}", f"t={num(a1['excess_vs_spy']['t'])}", num(a1["excess_vs_spy"]["p"]), "독립성 가정 기각 안 됨"],
        ],
        st, [52 * mm, 34 * mm, 36 * mm, 18 * mm, 42 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("핵심 엣지(월 초과 +4.0%p, t=2.49, p=0.019)와 승률(22/31, 이항 p=0.015)은 5%에서 유의. CAPM 알파(36.3%/년)는 t=1.72로 경계(p=0.096) — "
               "31개월 표본으로는 '알파가 있다'는 강한 주장까지는 도달하지 못한다. 샤프는 CI가 크게 겹쳐 차이를 판정할 수 없다. "
               "월 초과의 AR(1)=0.10(p=0.62)로 부트스트랩의 독립성 가정은 기각되지 않았다.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>8-3. 팩터 분석 유의성 판정표</b>", st["h2"]))
    sc_ = s["sleeve_corr"]
    E.append(table(
        ["검정", "통계량", "95% CI / p", "판정"],
        [
            ["핵심모멘텀 ↔ 중기모멘텀 월수익률 상관", num(sc_["leader_mom63"]["r"]), f"[{num(sc_['leader_mom63']['ci95'][0])}, {num(sc_['leader_mom63']['ci95'][1])}]", sc_["leader_mom63"]["verdict"]],
            ["핵심모멘텀 ↔ 저변동성 월수익률 상관", num(sc_["leader_lowvol"]["r"]), f"[{num(sc_['leader_lowvol']['ci95'][0])}, {num(sc_['leader_lowvol']['ci95'][1])}]", sc_["leader_lowvol"]["verdict"]],
            ["중기모멘텀 ↔ 저변동성 월수익률 상관", num(sc_["mom63_lowvol"]["r"]), f"[{num(sc_['mom63_lowvol']['ci95'][0])}, {num(sc_['mom63_lowvol']['ci95'][1])}]", sc_["mom63_lowvol"]["verdict"]],
            ["저변동성 ↔ SPY 상관", num(sc_["lowvol_spy"]["r"]), f"[{num(sc_['lowvol_spy']['ci95'][0])}, {num(sc_['lowvol_spy']['ci95'][1])}]", sc_["lowvol_spy"]["verdict"]],
            ["스코어 랭크상관: 리더 ↔ 중기모멘텀", num(s["score_corr"]["leader_score vs mom63_raw"]["mean"]), f"t={num(s['score_corr']['leader_score vs mom63_raw']['t'])}, p&lt;0.001", "유의(5%)"],
            ["스코어 랭크상관: 리더 ↔ 저변동성", num(s["score_corr"]["leader_score vs lowvol_score"]["mean"]), f"t={num(s['score_corr']['leader_score vs lowvol_score']['t'])}", s["score_corr"]["leader_score vs lowvol_score"]["verdict"]],
            ["스코어 랭크상관: 중기모멘텀 ↔ 저변동성", num(s["score_corr"]["mom63_raw vs lowvol_score"]["mean"]), f"t={num(s['score_corr']['mom63_raw vs lowvol_score']['t'])}", s["score_corr"]["mom63_raw vs lowvol_score"]["verdict"]],
            ["이름 중첩: 핵심∩중기 (월평균)", f"{num(s['overlap']['leader_mom63']['mean_common'])}종 (무작위 기대 {num(s['overlap']['leader_mom63']['expected_random'])}종)", f"월≥5종 {s['overlap']['leader_mom63']['months_ge5']}/{s['overlap']['leader_mom63']['n_months']}개월, 이항 p~0", s["overlap"]["leader_mom63"]["verdict"]],
            ["이름 중첩: 핵심∩저변동 (월평균)", f"{num(s['overlap']['leader_lowvol']['mean_common'])}종 (무작위 기대 {num(s['overlap']['leader_lowvol']['expected_random'])}종)", f"무중첩 {s['overlap']['leader_lowvol']['zero_months']}/{s['overlap']['leader_lowvol']['n_months']}개월, 이항 p=1.1e-7", s["overlap"]["leader_lowvol"]["verdict"]],
            ["이름 중첩: 중기∩저변동 (월평균)", f"{num(s['overlap']['lowvol_mom63']['mean_common'])}종 (무작위 기대 {num(s['overlap']['lowvol_mom63']['expected_random'])}종)", f"무중첩 {s['overlap']['lowvol_mom63']['zero_months']}/{s['overlap']['lowvol_mom63']['n_months']}개월, 이항 p={s['overlap']['lowvol_mom63']['p_binomial']:.0e}", s["overlap"]["lowvol_mom63"]["verdict"]],
        ],
        st, [52 * mm, 40 * mm, 52 * mm, 38 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("슬리브 CAPM 알파: 핵심모멘텀 +45.7%/년 (t=1.68, p=0.10), 중기모멘텀 +46.4%/년 (t=1.74, p=0.09), 저변동성 +0.4%/년 (t=0.05) — "
               "슬리브 개별 알파는 유의하지 않거나 경계 수준. 모멘텀 2슬리브의 중복(상관 0.90, 중첩 4.97종, p~0)과 저변동성의 분리(무중첩 28~30/32개월, p&lt;1e-7)는 "
               "세 경로(수익률·스코어·포트폴리오) 모두에서 통계적으로 확정된다.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>8-4. 레짐 셀 유의성 판정표</b>", st["h2"]))
    rc = s["regime_cells"]
    E.append(table(
        ["레짐 셀", "개월", "월평균 초과", "t값", "p값", "판정"],
        [
            ["추세↑·저변동", str(rc["추세↑·저변동"]["n"]), pct(rc["추세↑·저변동"]["mean_excess_m"]),
             num(rc["추세↑·저변동"]["t"]), num(rc["추세↑·저변동"]["p"]), rc["추세↑·저변동"]["verdict"]],
            ["추세↑·고변동", str(rc["추세↑·고변동"]["n"]), pct(rc["추세↑·고변동"]["mean_excess_m"]),
             num(rc["추세↑·고변동"]["t"]), num(rc["추세↑·고변동"]["p"]), rc["추세↑·고변동"]["verdict"]],
            ["추세↓·고변동 (위기·반등)", str(rc["추세↓·고변동"]["n"]), pct(rc["추세↓·고변동"]["mean_excess_m"]), "-", "-", rc["추세↓·고변동"]["verdict"]],
            ["셀 간 초과 차이 (추세↑·저변동 - 추세↑·고변동, Welch)", "-", pct(s["cell_diff_excess"]["mean_diff"]),
             num(s["cell_diff_excess"]["t_welch"]), num(s["cell_diff_excess"]["p"]), s["cell_diff_excess"]["verdict"]],
            ["내부 레짐: 강세 vs 박스 월수익 차이 (Welch)", "-", pct(s["internal_bull_vs_sideways"]["mean_diff"]),
             num(s["internal_bull_vs_sideways"]["t_welch"]), num(s["internal_bull_vs_sideways"]["p"]), s["internal_bull_vs_sideways"]["verdict"]],
        ],
        st, [56 * mm, 16 * mm, 24 * mm, 16 * mm, 16 * mm, 54 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("추세↑·저변동(엔진)의 초과만 5%에서 유의(t=2.64, p=0.022). 셀 간 초과 차이는 Welch 검정에서 유의하지 않아(t=1.61, p=0.12) "
               "'저변동 셀에서 더 낫다'는 정밀한 주장은 할 수 없다. 위기 셀(3개월)은 기술적 보고에 그친다.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>8-5. 강건성 검정과 종합 판정</b>", st["h2"]))
    pe = s["perturbation"]
    E.append(P(f"파라미터 섭동 27조합이 모두 2024~2026에서 초과수익 양(+) — 무작위라면 각 조합이 양(+)일 확률 1/2이므로 27개가 전부 양(+)일 확률은 "
               f"{pe['p_all_positive_if_p0.5']:.1e} (이항검정, p&lt;0.001). '엣지가 특정 파라미터 조합에서만 나온다'는 가설은 기각된다.", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("<b>종합 판정.</b> ① 사전지정 검정 8개 중 6개가 5% 유의(월 초과 t검정×3, 승률 이항×2, 월수익률 vs 0), 1개 경계(CAPM 알파 vs SPY), 1개 판정 불가(샤프 CI 중첩). "
               "② 탐색적 검정에서 모멘텀 2슬리브의 동질성(상관·스코어·중첩 3경로, p~0)과 저변동성의 독립성(중첩 p&lt;1e-7)이 일관되게 확인. "
               "③ 레짐 조건부로는 추세↑·저변동만 유의하고 셀 간 차이는 미유의. ④ 한계: 31개월 단일 레짐 표본, 다중검정(25개 중 우연 양성 1~2개 가능), "
               "생존 편향(과대평가 방향) — 이 검정 결과는 '이 구간·이 레짐에서'의 결론이다.", st["body"]))
    E.append(PageBreak())
    # ---- 9. bias & overfit ----
    E.append(section("9. 편향·과적합 점검 결과", st))
    bv = m["bias"]["variants"]
    E.append(P("<b>9-1. 민감도 (기준: PIT 유니버스, 익일 시가, 10bp)</b>", st["h2"]))
    E.append(table(
        ["변형", "연환산", "샤프", "MDD", "정보비율", "알파", "베타", "기준 대비"],
        [
            ["기준 (PIT, 익일 시가, 10bp)", pct(bv["pit_nextopen_10bp"]["cagr"]), num(bv["pit_nextopen_10bp"]["sharpe"]),
             pct(bv["pit_nextopen_10bp"]["mdd"]), num(bv["pit_nextopen_10bp"]["info_ratio"]),
             pct(bv["pit_nextopen_10bp"]["alpha"]), num(bv["pit_nextopen_10bp"]["beta"]), "-"],
            ["고정 유니버스 (멤버십 룩어헤드 포함)", pct(bv["fixed_nextopen_10bp"]["cagr"]), num(bv["fixed_nextopen_10bp"]["sharpe"]),
             pct(bv["fixed_nextopen_10bp"]["mdd"]), num(bv["fixed_nextopen_10bp"]["info_ratio"]),
             pct(bv["fixed_nextopen_10bp"]["alpha"]), num(bv["fixed_nextopen_10bp"]["beta"]),
             f"{pct(bv['fixed_nextopen_10bp']['cagr']-bv['pit_nextopen_10bp']['cagr'])}p"],
            ["비용 0bp", pct(bv["pit_cost_0bp"]["cagr"]), num(bv["pit_cost_0bp"]["sharpe"]),
             pct(bv["pit_cost_0bp"]["mdd"]), num(bv["pit_cost_0bp"]["info_ratio"]),
             pct(bv["pit_cost_0bp"]["alpha"]), num(bv["pit_cost_0bp"]["beta"]),
             f"{pct(bv['pit_cost_0bp']['cagr']-bv['pit_nextopen_10bp']['cagr'])}p"],
            ["비용 20bp", pct(bv["pit_cost_20bp"]["cagr"]), num(bv["pit_cost_20bp"]["sharpe"]),
             pct(bv["pit_cost_20bp"]["mdd"]), num(bv["pit_cost_20bp"]["info_ratio"]),
             pct(bv["pit_cost_20bp"]["alpha"]), num(bv["pit_cost_20bp"]["beta"]),
             f"{pct(bv['pit_cost_20bp']['cagr']-bv['pit_nextopen_10bp']['cagr'])}p"],
            ["룩어헤드: 신호일 종가 체결", pct(bv["pit_signal_close"]["cagr"]), num(bv["pit_signal_close"]["sharpe"]),
             pct(bv["pit_signal_close"]["mdd"]), num(bv["pit_signal_close"]["info_ratio"]),
             pct(bv["pit_signal_close"]["alpha"]), num(bv["pit_signal_close"]["beta"]),
             f"{pct(bv['pit_signal_close']['cagr']-bv['pit_nextopen_10bp']['cagr'])}p"],
            ["PIT top 100", pct(bv["pit_topn_100"]["cagr"]), num(bv["pit_topn_100"]["sharpe"]),
             pct(bv["pit_topn_100"]["mdd"]), num(bv["pit_topn_100"]["info_ratio"]),
             pct(bv["pit_topn_100"]["alpha"]), num(bv["pit_topn_100"]["beta"]),
             f"{pct(bv['pit_topn_100']['cagr']-bv['pit_nextopen_10bp']['cagr'])}p"],
            ["PIT top 125", pct(bv["pit_topn_125"]["cagr"]), num(bv["pit_topn_125"]["sharpe"]),
             pct(bv["pit_topn_125"]["mdd"]), num(bv["pit_topn_125"]["info_ratio"]),
             pct(bv["pit_topn_125"]["alpha"]), num(bv["pit_topn_125"]["beta"]),
             f"{pct(bv['pit_topn_125']['cagr']-bv['pit_nextopen_10bp']['cagr'])}p"],
        ],
        st, [46 * mm, 17 * mm, 13 * mm, 15 * mm, 17 * mm, 15 * mm, 13 * mm, 24 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P("룩어헤드 민감도(신호 종가 체결 76.4% &lt; 익일 시가 82.5%)는 NEXT_OPEN 규칙이 결과를 부풀리지 않았음을 보여준다. "
               "모든 변형에서 초과수익의 부호와 레짐 구조는 불변.", st["small"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>9-2. 잔존 편향 — 생존 편향</b>", st["h2"]))
    E.append(P("유니버스가 현재 S&amp;P500 구성 종목 기준이므로 상장폐지·탈락 종목의 가격 이력이 패널에 없다. "
               "이 보고서의 성과는 과대평가 방향의 편향을 포함하며, 데이터 한계상 수준을 제거할 수 없다(방향만 명시). "
               "완화 근거: ① PIT 유니버스 적용으로 멤버십 룩어헤드는 제거했고, ② 유니버스 크기 100/125/150 모두 초과수익 양(+)으로 부호는 견고, "
               "③ 최근 구간(2025-02~2026-06)의 높은 성과는 레짐의 산물로 해석(동결 문서 §9와 동일).", st["body"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>9-3. 파라미터 섭동 그리드 (과적합 여부)</b>", st["h2"]))
    pr = m["overfit"]["perturbation"]
    g = pd.DataFrame(pr["grid"])
    fz = g[g["frozen"]].iloc[0]
    q = g["cagr_win"].quantile([0, 0.25, 0.5, 0.75, 1.0])
    qs = g["sharpe_win"].quantile([0.25, 0.5, 0.75])
    E.append(table(
        ["통계 (27조합)", "2024~2026 연환산", "2024~2026 샤프", "전체기간(2018~) 연환산"],
        [
            ["최소", pct(q[0.0]), "-", pct(g["cagr_full"].min())],
            ["25분위", pct(q[0.25]), num(qs[0.25]), pct(g["cagr_full"].quantile(0.25))],
            ["중앙값", pct(q[0.5]), num(qs[0.5]), pct(g["cagr_full"].median())],
            ["75분위", pct(q[0.75]), num(qs[0.75]), pct(g["cagr_full"].quantile(0.75))],
            ["최대", pct(q[1.0]), "-", pct(g["cagr_full"].max())],
            ["동결점 (10/10/12)", pct(fz["cagr_win"]), num(fz["sharpe_win"]), pct(fz["cagr_full"])],
        ],
        st, [34 * mm, 34 * mm, 30 * mm, 40 * mm], left0=True,
    ))
    E.append(Spacer(1, 1.5 * mm))
    E.append(P(f"동결점은 27조합 중 2024~2026 연환산 기준 상위 {pr['percentile_rank_frozen']['cagr_win']*100:.0f}% 지점 — "
               f"최고점이 아니라 고원의 중앙 부근. 27/27 조합이 모두 초과수익 양(+)이며, 조합 간 연환산 범위는 "
               f"{pct(g['cagr_win'].min())}~{pct(g['cagr_win'].max())}. 즉 이 전략의 성과는 종목 수 파라미터의 미세한 선택에 좌우되지 않는다.", st["body"]))
    E.append(Spacer(1, 1.5 * mm))
    E.append(Image(str(charts["grid"]), width=W, height=W * 0.38))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>9-4. 구간 분할 해석 (과적합 관점)</b>", st["h2"]))
    ws = m["windows"]
    E.append(table(
        ["구간", "성격", "전략", "SPY", "연환산 초과", "해석"],
        [
            ["2024-01~2026-06 (30개월)", "동결 연구의 공식 OOS",
             pct(ws["research_window_2024_2026_06"]["cagr"]), pct(ws["research_window_2024_2026_06"]["bench_total"], 1),
             pct(ws["research_window_2024_2026_06"]["ann_excess"]),
             "연구 설계자가 본 구간 — '새 증거'가 아니라 재현"],
            ["2026-07 (1개월)", "연구 데이터 마감(2026-06-29) 직후 첫 신호",
             pct(ws["first_signal_after_research_2026_07"]["total"]), pct(ws["first_signal_after_research_2026_07"]["bench_total"], 1),
             pct(ws["first_signal_after_research_2026_07"]["ann_excess"]),
             "-24.8% — 반도체 집중 리스크의 실현"],
            ["2026-08 부분월 (10거래일)", "동결(2026-07-19) 이후 첫 신호",
             pct(ws["post_freeze_2026_08_partial"]["strat_ret"]), pct(ws["post_freeze_2026_08_partial"]["spy_ret"], 1),
             pct(ws["post_freeze_2026_08_partial"]["excess_spy"]),
             "진정한 표본 외 — 아직 1건, 판정 불가"],
        ],
        st, [36 * mm, 34 * mm, 16 * mm, 16 * mm, 20 * mm, 60 * mm], left0=True,
    ))
    E.append(PageBreak())

    # ---- 10. conclusion ----
    E.append(section("10. 결론과 한계", st))
    E.append(P("<b>10-1. 결론</b>", st["h2"]))
    E.append(P("① 2024-01~2026-07에서 동결 전략은 누적 +371%(연환산 82.5%, SPY +62.8%)를 냈고, 월 초과 +4.0%p(t=2.49, "
               "부트스트랩 P&gt;0 = 99.3%)는 통계적으로 유의하다. ② 초과의 약 77%(월평균 기준)는 종목 선택에서, 23%는 유니버스 틸트에서 나왔다. "
               "③ 레짐 조건부로 보면 추세↑·저변동(연 +175.9%)이 엔진이고, 위기·반등 구간은 방어 조정이 작동했으며, 박스장(-12.2%/년)이 유일한 취약점이다. "
               "④ 파라미터 27조합 섭동에서 성과는 고원 — 선택 과적합의 증거가 없다. ⑤ 그러나 2026-07 -24.8%와 최대 낙폭 -32.2%(SPY -18.8%의 1.7배)는 "
               "섹터 집중(평균 44.5%, 최고 71.4%)이 실재하는 리스크임을 보여준다.", st["body"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>10-2. 권고</b>", st["h2"]))
    E.append(P("① 섹터 40% 상한을 best-effort가 아닌 실제 게이트로 승격(7월 사건의 유일한 수정 가능 지점). "
               "② 추세↓·고변동(위기) 셀과 박스장에서의 거동을 라이브로 모니터링 — 방어 조정의 실효성이 이 구간에 달려 있음. "
               "③ '전략 - EW 동일유니버스'를 운영 KPI에 추가하여 선택 엣지의 지속성 추적. "
               "④ 동결 문서의 분기 1회 재검증 규율을 2026-10월까지 수행.", st["body"]))
    E.append(Spacer(1, 2 * mm))
    E.append(P("<b>10-3. 한계</b>", st["h2"]))
    E.append(P("① 생존 편향(상장폐지 종목 부재) — 과대평가 방향, 수준 미제거. ② 본 구간 대부분은 동결 연구의 OOS 재현이며, "
               "동결 후 표본 외는 10거래일 1건뿐 — '미래에도 그럴 것'이라는 증거가 아니다. ③ 월간 표본 31개로 엣지 크기의 신뢰구간이 넓고(§8), "
               "다중검정으로 우연 양성 가능. ④ 분수주·시장 충격·슬리피지 등 실거래 마찰 미반영(비용 민감도로 완충 확인). ⑤ 레짐 셀 중 추세↓·저변동은 표본 부재.", st["body"]))
    E.append(Spacer(1, 4 * mm))
    E.append(P("산출물: results/strict_report/ (metrics.json, monthly_table.csv, holdings.csv, equity.csv, perturbation.csv, factor_corr.json, charts/). "
               "재현 스크립트: research/strict_edge_report.py (분석), research/make_strict_edge_pdf.py (본 PDF). "
               "기본 데이터·정책: ops/ (동결 상수), data/us/*.parquet.", st["small"]))

    doc.build(E, onFirstPage=footer, onLaterPages=footer)
    print("PDF ->", OUT)


if __name__ == "__main__":
    build()
