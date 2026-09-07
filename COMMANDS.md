# US-Robust Live Ops — Commands

Procedure-first CLI. `python ops.py <command>` is a thin launcher for the
`ops/` package (same as `python -m ops.ops <command>`). Tests live in
`tests/`, research tooling in `research/`.

```bash
# from the repository root
python ops.py status
python ops.py refresh
python ops.py monthly
python ops.py rebalance
python ops.py execute --risk-mode NORMAL
python ops.py weekly
```

## Monthly standard procedure

```bash
# 0) status (+ excel sync of an existing month package)
python ops.py status

# 1) refresh US yfinance panels + valuation rebuild (+ excel sync)
python ops.py refresh
python ops.py refresh --smart
python ops.py refresh --with-fundamentals

# 2-5) select -> weights -> orders -> health -> excel
# month-end Close only (mid-month refused unless --force-intramonth)
python ops.py monthly
python ops.py monthly --capital 100000
python ops.py monthly --asof 2026-06-30

# 6) rebuild buy/sell ticket from frozen target + live book
python ops.py rebalance
python ops.py rebalance --capital 100000

# 7) LIVE execute (real broker orders when LIVE_ORDERS_ENABLED=True)
# CLI invocation + an explicit manual risk decision is the approval action.
python ops.py execute --risk-mode NORMAL
python ops.py execute --run-dir results/ops_runs/2026-06 --risk-mode L1
# L2 is sticky and sends defensive SELLs only:
python ops.py execute --run-dir results/ops_runs/2026-06 --risk-mode L2

# alt human path: Excel approve -> HTS sell then buy -> book fills

# 8) weekly live NAV + SPY snapshot (week-end anchor)
python ops.py weekly
# Mon-Thu runs are a clean no-op; Sat/Sun runs record the prior Friday
# anchor row in place. Missed weeks are backfilled on the next anchor run.
```

`status` / `refresh` / `monthly` / `rebalance` refresh
`results/ops_runs/{signal-month}/US_Robust_Ops_{signal-month}.xlsx`
when the run package exists. `monthly` creates it; status/refresh/excel do not.

Use CSV holdings or disable Toss for research:

```bash
python ops.py monthly --positions holdings.csv
python ops.py monthly --positions none
python ops.py weekly          # self-fetches SPY + held-ticker closes when cached panels are stale;
                              # a full refresh is only required for the monthly signal, not weekly tracking
```

## Stage map

| Step | Command | What | Excel |
|------|---------|------|-------|
| 0 | ops.py status | secrets / data/us freshness / broker book | sync existing |
| 1 | ops.py refresh | yfinance prices + valuation rebuild | sync existing |
| 2-5 | ops.py monthly | picks + equal-within-sleeve 60/20/20 + orders + health | 01/02/04/05 |
| 6 | ops.py rebalance | target fixed + live book ticket | 01 / 05 |
| 7 | ops.py execute | gates + LIVE real order send | optional |
| 8 | ops.py weekly | live NAV + SPY snapshot at weekly anchor -> daily_nav.csv (idempotent per ISO week) | 06_Weekly_Trend |

## Main CLI

### status

```bash
python ops.py status
python ops.py status --no-toss-probe
```

- secret presence (values hidden)
- data/us parquet presence + max date when readable
- broker portfolio probe (US book + cash)
- Excel sync only if the month package already exists

### refresh

```bash
python ops.py refresh
python ops.py refresh --smart
python ops.py refresh --with-fundamentals
```

Default force-refreshes US panels under data/us via yfinance, then rebuilds
valuation from cached fundamentals (`--with-fundamentals` also redownloads
fundamentals).

### monthly

```bash
python ops.py monthly
python ops.py monthly --capital 100000
python ops.py monthly --positions none
python ops.py monthly --asof 2026-06-30
python ops.py monthly --no-xlsx
python ops.py monthly --force-intramonth   # research only
```

Policy freeze inside the runner:

- sleeves leader 0.60 / mom63 0.20 / lowvol 0.20
- weight_mode equal_within_sleeve
- universe `--top-n` default 150
- empty sleeve / name-cap leftover -> residual cash (weight sum may be < 1)
- qty sizing prefers NEXT_OPEN, else signal Close
- `normalize_symbol` anti-zfill
- month-end Close only (incomplete month -> exit 3 unless `--force-intramonth`)
- package/folder/Excel use the SIGNAL month (e.g. 2026-07-31 close -> 2026-07);
  positions are HELD during the following month — banners show
  "Signal YYYY-MM -> Holding YYYY-MM"

### rebalance

```bash
python ops.py rebalance
python ops.py rebalance --capital 100000 --risk-mode NORMAL
python ops.py rebalance --run-dir results/ops_runs/2026-06 --risk-mode L1
```

Frozen target.csv + live book -> orders ticket only (no name reselection, no
broker send).

### execute

```bash
python ops.py execute --risk-mode NORMAL
python ops.py execute --run-dir results/ops_runs/2026-06 --risk-mode L1
python ops.py execute --run-dir results/ops_runs/2026-06 --risk-mode L2
python ops.py execute --run-dir results/ops_runs/2026-06 --risk-mode NORMAL --confirm-outside-window
python ops.py risk-reset --account-tail 1234 --ack "manual review complete"
```

**Real-order path.** The Python package/CSV is the sole order source; Excel is
a read-only comparison mirror. LIVE requires a pinned account, `positions=toss`,
no capital override, and an explicit manual risk mode:

- NORMAL: frozen alpha target; L1: gross 50%; L2: sticky, no BUY
- package manifest/hash + latest completed month + exact next regular-open window
- replay/claim protection; zero-order-POST failures (connect/gate) auto-retry by
  archiving the stale claim; anything that touched the order endpoint requires
  manual review
- SELL exact full-fill, then a refreshed cash gate, then BUY
- writes fills jsonl / execute_status / attempt result
- `--positions none`, CSV positions, and `--capital` are research-only and refused in LIVE

### weekly

```bash
python ops.py weekly
```

Record the live NAV + SPY snapshot at the weekly anchor (last US trading day of
the ISO week, normally Friday) into `results/ops_runs/YYYY-MM/daily_nav.csv` and
`daily_holdings.csv`. Weekly rows are stored under the legacy `daily_*` filenames
for reader compatibility. Mon-Thu runs are clean no-ops; Sat/Sun runs record the
prior Friday anchor row in place; missed weeks are backfilled on the next anchor
run.

### excel

```bash
python ops.py excel --run-dir results/ops_runs/2026-06
```

Refills Excel from an existing run dir only (does not auto-create monthly).

## Artifacts

```text
results/ops_runs/YYYY-MM/
  signals.csv
  target.csv
  orders_preview.csv
  health.json
  package_manifest.json  # immutable signals/target SHA256 + package_id
  US_Robust_Ops_YYYY-MM.xlsx
  execute_send_list.json
  execute_attempt.json / execute_attempt_result.json
  execute_dry_run.json   # only when LIVE blocked
  fills_*.jsonl          # LIVE fills

results/ops_runs/YYYY-MM/daily_nav.csv       # weekly NAV anchors, one row per ISO week
results/ops_runs/YYYY-MM/daily_holdings.csv  # per-week per-stock quantities
```

## Human checklist

1. health.json / Excel 04_Health is not BLOCK
2. 02_Screen_Select sleeves are leader/mom63/lowvol only
3. 05_Trade sell-first; Excel displays `CLI_REQUIRED` and is not the order source of truth
4. set/verify the broker account and choose a manual `NORMAL|L1|L2` risk mode
5. run `python ops.py execute --risk-mode ...` at the exact next US regular open
6. verify fills / execute_status / execute_attempt_result

## Do not

- commit .env
- flip LIVE_ORDERS_ENABLED casually
- zfill US tickers
- import research W_* into production
- clobber the master excel template
- recompute alpha in Excel
- run bare monthly mid-month without `--force-intramonth`

## Invariants

- US fractional qty default
- cash pulled with the portfolio
- zero-qty buys warn in sizing/health
- LIVE send only through ops.py execute
- monthly signal = completed month-end Close only
- execute price rule = NEXT_OPEN; unpriced universe codes are dropped (never silently selected)
- residual cash is allowed; weight_sum > 1 is BLOCK
