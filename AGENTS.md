# Repository Guidelines

## Project Overview

US long-only large-cap quant **live-ops** repository for the frozen 3-sleeve robust engine:

- **Leader 60%** / **Mom63 20%** / **LowVol 20%**
- Monthly name rebalance; signal at month-end **Close** -> execute **next Open**
- Name cap **15%** (sector **40%** best-effort only)
- Weight mode: **equal-within-sleeve** (no score-tilt on production path)
- Universe default **top_n=150**; empty sleeve / name-cap leftover stays **cash**
- Exit = signal drop + limits + portfolio MDD circuit (operator-selected `--risk-mode NORMAL|L1|L2`)
- Forbidden: AccumulDiv, fundamental-core sleeves, event NLP exits, weekly name refresh, Black-Litterman, casual LIVE enable

Python is the signal/target source of truth; Excel is the approval/ledger UI.

## Architecture and Data Flow

```text
.env (optional Toss keys)
  -> us_hybrid_backtest / yfinance (data/us panels)
  -> ops_us_policy.py + us_factor_research.select_factor
  -> ops_monthly_run.py
  -> ops_excel_write.py
  -> Human HTS or LIVE Toss execute (real orders when LIVE_ORDERS_ENABLED)
```

| Layer | Files |
|-------|-------|
| Engine / policy | ops_us_policy.py, us_factor_research.py, us_robust_strategy.py |
| Data loaders | us_hybrid_backtest.py (loaders only; never import production W_*) |
| Env | ops_env.py, .env.example, .gitignore |
| Ops | ops.py, ops_monthly_run.py, ops_excel_write.py |
| Toss | toss_portfolio.py, toss_orders.py |
| Execute | ops_execute.py, ops_execute_gates.py |

## Key Directories

| Path | Purpose |
|------|---------|
| ops/ | Production engine (policy, monthly runner, execute, excel, weekly tracker) |
| data/us/ | US parquet panels (downloaded by `python ops.py refresh`; not committed) |
| results/ops_runs/YYYY-MM/ | Monthly signals/target/orders/health/xlsx (run artifacts) |
| results/ops_excel/ | Master Excel template (committed; do not clobber) |
| research/ | Strict backtest validation + Korean report generators |
| scripts/ | Excel template + Notion asset helpers |
| tests/ | Fail-closed safety tests (hermetic; no live network) |

## Development Commands

Python 3.11 / Windows. Prefer procedure CLI:

```bash
python ops.py status
python ops.py refresh
python ops.py monthly
python ops.py rebalance
python ops.py execute --risk-mode NORMAL
python ops.py monthly --positions none
python ops.py excel --run-dir results/ops_runs/YYYY-MM
```

Excel path: results/ops_runs/YYYY-MM/US_Robust_Ops_YYYY-MM.xlsx

Full command book: COMMANDS.md

## Code Conventions

- Symbols via `ops.ops_us_policy.normalize_symbol` (never zfill US tickers)
- Production weights: equal-within-sleeve only; do not import research `W_*`
- Do not recompute alpha in Excel (Excel is a read-only mirror)
- Do not commit `.env`; load secrets via `ops_env.load_env()`

## Testing and QA

```bash
python -m pytest tests/ -q
python ops.py monthly --positions none
python ops.py execute --risk-mode NORMAL --run-dir results/ops_runs/YYYY-MM --positions none --capital 100000 --no-xlsx
```

Expect: weight_sum~=1, max_name<=0.15, weight_mode=equal_within_sleeve; monthly refuses an incomplete month unless `--force-intramonth`.
Tests are hermetic: no real HTTP, and the Excel readiness path uses `tests/fixtures/us_prices_fixture.parquet`.

## Policy Freeze (do not casual-change)

1. Equal-within-sleeve 60/20/20 (Leader / Mom63 / LowVol)
2. Next-open execution
3. Name 15% / sector 40% when mapped
4. Exit: signal drop + limits + MDD circuit
5. No AccumulDiv / fundamental-core / event NLP / weekly name refresh / Black-Litterman
6. Broker auto-send only via `ops.py execute` (LIVE real-order path; do not flip the flag casually)

## Live Trading Disclaimer

This is a personal research/ops project. The code is provided as-is (MIT). Past
backtest performance does not guarantee future results; any live use is entirely
the operator's own responsibility.
