"""
Tests for core.ai_sentiment — synthetic pulse/pulse_extra dicts, no network.
Run with: python -m unittest tests.test_ai_sentiment
"""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockanalysis.core.ai_sentiment import (
    compute_risk_score, compute_rotation, compute_ai_health,
    compute_macro_caution, compute_tier_status, compute_ai_sentiment,
    build_snapshot,
)

ET = ZoneInfo("America/New_York")


def basket(chgs, rsi=55.0):
    return [{"ticker": f"T{i}", "day_chg_pct": c, "above_20ema": c >= 0, "rsi_14": rsi}
            for i, c in enumerate(chgs)]


def pulse_extra(yield_bps=0, dxy_chg=0.0, soxx_above_20ma=True, nvda_vwap=True,
                basket_chgs=None):
    return {
        "yield": {"change_bps": yield_bps},
        "dxy": {"change_pct": dxy_chg},
        "soxx": {"above_20ma": soxx_above_20ma},
        "nvda_above_vwap": nvda_vwap,
        "basket": basket(basket_chgs if basket_chgs is not None else [1.0] * 9),
        "tier1": [], "tier2": [], "tier3": [],
    }


def pulse(vix_chg=0.0, spy_chg=0.0, qqq_chg=0.0, sectors=None, econ_events=None):
    return {
        "vix": {"change_pct": vix_chg},
        "spy": {"day_chg_pct": spy_chg},
        "qqq": {"day_chg_pct": qqq_chg},
        "sectors": sectors or [],
        "econ_events": econ_events or [],
    }


class TestRiskScore(unittest.TestCase):
    def test_all_negative_triggers_defensive(self):
        r = compute_risk_score(
            pulse_extra(yield_bps=10, dxy_chg=1.0, soxx_above_20ma=False,
                       nvda_vwap=False, basket_chgs=[-1.0] * 9),
            pulse(vix_chg=10.0, spy_chg=1.0, qqq_chg=0.5))
        # yield -2, dxy -1, vix -2, soxx -2, nasdaq-vs-spy -1, nvda -2, breadth +0
        self.assertEqual(r["score"], -10)
        self.assertEqual(r["label"], "Defensive")

    def test_all_positive_triggers_aggressive(self):
        r = compute_risk_score(
            pulse_extra(yield_bps=-10, dxy_chg=0.1, soxx_above_20ma=True,
                       nvda_vwap=True, basket_chgs=[1.0] * 9),
            pulse(vix_chg=-5.0, spy_chg=0.5, qqq_chg=1.0))
        # yield +2, dxy +0, vix +0, soxx +0, nasdaq-vs-spy +0, nvda +0, breadth +2
        self.assertEqual(r["score"], 4)
        self.assertEqual(r["label"], "Aggressive buying")

    def test_neutral_inputs_score_zero(self):
        r = compute_risk_score(
            pulse_extra(yield_bps=0, dxy_chg=0.0, soxx_above_20ma=True,
                       nvda_vwap=True, basket_chgs=[0.5] * 4 + [-0.5] * 5),
            pulse(vix_chg=0.0, spy_chg=0.5, qqq_chg=0.5))
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["label"], "Neutral")

    def test_missing_data_does_not_raise(self):
        r = compute_risk_score({}, {})
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["drivers"], [])


class TestRotation(unittest.TestCase):
    def test_defensive_up_and_semis_down_is_risk_off(self):
        sectors = [
            {"label": "Utilities", "chg_pct": 1.0}, {"label": "Staples", "chg_pct": 0.5},
            {"label": "Health", "chg_pct": 0.3}, {"label": "Semis", "chg_pct": -1.5},
        ]
        r = compute_rotation(sectors)
        self.assertEqual(r["state"], "Risk-Off")

    def test_growth_sectors_up_is_risk_on(self):
        sectors = [
            {"label": "Semis", "chg_pct": 1.2}, {"label": "Software", "chg_pct": 0.8},
            {"label": "Industr", "chg_pct": 0.4}, {"label": "Financials", "chg_pct": 0.6},
        ]
        r = compute_rotation(sectors)
        self.assertEqual(r["state"], "Risk-On")

    def test_ambiguous_is_mixed(self):
        sectors = [{"label": "Semis", "chg_pct": 0.3}, {"label": "Utilities", "chg_pct": -0.2}]
        r = compute_rotation(sectors)
        self.assertEqual(r["state"], "Mixed")

    def test_no_sector_data_is_unknown(self):
        r = compute_rotation([])
        self.assertEqual(r["state"], "Unknown")


class TestAIHealth(unittest.TestCase):
    def test_strong_trend_bands_above_80(self):
        h = compute_ai_health(basket([2.0] * 9, rsi=85.0))
        self.assertGreater(h["index"], 80)
        self.assertEqual(h["label"], "Strong AI trend")

    def test_broad_correction_bands_below_20(self):
        h = compute_ai_health(basket([-4.0] * 9, rsi=15.0))
        self.assertLess(h["index"], 20)
        self.assertEqual(h["label"], "Broad AI correction")

    def test_empty_basket_returns_no_data(self):
        h = compute_ai_health([])
        self.assertIsNone(h["index"])
        self.assertEqual(h["label"], "No data")

    def test_advance_decline_counts(self):
        h = compute_ai_health(basket([1.0, 1.0, -1.0]))
        self.assertEqual(h["advancers"], 2)
        self.assertEqual(h["decliners"], 1)


class TestMacroCaution(unittest.TestCase):
    def test_cpi_within_48h_triggers_caution(self):
        now = datetime(2026, 7, 16, 9, 0, tzinfo=ET)
        events = [{"title": "CPI m/m", "when": now + timedelta(hours=20), "impact": "High"}]
        m = compute_macro_caution(events, now=now)
        self.assertTrue(m["caution"])
        self.assertEqual(len(m["events"]), 1)

    def test_event_beyond_48h_does_not_trigger(self):
        now = datetime(2026, 7, 16, 9, 0, tzinfo=ET)
        events = [{"title": "FOMC Statement", "when": now + timedelta(hours=72), "impact": "High"}]
        m = compute_macro_caution(events, now=now)
        self.assertFalse(m["caution"])

    def test_non_macro_title_does_not_trigger(self):
        now = datetime(2026, 7, 16, 9, 0, tzinfo=ET)
        events = [{"title": "Earnings: Some Retailer", "when": now + timedelta(hours=5), "impact": "Medium"}]
        m = compute_macro_caution(events, now=now)
        self.assertFalse(m["caution"])


class TestTierStatus(unittest.TestCase):
    def test_all_red_flag(self):
        s = compute_tier_status([{"day_chg_pct": -1.0}, {"day_chg_pct": -0.5}])
        self.assertTrue(s["all_red"])

    def test_mixed_not_all_red(self):
        s = compute_tier_status([{"day_chg_pct": -1.0}, {"day_chg_pct": 0.5}])
        self.assertFalse(s["all_red"])


class TestCompositeSentiment(unittest.TestCase):
    def test_ai_specific_rotation_penalty_applies(self):
        risk = {"score": 0, "label": "Neutral", "drivers": []}
        rotation = {"state": "Mixed", "drivers": []}
        health = {"index": 50}
        tier_statuses = [{"all_red": True}, {"all_red": True}, {"all_red": True}]
        s = compute_ai_sentiment(risk, rotation, health, tier_statuses, market_flat=True)
        self.assertTrue(s["ai_specific_rotation"])

        s_no_flag = compute_ai_sentiment(risk, rotation, health, tier_statuses, market_flat=False)
        self.assertFalse(s_no_flag["ai_specific_rotation"])
        self.assertGreater(s_no_flag["score"], s["score"])

    def test_score_bands(self):
        risk = {"score": 4, "label": "Aggressive buying", "drivers": []}
        rotation = {"state": "Risk-On", "drivers": []}
        health = {"index": 90}
        s = compute_ai_sentiment(risk, rotation, health, [], market_flat=False)
        self.assertGreater(s["score"], 70)
        self.assertIn("Aggressive", s["label"])

        risk_bad = {"score": -10, "label": "Defensive", "drivers": []}
        rotation_bad = {"state": "Risk-Off", "drivers": []}
        health_bad = {"index": 10}
        s_bad = compute_ai_sentiment(risk_bad, rotation_bad, health_bad, [], market_flat=False)
        self.assertLess(s_bad["score"], 40)
        self.assertIn("Defensive", s_bad["label"])


class TestBuildSnapshot(unittest.TestCase):
    def test_builds_full_snapshot_without_raising(self):
        snap = build_snapshot(pulse_extra(), pulse())
        for key in ("sentiment", "risk", "rotation", "ai_health", "macro",
                   "tiers", "all_ai", "soxx", "yield", "dxy", "relative_strength"):
            self.assertIn(key, snap)
        self.assertIsInstance(snap["sentiment"]["score"], int)

    def test_handles_empty_inputs(self):
        snap = build_snapshot({}, {})
        self.assertIn("sentiment", snap)


if __name__ == "__main__":
    unittest.main()
