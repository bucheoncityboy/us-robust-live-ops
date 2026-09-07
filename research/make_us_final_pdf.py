"""미국 시장 강건 퀀트전략 최종 통합 보고서 (전략 소개 + 팩터연구 + 엄격 백테스트)"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

_fp = Path(r"C:\Windows\Fonts\malgun.ttf")
if _fp.exists():
    font_manager.fontManager.addfont(str(_fp))
    plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
ROB = ROOT / "results" / "us_robust"
LAB = ROOT / "results" / "us_factor_lab"
CHART = ROB / "charts_final"
OUT = ROB / "미국시장_강건퀀트전략_최종통합보고서.pdf"

NAVY = colors.HexColor("#0F2744")
BLUE = colors.HexColor("#1F4E79")
ACCENT = colors.HexColor("#C45C26")
LIGHT = colors.HexColor("#F4F7FB")
GRID = colors.HexColor("#D0D7E2")
GRAY = colors.HexColor("#5B6573")
GREEN = colors.HexColor("#1B7F4C")


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
    s["toc"] = ParagraphStyle("toc", fontName=font, fontSize=8.3, leading=11.5, textColor=colors.HexColor("#334155"))
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


def table(headers, rows, st, widths, left0=True):
    head = [P(h, st["th"]) for h in headers]
    body = []
    for r in rows:
        line = []
        for i, c in enumerate(r):
            style = st["td_left"] if (left0 and i == 0) else st["td"]
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
    t.setStyle(TableStyle(cmds))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(13.5 * mm, 10 * mm, A4[0] - 13.5 * mm, 10 * mm)
    canvas.setFont("KR", 7.0)
    canvas.setFillColor(GRAY)
    canvas.drawString(13.5 * mm, 6 * mm, "US Robust Quant Final · Research Only · Not Investment Advice")
    canvas.drawRightString(A4[0] - 13.5 * mm, 6 * mm, f"{doc.page}")
    canvas.restoreState()


def make_charts(eq: pd.DataFrame, rob: Dict, lab: Dict) -> Dict[str, Path]:
    CHART.mkdir(parents=True, exist_ok=True)
    out = {}
    rec = (rob.get("recommended") or {}).get("name")
    ranking = rob.get("ranking") or []
    wf = (rob.get("recommended") or {}).get("walk_forward") or []
    gates = (rob.get("recommended") or {}).get("gates") or {}
    single_rank = lab.get("single_ranking") or []
    corr = lab.get("factor_corr") or {}

    # 1 architecture final
    fig, ax = plt.subplots(figsize=(10.5, 4.0), dpi=160)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5.2)
    ax.axis("off")
    boxes = [
        (0.3, 3.3, 2.6, 1.35, "PASS 팩터\nLeader·Mom63\nNearHigh·RelMom", "#1F4E79"),
        (3.2, 3.3, 2.6, 1.35, "폐기\nAccumulDiv\n재무 코어", "#B42318"),
        (6.1, 3.3, 2.6, 1.35, "강건 조합\n사전등록 5안", "#C45C26"),
        (9.0, 3.3, 2.6, 1.35, "최종 고정\nL60/M63/LV20", "#1B7F4C"),
        (0.8, 0.55, 10.3, 2.0,
         "Leader 60%  (필터 모멘텀 코어)\n"
         "Mom63 20%   (3개월 모멘텀 위성, 비중 캡)\n"
         "LowVol 20%  (저상관 방어)\n"
         "Next-Open · 월1회 · 15% cap · 10/20bp · Gate10 · 블록 부트스트랩",
         "#334155"),
    ]
    for x, y, w, h, txt, c in boxes:
        ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=c, edgecolor="white", lw=1.1, alpha=0.93))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", color="white",
                fontsize=9.2, fontweight="bold")
    ax.set_title("미국 강건 퀀트전략 최종 구조", fontsize=12, pad=6)
    fig.tight_layout()
    p = CHART / "final_arch.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close()
    out["arch"] = p

    # 2 single factor rob
    if single_rank:
        fig, ax = plt.subplots(figsize=(10.2, 3.5), dpi=160)
        names = [r["factor"] for r in single_rank]
        scores = [r["score"] for r in single_rank]
        cols = ["#1B7F4C" if (r.get("gate") == "PASS") else ("#F9A825" if r.get("gate") == "WARN" else "#C62828")
                for r in single_rank]
        ax.barh(names[::-1], scores[::-1], color=cols[::-1])
        ax.axvline(0, color="#555", lw=0.8)
        ax.set_xlabel("Robustness score")
        ax.set_title("단일 팩터 강건성 (초록=PASS / 노랑=WARN / 빨강=FAIL)")
        ax.grid(axis="x", alpha=0.3)
        fig.tight_layout()
        p = CHART / "single_rob.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["single_rob"] = p

    # 3 equity
    fig, ax = plt.subplots(figsize=(10.3, 3.8), dpi=160)
    prefer = ["Bench_SPY", rec, "Aggressive_L100", "Robust_L70_LV30", "Robust_L50_RM_LV20"]
    cmap = {
        "Bench_SPY": "#8A94A6", rec: "#C45C26", "Aggressive_L100": "#E45756",
        "Robust_L70_LV30": "#1F4E79", "Robust_L50_RM_LV20": "#6A1B9A",
        "Robust_L55_NH_LV25": "#2E7D32", "Robust_L60_M63_LV20": "#C45C26",
    }
    for c in prefer:
        if c not in eq.columns or not c:
            continue
        s = eq[c].dropna()
        if s.empty:
            continue
        n = s / s.iloc[0] * 100
        lw = 2.3 if c in (rec, "Bench_SPY") else 1.1
        lab = c.replace("Robust_", "R_").replace("Aggressive_", "A_")
        ax.plot(n.index, n.values, label=lab, color=cmap.get(c), lw=lw)
    ax.legend(loc="upper left", fontsize=7.5, ncol=2)
    ax.set_title("자산곡선 (Next-Open, 비용 10bp)")
    ax.set_ylabel("성장지수 (100=시작)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = CHART / "equity.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close()
    out["equity"] = p

    # 4 dd
    if rec and rec in eq.columns:
        s = eq[rec].dropna()
        dd = s / s.cummax() - 1
        fig, ax = plt.subplots(figsize=(10.3, 2.7), dpi=160)
        ax.fill_between(dd.index, dd.values * 100, 0, color="#C62828", alpha=0.55)
        ax.set_title(f"낙폭 — {rec}")
        ax.set_ylabel("%")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        p = CHART / "dd.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["dd"] = p

    # 5 compare variants
    if ranking:
        fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.3), dpi=160)
        names = [r["name"].replace("Robust_", "R_").replace("Aggressive_", "A_") for r in ranking]
        axes[0].barh(names[::-1], [r["score"] for r in ranking][::-1], color="#1F4E79")
        axes[0].set_title("강건성")
        axes[1].barh(names[::-1], [r.get("sharpe") or 0 for r in ranking][::-1], color="#C45C26")
        axes[1].set_title("Sharpe")
        axes[2].barh(names[::-1], [(r.get("mdd") or 0) * 100 for r in ranking][::-1], color="#6A1B9A")
        axes[2].set_title("MaxDD %")
        for ax in axes:
            ax.grid(axis="x", alpha=0.3)
        fig.suptitle("사전등록 강건 변형 비교", fontsize=11)
        fig.tight_layout()
        p = CHART / "compare.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["compare"] = p

    # 6 wf
    if wf:
        fig, ax = plt.subplots(figsize=(9.4, 3.0), dpi=160)
        xs = [f"F{f['fold']}" for f in wf]
        ys = [(f.get("ann_ex") or 0) * 100 for f in wf]
        cols = ["#1B7F4C" if y > 0 else "#C62828" for y in ys]
        ax.bar(xs, ys, color=cols)
        ax.axhline(0, color="#333", lw=0.8)
        ax.set_ylabel("연율 초과 %p")
        ax.set_title(f"Walk-Forward 초과수익 — {rec}")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        p = CHART / "wf.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["wf"] = p

    # 7 gates
    checks = gates.get("checks") or []
    if checks:
        fig, ax = plt.subplots(figsize=(9.4, 3.2), dpi=160)
        names = [c["name"].replace("G", "") for c in checks]
        vals = [1 if c["pass"] else 0 for c in checks]
        cols = ["#1B7F4C" if v else "#C62828" for v in vals]
        ax.barh(names[::-1], vals[::-1], color=cols[::-1])
        ax.set_xlim(0, 1.2)
        ax.set_title(f"Gate {gates.get('status')} {gates.get('n_pass')}/{gates.get('n_total')}")
        fig.tight_layout()
        p = CHART / "gates.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["gates"] = p

    # 8 factor corr among used + top
    if corr:
        cdf = pd.DataFrame(corr)
        keep = [x for x in ["Leader", "Mom63", "LowVol", "Mom12", "RelMom", "NearHigh", "AccumulDiv", "ValueMom"]
                if x in cdf.columns]
        if len(keep) >= 3:
            sub = cdf.loc[keep, keep]
            fig, ax = plt.subplots(figsize=(6.6, 5.3), dpi=160)
            im = ax.imshow(sub.values, cmap="RdBu_r", vmin=-1, vmax=1)
            ax.set_xticks(range(len(keep)))
            ax.set_yticks(range(len(keep)))
            ax.set_xticklabels(keep, rotation=35, ha="right", fontsize=8)
            ax.set_yticklabels(keep, fontsize=8)
            for i in range(len(keep)):
                for j in range(len(keep)):
                    ax.text(j, i, f"{sub.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
            fig.colorbar(im, ax=ax, fraction=0.046)
            ax.set_title("팩터 월간 수익률 상관 (겹침)")
            fig.tight_layout()
            p = CHART / "corr.png"
            fig.savefig(p, bbox_inches="tight")
            plt.close()
            out["corr"] = p

    # 9 metrics board
    fig, axes = plt.subplots(1, 4, figsize=(10.5, 2.8), dpi=160)
    rs = (rob.get("recommended") or {}).get("stats") or {}
    bench = rob.get("bench") or {}
    labs = ["CAGR", "Sharpe", "IR", "MaxDD"]
    port = [(rs.get("cagr") or 0) * 100, rs.get("sharpe") or 0, rs.get("info_ratio") or 0, (rs.get("mdd") or 0) * 100]
    ben = [(bench.get("cagr") or 0) * 100, bench.get("sharpe") or 0, 0.0, (bench.get("mdd") or 0) * 100]
    for ax, lab, pv, bv in zip(axes, labs, port, ben):
        ax.bar([0, 1], [pv, bv], color=["#C45C26", "#8A94A6"])
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["전략", "SPY"], fontsize=8)
        ax.set_title(lab)
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle("권고 전략 vs SPY", fontsize=11)
    fig.tight_layout()
    p = CHART / "kpi.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close()
    out["kpi"] = p

    return out


def build():
    font, fb = fonts()
    st = styles(font, fb)

    rob = json.loads((ROB / "metrics.json").read_text(encoding="utf-8"))
    lab = {}
    if (LAB / "metrics.json").exists():
        lab = json.loads((LAB / "metrics.json").read_text(encoding="utf-8"))

    eq = pd.read_csv(ROB / "equity_curves.csv", index_col=0, parse_dates=True)
    rec_b = rob.get("recommended") or {}
    rec = rec_b.get("name")
    rs = rec_b.get("stats") or {}
    gates = rec_b.get("gates") or {}
    boot = rec_b.get("bootstrap") or {}
    isoos = rec_b.get("isoos") or {}
    wf = rec_b.get("walk_forward") or []
    rob_score = rec_b.get("robustness") or {}
    row = rec_b.get("row") or {}
    weights = row.get("weights") or {"Leader": 0.6, "Mom63": 0.2, "LowVol": 0.2}
    bench = rob.get("bench") or {}
    dr = rob.get("data_range") or {}
    ranking = rob.get("ranking") or []
    latest = rec_b.get("latest_holdings") or {}
    tail = rec_b.get("holdings_tail") or []
    stress = (rec_b.get("stress") or {}).get("stats") or {}
    single_rank = lab.get("single_ranking") or []
    sleeve_corr = rob.get("sleeve_corr") or {}

    wtxt = " / ".join(f"{k} {int(round(v * 100))}%" for k, v in weights.items())
    paths = make_charts(eq, rob, lab)

    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=13 * mm, rightMargin=13 * mm, topMargin=10 * mm, bottomMargin=13 * mm,
        title="미국 시장 강건 퀀트전략 최종통합보고서", author="RLM Research",
    )
    story: List = []

    # ========== COVER ==========
    banner = Table([
        [P("RLM Quantitative Research  ·  US ROBUST QUANT  ·  FINAL  ·  2026-07-19", st["cover_sub"])],
        [P("미국 시장 강건 퀀트전략<br/>최종 통합 보고서", st["cover_title"])],
        [P("전략 소개 · 팩터 탐색 · 겹침 분석 · 엄격 백테스트 · 운용 SOP · 한계", st["cover_sub"])],
    ], colWidths=[A4[0] - 26 * mm])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 11),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 1), (-1, 1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
    ]))
    story.append(banner)
    story.append(Spacer(1, 6))

    story.append(P(
        "<b>최종 한 줄</b><br/>"
        "한국식 외국인 수급 다이버전스는 미국에 이식 실패(AccumulDiv 기각). "
        "사전등록 팩터 실험 후 유효 축은 <b>모멘텀 코어 + 저변동 위성</b>이다. "
        f"최종 고정 전략: <b>{rec}</b> = <b>{wtxt}</b>. "
        f"CAGR {pct(rs.get('cagr'))} · Sharpe {num(rs.get('sharpe'))} · IR {num(rs.get('info_ratio'))} · "
        f"MaxDD {pct(rs.get('mdd'))} · 시장β {num(rs.get('beta'))} · "
        f"Gate <b>{gates.get('status')}</b> {gates.get('n_pass')}/{gates.get('n_total')}. "
        "목표함수는 원시 CAGR이 아니라 강건성(IR·WF중앙초과·블록부트·폴드집중 페널티)이다. "
        "절대 CAGR 과신 금지.",
        st["quote"],
    ))
    story.append(Spacer(1, 4))

    meta = [
        ["문서 성격", "전략 소개 + 팩터연구 요약 + 강건 백테스트 최종본 (투자 권유 아님)"],
        ["최종 전략", f"{rec} · {wtxt}"],
        ["검증 기간", f"{dr.get('signals')} · 신호 {dr.get('n_signals')}회 · {rs.get('years')}년"],
        ["유니버스", f"S&P 유동성 상위 {dr.get('n_codes')} (현재 구성·생존편향 존재)"],
        ["체결·비용", "월말 Close 신호 → 다음 Open / 10bp 기본 · 20bp 스트레스"],
        ["검증 체계", "IS/OOS(2023-12) · WF5 · 이동블록 부트스트랩 · Gate 10항"],
        ["폐기", "AccumulDiv · 재무 코어 · Mom12+RelMom 이중 적재"],
        ["한국과의 관계", "골격(월1회·Next-Open·상한) 공유 / 수급 20% 축은 미국 미채택"],
    ]
    mt = Table([[P(a, st["td_left"]), P(b, st["td_left"])] for a, b in meta], colWidths=[32 * mm, 150 * mm])
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 2.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(mt)
    story.append(Spacer(1, 3))
    story.append(P("<b>목차</b>", st["h2"]))
    for t in [
        "1. Executive Decision Summary",
        "2. 전략 소개 (왜 이 구조인가)",
        "3. 팩터 정의 · 채택/폐기",
        "4. 팩터 겹침(상관·종목 중복)",
        "5. 사전등록 변형 비교 · 최종 선택",
        "6. 엄격 백테스트 성과",
        "7. IS/OOS · Walk-Forward · Bootstrap · Gate",
        "8. 최근 포트폴리오 · 운용 SOP",
        "9. 결론 · 한계 · 면책",
    ]:
        story.append(P(t, st["toc"]))
    if "arch" in paths:
        story.append(Spacer(1, 2))
        story.append(Image(str(paths["arch"]), width=176 * mm, height=67 * mm))
        story.append(P("그림 1. 최종 전략 구조", st["caption"]))
    story.append(PageBreak())

    # ========== 1 Exec ==========
    story.append(section("1. Executive Decision Summary", st))
    items = [
        ("최종", "L60/M63/LV20"),
        ("CAGR", pct(rs.get("cagr"))),
        ("Sharpe", num(rs.get("sharpe"))),
        ("IR", num(rs.get("info_ratio"))),
        ("MaxDD", pct(rs.get("mdd"))),
        ("Gate", f"{gates.get('status')} {gates.get('n_pass')}/{gates.get('n_total')}"),
    ]
    cells = [Table([[P(a, st["kpi"])], [P(b, st["kpi_val"])]], colWidths=[28 * mm]) for a, b in items]
    k = Table([cells[:3], cells[3:]], colWidths=[58 * mm] * 3)
    k.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.45, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.28, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(k)
    story.append(Spacer(1, 3))
    if "kpi" in paths:
        story.append(Image(str(paths["kpi"]), width=176 * mm, height=47 * mm))
        story.append(P("그림 2. 권고 전략 vs SPY 핵심 지표", st["caption"]))

    story.append(table(
        ["질문", "결론"],
        [
            ["무엇을 사나?", "Leader(필터 모멘텀) 주력 + Mom63(빠른 모멘텀 위성) + LowVol(방어)"],
            ["비중?", wtxt + " · 슬리브 내 동일가중 · 종목 15% 캡"],
            ["유효 차원?", "겉보기 3팩터, 실질 2차원(모멘텀 묶음 + 저볼) — Leader↔Mom63 상관~0.9"],
            ["시장 겹침?", f"포트 β≈{num(rs.get('beta'))} (거의 시장 1배) + 알파 {pct(rs.get('alpha'))}"],
            ["폐기?", "AccumulDiv(수급 흉내), 재무 코어, Mom12+RelMom 이중 적재"],
            ["리밸·체결?", "월 1회 / 월말 Close 신호 → 다음 Open (look-ahead 차단)"],
            ["비용?", f"10bp 기본 / 20bp 스트레스 CAGR {pct(stress.get('cagr'))} Gate PASS"],
            ["검증?", f"Gate {gates.get('status')} · Bootstrap P(excess>0)={boot.get('prob_positive')} · WF 양수 폴드 {pct(rob_score.get('wf_pos_share'))}"],
        ],
        st, [32 * mm, 150 * mm],
    ))

    # ========== 2 intro ==========
    story.append(section("2. 전략 소개 (왜 이 구조인가)", st))
    story.append(P(
        "한국 운용 하이브리드는 Leader 55 / ValueMom 25 / Foreign Divergence 20이다. "
        "미국에는 일별 외국인 순매수 라벨이 없어 거래대금 다이버전스로 대체했으나 "
        "성과·IR·Gate에서 실패했다. 미국 대형 유동성 유니버스에서는 "
        "<b>가격 모멘텀이 엔진</b>이고, 재무·가짜 수급은 위성 코어로 부적합했다.",
        st["body"],
    ))
    story.append(P("<b>설계 원칙</b>", st["h2"]))
    story.append(table(
        ["원칙", "내용"],
        [
            ["1. PASS only", "단독 Gate PASS 가격 팩터만 알파 엔진 후보"],
            ["2. FAIL drop", "AccumulDiv 폐기, 재무 코어 미사용(표본 짧고 IR 약함)"],
            ["3. No double 12-1", "Mom12≈RelMom(상관~1) → 순수 12-1 슬리브 최대 1개"],
            ["4. Leader core", "필터 모멘텀을 주력. Mom63 올인은 고MDD로 비권고 → 20% 캡"],
            ["5. LowVol satellite", "단독 IR 음수여도 모멘텀과 상관~0.35~0.4 → 진짜 분산축"],
            ["6. Objective", "robustness = IR+Sharpe+WF중앙+부트 − 폴드집중 − MDD 페널티"],
            ["7. Small menu", "사전등록 소수 변형만 평가 (무한 그리드 탐색 금지)"],
        ],
        st, [34 * mm, 148 * mm],
    ))
    story.append(P(
        "잔존 편향: 현재 S&amp;P 멤버십 생존편향, yfinance 품질, 섹터 40% 캡 미적용, "
        "최근 메가캡·모멘텀 레짐 의존. CAGR 48~50%는 운용 목표가 아니라 연구 상한선으로 해석한다.",
        st["warn"],
    ))
    story.append(PageBreak())

    # ========== 3 factors ==========
    story.append(section("3. 팩터 정의 · 채택/폐기", st))
    story.append(P("<b>최종 채택 3축</b>", st["h2"]))
    story.append(table(
        ["팩터", "비중", "정의", "역할"],
        [
            ["Leader", "60%", "12-1 모멘텀+신고가근접+거래확인 복합점수 / mom&gt;0·near≥0.8 / 약세다이버전스 제외", "코어 엔진"],
            ["Mom63", "20%", "63거래일 수익률 상위 (빠른 중기 모멘텀)", "가속 위성(캡)"],
            ["LowVol", "20%", "60일 변동성 하위 · 급락 제외", "방어·저상관"],
        ],
        st, [22 * mm, 14 * mm, 100 * mm, 28 * mm],
    ))
    story.append(P("<b>연구 후보 · 상태</b>", st["h2"]))
    if single_rank:
        srows = []
        for r in single_rank:
            status = "채택" if r["factor"] in ("Leader", "Mom63") else (
                "위성채택" if r["factor"] == "LowVol" else (
                    "PASS·미채택" if r.get("gate") == "PASS" else r.get("gate", "")
                )
            )
            if r["factor"] == "AccumulDiv":
                status = "폐기"
            if r["factor"] in ("Value", "Quality", "ValueMom", "EP", "ROE", "ST_Reversal"):
                status = "미채택"
            srows.append([
                r["factor"], pct(r.get("cagr")), num(r.get("sharpe")), num(r.get("ir")),
                pct(r.get("mdd")), num(r.get("score"), 2),
                f"{r.get('gate')}", status,
            ])
        story.append(table(
            ["팩터", "CAGR", "Sh", "IR", "MDD", "강건성", "Gate", "최종"],
            srows,
            st, [24 * mm, 16 * mm, 12 * mm, 14 * mm, 16 * mm, 16 * mm, 18 * mm, 22 * mm],
        ))
    if "single_rob" in paths:
        story.append(Image(str(paths["single_rob"]), width=172 * mm, height=58 * mm))
        story.append(P("그림 3. 단일 팩터 강건성 순위", st["caption"]))

    story.append(P(
        "Mom12·RelMom·NearHigh는 PASS이나 Leader와 모멘텀 패밀리로 중복된다. "
        "최종안은 Leader를 코어로 두고 Mom63만 소비중 틸트, LowVol로 이질 축을 확보한다.",
        st["body"],
    ))

    # ========== 4 overlap ==========
    story.append(section("4. 팩터 겹침 (상관·종목 중복)", st))
    story.append(P(
        "여기서 ‘베타/겹침’은 시장 β가 아니라 <b>팩터끼리 얼마나 같은 움직임을 보이느냐</b>다. "
        "3팩터라고 부르지만 유효 차원은 사실상 2개다.",
        st["body"],
    ))
    story.append(table(
        ["쌍", "일간 상관", "R²(공유)", "고유(1−R²)", "월평균 종목교집합", "판정"],
        [
            ["Leader ↔ Mom63", "0.90", "80%", "20%", "~3.9 / Jaccard 0.28", "같은 모멘텀 가족"],
            ["Leader ↔ LowVol", "0.38", "14%", "86%", "~0.5 / Jaccard 0.03", "거의 독립"],
            ["Mom63 ↔ LowVol", "0.36", "13%", "87%", "~0.3 / Jaccard 0.02", "거의 독립"],
        ],
        st, [32 * mm, 22 * mm, 22 * mm, 24 * mm, 42 * mm, 32 * mm],
    ))
    if "corr" in paths:
        story.append(Image(str(paths["corr"]), width=115 * mm, height=92 * mm))
        story.append(P("그림 4. 팩터 월간 수익률 상관 히트맵", st["caption"]))
    story.append(P(
        "포트 가중치 중 멀티 슬리브 중복 종목 비중 평균 ~42%(대부분 모멘텀 쪽). "
        "위기 시 Leader+Mom63이 같이 움직이므로 완충은 LowVol 20%에 의존한다. "
        f"시장 β(참고): 포트 {num(rs.get('beta'))} · Leader~1.06 · Mom63~1.21 · LowVol~0.59.",
        st["body"],
    ))
    if sleeve_corr:
        sc_rows = []
        keys = list(sleeve_corr.keys())
        for a in keys:
            sc_rows.append([a] + [num(sleeve_corr.get(a, {}).get(b), 2) for b in keys])
        story.append(P("<b>최종 슬리브 월간 상관 (강건 런)</b>", st["h2"]))
        story.append(table(["\\"] + keys, sc_rows, st, [28 * mm] + [28 * mm] * len(keys)))
    story.append(PageBreak())

    # ========== 5 variants ==========
    story.append(section("5. 사전등록 변형 비교 · 최종 선택", st))
    rrows = []
    for r in ranking:
        rrows.append([
            r["name"].replace("Robust_", "R_").replace("Aggressive_", "A_"),
            " / ".join(f"{k[:1]}{int(round(v*100))}" for k, v in (r.get("weights") or {}).items()),
            pct(r.get("cagr")), num(r.get("sharpe")), num(r.get("ir")),
            pct(r.get("mdd")), num(r.get("med_wf_excess"), 3),
            num(r.get("fold_concentration"), 2), num(r.get("score"), 3),
            str(r.get("gate")),
        ])
    story.append(table(
        ["전략", "비중", "CAGR", "Sh", "IR", "MDD", "WF중앙", "집중", "강건성", "Gate"],
        rrows,
        st, [34 * mm, 26 * mm, 15 * mm, 12 * mm, 12 * mm, 15 * mm, 16 * mm, 12 * mm, 16 * mm, 14 * mm],
    ))
    if "compare" in paths:
        story.append(Image(str(paths["compare"]), width=175 * mm, height=55 * mm))
        story.append(P("그림 5. 변형별 강건성 / Sharpe / MaxDD", st["caption"]))
    story.append(P(
        f"선택 규칙: robust 패밀리 · 강건성 최대 · hard FAIL 제외. "
        f"결과 <b>{rec}</b> 채택. "
        "L50/RM/LV20(랩 1위)은 Leader–RelMom 중복이 커서 L60/M63/LV20에 밀림. "
        "L70/LV30·L55/NH/LV25는 낙폭은 더 작지만 강건성·IR 열위.",
        st["body"],
    ))

    # ========== 6 performance ==========
    story.append(section("6. 엄격 백테스트 성과", st))
    if "equity" in paths:
        story.append(Image(str(paths["equity"]), width=175 * mm, height=64 * mm))
        story.append(P("그림 6. 자산곡선", st["caption"]))
    if "dd" in paths:
        story.append(Image(str(paths["dd"]), width=175 * mm, height=46 * mm))
        story.append(P("그림 7. 낙폭", st["caption"]))

    l100 = next((r for r in ranking if r["name"] == "Aggressive_L100"), {})
    story.append(table(
        ["지표", "최종 전략", "SPY", "20bp 스트레스", "순수 Leader"],
        [
            ["CAGR", pct(rs.get("cagr")), pct(bench.get("cagr")), pct(stress.get("cagr")), pct(l100.get("cagr"))],
            ["Sharpe", num(rs.get("sharpe")), num(bench.get("sharpe")), num(stress.get("sharpe")), num(l100.get("sharpe"))],
            ["IR", num(rs.get("info_ratio")), "-", num((rec_b.get("stress") or {}).get("stats", {}).get("info_ratio")), num(l100.get("ir"))],
            ["Alpha", pct(rs.get("alpha")), pct(bench.get("alpha")), pct(stress.get("alpha")), "-"],
            ["MaxDD", pct(rs.get("mdd")), pct(bench.get("mdd")), pct(stress.get("mdd")), pct(l100.get("mdd"))],
            ["Vol", pct(rs.get("vol")), pct(bench.get("vol")), pct(stress.get("vol")), pct(l100.get("vol"))],
            ["Beta", num(rs.get("beta")), "1.00", num(stress.get("beta")), num(l100.get("beta") if "beta" in l100 else None)],
            ["강건성", num(rob_score.get("score"), 3), "-",
             num(((rec_b.get("stress") or {}).get("robustness") or {}).get("score"), 3),
             num(l100.get("score"), 3)],
            ["월승률", pct(rs.get("win_month")), pct(bench.get("win_month")), pct(stress.get("win_month")), pct(l100.get("win_month"))],
        ],
        st, [28 * mm, 30 * mm, 28 * mm, 34 * mm, 32 * mm],
    ))
    story.append(P(
        f"기간 {rs.get('start')}~{rs.get('end')} ({rs.get('years')}년). "
        f"총수익 {pct(rs.get('total_return'), 0)} · 최종자산(시드 대비) 배수로 해석. "
        "순수 Leader 대비 CAGR은 소폭 낮아도 Sharpe·IR·MDD·강건성이 개선되어 강건 북으로 채택.",
        st["body"],
    ))
    story.append(PageBreak())

    # ========== 7 diagnostics ==========
    story.append(section("7. IS/OOS · Walk-Forward · Bootstrap · Gate", st))
    story.append(P("<b>In-Sample / Out-of-Sample</b>", st["h2"]))
    irows = []
    for key in ["IS", "OOS"]:
        r = isoos.get(key) or {}
        if not r:
            continue
        irows.append([
            key, f"{r.get('start')}~{r.get('end')}", pct(r.get("cagr")), num(r.get("sharpe")),
            pct(r.get("mdd")), pct(r.get("alpha")), num(r.get("info_ratio")),
        ])
    if irows:
        story.append(table(
            ["구간", "기간", "CAGR", "Sharpe", "MDD", "Alpha", "IR"],
            irows, st, [16 * mm, 48 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 16 * mm],
        ))
    story.append(P(
        "OOS가 IS를 크게 웃돌면 일반화 성공이 아니라 최근 모멘텀 레짐 행운일 수 있다. "
        "IR 부호·WF 중앙값·폴드 집중과 함께 해석한다.",
        st["body"],
    ))

    story.append(P("<b>Walk-Forward (5 folds)</b>", st["h2"]))
    if wf:
        wrows = [[
            str(f.get("fold")), f"{f.get('start')}~{f.get('end')}",
            pct(f.get("cagr")), pct(f.get("bench_cagr")), pct(f.get("ann_ex")),
            num(f.get("sharpe")), pct(f.get("mdd")), num(f.get("info_ratio")),
        ] for f in wf]
        story.append(table(
            ["Fold", "기간", "CAGR", "Bench", "초과", "Sh", "MDD", "IR"],
            wrows, st, [14 * mm, 46 * mm, 16 * mm, 16 * mm, 16 * mm, 14 * mm, 16 * mm, 14 * mm],
        ))
    if "wf" in paths:
        story.append(Image(str(paths["wf"]), width=165 * mm, height=52 * mm))
        story.append(P("그림 8. 폴드별 연율 초과수익", st["caption"]))
    story.append(P(
        f"WF 중앙 초과={num(rob_score.get('med_wf_excess'), 3)}, "
        f"양수 폴드 비율={pct(rob_score.get('wf_pos_share'))}, "
        f"폴드 집중도={num(rob_score.get('fold_concentration'), 2)} "
        "(1에 가까울수록 한 구간 편중).",
        st["body"],
    ))

    story.append(P("<b>이동 블록 부트스트랩 초과수익</b>", st["h2"]))
    story.append(table(
        ["관측초과", "평균", "5%", "50%", "95%", "P(>0)", "방법"],
        [[
            pct(boot.get("obs_ann_excess")), pct(boot.get("boot_mean")),
            pct(boot.get("boot_p5")), pct(boot.get("boot_p50")), pct(boot.get("boot_p95")),
            pct(boot.get("prob_positive"), 1), str(boot.get("method", "moving_block_bootstrap")),
        ]],
        st, [24 * mm, 18 * mm, 16 * mm, 16 * mm, 16 * mm, 18 * mm, 50 * mm], left0=False,
    ))

    story.append(KeepTogether([
        P("<b>Gate Protocol (강화 10항)</b>", st["h2"]),
        P(
            f"종합: <b>{gates.get('status')}</b> — {gates.get('n_pass')}/{gates.get('n_total')}. "
            "절대수익이 아니라 벤치 대비·OOS·WF 중앙·부트스트랩 최소선.",
            st["body"],
        ),
    ]))
    if "gates" in paths:
        story.append(KeepTogether([
            Image(str(paths["gates"]), width=158 * mm, height=54 * mm),
            P("그림 9. Gate 보드", st["caption"]),
        ]))
    grows = [[c.get("name"), "PASS" if c.get("pass") else "FAIL", c.get("detail")]
             for c in (gates.get("checks") or [])]
    if grows:
        story.append(KeepTogether([table(["검사", "결과", "상세"], grows, st, [40 * mm, 16 * mm, 124 * mm])]))
    story.append(PageBreak())

    # ========== 8 holdings / SOP ==========
    story.append(section("8. 최근 포트폴리오 · 운용 SOP", st))
    story.append(table(
        ["항목", "내용"],
        [
            ["전략 코드", str(rec)],
            ["목표 비중", wtxt],
            ["신호일", str(latest.get("signal_date", "-"))],
            ["체결일", str(latest.get("exec_date", "-"))],
            ["보유 종목 수", str(latest.get("n", "-"))],
            ["턴오버(편도)", num(latest.get("turnover"), 3)],
        ],
        st, [32 * mm, 150 * mm],
    ))
    sleeves = latest.get("sleeves") or {}
    if sleeves:
        srows = [[k, ", ".join(v[:14]) if isinstance(v, list) else str(v)] for k, v in sleeves.items()]
        story.append(table(["슬리브", "최근 선정 종목"], srows, st, [26 * mm, 156 * mm]))
    if tail:
        trows = []
        for h in tail:
            sl = h.get("sleeves") or {}
            trows.append([
                h.get("signal_date", ""), h.get("exec_date", ""),
                str(sum(len(x) for x in sl.values() if isinstance(x, list))),
                str(h.get("n", "")), num(h.get("turnover"), 3),
            ])
        story.append(P("<b>최근 리밸 요약</b>", st["h2"]))
        story.append(table(
            ["신호일", "체결일", "선정합", "N", "TO"],
            trows, st, [32 * mm, 32 * mm, 24 * mm, 20 * mm, 20 * mm],
        ))

    story.append(P("<b>운영 SOP (동결)</b>", st["h2"]))
    story.append(table(
        ["단계", "규칙"],
        [
            ["1. 신호", "매월 말 거래일 Close로 가격·변동성 피처 확정"],
            ["2. 선정", "Leader Top10 / Mom63 Top10 / LowVol Top12 전후 · 유동성≥$50M · 가격≥$5"],
            ["3. 비중", f"{wtxt} × 슬리브 내 동일가중 → 종목 15% 상한 재분배"],
            ["4. 체결", "다음 거래일 Open 일괄 리밸 (신호일 종가 매매 금지)"],
            ["5. 청산", "다음 월 신호 탈락 시에만. 물타기·이벤트 NLP·주간 재선정 금지"],
            ["6. 리스크", "포트 MDD·턴오버·슬리브 상관·롤링 β 모니터링"],
            ["7. 금지", "AccumulDiv 재도입, 사후 비중 커브피팅, 주간 종목 교체, 절대 CAGR 목표화"],
            ["8. 재평가", "분기 1회 Gate·WF 중앙초과·팩터 상관 재점검 (규칙 변경은 사전등록 후)"],
        ],
        st, [26 * mm, 156 * mm],
    ))

    # ========== 9 conclusion ==========
    story.append(section("9. 결론 · 한계 · 면책", st))
    story.append(P("<b>결론</b>", st["h2"]))
    story.append(P(
        f"미국 대형 유동성 유니버스의 강건 퀀트 북은 "
        f"<b>Leader 60% + Mom63 20% + LowVol 20%</b> 로 고정한다. "
        f"한국 전략의 월간 Next-Open·상한 골격은 유지하되, 수급 다이버전스 20%는 폐기한다. "
        f"검증 결과 CAGR {pct(rs.get('cagr'))}, Sharpe {num(rs.get('sharpe'))}, "
        f"IR {num(rs.get('info_ratio'))}, MaxDD {pct(rs.get('mdd'))}, "
        f"β {num(rs.get('beta'))}, Gate {gates.get('status')} {gates.get('n_pass')}/{gates.get('n_total')}. "
        f"팩터 겹침 기준으로는 모멘텀 묶음(80%) + 저볼(20%)의 2차원 전략이다. "
        f"초과수익의 본체는 베타 증폭이 아니라 알파다.",
        st["body"],
    ))
    story.append(P("<b>한계</b>", st["h2"]))
    story.append(P(
        "1) 생존편향(현재 S&amp;P 구성). 2) yfinance 가격·재무 노이즈. "
        "3) 섹터 40% 캡 미적용. 4) 모멘텀 레짐·메가캡 장세 의존 가능. "
        "5) Leader–Mom63 고상관으로 위기 동조화. 6) 연구자 사전등록 메뉴 선택 편향 잔존. "
        "7) 실매매 슬리피지·세금·환·배당 과세 미완전 반영. "
        "8) OOS·최근 롤링 β 상승은 과신 금지 신호.",
        st["body"],
    ))
    story.append(P(
        "면책: 본 문서는 연구용 백테스트·전략 설명 통합본이며 특정 증권의 매수·매도 권유가 아니다. "
        "과거 성과는 미래 수익을 보장하지 않는다. 실매매 전 데이터·비용·컴플라이언스를 별도 점검해야 한다.",
        st["small"],
    ))
    story.append(Spacer(1, 5))
    story.append(P(
        f"산출물: {OUT.name} · {ROB/'metrics.json'} · equity_curves.csv · holdings.json · "
        f"팩터랩 {LAB/'metrics.json'} · us_robust_strategy.py · us_factor_research.py",
        st["small"],
    ))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("FINAL PDF ->", OUT)
    return OUT


if __name__ == "__main__":
    build()
