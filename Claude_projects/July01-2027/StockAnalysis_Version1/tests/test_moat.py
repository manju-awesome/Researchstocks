"""
Tests for core.moat — the quantitative moat proxy on the research page's
Company Overview. Pure function, no network.
Run with: python -m unittest tests.test_moat
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockanalysis.core.moat import compute_moat


def _row(**kw):
    base = {"GrossMargin%": None, "OperatingMargin%": None,
            "ReturnOnEquity%": None, "FCF_Positive": None,
            "MarketCap": None, "Inst_Own%": None}
    base.update(kw)
    return base


class TestComputeMoat(unittest.TestCase):
    def test_franchise_quality_profile_scores_strong(self):
        # MSFT-like: fat margins, high ROE, FCF, mega-cap, institutionally held
        m = compute_moat(_row(**{"GrossMargin%": 69.0, "OperatingMargin%": 45.0,
                                 "ReturnOnEquity%": 38.0, "FCF_Positive": True,
                                 "MarketCap": 3e12, "Inst_Own%": 74.0}))
        self.assertEqual(m["score"], 100)
        self.assertEqual(m["label"], "Strong")
        self.assertEqual(m["inputs_used"], 6)

    def test_commodity_profile_scores_weak(self):
        m = compute_moat(_row(**{"GrossMargin%": 12.0, "OperatingMargin%": 4.0,
                                 "ReturnOnEquity%": 5.0, "FCF_Positive": False,
                                 "MarketCap": 3e9, "Inst_Own%": 30.0}))
        self.assertEqual(m["score"], 0)
        self.assertEqual(m["label"], "Weak")

    def test_middling_profile_scores_moderate(self):
        m = compute_moat(_row(**{"GrossMargin%": 42.0, "OperatingMargin%": 16.0,
                                 "ReturnOnEquity%": 16.0, "FCF_Positive": True,
                                 "MarketCap": 50e9, "Inst_Own%": 60.0}))
        # 15 + 15 + 12 + 10 + 5 + 10 = 67
        self.assertEqual(m["score"], 67)
        self.assertEqual(m["label"], "Moderate")

    def test_insufficient_inputs_returns_no_score(self):
        m = compute_moat(_row(**{"GrossMargin%": 60.0, "MarketCap": 1e12}))
        self.assertIsNone(m["score"])
        self.assertIsNone(m["label"])
        self.assertIn("2 of 6", m["drivers"][0])

    def test_three_inputs_is_enough_and_missing_ones_add_nothing(self):
        m = compute_moat(_row(**{"GrossMargin%": 60.0, "OperatingMargin%": 25.0,
                                 "ReturnOnEquity%": 25.0}))
        self.assertEqual(m["score"], 70)   # 25 + 25 + 20
        self.assertEqual(m["label"], "Strong")
        self.assertEqual(m["inputs_used"], 3)

    def test_every_driver_names_its_contribution(self):
        m = compute_moat(_row(**{"GrossMargin%": 60.0, "OperatingMargin%": 8.0,
                                 "ReturnOnEquity%": 7.0, "FCF_Positive": True}))
        self.assertEqual(len(m["drivers"]), 4)
        self.assertIn("Gross margin 60% (+25)", m["drivers"][0])
        self.assertIn("ROE 7% (+0)", m["drivers"][2])


if __name__ == "__main__":
    unittest.main()
