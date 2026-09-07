"""US-Robust live ops CLI - procedure-oriented entrypoint.

Steps (monthly):
  1) status    - secrets/data health snapshot + Excel sync (existing run only)
  2) refresh   - update US yfinance panels (+ valuation rebuild) + Excel sync
  3) monthly   - select -> weight -> orders -> health -> Excel autofill
                 (default positions=toss live US book; month-end Close only)
  4) rebalance - rebuild buy/sell ticket from frozen target + live book
                 then refresh Excel 01_Portfolio_Now + 05_Trade
  5) execute   - gates then LIVE Toss send (real orders; LIVE_ORDERS_ENABLED)
                 or human HTS path after Excel approve

status / refresh / monthly / rebalance refresh
  results/ops_runs/YYYY-MM/US_Robust_Ops_YYYY-MM.xlsx when the run package exists.
monthly creates the package; status/refresh/excel do NOT auto-create monthly.

Policy freeze (US-Robust):
  Leader 60% / Mom63 20% / LowVol 20%, equal-within-sleeve, name cap 15%.

Examples:
  python ops.py status
  python ops.py refresh
  python ops.py monthly
  python ops.py rebalance
  python ops.py execute
  python ops.py monthly --positions holdings.csv
  python ops.py monthly --positions none
  python ops.py excel --run-dir results/ops_runs/2026-06
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from ops.ops_us_policy import TOP_N_DEFAULT

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OPS_RUNS = ROOT / "results" / "ops_runs"


def hint_existing_packages(run_dir: Path, prefix: str = "  ") -> None:
    """Print sibling month packages so the operator can pick --run-dir explicitly."""
    try:
        existing = sorted(
            p.name for p in OPS_RUNS.iterdir()
            if p.is_dir() and (p / "target.csv").exists() and (p / "health.json").exists()
        )
    except OSError:
        return
    if existing:
        print(f"{prefix}existing month packages: {', '.join(existing)}")
        print(f"{prefix}hint: use --run-dir results/ops_runs/{existing[-1]} to act on the latest package")


def _banner(step: str, title: str) -> None:
    print()
    print("=" * 60)
    print(f"[{step}] {title}")
    print("=" * 60)


def resolve_ops_month(asof: Optional[str] = None) -> Tuple[Path, pd.Timestamp]:
    """Return (run_dir, signal_date) for the active ops month (latest month-end ≤ asof/prices).

    Calendar source: US prices panel (us_hybrid_backtest.CACHE_PRICES /
    data/us/us_prices_panel.parquet), NOT hybrid_strategy KR panel.
    """
    import ops.us_hybrid_backtest as us
    from ops.ops_monthly_run import pick_signal_date

    prices_path = us.CACHE_PRICES
    if not prices_path.exists():
        # fall back to calendar month folder
        now = datetime.now()
        yyyymm = f"{now.year:04d}-{now.month:02d}"
        return OPS_RUNS / yyyymm, pd.Timestamp(now.date())

    panel = pd.read_parquet(prices_path)
    if isinstance(panel.index, pd.MultiIndex):
        dates = pd.to_datetime(panel.index.get_level_values(0)).unique()
    else:
        dates = pd.to_datetime(panel.index).unique()
    close = pd.DataFrame(index=pd.DatetimeIndex(sorted(dates)))
    signal_date = pick_signal_date(close, asof)
    yyyymm = f"{signal_date.year:04d}-{signal_date.month:02d}"
    return OPS_RUNS / yyyymm, signal_date


def sync_ops_excel(
    *,
    positions: str = "toss",
    asof: Optional[str] = None,
    out_dir: Optional[str] = None,
    create_if_missing: bool = False,
) -> Optional[Path]:
    """Refresh US_Robust_Ops_YYYY-MM.xlsx from an existing month run package.

    - Default: refill xlsx only when health/signals/target already exist.
    - create_if_missing=True: may run monthly package (prefer explicit monthly).
    Returns xlsx path or None on hard failure.
    """
    if out_dir:
        run_dir = Path(out_dir)
        health_path = run_dir / "health.json"
        if health_path.exists():
            try:
                sd = pd.Timestamp(json.loads(health_path.read_text(encoding="utf-8")).get("signal_date"))
            except Exception:
                sd = None
        else:
            sd = None
        if sd is None or pd.isna(sd):
            _, sd = resolve_ops_month(asof)
    else:
        run_dir, sd = resolve_ops_month(asof)

    run_dir.mkdir(parents=True, exist_ok=True)
    need = ["health.json", "signals.csv", "target.csv"]
    missing = [n for n in need if not (run_dir / n).exists()]

    print()
    print("-" * 60)
    print(f"excel_sync  run_dir={run_dir}  positions={positions}")

    produced_xlsx: Optional[Path] = None
    try:
        if missing:
            if not create_if_missing:
                print(f"  missing={missing} -> skip (run: python ops.py monthly)")
                hint_existing_packages(run_dir)
                return None
            print(f"  missing={missing} -> monthly package create")
            from ops.ops_monthly_run import run as monthly_run

            monthly_run(
                asof=asof or str(sd.date()),
                positions=positions,
                out_dir=str(run_dir),
                write_xlsx=True,
            )
        else:
            from ops.ops_excel_write import write_ops_xlsx

            produced_xlsx = write_ops_xlsx(run_dir, positions=positions)
            print(f"  updated {produced_xlsx}")
    except SystemExit as e:
        code = int(e.code) if isinstance(e.code, int) else 1
        print(f"  monthly finished with code={code} (excel may still exist)")
    except PermissionError as e:
        print(f"  EXCEL LOCKED? close the workbook and retry: {e}")
        return None
    except Exception as e:
        print(f"  excel_sync failed: {e}")
        return None

    if produced_xlsx is not None and produced_xlsx.exists():
        print(f"  excel={produced_xlsx}")
        return produced_xlsx

    xs = list(run_dir.glob("US_Robust_Ops_*.xlsx"))
    if xs:
        out = max(xs, key=lambda p: (p.stat().st_mtime_ns, p.name))
        print(f"  excel={out}")
        return out
    print("  excel=NOT FOUND")
    return None


def cmd_status(args: argparse.Namespace) -> int:
    _banner("0", "STATUS - secrets & cache")
    from ops.ops_env import candidate_env_paths, secrets_status

    print("secrets_present:")
    for k, ok in secrets_status().items():
        print(f"  - {k}: {'yes' if ok else 'no'}")
    print("env_paths:")
    for p in candidate_env_paths():
        print(f"  - {p} exists={p.exists()}")

    # KR pykrx path quarantined (US-only ops). Legacy modules may remain on disk.
    print("pykrx_session:")
    print("  - quarantined: US-only ops (use research scripts if KR scrape needed)")

    print("data_panels:")
    data_us = ROOT / "data" / "us"
    for name in [
        "us_prices_panel.parquet",
        "us_open_panel.parquet",
        "us_volume_panel.parquet",
        "us_universe_meta.parquet",
        "spy.parquet",
        "us_valuation_panel.parquet",
    ]:
        pth = data_us / name
        extra = ""
        if pth.exists():
            try:
                df = pd.read_parquet(pth)
                if name.endswith("_panel.parquet") and not df.empty:
                    if isinstance(df.index, pd.MultiIndex):
                        dmax = pd.to_datetime(df.index.get_level_values(0)).max()
                    elif "date" in df.columns:
                        dmax = pd.to_datetime(df["date"]).max()
                    else:
                        dmax = pd.to_datetime(df.index).max()
                    extra = f" max={pd.Timestamp(dmax).date()}"
                elif name == "spy.parquet" and not df.empty:
                    dmax = pd.to_datetime(df.index).max()
                    extra = f" max={pd.Timestamp(dmax).date()}"
            except Exception:
                extra = ""
        present = "yes" if pth.exists() else "NO"
        size_b = pth.stat().st_size if pth.exists() else 0
        print(f"  - us/{name}: {present} {size_b}B{extra}")

    # Toss: portfolio confirm only (no disk snapshot)
    probe = not getattr(args, "no_toss_probe", False)
    print("toss_portfolio:")
    try:
        from ops.toss_portfolio import status as toss_status

        ts = toss_status(probe=probe)
        for k, v in ts.items():
            print(f"  - {k}: {v}")
    except Exception as e:
        print(f"  - unavailable: {e}")

    if not getattr(args, "no_xlsx", False):
        sync_ops_excel(positions=getattr(args, "positions", "toss"), create_if_missing=False)
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    _banner("1", "REFRESH - US market panels (yfinance)")
    # Default: force redownload. --smart prefers cache.
    force = not bool(getattr(args, "smart", False))

    if getattr(args, "kr", False):
        print("KR ETL quarantined in US-only ops. Refusing --kr. Use archived KR scripts if needed.")
        return 2

    import ops.us_hybrid_backtest as us

    print(f"US refresh force={force} (validated atomic panels under data/us)")
    try:
        meta = us.build_universe(top_n=TOP_N_DEFAULT, force_refresh=force)
        codes = meta["Code"].astype(str).tolist()
        close, _open_px, volume = us.load_prices(codes, force=force)
        index_close = us.load_index(force=force)
    except Exception as exc:
        print(f"REFRESH BLOCKED - existing cache preserved: {type(exc).__name__}: {exc}")
        return 2
    min_codes = min(len(codes), max(80, int(len(codes) * 0.80)))
    if close is None or close.empty or close.shape[1] < min_codes or index_close is None or len(index_close) == 0:
        print(f"REFRESH BLOCKED - invalid staged coverage: prices={0 if close is None else close.shape[1]} required={min_codes}")
        return 2

    val_max = None
    try:
        if getattr(args, "with_fundamentals", False):
            print("fundamentals: downloading missing/forced via yfinance")
            fund = us.download_fundamentals(codes, force=force)
        elif us.CACHE_FUND.exists():
            fund = pd.read_parquet(us.CACHE_FUND)
            print(f"fundamentals: cache hit rows={len(fund)}")
        else:
            fund = pd.DataFrame()
            print("fundamentals: none (valuation rebuild may be empty)")
        fund_ttm = us.build_ttm(fund) if fund is not None and not fund.empty else pd.DataFrame()
        val = us.build_valuation_panel(close, volume, fund_ttm, force=True)
        if val is not None and not val.empty:
            val_max = str(pd.to_datetime(val["date"]).max().date())
            print(f"valuation: rebuilt rows={len(val)} max={val_max}")
        else:
            print("valuation: empty")
    except Exception as e:
        print(f"valuation rebuild skipped: {e}")

    n_codes = int(close.shape[1]) if close is not None and not close.empty else 0
    if close is not None and not close.empty:
        price_max = str(pd.Timestamp(close.index.max()).date())
        price_min = str(pd.Timestamp(close.index.min()).date())
    else:
        price_max = price_min = None
    idx_max = None
    if index_close is not None and len(index_close):
        idx_max = str(pd.Timestamp(index_close.index.max()).date())
    print(
        json.dumps(
            {
                "status": "ok",
                "market": "US",
                "n_codes": n_codes,
                "price_min": price_min,
                "price_max": price_max,
                "index_max": idx_max,
                "valuation_max": val_max,
                "force": force,
                "paths": {
                    "meta": str(us.CACHE_META),
                    "prices": str(us.CACHE_PRICES),
                    "index": str(us.CACHE_INDEX),
                    "valuation": str(us.CACHE_VAL),
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    if not getattr(args, "no_xlsx", False):
        sync_ops_excel(positions=getattr(args, "positions", "toss"), create_if_missing=False)
    return 0


def cmd_monthly(args: argparse.Namespace) -> int:
    _banner("2-5", "MONTHLY - select -> weight -> orders -> health -> excel")
    print("procedure:")
    print("  2) 종목 선정 (Leader/Mom63/LowVol)")
    print("  3) 비중 계산 (60/20/20 equal-within-sleeve + cap15)")
    print("  4) 주문 미리보기 (sell-first)")
    print("  5) 헬스 체크 + 엑셀 자동 기입 (positions 기본=toss live book)")
    print()

    from ops.ops_monthly_run import run as monthly_run

    # CSV/health always written by monthly_run; Excel is owned by sync_ops_excel
    # to avoid double-write and keep one rebuild path.
    code = 0
    dest: Optional[Path] = None
    try:
        dest = monthly_run(
            asof=args.asof,
            top_n=args.top_n,
            positions=args.positions,
            out_dir=args.out_dir,
            refresh_data=False,
            write_xlsx=False,
            capital_usd=getattr(args, "capital", None),
            force_intramonth=bool(getattr(args, "force_intramonth", False)),
        )
    except SystemExit as e:
        code = int(e.code) if isinstance(e.code, int) else 1
        if args.out_dir:
            dest = Path(args.out_dir)
        else:
            try:
                dest, _ = resolve_ops_month(args.asof)
            except Exception:
                dest = None
        # 3 = INTRA_MONTH_SIGNAL: no package write; stop before excel/next-steps noise
        if code == 3:
            print("monthly refused: incomplete month-end signal (use --force-intramonth for research)")
            return code

    if not args.no_xlsx:
        sync_ops_excel(
            positions=args.positions,
            asof=args.asof,
            out_dir=str(dest) if dest else args.out_dir,
        )

    print()
    print("next_human_steps:")
    if dest:
        print(f"  6) open Excel: {dest / f'US_Robust_Ops_{dest.name}.xlsx'}")
    else:
        print("  6) open Excel under results/ops_runs/YYYY-MM/")
    print("  7) approve Screen/Trade/Health")
    print("  8) LIVE path: python ops.py execute  (real Toss orders when LIVE_ORDERS_ENABLED)")
    print("     or HTS manual: sell first then buy (next open), book fills into Excel")
    return code


def cmd_excel(args: argparse.Namespace) -> int:
    _banner("5", "EXCEL - autofill from existing run dir")
    try:
        out = sync_ops_excel(
            positions=getattr(args, "positions", "toss"),
            out_dir=args.run_dir,
            create_if_missing=False,
        )
        if out is None:
            from ops.ops_excel_write import MASTER, write_ops_xlsx

            master = Path(args.master) if args.master else MASTER
            out = write_ops_xlsx(Path(args.run_dir), master=master, positions=args.positions)
        print("WROTE", out)
        if out and "_recovery_" in out.name:
            print("NOTE: main and updated workbooks were locked; wrote timestamped recovery workbook")
        elif out and out.name.endswith("_updated.xlsx"):
            print("NOTE: main workbook was locked; wrote sibling *_updated.xlsx")
        return 0
    except PermissionError as e:
        print(f"EXCEL LOCKED - close the workbook and retry: {e}")
        return 1


def cmd_weekly(args: argparse.Namespace) -> int:
    """Record the week's live NAV + SPY snapshot at the weekly anchor into results/ops_runs/daily_nav.csv."""
    _banner("8", "WEEKLY - live NAV + SPY snapshot (week-end anchor)")
    from ops.ops_daily import main as weekly_main

    return weekly_main()


def cmd_rebalance(args: argparse.Namespace) -> int:
    """Rebuild buy/sell rebalance ticket from target + live book, then refresh Excel.

    - Does NOT re-run name selection (monthly signal frozen in target.csv)
    - Does NOT send broker orders (HTS is human)
    - Updates orders_preview.csv + health sizing/toss
    - Rebuilds Excel sheets (esp. 01_Portfolio_Now, 05_Trade)
    """
    _banner("6", "REBALANCE - ticket rebuild + Excel Portfolio/Trade")
    print("procedure:")
    print("  a) load frozen target.csv (monthly signal)")
    print("  b) pull live positions (default toss)")
    print("  c) build sell-first order ticket (qty / cash_need)")
    print("  d) refresh Excel 01_Portfolio_Now + 05_Trade")
    print("  e) human HTS: sell first, then buy (NEXT_OPEN)")
    print()

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        run_dir, _ = resolve_ops_month(args.asof)

    need = ["target.csv", "health.json"]
    missing = [n for n in need if not (run_dir / n).exists()]
    if missing:
        print(f"missing {missing} in {run_dir}")
        print("run: python ops.py monthly   # first create the month package")
        hint_existing_packages(run_dir)
        return 1

    from ops.ops_live_safety import validate_execute_package
    package_check = validate_execute_package(run_dir, asof=args.asof)
    if not package_check.get("ok"):
        print("rebalance refused: unsafe/stale package")
        for reason in package_check.get("reasons") or []:
            print(f"  - {reason}")
        return 2

    from ops.ops_monthly_run import rebuild_rebalance_ticket

    try:
        summary = rebuild_rebalance_ticket(
            run_dir,
            positions=args.positions,
            capital_usd=getattr(args, "capital", None),
            risk_mode=getattr(args, "risk_mode", "NORMAL"),
        )
    except Exception as e:
        print(f"rebalance ticket failed: {e}")
        return 1

    print("ticket:")
    for k in (
        "signal_date",
        "n_target",
        "n_current",
        "n_sell",
        "n_buy",
        "n_hold",
        "capital_usd",
        "capital_source",
        "cash_usd",
        "buy_notional",
        "sell_notional",
        "net_cash_need",
        "cash_coverage",
        "cash_shortfall",
        "health_status",
    ):
        print(f"  {k}: {summary.get(k)}")
    print(f"  orders: {summary.get('orders_path')}")
    print(f"  broker_send: {summary.get('broker_send')} (always false)")

    xpath = None
    if not args.no_xlsx:
        try:
            from ops.ops_excel_write import write_ops_xlsx

            toss_book = None
            try:
                from ops.ops_monthly_run import load_positions as _lp

                toss_book = getattr(_lp, "last_toss_book", None)
            except Exception:
                toss_book = None
            xpath = write_ops_xlsx(run_dir, positions=args.positions, toss_book=toss_book)
            print(f"  excel={xpath}")
        except PermissionError as e:
            print(f"  EXCEL LOCKED? close workbook and retry: {e}")
            return 1
        except Exception as e:
            print(f"  excel refresh failed: {e}")
            return 1
    else:
        print("  excel=skipped (--no-xlsx)")

    print()
    print("next_human_steps:")
    print(f"  1) open {xpath or summary.get('xlsx_hint')}")
    print("  2) check 01_Portfolio_Now (live book) + 05_Trade (sell-first ticket)")
    print("  3) approve, then HTS execute SELL -> BUY (next open)")
    print("  4) book fills manually (no broker auto-send)")
    return 0


def cmd_execute(args: argparse.Namespace) -> int:
    """One-shot rebalance ticket + gates + LIVE Toss send (real orders).

    Production path: LIVE_ORDERS_ENABLED=True after research lock / human approval.
    If LIVE is False, gates still run then BLOCK with zero order POSTs.
    """
    _banner("7", "EXECUTE - ticket + gates + LIVE Toss send (real orders)")
    print("procedure:")
    print("  1) rebuild rebalance ticket (target + live book)")
    print("  2) refresh Excel 05_Trade / 01_Portfolio_Now")
    print("  3) CSV xcheck + materialize execute_send_list.json")
    print("  4) safety gates (qty, cash, caps, sell-first)")
    print("  5) LIVE send: SELL full-fill then BUY (real order POSTs when enabled)")
    print("  6) fills jsonl + status merge")
    print()

    if getattr(args, "run_dir", None):
        run_dir = Path(args.run_dir)
    else:
        run_dir, _ = resolve_ops_month(getattr(args, "asof", None))

    from ops.ops_execute import run_execute

    code, summary = run_execute(
        run_dir,
        positions=getattr(args, "positions", "toss"),
        capital_usd=getattr(args, "capital", None),
        asof=getattr(args, "asof", None),
        no_xlsx=bool(getattr(args, "no_xlsx", False)),
        risk_mode=getattr(args, "risk_mode", None),
        confirm_high_value=bool(getattr(args, "confirm_high_value", False)),
        confirm_outside_window=bool(getattr(args, "confirm_outside_window", False)),
    )
    print("summary:")
    for k in (
        "phase",
        "live_orders_enabled",
        "n_sendable",
        "http_order_posts",
        "error",
        "block_reason",
        "message",
        "fills",
        "outside_window_confirmed",
        "excel",
        "ok",
    ):
        if k in summary:
            print(f"  {k}: {summary.get(k)}")
    if summary.get("gate_a"):
        ga = summary["gate_a"]
        print(f"  gate_a.ok: {ga.get('ok')} reasons: {ga.get('reasons')}")
    if code != 0:
        print(f"EXECUTE exit={code}")
    else:
        print("EXECUTE ok")
    return code


def cmd_risk_reset(args: argparse.Namespace) -> int:
    """Clear sticky L2 only with an explicit operator acknowledgement."""
    from ops.ops_live_safety import reset_sticky_l2

    try:
        path = reset_sticky_l2(args.account_tail, args.ack)
    except Exception as exc:
        print(f"risk-reset refused: {exc}")
        return 2
    print(f"risk-reset recorded: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ops.py",
        description="US-Robust ops procedure CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Monthly flow:\n"
            "  python ops.py status\n"
            "  python ops.py refresh\n"
            "  python ops.py monthly\n"
            "  python ops.py rebalance\n"
            "  python ops.py execute   # LIVE real orders when enabled\n"
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", help="check secrets + data/us panels + toss + excel sync")
    sp.add_argument(
        "--no-toss-probe",
        action="store_true",
        help="skip live Toss token/holdings probe (keys presence only)",
    )
    sp.add_argument(
        "--positions",
        default="toss",
        help="positions source for excel sync (default toss)",
    )
    sp.add_argument("--no-xlsx", action="store_true", help="skip month Excel sync")
    sp.set_defaults(func=cmd_status)
    wk = sub.add_parser("weekly", help="record the week's live NAV + SPY snapshot at the weekly anchor (results/ops_runs/daily_nav.csv)")
    wk.set_defaults(func=cmd_weekly)
    rp = sub.add_parser("refresh", help="refresh US yfinance panels + valuation + excel sync")
    rp.add_argument(
        "--kr",
        action="store_true",
        help="refused: KR KRX/DART ETL is quarantined in US-only ops",
    )
    rp.add_argument(
        "--smart",
        action="store_true",
        help="use cache when sufficient (sets force=False; default is force refresh)",
    )
    rp.add_argument(
        "--with-fundamentals",
        action="store_true",
        help="also download/update fundamentals before valuation rebuild (slower)",
    )
    rp.add_argument(
        "--positions",
        default="toss",
        help="positions source for excel sync (default toss)",
    )
    rp.add_argument("--no-xlsx", action="store_true", help="skip month Excel sync")
    rp.set_defaults(func=cmd_refresh)

    mp = sub.add_parser("monthly", help="select + weight + orders + health + excel")
    mp.add_argument("--asof", default=None, help="YYYY-MM-DD signal upper bound (completed month-end)")
    mp.add_argument(
        "--top-n",
        type=int,
        default=TOP_N_DEFAULT,
        help=f"universe size (default {TOP_N_DEFAULT} from policy)",
    )
    mp.add_argument(
        "--positions",
        default="toss",
        help="default 'toss' live US book; CSV path; or 'none' for empty book",
    )
    mp.add_argument("--out-dir", default=None)
    mp.add_argument("--no-xlsx", action="store_true", help="skip Excel autofill/sync")
    mp.add_argument("--capital", type=float, default=None, help="USD capital for share qty sizing")
    mp.add_argument(
        "--force-intramonth",
        action="store_true",
        help="research only: allow incomplete current-month signal",
    )
    mp.set_defaults(func=cmd_monthly)

    bp = sub.add_parser(
        "rebalance",
        help="rebuild buy/sell ticket from target+live book; refresh Portfolio/Trade Excel",
    )
    bp.add_argument("--run-dir", default=None, help="results/ops_runs/YYYY-MM (default: active month)")
    bp.add_argument("--asof", default=None, help="used only to resolve active month when --run-dir omitted")
    bp.add_argument(
        "--positions",
        default="toss",
        help="default 'toss' live US book; CSV path; or 'none' for empty book",
    )
    bp.add_argument("--capital", type=float, default=None, help="USD capital override for share qty")
    bp.add_argument(
        "--risk-mode", choices=("NORMAL", "L1", "L2"), default="NORMAL",
        help="manual portfolio risk overlay; L1 gross=50%%, L2 no BUY",
    )
    bp.add_argument("--no-xlsx", action="store_true", help="skip Excel rebuild")
    bp.set_defaults(func=cmd_rebalance)

    xp = sub.add_parser(
        "execute",
        help="rebuild ticket+gates then LIVE Toss send (real orders when LIVE_ORDERS_ENABLED)",
    )
    xp.add_argument("--run-dir", default=None, help="results/ops_runs/YYYY-MM (default: active month)")
    xp.add_argument("--asof", default=None, help="resolve active month when --run-dir omitted")
    xp.add_argument(
        "--positions",
        default="toss",
        help="default 'toss' live US book; CSV path; or 'none'",
    )
    xp.add_argument("--capital", type=float, default=None, help="research only; LIVE rejects overrides")
    xp.add_argument(
        "--risk-mode", choices=("NORMAL", "L1", "L2"), required=True,
        help="required manual risk decision: NORMAL, L1 gross 50%%, or sticky L2 no BUY",
    )
    xp.add_argument(
        "--confirm-high-value", action="store_true",
        help="explicitly acknowledge any conservative high-value order gate",
    )
    xp.add_argument(
        "--confirm-outside-window", action="store_true",
        help="explicit operator acknowledgment to execute outside the regular next-open window (policy deviation; orders still placed at market)",
    )
    xp.add_argument("--no-xlsx", action="store_true", help="skip Excel rebuild")
    xp.set_defaults(func=cmd_execute)

    ep = sub.add_parser("excel", help="refill Excel from an existing ops_runs folder")
    ep.add_argument("--run-dir", required=True, help="results/ops_runs/YYYY-MM")
    ep.add_argument("--master", default=None, help="optional master template path")
    ep.add_argument(
        "--positions",
        default="toss",
        help="default 'toss' live US book; CSV path; or 'none' to skip live book",
    )
    ep.set_defaults(func=cmd_excel)

    rr = sub.add_parser("risk-reset", help="clear sticky L2 with an audited acknowledgement")
    rr.add_argument("--account-tail", required=True, help="last four account digits shown by status")
    rr.add_argument("--ack", required=True, help="operator acknowledgement/reason (minimum 4 chars)")
    rr.set_defaults(func=cmd_risk_reset)

    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    code = args.func(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
