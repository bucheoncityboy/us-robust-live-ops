"""Synthetic accounting and temporal isolation tests; no network or broker."""
import unittest
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd

from research.walk_forward_validation import (
    make_targets, select_candidate, simulate, fixed_targets, monthly_table,
    edge_statistics, regime_labels,
    fixed_main, candidate_main, validate_panels,
)
from scipy import stats


class WalkForwardTests(unittest.TestCase):
    def test_fixed_targets_are_causal_and_use_next_session(self):
        dates = pd.bdate_range('2018-01-01', periods=700)
        rng = np.random.default_rng(51)
        close = pd.DataFrame(100*np.exp(np.cumsum(rng.normal(.001,.01,(700,30)),axis=0)),
                             index=dates, columns=[f'A{i}' for i in range(30)])
        volume = close*0+1e7
        cutoff = dates[550]
        before, audit = fixed_targets(close, volume, close.mean(axis=1), cutoff, top_n=20)
        changed = close.copy()
        changed.loc[changed.index > cutoff] *= 50
        after, _ = fixed_targets(changed, volume, changed.mean(axis=1), cutoff, top_n=20)
        self.assertEqual(before, after)
        self.assertTrue(audit)
        for row in audit:
            signal = pd.Timestamp(row['signal_date'])
            execution = pd.Timestamp(row['execution_date'])
            self.assertEqual(execution, dates[dates > signal][0])
            self.assertLessEqual(row['eligible_cached_names'], 20)
            self.assertLessEqual(max(row['weights'].values(), default=0), .15+1e-9)
            self.assertAlmostEqual(sum(row['weights'].values())+row['cash_weight'], 1.)
            for codes in row['picks'].values():
                self.assertTrue(set(codes).issubset(close.columns[:20]))
        all_before, _ = fixed_targets(close, volume, close.mean(axis=1), dates[-1], top_n=20)
        all_after, _ = fixed_targets(changed, volume, changed.mean(axis=1), dates[-1], top_n=20)
        self.assertEqual({d: w for d, w in all_before.items() if d <= cutoff},
                         {d: w for d, w in all_after.items() if d <= cutoff})

    def test_invalid_target_is_rejected_instead_of_erased(self):
        dates = pd.bdate_range('2024-01-02', periods=2)
        prices = pd.DataFrame({'A': [100., 100.]}, index=dates)
        for target in [{'B': 1.}, {'A': np.nan}]:
            with self.assertRaises(ValueError):
                simulate(prices, prices, {dates[0]: target}, dates[0], dates[-1])

    def test_monthly_inference_matches_paired_test_and_is_reproducible(self):
        x = np.array([.04, -.03, .01, -.02, .06, -.05, .02, .01])
        out = edge_statistics(x, iid_n=500, block_n=500)
        expected = stats.ttest_1samp(x, 0.)
        self.assertAlmostEqual(out['t_stat'], expected.statistic)
        self.assertAlmostEqual(out['p_value_two_sided'], expected.pvalue)
        self.assertFalse(out['significant_at_5pct'])
        self.assertEqual(out, edge_statistics(x, iid_n=500, block_n=500))
        dates = pd.to_datetime(['2024-01-30', '2024-01-31', '2024-02-01'])
        daily = pd.DataFrame({'return_':[.1,-.1,.02], 'benchmark':[.02,.03,.01]}, index=dates)
        table = monthly_table(daily)
        self.assertAlmostEqual(table.iloc[0].strategy, -.01)
        self.assertAlmostEqual(table.iloc[0].benchmark, 1.02*1.03-1)
        self.assertAlmostEqual(table.iloc[0].excess, -.01-(1.02*1.03-1))

    def test_regime_is_known_before_current_session(self):
        dates = pd.bdate_range('2018-01-01', periods=500)
        spy = pd.Series(100*np.exp(np.cumsum(np.random.default_rng(8).normal(.0001,.01,500))), index=dates)
        before = regime_labels(spy)
        spy.iloc[400:] *= 100
        after = regime_labels(spy)
        pd.testing.assert_series_equal(before.iloc[:401], after.iloc[:401])

    def test_open_rebalance_does_not_spend_same_day_close(self):
        dates = pd.bdate_range('2024-01-02', periods=3)
        close = pd.DataFrame({'A': [100., 200., 200.]}, index=dates)
        opens = pd.DataFrame({'A': [100., 100., 200.]}, index=dates)
        target = {dates[0]: {'A': 1.}, dates[1]: {'A': 1.}}
        out = simulate(close, opens, target, dates[0], dates[-1])
        # Doubling occurs once, not once in the budget and again in the holding.
        self.assertAlmostEqual(out.iloc[1].equity / out.iloc[0].equity, 2.)
        self.assertAlmostEqual(out.iloc[1].fee, 0.)

    def test_cash_roundtrip_charges_both_legs(self):
        dates = pd.bdate_range('2024-01-02', periods=2)
        prices = pd.DataFrame({'A': [100., 100.]}, index=dates)
        out = simulate(prices, prices, {dates[0]: {'A': 1.}}, dates[0], dates[-1])
        self.assertAlmostEqual(out.iloc[-1].equity, (1-.0005)/(1+.0005))
        self.assertAlmostEqual((1+out.return_).prod(), out.iloc[-1].equity)

    def test_missing_held_price_fails(self):
        dates = pd.bdate_range('2024-01-02', periods=2)
        opens = pd.DataFrame({'A': [100., 100.]}, index=dates)
        close = opens.copy()
        close.iloc[-1, 0] = np.nan
        with self.assertRaises(ValueError):
            simulate(close, opens, {dates[0]: {'A': 1.}}, dates[0], dates[-1])

    def test_future_prices_cannot_change_training_targets_or_choice(self):
        dates = pd.bdate_range('2020-01-01', periods=700)
        rng = np.random.default_rng(15)
        close = pd.DataFrame(100*np.exp(np.cumsum(rng.normal(.0005,.01,(700,3)),axis=0)),
                             index=dates, columns=['A','B','C'])
        volume = close*0+1e7
        spy = close.mean(axis=1)
        cutoff = dates[550]
        spec = [dict(name='momentum', sleeves=['Mom63'], weights={'Mom63':1.})]
        before = make_targets(close, close, volume, spy, spec, cutoff)
        changed = close.copy()
        changed.loc[changed.index > cutoff] *= 50
        after = make_targets(changed, changed, volume, changed.mean(axis=1), spec, cutoff)
        self.assertEqual(before, after)
        r = pd.DataFrame({'a':[.01,.02,-.01,.03], 'b':[.02,-.04,.01,.001]},
                         index=dates[:4])
        b = pd.Series(0., index=r.index)
        selected, _ = select_candidate(r, b)
        extended = pd.concat([r, pd.DataFrame({'a':[-.9], 'b':[10.]},index=[dates[4]])])
        self.assertEqual(selected, select_candidate(extended.loc[:dates[3]], b)[0])

    def test_live_and_fixed_policy_match_young_gapped_and_snapshot_order(self):
        from ops.ops_live_safety import nyse_calendar
        from ops.ops_monthly_run import build_target
        from ops.us_factor_research import compute_all_features
        from ops.us_hybrid_backtest import market_regime
        dates = nyse_calendar('2022-11-01', '2024-03-04').sessions_in_range('2022-11-01', '2024-03-04')
        rng = np.random.default_rng(72)
        close = pd.DataFrame(100*np.exp(np.cumsum(rng.normal(.001, .015, (len(dates), 14)), axis=0)),
                             index=dates, columns=[f'A{i}' for i in range(14)])
        signal = pd.Timestamp('2024-02-29')
        young_dates = dates[dates <= signal][-220:]
        close['YOUNG'] = np.nan
        close.loc[young_dates, 'YOUNG'] = np.linspace(100, 300, 220)
        close.loc[dates > signal, 'YOUNG'] = 301.
        close['GAPPED'] = 100*np.exp(np.arange(len(dates))*.0002)
        close.loc[dates[dates <= signal][-10], 'GAPPED'] = np.nan
        close['OUTSIDE'] = np.linspace(10, 10000, len(dates))
        volume = close*0 + 1e7
        spy = close[[f'A{i}' for i in range(14)]].mean(axis=1)
        meta = pd.DataFrame({'Code': ['GAPPED', 'YOUNG'] + [f'A{i}' for i in range(14)]})
        feats, regime = compute_all_features(close, volume, spy), market_regime(spy)
        picks, target, _, _ = build_target(signal, feats, {}, pd.DataFrame(), regime,
                                          close, volume, universe=meta)
        _, audit = fixed_targets(close, volume, spy, dates[-1], universe=meta)
        row = next(r for r in audit if r['signal_date'] == '2024-02-29')
        self.assertEqual(picks, row['picks'])
        self.assertEqual(target, row['weights'])
        self.assertIn('YOUNG', picks['mom63'])
        self.assertIn('GAPPED', picks['lowvol'])
        self.assertNotIn('OUTSIDE', target)
        changed = close.copy()
        changed.loc[changed.index > signal] *= 100
        altered, _ = fixed_targets(changed, volume, spy, dates[-1], universe=meta)
        original, _ = fixed_targets(close, volume, spy, dates[-1], universe=meta)
        self.assertEqual(original[dates[dates > signal][0]], altered[dates[dates > signal][0]])

    def test_all_legacy_accounting_entrypoints_are_disabled(self):
        from ops.us_factor_research import run_portfolio
        from ops.us_hybrid_backtest import run_strict
        from research.strict_asif_test import simulate as legacy_simulate
        for call in (lambda: run_portfolio(None, None, {}, {}, {}),
                     lambda: run_strict(None, None, {}, {}, {}, None),
                     lambda: legacy_simulate({}, None, None, .001)):
            with self.assertRaisesRegex(RuntimeError, 'Legacy accounting disabled'):
                call()

    def test_drift_rebalance_and_entry_cost_are_in_return_series(self):
        dates = pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04'])
        close = pd.DataFrame({'A': [100., 200., 200.], 'B': [100., 100., 100.]}, index=dates)
        target = {dates[0]: {'A': .5, 'B': .5}, dates[2]: {'A': .5, 'B': .5}}
        out = simulate(close, close, target, dates[0], dates[-1])
        self.assertLess(out.iloc[0].return_, 0.)
        self.assertGreater(out.iloc[2].fee, out.iloc[2].equity*.0005)  # drift fee plus liquidation
        self.assertAlmostEqual((1+out.return_).prod(), out.iloc[-1].equity)

    def test_complete_fold_calendar_rejects_missing_final_and_internal_sessions(self):
        from ops.ops_live_safety import nyse_calendar
        dates = nyse_calendar('2019-08-01', '2026-06-30').sessions_in_range('2019-08-01', '2026-06-30')
        prices = pd.DataFrame({'A': 100.}, index=dates)
        benchmark = prices.rename(columns={'A': 'Close'})
        validate_panels([prices, prices, prices, benchmark])
        for missing in [pd.Timestamp('2026-06-30'), pd.Timestamp('2025-03-12')]:
            with self.assertRaisesRegex(ValueError, 'NYSE sessions'):
                validate_panels([f.drop(missing) for f in [prices, prices, prices, benchmark]])

    def test_both_actual_mains_refuse_june29_cache_before_output(self):
        from ops.ops_live_safety import nyse_calendar
        dates = nyse_calendar('2018-01-02', '2026-06-29').sessions_in_range('2018-01-02', '2026-06-29')
        with tempfile.TemporaryDirectory() as scratch:
            data = Path(scratch)
            prices = pd.DataFrame({'A': 100.}, index=dates)
            for name in ['us_prices_panel', 'us_open_panel', 'us_volume_panel']:
                prices.to_parquet(data/(name+'.parquet'))
            prices.rename(columns={'A': 'Close'}).to_parquet(data/'spy.parquet')
            pd.DataFrame({'Code': ['A']}).to_parquet(data/'us_universe_meta.parquet')
            for run in [fixed_main, candidate_main]:
                output = data/run.__name__
                with self.assertRaisesRegex(ValueError, '2026-06-30'):
                    run(data, output)
                self.assertFalse(output.exists())

    def test_offline_import_succeeds_without_download_clients(self):
        code = '''
import sys
class BlockDownloads:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'yfinance', 'FinanceDataReader'}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, BlockDownloads())
import research.walk_forward_validation
from ops import us_hybrid_backtest as loaders
assert loaders.yf is None and loaders.fdr is None
print('OFFLINE_IMPORT_OK')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OFFLINE_IMPORT_OK', result.stdout)

    def test_fixed_and_candidate_complete_synthetic_nyse_folds(self):
        from ops.ops_live_safety import nyse_calendar
        dates = nyse_calendar('2018-01-02', '2026-07-02').sessions_in_range('2018-01-02', '2026-07-02')
        rng = np.random.default_rng(20261008)
        prices = pd.DataFrame(100*np.exp(np.cumsum(rng.normal(.0004, .012, (len(dates), 20)), axis=0)),
                              index=dates, columns=[f'A{i}' for i in range(20)])
        with tempfile.TemporaryDirectory() as scratch:
            data = Path(scratch)
            for frame, name in [(prices, 'us_prices_panel'), (prices, 'us_open_panel'),
                                (prices*0+1e7, 'us_volume_panel'), (prices.mean(axis=1).to_frame('Close'), 'spy')]:
                frame.to_parquet(data/(name+'.parquet'))
            pd.DataFrame({'Code': list(prices.columns)}).to_parquet(data/'us_universe_meta.parquet')
            with patch('ops.us_hybrid_backtest.yf', None), patch('ops.us_hybrid_backtest.fdr', None), \
                    patch('sys.stdout', new=io.StringIO()):
                for run in [fixed_main, candidate_main]:
                    output = data/run.__name__
                    run(data, output)
                    report = json.loads((output/'metrics.json').read_text(encoding='utf-8'))
                    self.assertEqual(len(report['folds']), 5)
                    self.assertEqual(report['folds'][-1]['test_end'], '2026-06-30')
                    returns = pd.read_csv(output/'oos_returns.csv')
                    self.assertFalse(returns.date.duplicated().any())
                    self.assertAlmostEqual((1+returns.return_).prod()-1, report['stitched_strategy']['total_return'])
                    self.assertEqual(len(returns), 625)


if __name__ == '__main__':
    unittest.main()
