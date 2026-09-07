"""Read-only Toss Securities portfolio client for US-Robust ops.

Purpose: connection status + live US holdings for Excel / monthly positions.
No order endpoints. No mandatory disk snapshot.
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from ops.ops_env import get_secret, load_env

BASE_URL = "https://openapi.tossinvest.com"
TIMEOUT = 20


class TossPortfolioError(RuntimeError):
    """Toss portfolio API failure (safe message, no secrets)."""


def _creds() -> Tuple[str, str]:
    load_env()
    key = get_secret("TOSS_API_KEY", "").strip()
    secret = get_secret("TOSS_SECRET_KEY", "").strip()
    if not key or not secret:
        raise TossPortfolioError("missing TOSS_API_KEY / TOSS_SECRET_KEY")
    return key, secret


def _token(key: str, secret: str) -> str:
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
            raise TossPortfolioError("IP not whitelisted for Toss OpenAPI")
        raise TossPortfolioError(f"oauth failed ({resp.status_code})")
    tok = (resp.json() or {}).get("access_token") or ""
    if not tok:
        raise TossPortfolioError("oauth returned empty access_token")
    return tok


def _get(path: str, token: str, headers: Optional[Dict[str, str]] = None) -> Any:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    resp = requests.get(f"{BASE_URL}{path}", headers=h, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise TossPortfolioError(f"{path} failed ({resp.status_code})")
    return resp.json()


def _pick_brokerage(accounts: List[Dict[str, Any]]) -> Dict[str, Any]:
    brokers = [a for a in accounts if str(a.get("accountType") or "").upper() == "BROKERAGE"]
    pin = get_secret("TOSS_ACCOUNT_SEQ", "").strip()
    if pin:
        matches = [a for a in brokers if str(a.get("accountSeq") or "") == pin]
        if len(matches) != 1:
            raise TossPortfolioError("TOSS_ACCOUNT_SEQ does not identify exactly one brokerage account")
        return matches[0]
    if len(brokers) == 1:
        return brokers[0]
    if len(brokers) > 1:
        raise TossPortfolioError("multiple brokerage accounts; set TOSS_ACCOUNT_SEQ")
    raise TossPortfolioError("no BROKERAGE account returned")


def _is_kr_item(item: Dict[str, Any]) -> bool:
    country = str(item.get("marketCountry") or "").upper()
    ccy = str(item.get("currency") or "").upper()
    sym = str(item.get("symbol") or item.get("code") or "").strip()
    if country in ("KR", "KOR", "KOREA"):
        return True
    if ccy == "KRW" and sym.isdigit():
        return True
    # pure 6-digit KRX-looking codes
    if sym.isdigit() and len(sym) <= 6 and ccy in ("", "KRW"):
        return True
    return False


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_holdings_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Toss holdings JSON (items schema) into ops book."""
    items = result.get("items") or result.get("stocks") or []
    mv = result.get("marketValue") or {}
    amt = mv.get("amount", mv) if isinstance(mv, dict) else {}
    if not isinstance(amt, dict):
        amt = {}
    equity_krw = _f(amt.get("krw"))
    equity_usd = _f(amt.get("usd"))

    # Optional cash fields if holdings payload ever includes them
    cash_krw = 0.0
    cash_usd = 0.0
    for key in ("cash", "availableCash", "withdrawableAmount", "cashBalance", "deposit"):
        if key not in result:
            continue
        v = result.get(key)
        if isinstance(v, dict):
            if "krw" in v or "usd" in v:
                cash_krw = _f(v.get("krw"), cash_krw)
                cash_usd = _f(v.get("usd"), cash_usd)
            else:
                cash_krw = _f(v.get("amount") or v.get("cash") or v.get("value"), cash_krw)
        else:
            cash_krw = _f(v, cash_krw)

    holdings: List[Dict[str, Any]] = []
    for it in items:
        sym = str(it.get("symbol") or it.get("code") or "").strip()
        if not sym:
            continue
        code = (sym.zfill(6) if sym.isdigit() else sym.upper())
        qty = _f(it.get("quantity", it.get("qty")))
        last = _f(it.get("lastPrice"))
        avg = _f(it.get("averagePurchasePrice", it.get("averagePrice")))
        mkt = it.get("marketValue") or {}
        if isinstance(mkt, dict):
            mkt_amt = _f(mkt.get("amount"))
        else:
            mkt_amt = _f(mkt)
        if mkt_amt <= 0 and qty and last:
            mkt_amt = qty * last
        row = {
            "code": code,
            "symbol_raw": sym,
            "name": it.get("name") or "",
            "qty": qty,
            "avg_price": avg,
            "last_price": last,
            "mkt_value": mkt_amt,
            "currency": it.get("currency") or "",
            "market_country": it.get("marketCountry") or "",
            "is_kr": False,
        }
        row["is_kr"] = _is_kr_item(
            {
                "marketCountry": row["market_country"],
                "currency": row["currency"],
                "symbol": row["symbol_raw"],
            }
        )
        holdings.append(row)

    kr = [h for h in holdings if h["is_kr"] and h["qty"] > 0]
    non_kr = [h for h in holdings if not h["is_kr"] and h["qty"] > 0]
    kr_eq = sum(h["mkt_value"] for h in kr)
    for h in kr:
        h["weight"] = (h["mkt_value"] / kr_eq) if kr_eq > 0 else 0.0
    us_eq = sum(h["mkt_value"] for h in non_kr)
    for h in non_kr:
        h["weight"] = (h["mkt_value"] / us_eq) if us_eq > 0 else 0.0

    return {
        "source": "toss",
        "purpose": "portfolio_confirm_readonly",
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "equity_krw": equity_krw,
        "equity_usd": equity_usd if equity_usd > 0 else us_eq,
        "cash_krw": cash_krw,
        "cash_usd": cash_usd,
        "cash_buying_power_krw": cash_krw,
        "cash_buying_power_usd": cash_usd,
        "holdings": holdings,
        "kr_holdings": kr,
        "non_kr_holdings": non_kr,
        "us_holdings": non_kr,
        "n_items": len(holdings),
        "n_kr": len(kr),
        "n_non_kr": len(non_kr),
        "n_us": len(non_kr),
        "kr_equity": kr_eq,
        "us_equity": us_eq,
        "ops_ready": False,
        "flat": len(non_kr) == 0,
    }


def _fetch_buying_power(token: str, account_seq: str, currency: str) -> float:
    """GET /api/v1/buying-power?currency=KRW|USD -> cashBuyingPower."""
    try:
        import requests

        resp = requests.get(
            f"{BASE_URL}/api/v1/buying-power",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Tossinvest-Account": str(account_seq),
            },
            params={"currency": currency},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return 0.0
        data = resp.json() or {}
        result = data.get("result") or {}
        return _f(result.get("cashBuyingPower"))
    except Exception:
        return 0.0


def fetch_portfolio() -> Dict[str, Any]:
    """Live pull: token -> accounts -> holdings (+ cash buying power). Read-only."""
    key, secret = _creds()
    token = _token(key, secret)
    accts = _get("/api/v1/accounts", token).get("result") or []
    if not isinstance(accts, list):
        raise TossPortfolioError("accounts payload invalid")
    acct = _pick_brokerage(accts)
    seq = str(acct.get("accountSeq") or "")
    if not seq:
        raise TossPortfolioError("accountSeq missing")
    raw = _get(
        "/api/v1/holdings",
        token,
        headers={"X-Tossinvest-Account": seq},
    )
    result = raw.get("result") or {}
    if not isinstance(result, dict):
        raise TossPortfolioError("holdings payload invalid")
    book = parse_holdings_payload(result)
    book["account_no_tail"] = str(acct.get("accountNo") or "")[-4:]
    book["account_seq"] = seq
    book["account_type"] = acct.get("accountType")
    book["_n_accounts"] = len(accts)
    book["status"] = "ok"

    cash_krw = _fetch_buying_power(token, seq, "KRW")
    cash_usd = _fetch_buying_power(token, seq, "USD")
    # Prefer buying-power values when present
    if cash_krw > 0 or float(book.get("cash_krw") or 0) == 0:
        book["cash_krw"] = cash_krw
    if cash_usd > 0 or float(book.get("cash_usd") or 0) == 0:
        book["cash_usd"] = cash_usd
    book["cash_buying_power_krw"] = cash_krw
    book["cash_buying_power_usd"] = cash_usd
    book["total_krw"] = float(book.get("equity_krw") or 0.0) + float(book.get("cash_krw") or 0.0)
    book["total_usd"] = float(book.get("equity_usd") or 0.0) + float(book.get("cash_usd") or 0.0)
    book["has_cash"] = float(book.get("cash_usd") or 0.0) > 0
    book["flat"] = int(book.get("n_us") or 0) == 0
    book["ops_ready"] = True
    return book



def us_weights(book: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """US weights on total USD NAV (equity + cash); do not renormalize cash away."""
    b = book if book is not None else fetch_portfolio()
    total = float(b.get("total_usd") or 0.0)
    if total <= 0:
        total = float(b.get("equity_usd") or 0.0) + float(b.get("cash_usd") or 0.0)
    if total <= 0:
        return {}
    out: Dict[str, float] = {}
    for h in b.get("us_holdings") or []:
        sym = str(h.get("symbol_raw") or h.get("code") or "").strip().upper()
        value = float(h.get("mkt_value") or 0.0)
        if sym and not sym.isdigit() and value > 0:
            out[sym] = out.get(sym, 0.0) + value / total
    return out





def toss_last_prices(book: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """US last prices from Toss holdings (broker SoT for live book / trade px)."""
    b = book if book is not None else fetch_portfolio()
    out: Dict[str, float] = {}
    for h in (b.get("us_holdings") or []):
        sym = str(h.get("symbol_raw") or h.get("code") or "").strip().upper()
        if not sym or sym.isdigit():
            continue
        px = _f(h.get("last_price"))
        if px > 0:
            out[sym] = px
    return out


def toss_qty_map(book: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """US share quantities from Toss holdings."""
    b = book if book is not None else fetch_portfolio()
    out: Dict[str, float] = {}
    for h in (b.get("us_holdings") or []):
        sym = str(h.get("symbol_raw") or h.get("code") or "").strip().upper()
        if not sym or sym.isdigit():
            continue
        q = _f(h.get("qty"))
        if q > 0:
            out[sym] = out.get(sym, 0.0) + q
    return out


def status(probe: bool = True) -> Dict[str, Any]:
    """Safe status map for `ops.py status` (no secrets)."""
    load_env()
    key_ok = bool(get_secret("TOSS_API_KEY", "").strip())
    secret_ok = bool(get_secret("TOSS_SECRET_KEY", "").strip())
    out: Dict[str, Any] = {
        "keys_present": key_ok and secret_ok,
        "base_url": BASE_URL,
        "purpose": "portfolio_confirm_readonly",
    }
    if not probe:
        out["probed"] = False
        return out
    if not (key_ok and secret_ok):
        out.update({"probed": True, "ok": False, "error": "missing_keys"})
        return out
    t0 = time.time()
    try:
        book = fetch_portfolio()
        cash_usd = float(book.get("cash_usd") or 0.0)
        n_us = int(book.get("n_us") or book.get("n_non_kr") or 0)
        if n_us > 0:
            msg = f"connected; {n_us} US names | cash_usd={cash_usd:.2f}"
        elif cash_usd > 0:
            msg = f"connected; US flat (cash-only) | cash_usd={cash_usd:.2f}"
        else:
            msg = f"connected; US flat | cash_usd={cash_usd:.2f}"
        out.update(
            {
                "probed": True,
                "ok": True,
                "token": "ok",
                "account_type": book.get("account_type"),
                "account_no_tail": book.get("account_no_tail"),
                "n_kr": book.get("n_kr"),
                "n_us": book.get("n_us"),
                "equity_usd": book.get("equity_usd"),
                "cash_usd": cash_usd,
                "cash_buying_power_usd": book.get("cash_buying_power_usd"),
                "total_usd": book.get("total_usd"),
                "ops_ready": book.get("ops_ready"),
                "flat": book.get("flat"),
                "latency_ms": int((time.time() - t0) * 1000),
                "message": msg,
            }
        )
    except Exception as e:
        out.update(
            {
                "probed": True,
                "ok": False,
                "token": "fail",
                "error": str(e),
                "latency_ms": int((time.time() - t0) * 1000),
            }
        )
    return out
