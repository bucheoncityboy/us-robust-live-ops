"""Synthetic accounting and temporal isolation tests; no network or broker."""
import unittest
import numpy as np
import pandas as pd

from research.walk_forward_validation import (
    make_targets, select_candidate, simulate, fixed_targets, monthly_table,
    edge_statistics, regime_labels,
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
                dollar_volume = (close.loc[:signal].tail(20)*volume.loc[:signal].tail(20)).mean()
                self.assertTrue(set(codes).issubset(dollar_volume.nlargest(20).index))
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


if __name__ == '__main__':
    unittest.main()
