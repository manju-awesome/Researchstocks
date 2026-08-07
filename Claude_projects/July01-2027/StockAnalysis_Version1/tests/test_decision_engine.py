"""
Tests for core.decision_engine — the three scores the decision layer is
built on.

The invariant these defend: a missing input never becomes a score. Absent
data is reported as reduced coverage, not as 0 (which reads as bad) and not
as 50 (which invents a measurement).
Run with: python -m unittest tests.test_decision_engine
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockanalysis.core import decision_engine as DE


def _row(**kw):
    base = {
        "ticker": "TEST", "quality": 90, "health": 80, "moat": 3,
        "eps_growth": 30.0, "revenue_growth": 15.0, "forward_pe": 20.0,
        "rs_rank": 85, "above_200ma": True, "above_50ma": True,
        "swing_score": 80, "breakout_probability": 75.0, "rr": 3.0,
        "rvol": 1.5, "abs_vs_8ema": 1.0, "in_buy_zone": False,
        "category": "Momentum",
    }
    base.update(kw)
    return base


class TestInvestmentScore(unittest.TestCase):
    def test_a_strong_company_scores_high(self):
        r = DE.investment_score(_row(quality=95, health=90, moat=4,
                                     eps_growth=50, revenue_growth=25,
                                     forward_pe=15, rs_rank=90))
        self.assertGreaterEqual(r["score"], 85)
        self.assertIn(r["label"], ("Strong", "Exceptional"))
        self.assertEqual(r["coverage"], 1.0)

    def test_a_weak_company_scores_low(self):
        r = DE.investment_score(_row(quality=20, health=15, moat=0,
                                     eps_growth=-10, revenue_growth=-5,
                                     forward_pe=60, rs_rank=10,
                                     above_200ma=False))
        self.assertLess(r["score"], 30)
        self.assertEqual(r["label"], "Weak")

    def test_a_missing_field_reduces_coverage_rather_than_the_score(self):
        full = DE.investment_score(_row())
        partial = DE.investment_score(_row(moat=None))
        self.assertIn("Moat", partial["missing"])
        self.assertLess(partial["coverage"], 1.0)
        # Dropping a component the stock scored ~75 on shouldn't crater it
        self.assertGreater(partial["score"], full["score"] - 15)

    def test_no_data_at_all_scores_none_not_zero(self):
        r = DE.investment_score({})
        self.assertIsNone(r["score"])
        self.assertIsNone(r["label"])
        self.assertEqual(r["coverage"], 0.0)

    def test_negative_pe_is_not_treated_as_cheap(self):
        # A negative multiple means no earnings, which is not a bargain.
        cheap = DE.investment_score(_row(forward_pe=12))
        loss = DE.investment_score(_row(forward_pe=-30))
        self.assertIn("Valuation", loss["missing"])
        self.assertGreater(cheap["score"], loss["score"])

    def test_extreme_eps_growth_is_capped(self):
        # 21,000% EPS growth is an accounting artifact, not 350x the signal
        big = DE.investment_score(_row(eps_growth=21000))
        good = DE.investment_score(_row(eps_growth=60))
        self.assertEqual(big["score"], good["score"])


class TestSwingScore(unittest.TestCase):
    def test_a_clean_setup_scores_high(self):
        r = DE.swing_score(_row(swing_score=90, rs_rank=95,
                                breakout_probability=90, rr=4.0, rvol=2.5))
        self.assertGreaterEqual(r["score"], 85)
        self.assertIn(r["label"], ("A Setup", "A+ Setup"))

    def test_fundamentals_cannot_inflate_a_swing_score(self):
        # Perfect company, no setup: the swing score must stay low.
        r = DE.swing_score(_row(quality=100, health=100, moat=4,
                                eps_growth=200, swing_score=5, rs_rank=5,
                                breakout_probability=0, rr=0.5, rvol=0.3,
                                above_200ma=False, above_50ma=False))
        self.assertLess(r["score"], 30)
        self.assertEqual(r["label"], "Avoid")

    def test_falls_back_to_ema_distance_without_a_scan_swing_score(self):
        r = DE.swing_score(_row(swing_score=None, abs_vs_8ema=0.5))
        self.assertFalse(r["used_scan_swing"])
        self.assertNotIn("Setup quality", r["missing"])

    def test_missing_rr_and_breakout_are_reported(self):
        # The common case: R:R covers 207/545 rows, breakout 313/545.
        r = DE.swing_score(_row(rr=None, breakout_probability=None))
        self.assertIn("Risk/reward", r["missing"])
        self.assertIn("Breakout probability", r["missing"])
        self.assertLess(r["coverage"], 0.80)
        self.assertIsNotNone(r["score"])


class TestConfluence(unittest.TestCase):
    def test_counts_independent_confirmations(self):
        c = DE.confluence(_row(), regime_favorable=True)
        self.assertGreaterEqual(c["score"], 8)
        self.assertEqual(c["max"], 10)

    def test_correlated_signals_are_not_double_counted(self):
        # Quality and Moat are one business-strength check, not two.
        both = DE.confluence(_row(quality=95, moat=4))
        one = DE.confluence(_row(quality=95, moat=0))
        self.assertEqual(both["score"], one["score"])

    def test_unknown_regime_is_not_counted_either_way(self):
        c = DE.confluence(_row(), regime_favorable=None)
        self.assertIn("Market regime", c["unknown"])
        self.assertNotIn("Market regime", c["hits"])
        self.assertNotIn("Market regime", c["misses"])

    def test_measured_separates_unknown_from_failed(self):
        sparse = DE.confluence({"quality": 90}, regime_favorable=None)
        self.assertLess(sparse["measured"], 10)
        self.assertTrue(sparse["unknown"])

    def test_a_broken_stock_scores_low(self):
        c = DE.confluence(_row(quality=10, health=10, moat=0, eps_growth=-50,
                               rs_rank=5, above_200ma=False, above_50ma=False,
                               rr=0.4, rvol=0.3, breakout_probability=5,
                               abs_vs_8ema=25, category="Avoid",
                               in_buy_zone=False), regime_favorable=False)
        self.assertLessEqual(c["score"], 1)


class TestScoreRow(unittest.TestCase):
    def test_reliable_requires_coverage_on_both_scores(self):
        self.assertTrue(DE.score_row(_row())["reliable"])

    def test_sparse_data_is_not_reliable(self):
        r = DE.score_row({"ticker": "X", "quality": 90})
        self.assertFalse(r["reliable"])

    def test_returns_all_three_scores(self):
        r = DE.score_row(_row(), regime_favorable=True)
        self.assertIn("investment", r)
        self.assertIn("swing", r)
        self.assertIn("confluence", r)
        self.assertEqual(r["ticker"], "TEST")



class TestActions(unittest.TestCase):
    def _strong(self, **kw):
        base = dict(quality=90, health=85, moat=4, eps_growth=40,
                    rs_rank=92, swing_score=85, breakout_probability=85,
                    rr=3.5, rvol=1.8, abs_vs_8ema=1.0, above_200ma=True,
                    above_50ma=True, days_to_earnings=40)
        base.update(kw)          # kw wins; passing both would be a TypeError
        return _row(**base)

    def test_exactly_one_action_and_it_is_a_known_one(self):
        d = DE.decide(self._strong())
        self.assertIn(d["action"], DE.ACTIONS)
        self.assertNotIn("/", d["action"])          # no "BUY/WATCH"

    def test_strategy_decides_which_score_gates(self):
        # Strong company, poor setup: a long-term buy, not a swing entry.
        row = _row(quality=95, health=90, moat=4, eps_growth=50, rs_rank=88,
                   swing_score=20, breakout_probability=10, rr=2.5,
                   rvol=0.5, abs_vs_8ema=1.0, days_to_earnings=40)
        lt = DE.decide(row, strategy="LONGTERM")["action"]
        sw = DE.decide(row, strategy="SWING")["action"]
        self.assertNotEqual(lt, sw)

    def test_balanced_requires_both_scores(self):
        # max() would let this through; min() is the honest reading.
        row = _row(quality=20, health=25, moat=0, eps_growth=-5,
                   swing_score=90, rs_rank=95, rr=3.0, days_to_earnings=40)
        self.assertNotEqual(DE.decide(row, strategy="BALANCED")["action"],
                            "BUY NOW")

    def test_imminent_earnings_downgrades_a_buy(self):
        row = self._strong(days_to_earnings=1)
        d = DE.decide(row, strategy="SWING")
        self.assertEqual(d["action"], "WAIT")
        self.assertEqual(d["earnings_risk"], "CRITICAL")
        self.assertTrue(any("Earnings" in r for r in d["risks"]))

    def test_earnings_strategy_opt_in_restores_the_buy(self):
        row = self._strong(days_to_earnings=3)
        d = DE.decide(row, strategy="SWING", earnings_strategy=True)
        self.assertNotEqual(d["action"], "WAIT")

    def test_weak_quality_is_speculative_not_a_buy(self):
        row = self._strong(quality=30, health=35)
        self.assertEqual(DE.decide(row, strategy="SWING")["action"],
                         "SPECULATIVE")

    def test_negative_rr_is_disqualifying(self):
        self.assertEqual(DE.decide(self._strong(rr=0.4))["action"], "AVOID")

    def test_insufficient_data_never_yields_a_buy(self):
        d = DE.decide({"ticker": "X", "quality": 90})
        self.assertEqual(d["action"], "AVOID")
        self.assertFalse(d["reliable"])

    def test_extended_price_becomes_buy_on_pullback(self):
        # No breakout in progress — a genuine breakout IS extended, and is
        # entered on the breakout, so it must not be diverted to "pullback".
        row = self._strong(abs_vs_8ema=9.0, in_buy_zone=False,
                           breakout_probability=30, rvol=0.9)
        d = DE.decide(row, strategy="SWING")
        self.assertIn(d["action"], ("BUY ON PULLBACK", "WATCH"))
        self.assertTrue(d["triggers"])

    def test_watch_always_says_what_would_change_it(self):
        row = _row(quality=75, health=70, moat=2, eps_growth=18, rs_rank=72,
                   swing_score=66, breakout_probability=75, rr=1.4,
                   rvol=0.9, abs_vs_8ema=6.0, days_to_earnings=40)
        d = DE.decide(row, strategy="SWING")
        if d["action"] in ("WATCH", "WAIT"):
            self.assertTrue(d["triggers"])

    def test_defensive_regime_is_stricter_than_favorable(self):
        row = _row(quality=80, health=75, moat=3, eps_growth=25, rs_rank=82,
                   swing_score=78, breakout_probability=72, rr=2.2,
                   rvol=1.3, abs_vs_8ema=1.5, days_to_earnings=40)
        fav = DE.decide(row, strategy="SWING", regime="FAVORABLE")["action"]
        dfn = DE.decide(row, strategy="SWING", regime="DEFENSIVE")["action"]
        order = {a: i for i, a in enumerate(
            ["BUY NOW", "BREAKOUT ENTRY", "BUY ZONE", "BUY ON PULLBACK",
             "WATCH", "WAIT", "SPECULATIVE", "AVOID"])}
        self.assertGreaterEqual(order[dfn], order[fav])

    def test_earnings_risk_bands(self):
        self.assertEqual(DE.earnings_risk(1), "CRITICAL")
        self.assertEqual(DE.earnings_risk(5), "HIGH")
        self.assertEqual(DE.earnings_risk(10), "MEDIUM")
        self.assertEqual(DE.earnings_risk(40), "LOW")
        self.assertEqual(DE.earnings_risk(None), "UNKNOWN")

    def test_recovered_data_is_flagged_as_a_risk(self):
        row = self._strong(recovered=True, data_as_of="2026-08-05 16:45")
        self.assertTrue(any("snapshot" in r for r in
                            DE.decide(row)["risks"]))

if __name__ == "__main__":
    unittest.main()
