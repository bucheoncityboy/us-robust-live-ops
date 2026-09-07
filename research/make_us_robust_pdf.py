"""미국 시장 강건 전략 구성 · 엄격 백테스트 한글 PDF"""
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
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "us_robust"
CHART = RES / "charts"
OUT = RES / "미국시장_강건전략_엄격백테스트_보고서.pdf"

NAVY = colors.HexColor("#0F2744")
BLUE = colors.HexColor("#1F4E79")
ACCENT = colors.HexColor("#C45C26")
LIGHT = colors.HexColor("#F4F7FB")
GRID = colors.HexColor("#D0D7E2")
GRAY = colors.HexColor("#5B6573")


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
    s["cover_title"] = ParagraphStyle("ct", fontName=fb, fontSize=18, leading=24, textColor=colors.white)
    s["cover_sub"] = ParagraphStyle("cs", fontName=font, fontSize=8.8, leading=12, textColor=colors.HexColor("#D9E2F0"))
    s["h1"] = ParagraphStyle("h1", fontName=fb, fontSize=12.5, leading=16, textColor=NAVY, spaceBefore=2, spaceAfter=4)
    s["h2"] = ParagraphStyle("h2", fontName=fb, fontSize=10.2, leading=13.5, textColor=BLUE, spaceBefore=4, spaceAfter=2)
    s["body"] = ParagraphStyle("body", fontName=font, fontSize=8.8, leading=12.5, textColor=colors.HexColor("#1F2933"))
    s["quote"] = ParagraphStyle(
        "q", fontName=font, fontSize=9.0, leading=13, textColor=colors.HexColor("#111827"),
        backColor=LIGHT, borderPadding=6,
    )
    s["th"] = ParagraphStyle("th", fontName=fb, fontSize=7.5, leading=9.8, textColor=colors.white)
    s["td"] = ParagraphStyle("td", fontName=font, fontSize=7.5, leading=10, textColor=colors.HexColor("#1F2933"), alignment=1)
    s["td_left"] = ParagraphStyle("tdl", fontName=font, fontSize=7.5, leading=10, textColor=colors.HexColor("#1F2933"), alignment=0)
    s["kpi"] = ParagraphStyle("kpi", fontName=font, fontSize=7.2, leading=9.5, textColor=GRAY, alignment=1)
    s["kpi_val"] = ParagraphStyle("kpiv", fontName=fb, fontSize=10.5, leading=13, textColor=NAVY, alignment=1)
    s["caption"] = ParagraphStyle("cap", fontName=font, fontSize=7.2, leading=9.5, textColor=GRAY, alignment=1)
    s["toc"] = ParagraphStyle("toc", fontName=font, fontSize=8.6, leading=12, textColor=colors.HexColor("#334155"))
    s["small"] = ParagraphStyle("sm", fontName=font, fontSize=7.2, leading=9.8, textColor=GRAY)
    s["warn"] = ParagraphStyle("warn", fontName=font, fontSize=8.2, leading=11.5, textColor=ACCENT)
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
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
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
        ("INNERGRID", (0, 0), (-1, -1), 0.3, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 2.9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.9),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
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
    canvas.setFont("KR", 7.2)
    canvas.setFillColor(GRAY)
    canvas.drawString(13.5 * mm, 6 * mm, "US Robust Strategy · Strict Research · Not Investment Advice")
    canvas.drawRightString(A4[0] - 13.5 * mm, 6 * mm, f"{doc.page}")
    canvas.restoreState()


def make_charts(eq: pd.DataFrame, m: Dict) -> Dict[str, Path]:
    CHART.mkdir(parents=True, exist_ok=True)
    out = {}
    rec = (m.get("recommended") or {}).get("name")
    ranking = m.get("ranking") or []
    wf = (m.get("recommended") or {}).get("walk_forward") or []
    gates = (m.get("recommended") or {}).get("gates") or {}
    rob = (m.get("recommended") or {}).get("robustness") or {}

    # arch
    fig, ax = plt.subplots(figsize=(10.4, 3.9), dpi=160)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5)
    ax.axis("off")
    wmap = ((m.get("recommended") or {}).get("row") or {}).get("weights") or {}
    boxes = [
        (0.5, 3.0, 3.2, 1.4, f"CORE\nLeader {int((wmap.get('Leader') or 0)*100)}%", "#C45C26"),
        (4.2, 3.0, 3.2, 1.4, "SATELLITE\n" + " / ".join(
            f"{k} {int(v*100)}%" for k, v in wmap.items() if k != "Leader"
        ) or "—", "#1F4E79"),
        (8.0, 3.0, 3.4, 1.4, "CONTROLS\nNext-Open · 15% cap\nEW sleeve · monthly", "#2E7D32"),
        (1.2, 0.6, 9.5, 1.6,
         "DROP: AccumulDiv · pure Value/Quality as core · Mom12+RelMom double count\n"
         "OBJECTIVE: robustness (IR · WF median excess · block bootstrap − fold concentration)",
         "#334155"),
    ]
    for x, y, w, h, txt, c in boxes:
        ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=c, edgecolor="white", lw=1.2, alpha=0.93))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", color="white",
                fontsize=10, fontweight="bold")
    ax.set_title(f"강건 전략 구조 — {rec}", fontsize=12, pad=8)
    fig.tight_layout()
    p = CHART / "arch.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close()
    out["arch"] = p

    # equity
    fig, ax = plt.subplots(figsize=(10.3, 3.9), dpi=160)
    order = ["Bench_SPY", rec, "Aggressive_L100", "Robust_L70_LV30", "Robust_L60_M63_LV20",
             "Robust_L50_RM_LV20", "Robust_L55_NH_LV25"]
    cmap = {
        "Bench_SPY": "#8A94A6", rec: "#C45C26", "Aggressive_L100": "#E45756",
        "Robust_L70_LV30": "#1F4E79", "Robust_L60_M63_LV20": "#6A1B9A",
        "Robust_L50_RM_LV20": "#00838F", "Robust_L55_NH_LV25": "#2E7D32",
    }
    for c in order:
        if c not in eq.columns or c is None:
            continue
        s = eq[c].dropna()
        if s.empty:
            continue
        n = s / s.iloc[0] * 100
        lw = 2.3 if c in (rec, "Bench_SPY") else 1.1
        ax.plot(n.index, n.values, label=c.replace("Robust_", "R_").replace("Aggressive_", "A_"),
                color=cmap.get(c), lw=lw)
    ax.legend(loc="upper left", fontsize=7.5, ncol=2)
    ax.set_title("자산곡선 (Next-Open, 10bp)")
    ax.set_ylabel("성장지수 100=시작")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = CHART / "equity.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close()
    out["equity"] = p

    # ranking bars
    fig, axes = plt.subplots(1, 3, figsize=(10.6, 3.5), dpi=160)
    names = [r["name"].replace("Robust_", "R_").replace("Aggressive_", "A_") for r in ranking]
    axes[0].barh(names[::-1], [r["score"] for r in ranking][::-1], color="#1F4E79")
    axes[0].set_title("강건성")
    axes[1].barh(names[::-1], [r.get("sharpe") or 0 for r in ranking][::-1], color="#C45C26")
    axes[1].set_title("Sharpe")
    axes[2].barh(names[::-1], [(r.get("mdd") or 0) * 100 for r in ranking][::-1], color="#6A1B9A")
    axes[2].set_title("MaxDD %")
    for ax in axes:
        ax.grid(axis="x", alpha=0.3)
    fig.suptitle("사전등록 변형 비교", fontsize=11)
    fig.tight_layout()
    p = CHART / "compare.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close()
    out["compare"] = p

    # dd of recommended
    if rec and rec in eq.columns:
        s = eq[rec].dropna()
        dd = s / s.cummax() - 1
        fig, ax = plt.subplots(figsize=(10.3, 2.8), dpi=160)
        ax.fill_between(dd.index, dd.values * 100, 0, color="#C62828", alpha=0.55)
        ax.set_title(f"낙폭 — {rec}")
        ax.set_ylabel("%")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        p = CHART / "dd.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["dd"] = p

    if wf:
        fig, ax = plt.subplots(figsize=(9.5, 3.1), dpi=160)
        xs = [f"F{f['fold']}" for f in wf]
        ys = [(f.get("ann_ex") or 0) * 100 for f in wf]
        cols = ["#2E7D32" if y > 0 else "#C62828" for y in ys]
        ax.bar(xs, ys, color=cols)
        ax.axhline(0, color="#333", lw=0.8)
        ax.set_title(f"Walk-Forward 초과수익 — {rec}")
        ax.set_ylabel("%p")
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        p = CHART / "wf.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["wf"] = p

    checks = gates.get("checks") or []
    if checks:
        fig, ax = plt.subplots(figsize=(9.5, 3.3), dpi=160)
        names = [c["name"].replace("G", "") for c in checks]
        vals = [1 if c["pass"] else 0 for c in checks]
        cols = ["#2E7D32" if v else "#C62828" for v in vals]
        ax.barh(names[::-1], vals[::-1], color=cols[::-1])
        ax.set_xlim(0, 1.2)
        ax.set_title(f"Gate {gates.get('status')} {gates.get('n_pass')}/{gates.get('n_total')}")
        fig.tight_layout()
        p = CHART / "gates.png"
        fig.savefig(p, bbox_inches="tight")
        plt.close()
        out["gates"] = p

    return out


def build():
    font, fb = fonts()
    st = styles(font, fb)
    m = json.loads((RES / "metrics.json").read_text(encoding="utf-8"))
    eq = pd.read_csv(RES / "equity_curves.csv", index_col=0, parse_dates=True)

    rec_b = m.get("recommended") or {}
    rec = rec_b.get("name")
    rs = rec_b.get("stats") or {}
    gates = rec_b.get("gates") or {}
    boot = rec_b.get("bootstrap") or {}
    isoos = rec_b.get("isoos") or {}
    wf = rec_b.get("walk_forward") or []
    rob = rec_b.get("robustness") or {}
    row = rec_b.get("row") or {}
    bench = m.get("bench") or {}
    dr = m.get("data_range") or {}
    ranking = m.get("ranking") or []
    latest = rec_b.get("latest_holdings") or {}
    tail = rec_b.get("holdings_tail") or []
    stress = (rec_b.get("stress") or {}).get("stats") or {}
    weights = row.get("weights") or {}
    thesis = row.get("thesis") or ""
    paths = make_charts(eq, m)

    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=13.5 * mm, rightMargin=13.5 * mm, topMargin=11 * mm, bottomMargin=14 * mm,
        title="미국 시장 강건전략 엄격 백테스트", author="RLM Research",
    )
    story: List = []

    banner = Table([
        [P("RLM Quantitative Research  ·  US ROBUST STRATEGY  ·  2026-07-19", st["cover_sub"])],
        [P("미국 시장 강건 전략 구성<br/>엄격 백테스트 보고서", st["cover_title"])],
        [P("팩터랩 통과 팩터 조합 · 중복 제거 · Next-Open · 블록 부트스트랩 · Gate 10항", st["cover_sub"])],
    ], colWidths=[A4[0] - 27 * mm])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, 0), 12),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 1), (-1, 1), 7),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
    ]))
    story.append(banner)
    story.append(Spacer(1, 7))

    wtxt = " / ".join(f"{k} {int(v*100)}%" for k, v in weights.items())
    story.append(P(
        "<b>최종 한 줄</b><br/>"
        "팩터 연구에서 PASS한 가격 팩터만 모아 <b>사전등록 소수 변형</b>으로 강건 북을 구성했다. "
        f"권고: <b>{rec}</b> ({wtxt}). {thesis} "
        f"CAGR {pct(rs.get('cagr'))} · Sharpe {num(rs.get('sharpe'))} · IR {num(rs.get('info_ratio'))} · "
        f"MaxDD {pct(rs.get('mdd'))} · Gate <b>{gates.get('status')}</b> "
        f"({gates.get('n_pass')}/{gates.get('n_total')}). "
        "목표함수는 원시 CAGR이 아니라 강건성 점수다.",
        st["quote"],
    ))
    story.append(Spacer(1, 5))

    meta = [
        ["문서 성격", "강건 전략 고정안 + 엄격 검증 (투자 권유 아님)"],
        ["권고 전략", f"{rec} · 강건성 {num(rob.get('score'), 3)}"],
        ["가중치", wtxt],
        ["검증 기간", f"{dr.get('signals')} (신호 {dr.get('n_signals')}회)"],
        ["유니버스", f"S&P 유동성 상위 {dr.get('n_codes')} · 생존편향 존재"],
        ["프로토콜", "Next-Open · 10/20bp · IS/OOS · WF5 · 블록부트스트랩 · Gate10"],
        ["리밸", "월 1회 · 월말 Close 신호 → 다음 Open · 종목 15%"],
        ["폐기", "AccumulDiv · 재무 코어 · Mom12+RelMom 이중 적재"],
    ]
    mt = Table([[P(a, st["td_left"]), P(b, st["td_left"])] for a, b in meta], colWidths=[32 * mm, 148 * mm])
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.55, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.32, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(mt)
    story.append(Spacer(1, 4))
    for t in [
        "1. Executive Decision Summary",
        "2. 설계 원칙 (강건성)",
        "3. 사전등록 변형 · 선택",
        "4. 권고 전략 성과",
        "5. IS/OOS · WF · Bootstrap · Gate",
        "6. 최근 포트 · 운용 SOP",
        "7. 결론 · 한계 · 면책",
    ]:
        story.append(P(t, st["toc"]))
    if "arch" in paths:
        story.append(Spacer(1, 3))
        story.append(Image(str(paths["arch"]), width=175 * mm, height=65 * mm))
        story.append(P("그림 1. 강건 전략 구조", st["caption"]))
    story.append(PageBreak())

    # 1
    story.append(section("1. Executive Decision Summary", st))
    items = [
        ("권고", str(rec).replace("Robust_", "R_")[:16]),
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
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.32, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(k)
    story.append(Spacer(1, 4))
    story.append(table(
        ["질문", "결론"],
        [
            ["코어 팩터?", "Leader (12-1+신고가+거래확인 필터 모멘텀)"],
            ["위성?", "LowVol 필수 검토 / Mom63·NearHigh·RelMom은 변형별 선택"],
            ["왜 강건?", "중복 모멘텀 통제 · 방어 위성 · WF 중앙초과 · 폴드집중 감점 · 블록부트"],
            ["비중?", wtxt],
            ["비용 스트레스?", f"20bp CAGR {pct(stress.get('cagr'))} Sharpe {num(stress.get('sharpe'))}"],
            ["vs SPY?", f"초과 CAGR {pct((rs.get('cagr') or 0)-(bench.get('cagr') or 0))} · Alpha {pct(rs.get('alpha'))}"],
            ["금지?", "AccumulDiv, 주간 교체, 사후 비중 최적화, 물타기"],
        ],
        st, [36 * mm, 144 * mm],
    ))

    # 2
    story.append(section("2. 설계 원칙 (강건성)", st))
    story.append(P(
        "강건 전략은 ‘가장 높은 CAGR 조합’이 아니라 "
        "<b>시간 축에서 반복되는 위험조정 초과</b>를 노린다. "
        "팩터랩에서 PASS한 축만 쓰고, 실패·중복·짧은 표본 축은 구조적으로 배제한다.",
        st["body"],
    ))
    story.append(table(
        ["원칙", "내용"],
        [
            ["1. PASS only", "단독 Gate PASS 가격 팩터만 알파 엔진 후보"],
            ["2. Drop FAIL", "AccumulDiv 폐기, 재무 코어 미사용(표본·IR 약함)"],
            ["3. No double 12-1", "Mom12≈RelMom(상관~1) → 순수 12-1 슬리브는 최대 1개"],
            ["4. Leader core", "필터 모멘텀을 주력. 순수 Mom63 올인은 고MDD로 비권고"],
            ["5. LowVol satellite", "단독 IR 음수여도 Leader 상관~0.4 → 방어 위성"],
            ["6. Objective", "robustness = IR+Sharpe+WF중앙+부트 − 폴드집중 − MDD 페널티"],
            ["7. Small menu", "사전등록 5변형 + 스트레스 1개만 평가"],
        ],
        st, [36 * mm, 144 * mm],
    ))
    story.append(P(
        "잔존 편향: 생존 S&amp;P 멤버십, yfinance 노이즈, 섹터캡 미적용, 최근 모멘텀 레짐 의존. "
        "절대 CAGR을 운용 KPI로 쓰지 말 것.",
        st["warn"],
    ))

    # 3
    story.append(section("3. 사전등록 변형 · 선택", st))
    rrows = []
    for r in ranking:
        rrows.append([
            r["name"].replace("Robust_", "R_").replace("Aggressive_", "A_"),
            " / ".join(f"{k[:3]}{int(v*100)}" for k, v in (r.get("weights") or {}).items()),
            pct(r.get("cagr")),
            num(r.get("sharpe")),
            num(r.get("ir")),
            pct(r.get("mdd")),
            num(r.get("med_wf_excess"), 3),
            num(r.get("fold_concentration"), 2),
            num(r.get("score"), 3),
            f"{r.get('gate')}",
        ])
    story.append(table(
        ["전략", "비중", "CAGR", "Sh", "IR", "MDD", "WF중앙", "집중", "강건성", "Gate"],
        rrows,
        st, [34 * mm, 28 * mm, 15 * mm, 12 * mm, 12 * mm, 15 * mm, 16 * mm, 12 * mm, 16 * mm, 14 * mm],
    ))
    if "compare" in paths:
        story.append(Image(str(paths["compare"]), width=175 * mm, height=58 * mm))
        story.append(P("그림 2. 변형별 강건성 / Sharpe / MaxDD", st["caption"]))
    story.append(P(
        f"선택 규칙: robust 패밀리 중 강건성 최대 · hard FAIL 제외 · 스트레스·공격 벤치 제외. "
        f"결과 권고 = <b>{rec}</b>. {thesis}",
        st["body"],
    ))
    story.append(PageBreak())

    # 4
    story.append(section("4. 권고 전략 성과", st))
    if "equity" in paths:
        story.append(Image(str(paths["equity"]), width=175 * mm, height=66 * mm))
        story.append(P("그림 3. 자산곡선", st["caption"]))
    if "dd" in paths:
        story.append(Image(str(paths["dd"]), width=175 * mm, height=48 * mm))
        story.append(P("그림 4. 낙폭", st["caption"]))

    story.append(table(
        ["지표", "권고", "SPY", "스트레스20bp", "공격 L100"],
        [
            ["CAGR", pct(rs.get("cagr")), pct(bench.get("cagr")),
             pct(stress.get("cagr")),
             pct(next((r.get("cagr") for r in ranking if r["name"] == "Aggressive_L100"), None))],
            ["Sharpe", num(rs.get("sharpe")), num(bench.get("sharpe")),
             num(stress.get("sharpe")),
             num(next((r.get("sharpe") for r in ranking if r["name"] == "Aggressive_L100"), None))],
            ["IR", num(rs.get("info_ratio")), "-",
             num((rec_b.get("stress") or {}).get("stats", {}).get("info_ratio")),
             num(next((r.get("ir") for r in ranking if r["name"] == "Aggressive_L100"), None))],
            ["MaxDD", pct(rs.get("mdd")), pct(bench.get("mdd")),
             pct(stress.get("mdd")),
             pct(next((r.get("mdd") for r in ranking if r["name"] == "Aggressive_L100"), None))],
            ["Alpha", pct(rs.get("alpha")), pct(bench.get("alpha")),
             pct(stress.get("alpha")), "-"],
            ["Vol", pct(rs.get("vol")), pct(bench.get("vol")),
             pct(stress.get("vol")),
             pct(next((r.get("vol") for r in ranking if r["name"] == "Aggressive_L100"), None))],
            ["강건성", num(rob.get("score"), 3), "-",
             num(((rec_b.get("stress") or {}).get("robustness") or {}).get("score"), 3),
             num(next((r.get("score") for r in ranking if r["name"] == "Aggressive_L100"), None), 3)],
        ],
        st, [28 * mm, 30 * mm, 28 * mm, 36 * mm, 36 * mm],
    ))
    story.append(P(
        f"해석: 공격 L100 대비 권고안은 CAGR을 일부 희생하더라도 "
        f"Sharpe·IR·MDD·강건성 중 하나 이상에서 개선되는지를 본다. "
        f"20bp 스트레스 후에도 구조가 유지되는지가 실무 기준선이다.",
        st["body"],
    ))

    # 5
    story.append(section("5. IS/OOS · WF · Bootstrap · Gate", st))
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
    if wf:
        wrows = [[
            str(f.get("fold")), f"{f.get('start')}~{f.get('end')}",
            pct(f.get("cagr")), pct(f.get("bench_cagr")), pct(f.get("ann_ex")),
            num(f.get("sharpe")), pct(f.get("mdd")), num(f.get("info_ratio")),
        ] for f in wf]
        story.append(P("<b>Walk-Forward</b>", st["h2"]))
        story.append(table(
            ["Fold", "기간", "CAGR", "Bench", "초과", "Sh", "MDD", "IR"],
            wrows, st, [14 * mm, 46 * mm, 16 * mm, 16 * mm, 16 * mm, 14 * mm, 16 * mm, 14 * mm],
        ))
    if "wf" in paths:
        story.append(Image(str(paths["wf"]), width=165 * mm, height=54 * mm))
        story.append(P("그림 5. 폴드별 초과수익", st["caption"]))
    story.append(P(
        f"WF 중앙 초과={num(rob.get('med_wf_excess'), 3)}, 양수 폴드 비율={pct(rob.get('wf_pos_share'))}, "
        f"폴드 집중={num(rob.get('fold_concentration'), 2)}.",
        st["body"],
    ))
    story.append(P("<b>블록 부트스트랩</b>", st["h2"]))
    story.append(table(
        ["관측초과", "평균", "5%", "50%", "95%", "P(>0)", "방법"],
        [[
            pct(boot.get("obs_ann_excess")), pct(boot.get("boot_mean")),
            pct(boot.get("boot_p5")), pct(boot.get("boot_p50")), pct(boot.get("boot_p95")),
            pct(boot.get("prob_positive"), 1), str(boot.get("method", "-")),
        ]],
        st, [24 * mm, 20 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm, 46 * mm], left0=False,
    ))
    if "gates" in paths:
        story.append(Image(str(paths["gates"]), width=160 * mm, height=56 * mm))
        story.append(P("그림 6. Gate 보드", st["caption"]))
    grows = [[c.get("name"), "PASS" if c.get("pass") else "FAIL", c.get("detail")]
             for c in (gates.get("checks") or [])]
    if grows:
        story.append(table(["검사", "결과", "상세"], grows, st, [42 * mm, 18 * mm, 120 * mm]))
    story.append(PageBreak())

    # 6
    story.append(section("6. 최근 포트 · 운용 SOP", st))
    story.append(table(
        ["항목", "내용"],
        [
            ["전략", str(rec)],
            ["비중", wtxt],
            ["신호일", str(latest.get("signal_date", "-"))],
            ["체결일", str(latest.get("exec_date", "-"))],
            ["보유 N", str(latest.get("n", "-"))],
            ["턴오버", num(latest.get("turnover"), 3)],
        ],
        st, [32 * mm, 148 * mm],
    ))
    sleeves = latest.get("sleeves") or {}
    if sleeves:
        srows = [[k, ", ".join(v[:12]) if isinstance(v, list) else str(v)] for k, v in sleeves.items()]
        story.append(table(["슬리브", "최근 종목"], srows, st, [28 * mm, 152 * mm]))
    if tail:
        trows = []
        for h in tail:
            sl = h.get("sleeves") or {}
            trows.append([
                h.get("signal_date", ""), h.get("exec_date", ""),
                str(sum(len(x) for x in sl.values() if isinstance(x, list))),
                str(h.get("n", "")), num(h.get("turnover"), 3),
            ])
        story.append(table(
            ["신호일", "체결일", "선정합", "N", "TO"],
            trows, st, [32 * mm, 32 * mm, 24 * mm, 20 * mm, 20 * mm],
        ))
    story.append(P("<b>SOP</b>", st["h2"]))
    story.append(table(
        ["단계", "규칙"],
        [
            ["1 신호", "매월 말 Close로 피처 확정"],
            ["2 선정", f"슬리브별 Top{10} · 유동성·가격 필터"],
            ["3 비중", f"{wtxt} × 슬리브 내 동일가중 → 15% 캡"],
            ["4 체결", "다음 거래일 Open (신호일 종가 금지)"],
            ["5 청산", "월말 신호 탈락 시만. 물타기·이벤트 청산 금지"],
            ["6 모니터링", "MDD, 턴오버, 슬리브 상관, Gate 재평가(분기)"],
            ["7 금지", "AccumulDiv 재도입, 주간 리밸, 사후 최적 비중"],
        ],
        st, [28 * mm, 152 * mm],
    ))

    # 7
    story.append(section("7. 결론 · 한계 · 면책", st))
    story.append(P(
        f"<b>결론</b> — 미국 강건 북의 본체는 Leader 모멘텀이고, "
        f"저상관 LowVol(및 변형에 따라 Mom63/NearHigh/RelMom) 위성이 낙폭·강건성을 보탠다. "
        f"최종 고정 권고는 <b>{rec}</b> ({wtxt}). "
        f"성과: CAGR {pct(rs.get('cagr'))}, Sharpe {num(rs.get('sharpe'))}, "
        f"IR {num(rs.get('info_ratio'))}, MaxDD {pct(rs.get('mdd'))}, "
        f"Gate {gates.get('status')}. "
        f"한국식 수급 다이버전스와 재무 코어는 이 유니버스·표본에서 채택하지 않는다.",
        st["body"],
    ))
    story.append(P(
        "한계: 생존편향, 데이터 품질, 섹터캡 부재, 모멘텀 레짐 의존, 연구자 사전등록 메뉴 선택 편향. "
        "실매매 전 브로커 비용·세금·환·실행 슬립을 재검증할 것.",
        st["body"],
    ))
    story.append(P(
        "면책: 연구용 백테스트이며 투자 권유가 아니다. 과거 성과는 미래를 보장하지 않는다.",
        st["small"],
    ))
    story.append(Spacer(1, 5))
    story.append(P(
        f"산출물: {RES/'metrics.json'} · stats.csv · equity_curves.csv · holdings.json · 본 PDF",
        st["small"],
    ))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print("PDF ->", OUT)
    return OUT


if __name__ == "__main__":
    build()
