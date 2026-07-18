"""
Tests for core.watchlist_alerts — each condition function against synthetic
scan rows, plus the full scan_rows_for_alerts dedup lifecycle (MACD's
network fetch is monkeypatched out). No real yfinance calls anywhere here.
Run with: python -m unittest tests.test_watchlist_alerts
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockanalysis.core import alerts
from stockanalysis.core import watchlist_alerts as wa

FLAT_ROW = {
    "Ticker": "MSFT", "RSI_14": 50, "Dist_to_Support%": 10, "Dist_to_Resistance%": 10,
    "Gap_Now%": 0.1, "RVOL": 0.9, "Price_vs_50MA%": -1,
}


class TestConditions(unittest.TestCase):
    def test_support_touch_fires_within_threshold(self):
        row = {**FLAT_ROW, "Dist_to_Support%": 1.0}
        self.assertIsNotNone(wa._support_touch(row))

    def test_support_touch_ignores_far_away(self):
        row = {**FLAT_ROW, "Dist_to_Support%": 8.0}
        self.assertIsNone(wa._support_touch(row))

    def test_breakdown_fires_when_below_support(self):
        row = {**FLAT_ROW, "Dist_to_Support%": -0.3}
        alert = wa._breakdown(row)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["priority"], "HIGH")

    def test_breakout_fires_when_above_resistance(self):
        row = {**FLAT_ROW, "Dist_to_Resistance%": -0.3, "Breakout_Probability": 80}
        alert = wa._breakout(row)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["confidence"], 80)

    def test_resistance_touch_does_not_fire_after_breakout(self):
        """Once price is through resistance (negative distance), that's a
        breakout, not a "touch" — the two conditions should be mutually
        exclusive on the same row."""
        row = {**FLAT_ROW, "Dist_to_Resistance%": -0.3}
        self.assertIsNone(wa._resistance_touch(row))
        self.assertIsNotNone(wa._breakout(row))

    def test_gap_requires_threshold(self):
        self.assertIsNone(wa._gap({**FLAT_ROW, "Gap_Now%": 1.5}))
        self.assertIsNotNone(wa._gap({**FLAT_ROW, "Gap_Now%": 3.5}))
        self.assertIsNotNone(wa._gap({**FLAT_ROW, "Gap_Now%": -4.0}))  # gap down too

    def test_volume_spike_requires_2x(self):
        self.assertIsNone(wa._volume_spike({**FLAT_ROW, "RVOL": 1.5}))
        self.assertIsNotNone(wa._volume_spike({**FLAT_ROW, "RVOL": 2.5}))

    def test_rsi_oversold_and_overbought_are_mutually_exclusive(self):
        oversold = {**FLAT_ROW, "RSI_14": 25}
        overbought = {**FLAT_ROW, "RSI_14": 75}
        self.assertIsNotNone(wa._rsi_oversold(oversold))
        self.assertIsNone(wa._rsi_overbought(oversold))
        self.assertIsNotNone(wa._rsi_overbought(overbought))
        self.assertIsNone(wa._rsi_oversold(overbought))

    def test_ema_crossover_proxy_requires_positive_pct(self):
        self.assertIsNone(wa._ema_crossover({**FLAT_ROW, "Price_vs_50MA%": -2}))
        self.assertIsNotNone(wa._ema_crossover({**FLAT_ROW, "Price_vs_50MA%": 3}))

    def test_missing_fields_do_not_raise(self):
        bare_row = {"Ticker": "XYZ"}
        for condition in wa._CONDITIONS:
            if condition is wa._macd_crossover:
                continue
            self.assertIsNone(condition(bare_row))

    def test_flat_row_fires_nothing(self):
        for condition in wa._CONDITIONS:
            if condition is wa._macd_crossover:
                continue
            self.assertIsNone(condition(FLAT_ROW))

    def test_headline_does_not_repeat_the_ticker(self):
        """Regression test: every display site (Alerts card, log table,
        email digest, Pre-Market Brief) prepends a["ticker"] in front of
        a["headline"] — if headline also started with the ticker, every
        rendering would read e.g. "PWR PWR MACD is bearish"."""
        row = {**FLAT_ROW, "Ticker": "PWR", "RSI_14": 25, "Gap_Now%": 5.0,
              "Dist_to_Resistance%": -0.5, "Dist_to_Support%": -0.5, "RVOL": 3.0,
              "Price_vs_50MA%": 3.0}
        for condition in wa._CONDITIONS:
            if condition is wa._macd_crossover:
                continue
            alert = condition(row)
            if alert is not None:
                self.assertFalse(alert["headline"].startswith("PWR"),
                                 f"{condition.__name__} headline repeats the ticker: {alert['headline']!r}")


class TestDefaultAlertTickers(unittest.TestCase):
    def test_uses_only_the_watchlist_named_list(self):
        """Regression test: watchlists.json also holds broad reference
        universes (sp500, whole GICS sectors) for the Scanner/Research
        pages. The alert monitor must scan only the "watchlist" list, not
        every saved list, or a 10-minute scan silently balloons to 500+
        tickers."""
        import stockanalysis.reporting.research as research

        orig = research.load_watchlists
        research.load_watchlists = lambda: {
            "watchlist": ["NVDA", "AMD"],
            "sp500": [f"T{i}" for i in range(500)],
            "Sector: Technology": [f"S{i}" for i in range(100)],
        }
        try:
            tickers = wa.default_alert_tickers()
            self.assertEqual(tickers, ["NVDA", "AMD"])
        finally:
            research.load_watchlists = orig

    def test_missing_watchlist_key_returns_empty(self):
        import stockanalysis.reporting.research as research
        orig = research.load_watchlists
        research.load_watchlists = lambda: {"sp500": ["A", "B"]}
        try:
            self.assertEqual(wa.default_alert_tickers(), [])
        finally:
            research.load_watchlists = orig


class ScanRowsForAlertsTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_state = alerts.ALERTS_STATE_PATH
        self._orig_log = alerts.ALERTS_LOG_PATH
        self._orig_macd = wa._macd_state
        self._orig_send = alerts.send_alert_emails
        tmp_dir = Path(tempfile.mkdtemp())
        alerts.ALERTS_STATE_PATH = tmp_dir / "alerts_state.json"
        alerts.ALERTS_LOG_PATH = tmp_dir / "alerts_log.json"
        wa._macd_state = lambda ticker: None  # no network in these tests
        alerts.send_alert_emails = lambda alerts_list: False

    def tearDown(self):
        alerts.ALERTS_STATE_PATH = self._orig_state
        alerts.ALERTS_LOG_PATH = self._orig_log
        wa._macd_state = self._orig_macd
        alerts.send_alert_emails = self._orig_send


class TestScanRowsForAlerts(ScanRowsForAlertsTestCase):
    def test_new_alerts_fire_once_and_resolve(self):
        rows = [{"Ticker": "NVDA", "Dist_to_Resistance%": -0.5, "Breakout_Probability": 70},
               {"Ticker": "TSLA", "RSI_14": 25}]
        first = wa.scan_rows_for_alerts(rows)
        self.assertEqual({a["dedup_key"] for a in first}, {"NVDA:breakout", "TSLA:rsi_oversold"})

        second = wa.scan_rows_for_alerts(rows)
        self.assertEqual(second, [])  # still true, already notified

        resolved_rows = [{"Ticker": "NVDA", "Dist_to_Resistance%": 5},
                        {"Ticker": "TSLA", "RSI_14": 55}]
        third = wa.scan_rows_for_alerts(resolved_rows)
        self.assertEqual(third, [])
        self.assertEqual(alerts.load_active(), {})

        fourth = wa.scan_rows_for_alerts(rows)
        self.assertEqual({a["dedup_key"] for a in fourth}, {"NVDA:breakout", "TSLA:rsi_oversold"})

    def test_rows_missing_ticker_are_skipped(self):
        rows = [{"RSI_14": 20}]  # no "Ticker" key
        self.assertEqual(wa.scan_rows_for_alerts(rows), [])

    def test_multiple_conditions_on_same_ticker_all_fire(self):
        rows = [{"Ticker": "AMD", "RSI_14": 20, "Gap_Now%": 5.0}]
        fired = {a["dedup_key"] for a in wa.scan_rows_for_alerts(rows)}
        self.assertEqual(fired, {"AMD:rsi_oversold", "AMD:gap"})


if __name__ == "__main__":
    unittest.main()
