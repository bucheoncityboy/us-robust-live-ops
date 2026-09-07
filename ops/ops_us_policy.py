"""US Robust live-ops policy freeze (Robust_L60_M63_LV20).

Research-frozen production policy:
  Leader 60% / Mom63 20% / LowVol 20%
  equal-within-sleeve, name cap 15%, Top10 (LowVol ~12)
  NEXT_OPEN monthly rebalance
  No AccumulDiv / fundamental core / KR hybrid sleeves
  Empty sleeve weight -> cash; name-cap leftover -> residual cash
  Leader uses price score only (no AccumulDiv confirm/bear overlay)
  TOP_N_DEFAULT = 150 (ops.py monthly --top-n default must match)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

# ---------------------------------------------------------------------------
# Policy constants (live freeze) — do not import W_* from ops.us_hybrid_backtest
# ---------------------------------------------------------------------------
POLICY_NAME = "Robust_L60_M63_LV20"
W_LEADER = 0.60
W_MOM63 = 0.20
W_LOWVOL = 0.20
SLEEVE_WEIGHTS: Dict[str, float] = {
    "leader": W_LEADER,
    "mom63": W_MOM63,
    "lowvol": W_LOWVOL,
}
MAX_NAME = 0.15
MAX_SECTOR = 0.40  # best-effort only; not a migration hard gate
N_LEADER = 10
N_MOM63 = 10
N_LOWVOL = 12
TOP_N_DEFAULT = 150
COST = 0.0010  # 10bp round-trip US liquid large-cap
EXEC_RULE = "NEXT_OPEN"
WEIGHT_MODE = "equal_within_sleeve"
WEIGHT_EPS = 1e-6

# Expected names band for health WARN (not BLOCK)
N_NAMES_WARN_LO = 12
N_NAMES_WARN_HI = 32

# Factor-lab sleeve labels → ops keys
_FACTOR_TO_OPS = {
    "Leader": "leader",
    "Mom63": "mom63",
    "LowVol": "lowvol",
}
_OPS_TO_FACTOR = {v: k for k, v in _FACTOR_TO_OPS.items()}
_OPS_N = {
    "leader": N_LEADER,
    "mom63": N_MOM63,
    "lowvol": N_LOWVOL,
}


def normalize_symbol(x) -> str:
    """US ticker normalizer - never zfill; reject accidental zero-padded alpha tickers."""
    if x is None:
        return ""
    try:
        if isinstance(x, float) and pd.isna(x):
            return ""
    except Exception:
        pass
    s = str(x).replace(".0", "").strip().upper()
    if not s or s.lower() in {"nan", "none", "nat"}:
        return ""
    # Phase-1 hard gate: reject 0AAPL-style padding (never silent strip)
    if len(s) > 1 and s[0] == "0" and any(ch.isalpha() for ch in s):
        raise ValueError(f"invalid US ticker with leading-zero pad: {s}")
    return s


def is_positive_qty(qty) -> bool:
    """True when qty is a positive number (accepts float/fractional US qty)."""
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return False
    return q > 0


def is_integer_qty(qty) -> bool:
    """True when qty is a positive integer-valued number (KR whole-share rule)."""
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return False
    if q != q:  # NaN
        return False
    if q <= 0:
        return False
    return abs(q - round(q)) <= 1e-9


def select_us_picks(
    date,
    feats: Dict[str, pd.DataFrame],
    close: pd.DataFrame,
    volume: pd.DataFrame,
    regime,
    *,
    n_leader: Optional[int] = None,
    n_mom63: Optional[int] = None,
    n_lowvol: Optional[int] = None,
) -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, float]]]:
    """Select Robust_L60_M63_LV20 sleeves for one signal date.

    Returns
    -------
    picks : dict sleeve -> list of normalized US symbols
    scores : dict sleeve -> {symbol: score}
    """
    from ops.us_factor_research import select_factor

    reg = regime.loc[date] if hasattr(regime, "index") and date in regime.index else regime
    if not isinstance(reg, str):
        reg = str(reg) if reg is not None else "sideways"

    ns = {
        "leader": int(n_leader if n_leader is not None else N_LEADER),
        "mom63": int(n_mom63 if n_mom63 is not None else N_MOM63),
        "lowvol": int(n_lowvol if n_lowvol is not None else N_LOWVOL),
    }

    picks: Dict[str, List[str]] = {}
    scores: Dict[str, Dict[str, float]] = {}
    for ops_key in ("leader", "mom63", "lowvol"):
        factor_name = _OPS_TO_FACTOR[ops_key]
        codes, sm = select_factor(
            factor_name,
            date,
            feats,
            None,  # no fundamental core
            close,
            volume,
            reg,
            n=ns[ops_key],
        )
        picks[ops_key] = [normalize_symbol(c) for c in codes if normalize_symbol(c)]
        scores[ops_key] = {
            normalize_symbol(k): float(v)
            for k, v in (sm or {}).items()
            if normalize_symbol(k)
        }
    return picks, scores
