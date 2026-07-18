"""
Tests for core.alerts — the priority/dedup engine behind the Alerts feed.
All storage goes through temp files (module paths monkeypatched) and email
sending is monkeypatched to a no-op capture, so nothing here touches real
data files or the network.
Run with: python -m unittest tests.test_alerts
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockanalysis.core import alerts


def _alert(dedup_key, priority="MEDIUM", ticker="NVDA"):
    return alerts.make_alert(
        dedup_key=dedup_key, category="watchlist", priority=priority, ticker=ticker,
        headline=f"{ticker} test alert", why_it_matters="testing",
        expected_impact="none", suggested_action="none",
        confidence=50, time_sensitivity="now")


class AlertsStorageTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_state = alerts.ALERTS_STATE_PATH
        self._orig_log = alerts.ALERTS_LOG_PATH
        tmp_dir = Path(tempfile.mkdtemp())
        alerts.ALERTS_STATE_PATH = tmp_dir / "alerts_state.json"
        alerts.ALERTS_LOG_PATH = tmp_dir / "alerts_log.json"

    def tearDown(self):
        alerts.ALERTS_STATE_PATH = self._orig_state
        alerts.ALERTS_LOG_PATH = self._orig_log


class TestMakeAlert(unittest.TestCase):
    def test_rejects_unknown_priority(self):
        with self.assertRaises(ValueError):
            alerts.make_alert(dedup_key="x", category="c", priority="URGENT!!",
                              headline="h", why_it_matters="w", expected_impact="e",
                              suggested_action="s", confidence=50, time_sensitivity="now")

    def test_confidence_is_clamped_to_0_100(self):
        a = alerts.make_alert(dedup_key="x", category="c", priority="LOW",
                              headline="h", why_it_matters="w", expected_impact="e",
                              suggested_action="s", confidence=150, time_sensitivity="now")
        self.assertEqual(a["confidence"], 100)
        b = alerts.make_alert(dedup_key="y", category="c", priority="LOW",
                              headline="h", why_it_matters="w", expected_impact="e",
                              suggested_action="s", confidence=-10, time_sensitivity="now")
        self.assertEqual(b["confidence"], 0)


class TestPriorityRank(unittest.TestCase):
    def test_critical_outranks_low(self):
        self.assertLess(alerts.priority_rank("CRITICAL"), alerts.priority_rank("LOW"))

    def test_unknown_priority_sorts_last(self):
        self.assertGreater(alerts.priority_rank("WHATEVER"), alerts.priority_rank("LOW"))


class TestDedupLifecycle(AlertsStorageTestCase):
    def setUp(self):
        super().setUp()
        # avoid any real network/email attempts during these tests
        self._orig_send = alerts.send_alert_emails
        alerts.send_alert_emails = lambda alerts_list: False

    def tearDown(self):
        alerts.send_alert_emails = self._orig_send
        super().tearDown()

    def test_new_condition_fires_once(self):
        a = _alert("NVDA:rsi_oversold")
        first = alerts.raise_alerts([a], {"NVDA:rsi_oversold"})
        second = alerts.raise_alerts([a], {"NVDA:rsi_oversold"})
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0)  # still true, already notified

    def test_resolved_condition_clears_state(self):
        a = _alert("NVDA:rsi_oversold")
        alerts.raise_alerts([a], {"NVDA:rsi_oversold"})
        alerts.raise_alerts([], {"NVDA:rsi_oversold"})  # condition no longer true
        self.assertEqual(alerts.load_active(), {})

    def test_recurrence_after_resolution_fires_again(self):
        a = _alert("NVDA:rsi_oversold")
        alerts.raise_alerts([a], {"NVDA:rsi_oversold"})
        alerts.raise_alerts([], {"NVDA:rsi_oversold"})
        third = alerts.raise_alerts([a], {"NVDA:rsi_oversold"})
        self.assertEqual(len(third), 1)

    def test_unrelated_active_alert_is_untouched_by_other_checks(self):
        """A dedup_key not in checked_keys this cycle (a different ticker/
        condition scan) must survive even though it isn't in current_alerts."""
        a = _alert("NVDA:rsi_oversold")
        alerts.raise_alerts([a], {"NVDA:rsi_oversold"})
        # a completely different scan cycle checking only TSLA shouldn't
        # touch NVDA's still-active state
        alerts.raise_alerts([], {"TSLA:rsi_oversold"})
        self.assertIn("NVDA:rsi_oversold", alerts.load_active())

    def test_log_accumulates_new_alerts_only(self):
        a = _alert("NVDA:rsi_oversold")
        alerts.raise_alerts([a], {"NVDA:rsi_oversold"})
        alerts.raise_alerts([a], {"NVDA:rsi_oversold"})  # suppressed, not logged again
        self.assertEqual(len(alerts.load_log()), 1)


class TestEmailBatching(unittest.TestCase):
    def test_only_critical_and_high_trigger_email(self):
        sent = {}

        def fake_send(subject, text, html, to=None):
            sent["subject"] = subject
            sent["text"] = text
            return True

        import stockanalysis.scanners.market_movers as mm
        orig = mm.send_resend_email
        mm.send_resend_email = fake_send
        try:
            batch = [_alert("A:x", priority="LOW"), _alert("B:y", priority="MEDIUM")]
            result = alerts.send_alert_emails(batch)
            self.assertFalse(result)
            self.assertNotIn("subject", sent)

            batch2 = [_alert("A:x", priority="LOW"), _alert("C:z", priority="CRITICAL")]
            result2 = alerts.send_alert_emails(batch2)
            self.assertTrue(result2)
            self.assertIn("1 alert", sent["subject"])
            self.assertIn("CRITICAL", sent["text"])
            self.assertNotIn("LOW", sent["text"])  # low-priority alert excluded from the batch
        finally:
            mm.send_resend_email = orig

    def test_no_urgent_alerts_returns_false_without_sending(self):
        self.assertFalse(alerts.send_alert_emails([_alert("A:x", priority="LOW")]))


if __name__ == "__main__":
    unittest.main()
