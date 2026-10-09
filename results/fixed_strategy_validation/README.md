# 고정 60/20/20 전략의 IS/OOS 검증

> 수정 전 `f0bcd3e`의 보관 결과입니다. 이 실행의 252개 관측값 조건과 월별 유동성 재순위는 당시 운용 정책과 달랐습니다. 현재 소스는 공통 정책으로 수정했으며 원본 캐시가 없어 수정 후 시장 성과는 재산출하지 않았습니다. 아래 수치를 현재 코드나 실계좌의 성과로 인용할 수 없습니다. [수정 기록](../../docs/audit_fixes.md)

월말 종가 신호와 익영업일 시가 체결을 적용하고 왕복 10bp 비용을 반영했습니다. IS를 확장하며 시간순 5개 OOS Fold를 평가한 뒤 같은 OOS 수익률로 국면별 분석과 t검정 및 Bootstrap을 수행했습니다.

고정 전략이므로 IS에서 파라미터를 재학습하거나 후보를 다시 선택하지 않습니다. 이번 실행은 사후 재검증이며 과거에 이 절차를 사전 등록했다는 의미가 아닙니다.

| Fold | IS 종료 | OOS 시작 | OOS 종료 | 전략 수익률 | SPY 수익률 |
|---|---|---|---|---:|---:|
| 1 | 2023-12-29 | 2024-01-02 | 2024-06-28 | 36.92% | 15.22% |
| 2 | 2024-06-28 | 2024-07-01 | 2024-12-31 | 30.70% | 8.39% |
| 3 | 2024-12-31 | 2025-01-02 | 2025-06-30 | 12.97% | 6.05% |
| 4 | 2025-06-30 | 2025-07-01 | 2025-12-31 | 34.46% | 11.00% |
| 5 | 2025-12-31 | 2026-01-02 | 2026-06-30 | 105.02% | 10.09% |

연결 OOS CAGR 99.91%, Sharpe 2.31, MDD -22.14%.

월별 초과수익 t=3.8571, 양측 p=0.000589; 5% 유의수준 판정: True.

| 재표집 | 반복 수 | 월평균 초과수익 95% 구간 | 평균이 양수인 비율 |
|---|---:|---|---:|
| iid | 10000 | 2.34% ~ 6.73% | 100.00% |
| block4 | 10000 | 1.93% ~ 7.16% | 100.00% |

Bootstrap의 양수 비율은 p-value가 아닙니다. 국면별 결과는 regime_table.csv를 참고하세요. 국면은 전일 종가까지의 정보로 분류하며 기여도는 일별 초과수익의 합으로 복리 성과 기여도가 아닙니다.

## 재현

```bash
python research/walk_forward_validation.py --mode fixed --data-dir data/us
npx --yes tsx src/harness.ts
```

## 한계

- Retrospective validation; frozen strategy was designed with historical data knowledge.
- Universe: 149 names in the available current-constituent cache; historical S&P 500 membership is not reconstructed.
- Fixed-policy temporal validation; IS is diagnostic and is not a model-refitting walk-forward.
- Monthly t-test assumes independent observations; block bootstrap only checks short dependence and sampling sensitivity.
- SPY close-to-close returns are a passive gross benchmark; strategy pays entry/rebalance/exit costs.
- No spread/slippage/impact model beyond 10bp round-trip cost; not live performance.
