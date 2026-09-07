"""Toss OpenAPI order client for ops.py execute (US live path).

LIVE_ORDERS_ENABLED is the hard switch for real order POSTs.
Current production value is True after 2026-07-20 human approval
(US sell-first / fractional). When False, place_order hard-refuses
(no HTTP POST to /api/v1/orders).

Policy: only ops.py execute may call this module for real sends.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from ops.ops_us_policy import is_integer_qty, is_positive_qty, normalize_symbol

import requests

from ops.ops_env import get_secret, load_env

BASE_URL = "https://openapi.tossinvest.com"
TIMEOUT = 20

# Research gate - flip only after docs/toss_order_api_research.md checklist 1–4 locked
# and Pre-LIVE human approval. Never enable casually.
# 2026-07-20: human approved LIVE for US sell-first execute (tiny book / fractional).
LIVE_ORDERS_ENABLED = True

POLL_INTERVAL_SEC = 1.0
POLL_WALL_TIMEOUT_SEC = 120.0
MAX_429_RETRIES = 3
BACKOFF_CAPS = (1.0, 2.0, 4.0, 8.0)
QTY_FILL_EPS = 0.0  # exact full fill only
AUTO_CANCEL = False
GET_ORDER_PATH_TEMPLATE = "/api/v1/orders/{order_id}"  # confirm in research before LIVE


class TossOrderError(RuntimeError):
    """Safe order API failure (no secrets)."""


class LiveOrdersBlocked(TossOrderError):
    """Raised when LIVE_ORDERS_ENABLED is False or research incomplete."""


def live_orders_enabled() -> bool:
    return bool(LIVE_ORDERS_ENABLED)


def research_block_reason() -> Optional[str]:
    if not LIVE_ORDERS_ENABLED:
        return (
            "LIVE_ORDERS_ENABLED=False - complete docs/toss_order_api_research.md "
            "checklist and Pre-LIVE approval before enabling real POSTs"
        )
    return None


def _creds() -> Tuple[str, str]:
    load_env()
    key = get_secret("TOSS_API_KEY", "").strip()
    secret = get_secret("TOSS_SECRET_KEY", "").strip()
    if not key or not secret:
        raise TossOrderError("missing TOSS_API_KEY / TOSS_SECRET_KEY")
    return key, secret


def _token(key: str, secret: str) -> str:
    import base64

    creds = base64.b64encode(f"{key}:{secret}".encode()).decode()
    resp = requests.post(
        f"{BASE_URL}/oauth2/token",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        body = resp.text[:220]
        if "IP address not allowed" in body:
            raise TossOrderError("IP not whitelisted for Toss OpenAPI")
        raise TossOrderError(f"oauth failed ({resp.status_code})")
    tok = (resp.json() or {}).get("access_token") or ""
    if not tok:
        raise TossOrderError("oauth returned empty access_token")
    return tok


def _pick_brokerage(accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
    brokers = [a for a in accounts if str(a.get("accountType") or "").upper() == "BROKERAGE"]
    pin = get_secret("TOSS_ACCOUNT_SEQ", "").strip()
    if pin:
        matches = [a for a in brokers if str(a.get("accountSeq") or "") == pin]
        if len(matches) != 1:
            raise TossOrderError("TOSS_ACCOUNT_SEQ does not identify exactly one brokerage account")
        return matches[0]
    if len(brokers) == 1:
        return brokers[0]
    if len(brokers) > 1:
        raise TossOrderError("multiple brokerage accounts; set TOSS_ACCOUNT_SEQ")
    raise TossOrderError("no BROKERAGE account returned")


def resolve_account(token: Optional[str] = None) -> Tuple[str, str, str]:
    """Return (token, account_seq, account_no_tail)."""
    key, secret = _creds()
    tok = token or _token(key, secret)
    resp = requests.get(
        f"{BASE_URL}/api/v1/accounts",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise TossOrderError(f"accounts failed ({resp.status_code})")
    accts = (resp.json() or {}).get("result") or []
    if not isinstance(accts, list):
        raise TossOrderError("accounts payload invalid")
    acct = _pick_brokerage(accts)
    seq = str(acct.get("accountSeq") or "")
    if not seq:
        raise TossOrderError("accountSeq missing")
    tail = str(acct.get("accountNo") or "")[-4:]
    return tok, seq, tail


def make_client_order_id(
    *,
    run_tag: str,
    code: str,
    side: str,
    qty: float,
    attempt: int = 1,
) -> str:
    """≤36 chars, stable-ish unique key per send attempt."""
    raw = f"{run_tag}|{code}|{side}|{qty}|{attempt}"
    h = hashlib.sha1(raw.encode()).hexdigest()[:10]
    side_c = (side or "?")[0].upper()
    sym = normalize_symbol(code) if not str(code).isdigit() else str(code).zfill(6)
    base = f"x{run_tag[-8:]}{sym[-6:]}{side_c}{attempt}{h}"
    return base[:36]


def is_kr_integer_qty(qty: Any) -> bool:
    """Legacy name - positive integer-valued qty (KR whole-share rule)."""
    return is_integer_qty(qty)


def is_positive_qty(qty: Any) -> bool:
    """True when qty is a positive number (accepts fractional US qty)."""
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return False
    return q > 0


def is_whole_share_qty(qty: Any) -> bool:
    """True when qty is a positive whole share (integer-valued)."""
    return is_integer_qty(qty)


def _positive_amount(amount: Any) -> Optional[float]:
    try:
        a = float(amount)
    except (TypeError, ValueError):
        return None
    if a <= 0:
        return None
    return a


def build_order_payload(
    *,
    symbol: str,
    side: str,
    quantity: float,
    client_order_id: str,
    market: str = "US",
    order_type: str = "MARKET",
    time_in_force: str = "DAY",
    confirm_high_value: bool = False,
    order_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Build createOrder body.

    US rules (Toss live):
    - SELL: quantity (fractional MARKET SELL allowed in RTH)
    - BUY whole shares: quantity
    - BUY fractional: orderAmount (USD) — quantity is rejected by Toss
    KR: zfill + integer quantity (legacy).
    """
    mkt = (market or "US").upper()
    side_u = str(side).upper()
    coid = str(client_order_id)[:36]
    if mkt == "US":
        sym = normalize_symbol(symbol)
        if not sym or sym.startswith("0") and not sym.isdigit():
            # reject padded alpha tickers
            if sym and len(sym) > 1 and sym[0] == "0" and not sym.isdigit():
                raise TossOrderError(f"US symbol looks zero-padded: {symbol}")
        body: Dict[str, Any] = {
            "symbol": sym,
            "side": side_u,
            "orderType": order_type,
            "timeInForce": time_in_force,
            "clientOrderId": coid,
            "market": "US",
        }
        amt = _positive_amount(order_amount)
        # All US BUYs are amount-based so market gaps cannot exceed the approved dollars.
        if side_u == "BUY":
            if amt is None or amt < 1.0:
                raise TossOrderError(
                    f"US BUY requires orderAmount >= $1, got qty={quantity} order_amount={order_amount}"
                )
            body["orderAmount"] = float(round(amt, 4))
        else:
            if not is_positive_qty(quantity):
                raise TossOrderError(f"US qty must be positive float, got {quantity}")
            if abs(float(quantity) - round(float(quantity), 6)) > 1e-9:
                raise TossOrderError(f"US fractional SELL supports at most 6 decimals: {quantity}")
            body["quantity"] = float(quantity)
    else:
        if not is_integer_qty(quantity):
            raise TossOrderError(f"KR qty must be positive integer, got {quantity}")
        body = {
            "symbol": str(symbol).zfill(6),
            "side": side_u,
            "orderType": order_type,
            "quantity": int(round(float(quantity))),
            "timeInForce": time_in_force,
            "clientOrderId": coid,
            "market": "KR",
        }
    if confirm_high_value:
        body["confirmHighValueOrder"] = True
    return body


def dry_run_orders(send_list: List[Dict[str, Any]], *, market: str = "US", run_tag: str = "dry") -> Dict[str, Any]:
    """Validate/build payloads without HTTP POST. LIVE must stay blocked."""
    payloads = []
    errors = []
    for i, row in enumerate(send_list or []):
        try:
            code = row.get("code") or row.get("symbol")
            side = row.get("side") or row.get("action") or ""
            if str(side).upper().startswith("SELL"):
                side = "SELL"
            elif str(side).upper().startswith("BUY"):
                side = "BUY"
            qty = row.get("send_qty", row.get("qty", row.get("quantity")))
            amt = row.get("order_amount", row.get("notional", row.get("orderAmount")))
            coid = make_client_order_id(run_tag=run_tag, code=str(code), side=str(side), qty=float(qty or 0), attempt=i + 1)
            body = build_order_payload(
                symbol=str(code),
                side=str(side),
                quantity=float(qty),
                client_order_id=coid,
                market=market,
                order_amount=_positive_amount(amt),
            )
            payloads.append({"row_index": i, "payload": body})
        except Exception as e:
            errors.append(
                {
                    "row_index": i,
                    "error": str(e),
                    "row": {k: row.get(k) for k in ("code", "side", "send_qty", "qty", "notional", "order_amount")},
                }
            )
    return {
        "dry_run": True,
        "live_orders_enabled": live_orders_enabled(),
        "http_order_posts": 0,
        "market": market,
        "n_rows": len(send_list or []),
        "n_ok": len(payloads),
        "n_err": len(errors),
        "payloads": payloads,
        "errors": errors,
    }



@dataclass
class OrderAttempt:
    code: str
    side: str
    qty: float
    client_order_id: str
    order_id: Optional[str] = None
    status: str = "PENDING"
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    error: Optional[str] = None
    attempts: int = 0
    terminal: str = ""  # FULL_FILL | PARTIAL | ZERO_REJECT | TIMEOUT_OPEN | UNKNOWN_NET | BLOCKED


@dataclass
class OrderClient:
    """HTTP order client. Never posts when LIVE_ORDERS_ENABLED is False."""

    token: str = ""
    account_seq: str = ""
    account_no_tail: str = ""
    http_post_count: int = 0
    http_get_count: int = 0
    last_posts: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def connect(cls) -> "OrderClient":
        tok, seq, tail = resolve_account()
        return cls(token=tok, account_seq=seq, account_no_tail=tail)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Tossinvest-Account": str(self.account_seq),
        }

    def ensure_live_allowed(self) -> None:
        reason = research_block_reason()
        if reason:
            raise LiveOrdersBlocked(reason)

    def create_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        client_order_id: str,
        order_type: str = "MARKET",
        time_in_force: str = "DAY",
        confirm_high_value: bool = False,
        market: str = "US",
        order_amount: Optional[float] = None,
    ) -> Dict[str, Any]:
        self.ensure_live_allowed()
        body = build_order_payload(
            symbol=symbol,
            side=side,
            quantity=quantity,
            client_order_id=client_order_id,
            market=market,
            order_type=order_type,
            time_in_force=time_in_force,
            confirm_high_value=confirm_high_value,
            order_amount=order_amount,
        )
        # API body should not include our internal market tag
        body = {k: v for k, v in body.items() if k != "market"}
        return self._post_with_backoff("/api/v1/orders", body)

    def get_order(self, order_id: str) -> Dict[str, Any]:
        self.ensure_live_allowed()
        path = GET_ORDER_PATH_TEMPLATE.format(order_id=order_id)
        return self._get_with_backoff(path)

    def get_open_orders(self) -> List[Dict[str, Any]]:
        raw = self._get_with_backoff("/api/v1/orders?status=OPEN")
        result = raw.get("result") if isinstance(raw, dict) else {}
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return list(result.get("orders") or result.get("items") or [])
        return []

    def get_sellable_quantity(self, symbol: str) -> float:
        raw = self._get_with_backoff(f"/api/v1/sellable-quantity?symbol={normalize_symbol(symbol)}")
        result = raw.get("result") if isinstance(raw, dict) else {}
        if not isinstance(result, dict):
            return 0.0
        for key in ("sellableQuantity", "quantity", "sellableQty"):
            if result.get(key) is not None:
                return float(result[key])
        return 0.0

    def get_us_market_calendar(self, signal_date: str) -> Dict[str, Any]:
        return self._get_with_backoff(f"/api/v1/market-calendar/US?date={signal_date}")

    def _post_with_backoff(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(1, MAX_429_RETRIES + 2):
            self.http_post_count += 1
            self.last_posts.append({"path": path, "body": {k: v for k, v in body.items() if k != "token"}})
            try:
                resp = requests.post(
                    f"{BASE_URL}{path}",
                    headers=self._headers(),
                    json=body,
                    timeout=TIMEOUT,
                )
            except requests.RequestException as e:
                last_err = e
                if attempt > MAX_429_RETRIES:
                    break
                time.sleep(BACKOFF_CAPS[min(attempt - 1, len(BACKOFF_CAPS) - 1)])
                continue
            if resp.status_code == 429:
                last_err = TossOrderError("rate limited (429)")
                if attempt > MAX_429_RETRIES:
                    break
                time.sleep(BACKOFF_CAPS[min(attempt - 1, len(BACKOFF_CAPS) - 1)])
                continue
            if resp.status_code >= 500:
                last_err = TossOrderError(f"server error ({resp.status_code})")
                if attempt > MAX_429_RETRIES:
                    break
                time.sleep(BACKOFF_CAPS[min(attempt - 1, len(BACKOFF_CAPS) - 1)])
                continue
            if resp.status_code not in (200, 201):
                raise TossOrderError(f"{path} failed ({resp.status_code}): {resp.text[:200]}")
            return resp.json() or {}
        raise TossOrderError(f"{path} failed after retries: {last_err}")

    def _get_with_backoff(self, path: str) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(1, MAX_429_RETRIES + 2):
            self.http_get_count += 1
            try:
                resp = requests.get(
                    f"{BASE_URL}{path}",
                    headers=self._headers(),
                    timeout=TIMEOUT,
                )
            except requests.RequestException as e:
                last_err = e
                if attempt > MAX_429_RETRIES:
                    break
                time.sleep(BACKOFF_CAPS[min(attempt - 1, len(BACKOFF_CAPS) - 1)])
                continue
            if resp.status_code == 429:
                last_err = TossOrderError("rate limited (429)")
                if attempt > MAX_429_RETRIES:
                    break
                time.sleep(BACKOFF_CAPS[min(attempt - 1, len(BACKOFF_CAPS) - 1)])
                continue
            if resp.status_code != 200:
                raise TossOrderError(f"{path} failed ({resp.status_code})")
            return resp.json() or {}
        raise TossOrderError(f"{path} failed after retries: {last_err}")

    def classify_fill(
        self,
        requested_qty: float,
        filled_qty: float,
        status: str = "",
        *,
        amount_based: bool = False,
    ) -> str:
        filled = float(filled_qty or 0.0)
        req = float(requested_qty or 0.0)
        st = str(status or "").upper()
        if st == "FILLED":
            return "FULL_FILL"
        if st in {"REJECTED", "CANCELED", "CANCELLED", "EXPIRED", "REPLACED", "FAILED"}:
            return "PARTIAL" if filled > 0 else "ZERO_REJECT"
        if amount_based:
            return "PARTIAL" if filled > 0 else "PENDING"
        if req > 0 and filled + QTY_FILL_EPS >= req:
            return "FULL_FILL"
        return "PARTIAL" if filled > 0 else "PENDING"

    def await_fill(
        self,
        *,
        order_id: str,
        requested_qty: float,
        poll_interval: float = POLL_INTERVAL_SEC,
        wall_timeout: float = POLL_WALL_TIMEOUT_SEC,
        amount_based: bool = False,
    ) -> OrderAttempt:
        """Poll until full fill or fail-stop terminal. No auto-cancel."""
        self.ensure_live_allowed()
        t0 = time.time()
        last: Dict[str, Any] = {}
        while time.time() - t0 < wall_timeout:
            try:
                raw = self.get_order(order_id)
            except TossOrderError as e:
                # unknown net: do not blind re-POST; surface and stop
                att = OrderAttempt(
                    code="",
                    side="",
                    qty=requested_qty,
                    client_order_id="",
                    order_id=order_id,
                    status="UNKNOWN_NET",
                    error=str(e),
                    terminal="UNKNOWN_NET",
                )
                return att
            last = raw.get("result") if isinstance(raw.get("result"), dict) else raw
            filled = _extract_filled_qty(last)
            status = str(last.get("status") or last.get("orderStatus") or "")
            term = self.classify_fill(requested_qty, filled, status, amount_based=amount_based)
            if term == "FULL_FILL":
                return OrderAttempt(
                    code=str(last.get("symbol") or ""),
                    side=str(last.get("side") or ""),
                    qty=requested_qty,
                    client_order_id=str(last.get("clientOrderId") or ""),
                    order_id=order_id,
                    status=status or "FILLED",
                    filled_qty=filled,
                    avg_price=_extract_avg_px(last),
                    terminal="FULL_FILL",
                )
            if term in ("PARTIAL", "ZERO_REJECT") and any(
                x in status.upper() for x in ("REJECT", "CANCEL", "EXPIRED", "FILL", "DONE", "CLOSED")
            ):
                return OrderAttempt(
                    code=str(last.get("symbol") or ""),
                    side=str(last.get("side") or ""),
                    qty=requested_qty,
                    client_order_id=str(last.get("clientOrderId") or ""),
                    order_id=order_id,
                    status=status,
                    filled_qty=filled,
                    avg_price=_extract_avg_px(last),
                    terminal=term if filled > 0 else "ZERO_REJECT",
                )
            time.sleep(poll_interval)
        filled = _extract_filled_qty(last)
        st = str(last.get("status") or last.get("orderStatus") or "TIMEOUT").upper()
        if st == "FILLED":
            term = "FULL_FILL"
        elif filled > 0:
            term = "PARTIAL"
        else:
            term = "TIMEOUT_OPEN"
        return OrderAttempt(
            code=str(last.get("symbol") or ""),
            side=str(last.get("side") or ""),
            qty=requested_qty,
            client_order_id=str(last.get("clientOrderId") or ""),
            order_id=order_id,
            status=str(last.get("status") or "TIMEOUT"),
            filled_qty=filled,
            avg_price=_extract_avg_px(last),
            terminal=term,
            error="poll wall timeout",
        )


def _extract_filled_qty(order: Dict[str, Any]) -> float:
    if not order:
        return 0.0
    ex = order.get("execution") or {}
    for k in ("filledQuantity", "filled_qty", "filledQty", "executedQuantity"):
        if k in ex and ex[k] is not None:
            try:
                return float(ex[k])
            except (TypeError, ValueError):
                pass
        if k in order and order[k] is not None:
            try:
                return float(order[k])
            except (TypeError, ValueError):
                pass
    return 0.0


def _extract_avg_px(order: Dict[str, Any]) -> Optional[float]:
    if not order:
        return None
    ex = order.get("execution") or {}
    for k in ("averageFilledPrice", "avgPrice", "averagePrice"):
        if k in ex and ex[k] is not None:
            try:
                return float(ex[k])
            except (TypeError, ValueError):
                pass
        if k in order and order[k] is not None:
            try:
                return float(order[k])
            except (TypeError, ValueError):
                pass
    return None


def place_and_await(
    client: OrderClient,
    *,
    code: str,
    side: str,
    qty: float,
    run_tag: str,
    attempt: int = 1,
    order_amount: Optional[float] = None,
    confirm_high_value: bool = False,
) -> OrderAttempt:
    """Create + await full fill. Raises LiveOrdersBlocked when LIVE false."""
    client.ensure_live_allowed()
    coid = make_client_order_id(run_tag=run_tag, code=code, side=side, qty=qty, attempt=attempt)
    high = False
    amt = _positive_amount(order_amount)
    amount_based = str(side).upper() == "BUY"
    raw = client.create_order(
        symbol=code,
        side=side,
        quantity=qty,
        client_order_id=coid,
        confirm_high_value=bool(confirm_high_value),
        order_amount=amt,
    )
    result = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    order_id = str(
        (result or {}).get("orderId")
        or (result or {}).get("id")
        or raw.get("orderId")
        or ""
    )
    if not order_id:
        return OrderAttempt(
            code=code,
            side=side,
            qty=qty,
            client_order_id=coid,
            status="REJECT",
            error="createOrder returned no orderId",
            terminal="ZERO_REJECT",
            attempts=attempt,
        )
    att = client.await_fill(order_id=order_id, requested_qty=qty, amount_based=amount_based)
    att.code = code
    att.side = side
    att.qty = qty
    att.client_order_id = coid
    att.attempts = attempt
    return att


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
