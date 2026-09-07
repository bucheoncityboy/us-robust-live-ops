"""Fail-closed safety primitives for US-Robust live operations.

This module has no import-time network side effects.  Python CSV/package files
remain the source of truth; Excel is a read-only mirror.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from ops.ops_us_policy import MAX_NAME, normalize_symbol

ROOT = Path(__file__).resolve().parent.parent
NY_TZ = ZoneInfo("America/New_York")
KST_TZ = ZoneInfo("Asia/Seoul")
PACKAGE_HASH_FILES = ("signals.csv", "target.csv")
MAX_EXECUTE_AGE_DAYS = 7
OPEN_WINDOW_MINUTES = 30
MIN_BUY_USD = 1.0
CASH_BUFFER_RATIO = 0.02
HIGH_VALUE_USD_CONSERVATIVE = 70_000.0
RISK_MODES = ("NORMAL", "L1", "L2")
RISK_STATE_DIR = ROOT / "results" / "ops_state"


def ny_today(now: Optional[Any] = None) -> date:
    if now is None:
        return datetime.now(timezone.utc).astimezone(NY_TZ).date()
    if isinstance(now, date) and not isinstance(now, datetime):
        return now
    ts = pd.Timestamp(now)
    if ts.tzinfo is None:
        return ts.date()
    return ts.tz_convert(NY_TZ).date()


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)
    return path


def atomic_write_json(path: Path, payload: Any) -> Path:
    return atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def atomic_write_csv(df: pd.DataFrame, path: Path, *, encoding: str = "utf-8-sig") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    df.to_csv(tmp, index=False, encoding=encoding)
    os.replace(tmp, path)
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_package_manifest(run_dir: Path) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    health = json.loads((run_dir / "health.json").read_text(encoding="utf-8"))
    files: Dict[str, str] = {}
    missing: List[str] = []
    for name in PACKAGE_HASH_FILES:
        path = run_dir / name
        if path.exists():
            files[name] = _sha256(path)
        else:
            missing.append(name)
    digest = hashlib.sha256(
        "|".join(f"{k}:{files[k]}" for k in sorted(files)).encode()
    ).hexdigest()
    return {
        "version": 1,
        "package_id": f"{health.get('signal_date', run_dir.name)}-{digest[:12]}",
        "signal_date": health.get("signal_date"),
        "force_intramonth": bool(health.get("force_intramonth")),
        "files": files,
        "missing": missing,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }


def write_package_manifest(run_dir: Path) -> Path:
    manifest = build_package_manifest(run_dir)
    if manifest["missing"]:
        raise ValueError(f"package files missing: {manifest['missing']}")
    return atomic_write_json(Path(run_dir) / "package_manifest.json", manifest)


def verify_package_manifest(run_dir: Path) -> Tuple[bool, List[str], Dict[str, Any]]:
    run_dir = Path(run_dir)
    path = run_dir / "package_manifest.json"
    if not path.exists():
        return False, ["manifest_missing"], {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"manifest_unreadable:{type(exc).__name__}"], {}
    reasons: List[str] = []
    for name in PACKAGE_HASH_FILES:
        expected = (manifest.get("files") or {}).get(name)
        file_path = run_dir / name
        if not expected:
            reasons.append(f"manifest_hash_missing:{name}")
        elif not file_path.exists():
            reasons.append(f"package_file_missing:{name}")
        elif _sha256(file_path) != expected:
            reasons.append(f"package_hash_mismatch:{name}")
    return not reasons, reasons, manifest


def completed_month_signal(
    signal_date: Any,
    close_index: Iterable[Any],
    *,
    now: Optional[Any] = None,
) -> Tuple[bool, List[str]]:
    """Conservative offline month-completion check.

    Exact next-session validation is repeated against Toss' official US market
    calendar immediately before LIVE sends.
    """
    sd = pd.Timestamp(signal_date).normalize()
    today = ny_today(now)
    reasons: List[str] = []
    if (sd.year, sd.month) >= (today.year, today.month):
        reasons.append("current_or_future_new_york_month")
    idx = pd.DatetimeIndex(pd.to_datetime(list(close_index))).tz_localize(None).normalize()
    if any((d > sd and d.year == sd.year and d.month == sd.month) for d in idx):
        reasons.append("later_same_month_session_exists")
    cal_end = (sd + pd.offsets.MonthEnd(0)).normalize()
    if (cal_end - sd).days > 3:
        reasons.append(f"signal_not_near_calendar_month_end:{sd.date()}")
    return not reasons, reasons


def _single_csv_date(path: Path) -> Tuple[Optional[date], Optional[str]]:
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        return None, f"{path.name}_unreadable:{type(exc).__name__}"
    if "asof" not in df.columns:
        return None, f"{path.name}_missing_asof"
    values = pd.to_datetime(df["asof"], errors="coerce").dropna().dt.date.unique().tolist()
    if len(values) != 1:
        return None, f"{path.name}_asof_count:{len(values)}"
    return values[0], None


def validate_execute_package(
    run_dir: Path,
    *,
    asof: Optional[str] = None,
    now: Optional[Any] = None,
    max_age_days: int = MAX_EXECUTE_AGE_DAYS,
) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    reasons: List[str] = []
    required = ("health.json", "target.csv", "orders_preview.csv", "package_manifest.json")
    for name in required:
        if not (run_dir / name).exists():
            reasons.append(f"missing:{name}")
    if reasons:
        return {"ok": False, "reasons": reasons}
    try:
        health = json.loads((run_dir / "health.json").read_text(encoding="utf-8"))
        signal = pd.Timestamp(health.get("signal_date")).date()
    except Exception:
        return {"ok": False, "reasons": ["health_signal_date_invalid"]}
    if bool(health.get("force_intramonth")):
        reasons.append("force_intramonth_package")
    for name in ("target.csv", "orders_preview.csv"):
        value, error = _single_csv_date(run_dir / name)
        if error:
            reasons.append(error)
        elif value != signal:
            reasons.append(f"{name}_asof_mismatch:{value}!={signal}")
    if asof is not None:
        try:
            if pd.Timestamp(asof).date() != signal:
                reasons.append("cli_asof_mismatch")
        except Exception:
            reasons.append("cli_asof_invalid")
    if re.fullmatch(r"\d{4}-\d{2}", run_dir.name):
        expected = f"{signal.year:04d}-{signal.month:02d}"
        if run_dir.name != expected:
            reasons.append(f"run_dir_month_mismatch:{run_dir.name}!={expected}")
    today = ny_today(now)
    age = (today - signal).days
    if age < 0:
        reasons.append("signal_in_future")
    if age > int(max_age_days):
        reasons.append(f"signal_stale_days:{age}")
    expected_month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    if (signal.year, signal.month) != expected_month:
        reasons.append("signal_month_not_latest_completed")
    cal_end = (pd.Timestamp(signal) + pd.offsets.MonthEnd(0)).date()
    if (cal_end - signal).days > 3:
        reasons.append("signal_not_near_month_end")
    manifest_ok, manifest_reasons, manifest = verify_package_manifest(run_dir)
    if not manifest_ok:
        reasons.extend(manifest_reasons)
    if manifest.get("signal_date") != str(signal):
        reasons.append("manifest_signal_date_mismatch")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "signal_date": str(signal),
        "reference_date_ny": str(today),
        "signal_age_days": age,
        "package_id": manifest.get("package_id"),
    }


def execution_evidence(run_dir: Path, sendable: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    wanted = {normalize_symbol(r.get("code")) for r in sendable if normalize_symbol(r.get("code"))}
    evidence: List[Dict[str, Any]] = []
    status_path = run_dir / "execute_status.json"
    if status_path.exists():
        try:
            statuses = json.loads(status_path.read_text(encoding="utf-8")).get("codes") or {}
            for raw, status in statuses.items():
                code = normalize_symbol(raw)
                if code in wanted and str(status).upper().startswith("FILLED"):
                    evidence.append({"source": status_path.name, "code": code, "status": status})
        except Exception as exc:
            evidence.append({"source": status_path.name, "error": type(exc).__name__})
    for path in sorted(run_dir.glob("fills_*.jsonl")):
        try:
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                code = normalize_symbol(row.get("code"))
                event = str(row.get("event") or "").upper()
                terminal = str(row.get("terminal") or "").upper()
                if code in wanted and (event in {"FILL", "FULL_FILL"} or terminal in {"FULL_FILL", "PARTIAL", "PARTIAL_FILLED", "TIMEOUT_OPEN", "UNKNOWN_NET"}):
                    evidence.append({"source": path.name, "line": line_no, "code": code, "event": event, "terminal": terminal})
        except Exception as exc:
            evidence.append({"source": path.name, "error": type(exc).__name__})
    attempts_path = run_dir / "execute_attempt.json"
    result_path = run_dir / "execute_attempt_result.json"
    if attempts_path.exists():
        retryable = False
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                retryable = str(result.get("status") or "").endswith("_ZERO_POST") and int(result.get("http_order_posts", -1)) == 0
            except Exception:
                retryable = False
        if not retryable:
            evidence.append({"source": attempts_path.name, "event": "AMBIGUOUS_ATTEMPT"})
    return {"blocked": bool(evidence), "evidence": evidence, "codes": sorted(wanted)}


def acquire_execution_claim(run_dir: Path, payload: Dict[str, Any]) -> Path:
    run_dir = Path(run_dir)
    claim = run_dir / "execute_attempt.json"
    result = run_dir / "execute_attempt_result.json"
    if claim.exists():
        retryable = False
        if result.exists():
            try:
                prior = json.loads(result.read_text(encoding="utf-8"))
                retryable = str(prior.get("status") or "").endswith("_ZERO_POST") and int(prior.get("http_order_posts", -1)) == 0
            except Exception:
                pass
        if not retryable:
            raise FileExistsError(f"ambiguous/prior execute claim exists: {claim}")
        archive = run_dir / f"execute_attempt_retry_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json"
        os.replace(claim, archive)
    body = {"claimed_utc": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), **payload}
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(claim, flags)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(body, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    return claim


def write_attempt_result(run_dir: Path, payload: Dict[str, Any]) -> Path:
    return atomic_write_json(
        Path(run_dir) / "execute_attempt_result.json",
        {"updated_utc": datetime.now(timezone.utc).isoformat(), **payload},
    )


def _risk_path(account_tail: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", account_tail or "unknown")
    return RISK_STATE_DIR / f"manual_risk_{safe}.json"


def resolve_risk_mode(mode: Optional[str], account_tail: str = "unknown") -> str:
    if not mode:
        raise ValueError("LIVE execute requires explicit --risk-mode NORMAL|L1|L2")
    requested = str(mode).upper()
    if requested not in RISK_MODES:
        raise ValueError(f"invalid risk mode: {mode}")
    path = _risk_path(account_tail)
    prior: Dict[str, Any] = {}
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raise ValueError("manual risk state unreadable")
    if prior.get("sticky_l2") and requested != "L2":
        raise ValueError("sticky L2 active; run risk-reset with explicit acknowledgement")
    if requested == "L2":
        atomic_write_json(path, {"sticky_l2": True, "mode": "L2", "updated_utc": datetime.now(timezone.utc).isoformat()})
    return requested


def reset_sticky_l2(account_tail: str, acknowledgement: str) -> Path:
    if not acknowledgement or len(acknowledgement.strip()) < 4:
        raise ValueError("risk-reset requires a meaningful acknowledgement")
    path = _risk_path(account_tail)
    return atomic_write_json(path, {
        "sticky_l2": False,
        "mode": "RESET",
        "acknowledgement": acknowledgement.strip(),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    })


def apply_risk_weights(weights: Dict[str, float], mode: str) -> Dict[str, float]:
    clean = {normalize_symbol(k): float(v) for k, v in weights.items() if normalize_symbol(k) and float(v) > 0}
    mode = str(mode).upper()
    if mode == "NORMAL":
        return clean
    if mode == "L2":
        return {}
    if mode == "L1":
        gross = sum(clean.values())
        if gross <= 0:
            return {}
        scale = min(1.0, 0.50 / gross)
        return {k: v * scale for k, v in clean.items()}
    raise ValueError(f"invalid risk mode: {mode}")


def validate_unique_rows(rows: Iterable[Dict[str, Any]]) -> List[str]:
    seen: set[Tuple[str, str]] = set()
    reasons: List[str] = []
    for row in rows:
        key = (normalize_symbol(row.get("code")), str(row.get("side") or "").upper())
        if not key[0]:
            reasons.append("empty_code")
        elif key in seen:
            reasons.append(f"duplicate_order:{key[0]}:{key[1]}")
        seen.add(key)
    return reasons


def validate_order_gates(
    sendable: List[Dict[str, Any]],
    *,
    capital_usd: Optional[float],
    cash_usd: Optional[float],
    phase: str,
    confirm_high_value: bool = False,
) -> Tuple[List[str], List[str]]:
    reasons = validate_unique_rows(sendable)
    warnings: List[str] = []
    aggregate: Dict[str, float] = {}
    for row in sendable:
        code = normalize_symbol(row.get("code"))
        side = str(row.get("side") or "").upper()
        qty = float(row.get("send_qty") or 0)
        notional = float(row.get("notional") or 0)
        if qty <= 0:
            reasons.append(f"non_positive_qty:{code}")
        if abs(qty - round(qty, 6)) > 1e-9:
            reasons.append(f"fractional_precision_gt_6:{code}")
        if side == "BUY" and notional < MIN_BUY_USD:
            reasons.append(f"buy_below_minimum:{code}:{notional:.4f}")
        if notional >= HIGH_VALUE_USD_CONSERVATIVE and not confirm_high_value:
            reasons.append(f"high_value_confirmation_required:{code}:{notional:.2f}")
        if side == "BUY":
            aggregate[code] = aggregate.get(code, 0.0) + notional
    if capital_usd is None or float(capital_usd) <= 0:
        reasons.append("capital_missing")
    else:
        limit = float(capital_usd) * MAX_NAME + 1.0
        for code, amount in aggregate.items():
            if amount > limit:
                reasons.append(f"aggregate_name_cap:{code}:{amount:.2f}>{limit:.2f}")
    if phase.upper() == "B":
        if cash_usd is None:
            reasons.append("post_sell_cash_missing")
        else:
            buy_total = sum(float(r.get("notional") or 0) for r in sendable if str(r.get("side")).upper() == "BUY")
            available = max(0.0, float(cash_usd) * (1.0 - CASH_BUFFER_RATIO))
            if buy_total > available + 0.01:
                reasons.append(f"cash_buffer_breach:{buy_total:.2f}>{available:.2f}")
    return reasons, warnings


def validate_account_identity(book: Optional[Dict[str, Any]], client: Any = None) -> List[str]:
    if not book:
        return ["live_portfolio_book_missing"]
    reasons: List[str] = []
    seq = str(book.get("account_seq") or "")
    pin = os.environ.get("TOSS_ACCOUNT_SEQ", "").strip()
    if not seq:
        reasons.append("portfolio_account_seq_missing")
    if str(book.get("account_type") or "").upper() != "BROKERAGE":
        reasons.append("portfolio_account_not_brokerage")
    if pin and seq != pin:
        reasons.append("portfolio_account_pin_mismatch")
    if client is not None and str(getattr(client, "account_seq", "")) != seq:
        reasons.append("order_client_account_mismatch")
    return reasons


def _walk_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def validate_official_next_open(
    calendar_payload: Dict[str, Any],
    signal_date: str,
    *,
    now: Optional[Any] = None,
    window_minutes: int = OPEN_WINDOW_MINUTES,
) -> List[str]:
    """Validate exact next US trading day and first regular-open window.

    The parser intentionally accepts common Toss schema spellings but blocks if
    no unambiguous dated regular session can be found.
    """
    signal = pd.Timestamp(signal_date).date()
    sessions: List[Tuple[date, pd.Timestamp, pd.Timestamp]] = []
    for row in _walk_dicts(calendar_payload):
        raw_date = row.get("date") or row.get("marketDate") or row.get("localDate")
        regular = row.get("regularMarket") or row.get("regular")
        if not raw_date or not isinstance(regular, dict):
            continue
        start = regular.get("startTime") or regular.get("start") or regular.get("startAt") or regular.get("openAt")
        end = regular.get("endTime") or regular.get("end") or regular.get("endAt") or regular.get("closeAt")
        if not start or not end:
            continue
        try:
            d = pd.Timestamp(raw_date).date()
            st, en = pd.Timestamp(start), pd.Timestamp(end)
            if st.tzinfo is None:
                st = st.tz_localize(KST_TZ)
            if en.tzinfo is None:
                en = en.tz_localize(KST_TZ)
            sessions.append((d, st, en))
        except Exception:
            continue
    future = sorted((s for s in sessions if s[0] > signal), key=lambda x: x[0])
    if not future:
        return ["official_next_session_unavailable"]
    trade_date, start, end = future[0]
    current = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if current.tzinfo is None:
        current = current.tz_localize(KST_TZ)
    current = current.tz_convert(start.tz)
    deadline = min(end, start + pd.Timedelta(minutes=int(window_minutes)))
    reasons: List[str] = []
    if current.date() != start.date() or current < start or current > deadline:
        reasons.append(f"outside_next_open_window:{trade_date}:{start.isoformat()}..{deadline.isoformat()}")
    return reasons


def sanitize_excel_value(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + value
    return value
