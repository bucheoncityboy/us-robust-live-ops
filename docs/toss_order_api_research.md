# Toss Order API Research Lock

**Status:** PARTIAL — LIVE path **BLOCKED** until checklist complete  
**Date:** 2026-07-18  
**Base URL:** `https://openapi.tossinvest.com`

## Known (from public OpenAPI + existing client)

| Item | Value |
|------|--------|
| OAuth | `POST /oauth2/token` client_credentials (same as `toss_portfolio.py`) |
| Account header | `X-Tossinvest-Account: {accountSeq}` |
| Create order | `POST /api/v1/orders` |
| Cancel | `POST /api/v1/orders/{orderId}/cancel` |
| Modify | `POST /api/v1/orders/{orderId}/modify` (if available) |
| Holdings (read) | `GET /api/v1/holdings` |
| Buying power | `GET /api/v1/buying-power?currency=KRW\|USD` |
| Accounts | `GET /api/v1/accounts` |

### KR quantity rules (critical)

- KR qty must be **positive integers** (Toss rejects fractional KR).
- Fractional qty only for **US MARKET SELL** (out of scope for execute v1 KR path).
- US fractional **BUY** must use **orderAmount** (USD), not quantity. Toss rejects fractional BUY quantity.
- `clientOrderId` optional idempotency ≤36 chars, ~10-minute window.
- High notional ≥1e8 KRW may need `confirmHighValueOrder=true`.
- `timeInForce` default `DAY`; OPG (at-open) currently unsupported in notes → use MARKET+DAY.

### Order create body (planning sketch — verify before LIVE)

```json
{
  "symbol": "005930",
  "side": "BUY",
  "orderType": "MARKET",
  "quantity": 1,
  "timeInForce": "DAY",
  "clientOrderId": "exYYYYMMDDHHMMSS-005930-B-1"
}
```

Field names may differ slightly in official docs; implementer must align with current Toss OpenAPI schema before enabling LIVE.

## Open checklist (must lock before LIVE_ORDERS_ENABLED=true)

1. [ ] Exact **GET/list order** path to poll by `orderId` (response model exists; path not locked)
2. [ ] KR-compatible `orderType` + `timeInForce` confirmed in live sandbox/docs
3. [ ] Terminal **status enum** values for full fill / partial / rejected / canceled
4. [ ] `filledQuantity` JSON path and whether partial fills occur on KR MARKET
5. [ ] Poll behavior: recommended interval (plan default 1.0s), wall timeout (plan default 120s)
6. [ ] ORDER-group rate-limit / 429 semantics
7. [ ] Symbol format for KRX (expect 6-digit; matches repo `zfill(6)`)

## LIVE gate rule

If any of items 1–4 remain open:

- `LIVE_ORDERS_ENABLED = False` in `toss_orders.py`
- `python ops.py execute` must exit non-zero with clear **BLOCK** message
- **Zero** `POST /api/v1/orders` calls

## Plan defaults (implement even while path TBD)

| Constant | Default |
|----------|---------|
| POLL_INTERVAL_SEC | 1.0 |
| POLL_WALL_TIMEOUT_SEC | 120 |
| MAX_429_RETRIES | 3 |
| Backoff | 1, 2, 4 (cap 8) seconds |
| QTY_FILL_EPS | 0 (exact full fill) |
| AUTO_CANCEL | false |

## Safety

- Never log API keys/tokens.
- No production POSTs during implementation verification unless separate human live approval.

## US fractional checklist (Phase2 — LIVE still BLOCKED)

| Item | Status | Notes |
|------|--------|-------|
| US symbol (no zfill) | DONE in code | normalize_symbol + build_order_payload(market=US) |
| Fractional qty float | DONE in code | US path allows float qty; KR keeps integer |
| dry_run_orders no HTTP POST | DONE | toss_orders.dry_run_orders |
| execute_dry_run.json on LIVE_BLOCK | DONE | written by ops_execute |
| USD cash / buying-power on status | DONE | cash_usd / cash_buying_power_usd |
| us_weights / us_holdings ops_ready | DONE | US book primary |
| Confirm live schema for US MARKET fractional | DONE | SELL=quantity; fractional BUY=orderAmount (live 400 confirmed) |
| Pre-LIVE human approval | DONE | 2026-07-20 user explicitly approved LIVE unlock + execute |

**Note (2026-07-20):** `LIVE_ORDERS_ENABLED=True` after human approval. US fractional MARKET only in regular hours.
**Note (2026-07-20 evening):** Live 400 confirmed — fractional BUY quantity rejected; execute path now sends `orderAmount` for US fractional BUY (SELL still uses quantity).
