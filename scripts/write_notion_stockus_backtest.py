"""Write the as-if backtest section onto the Notion Stock_US main page.

Content source: results/strict_asif/*.csv + metrics.json (strict_asif_test.py output).
Re-runnable: deletes the previously written section (heading_2 "8. as-if 백테스트" .. next heading_2)
and re-appends it at the page end.

SAFETY: the section is ALWAYS appended at the page end. This Notion API version rejects
positional insert ("after"), and reordering other blocks is forbidden — moving the
"월별 기록" placeholder once deleted a nested sub-page (2026-08) along with its content
(it was recovered by rebuilding from results/ops_runs CSVs). A guard refuses to delete
any block with nested children (child_page / toggle / bullet children).
Uses the global Notion skill conventions: PAT at ~/.notion-cli/token, Notion-Version 2026-03-11.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
TOKEN = (Path.home() / ".notion-cli" / "token").read_text(encoding="utf-8").strip()
BASE = "https://api.notion.com/v1"
PAGE = "5e91bb8f-28d7-443c-ac21-b1f1cf64d0df"  # Stock_US main page
SECTION = "8. as-if 백테스트 — 동결 전략 그대로 재현 (2025-01 ~ 2026-07)"
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2026-03-11"}

SRC = ROOT / "results" / "strict_asif"
REGIME_KR = {"bull": "상승", "sideways": "박스", "bear": "약세"}


def cell(text):
    return [{"type": "text", "text": {"content": str(text)}}]


def pct(v):
    return f"{float(v) * 100:+.2f}%" if v == v and v is not None else ""


def heading_2(text):
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": cell(text)}}


def heading_3(text):
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": cell(text)}}


def para(text):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": cell(text)}}


def bullet(text):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": cell(text)}}


def table(headers, rows):
    return {
        "object": "block", "type": "table",
        "table": {
            "table_width": len(headers), "has_column_header": True, "has_row_header": False,
            "children": [
                {"object": "block", "type": "table_row",
                 "table_row": {"cells": [cell(h) for h in headers]}}
            ] + [
                {"object": "block", "type": "table_row",
                 "table_row": {"cells": [cell(v) for v in r]}} for r in rows
            ],
        },
    }


def build_children():
    m = json.loads((SRC / "metrics.json").read_text(encoding="utf-8"))
    st, bs = m["stats"], m["bench"]
    mr = pd.read_csv(SRC / "monthly_returns.csv", index_col=0, parse_dates=True)
    eq = pd.read_csv(SRC / "equity.csv", index_col=0, parse_dates=True)
    mt = pd.read_csv(SRC / "monthly_table.csv")

    # ---- monthly-frequency stats from monthly_returns.csv / equity.csv ----
    s, b = mr["strat_ret"], mr["spy_ret"]
    ex = mr["excess"]
    n = len(s)
    msharpe = float(s.mean() / s.std(ddof=1) * (12 ** 0.5)) if n > 1 and s.std(ddof=1) > 0 else None
    mvol = float(s.std(ddof=1) * (12 ** 0.5))
    wins = int((s > 0).sum())
    ex_wins = int((ex > 0).sum())
    eqm = eq["STRAT"].resample("ME").last()
    eqm = eqm[eqm.index <= pd.Timestamp("2026-07-31")]
    y25 = float(eq["STRAT"].loc["2025-12-31"] / eq["STRAT"].loc["2025-01-02"] - 1)
    y25b = float(eq["SPY"].loc["2025-12-31"] / eq["SPY"].loc["2025-01-02"] - 1)
    y26 = float(eq["STRAT"].loc["2026-07-31"] / eq["STRAT"].loc["2025-12-31"] - 1)
    y26b = float(eq["SPY"].loc["2026-07-31"] / eq["SPY"].loc["2025-12-31"] - 1)
    best3 = mr["strat_ret"].nlargest(3)
    worst3 = mr["strat_ret"].nsmallest(3)

    vs, uni, boot = m["variant_stats"], m["universe_sensitivity"], m["bootstrap_monthly_excess"]

    # ---- monthly performance table ----
    m_rows = []
    for _, r in mt.iterrows():
        m_rows.append([
            r["month"],
            f"{r['signal'][5:]}→{r['exec'][5:]}",
            REGIME_KR.get(r["regime"], r["regime"]),
            f"{int(r['n_leader'])}/{int(r['n_mom63'])}/{int(r['n_lowvol'])}",
            f"{float(r['turnover']):.2f}",
            pct(r["strat_ret"]), pct(r["spy_ret"]), pct(r["excess"]),
            f"{float(r['equity_end']) / 1e4:,.0f}만",
        ])

    # ---- summary stats table ----
    def row(label, sv, bv=""):
        return [label, str(sv), str(bv)]

    sum_rows = [
        row("누적 수익률 (2025-01 ~ 2026-07)", pct(st["total_return"]), pct(bs["total_return"])),
        row("연환산 (CAGR)", pct(st["cagr"]), pct(bs["cagr"])),
        row("샤프 (일별)", f"{st['sharpe']}", "—"),
        row("최대 낙폭 (일별)", pct(st["mdd"]), pct(bs["mdd"])),
        row("변동성 (일별 연환산)", pct(st["vol"]), "—"),
        row("정보비율 / 알파 / 베타", f"{st['info_ratio']} / {pct(st['alpha'])} / {st['beta']}", "—"),
        row("월간 샤프 (월말 기준)", f"{msharpe:.2f}", "—"),
        row("월간 변동성 (연환산)", pct(mvol), "—"),
        row("월간 승률", f"{wins}/{n} = {wins / n:.1%}", "—"),
        row("월간 초과승률", f"{ex_wins}/{n} = {ex_wins / n:.1%}", "—"),
        row("2025년", pct(y25), pct(y25b)),
        row("2026년 1~7월", pct(y26), pct(y26b)),
        row("월평균 / 월 최고 / 월 최악",
            f"{pct(s.mean())} / {pct(best3.iloc[0])} / {pct(worst3.iloc[0])}", "—"),
        row("월평균 턴오버 / 연간 비용", f"{float(m['turnover']['mean']):.1%} / "
            f"{float(m['cost_drag_bps_ann']):.0f}bp", "—"),
    ]

    # ---- strictness / bias check table ----
    chk_rows = [
        ["선견 편향 (신호일 종가 체결 시)",
         f"CAGR {pct(vs['signal_close_10bp']['cagr'])} vs 기본 {pct(vs['base_10bp']['cagr'])}",
         "NEXT_OPEN 규칙이 성과를 부풀리지 않음"],
        ["비용 0bp / 10bp / 20bp",
         f"{pct(vs['cost_0bp']['cagr'])} / {pct(vs['base_10bp']['cagr'])} / {pct(vs['cost_20bp']['cagr'])}",
         "비용 민감도 낮음"],
        ["유니버스 top 100 / 125 / 150",
         f"{pct(uni['100']['cagr'])} / {pct(uni['125']['cagr'])} / {pct(uni['150']['cagr'])}",
         "유니버스 크기와 무관하게 방향 일관"],
        ["월간 초과 부트스트랩 (19개월)",
         f"연초과 {pct(boot['obs_ann_excess'])}, t={boot['t_stat']}, "
         f"P(초과>0)={boot['prob_positive']:.0%}, 90% CI [{pct(boot['boot_p5'])}, {pct(boot['boot_p95'])}]",
         "19개월 표본이라 통계 검정력 약함 (CI 폭이 큼)"],
        ["슬리브 단독 기여",
         f"leader {pct(vs['sleeve_leader']['cagr'])} (MDD {pct(vs['sleeve_leader']['mdd'])}), "
         f"mom63 {pct(vs['sleeve_mom63']['cagr'])} (MDD {pct(vs['sleeve_mom63']['mdd'])}), "
         f"lowvol {pct(vs['sleeve_lowvol']['cagr'])} (MDD {pct(vs['sleeve_lowvol']['mdd'])})",
         "성과는 순수 모멘텀에서 발생, lowvol은 방어 (2026-07 +4.6%)"],
        ["섹터 집중", f"평균 최대 섹터 비중 {float(m['max_sector_w_mean']):.1%}",
         "40% 섹터 상한은 best-effort(미적용) — 2026-07 급락의 직접 원인"],
    ]

    return [
        heading_2(SECTION),
        para(
            "동결 전략(Robust_L60_M63_LV20)을 생산 파이프라인 코드 그대로 재현해 "
            "\"매달 실행했다면\"의 as-if 성과를 산출한 테스트입니다. "
            "신호는 2024-12-31 ~ 2026-07-31 월말 종가(총 20회), 체결은 익영업일 시가(NEXT_OPEN), "
            "비용은 편도 10bp를 적용했습니다. 각 신호는 해당 월말까지의 데이터만 사용합니다 "
            "(모든 피처가 후행 롤링 윈도우: 모멘텀 252/63/21일, 신고가 252일, 거래대금 20일, 국면 MA60 등)."
        ),
        para(
            "재현 경로는 연구용 재구현이 아니라 라이브 운영과 동일한 함수 "
            "(ops_monthly_run.load_market + build_target)를 그대로 사용했고, 파라미터는 동결값 "
            "(60/20/20 동일비중, 종목 15% 상한, 빈 슬리브/상한 잔여는 현금)을 테스트 구간에서 "
            "전혀 재조정하지 않았습니다."
        ),
        heading_3("8-1. 전략과 동일함의 증명 (라이브 신호 대조)"),
        bullet("2026-07-31 신호: 라이브 ops 산출물(signals.csv / target.csv)과 종목·비중 완전 일치 — 비중 오차 9e-17"),
        bullet("2026-06-30 신호: 종목 6개 차이(leader TER↔MU 등) — 8/3 패널 갱신에 따른 데이터 개정(점수 근접 종목 순위 변동). "
               "파이프라인 자체는 2026-07 신호 완전 일치로 정합성 입증"),
        bullet("산출물: research/strict_asif_test.py → results/strict_asif/ (monthly_table.csv, equity.csv, metrics.json)"),
        heading_3("8-2. 월별 성과 (as-if, 시드 100만 달러)"),
        table(["월", "신호→체결", "국면", "종목수(L/M/LV)", "턴오버", "전략", "SPY", "초과", "전략잔액"],
              m_rows),
        para("※ 2026-08은 08-03 하루만 포함한 부분 월(부록). 이 신호는 라이브로 실제 체결됨."),
        heading_3("8-3. 요약 통계 (2025-01 ~ 2026-07, 19개월)"),
        table(["지표", "전략", "SPY"], sum_rows),
        heading_3("8-4. 엄격성·편향 점검"),
        table(["점검", "결과", "해석"], chk_rows),
        para(
            "한계: 유니버스가 현재 S&P500 상위 150종 기준이라 생존 편향(과거 성과 과대평가 방향)이 구조적으로 남아 있습니다. "
            "또 2025-01 ~ 2026-06은 동결 연구의 표본 내 구간(fold 5, 연환산 140.3%)과 겹칩니다 — "
            "본 재현의 동일 구간 CAGR 151.9%는 '재현성'이지 '표본 외 검증 통과'가 아닙니다. "
            "진짜 표본 외 증거는 2026-07 신호(2026-08-03 체결) 이후부터입니다. "
            "2026-07 한 달 -24.8%(SPY +0.0%)가 이 구간 최대 위험 사건이며, "
            "전체 성과는 2026-01~06(+148.9%) 등 특정 레짐 몇 달에 집중되어 있습니다."
        ),
    ]


def get_children():
    r = requests.get(f"{BASE}/blocks/{PAGE}/children", headers=H, timeout=60)
    r.raise_for_status()
    return r.json().get("results", [])


def main():
    # 1) collect previously written section (heading_2 SECTION .. next heading_2)
    to_delete = []
    in_sec = False
    for b in get_children():
        text = "".join(x.get("plain_text", "") for x in b.get(b["type"], {}).get("rich_text", []))
        if b["type"] == "heading_2" and text.startswith("8. as-if 백테스트"):
            in_sec = True
            to_delete.append(b["id"])
            continue
        if in_sec:
            if b["type"] == "heading_2":
                in_sec = False
            else:
                to_delete.append(b["id"])

    # 2) SAFETY GUARD: never delete blocks with nested content (child pages, toggle/bullet
    #    children, etc.). Tables are fine (rows are regenerated with the section).
    if to_delete:
        ids = set(to_delete)
        for b in get_children():
            if b["id"] in ids:
                if b["type"] == "child_page":
                    raise SystemExit("ABORT: section contains a child_page block — refusing to delete")
                if b.get("has_children") and b["type"] != "table":
                    raise SystemExit(
                        f"ABORT: section block {b['id'][:8]} type={b['type']} has nested children — refusing to delete"
                    )
        for bid in to_delete:
            requests.delete(f"{BASE}/blocks/{bid}", headers=H, timeout=60)
        print("removed old section blocks:", len(to_delete))

    # 3) append the section at the page end.
    #    NOTE: this Notion API version rejects positional insert ("after" fails validation),
    #    so the section lands after any existing tail content. Do NOT try to "move" other
    #    blocks to reorder — that deleted a nested sub-page once (2026-08, recovered by
    #    rebuilding). Appending at the end is the only safe option.
    children = build_children()
    r = requests.patch(f"{BASE}/blocks/{PAGE}/children", headers=H,
                       json={"children": children}, timeout=60)
    r.raise_for_status()
    print("appended blocks:", len(children))

    # 3) verify: print the newly written section
    print("\n== verify (new section) ==")
    started = False
    for b in get_children():
        text = "".join(x.get("plain_text", "") for x in b.get(b["type"], {}).get("rich_text", []))
        if b["type"] == "heading_2" and text.startswith("8. as-if 백테스트"):
            started = True
        elif started and b["type"] == "heading_2":
            break
        if not started:
            continue
        if b["type"] == "table":
            print(f"  table: {b['table']['table_width']} cols x {len(b['table'].get('children', []))} rows")
        elif b["type"] in ("heading_2", "heading_3", "paragraph", "bulleted_list_item"):
            print(f"  {b['type']}: {text[:90]}")


if __name__ == "__main__":
    sys.exit(main())
