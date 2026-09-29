"""Synthetic accounting and temporal isolation tests; no network or broker."""
import unittest
import numpy as np
import pandas as pd

from research.walk_forward_validation import make_targets, select_candidate, simulate


class WalkForwardTests(unittest.TestCase):
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
