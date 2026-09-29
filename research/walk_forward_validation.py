"""Offline, expanding-window strategy selection. Never imports live order code.

Protocol fixed before execution: four existing robust candidates; train from
2019-08; select highest training daily excess-return IR (name breaks ties);
five six-month tests starting 2024-01. Refit only at each test boundary.
This is retrospective research, not a claim of historical preregistration.
"""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.us_factor_research import build_multi_picks, compute_all_features
from ops.us_hybrid_backtest import market_regime, merge_sleeve_weights, weights_equal
from research.us_robust_strategy import VARIANTS

COST = 0.001  # round trip: charge 5bp on each dollar bought or sold
OUT = ROOT / 'results' / 'walk_forward_validation'


def metrics(r):
    r = pd.Series(r).astype(float)
    wealth = (1 + r).cumprod()
    peak = wealth.cummax().clip(lower=1.0)
    vol = float(r.std(ddof=1) * np.sqrt(252))
    return dict(n_days=len(r), total_return=float(wealth.iloc[-1]-1),
                cagr=float(wealth.iloc[-1]**(252/len(r))-1),
                sharpe=float(r.mean()*252/vol) if vol > 0 else None,
                mdd=float((wealth/peak-1).min()))


def select_candidate(training, benchmark):
    """Accept only training rows; never receives test returns."""
    if training.empty or training.isna().any().any():
        raise ValueError('Missing training returns')
    excess = training.sub(benchmark.reindex(training.index), axis=0)
    if excess.isna().any().any():
        raise ValueError('Missing benchmark')
    scores = excess.mean()/excess.std(ddof=1).replace(0, np.nan)*np.sqrt(252)
    scores = scores.replace([np.inf, -np.inf], np.nan).dropna()
    if scores.empty:
        raise ValueError('No valid candidate')
    winner = sorted(scores.index, key=lambda n: (-scores[n], n))[0]
    return winner, {k: float(v) for k, v in scores.items()}


def simulate(close, opens, targets, start, end):
    """Cash-start segment; open valuation, drifted turnover, explicit exit fee.

    Full cash liquidation at segment end prevents free switches across folds.
    Missing held-asset prices fail rather than silently erasing holdings.
    """
    days = close.loc[start:end].index
    shares = pd.Series(0.0, index=close.columns)
    cash, previous = 1.0, 1.0
    rows = []
    for day in days:
        held = shares[shares != 0]
        fee = 0.0
        if day in targets:
            op = opens.loc[day]
            if (op.reindex(held.index).isna() | (op.reindex(held.index) <= 0)).any():
                raise ValueError(f'Missing held open: {day}')
            assets = shares * op.fillna(0)
            nav = float(cash + assets.sum())
            target = pd.Series(targets[day], dtype=float).reindex(shares.index).fillna(0)
            if (target < 0).any() or target.sum() > 1.00000001:
                raise ValueError('Invalid target')
            wanted = target > 0
            if (op[wanted].isna() | (op[wanted] <= 0)).any():
                raise ValueError(f'Missing target open: {day}')
            # Solve post-fee NAV because transaction amounts depend on it.
            post = nav
            for _ in range(30):
                fee = float((target*post-assets).abs().sum()*COST/2)
                post = nav-fee
            shares = (target*post/op).where(wanted, 0.0)
            cash = float(post*(1-target.sum()))
        held = shares[shares != 0]
        px = close.loc[day].reindex(held.index)
        if (px.isna() | (px <= 0)).any():
            raise ValueError(f'Missing held close: {day}')
        value = float((held*px).sum())
        nav = cash+value
        if day == days[-1]:
            exit_fee = value*COST/2
            fee += exit_fee
            nav -= exit_fee
        rows.append(dict(date=day, return_=nav/previous-1, equity=nav, fee=fee))
        previous = nav
    return pd.DataFrame(rows).set_index('date')


def make_targets(close, opens, volume, spy, specs, through):
    # Truncate raw inputs before feature generation and selection.
    c, o, v, s = [x.loc[:through] for x in (close, opens, volume, spy)]
    feats = compute_all_features(c, v, s)
    regime = market_regime(s)
    signals = c.groupby(c.index.to_period('M')).tail(1).index
    signals = signals[signals >= pd.Timestamp('2019-07-01')]
    result = {}
    for spec in specs:
        picks, _ = build_multi_picks(signals, feats, pd.DataFrame(), c, v, regime, spec['sleeves'])
        targets = {}
        for day, sleeves in picks.items():
            pos = c.index.searchsorted(day, side='right')
            if pos >= len(c.index):
                continue
            name_weights = {k: weights_equal(names) for k, names in sleeves.items()}
            targets[c.index[pos]] = merge_sleeve_weights(spec['weights'], name_weights, max_name=0.15)
        result[spec['name']] = targets
    return result


def main():
    data = ROOT/'data'/'us'
    names = ['us_prices_panel', 'us_open_panel', 'us_volume_panel', 'spy']
    frames = [pd.read_parquet(data/(n+'.parquet')) for n in names]
    close, opens, volume, spy_frame = frames
    for frame in frames:
        frame.index = pd.to_datetime(frame.index)
        if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
            raise ValueError('Invalid dates')
    spy = spy_frame['Close'].reindex(close.index)
    benchmark = spy.pct_change(fill_method=None)
    specs = [x for x in VARIANTS if x['family'] == 'robust']
    folds, returns = [], []
    for i in range(5):
        start = pd.Timestamp('2024-01-01') + pd.DateOffset(months=6*i)
        end = start + pd.DateOffset(months=6)-pd.Timedelta(days=1)
        train_end = close.index[close.index < start][-1]
        if close.index[-1] < end-pd.Timedelta(days=3):
            raise ValueError('Incomplete test interval')
        train_targets = make_targets(close, opens, volume, spy, specs, train_end)
        train = pd.DataFrame({n: simulate(close, opens, t, '2019-08-01', train_end)['return_']
                              for n, t in train_targets.items()})
        winner, scores = select_candidate(train, benchmark)
        spec = next(x for x in specs if x['name'] == winner)
        test_targets = make_targets(close, opens, volume, spy, [spec], end)[winner]
        test = simulate(close, opens, test_targets, start, end)
        test['benchmark'] = benchmark.reindex(test.index)
        test['fold'] = i+1
        test['selected'] = winner
        if test['benchmark'].isna().any():
            raise ValueError('Missing test benchmark')
        folds.append(dict(fold=i+1, train_start=str(train.index[0].date()),
                          train_end=str(train_end.date()), test_start=str(test.index[0].date()),
                          test_end=str(test.index[-1].date()), selected=winner, training_scores=scores,
                          strategy=metrics(test['return_']), benchmark=metrics(test['benchmark'])))
        returns.append(test)
        print(f'Fold {i+1}: {winner}; test return {folds[-1]["strategy"]["total_return"]:.2%}', flush=True)
    combined = pd.concat(returns)
    if combined.index.has_duplicates:
        raise ValueError('Overlapping tests')
    report = dict(protocol=dict(train='expanding from 2019-08-01', test='five consecutive six-month windows from 2024-01',
                                selection='training daily excess-return IR; ties by name', round_trip_cost_bps=10,
                                execution='next open; liquidate at each fold end', candidates=[x['name'] for x in specs]),
                  limitations=['Retrospective protocol; candidate definitions were developed with historical data knowledge.',
                               'Cached current-constituent universe retains survivorship bias.',
                               'Not prospective live performance; original published figures are not replaced.'],
                  folds=folds, stitched_strategy=metrics(combined['return_']),
                  stitched_benchmark=metrics(combined['benchmark']),
                  input_sha256={n: hashlib.sha256((data/(n+'.parquet')).read_bytes()).hexdigest() for n in names})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'metrics.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    combined.to_csv(OUT/'oos_returns.csv')
    print(json.dumps(report['stitched_strategy'], indent=2))


if __name__ == '__main__':
    main()
