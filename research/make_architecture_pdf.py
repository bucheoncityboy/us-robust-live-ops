"""미국 강건 퀀트 라이브 운영 시스템 — 아키텍처 심층 분석 보고서 PDF (한글).

포트폴리오용 프로젝트 분석 문서. results/architecture_report/ 아래로 PDF 출력.
차트는 results/strict_report/charts/* (strict_edge_report.py 산출물) 재사용.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

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
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results" / "architecture_report"
CHARTS = ROOT / "results" / "strict_report" / "charts"
OUT = RES / "미국_강건퀀트_라이브운영시스템_아키텍처_분석보고서.pdf"

NAVY = colors.HexColor("#0F2744")
BLUE = colors.HexColor("#1F4E79")
ACCENT = colors.HexColor("#C45C26")
LIGHT = colors.HexColor("#F4F7FB")
GRID = colors.HexColor("#D0D7E2")
GRAY = colors.HexColor("#5B6573")
GREEN = colors.HexColor("#1B7F4C")
RED = colors.HexColor("#B3392B")
WHITE = colors.white


def fonts():
    reg = Path(r"C:\Windows\Fonts\malgun.ttf")
    bold = Path(r"C:\Windows\Fonts\malgunbd.ttf")
    pdfmetrics.registerFont(TTFont("KR", str(reg)))
    if bold.exists():
        pdfmetrics.registerFont(TTFont("KR-Bold", str(bold)))
        return "KR", "KR-Bold"
    return "KR", "KR"


def styles(font, fb):
    s = {}
    s["cover_title"] = ParagraphStyle("ct", fontName=fb, fontSize=20, leading=27, textColor=WHITE)
    s["cover_title2"] = ParagraphStyle("ct2", fontName=fb, fontSize=12.5, leading=17, textColor=colors.HexColor("#D9E2F0"))
    s["cover_meta"] = ParagraphStyle("cm", fontName=font, fontSize=9, leading=13, textColor=colors.HexColor("#B9C6D8"))
    s["h1"] = ParagraphStyle("h1", fontName=fb, fontSize=12.5, leading=17, textColor=NAVY, spaceBefore=4, spaceAfter=4)
    s["toc_h1"] = ParagraphStyle(
        "toc_h1", fontName=fb, fontSize=12.5, leading=17, textColor=NAVY,
        backColor=LIGHT, borderPadding=(6, 7, 5, 7), spaceBefore=8, spaceAfter=3,
    )
    s["toc_h2"] = ParagraphStyle("toc_h2", fontName=fb, fontSize=10.2, leading=13.5, textColor=BLUE, spaceBefore=5, spaceAfter=3)
    s["toc_e1"] = ParagraphStyle("toc_e1", fontName=fb, fontSize=9.5, leading=14, textColor=NAVY)
    s["toc_e2"] = ParagraphStyle("toc_e2", fontName=font, fontSize=8.2, leading=12, textColor=colors.HexColor("#3A4657"), leftIndent=10)
    s["h2"] = ParagraphStyle("h2", fontName=fb, fontSize=10.2, leading=13.5, textColor=BLUE, spaceBefore=5, spaceAfter=3)
    s["h3"] = ParagraphStyle("h3", fontName=fb, fontSize=9.0, leading=12, textColor=colors.HexColor("#333F50"), spaceBefore=3, spaceAfter=2)
    s["body"] = ParagraphStyle("body", fontName=font, fontSize=8.6, leading=12.6, textColor=colors.HexColor("#1F2933"))
    s["body_center"] = ParagraphStyle("bodyc", parent=s["body"], alignment=1)
    s["bullet"] = ParagraphStyle("bullet", parent=s["body"], leftIndent=10, bulletIndent=2, spaceAfter=1.2)
    s["quote"] = ParagraphStyle("q", fontName=font, fontSize=8.8, leading=12.5, textColor=colors.HexColor("#111827"),
                                backColor=LIGHT, borderPadding=6)
    s["th"] = ParagraphStyle("th", fontName=fb, fontSize=7.2, leading=9.4, textColor=WHITE)
    s["td"] = ParagraphStyle("td", fontName=font, fontSize=7.2, leading=9.6, textColor=colors.HexColor("#1F2933"), alignment=1)
    s["td_left"] = ParagraphStyle("tdl", fontName=font, fontSize=7.2, leading=9.6, textColor=colors.HexColor("#1F2933"), alignment=0)
    s["td_left_b"] = ParagraphStyle("tdlb", fontName=fb, fontSize=7.2, leading=9.6, textColor=colors.HexColor("#1F2933"), alignment=0)
    s["caption"] = ParagraphStyle("cap", fontName=font, fontSize=7.0, leading=9.2, textColor=GRAY, alignment=1)
    s["small"] = ParagraphStyle("sm", fontName=font, fontSize=7.2, leading=10, textColor=GRAY)
    s["kpi_v"] = ParagraphStyle("kpiv", fontName=fb, fontSize=13.5, leading=16, textColor=NAVY, alignment=1)
    s["kpi_l"] = ParagraphStyle("kpil", fontName=font, fontSize=7.0, leading=9.2, textColor=GRAY, alignment=1)
    s["foot"] = ParagraphStyle("foot", fontName=font, fontSize=6.8, leading=9.4, textColor=GRAY)
    return s


def P(text, st):
    t = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
        .replace("&lt;br/&gt;", "<br/>")
    )
    return Paragraph(t, st)


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


class Doc(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            st = flowable.style.name
            if st == "toc_h1":
                self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
            elif st == "toc_h2":
                self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


def section(title, st):
    head = [
        P(title, st["toc_h1"]),
        Table([[Spacer(1, 0)]], colWidths=[180 * mm], rowHeights=[1.6]),
        Spacer(1, 3),
    ]
    table = Table([[head[1]]], colWidths=[180 * mm])
    table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.6, NAVY)]))
    return [head[0], table]


def h2(title, st):
    return Paragraph(title, st["toc_h2"])


def datatable(st, header, rows, widths=None, aligns=None, fontsize=7.2):
    data = [[P(h, st["th"]) for h in header]]
    n = len(header)
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            a = st["td"] if (aligns is None or aligns[i] == "c") else st["td_left"]
            cells.append(P(c, a))
        data.append(cells)
    if widths is None:
        widths = [180 * mm / n] * n
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
    ]
    t.setStyle(TableStyle(style))
    return t


def chart(st, name, caption, width_mm=172):
    img_path = CHARTS / name
    if not img_path.exists():
        return Spacer(1, 4)
    from PIL import Image as PILImage
    with PILImage.open(img_path) as im:
        w, h = im.size
    ratio = h / w
    el = [
        Image(str(img_path), width=width_mm * mm, height=width_mm * ratio * mm),
        Spacer(1, 1.5 * mm),
        P(caption, st["caption"]),
        Spacer(1, 3 * mm),
    ]
    return el


def bullets(st, items):
    out = []
    for it in items:
        out.append(Paragraph(f"•&nbsp;&nbsp;{it}", st["bullet"]))
    return out


def build_story(st):
    S = []
    # ---------------- COVER ----------------
    cover_inner = Table(
        [[P("미국 강건 퀀트 전략<br/>라이브 운영 시스템", st["cover_title"])],
         [Spacer(1, 4 * mm)],
         [P("아키텍처 심층 분석 보고서", st["cover_title2"])],
         ],
        colWidths=[176 * mm],
    )
    cover_inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    cover = Table([[cover_inner]], colWidths=[180 * mm], rowHeights=[108 * mm])
    cover.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    S.append(cover)
    meta = Table(
        [[P("전략: Robust_L60_M63_LV20 (2026-07-19 동결) · 미국 대형주 · 월간 리밸런싱", st["cover_meta"])],
         [P("리서치 → 엄격 검증 → 라이브 운영 전 과정 자동화 파이프라인", st["cover_meta"])],
         [P("작성: 2026-09-02 · 작성자: 김재원", st["cover_meta"])],
         [P("Python 3.11 · pandas · reportlab · matplotlib · Toss OpenAPI", st["cover_meta"])],
         ],
        colWidths=[176 * mm],
    )
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#16304F")),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    S.append(meta)
    # KPI strip
    kpi_rows = [
        ["검증 기간", "2024-01 ~ 2026-07 (31개월)"],
        ["PIT 연환산", "82.5%"],
        ["샤프 지수", "1.89"],
        ["최대 낙폭", "-32.2%"],
        ["엄격 검증", "10/10 게이트"],
        ["코드 규모", "≈ 16,200 LOC"],
    ]
    kpi_t = Table([[P(v, st["kpi_v"]) for v in row] for row in kpi_rows], colWidths=[30 * mm] * 6)
    kpi_t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
    ]))
    S.append(Spacer(1, 5 * mm))
    S.append(kpi_t)
    S.append(Spacer(1, 5 * mm))
    S.append(P("본 보고서는 리서치·백테스트·라이브 운영까지의 전체 시스템을 모듈 단위로 분석한 기술 문서로, "
               "포트폴리오 제출용으로 작성되었습니다. 성과 수치는 동결 정책(2026-07-19 동결)의 사후 엄격 검증 결과 "
               "(results/strict_report, 2026-08 산출)를 기준으로 합니다.", st["small"]))
    S.append(PageBreak())

    # ---------------- TOC ----------------
    S.append(P("목차", st["h1"]))
    toc = TableOfContents()
    toc.levelStyles = [st["toc_e1"], st["toc_e2"]]
    S.append(toc)
    S.append(Spacer(1, 6 * mm))
    S.append(P("※ 본 문서의 모든 경로와 수치는 실제 저장 아티팩트(results/, ops/, research/)에서 발췌한 값입니다.", st["foot"]))
    S.append(PageBreak())

    # ---------------- 1. 개요 ----------------
    S += section("1. 프로젝트 개요", st)
    S.append(P(
        "이 프로젝트는 <b>미국 대형주 강건(robust) 퀀트 전략의 라이브 운영 시스템</b>입니다. 3개 슬리브(핵심 모멘텀 60% · "
        "중기 모멘텀 20% · 저변동성 20%)로 구성된 'Robust_L60_M63_LV20' 정책을 2018년부터의 시장 데이터로 설계하고, "
        "과적합·생존 편향을 통제하는 엄격한 검증 프로세스를 통과한 후, 월별 신호 생성 → 비중 산출 → 안전 게이트 → "
        "Toss 증권 OpenAPI 실제 주문까지 이어지는 <b>종단간 자동화된 운영 파이프라인</b>을 구축한 것이 핵심 성과입니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("1-1. 핵심 설계 원칙", st))
    for b in [
        "Python이 신호의 단일 진실 원천(SoT). Excel은 승인·원장 UI일 뿐 주문의 진실 원천이 아님(CLI_REQUIRED 표시).",
        "Fail-closed 안전 설계. 모든 실주문 경로는 기본 차단(LIVE_ORDERS_ENABLED=False)이며, 게이트 통과 + 인간 승인 후에만 열림.",
        "동결(freeze) 정책. 검증을 통과한 파라미터는 상수로 동결하고, 운영 중 파라미터 튜닝을 금지(과적합 재진입 차단).",
        "이중 검증. ① 동결 시점 검증(2019-07~2026-06, 10/10 게이트) ② 동결 이후 후행 검증(2024-01~2026-07, PIT 유니버스·비용 민감도·퍼터베이션).",
        "모든 산출물이 디스크 아티팩트로 남음(신호·타깃·주문·건강도·체결 로그·주간 NAV) → 감사·재현 가능.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("1-2. 시스템 규모", st))
    S.append(datatable(st,
        ["영역", "모듈", "주요 책임", "규모(LOC)"],
        [
            ["운영 코어", "ops/ (14개 모듈)", "월간 파이프라인·안전 게이트·브로커·Excel 자동화", "≈ 9,455"],
            ["리서치", "research/ (6개 모듈)", "엄격 백테스트·통계 검증·PDF 리포트 생성", "≈ 4,383"],
            ["보고/템플릿", "scripts/ (4개)", "Excel 템플릿·Notion 주간 보고 동기화", "≈ 1,436"],
            ["테스트", "tests/", "라이브 안전·게이트·주간 앵커·Excel 테스트", "≈ 903"],
        ],
        widths=[20 * mm, 44 * mm, 84 * mm, 32 * mm], aligns=["c", "l", "l", "c"]))
    S.append(Spacer(1, 1.5 * mm))
    S.append(P("기술 스택: Python 3.11 / pandas 2.2 / numpy / scipy / matplotlib / reportlab / openpyxl / yfinance / "
               "requests / Toss OpenAPI / Notion API / parquet / pytest", st["small"]))
    S.append(PageBreak())

    # ---------------- 2. 아키텍처 ----------------
    S += section("2. 시스템 아키텍처", st)
    S.append(P("전체 시스템은 6개 계층으로 분리되며, 데이터는 항상 아래에서 위로 단방향으로 흐릅니다. "
               "각 계층의 인터페이스는 명시적 함수(load_market · build_target · evaluate_gates · place_and_await)로 정의되어 "
               "라이브 주문 경로가 리서치 폴리시 상수를 직접 import하지 않도록 분리했습니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    layers = Table([
        [P("① 데이터 계층", st["th"]), P("yfinance SoT → data/us/*.parquet 캐시 · 유니버스 상위 150종 · PIT 유니버스 · 갱신 stale 검사", st["td_left"])],
        [P("② 전략·정책 계층", st["th"]), P("동결 파라미터(60/20/20, 이름 15%, 익일 시가) · 팩터 정의 · 슬리브 선정(select_us_picks)", st["td_left"])],
        [P("③ 월간 운영 계층", st["th"]), P("완료 월 가드 → 선정·비중(build_target) → 주문 티켓 → health.json → 패키지 매니페스트(SHA256)", st["td_left"])],
        [P("④ 원장·보고 계층", st["th"]), P("Excel 워크북 6시트 자동 생성 · 주간 NAV/보유 앵커 · Notion 주간 수익률 동기화", st["td_left"])],
        [P("⑤ 안전·리스크 계층", st["th"]), P("fail-closed 실행 게이트(패키지 검증·계좌 식별·공식 시가 윈도우·고액 확인) · L1/L2 낙폭 서킷 · 원자적 쓰기", st["td_left"])],
        [P("⑥ 브로커 실행 계층", st["th"]), P("Toss OpenAPI 인증·주문 페이로드 · 매도 우선 체결 · 전체 체결 폴링(1초/120초) · 체결 증거 기록", st["td_left"])],
    ], colWidths=[34 * mm, 146 * mm])
    layers.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (0, -1), BLUE),
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    S.append(layers)
    S.append(Spacer(1, 2.5 * mm))
    S.append(P("운영 데이터 흐름(월 1회):", st["h3"]))
    S.append(P(
        ".env(선택 Toss 키) → us_hybrid_backtest / yfinance → ops_us_policy.select_us_picks → "
        "ops_monthly_run.build_target → ops_excel_write(Excel 원장) → 인간 HTS 또는 Toss LIVE 주문 → "
        "ops_daily(주간 NAV) → scripts/update_notion_weekly_table(Notion 보고)", st["quote"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("2-1. 폴리시 동결과 운영 격리", st))
    for b in [
        "정책 상수는 ops/ops_us_policy.py 한 곳에만 존재. 백테스트 로더(us_hybrid_backtest)의 연구용 W_* 가중치는 운영 경로에서 import 금지(테스트로 강제).",
        "KR(국내) 하이브리드·pykrx·KRX+DART 모듈은 운영 진실 원천이 아니며 ops 진입점에서 import 금지 — refresh --kr 명령 자체가 거부됨.",
        "동결 목록: 60/20/20 슬리브 가중치 · 익영업일 시가 체결 · 이름 15%/섹터 40% · 신호 탈락 시에만 청산 · AccumulDiv/펀더멘털 코어/이벤트 NLP/주간 리프레시/Black-Litterman 금지.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(PageBreak())

    # ---------------- 3. 데이터 계층 ----------------
    S += section("3. 데이터 계층 (us_hybrid_backtest.py)", st)
    S.append(P("시장 데이터는 yfinance가 SoT이며, 5종의 parquet 패널로 캐시되어 오프라인 운영이 가능합니다. "
               "캐시 staleness(기본 5일)를 초과하면 refresh 단계에서 재다운로드합니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(datatable(st,
        ["캐시 파일", "내용", "용도"],
        [
            ["us_prices_panel.parquet", "종가 와이드 패널 (2018-01~현재)", "신호·팩터·NAV 평가"],
            ["us_open_panel.parquet", "시가 와이드 패널", "익영업일 시가 체결 백테스트"],
            ["us_volume_panel.parquet", "거래량 와이드 패널", "유동성 랭킹·거래대금 필터"],
            ["spy.parquet", "SPY 종가", "벤치마크·시장 국면(SMA200)"],
            ["us_valuation_panel.parquet", "밸류/TTM 재무 스냅샷", "밸류 팩터(연구용)"],
            ["us_universe_meta.parquet", "유니버스 메타", "구성 종목 관리"],
        ],
        widths=[58 * mm, 70 * mm, 52 * mm], aligns=["l", "l", "l"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("3-1. 유니버스 및 필터", st))
    for b in [
        "운용 유니버스: SPX 구성종목 중 최근 20거래일 평균 거래대금 상위 150종(top_n=150, 동결).",
        "유동성 하한: 평균 거래대금 ≥ $5천만, 주가 ≥ $5.0 — 저유동성 종목 배제.",
        "모든 신호·백테스트는 시점 일관성 유지: 팩터는 후행 롤링 윈도우만 사용(미래 정보 없음).",
        "엄격 검증에서는 신호일 시점의 '과거 252일 가격 이력 + 최근 20일 거래대금 상위'로 PIT(Point-in-Time) 유니버스를 재구축(크기 146~148종)하여 구성종목 변화를 반영.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("3-2. 팩터 계산 (compute_price_features)", st))
    S.append(datatable(st,
        ["팩터 패널", "정의"],
        [
            ["mom_12_1", "12개월-1개월 모멘텀 = P[-21] / P[-252] - 1"],
            ["mom_63", "중기 모멘텀 = P / P[-63] - 1"],
            ["mom_21(단기)", "1개월 모멘텀 = P / P[-21] - 1"],
            ["near_high", "52주 신고가 근접도 = P / 252일 최고가"],
            ["vol_ratio / lowvol", "변동성 급증 비율 · 60일 실현변동성 연환산"],
            ["market_regime", "SPY > SMA200 → 추세↑/↓, 21일 실현변동성 vs 1년 중앙값 → 고/저변동"],
        ],
        widths=[46 * mm, 134 * mm], aligns=["l", "l"]))
    S.append(PageBreak())

    # ---------------- 4. 전략·정책 계층 ----------------
    S += section("4. 전략·정책 계층 (ops_us_policy.py)", st)
    S.append(P("동결 정책 상수는 이 모듈에만 존재하며, 운영·검증 모두 이 상수를 import합니다. "
               "검증 코드가 운영 코드와 같은 함수를 호출하므로 '검증은 별개 구현'이라는 비판 자체가 성립하지 않습니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("4-1. 동결 정책 상수", st))
    S.append(datatable(st,
        ["파라미터", "값", "의미"],
        [
            ["POLICY_NAME", "Robust_L60_M63_LV20", "운영 정책 식별자"],
            ["SLEEVE_WEIGHTS", "0.60 / 0.20 / 0.20", "Leader / Mom63 / LowVol 목표 비중"],
            ["N_LEADER / N_MOM63 / N_LOWVOL", "10 / 10 / 12", "슬리브별 보유 종목 수"],
            ["MAX_NAME", "15%", "개별 종목 비중 상한(초과분 재분배)"],
            ["MAX_SECTOR", "40%", "섹터 상한(best-effort, 강제 게이트 아님)"],
            ["WEIGHT_MODE", "equal_within_sleeve", "슬리브 내 동일 비중(스코어 틸트 없음)"],
            ["COST", "10bp", "편도 왕복 비용 가정"],
            ["EXEC_RULE", "NEXT_OPEN", "신호일 종가 확정 → 익영업일 시가 체결"],
            ["TOP_N_DEFAULT", "150", "운용 유니버스 상한"],
        ],
        widths=[44 * mm, 42 * mm, 94 * mm], aligns=["l", "c", "l"]))
    S.append(Spacer(1, 2.5 * mm))
    S.append(h2("4-2. 슬리브 선정 기준", st))
    S.append(P("① Leader (핵심 모멘텀, 10종)", st["h3"]))
    S.append(P("복합 스코어(시점별 순위 백분위 가중합) + 진입 필터를 모두 통과해야 선정됩니다.", st["body"]))
    S.append(datatable(st,
        ["스코어 구성요소", "가중치", "의미"],
        [
            ["12개월-1개월 모멘텀", "45%", "과거 12개월(최근 1개월 제외) 수익률"],
            ["52주 신고가 근접도", "20%", "252거래일 최고가 대비 현재가 수준"],
            ["중기 모멘텀(63거래일)", "15%", "최근 3개월 수익률"],
            ["변동성 급증 여부", "10%", "단기/중기 변동성 비율"],
            ["단기 모멘텀(21거래일)", "10%", "최근 1개월 수익률"],
        ],
        widths=[52 * mm, 26 * mm, 102 * mm], aligns=["l", "c", "l"]))
    S.append(Spacer(1, 1.5 * mm))
    for b in [
        "진입 필터(모두 충족): 거래대금 ≥ 최소 유동성 · 12개월-1개월 모멘텀 > 0 · 52주 신고가 근접도 ≥ 0.80",
        "시장 국면 조정: 박스장 최대 7종, 약세장 최대 3종 + 신고가 근접도 90% 이상 (낙폭 통제).",
        "동결 이후 AccumulDiv 확인·베어 오버레이 등 과거 보호장치는 사용하지 않음 — 가격 스코어 단독.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(P("② Mom63 (중기 모멘텀, 10종)", st["h3"]))
    S.append(P("63거래일(≈3개월) 수익률이 양(+)인 종목 중 상위 10종. 추가 모멘텀 노출.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(P("③ LowVol (저변동성, 12종)", st["h3"]))
    S.append(P("60거래일 일별 수익률 표준편차의 연환산이 낮은 종목. 단, 12개월-1개월 모멘텀 ≤ -30% 급락 종목은 "
               "방어 목적이라도 배제(낙폭 중인 종목을 저변동성으로 오인하는 것 방지).", st["body"]))
    S.append(Spacer(1, 2.5 * mm))
    S.append(h2("4-3. 심볼 정규화 (normalize_symbol)", st))
    S.append(P("US 티커에 zfill(0 채움)을 절대 적용하지 않는 정규화 함수를 전 경로에서 사용. "
               "과거 KR 경로의 6자리 코드 관습이 US 티커에 유출되는 것을 코드 수준에서 차단합니다.", st["body"]))
    S.append(PageBreak())

    # ---------------- 5. 월간 운영 파이프라인 ----------------
    S += section("5. 월간 운영 파이프라인 (ops.py · ops_monthly_run.py)", st)
    S.append(P("CLI는 절차 지향 단계(0~8)로 구성되어 있습니다. 전체 실행은 'python ops.py monthly' 한 명령으로 "
               "신호 선정 → 비중 산출 → 주문 티켓 → 건강도 → Excel 자동 기입까지 수행합니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(datatable(st,
        ["단계", "명령", "수행 내용"],
        [
            ["0", "ops.py status", "시크릿 존재 여부·캐시 최신성 점검(값 출력 금지)"],
            ["1", "ops.py refresh", "US 패널 yfinance 갱신(KR 경로 거부)"],
            ["2-5", "ops.py monthly", "신호(select_us_picks) → 타깃(build_target) → 주문 티켓(classify_actions) → health → Excel"],
            ["5", "ops.py excel", "기존 run 디렉토리에서 Excel 재생성"],
            ["6", "ops.py rebalance", "동결 타깃 + 라이브 북(계좌) 기반 매수/매도 티켓 재구축"],
            ["7", "ops.py execute --risk-mode NORMAL|L1|L2", "게이트 검증 후 Toss 실주문 매도 우선 (LIVE 활성 시)"],
            ["8", "ops.py weekly", "주간 앵커 NAV 스냅샷 기록 + Notion 자산"],
        ],
        widths=[14 * mm, 66 * mm, 100 * mm], aligns=["c", "l", "l"]))
    S.append(Spacer(1, 2.5 * mm))
    S.append(h2("5-1. build_target — 타깃 비중 산출", st))
    for b in [
        "슬리브 내 동일 비중 → 슬리브 가중치(60/20/20) 적용 → 개별 종목 15% 상한 초과분은 나머지 종목에 재분배.",
        "슬리브가 비었거나 상한 여분이 남으면 잔여분은 현금(sleep) 처리 — 무리한 강제 투자 금지.",
        "10bp 왕복 비용 가정은 리서치·운영 모두 동일(COST=0.001) 적용.",
        "산출물 검증 함수(validate_target): 비중 합계 ≤ 1 · 종목별 15% 상한 · 심볼 유효성 · weight_sum > 1이면 BLOCK.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("5-2. 완료 월 가드 (is_final_month_end_signal)", st))
    S.append(P("신호일이 '완료된 뉴욕 월'의 마지막 거래일일 때만 월간 실행을 허용합니다. 미완료 월 신호는 "
               "--force-intramonth 없이 거부(SystemExit 3). 캐시 마지막 날짜와 신호일 간 lag 3일 초과 시 BLOCK.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("5-3. 패키지 매니페스트 (package_manifest.json)", st))
    S.append(P("매 월 실행 시 signals.csv·target.csv의 SHA256 해시와 package_id를 매니페스트로 고정합니다. "
               "execute 단계에서 재검증하므로, 실행 전 신호/타깃이 '해시 무결성' 없이는 주문 경로에 진입할 수 없습니다. "
               "pytest에서 변조(tamper) 감지 테스트가 포함되어 있습니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("5-4. 월간 산출물 (results/ops_runs/YYYY-MM/)", st))
    S.append(datatable(st,
        ["아티팩트", "내용"],
        [
            ["signals.csv / target.csv", "슬리브별 종목 선정 및 최종 비중 (SoT)"],
            ["orders_preview.csv", "매수/매도/홀드 사전 티켓"],
            ["health.json", "정책 준수·사이징·현금 커버리지 상태 (BLOCK/WARN/OK)"],
            ["package_manifest.json", "signals/target SHA256 + package_id (불변)"],
            ["US_Robust_Ops_YYYY-MM.xlsx", "6시트 승인·원장 워크북"],
            ["execute_send_list.json / attempts / fills_*.jsonl", "실행 전송 목록·시도·체결 증거"],
            ["daily_nav.csv / daily_holdings.csv", "주간 앵커 NAV·보유 스냅샷(월별 파일, 읽는 쪽에서 통합)"],
        ],
        widths=[66 * mm, 114 * mm], aligns=["l", "l"]))
    S.append(PageBreak())

    # ---------------- 6. Excel 원장 ----------------
    S += section("6. 엑셀 원장 (ops_excel_write.py)", st)
    S.append(P("Excel은 '승인·원장 UI'입니다. 값은 항상 Python 산출물에서 채워지며(엑셀에서 알파 재계산 금지) "
               "주문의 진실 원천은 설계상 CLI입니다. 템플릿의 시연 데이터·병합·행 높이·샘플 보유가 운영 워크북으로 "
               "새지 않도록 01/02/05 시트는 매 실행마다 처음부터 재구축합니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(datatable(st,
        ["시트", "내용"],
        [
            ["01_Account", "계좌 상태(자산·현금·보유 현황)"],
            ["02_Screen_Select", "슬리브별 선정 종목(leader/mom63/lowvol만)"],
            ["03_Target", "목표 비중·개별 15% 상한 검증"],
            ["04_Health", "health.json 상태(BLOCK 시 강조)"],
            ["05_Trade", "매도 우선 주문 티켓 + CLI_REQUIRED 표시"],
            ["06_Weekly_Trend", "주간 NAV·SPY·수익률 추이"],
        ],
        widths=[40 * mm, 140 * mm], aligns=["l", "l"]))
    S.append(Spacer(1, 2 * mm))
    for b in [
        "openpyxl 기반 자동화 — 템플릿 마스터 유지(report 수정 시 재생성) 후 월별 워크북만 갱신.",
        "셀 값은 sanitize_excel_value로 방어: '='·'+'·'-'·'@'·탭·개행으로 시작하는 값을 quoting 처리(수식 주입 방지).",
        "차트(라인/바/파이) 자동 삽입, 셀 서식·너비·색상 표준화, 잘못된 매크로/자동 승인 기능 없음(테스트로 검증).",
        "실행 상태(execute_status.json)는 워크북 재생성 시 재병합되어 체결 상태가 원장에 영속됨.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2.5 * mm))
    S.append(h2("6-1. 주간 NAV 모니터링 (ops_daily.py)", st))
    for b in [
        "ISO 주 단위 '마지막 미국 거래일(보통 금요일)'을 앵커로 계좌 총자산·현금·보유 수량 스냅샷(주 1행).",
        "Mon~Thu는 no-op, 주말 실행 시 금요일 앵커 기록, 누락 주는 다음 앵커에서 백필하여 주간 수익률 시계열이 끊기지 않음.",
        "레거시 일별 CSV는 최초 1회 주간 앵커로 압축(.bak 보존), 이후 재계산·통합 — 명확한 마이그레이션 경로.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(PageBreak())

    # ---------------- 7. 안전·리스크 계층 ----------------
    S += section("7. 안전·리스크 계층 (ops_live_safety.py · ops_execute_gates.py)", st)
    S.append(P("라이브 주문 경로는 <b>기본 차단(fail-closed)</b>입니다. 모든 안전 규칙은 이 모듈에 집중되어 있으며, "
               "execute는 단일 진입점(ops.py execute)으로만 실주문이 가능합니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("7-1. 실행 전 게이트 (evaluate_gates)", st))
    S.append(datatable(st,
        ["게이트", "규칙"],
        [
            ["패키지 검증", "매니페스트 SHA256 재검증 · 실행 가능 연령 ≤ 7일 · 완료 월 신호 확인"],
            ["공식 익영업일 시가 윈도우", "다음 미국 거래일 + 정규장 시작 30분 창 내에서만 실행(validate_official_next_open)"],
            ["계좌 식별", "Toss 계좌 유형(BROKERAGE)·계좌 번호 일치 확인"],
            ["주문 행 유일성", "code×side 중복 행 거부(validate_unique_rows)"],
            ["최소·상한", "매수 ≥ $1 · 이름 수 ≤ 40 · 개별 비중 ≤ 15%"],
            ["현금 버퍼", "예상 체결금액의 2% 버퍼 — 현금 부족 시 BLOCK"],
            ["고액 확인", "단일 주문 ≥ $70,000는 명시적 확인 요구"],
            ["매도 우선 2단계 게이트", "매도 FULL_FILL 확인 후 매수 전 재검증(LIVE_BLOCKED 없이 진행 불가)"],
        ],
        widths=[42 * mm, 138 * mm], aligns=["l", "l"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("7-2. 실행 클레임·증거 (acquire_execution_claim / execution_evidence)", st))
    for b in [
        "실행 전 원자적 클레임(claim) 파일을 획득 — 중복 실행/동시 실행을 파일 시스템 수준에서 차단.",
        "모든 시도(생성·체결·오류·타임아웃)는 executes_attempt/attempt_result/fills JSONL에 구조화 기록.",
        "PARTIAL/타임아웃은 전체 체결(full-fill) 정책상 실패 처리; ZERO_REJECT·TIMEOUT_OPEN은 자동 재시도, REVIEW_REQUIRED는 인간 개입 요구.",
        "0건 HTTP POST(게이트 실패)와 체결 발생 상태를 구분해 감사 — '실행했다'는 증거 없이는 기록되지 않음.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("7-3. 낙폭 서킷 (risk-mode NORMAL/L1/L2)", st))
    S.append(datatable(st,
        ["모드", "조건", "동작"],
        [
            ["NORMAL", "기본", "동결 정책 가중치 그대로 실행"],
            ["L1", "포트폴리오 낙폭 ≤ -15%", "총노출 50% 축소(apply_risk_weights)"],
            ["L2", "낙폭 ≤ -25%", "매수 중단·방어적 매도, 상태 sticky — 해제는 명시적 승인 문자열(reset_sticky_l2)만 가능"],
        ],
        widths=[26 * mm, 52 * mm, 102 * mm], aligns=["c", "l", "l"]))
    S.append(Spacer(1, 1.5 * mm))
    S.append(P("리스크 상태는 results/ops_state/manual_risk_*.json에 계좌별로 저장되어, L2 해제 없이는 "
               "재실행해도 축소 모드가 유지됩니다(휘발성 상태 금지).", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("7-4. 원자적 쓰기·인코딩 방어", st))
    S.append(P("atomic_write_text/json/csv를 통해 부분 쓰기로 인한 손상 파일이 감사 경로에 들어가지 않도록 했고, "
               "CSV는 UTF-8 BOM(utf-8-sig)로 Excel 한글 호환을 보장합니다.", st["body"]))
    S.append(PageBreak())

    # ---------------- 8. 브로커 실행 계층 ----------------
    S += section("8. 브로커 실행 계층 (toss_portfolio.py · toss_orders.py)", st)
    S.append(P("Toss 증권 OpenAPI(openapi.tossinvest.com)를 사용합니다. 포트폴리오 조회는 읽기 전용이며, "
               "주문 전송은 단 하나의 클라이언트(OrderClient.place_and_await)를 통해서만 가능합니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("8-1. 구현 상세", st))
    for b in [
        "인증: API 키+시크릿 base64 → Bearer 토큰. 시크릿은 .env(로컬, gitignore)에서만 로드, 어떤 경로에서도 값 출력 금지.",
        "계좌 선택: accountType=BROKERAGE 필터 + 계좌 2개 이상 시 PIN 입력 강제(실수 방지).",
        "주문 페이로드: 분수주(fractional) 지원, 주문금액 상한 기반(미국 정수주 강제 아님), client_order_id ≤ 36자 고유키.",
        "체결 대기: 1초 간격 폴링, 최대 120초, HTTP 429는 1/2/4/8초 지수 백오프 최대 3회.",
        "전체 체결만 승인(부분 체결은 실패 처리) — '부분으로 남은 포지션'이 원장과 어긋나는 것을 원천 차단.",
        "매도 우선: SELL 행을 먼저 체결하고 매도 대금으로 매수 자금을 산정(rebuild_rebalance_ticket).",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("8-2. LIVE 전환 절차와 실제 운영 이력", st))
    S.append(P("docs/toss_order_api_research.md의 체크리스트 1~4항(계좌·주문 스키마·부분체결·취소)을 연구로 잠그고 "
               "Pre-LIVE 인간 승인 후에만 LIVE_ORDERS_ENABLED=True가 되며(2026-07-20 승인), "
               "그 전까지는 모든 시도가 LIVE_BLOCKED로 기록됩니다. 실제 체결 로그(fills_*.jsonl)에 남은 이력:", st["body"]))
    S.append(datatable(st,
        ["시각 (UTC)", "이벤트", "내용"],
        [
            ["2026-07-19 17:03", "LIVE_BLOCKED", "게이트 통과 전 실주문 차단 확인(2건)"],
            ["2026-07-20 15:17", "FILL (SELL)", "실계좌 첫 체결 — QQQ 매도 완료"],
            ["2026-07-20 15:18 / 18:11", "ERROR (BUY)", "CRWD 주문 400 응답을 구조화 로그로 기록(재시도 대상 식별)"],
            ["2026-08-03 15:53", "FILL ×29", "2026-08 신호 익영업일 시가 기준 매수 29건 전체 체결"],
        ],
        widths=[40 * mm, 30 * mm, 110 * mm], aligns=["l", "c", "l"]))
    S.append(Spacer(1, 1.5 * mm))
    S.append(P("※ 실계좌는 분수주 테스트 규모(약 $70)의 소액 북으로, 시장 충격과는 무관한 '경로 검증용' 라이브 운용입니다. "
               "execute_attempt_result.json의 status=DONE과 package_id가 매 실행마다 남습니다.", st["small"]))
    S.append(PageBreak())

    # ---------------- 9. 검증·품질 엔지니어링 ----------------
    S += section("9. 검증 · 품질 엔지니어링", st)
    S.append(h2("9-1. 동결 시점 검증 (2019-07 ~ 2026-06, 월간 신호 84회)", st))
    S.append(P("동결 전 연구 단계의 공식 검증입니다. 사전 정의 10개 게이트를 모두 통과해야 채택했습니다.", st["body"]))
    S.append(datatable(st,
        ["지표", "전략", "벤치마크(SPY)", "게이트"],
        [
            ["연환산 수익률", "49.0%", "16.0%", "G1: 벤치+1%p 초과 ✅"],
            ["샤프 지수", "1.54", "-", "G2: ≥ 0.6 ✅"],
            ["최대 낙폭", "-30.4%", "-33.7%", "G3: 벤치보다 양호 ✅"],
            ["알파", "26.7%", "-", "G4: > 2% ✅"],
            ["정보비율", "1.37", "-", "G5: > 0.2 ✅"],
            ["표본 외(OOS) 성과", "IR 1.93 / α 47.2%", "-", "G6 ✅"],
            ["교차검증 5구간", "초과수익 5/5", "-", "G8·G9 (중앙값 +23.8%) ✅"],
            ["부트스트랩(1,000회)", "초과수익 양(+) 확률 100%", "-", "G10 ✅"],
        ],
        widths=[40 * mm, 62 * mm, 30 * mm, 48 * mm], aligns=["l", "l", "c", "l"]))
    S.append(Spacer(1, 1.5 * mm))
    S.append(P("비용 스트레스(20bp)에서도 연환산 48.1%·샤프 1.52·10/10 유지 — 비용 2배에도 성과 열화 미미.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("9-2. 동결 이후 엄격 후행 검증 (2024-01 ~ 2026-07, 31개월)", st))
    S.append(P("동결 후 재현(research/strict_edge_report.py)으로, 검증 장치를 한층 강화했습니다:", st["body"]))
    for b in [
        "PIT 유니버스: 신호일 시점 거래대금 상위 150종 + 252일 이력 요건. 구성종목 '변경에 따른 미래 정보'를 제거.",
        "비용 민감도: 0bp / 10bp(기본) / 20bp(스트레스) — CAGR 83.6% / 82.5% / 81.5%로 열화 미미(비용 강건성).",
        "룩어헤드 대조: 신호일 종가 체결 대비 익일 시가 체결의 차이 -6.5%p — NEXT_OPEN 규칙이 회피하는 편향을 수치화.",
        "유니버스 민감도: top_n 100/125/150 → CAGR 61.8% / 75.7% / 82.5% — 상한을 넓힐수록 개선(경계값에 예민하지 않음).",
        "파라미터 퍼터베이션: 슬리브 종목 수 × 3×3×3 = 27조합 전부 초과수익 양(+) — 동결 지점이 '칼날 위'가 아니라 '고원(plateau)' 위임을 확인(전부 양성일 확률 p=7.5e-09).",
        "통계 검정: 월간 초과수익(전략-벤치) t=2.49, 승률 71% · iid 부트스트랩 99.3% / 블록(4개월) 부트스트랩 99.2% 양(+) 확률.",
        "CAPM 알파: 벤치 대비 연 36.3%(t=1.72) / 동일 유니버스 EW 대비 연 17.9% — '선택 능력'과 '유니버스 틸트' 분해.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("9-3. as-if 테스트 — 라이브 신호와의 대조", st))
    S.append(P("research/strict_asif_test.py는 라이브 운영과 동일한 코드 경로(build_target)로 월말 신호를 재생성해 "
               "실제 라이브 신호(signals.csv)와 비교합니다. 2026-07-31 신호 기준 슬리브 종목 수 10/10/12 일치, "
               "타깃 최대 차이 1.7%p(동결 고정 유니버스 기준)로 재현성을 검증했습니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("9-4. 자동화 테스트 (tests/test_ops_live_safety.py)", st))
    S.append(datatable(st,
        ["영역", "대표 테스트 항목"],
        [
            ["실행 안전", "매니페스트 변조 감지 · 익영업일 시가 윈도우 · 계좌 PIN 강제 · 고액 확인 · 현금 버퍼 · 최소 주문"],
            ["주문 클라이언트", "분수주 페이로드 · 부분/타임아웃 시 전체 체결 불허 · 0건 HTTP 게이트 실패 구분 · 재시도 클레임"],
            ["원장·Excel", "자동 승인/가짜 결과 없음 · 실행 결과 병합 · stales 북 표시 · 템플릿 보존"],
            ["주간 앵커", "금요일/휴일 앵커 · 주중 실행 거부 · 누락 주 백필 · 레거시 일별→주간 압축"],
            ["네트워크", "실제 HTTP 금지 fixture(요청 시 pytest 실패) — 외부 의존성 없는 결정적 테스트"],
        ],
        widths=[34 * mm, 146 * mm], aligns=["l", "l"]))
    S.append(Spacer(1, 1.5 * mm))
    S.append(P("QA 증거 아티팩트(results/qa_evidence/)에 CLI 리플레이·레드팀 grep·cp949 스캔·원장 해시 비교 등 "
               "단계별 검증 산출물을 보관해 재현성을 확보했습니다.", st["small"]))
    S.append(PageBreak())

    # ---------------- 10. 성과 요약 ----------------
    S += section("10. 성과 요약 (엄격 후행 검증 기준)", st)
    S.append(P("기준: 2024-01 ~ 2026-07 · PIT 유니버스(상위 150) · 익영업일 시가 · 10bp 비용. "
               "하단 차트는 업계 관례대로 결과 화면을 그대로 인용합니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(datatable(st,
        ["지표", "전략(PIT)", "전략(고정 유니버스)", "EW 동일 유니버스", "SPY"],
        [
            ["총수익률", "371.3%", "404.7%", "113.4%", "62.8%"],
            ["연환산(CAGR)", "82.5%", "87.5%", "34.2%", "20.8%"],
            ["변동성", "35.3%", "35.7%", "19.0%", "15.8%"],
            ["샤프", "1.89", "1.95", "1.65", "1.28"],
            ["최대 낙폭", "-32.2%", "-32.2%", "-24.1%", "-18.8%"],
            ["캘마", "2.56", "2.71", "1.42", "1.11"],
            ["정보비율", "1.59", "1.67", "-", "-"],
            ["알파(연)", "40.6%", "43.2%", "8.4%", "≈0%"],
            ["월간 승률", "66.7%", "66.7%", "80.0%", "70.0%"],
        ],
        widths=[34 * mm, 38 * mm, 40 * mm, 36 * mm, 32 * mm], aligns=["l", "c", "c", "c", "c"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("10-1. 연도별·레짐별 성과", st))
    S.append(datatable(st,
        ["구간", "전략", "샤프", "낙폭", "SPY", "연환산 초과"],
        [
            ["2024 (12개월)", "+66.3%", "1.91", "-18.7%", "+25.6%", "+36.9%p"],
            ["2025 (12개월)", "+56.5%", "1.75", "-25.1%", "+17.7%", "+35.0%p"],
            ["2026 상반기 (6개월)", "+140.9%", "3.65", "-14.2%", "+10.1%", "+403.5%p"],
            ["2026-07 (1개월)", "-24.8%", "-3.99", "-23.9%", "+0.03%", "-96.8%p"],
        ],
        widths=[34 * mm, 30 * mm, 24 * mm, 30 * mm, 28 * mm, 34 * mm], aligns=["l", "c", "c", "c", "c", "c"]))
    S.append(Spacer(1, 1.5 * mm))
    S.append(P("레짐별(2026-07 말 기준): 강세 22개월 연환산 127.3%·초과 92.3%·승률 72.7% / 박스 6개월 연환산 -12.2%·초과 -16.4% / "
               "약세 3개월 연환산 165.8%(표본 3개월로 해석 주의). 2026-07의 -24.8%는 박스 국면에서 Leader -34.1%·Mom63 -23.4%, "
               "그 와중에 LowVol +4.2%로 방어 역할을 확인했습니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("10-2. 슬리브별 기여", st))
    S.append(datatable(st,
        ["슬리브", "CAGR", "샤프", "낙폭", "알파", "베타"],
        [
            ["Leader", "90.5%", "1.71", "-43.7%", "46.8%", "1.35"],
            ["Mom63", "124.6%", "1.98", "-36.8%", "57.7%", "1.70"],
            ["LowVol", "6.5%", "0.56", "-12.2%", "-0.02%", "0.35"],
        ],
        widths=[30 * mm, 32 * mm, 30 * mm, 38 * mm, 30 * mm, 20 * mm], aligns=["l", "c", "c", "c", "c", "c"]))
    S.append(Spacer(1, 1.5 * mm))
    S.append(P("슬리브 월수익률 상관: Leader×Mom63 0.90(유의) / Leader×LowVol 0.01(미유의) / Mom63×LowVol 0.03(미유의) — "
               "모멘텀 묶음과 저변동성의 상관이 사실상 0에 가까워 분산 효과의 설계 근거가 됩니다.", st["body"]))
    S.append(Spacer(1, 2 * mm))
    S.append(h2("10-3. 운영 특성", st))
    S.append(P("월 평균 회전율 51.3%(최대 78.7%), 회전 비용 드래그 연 63.4bp, 평균 보유 종목 25.6종, "
               "평균 최대 섹터 비중 44.5%(섹터 40%는 best-effort 상한). 동결 후 첫 신호(2026-08 부분월, 10거래일) "
               "전략 +2.36% vs SPY +3.92%로 초과 -1.56%p를 기록했습니다.", st["body"]))
    for c in [("c1_equity.png", "그림 1. 전략·동일 유니버스·SPY 누적 수익곡선 (2024-01~2026-07)"),
              ("c3_regime.png", "그림 2. 시장 국면(추세×변동성)별 월별 수익률 분포"),
              ("c7_grid.png", "그림 3. 파라미터 퍼터베이션 27조합 — 동결 지점이 고원(plateau) 위에 위치"),
              ("c6_dd.png", "그림 4. 전략 vs SPY 낙폭 에피소드 비교")]:
        S += chart(st, c[0], c[1])
    S.append(PageBreak())

    # ---------------- 11. 한계 ----------------
    S += section("11. 한계 및 리스크 고지", st)
    S.append(P("성과 검증의 한계를 명시적으로 보고하고 있습니다(문서·코드 주석 모두):", st["body"]))
    S.append(Spacer(1, 1.5 * mm))
    for b in [
        "생존 편향: 유니버스가 현재 구성종목 기준(과거 상장폐지 종목 부재) → 과거 성과가 다소 과대평가될 가능성이 있으며, 그 방향을 수량화해 보고합니다.",
        "표본 크기: 월간 신호 84회(동결 검증) / 31개월(후행 검증) — 부트스트랩·교차검증으로 보완했으나 통계적으로 완전한 검증은 어렵습니다.",
        "레짐 의존성: 모멘텀 전략 특성상 강세·추세장에서 성과가 집중되며, 박스장에서는 초과 -16.4%p(연환산)로 약해집니다(2026-07 -24.8% 기록).",
        "백테스트-라이브 차이: 백테스트(119~150종)와 라이브 유니버스, 분수주 체결, 실거래 비용·시장 충격·슬리피지 미반영.",
        "라이브 규모: 현재 실계좌는 경로 검증용 소액 북(약 $70)으로, 대규모 자본 운용 시 성과가 동일하다고 단정할 수 없음.",
        "본 문서의 수치는 과거 데이터 기반이며 미래 성과를 보장하지 않습니다.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 3 * mm))
    S += section("12. 결론 — 무엇을 만들었는가", st)
    S.append(P(
        "이 프로젝트는 단일 전략의 백테스트가 아니라, <b>리서치 → 검증 → 실운영</b>의 전 과정을 설계 사상으로 엮은 "
        "시스템입니다. 핵심은 세 가지입니다.", st["body"]))
    S.append(Spacer(1, 1.5 * mm))
    for b in [
        "① 진실 원천 분리 — 신호는 Python, 승인·원장은 Excel, 체결은 브로커. 각 경계를 명시적 함수와 아티팩트로 고정.",
        "② 검증의 공학화 — 10개 사전 게이트, PIT 유니버스, 비용·룩어헤드·유니버스·파라미터 4축 민감도, 부트스트랩·t-검정. '된다'가 아니라 '어떤 가정에서 왜 되는지'를 수량화.",
        "③ 실전 안전 설계 — fail-closed 주문 경로, SHA256 패키지 무결성, 공식 시가 윈도우, L2 스티키 서킷, 원자적 감사 로그. 자동화가 위험을 숨기지 않고 위험을 통제하도록 설계.",
    ]:
        S.append(Paragraph(f"•&nbsp;&nbsp;{b}", st["bullet"]))
    S.append(Spacer(1, 2 * mm))
    S.append(P("검증된 성과(2024-01~2026-07 PIT 기준 연환산 82.5%, 샤프 1.89, 27조합 퍼터베이션 전부 양성)와 "
               "실계좌 체결(2026-07-20 첫 매도, 2026-08-04 매수 29건 전체 체결)이라는 라이브 증거를 함께 확보했습니다.", st["body"]))
    S.append(Spacer(1, 3 * mm))
    S += section("부록 A. 모듈별 파일 매핑", st)
    S.append(datatable(st,
        ["계층", "파일", "핵심 책임"],
        [
            ["데이터", "ops/us_hybrid_backtest.py", "yfinance SoT · parquet 캐시 · 유니버스 · 팩터 · 연구용 백테스트"],
            ["정책", "ops/ops_us_policy.py", "동결 상수 · 슬리브 선정 · 심볼 정규화"],
            ["운영", "ops/ops_monthly_run.py", "월간 실행 · build_target · health · 티켓 · 매니페스트"],
            ["CLI", "ops/ops.py", "status/refresh/monthly/excel/weekly/rebalance/execute 진입점"],
            ["원장", "ops/ops_excel_write.py", "6시트 워크북 자동화 · 차트 · 실행 상태 병합"],
            ["모니터링", "ops/ops_daily.py", "주간 앵커 NAV/보유 · 백필 · 레거시 압축"],
            ["안전", "ops/ops_live_safety.py", "게이트 · 클레임/증거 · L1/L2 서킷 · 원자적 쓰기"],
            ["게이트", "ops/ops_execute_gates.py", "cross_check · send_list · 2단계 평가"],
            ["실행", "ops/ops_execute.py", "execute 오케스트레이션 · 상태 병합"],
            ["브로커", "ops/toss_orders.py · toss_portfolio.py", "Toss OpenAPI 주문·조회 클라이언트"],
            ["엔비", "ops/ops_env.py", ".env 로더 · 시크릿 존재 확인"],
            ["검증", "research/strict_edge_report.py", "PIT 엄격 백테스트 · 통계 · 퍼터베이션"],
            ["검증", "research/strict_asif_test.py", "라이브 신호 대조 as-if 재현"],
            ["리포트", "research/make_*_pdf.py", "한글 PDF 리포트 생성(reportlab)"],
            ["보고", "scripts/update_notion_weekly_table.py 외", "Notion 주간 테이블 · Excel 템플릿 생성"],
            ["테스트", "tests/test_ops_live_safety.py", "안전·게이트·원장·주간 앵커 자동화 테스트"],
        ],
        widths=[20 * mm, 52 * mm, 108 * mm], aligns=["c", "l", "l"]))
    S.append(Spacer(1, 2 * mm))
    S += section("부록 B. 주요 실행 명령", st)
    S.append(P("python ops.py status / refresh / monthly / excel --run-dir results/ops_runs/YYYY-MM / "
               "rebalance / weekly / execute --risk-mode NORMAL", st["quote"]))
    S.append(Spacer(1, 2 * mm))
    S.append(P("검증 재현: python research/strict_edge_report.py → results/strict_report/ (metrics.json · 차트) / "
               "python research/strict_asif_test.py → results/strict_asif/ · pytest tests/ -q", st["quote"]))
    S.append(Spacer(1, 4 * mm))
    S.append(P("— 자료 끝 —", st["caption"]))
    return S


def main():
    RES.mkdir(parents=True, exist_ok=True)
    reg, bold = fonts()
    st = styles(reg, bold)
    doc = Doc(str(OUT), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
              topMargin=16 * mm, bottomMargin=16 * mm,
              title="미국 강건 퀀트 라이브 운영 시스템 — 아키텍처 분석 보고서",
              author="김재원",
              subject="Robust_L60_M63_LV20 아키텍처 심층 분석")
    story = build_story(st)
    doc.multiBuild(story)
    print(f"OK -> {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()