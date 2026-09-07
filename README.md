# US-Robust Live Ops

미국 대형주(SPY 벤치마크) 3-슬리브 퀀트 전략을 **월간 리밸런스로 실제 운용하는 라이브 옵스 시스템**입니다. 신호와 목표 비중은 Python이 유일한 원천(source of truth)이고, openpyxl로 만드는 엑셀 원장과 Notion 대시보드는 읽기 전용 소비자로 분리했습니다. 데스크에서 엑셀을 직접 고치다 생기는 수식 오염, 원장 어긋남 같은 실수를 구조적으로 막는 게 이 저장소의 핵심입니다.

- 전략: `Robust_L60_M63_LV20` (Leader 60% / Mom63 20% / LowVol 20%, 동일비중)
- 리밸런스: 월말 종가 신호 -> 익영업일 시가 체결 (NEXT_OPEN)
- 종목: S&P500 유동성 상위 150 (이름 상한 15%)
- 원장: 월별 주간 NAV 앵커 + SPY 비교 (06_Weekly_Trend)
- 규모: Python 약 17k LOC, 모듈 27개, fail-closed 테스트 45개

## 왜 이런 구조인가

퀀트 데스크 운영에서 가장 위험한 지점은 "엑셀에서 뭔가를 고쳤다"입니다. 수식 하나가 잘못 복사되면 P&L이 조용히 틀어지고, 그걸 나중에 발견하기 어렵습니다. 이 저장소는 계산을 전부 Python에 두고, 엑셀/Notion은 결과를 그려주는 화면으로만 씁니다.

- Python CSV/패키지가 주문·NAV 원천. 엑셀은 `CLI_REQUIRED`만 표시하고 주문을 만들지 못함
- 매 실행이 마스터 템플릿에서 원장 워크북을 다시 생성. 병합 셀이나 샘플 잔고가 섞일 여지가 없음
- 패키지 매니페스트(SHA256)로 신호·목표 위변조를 실행 전에 감지
- 실주문은 `ops.py execute` + 명시적 위험모드(NORMAL/L1/L2)에서만 통과

## 백테스트 성과 요약

2024-01 ~ 2026-07 엄격 검증(편향 통제, 월말 신호->익일 시가, 비용 반영):

| 지표 | 값 |
|---|---|
| 연환산 수익률 | 49.0% |
| 샤프 | 1.54 |
| 정보비율 | 1.37 |
| 최대 낙폭 | -30.4% |
| 검증 기준 | 10/10 통과 |

수치는 과거 데이터 기반이고, 특히 유니버스가 현재 시장 구성종목 기준이라 생존 편향이 일부 있습니다. 미래 성과를 보장하지 않습니다.

## 아키텍처

![US-Robust Live Ops architecture](docs/architecture.png)

Python(ops/)이 신호·비중·NAV 계산의 유일한 원천이고, 엑셀 원장과 Notion은 결과를 그려주는 소비자다. 자세한 설명은 [docs/architecture.md](docs/architecture.md)를 참고.

## 저장소 구조

```text
ops/                 # 운용 엔진 (14 모듈)
  ops_us_policy.py     동결 정책 (60/20/20, 이름 상한, NEXT_OPEN)
  ops_monthly_run.py   월간 신호 -> 목표 -> 주문 -> health
  ops_excel_write.py   openpyxl 원장 워크북 생성
  ops_daily.py         주간 NAV/SPY 앵커 기록
  ops_execute*.py      실주문 게이트 + 실행
  toss_*.py            브로커 잔고 조회 / 주문 클라이언트
  us_*.py              팩터 연구 + 백테스트 로더
scripts/             # 엑셀 템플릿 생성, Notion 주간 자산
research/            # 엄격 백테스트 검증 + 한글 보고서 생성
tests/               # fail-closed 안전 테스트 (네트워크 차단)
docs/                # 전략 명세, 아키텍처
```

아키텍처 다이어그램과 시트별 설명은 [docs/architecture.md](docs/architecture.md)에 있습니다.

## 빠른 시작

```bash
python -m pip install -r requirements.txt
python -m pytest tests/ -q          # hermetic, 네트워크 없음

# 데이터 갱신 후 월간 운용 절차
python ops.py refresh
python ops.py monthly               # 신호 -> 목표 -> 주문 티켓 -> 엑셀
python ops.py rebalance             # 동결 목표 + 실시간 잔고로 티켓 재구성
python ops.py execute --risk-mode NORMAL   # 게이트 통과 후 실주문(선택)
python ops.py weekly                # 주간 NAV + SPY 스냅샷 (금요일 앵커)
```

브로커 연동(Toss OpenAPI)은 `.env`에 키를 넣고 `ops_env.load_env()`로 읽습니다.
`refresh`는 데이터를 만들어 `data/us/`에 parquet으로 저장합니다. 전체 커맨드는
[COMMANDS.md](COMMANDS.md)를 보세요.

## 테스트 철학

`tests/test_ops_live_safety.py`는 라이브 호출을 전부 차단합니다(HTTP 금지
fixture). 엑셀 READY 경로는 `tests/fixtures/us_prices_fixture.parquet` 같은
결정적 픽스처만 써서, 저장소를 새로 받아도 같은 결과가 나옵니다. 그래서
"게이트를 우회하면 안 된다"가 아니라 "게이트가 실제로 막는지"를 코드로 검증합니다.

## 라이선스와 책임

MIT 라이선스로 공개합니다. 이 코드는 개인 연구·운용 프로젝트이며, 실제 투자에
쓰는 결정과 그 결과의 책임은 전적으로 운영자에게 있습니다.
