# 2026-10-08 검수 결함 수정

기준 커밋: `f0bcd3e7033abd1307c02c3c182ac5d86d1468d8`.
동결된 60/20/20 비중, 동일비중, 이름 상한 15%, NEXT_OPEN 규칙을 유지한다.

| 검수 항목 | 수정 | 회귀 검증 |
|---|---|---|
| 1. 연구·운용 종목 자격 불일치 | `ops_us_policy.build_us_target` 공유. 메타데이터 순서·Marcap 정렬·top_n·신호일까지 유효 종가 200개를 동일 적용하고 적격 종목 안에서 Leader 순위를 계산한다. fixed CLI는 같은 버전의 메타데이터를 필수로 받는다. | 220개 관측값 YOUNG, 최근 결측 GAPPED, 메타데이터 밖 고유동성 종목에서 타깃·picks가 동일하며 미래 가격 변경에 불변. |
| 2. 가격 없는 주문 누락 후 게이트 통과 | 종목별 신호일 종가 대체. 가격·수량 오류는 BLOCK. A/B 게이트는 원래 티켓의 필요한 코드·매수/매도와 전송 목록을 비교한다. | 개별 시가 결측 대체, 가격 전체 결측, 정상 주문 일부 누락, sizing 오류, 0회 브로커 연결·주문 호출, 가격 복구 후 티켓 정상화. |
| 3. 구형 회계 엔진 | 구형 세 엔진 본체 제거 후 RuntimeError로 차단. 해당 연구 CLI도 데이터 로드 전 차단. 현재 연구 회계는 새 `simulate`. 구형 walk_forward는 학습 없는 구간 집계라고 명시. | 세 구형 엔진 차단, 새 엔진의 시가 예산·진입 비용·비중 드리프트·수익률/NAV 정합성. |
| 4. refresh 묶음의 비원자적 교체 | `data/us/snapshots/<id>/`에 메타·가격·시가·거래량·SPY를 준비한다. 날짜·종목 축, 최종 완료 세션, 커버리지를 검사하고 SHA256 manifest와 `current_snapshot.json` 포인터를 원자적으로 게시한다. 월간 운용과 WFA는 포인터를 한 번 읽어 버전을 고정한다. | 실제 cmd_refresh/load_prices 실행 후 SPY 실패에도 이전 파일/포인터 보존. 정상 게시, 기존 버전 유지, 내부 세션 결측·종목 축 불일치·포인터 게시 실패. |
| 5. WFA 종료 구간 불완전 | 전체 선언된 IS/OOS 구간에서 NYSE 세션을 요구한다. 마지막 세션 또는 내부 세션이 빠지면 Fold 계산·산출물 저장 전에 실패한다. 두 모드의 날짜·종목 축도 동일 검사. | Jun29 캐시에서 fixed/candidate 실제 main 모두 실패. Jun30·내부 세션 누락 차단. 정상 합성 NYSE 5 Fold·625 OOS 세션 완료. |
| 6. 주간 NAV 화요일 기록 | 관측값의 끝이 아닌 XNYS 주간 마지막 세션을 기준으로 판단. 해당 SPY 종가와 실제 세션 종료를 요구한다. | 화요일까지의 데이터로 화요일 기록 거부, 주말에 금요일 누락 거부, Good Friday 주간·정규 종료·조기 종료·서머타임 검사. |
| 7. 패키지 명령의 미완료 현재 월 선택 | 기존 패키지 조회 `resolve_ops_month`와 신호 생성 `resolve_signal_month`를 분리. 조회는 완료된 신호일·파일·manifest가 있는 최신 패키지를 선택한다. | Sep30 패키지와 Oct7 캐시/불완전 패키지가 있을 때 Sep 선택. 가격 캐시 없이 조회. 완료 패키지 없는 경우 명확한 실패/Excel skip. |
| 8. 누락 의존성·오프라인 import | yfinance, finance-datareader, exchange-calendars, tzdata 명시. Python 3.11 전체 의존성을 requirements-lock.txt로 잠근다. 다운로드 클라이언트가 없어도 순수 계산 모듈 import 허용. | 새 가상환경에서 requirements.txt만 설치. pip check. 다운로드 라이브러리 import를 차단한 별도 프로세스에서 오프라인 WFA import 성공. |
| 9. 이전 브로커 상태 잔류 | `load_position_context`가 `(weights, book)`을 반환하고 실행 경로가 이를 명시적으로 전달한다. 함수 속성과 월간 `_LAST_*` 상태 제거. `load_positions`는 상태 없는 weights 전용 호환 함수. | 같은 프로세스의 toss → none → CSV 호출에서 book·자본 출처가 이전 호출을 참조하지 않음. |

## 검증 실행

```powershell
$env:PYTHONUTF8 = '1'
python -m venv .audit-clean-venv
.\.audit-clean-venv\Scripts\python.exe -m pip install -r requirements.txt
.\.audit-clean-venv\Scripts\python.exe -m pip check
$env:VALIDATION_PYTHON = (Resolve-Path .\.audit-clean-venv\Scripts\python.exe).Path
npm ci
npm run check
npx tsx src/harness.ts
```

최종 검증: Python 3.11 새 가상환경에 `requirements.txt`만 설치했고 `pip check`가 통과했다. `npm run check`와 `tsx src/harness.ts`가 통과했으며 전체 Python 테스트는 **78 passed, 1 skipped**였다. 건너뛴 테스트는 기존 주간 원장의 마이그레이션 guard 조건에 관한 것이다. 보관 CSV/JSON의 625세션·30개월·5 Fold 산술 검증도 통과했다. 실제 시장 데이터 다운로드나 브로커 주문은 실행하지 않았다.

Harness는 보관 CSV/JSON의 산술과 현재 Python 전체 테스트를 검사한다. 합성 데이터의 성과는 투자 성과로 해석하지 않는다. NYSE 세션·휴장·조기 종료는 고정된 [exchange_calendars XNYS](https://github.com/gerrymanoim/exchange_calendars) 버전을 사용하며 브로커 주문 사전 점검은 기존 공식 시장 캘린더를 사용한다.

## 운용·재현 변경

- `refresh` 실패 시 게시된 버전은 보존된다. 실패한 미게시 버전은 진단용으로 남는다. 이전 평면 parquet도 보존되지만 포인터가 생긴 뒤 운용/WFA는 게시된 버전을 읽는다.
- 보유분 및 오프라인 가격 패널은 실행마다 새로 읽는다. `build_target`의 라이브러리 호출은 close/volume을 명시해야 한다.
- `rebalance` 반환값의 book은 같은 실행의 Excel/execute에 전달하며 디스크의 ticket JSON에는 브로커 원본 book을 저장하지 않는다.
- 섹터 정책은 기존 운용과 같이 best-effort 진단이다. 역사적 섹터 복원이나 강제 상한으로 확대하지 않았고, 수동 NORMAL/L1/L2 overlay도 fixed 실험에 자동 적용하지 않는다.
- 기존 fixed/candidate 산출물은 이전 실행 기록이다. 원본 가격·메타데이터가 저장소에 없어서 수정된 정책의 시장 수익률을 재산출하지 않았다. PIT 구성종목, 상장폐지, 독립 사후 holdout, 실제 체결·현금흐름 원장 검증은 별도 조건으로 남는다.
