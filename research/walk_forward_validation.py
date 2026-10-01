"""Offline IS/OOS validation. Never imports live order code.

Default: frozen production 60/20/20 strategy, five sequential OOS folds,
regime diagnostics and monthly excess-return inference. Optional candidate
mode preserves the earlier training-only selection experiment. Both are
retrospective research, not a claim of historical preregistration.
"""
from pathlib import Path
import hashlib
import json
import sys
import argparse

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ops.us_factor_research import build_multi_picks, compute_all_features
from ops.us_hybrid_backtest import market_regime, merge_sleeve_weights, weights_equal
from research.us_robust_strategy import VARIANTS
from ops.ops_us_policy import POLICY_NAME, SLEEVE_WEIGHTS, MAX_NAME, select_us_picks

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
    if days.empty:
        raise ValueError('Empty simulation interval')
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
            raw_target = pd.Series(targets[day], dtype=float)
            if not np.isfinite(raw_target).all() or set(raw_target.index)-set(shares.index):
                raise ValueError('Nonfinite or unknown target asset')
            target = raw_target.reindex(shares.index).fillna(0)
            if not np.isfinite(target).all() or (target < 0).any() or target.sum() > 1.00000001:
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


def candidate_main(data=None, output=None):
    data = data if data is not None else ROOT/'data'/'us'
    output = output if output is not None else OUT
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
    output.mkdir(parents=True, exist_ok=True)
    (output/'metrics.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    combined.to_csv(output/'oos_returns.csv')
    print(json.dumps(report['stitched_strategy'], indent=2))


def month_end_signals(index):
    """Exclude an incomplete last month; observed NYSE final sessions only."""
    index = pd.DatetimeIndex(index)
    last = index[-1]
    ends = pd.Series(index, index=index).groupby(index.to_period('M')).last()
    return pd.DatetimeIndex([d for d in ends if d.to_period('M') < last.to_period('M')])


def fixed_targets(close, volume, spy, through, top_n=150):
    """Frozen production selectors; trailing liquidity screen at each signal.

    Truncation makes any changes beyond through irrelevant to these targets.
    Rank only available cached names: historical S&P membership is unavailable.
    """
    c, v, s = [x.loc[:through] for x in (close, volume, spy)]
    feats = compute_all_features(c, v, s)
    regime = market_regime(s)
    signals = month_end_signals(c.index)
    targets, audit = {}, []
    for day in signals[signals >= pd.Timestamp('2019-07-01')]:
        amount = (c.loc[:day].tail(20)*v.loc[:day].tail(20)).mean()
        eligible = (c.loc[day].notna() & (c.loc[day] > 0)
                    & (c.loc[:day].tail(252).notna().sum() >= 252)
                    & amount.notna() & (amount > 0))
        names = amount[eligible].sort_values(ascending=False, kind='stable').head(top_n).index
        # Mask selectors rather than recompute cross-sectional ranks after filtering.
        masked = {}
        for key, frame in feats.items():
            masked[key] = frame.loc[[day]].astype(float).copy()
            masked[key].loc[day, ~masked[key].columns.isin(names)] = np.nan
        picks, _ = select_us_picks(day, masked, c, v, regime)
        name_weights = {k: weights_equal(codes) for k, codes in picks.items()}
        sleeve_weights = dict(SLEEVE_WEIGHTS)
        sleeve_weights['cash'] = sum(w for k, w in SLEEVE_WEIGHTS.items() if not picks[k])
        for k in SLEEVE_WEIGHTS:
            if not picks[k]:
                sleeve_weights[k] = 0.0
        target = merge_sleeve_weights(sleeve_weights, name_weights, max_name=MAX_NAME)
        if set(target)-set(names) or max(target.values(), default=0) > MAX_NAME+1e-9:
            raise ValueError('Universe/name cap violation')
        pos = c.index.searchsorted(day, side='right')
        if pos >= len(c.index):
            continue
        execution = c.index[pos]
        targets[execution] = target
        audit.append(dict(signal_date=str(day.date()), execution_date=str(execution.date()),
                          eligible_cached_names=len(names), picks=picks, weights=target,
                          cash_weight=1-sum(target.values())))
    return targets, audit


def monthly_table(daily):
    periods = daily.index.to_period('M')
    table = daily[['return_', 'benchmark']].groupby(periods).agg(lambda r: (1+r).prod()-1)
    table.columns = ['strategy', 'benchmark']
    table['excess'] = table.strategy-table.benchmark
    return table


def edge_statistics(excess, iid_n=10000, block_n=10000, seed=7):
    """Paired monthly excess t-test and seeded circular four-month bootstrap.

    Bootstrap estimates distribution of mean excess, not an uncentered p-value.
    """
    x = np.asarray(excess, dtype=float)
    if len(x) < 4 or not np.isfinite(x).all() or x.std(ddof=1) == 0:
        raise ValueError('Need >=4 finite, nonconstant monthly excess returns')
    test = scipy_stats.ttest_1samp(x, popmean=0.0)
    rng = np.random.default_rng(seed)
    iid = x[rng.integers(0, len(x), size=(iid_n, len(x)))].mean(axis=1)
    starts = rng.integers(0, len(x), size=(block_n, int(np.ceil(len(x)/4))))
    indices = (starts[:, :, None]+np.arange(4)) % len(x)
    block = x[indices.reshape(block_n, -1)[:, :len(x)]].mean(axis=1)
    def describe(draws):
        return dict(repetitions=len(draws), mean_monthly_excess=float(draws.mean()),
                    ci95_monthly_excess=[float(v) for v in np.quantile(draws, [.025, .975])],
                    fraction_mean_above_zero=float((draws > 0).mean()))
    return dict(n_months=len(x), mean_monthly_excess=float(x.mean()),
                t_stat=float(test.statistic), p_value_two_sided=float(test.pvalue),
                significant_at_5pct=bool(test.pvalue < .05), seed=seed,
                iid=describe(iid), block4=dict(block_months=4, method='circular moving blocks', **describe(block)))


def regime_labels(spy):
    """Known at preceding close: SMA200 trend and trailing RV21 median."""
    trend = spy > spy.rolling(200, min_periods=200).mean()
    rv = spy.pct_change(fill_method=None).rolling(21).std(ddof=1)*np.sqrt(252)
    median = rv.rolling(252, min_periods=252).median()
    labels = pd.Series(np.where(trend, 'up', 'down'), index=spy.index) + '_' + pd.Series(
        np.where(rv > median, 'high_vol', 'low_vol'), index=spy.index)
    return labels.where(median.notna()).shift(1)


def fixed_main(data_dir, output_dir):
    names = ['us_prices_panel', 'us_open_panel', 'us_volume_panel', 'spy']
    frames = [pd.read_parquet(data_dir/(n+'.parquet')) for n in names]
    for frame in frames:
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        if not frame.index.is_monotonic_increasing or frame.index.has_duplicates or frame.columns.has_duplicates:
            raise ValueError('Invalid panel axes')
    close, opens, volume, spy_frame = frames
    if any(not close.index.equals(f.index) for f in frames[1:]):
        raise ValueError('Panels must have identical observation dates')
    if not close.columns.equals(opens.columns) or not close.columns.equals(volume.columns):
        raise ValueError('Asset columns must align')
    spy = spy_frame['Close']
    benchmark = spy.pct_change(fill_method=None)
    labels = regime_labels(spy)
    folds, parts, audits = [], [], []
    for i in range(5):
        start = pd.Timestamp('2024-01-01') + pd.DateOffset(months=6*i)
        end = start+pd.DateOffset(months=6)-pd.Timedelta(days=1)
        if close.index[-1] < end-pd.Timedelta(days=3):
            raise ValueError('Incomplete OOS fold')
        train_end = close.index[close.index < start][-1]
        train_targets, _ = fixed_targets(close, volume, spy, train_end)
        train = simulate(close, opens, train_targets, '2019-08-01', train_end)
        test_targets, audit = fixed_targets(close, volume, spy, end)
        test = simulate(close, opens, test_targets, start, end)
        test['benchmark'] = benchmark.reindex(test.index)
        test['regime'] = labels.reindex(test.index)
        test['fold'] = i+1
        if test[['benchmark', 'regime']].isna().any().any():
            raise ValueError('Missing OOS benchmark/regime')
        folds.append(dict(fold=i+1, train_start=str(train.index[0].date()),
                          train_end=str(train_end.date()), test_start=str(test.index[0].date()),
                          test_end=str(test.index[-1].date()), policy=POLICY_NAME,
                          is_strategy=metrics(train.return_), oos_strategy=metrics(test.return_),
                          oos_benchmark=metrics(test.benchmark)))
        audits.extend(dict(fold=i+1, **row) for row in audit if start <= pd.Timestamp(row['execution_date']) <= end)
        parts.append(test)
        print(f'Fold {i+1}: fixed 60/20/20 OOS return {folds[-1]["oos_strategy"]["total_return"]:.2%}', flush=True)
    daily = pd.concat(parts)
    if daily.index.has_duplicates:
        raise ValueError('Overlapping OOS folds')
    monthly = monthly_table(daily)
    statistics = edge_statistics(monthly.excess)
    regimes = []
    for label, group in daily.groupby('regime'):
        excess = group.return_-group.benchmark
        regimes.append(dict(regime=label, n_days=len(group),
                            mean_daily_strategy=float(group.return_.mean()),
                            mean_daily_benchmark=float(group.benchmark.mean()),
                            mean_daily_excess=float(excess.mean()),
                            contribution_to_oos_daily_excess_sum=float(excess.sum())))
    report = dict(protocol=dict(policy=POLICY_NAME, sleeve_weights=SLEEVE_WEIGHTS,
        train='expanding IS from 2019-08-01; diagnostic only; no parameter fitting',
        test='five consecutive six-month OOS windows from 2024-01-01 through 2026-06-30',
        tuning='none; 60/20/20 weights and selectors fixed for every fold',
        execution='month-end close signal; next observed trading-day open; cash start and close liquidation per fold',
        round_trip_cost_bps=10, one_way_cost_bps=5, name_cap=MAX_NAME,
        universe='trailing 20-session mean dollar volume top 150 among cached names with 252 valid sessions',
        cached_names=len(close.columns), regime='previous-close SMA200 trend x RV21 above/below trailing 252-day median',
        inference='paired monthly strategy minus SPY returns on stitched OOS only; two-sided t-test',
        sector='no historical sector mapping/cap in this validation; production sector handling is best effort'),
        limitations=['Retrospective validation; frozen strategy was designed with historical data knowledge.',
        f'Current-constituent cache retains survivorship/preselection bias; only {len(close.columns)} cached names, not historical full S&P500 membership.',
        'Fixed-policy temporal validation; IS is diagnostic and is not a model-refitting walk-forward.',
        'Monthly t-test assumes independent observations; block bootstrap only checks short dependence and sampling sensitivity.',
        'SPY close-to-close returns are a passive gross benchmark; strategy pays entry/rebalance/exit costs.',
        'No spread/slippage/impact model beyond 10bp round-trip cost; not live performance.'],
        folds=folds, stitched_strategy=metrics(daily.return_), stitched_benchmark=metrics(daily.benchmark),
        statistics=statistics, regimes=regimes,
        input_sha256={n: hashlib.sha256((data_dir/(n+'.parquet')).read_bytes()).hexdigest() for n in names})
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/'metrics.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    daily.to_csv(output_dir/'oos_returns.csv', index_label='date')
    monthly.to_csv(output_dir/'monthly_returns.csv', index_label='month')
    pd.DataFrame(regimes).to_csv(output_dir/'regime_table.csv', index=False)
    (output_dir/'target_audit.json').write_text(json.dumps(audits, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# 고정 60/20/20 전략의 IS/OOS 검증', '',
        '월말 종가 신호와 익영업일 시가 체결을 적용하고 왕복 10bp 비용을 반영했습니다. '
        'IS를 확장하며 시간순 5개 OOS Fold를 평가한 뒤 같은 OOS 수익률로 국면별 분석과 t검정 및 Bootstrap을 수행했습니다.', '',
        '고정 전략이므로 IS에서 파라미터를 재학습하거나 후보를 다시 선택하지 않습니다. '
        '이번 실행은 사후 재검증이며 과거에 이 절차를 사전 등록했다는 의미가 아닙니다.', '',
        '| Fold | IS 종료 | OOS 시작 | OOS 종료 | 전략 수익률 | SPY 수익률 |',
        '|---|---|---|---|---:|---:|']
    for f in folds:
        lines.append(f'| {f["fold"]} | {f["train_end"]} | {f["test_start"]} | {f["test_end"]} | {f["oos_strategy"]["total_return"]:.2%} | {f["oos_benchmark"]["total_return"]:.2%} |')
    lines.extend(['', f'연결 OOS CAGR {report["stitched_strategy"]["cagr"]:.2%}, Sharpe {report["stitched_strategy"]["sharpe"]:.2f}, MDD {report["stitched_strategy"]["mdd"]:.2%}.', '',
        f'월별 초과수익 t={statistics["t_stat"]:.4f}, 양측 p={statistics["p_value_two_sided"]:.6f}; 5% 유의수준 판정: {statistics["significant_at_5pct"]}.', '',
        '| 재표집 | 반복 수 | 월평균 초과수익 95% 구간 | 평균이 양수인 비율 |', '|---|---:|---|---:|'])
    for key in ['iid', 'block4']:
        b = statistics[key]
        lines.append(f'| {key} | {b["repetitions"]} | {b["ci95_monthly_excess"][0]:.2%} ~ {b["ci95_monthly_excess"][1]:.2%} | {b["fraction_mean_above_zero"]:.2%} |')
    lines.extend(['', 'Bootstrap의 양수 비율은 p-value가 아닙니다. 국면별 결과는 regime_table.csv를 참고하세요. '
        '국면은 전일 종가까지의 정보로 분류하며 기여도는 일별 초과수익의 합으로 복리 성과 기여도가 아닙니다.', '',
        '## 재현', '', '```bash', 'python research/walk_forward_validation.py --mode fixed --data-dir data/us',
        'npx --yes tsx src/harness.ts', '```', '', '## 한계', '']+[f'- {x}' for x in report['limitations']])
    (output_dir/'README.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(strategy=report['stitched_strategy'], statistics=statistics), indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Offline strategy validation; no broker or data refresh')
    parser.add_argument('--mode', choices=['fixed', 'candidate'], default='fixed')
    parser.add_argument('--data-dir', type=Path, default=ROOT/'data'/'us')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    if args.mode == 'candidate':
        candidate_main(args.data_dir, args.output_dir)
    else:
        fixed_main(args.data_dir, args.output_dir or ROOT/'results'/'fixed_strategy_validation')
