"""
Tests for core.longterm — the Long-Term Buy Engine.

The invariants these defend, in the order the engine applies them:

  1. The hierarchy is structural. A perfect chart cannot rescue a company
     that failed the quality gate, because the technical gate is never
     reached. This is the property that distinguishes the engine from a
     weighted composite, and the one most likely to be broken by a
     well-meaning refactor that "simplifies" the ladder into a score.
  2. A missing input is never a satisfied condition. Unknown trend is not
     an intact trend; an unmeasured candle is not a confirmation.
  3. Support means price is ABOVE the level. A moving average price has
     fallen through is resistance, and counting it as support is how a
     screener recommends a breakdown.
  4. The reverse DCF's comparison survives negative growth on either side.

Run with: python -m unittest tests.test_longterm_engine
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockanalysis.core.longterm import engine as E
from stockanalysis.core.longterm import quality as Q
from stockanalysis.core.longterm import technicals as T
from stockanalysis.core.longterm import valuation as V


def _row(**kw):
    """An elite company at a clean 8/21 EMA pullback with confirmation —
    the one shape that should reach BUY NOW. Every test mutates one thing."""
    base = {
        "Ticker": "TEST", "LongName": "Test Corp", "Sector": "Technology",
        "Industry": "Software - Infrastructure", "Current Price": 100.0,
        # fundamentals -> LQuality well above the 85 the EMA zone needs
        "Revenue": 25.0, "EPS_Growth%": 30.0, "ReturnOnEquity%": 30.0,
        "OperatingMargin%": 30.0, "GrossMargin%": 70.0, "FCF_Margin%": 25.0,
        "FCF_Positive": True, "DebtToEquity": 20.0, "CurrentRatio": 3.0,
        "TotalCash": 5e10, "TotalDebt": 1e10, "Inst_Own%": 65.0,
        "Inst_Own_Chg": 1.5, "FreeCashFlow": 2.0e10, "NetIncome": 2.0e10,
        "SharesOutstanding": 1.0e9, "Beta": 1.0, "MarketCap": 1.0e11,
        "FCF_CAGR%": 20.0, "FCF_Years": 4, "FCF_Positive_Years": 4,
        "Revenue_CAGR%": 20.0, "OperatingMargin_Trend_pp": 2.0,
        # trend: intact and rising
        "8EMA": 99.0, "21EMA": 98.5, "50MA": 92.0, "200MA": 80.0,
        "Above_200MA": True, "Price_vs_50MA%": 8.7, "Price_vs_200MA%": 25.0,
        "Pct_vs_8EMA": 1.0, "MA50_Slope%": 2.0, "MA200_Slope%": 1.5,
        "ATR_Pct": 2.0, "RSI_14": 55.0, "Dist_52W_High%": -8.0,
        "52W High": 108.0, "Prior_Breakout_Level": 99.2,
        # volume + confirmation
        "Vol_vs_20D": 0.7, "Pullback_Vol_Ratio": 0.7, "VolumeDryingUp": True,
        "Distribution_Days_25d": 1, "Reversal_Candle": "bullish engulfing",
        "RVOL": 1.3, "RS_Rank": 85.0, "RS": 8.0,
        "Days_To_Earnings": 40,
    }
    base.update(kw)
    return base


class TestHierarchyIsStructural(unittest.TestCase):
    """The core claim of the whole package."""

    def test_the_baseline_row_is_a_buy(self):
        # If this breaks, every "cannot reach a buy" test below is vacuous.
        r = E.evaluate(_row())
        self.assertEqual(r["action"], "BUY NOW")
        self.assertEqual(r["gate"], "confirmed")

    def test_a_perfect_chart_cannot_rescue_a_weak_company(self):
        # Chart, volume, trend and confirmation all untouched and ideal;
        # only the business is gutted.
        weak = _row(FCF_Positive=False, DebtToEquity=400.0,
                    CurrentRatio=0.6, TotalCash=1e8, TotalDebt=5e10,
                    OperatingMargin_Trend_pp=-8.0,
                    **{"Revenue": -5.0, "EPS_Growth%": -20.0,
                       "ReturnOnEquity%": 2.0, "OperatingMargin%": 1.0,
                       "GrossMargin%": 8.0, "FCF_Margin%": -5.0,
                       "FCF_CAGR%": -30.0})
        r = E.evaluate(weak)
        self.assertEqual(r["action"], "AVOID")
        self.assertEqual(r["gate"], "quality")
        self.assertLess(r["quality"]["score"], Q.MIN_OWNABLE)

    def test_quality_alone_cannot_reach_a_buy_when_overvalued(self):
        # An elite business whose price demands far more than it delivers.
        r = E.evaluate(_row(FreeCashFlow=2.0e8,
                            **{"FCF_CAGR%": 3.0, "Revenue_CAGR%": 3.0,
                               "Revenue": 3.0}))
        # Named, not bare: the business is fine, the price is not.
        self.assertEqual(r["action"], "OWN / WAIT FOR PRICE")
        self.assertEqual(r["gate"], "valuation")

    def test_broken_trend_watches_rather_than_avoids(self):
        # The business still passed gate 1, so this is a watchlist name whose
        # chart has to heal — not a company to discard.
        # BOTH averages must point down for a breakdown — leaving the
        # fixture's default rising 50 MA in place describes a recovery.
        r = E.evaluate(_row(Above_200MA=False,
                            **{"MA200_Slope%": -2.0, "MA50_Slope%": -2.0,
                               "200MA": 120.0, "50MA": 110.0,
                               "Price_vs_50MA%": -9.0}))
        self.assertEqual(r["trend"]["state"], "BROKEN")
        self.assertEqual(r["action"], "OWN / WAIT FOR TREND")
        self.assertEqual(r["gate"], "trend")

    def test_zone_quality_bars_come_from_the_framework(self):
        # 200 MA is the deep entry and demands 90, not 85.
        self.assertEqual(E.ZONE_MIN_QUALITY["200MA"], 90)
        self.assertEqual(E.ZONE_MIN_QUALITY["EMA"], 85)


class TestMissingInputsAreNotSatisfiedConditions(unittest.TestCase):
    def test_unknown_trend_slope_blocks_a_buy_without_failing_the_trend(self):
        r = E.evaluate(_row(**{"MA200_Slope%": None}))
        self.assertIsNone(r["trend"]["pass"])
        self.assertNotEqual(r["action"], "BUY NOW")

    def test_an_unmeasured_candle_is_not_a_confirmation(self):
        r = E.evaluate(_row(Reversal_Candle=None))
        self.assertEqual(r["action"], "WATCH")
        self.assertEqual(r["gate"], "trigger")

    def test_no_reversal_candle_blocks_the_buy(self):
        r = E.evaluate(_row(Reversal_Candle="none"))
        self.assertEqual(r["gate"], "trigger")
        self.assertTrue(any("reversal" in b.lower() for b in r["blockers"]))

    def test_quality_renormalises_rather_than_zero_filling(self):
        full = Q.compute_lquality(_row())
        # Drop two factors entirely; the score must not collapse toward zero.
        partial = Q.compute_lquality(
            _row(Inst_Own_Chg=None, CurrentRatio=None, DebtToEquity=None,
                 TotalCash=None, TotalDebt=None, **{"Inst_Own%": None}))
        self.assertLess(partial["coverage"], full["coverage"])
        self.assertGreater(partial["score"], 70)

    def test_unreliable_coverage_withholds_the_tier_and_avoids(self):
        bare = {"Ticker": "X", "Current Price": 10.0, "GrossMargin%": 70.0}
        lq = Q.compute_lquality(bare)
        self.assertFalse(lq["reliable"])
        self.assertIsNone(lq["tier"])
        self.assertEqual(E.evaluate(bare)["gate"], "quality")


class TestSupportRequiresPriceAboveTheLevel(unittest.TestCase):
    def test_a_level_price_has_fallen_through_is_not_support(self):
        # 8 EMA above the price: that is resistance overhead.
        conf = T.compute_support_confluence(
            _row(**{"8EMA": 105.0, "21EMA": 104.0, "50MA": 103.0,
                    "200MA": 102.0, "Prior_Breakout_Level": 101.0}))
        self.assertEqual(conf["score"], 0)
        self.assertEqual(conf["hits"], [])

    def test_a_stock_falling_through_every_average_scores_no_support(self):
        # The failure mode the module exists to prevent: proximity to four
        # averages at once during a collapse reading as strong confluence.
        row = _row(**{"Current Price": 79.0, "8EMA": 99.0, "21EMA": 98.5,
                      "50MA": 92.0, "200MA": 80.0, "Pct_vs_8EMA": -20.2})
        self.assertEqual(T.compute_pullback(row)["zone"], "NONE")
        self.assertEqual(T.compute_support_confluence(row)["score"], 0)

    def test_the_breakdown_note_does_not_contradict_itself(self):
        """The distance is derived from the price and level just compared.

        Reading it from Price_vs_200MA% instead let a stale scan column
        produce "Below the 200 MA (+25.0%)" — a sentence that disagrees with
        itself inside eight words.
        """
        pull = T.compute_pullback(
            _row(**{"Current Price": 79.0, "200MA": 80.0,
                    "Price_vs_200MA%": 25.0, "MA200_Slope%": -1.0,
                    "MA50_Slope%": -1.0}))
        self.assertIn("-1.2%", pull["note"])
        self.assertNotIn("+25.0%", pull["note"])

    def test_a_lost_average_above_a_held_200ma_reads_as_resistance(self):
        # Below the short-term averages but still above the 200 MA: not a
        # breakdown, and the levels overhead are resistance, not support.
        pull = T.compute_pullback(
            _row(**{"Current Price": 90.0, "8EMA": 99.0, "21EMA": 98.5,
                    "50MA": 92.0, "200MA": 60.0, "Pct_vs_8EMA": -9.1,
                    "Prior_Breakout_Level": None, "ATR_Pct": 1.0}))
        self.assertEqual(pull["stage"], "STAGE3_DEEP")
        self.assertEqual(T.compute_support_confluence(
            _row(**{"Current Price": 90.0, "8EMA": 99.0, "21EMA": 98.5,
                    "50MA": 92.0, "200MA": 99.0, "S1": None,
                    "Prior_Breakout_Level": None}))["score"], 0)

    def test_confluence_counts_the_ema_pair_once(self):
        # 8 and 21 EMA are one short-term signal at two lookbacks.
        conf = T.compute_support_confluence(
            _row(**{"8EMA": 99.5, "21EMA": 99.0, "50MA": 60.0,
                    "200MA": 50.0, "S1": None, "Prior_Breakout_Level": None}))
        names = [h["name"] for h in conf["hits"]]
        self.assertEqual(names.count("8/21 EMA"), 1)

    def test_tolerance_scales_with_volatility(self):
        quiet = T._tolerance(_row(**{"ATR_Pct": 0.5}))
        wild = T._tolerance(_row(**{"ATR_Pct": 9.0}))
        self.assertLess(quiet, wild)
        self.assertGreaterEqual(quiet, T.MIN_TOLERANCE_PCT)
        self.assertLessEqual(wild, T.MAX_TOLERANCE_PCT)


class TestExtensionAndEarnings(unittest.TestCase):
    def test_extended_price_is_not_a_zone(self):
        r = E.evaluate(_row(**{"Pct_vs_8EMA": 9.0}))
        self.assertTrue(r["pullback"]["extended"])
        self.assertEqual(r["pullback"]["zone"], "NONE")
        self.assertNotEqual(r["action"], "BUY NOW")

    def test_extended_names_still_get_a_priced_entry(self):
        r = E.evaluate(_row(**{"Pct_vs_8EMA": 9.0}))
        self.assertTrue(r["entries"])
        self.assertTrue(all(e["price"] is not None for e in r["entries"]))
        self.assertTrue(any("$" in t for t in r["triggers"]))

    def test_imminent_earnings_blocks_every_buy(self):
        r = E.evaluate(_row(Days_To_Earnings=2))
        self.assertEqual(r["action"], "WAIT")
        self.assertEqual(r["gate"], "earnings")

    def test_defensive_regime_stops_buying_entirely(self):
        r = E.evaluate(_row(), regime="DEFENSIVE")
        self.assertEqual(r["action"], "WATCH")
        self.assertEqual(r["gate"], "regime")

    def test_selective_regime_raises_the_quality_bar(self):
        # Quality sitting between the normal bar and the bumped one.
        row = _row()
        base = Q.compute_lquality(row)["score"]
        self.assertGreaterEqual(base, 85)
        favorable = E.evaluate(row, regime="FAVORABLE")
        self.assertEqual(favorable["action"], "BUY NOW")


class TestReverseDCF(unittest.TestCase):
    def test_a_price_demanding_more_than_delivered_is_overvalued(self):
        v = V.compute_valuation(_row(FreeCashFlow=2.0e8,
                                     **{"FCF_CAGR%": 3.0,
                                        "Revenue_CAGR%": 3.0, "Revenue": 3.0}))
        self.assertEqual(v["band"], "OVERVALUED")
        self.assertFalse(v["acceptable"])

    def test_declining_business_priced_for_less_decline_is_overvalued(self):
        """The bug a ratio comparison cannot see.

        Implied -5%/yr against a company shrinking 10%/yr gives a ratio of
        -1.67, which sorts into "asks less than delivered" and reports a
        melting business as UNDERVALUED. The price is in fact demanding a
        better outcome than the company produces.
        """
        implied, delivered = -5.0, -10.0
        gap = implied - delivered
        tolerance = max(V.TOLERANCE_FLOOR_PP,
                        abs(delivered) * V.TOLERANCE_FRACTION)
        self.assertGreater(gap, tolerance)      # -> OVERVALUED, correctly

    def test_implausible_implied_growth_is_refused_at_any_delivered_rate(self):
        # A base-effect year must not license a price requiring 50%+ forever.
        v = V.compute_valuation(_row(FreeCashFlow=2.0e8,
                                     **{"FCF_CAGR%": 200.0,
                                        "Revenue_CAGR%": 200.0}))
        if v["implied_growth_pct"] is not None and \
                v["implied_growth_pct"] >= V.IMPLAUSIBLE_IMPLIED_GROWTH:
            self.assertEqual(v["band"], "OVERVALUED")
            self.assertEqual(V.valuation_sub_score(v), 0.0)

    def test_financials_are_priced_on_peers_not_cash_flow(self):
        blocked = V._dcf_blocked(_row(Sector="Financial Services"))
        self.assertIsNotNone(blocked)
        self.assertIn("free cash flow", blocked.lower())

    def test_negative_free_cash_flow_blocks_the_model(self):
        self.assertIsNotNone(V._dcf_blocked(_row(FreeCashFlow=-1e9)))

    def test_share_count_falls_back_to_market_cap(self):
        shares = V._shares(_row(SharesOutstanding=None, MarketCap=1.0e11,
                                **{"Current Price": 100.0}))
        self.assertAlmostEqual(shares, 1.0e9, delta=1.0)

    def test_the_implied_rate_means_what_the_headline_says(self):
        """Growth is held flat through the explicit window.

        Re-deriving the value at the solved rate must reproduce the market
        capitalisation; if the model faded growth internally the headline
        "requires X% every year for 5 years" would be false.
        """
        row = _row()
        discount, _ = V._discount_rate(1.0, V.DEFAULT_RISK_FREE)
        net_cash = row["TotalCash"] - row["TotalDebt"]
        market_equity = row["Current Price"] * row["SharesOutstanding"]
        g = V._implied_growth(market_equity, row["FreeCashFlow"], discount,
                              net_cash)
        self.assertIsNotNone(g)
        rebuilt = V._equity_value(row["FreeCashFlow"], g, discount, net_cash)
        self.assertAlmostEqual(rebuilt / market_equity, 1.0, places=3)


class TestQualityCalibration(unittest.TestCase):
    def test_moat_excludes_revenue_growth(self):
        # Growth is not a moat, and is already scored twice elsewhere.
        fields = [key for key, _label, _t in Q._MOAT_CHECKS]
        self.assertNotIn("Revenue", fields)

    def test_a_low_margin_leader_is_not_penalised_for_its_industry(self):
        """Absolute-only thresholds scored Walmart's moat 0 — a finding about
        retail accounting, not competitive position."""
        # Every figure below is beneath the absolute elite bars (60% gross,
        # 25% operating, 25% ROE), which is the normal state of a retailer.
        peers = [_row(Ticker=f"P{i}", Sector="Consumer Defensive",
                      Industry="Discount Stores", **{"GrossMargin%": 10.0 + i,
                                                     "OperatingMargin%": 2.0 + i * 0.1,
                                                     "ReturnOnEquity%": 10.0 + i})
                 for i in range(12)]
        leader = _row(Ticker="LEAD", Sector="Consumer Defensive",
                      Industry="Discount Stores", **{"GrossMargin%": 25.0,
                                                     "OperatingMargin%": 5.0,
                                                     "ReturnOnEquity%": 22.0})
        stats = Q.build_sector_stats(peers + [leader])
        scored, _ = Q._moat(leader, stats)
        self.assertGreater(scored, 0.0)
        # ...while the same company against absolute bars alone scores zero.
        bare, _ = Q._moat(leader, {})
        self.assertEqual(bare, 0.0)

    def test_zero_gross_margin_is_treated_as_not_reported(self):
        # Banks have no COGS line; reading the placeholder as a real 0%
        # scored JPMorgan down for a field it cannot have.
        with_zero, _ = Q._moat(_row(**{"GrossMargin%": 0.0,
                                       "OperatingMargin%": 50.0,
                                       "ReturnOnEquity%": 30.0}), {})
        self.assertEqual(with_zero, 100.0)

    def test_fcf_trend_separates_growing_from_shrinking(self):
        growing, _ = Q._free_cash_flow(_row(**{"FCF_CAGR%": 25.0}))
        shrinking, _ = Q._free_cash_flow(_row(**{"FCF_CAGR%": -20.0,
                                                 "FCF_Positive_Years": 2}))
        self.assertGreater(growing, shrinking)

    def test_margin_direction_adjusts_but_does_not_dominate(self):
        high_eroding, _ = Q._operating_margin(
            _row(**{"OperatingMargin%": 45.0, "OperatingMargin_Trend_pp": -3.0}))
        low_expanding, _ = Q._operating_margin(
            _row(**{"OperatingMargin%": 8.0, "OperatingMargin_Trend_pp": 3.0}))
        self.assertGreater(high_eroding, low_expanding)


class TestUniverseContext(unittest.TestCase):
    def test_sector_rs_rank_is_relative_to_the_sector(self):
        rows = [_row(Ticker=f"T{i}", Sector="Technology", RS=float(i))
                for i in range(10)]
        rows += [_row(Ticker=f"E{i}", Sector="Energy", RS=100.0 + i)
                 for i in range(10)]
        E.attach_sector_context(rows)
        # The weakest Energy name leads the market on raw RS but sits at the
        # bottom of its own group — §9's whole point.
        weakest_energy = next(r for r in rows if r["Ticker"] == "E0")
        self.assertEqual(weakest_energy["Sector_RS_Rank"], 0)
        self.assertGreater(weakest_energy["Sector_Strength_Rank"], 0)

    def test_evaluate_universe_sorts_buys_first(self):
        results = E.evaluate_universe([_row(Ticker="GOOD"),
                                       _row(Ticker="BAD",
                                            **{"Revenue": -10.0,
                                               "EPS_Growth%": -30.0,
                                               "ReturnOnEquity%": 1.0,
                                               "OperatingMargin%": 0.5,
                                               "GrossMargin%": 5.0,
                                               "FCF_Margin%": -10.0,
                                               "DebtToEquity": 500.0})])
        self.assertEqual(results[0]["ticker"], "GOOD")
        self.assertEqual(results[-1]["action"], "AVOID")


if __name__ == "__main__":
    unittest.main()


class TestTickerSearch(unittest.TestCase):
    """webapp.longterm_view.parse_tickers — the /longterm search box."""

    def setUp(self):
        from stockanalysis.webapp import longterm_view
        self.parse = longterm_view.parse_tickers

    def test_a_single_ticker(self):
        self.assertEqual(self.parse("NVDA"), ["NVDA"])

    def test_comma_separated(self):
        self.assertEqual(self.parse("NVDA,MSFT,AAPL"),
                         ["NVDA", "MSFT", "AAPL"])

    def test_lowercase_is_normalised(self):
        self.assertEqual(self.parse("nvda, msft"), ["NVDA", "MSFT"])

    def test_any_separator_works(self):
        # Pasted lists arrive as newlines, tabs, semicolons or bare spaces
        # depending on where they were copied from.
        self.assertEqual(self.parse("NVDA, MSFT\nAAPL\tGOOGL;AMD  META"),
                         ["NVDA", "MSFT", "AAPL", "GOOGL", "AMD", "META"])

    def test_share_classes_and_indices_survive(self):
        self.assertEqual(self.parse("BRK-B, BF.B, ^GSPC"),
                         ["BRK-B", "BF.B", "^GSPC"])

    def test_duplicates_collapse_keeping_first_position(self):
        self.assertEqual(self.parse("NVDA, MSFT, NVDA"), ["NVDA", "MSFT"])

    def test_empty_and_junk_yield_nothing(self):
        for junk in ("", "   ", ",,,", None):
            self.assertEqual(self.parse(junk), [])

    def test_a_pasted_column_is_capped(self):
        many = ", ".join(f"T{i}" for i in range(500))
        self.assertEqual(len(self.parse(many, limit=60)), 60)


class TestSearchPageWiring(unittest.TestCase):
    """The page renders the search without reaching the network.

    api.longterm() is stubbed because the point of these is the filtering and
    URL-state logic, not the engine — which the tests above already cover.
    """

    def setUp(self):
        from stockanalysis.webapp import api, longterm_view
        self.view = longterm_view
        self._real = api.longterm
        rows = [E.evaluate(_row(Ticker=t)) for t in ("NVDA", "MSFT", "AAPL")]
        rows[2]["action"], rows[2]["icon"] = "AVOID", "🔴"
        api.longterm = lambda override=None: {
            "rows": rows, "counts": {}, "regime": "FAVORABLE",
            "regime_note": "test", "risk_free_note": "test",
            "coverage": {"total": 3, "ma_slope": 3, "reversal": 3,
                         "statements": 3, "breakout": 3, "needs_rescan": False},
        }

    def tearDown(self):
        from stockanalysis.webapp import api
        api.longterm = self._real

    def test_search_narrows_to_the_named_tickers(self):
        body, _ = self.view.longterm_page({"q": ["nvda, msft"]})
        self.assertIn(">NVDA<", body)
        self.assertIn(">MSFT<", body)
        self.assertNotIn(">AAPL<", body)

    def test_unknown_tickers_are_named_not_silently_dropped(self):
        body, _ = self.view.longterm_page({"q": ["NVDA, ZZZZ"]})
        self.assertIn("Not in the research library", body)
        self.assertIn("ZZZZ", body)

    def test_a_single_result_opens_its_reasoning(self):
        body, _ = self.view.longterm_page({"q": ["NVDA"]})
        self.assertIn("<details open>", body)

    def test_several_results_stay_collapsed(self):
        body, _ = self.view.longterm_page({"q": ["NVDA, MSFT"]})
        self.assertNotIn("<details open>", body)

    def test_chips_preserve_the_search(self):
        # Clicking a chip used to drop the search entirely.
        body, _ = self.view.longterm_page({"q": ["NVDA, AAPL"]})
        self.assertIn("q=NVDA%2C+AAPL", body)

    def test_chip_counts_are_scoped_to_the_search(self):
        # Counting across the whole library would offer "Avoid 347" beside
        # two searched tickers and return an empty table when clicked.
        body, _ = self.view.longterm_page({"q": ["NVDA, MSFT"]})
        self.assertNotIn("Avoid 1", body)
        full, _ = self.view.longterm_page({})
        self.assertIn("Avoid 1", full)

    def test_no_search_still_renders_the_whole_library(self):
        body, _ = self.view.longterm_page({})
        for ticker in ("NVDA", "MSFT", "AAPL"):
            self.assertIn(f">{ticker}<", body)
        self.assertNotIn("Not in the research library", body)


class Test52WeekRange(unittest.TestCase):
    def test_position_in_the_range(self):
        rng = T.compute_52w_range(_row(**{"Current Price": 90.0,
                                          "52W High": 100.0, "52W Low": 50.0}))
        self.assertEqual(rng["position_pct"], 80.0)
        self.assertEqual(rng["high"], 100.0)
        self.assertEqual(rng["low"], 50.0)

    def test_both_endpoints_are_reported(self):
        """A stock 8% off its high and one 8% off its low are not the same
        purchase, and only having one endpoint cannot tell them apart."""
        rng = T.compute_52w_range(_row(**{"Current Price": 92.0,
                                          "52W High": 100.0, "52W Low": 50.0,
                                          "Dist_52W_High%": None,
                                          "Pct_From_52W_Low%": None}))
        self.assertAlmostEqual(rng["from_high_pct"], -8.0, places=1)
        self.assertAlmostEqual(rng["from_low_pct"], 84.0, places=1)

    def test_scan_columns_win_over_derivation(self):
        rng = T.compute_52w_range(_row(**{"Current Price": 92.0,
                                          "52W High": 100.0, "52W Low": 50.0,
                                          "Dist_52W_High%": -7.5}))
        self.assertEqual(rng["from_high_pct"], -7.5)

    def test_missing_range_degrades_to_none(self):
        rng = T.compute_52w_range({"Current Price": 10.0})
        self.assertIsNone(rng["position_pct"])
        self.assertIsNone(rng["high"])

    def test_a_degenerate_range_does_not_divide_by_zero(self):
        rng = T.compute_52w_range(_row(**{"Current Price": 50.0,
                                          "52W High": 50.0, "52W Low": 50.0}))
        self.assertIsNone(rng["position_pct"])


class TestSupportLadder(unittest.TestCase):
    def test_s1_to_s4_are_a_fixed_ladder(self):
        # Fixed, not "nearest support" — a column is only comparable down the
        # page if S3 means the 50 MA on every row.
        self.assertEqual([s for s, _k, _n in T.SUPPORT_SLOTS],
                         ["S1", "S2", "S3", "S4"])
        self.assertEqual([k for _s, k, _n in T.SUPPORT_SLOTS],
                         ["8EMA", "21EMA", "50MA", "200MA"])

    def test_by_level_carries_every_rung(self):
        p = T.compute_pullback(_row())
        for _slot, key, _name in T.SUPPORT_SLOTS:
            self.assertIn(key, p["by_level"])
            self.assertIsNotNone(p["by_level"][key]["distance_pct"])

    def test_held_follows_the_sign_not_the_tolerance(self):
        # Price far above the 200 MA still HOLDS it, even though it is too
        # far away to be a supporting entry.
        p = T.compute_pullback(_row(**{"Current Price": 100.0, "200MA": 50.0}))
        lv = p["by_level"]["200MA"]
        self.assertTrue(lv["held"])
        self.assertFalse(lv["supporting"])
        self.assertAlmostEqual(lv["distance_pct"], 100.0, places=1)

    def test_a_lost_level_reads_as_not_held(self):
        p = T.compute_pullback(_row(**{"Current Price": 90.0, "50MA": 100.0}))
        lv = p["by_level"]["50MA"]
        self.assertFalse(lv["held"])
        self.assertLess(lv["distance_pct"], 0)

    def test_a_missing_level_is_none_not_zero(self):
        p = T.compute_pullback(_row(**{"200MA": None}))
        self.assertIsNone(p["by_level"]["200MA"]["distance_pct"])
        self.assertIsNone(p["by_level"]["200MA"]["held"])


class TestSortableDraggableTable(unittest.TestCase):
    def setUp(self):
        from stockanalysis.webapp import longterm_view
        self.view = longterm_view
        self.html = longterm_view._row(E.evaluate(_row()))

    def test_columns_cover_both_verdicts_and_both_levels(self):
        keys = [c[0] for c in self.view._COLUMNS]
        for key in ("investment", "entry_score", "buyzone", "resistance",
                    "support"):
            self.assertIn(key, keys)

    def test_every_cell_carries_a_column_key_and_sort_value(self):
        # The JS finds cells by data-col rather than by index, so a reordered
        # table still sorts the right column.
        for key, _label, _align, _type in self.view._COLUMNS:
            self.assertIn(f'data-col="{key}"', self.html)
        self.assertEqual(self.html.count('data-sort='),
                         len(self.view._COLUMNS))

    def test_detail_row_spans_every_column(self):
        # A stale colspan silently narrows the reasoning panel when columns
        # are added.
        self.assertIn(f'colspan="{len(self.view._COLUMNS)}"', self.html)

    def test_rows_are_tagged_so_pairs_move_together(self):
        self.assertIn('data-main="1"', self.html)
        self.assertIn('data-detail="1"', self.html)

    def test_a_custom_order_reorders_the_cells(self):
        order = ["action", "ticker", "lt"]
        html = self.view._row(E.evaluate(_row()), order=order)
        positions = [html.index(f'data-col="{k}"') for k in order]
        self.assertEqual(positions, sorted(positions))

    def test_better_always_sorts_higher(self):
        # Descending on any ranked column must put the good ones on top.
        self.assertGreater(self.view._ACTION_RANK["BUY NOW"],
                           self.view._ACTION_RANK["AVOID"])
        self.assertGreater(self.view._BAND_RANK["UNDERVALUED"],
                           self.view._BAND_RANK["OVERVALUED"])
        self.assertGreater(self.view._TREND_RANK["CONFIRMED"],
                           self.view._TREND_RANK["BROKEN"])
        self.assertGreater(self.view._TREND_RANK["PARTIAL"],
                           self.view._TREND_RANK["IMPAIRED"])
        self.assertGreater(self.view._TREND_RANK["IMPAIRED"],
                           self.view._TREND_RANK["BROKEN"])

    def test_missing_values_emit_an_empty_sort_key(self):
        # The JS pins empty data-sort to the bottom in both directions; a "0"
        # here would rank a ticker with no 200 MA as the worst 200 MA support.
        html = self.view._row(E.evaluate(_row(**{"S1": None, "R1": None,
                                                 "8EMA": None, "21EMA": None,
                                                 "50MA": None, "200MA": None,
                                                 "Prior_Breakout_Level": None})))
        self.assertIn('data-col="buyzone" data-sort=""', html)


class TestBuyZoneLevel(unittest.TestCase):
    """technicals.compute_buy_zone_level — the price to work an order at."""

    def test_a_volume_confirmed_shelf_is_actual_support(self):
        bz = T.compute_buy_zone_level(
            _row(**{"Current Price": 100.0, "S1": 96.0, "Touches": 42,
                    "Volume_Confirmation": True}))
        self.assertTrue(bz["actual_support"])
        self.assertEqual(bz["source"], "volume_shelf")
        self.assertEqual(bz["price"], 96.0)
        self.assertAlmostEqual(bz["distance_pct"], -4.0, places=1)
        self.assertIn("42 touches", bz["label"])

    def test_an_unconfirmed_shelf_is_still_a_level_but_not_confirmed(self):
        bz = T.compute_buy_zone_level(
            _row(**{"Current Price": 100.0, "S1": 96.0, "Touches": 4,
                    "Volume_Confirmation": False}))
        self.assertEqual(bz["source"], "volume_shelf")
        self.assertFalse(bz["actual_support"])

    def test_it_falls_back_to_the_nearest_moving_average(self):
        bz = T.compute_buy_zone_level(
            _row(**{"Current Price": 100.0, "S1": None, "8EMA": 97.0,
                    "21EMA": 94.0, "50MA": 90.0, "200MA": 80.0,
                    "Prior_Breakout_Level": None}))
        self.assertEqual(bz["source"], "moving_average")
        self.assertEqual(bz["price"], 97.0)
        self.assertEqual(bz["label"], "8 EMA")

    def test_a_derived_level_never_claims_to_be_support(self):
        # The distinction the column exists to preserve: roughly a third of
        # the library has no tested level, and a moving average nobody has
        # defended must not be presented in the same voice as one they have.
        bz = T.compute_buy_zone_level(
            _row(**{"Current Price": 100.0, "S1": None, "50MA": 90.0}))
        self.assertFalse(bz["actual_support"])
        self.assertIn("not", bz["note"].lower())

    def test_a_level_above_the_price_is_not_a_buy_zone(self):
        # Overhead resistance, not somewhere to leave a bid.
        bz = T.compute_buy_zone_level(
            _row(**{"Current Price": 100.0, "S1": 110.0, "8EMA": 105.0,
                    "21EMA": 106.0, "50MA": 107.0, "200MA": 108.0,
                    "Prior_Breakout_Level": None}))
        self.assertIsNone(bz["price"])

    def test_it_is_attached_to_the_pullback_result(self):
        self.assertIn("buy_zone", T.compute_pullback(_row()))


class TestColumns(unittest.TestCase):
    def setUp(self):
        from stockanalysis.webapp import longterm_view
        self.view = longterm_view

    def test_the_ma_distance_columns_moved_to_the_reasoning_panel(self):
        # Reference prices, not judgments — four columns of noise before a
        # name is worth looking at.
        keys = [c[0] for c in self.view._COLUMNS]
        for gone in ("s1", "s2", "s3", "s4"):
            self.assertNotIn(gone, keys)
        html = self.view._levels_panel(E.evaluate(_row()))
        for label in ("8 EMA", "21 EMA", "50 MA", "200 MA"):
            self.assertIn(label, html)

    def test_price_support_and_resistance_are_columns(self):
        keys = [c[0] for c in self.view._COLUMNS]
        for key in ("price", "buyzone", "resistance"):
            self.assertIn(key, keys)
        labels = {c[0]: c[1] for c in self.view._COLUMNS}
        self.assertEqual(labels["buyzone"], "S1 \u00b7 Support")
        self.assertEqual(labels["resistance"], "R1 \u00b7 Resistance")

    def test_the_company_and_timing_verdicts_are_separate_columns(self):
        # The whole point: "excellent company" and "poor entry" are
        # different findings and one blended score cannot hold both.
        keys = [c[0] for c in self.view._COLUMNS]
        self.assertIn("investment", keys)
        self.assertIn("entry_score", keys)
        self.assertNotIn("lt", keys)

    def test_every_column_still_renders_a_cell(self):
        html = self.view._row(E.evaluate(_row()))
        for key, _l, _a, _t in self.view._COLUMNS:
            self.assertIn(f'data-col="{key}"', html)
        self.assertIn(f'colspan="{len(self.view._COLUMNS)}"', html)

    def _conf(self, **kw):
        return T.compute_support_confluence(_row(**kw))

    def test_the_band_boundary_is_the_buy_gate(self):
        # "Adequate" starts exactly where the engine starts issuing buys.
        floors = {name: floor for floor, name in T.CONFLUENCE_BANDS}
        self.assertEqual(floors["🟡 Adequate"], E.MIN_CONFLUENCE_HITS)

    def test_label_follows_the_count_not_the_score(self):
        # Two hits worth 50 points (50 MA + 200 MA) and two worth 25
        # (8/21 EMA + key level) must carry the SAME label.
        # ATR 3% -> tolerance 4.5%, wide enough for both MAs to count.
        heavy = self._conf(**{"Current Price": 100.0, "8EMA": 120.0,
                              "21EMA": 121.0, "50MA": 99.0, "200MA": 98.0,
                              "S1": None, "Prior_Breakout_Level": None,
                              "ATR_Pct": 3.0})
        light = self._conf(**{"Current Price": 100.0, "8EMA": 99.5,
                              "21EMA": 99.0, "50MA": 60.0, "200MA": 50.0,
                              "S1": 99.4, "Volume_Confirmation": None,
                              "Prior_Breakout_Level": None, "ATR_Pct": 3.0})
        self.assertEqual(heavy["agreeing"], 2)
        self.assertEqual(light["agreeing"], 2)
        self.assertEqual(heavy["label"], light["label"])
        # ...while the score still separates them for ranking.
        self.assertGreater(heavy["score"], light["score"])

    def test_every_band_is_reachable(self):
        seen = set()
        for n in range(0, 6):
            label = next(name for floor, name in T.CONFLUENCE_BANDS
                         if n >= floor)
            seen.add(label)
        self.assertEqual(seen, {name for _f, name in T.CONFLUENCE_BANDS})



class TestResistanceLevel(unittest.TestCase):
    """technicals.compute_resistance_level — the first thing overhead."""

    def test_a_tested_r1_wins(self):
        rz = T.compute_resistance_level(
            _row(**{"Current Price": 100.0, "R1": 108.0, "S1": 99.0,
                    "Touches": 55}))
        self.assertTrue(rz["actual_resistance"])
        self.assertEqual(rz["price"], 108.0)
        self.assertAlmostEqual(rz["distance_pct"], 8.0, places=1)

    def test_it_falls_back_to_the_nearest_average_above_price(self):
        rz = T.compute_resistance_level(
            _row(**{"Current Price": 100.0, "R1": None, "8EMA": 104.0,
                    "21EMA": 110.0, "50MA": 120.0, "200MA": 130.0,
                    "52W High": 200.0}))
        self.assertEqual(rz["source"], "moving_average")
        self.assertEqual(rz["price"], 104.0)
        self.assertFalse(rz["actual_resistance"])

    def test_an_uptrend_falls_back_to_the_52_week_high(self):
        """Every average sits BELOW a stock in a clean uptrend.

        Without this rung the column is blank for exactly the names worth
        owning — NVDA, MSFT and GILD all have nothing overhead but the high.
        """
        rz = T.compute_resistance_level(
            _row(**{"Current Price": 100.0, "R1": None, "8EMA": 98.0,
                    "21EMA": 95.0, "50MA": 90.0, "200MA": 80.0,
                    "Prior_Breakout_Level": 85.0, "52W High": 112.0}))
        self.assertEqual(rz["source"], "52w_high")
        self.assertEqual(rz["price"], 112.0)
        self.assertFalse(rz["actual_resistance"])

    def test_nothing_overhead_at_new_highs(self):
        rz = T.compute_resistance_level(
            _row(**{"Current Price": 100.0, "R1": None, "8EMA": 98.0,
                    "21EMA": 95.0, "50MA": 90.0, "200MA": 80.0,
                    "Prior_Breakout_Level": None, "52W High": 100.0}))
        self.assertIsNone(rz["price"])

    def test_a_level_below_price_is_not_resistance(self):
        rz = T.compute_resistance_level(
            _row(**{"Current Price": 100.0, "R1": 90.0, "8EMA": 105.0,
                    "21EMA": 106.0, "50MA": 107.0, "200MA": 108.0}))
        self.assertEqual(rz["source"], "moving_average")

    def test_it_is_attached_to_the_pullback_result(self):
        self.assertIn("resistance", T.compute_pullback(_row()))


class TestTouchAttribution(unittest.TestCase):
    """Touches/Volume_Confirmation describe whichever level is NEAREST.

    core.key_levels writes them for `nearest = s1 if (price - s1) <= (r1 -
    price) else r1`. Crediting them to S1 unconditionally makes a support
    shelf look better tested than it is whenever resistance is closer —
    which is the real WDC case: 329 touches belong to R1 at $454.48, not to
    the $420.26 shelf.
    """

    def test_touches_go_to_whichever_level_is_nearer(self):
        # R1 nearer: 454.48 - 438.40 = 16.08 vs 438.40 - 420.26 = 18.14
        wdc = _row(**{"Current Price": 438.40, "S1": 420.26, "R1": 454.48,
                      "Touches": 329, "Volume_Confirmation": True})
        self.assertEqual(T._touches_belong_to(wdc), "R1")
        self.assertIsNone(T.compute_buy_zone_level(wdc)["touches"])
        self.assertEqual(T.compute_resistance_level(wdc)["touches"], 329)

    def test_support_keeps_the_touches_when_it_is_nearer(self):
        row = _row(**{"Current Price": 100.0, "S1": 99.0, "R1": 130.0,
                      "Touches": 42, "Volume_Confirmation": True})
        self.assertEqual(T._touches_belong_to(row), "S1")
        bz = T.compute_buy_zone_level(row)
        self.assertEqual(bz["touches"], 42)
        self.assertTrue(bz["actual_support"])

    def test_an_unowned_touch_count_never_confirms_the_shelf(self):
        # The bug this guards: a shelf reading "volume-confirmed" on the
        # strength of a resistance level's volume.
        wdc = _row(**{"Current Price": 438.40, "S1": 420.26, "R1": 454.48,
                      "Touches": 329, "Volume_Confirmation": True})
        self.assertFalse(T.compute_buy_zone_level(wdc)["actual_support"])


class TestLongTermScreening(unittest.TestCase):
    """core.longterm.screen — rules over the engine's own columns."""

    def setUp(self):
        from stockanalysis.core.longterm import screen as LS
        self.LS = LS
        self.results = [
            E.evaluate(_row(Ticker="ELITE")),
            E.evaluate(_row(Ticker="WEAK", FCF_Positive=False,
                            DebtToEquity=400.0, CurrentRatio=0.6,
                            **{"Revenue": -5.0, "EPS_Growth%": -20.0,
                               "ReturnOnEquity%": 2.0, "OperatingMargin%": 1.0,
                               "GrossMargin%": 8.0, "FCF_Margin%": -5.0})),
        ]

    def test_it_reuses_the_screener_engine_not_a_second_one(self):
        from stockanalysis.core import screener as S
        # Resolvable by the shared rule engine...
        self.assertIn("lquality", S.FIELD_BY_KEY)
        # ...but absent from the /screener picker, whose universe has no
        # values for these fields — every rule would read "no data".
        self.assertNotIn("lquality", {f.key for f in S.FIELDS})

    def test_flatten_turns_a_nested_verdict_into_scalars(self):
        flat = self.LS.flatten(self.results[0])
        for key in ("lquality", "lq_tier", "valuation_band", "trend_state",
                    "stage", "s1_price", "r1_price", "readiness", "action"):
            self.assertIn(key, flat)
        self.assertNotIsInstance(flat["lquality"], dict)
        self.assertIs(flat["_result"], self.results[0])

    def test_every_declared_field_is_produced_by_flatten(self):
        # A field in the picker that flatten never writes would read
        # "no data" for every row — an option that cannot match anything.
        flat = self.LS.flatten(self.results[0])
        for spec in self.LS.LONGTERM_FIELDS:
            self.assertIn(spec.src, flat, f"{spec.key} has no value")

    def test_a_numeric_rule_filters(self):
        kept, conds, _ = self.LS.apply_rules(self.results, ["lquality:gte:85"])
        self.assertEqual([r["ticker"] for r in kept], ["ELITE"])
        self.assertEqual(len(conds), 1)

    def test_rules_combine_with_and(self):
        kept, _, _ = self.LS.apply_rules(
            self.results, ["lquality:gte:85", "lq_tier:eq:Elite"])
        self.assertEqual([r["ticker"] for r in kept], ["ELITE"])

    def test_rules_combine_with_or(self):
        kept, _, _ = self.LS.apply_rules(
            self.results, ["lquality:gte:85", "lquality:lt:0"], op="OR")
        self.assertEqual([r["ticker"] for r in kept], ["ELITE"])

    def test_an_unparseable_rule_drops_itself(self):
        # A pasted URL with one bad rule must not error the page.
        for bad in ("nosuchfield:gte:5", "lquality:nosuchop:5",
                    "lquality:gte:notanumber", "garbage", ""):
            kept, conds, _ = self.LS.apply_rules(self.results, [bad])
            self.assertEqual(conds, [], bad)
            self.assertEqual(len(kept), len(self.results), bad)

    def test_a_bool_rule_reads_true_and_false(self):
        self.assertIs(self.LS.parse_rule("s1_tested:eq:true").value, True)
        self.assertIs(self.LS.parse_rule("s1_tested:eq:false").value, False)

    def test_between_needs_both_bounds(self):
        self.assertIsNone(self.LS.parse_rule("lquality:between:90"))
        cond = self.LS.parse_rule("lquality:between:90,100")
        self.assertEqual((cond.value, cond.value2), (90.0, 100.0))

    def test_a_rule_round_trips_through_its_url_text(self):
        from stockanalysis.webapp import longterm_view as V
        for text in ("lquality:gte:85", "lq_tier:eq:Elite",
                     "s1_tested:eq:true", "lquality:between:90,100"):
            cond = self.LS.parse_rule(text)
            self.assertEqual(V._rule_text(cond), text)

    def test_stats_name_the_binding_constraint(self):
        _, _, stats = self.LS.apply_rules(
            self.results, ["lquality:gte:85", "lq_tier:eq:Elite"])
        self.assertEqual(len(stats), 2)
        for st in stats:
            for key in ("alone", "missing", "without", "label"):
                self.assertIn(key, st)

    def test_headroom_is_none_when_the_levels_do_not_straddle(self):
        # Support above the price, or resistance below it, would invert the
        # ratio's meaning rather than merely making it large.
        flat = self.LS.flatten(E.evaluate(
            _row(**{"Current Price": 100.0, "S1": 120.0, "R1": 130.0,
                    "8EMA": 121.0, "21EMA": 122.0, "50MA": 123.0,
                    "200MA": 124.0, "Prior_Breakout_Level": None})))
        self.assertIsNone(flat["headroom_ratio"])

    def test_headroom_is_the_ratio_when_they_do_straddle(self):
        flat = self.LS.flatten(E.evaluate(
            _row(**{"Current Price": 100.0, "S1": 90.0, "R1": 120.0,
                    "Prior_Breakout_Level": None})))
        # 20% of headroom against 10% of give-back.
        self.assertAlmostEqual(flat["headroom_ratio"], 2.0, places=1)


class TestPresets(unittest.TestCase):
    """Every preset must be able to return something, and say so when it
    cannot yet.

    Three features in this engine were first built with thresholds that were
    empty by construction — the forward DCF, the confluence gate and the
    readiness bands. A preset that returns nothing on every library is
    indistinguishable from a broken one, so the counts in `note` are checked
    against the real thing rather than trusted.
    """

    def setUp(self):
        from stockanalysis.core.longterm import screen as LS
        self.LS = LS

    def test_every_preset_parses_to_valid_conditions(self):
        for preset in self.LS.PRESETS:
            conds = [self.LS.parse_rule(r) for r in preset["rules"]]
            self.assertTrue(all(c is not None for c in conds),
                            f"{preset['key']} has an unparseable rule")

    def test_every_preset_rule_names_a_real_field(self):
        for preset in self.LS.PRESETS:
            for rule in preset["rules"]:
                key = rule.split(":")[0]
                self.assertIn(key, self.LS.LONGTERM_FIELD_BY_KEY,
                              f"{preset['key']} -> unknown field {key}")

    def test_enum_rules_use_a_declared_value(self):
        # "valuation_band:eq:CHEAP" would parse and silently match nothing.
        for preset in self.LS.PRESETS:
            for rule in preset["rules"]:
                key, op, _, value = (rule.split(":", 2) + [""])[:3] + [
                    rule.split(":", 2)[2] if rule.count(":") >= 2 else ""]
                spec = self.LS.LONGTERM_FIELD_BY_KEY.get(key)
                if spec and spec.kind == self.LS.ENUM and op in ("eq", "ne"):
                    self.assertIn(value, spec.values,
                                  f"{preset['key']}: {value} is not a "
                                  f"value of {key}")

    def test_keys_and_groups_are_well_formed(self):
        keys = [p["key"] for p in self.LS.PRESETS]
        self.assertEqual(len(keys), len(set(keys)), "duplicate preset key")
        for preset in self.LS.PRESETS:
            self.assertIn(preset["group"], self.LS.PRESET_GROUPS)
            for field in ("icon", "name", "desc", "rules"):
                self.assertTrue(preset.get(field), f"{preset['key']}.{field}")

    def test_preset_rules_looks_up_by_key(self):
        first = self.LS.PRESETS[0]
        self.assertEqual(self.LS.preset_rules(first["key"]), list(first["rules"]))
        self.assertEqual(self.LS.preset_rules("nope"), [])

    def test_a_preset_actually_filters(self):
        results = [E.evaluate(_row(Ticker="ELITE")),
                   E.evaluate(_row(Ticker="WEAK", **{"Revenue": -5.0,
                                                     "EPS_Growth%": -20.0,
                                                     "ReturnOnEquity%": 2.0,
                                                     "OperatingMargin%": 1.0,
                                                     "GrossMargin%": 8.0,
                                                     "FCF_Margin%": -5.0}))]
        kept, conds, _ = self.LS.apply_rules(
            results, self.LS.preset_rules("quality_at_discount"))
        self.assertEqual(len(conds), 3)
        self.assertNotIn("WEAK", [r["ticker"] for r in kept])

    def test_no_preset_stores_a_hardcoded_count(self):
        """Counts are computed, never written down.

        A recorded count is a claim about a moving target. Splitting
        STAGE4_BREAKDOWN into "confirmed" and "unconfirmed" silently took
        Fallen Quality from 10 matches to 0 while its label still said 10,
        so clicking it returned an empty table.
        """
        for preset in self.LS.PRESETS:
            self.assertNotIn("note", preset, f"{preset['key']} stores a count")

    def test_preset_counts_match_what_applying_the_rules_returns(self):
        """The number on the pill is the number you get when you click it."""
        results = [E.evaluate(_row(Ticker=f"T{i}")) for i in range(3)]
        results[0]["quality"]["score"] = 40      # fails the quality screens
        counts = self.LS.preset_counts(results)
        for preset in self.LS.PRESETS:
            kept, _, _ = self.LS.apply_rules(results, preset["rules"])
            self.assertEqual(counts[preset["key"]], len(kept), preset["key"])

    def test_presets_do_not_pin_themselves_to_a_stage_name(self):
        """Fallen Quality asks "is price below the 200 MA", not "is the
        stage called STAGE4_BREAKDOWN" — so redefining a stage cannot empty
        it again."""
        rules = self.LS.preset_rules("fallen_quality")
        self.assertNotIn("stage", " ".join(rules))
        self.assertIn("lt_pct_vs_200ma:lt:0", rules)

    def test_statement_dependent_presets_are_flagged(self):
        """The four screens that need the annual statements declare it.

        Their fields are 0% covered until a scan runs
        core.longterm.fundamentals, so they return nothing today — not
        because the rules are wrong but because the reverse DCF has no
        inputs. The flag is what lets the UI say that instead of showing a
        bare zero.
        """
        statement_fields = {"implied_growth", "delivered_growth",
                            "growth_gap", "valuation_method",
                            "valuation_confidence"}
        for preset in self.LS.PRESETS:
            uses = {r.split(":")[0] for r in preset["rules"]}
            needs = bool(uses & {"implied_growth", "delivered_growth",
                                 "growth_gap"}) or (
                "valuation_method" in uses)
            if needs:
                self.assertTrue(preset.get("needs_statements"),
                                f"{preset['key']} depends on statement data "
                                f"but is not flagged")


class TestBelow200MASplitsByMeasuredSlope(unittest.TestCase):
    """A breakdown is price below a FALLING 200 MA — not below any 200 MA.

    Meta is the case that exposed it: below its 200 MA with a death cross
    but both slopes unscanned, reported as a confirmed trend breakdown on
    the strength of one inequality. Price under a RISING long-term average
    is a deep correction, and the two call for opposite actions.
    """

    def _below(self, **kw):
        base = {"Current Price": 90.0, "200MA": 100.0, "50MA": 95.0,
                "8EMA": 99.0, "21EMA": 98.0, "Pct_vs_8EMA": -9.1,
                "S1": None, "R1": None, "Prior_Breakout_Level": None}
        base.update(kw)
        return _row(**base)

    def test_unmeasured_slopes_are_unconfirmed_not_broken(self):
        pull = T.compute_pullback(self._below(**{"MA200_Slope%": None,
                                                 "MA50_Slope%": None}))
        self.assertEqual(pull["stage"], "STAGE4_UNCONFIRMED")
        self.assertIn("cannot be said", pull["note"])

    def test_a_falling_200ma_is_a_confirmed_breakdown(self):
        pull = T.compute_pullback(self._below(**{"MA200_Slope%": -2.0,
                                                 "MA50_Slope%": -3.0}))
        self.assertEqual(pull["stage"], "STAGE4_BREAKDOWN")

    def test_a_rising_200ma_is_a_deep_pullback(self):
        pull = T.compute_pullback(self._below(**{"MA200_Slope%": 1.5,
                                                 "MA50_Slope%": 1.0}))
        self.assertEqual(pull["stage"], "STAGE3_DEEP")

    def test_trend_is_impaired_not_broken_without_the_slope(self):
        trend = T.compute_trend(self._below(**{"MA200_Slope%": None,
                                               "MA50_Slope%": None,
                                               "Above_200MA": False}))
        self.assertEqual(trend["state"], "IMPAIRED")
        self.assertIs(trend["pass"], False)   # still not a trend to buy into
        # The summary names what failed AND that the slope is unread, rather
        # than asserting the slopes are missing on every impaired row.
        self.assertIn("unmeasured", trend["summary"])
        self.assertIn("200 MA", trend["summary"])

    def test_trend_is_broken_once_the_slope_confirms_it(self):
        trend = T.compute_trend(self._below(**{"MA200_Slope%": -2.0,
                                               "MA50_Slope%": -2.0,
                                               "Above_200MA": False}))
        self.assertEqual(trend["state"], "BROKEN")


class TestMACluster(unittest.TestCase):
    """Compression around the price — a different question from support."""

    def test_it_counts_levels_on_both_sides(self):
        # Support confluence only counts levels price sits ABOVE; a cluster
        # is about how tightly the averages are wound, either side.
        cluster = T.compute_ma_cluster(
            _row(**{"Current Price": 100.0, "8EMA": 99.4, "21EMA": 100.9,
                    "50MA": 101.3, "200MA": 140.0, "S1": 99.6, "R1": 100.2,
                    "Prior_Breakout_Level": None}))
        self.assertEqual(cluster["count"], 5)
        self.assertIn("Strong", cluster["label"])
        self.assertLess(cluster["span_pct"], 2.5)

    def test_a_far_flung_chart_has_no_cluster(self):
        cluster = T.compute_ma_cluster(
            _row(**{"Current Price": 100.0, "8EMA": 80.0, "21EMA": 70.0,
                    "50MA": 60.0, "200MA": 50.0, "S1": None, "R1": None,
                    "Prior_Breakout_Level": None}))
        self.assertEqual(cluster["count"], 0)

    def test_a_cluster_can_coexist_with_weak_support(self):
        """Meta: five levels inside 1.9%, only two of them beneath price.

        Both readings are correct, and reporting only the support score
        describes a tight coil as an absence.
        """
        row = _row(**{"Current Price": 592.10, "8EMA": 588.38,
                      "21EMA": 597.75, "50MA": 599.62, "200MA": 630.44,
                      "S1": 589.98, "R1": 593.55, "ATR_Pct": 3.88,
                      "Prior_Breakout_Level": None})
        cluster = T.compute_ma_cluster(row)
        conf = T.compute_support_confluence(row)
        self.assertGreaterEqual(cluster["count"], 4)
        self.assertLess(conf["score"], 50)


class TestTwoVerdicts(unittest.TestCase):
    """Company verdict and timing verdict, reported separately."""

    def test_an_elite_business_at_a_bad_price_stays_a_core_holding(self):
        """A demanding price is a reason to wait, not to stop wanting it.

        Valuation is 10% of the company question; at 30% it dragged
        Nvidia at 98 quality out of the top tier, which is the opposite of
        useful — the waiting belongs on the entry side.
        """
        r = E.evaluate(_row(FreeCashFlow=2.0e8,
                            **{"FCF_CAGR%": 3.0, "Revenue_CAGR%": 3.0,
                               "Revenue": 3.0}))
        # Still an ownable tier despite the price — valuation costs about
        # ten points, so a 98 stays CORE and an 88 slips to OWN. What must
        # NOT happen is an elite business falling out of the ownable tiers
        # because it is expensive.
        self.assertIn(r["investment"]["status"], E.OWNABLE_TIERS)
        self.assertIn("price is demanding", r["investment"]["why"])
        self.assertIs(r["investment"]["priced_well"], False)
        self.assertGreaterEqual(r["quality"]["score"], 85)

    def test_quality_and_price_both_fine_is_a_core_holding(self):
        r = E.evaluate(_row())
        self.assertEqual(r["investment"]["status"], "CORE")
        self.assertIs(r["investment"]["priced_well"], True)

    def test_a_weak_business_is_avoid_whatever_the_chart(self):
        r = E.evaluate(_row(**{"Revenue": -5.0, "EPS_Growth%": -20.0,
                               "ReturnOnEquity%": 2.0, "OperatingMargin%": 1.0,
                               "GrossMargin%": 8.0, "FCF_Margin%": -5.0}))
        self.assertEqual(r["investment"]["status"], "REJECT")

    def test_the_two_verdicts_can_disagree(self):
        # The pairing the page exists to show: worth owning, not worth
        # buying today.
        r = E.evaluate(_row(FreeCashFlow=2.0e8,
                            **{"FCF_CAGR%": 3.0, "Revenue_CAGR%": 3.0,
                               "Revenue": 3.0}))
        self.assertIn(r["investment"]["status"], E.OWNABLE_TIERS)
        self.assertEqual(r["action"], "OWN / WAIT FOR PRICE")

    def test_five_component_scores_are_reported_separately(self):
        r = E.evaluate(_row())
        keys = [c["key"] for c in r["components"]]
        self.assertEqual(keys, ["quality", "valuation", "trend", "pullback",
                                "support"])

    def test_thesis_broken_needs_both_halves(self):
        weak = {"Revenue": -5.0, "EPS_Growth%": -20.0, "ReturnOnEquity%": 2.0,
                "OperatingMargin%": 1.0, "GrossMargin%": 8.0,
                "FCF_Margin%": -5.0}
        # Weak business, trend not measurably broken -> plain AVOID.
        self.assertEqual(E.evaluate(_row(**weak))["action"], "AVOID")
        # Weak business AND a falling 200 MA -> the numbers and tape agree.
        broken = dict(weak)
        broken.update({"Current Price": 90.0, "200MA": 100.0, "50MA": 95.0,
                       "MA200_Slope%": -2.0, "MA50_Slope%": -2.0,
                       "Above_200MA": False})
        self.assertEqual(E.evaluate(_row(**broken))["action"], "THESIS BROKEN")


class TestRecoveringTrend(unittest.TestCase):
    """A 50/200 inversion means opposite things either side of the 200 MA.

    Palantir: price $172.01, above its 200 MA at $152.28 and 30% above its
    50 MA at $132.60, with the 50 MA still under the 200 MA. Nothing is
    damaged — the 50 MA is a lagging average that has not yet climbed back
    through the 200 after an earlier decline. That is a golden cross pending,
    not a death cross just struck, and reporting it as "damaged" inverted the
    reading for 49 library rows.
    """

    def _pltr(self, **kw):
        base = {"Current Price": 172.01, "200MA": 152.28, "50MA": 132.60,
                "21EMA": 138.21, "8EMA": 149.26, "Above_200MA": True,
                "MA200_Slope%": None, "MA50_Slope%": None,
                "Price_vs_50MA%": 29.7}
        base.update(kw)
        return _row(**base)

    def test_above_the_200ma_with_a_pending_cross_is_recovering(self):
        trend = T.compute_trend(self._pltr())
        self.assertEqual(trend["state"], "RECOVERING")
        self.assertEqual(trend["structural_failed"], ["50 MA above 200 MA"])

    def test_recovering_does_not_eject_the_name_from_the_ladder(self):
        # Price is above the long-term average, so this is a trend awaiting
        # confirmation rather than one to walk away from.
        self.assertIsNone(T.compute_trend(self._pltr())["pass"])

    def test_below_the_200ma_is_still_impaired(self):
        trend = T.compute_trend(self._pltr(**{"Current Price": 140.0,
                                              "Above_200MA": False}))
        self.assertEqual(trend["state"], "IMPAIRED")
        self.assertIs(trend["pass"], False)

    def test_a_falling_200ma_still_outranks_the_recovery_reading(self):
        trend = T.compute_trend(self._pltr(**{"MA200_Slope%": -2.0}))
        self.assertEqual(trend["state"], "BROKEN")

    def test_recovering_is_only_for_the_cross_not_any_failure(self):
        # Price below the 200 MA AND a crossed pair is not a recovery.
        trend = T.compute_trend(self._pltr(**{"Current Price": 100.0,
                                              "Above_200MA": False}))
        self.assertNotEqual(trend["state"], "RECOVERING")

    def test_the_ranking_places_recovering_between_partial_and_impaired(self):
        from stockanalysis.webapp import longterm_view as V
        rank = V._TREND_RANK
        self.assertGreater(rank["PARTIAL"], rank["RECOVERING"])
        self.assertGreater(rank["RECOVERING"], rank["IMPAIRED"])

    def test_every_state_has_an_icon_summary_and_rank(self):
        from stockanalysis.webapp import longterm_view as V
        for state in T.TREND_STATES:
            self.assertIn(state, T.TREND_ICONS)
            self.assertIn(state, T.TREND_SUMMARY)
            self.assertIn(state, V._TREND_RANK)


class TestTrendSlopeSemantics(unittest.TestCase):
    """What the two slopes are allowed to decide.

    Nvidia drove both fixes here: freshly scanned, with a rising 200 MA and
    a cooling 50 MA, it was reported as a damaged trend AND told that its
    moving-average slopes were unmeasured — while carrying both of them.
    """

    def _nvda(self, **kw):
        base = {"Current Price": 223.96, "200MA": 193.80, "50MA": 206.05,
                "21EMA": 207.73, "8EMA": 212.82, "Above_200MA": True,
                "Price_vs_50MA%": 8.7,
                "MA200_Slope%": 1.22, "MA50_Slope%": -1.45}
        base.update(kw)
        return _row(**base)

    def test_a_cooling_50ma_cannot_break_a_rising_200ma(self):
        # An intermediate average rolling over inside a rising long-term one
        # is the ordinary shape of a buyable pullback.
        trend = T.compute_trend(self._nvda())
        self.assertEqual(trend["state"], "CONFIRMED")

    def test_but_it_still_costs_the_score(self):
        cooling = T.compute_trend(self._nvda())
        rising = T.compute_trend(self._nvda(**{"MA50_Slope%": 2.0}))
        self.assertLess(cooling["score"], rising["score"])
        self.assertIn("50 MA rising", cooling["failed"])

    def test_the_50ma_slope_is_not_structural(self):
        structural = {name for name, _w, s in T._TREND_CHECKS if s}
        self.assertIn("200 MA rising", structural)
        self.assertNotIn("50 MA rising", structural)

    def test_the_summary_never_claims_unmeasured_slopes_it_has(self):
        trend = T.compute_trend(self._nvda(**{"Above_200MA": False,
                                              "Current Price": 150.0,
                                              "MA200_Slope%": 1.0,
                                              "MA50_Slope%": -1.0}))
        self.assertEqual(trend["state"], "IMPAIRED")
        self.assertNotIn("unmeasured", trend["summary"])
        self.assertNotIn("without", trend["summary"])

    def test_a_breakdown_needs_both_averages_pointing_down(self):
        """Microsoft: 200 MA -2.01%, 50 MA +0.91%.

        A falling long-term average with the intermediate one already
        turning up is how every recovery begins; reading only the slower
        average calls it a breakdown.
        """
        recovering = T.compute_trend(self._nvda(**{"MA200_Slope%": -2.01,
                                                   "MA50_Slope%": 0.91}))
        self.assertEqual(recovering["state"], "RECOVERING")
        self.assertIn("50 MA is rising", recovering["summary"])

        broken = T.compute_trend(self._nvda(**{"MA200_Slope%": -1.75,
                                               "MA50_Slope%": -0.08}))
        self.assertEqual(broken["state"], "BROKEN")

    def test_recovering_covers_both_shapes_of_repair(self):
        # (a) price back above the 200 MA, averages still crossed
        crossed = T.compute_trend(
            _row(**{"Current Price": 172.01, "200MA": 152.28, "50MA": 132.60,
                    "21EMA": 138.21, "8EMA": 149.26, "Above_200MA": True,
                    "MA200_Slope%": None, "MA50_Slope%": None}))
        self.assertEqual(crossed["state"], "RECOVERING")
        # (b) the 50 MA turning up under a still-falling 200 MA
        turning = T.compute_trend(self._nvda(**{"MA200_Slope%": -3.84,
                                                "MA50_Slope%": 9.81}))
        self.assertEqual(turning["state"], "RECOVERING")


class TestListFilter(unittest.TestCase):
    """Watchlist / daytrade selection on the /longterm page."""

    def setUp(self):
        from stockanalysis.webapp import api, longterm_view
        self.view = longterm_view
        self.api = api
        self._real_lt = api.longterm
        self._real_lists = api.longterm_lists
        rows = [E.evaluate(_row(Ticker=t))
                for t in ("NVDA", "META", "AMD", "KO")]
        api.longterm = lambda override=None: {
            "rows": rows, "counts": {}, "regime": "FAVORABLE",
            "regime_note": "t", "risk_free_note": "t",
            "coverage": {"total": 4, "ma_slope": 4, "reversal": 4,
                         "statements": 4, "breakout": 4,
                         "needs_rescan": False}}
        api.longterm_lists = lambda: {
            "daytrade": ["NVDA", "META", "AMD", "ZZZZ"],
            "Longterm": ["KO"]}

    def tearDown(self):
        self.api.longterm = self._real_lt
        self.api.longterm_lists = self._real_lists

    def test_a_list_narrows_the_universe(self):
        body, _ = self.view.longterm_page({"list": ["daytrade"]})
        self.assertEqual(body.count('data-main="1"'), 3)
        self.assertNotIn(">KO<", body)

    def test_list_members_with_no_research_page_are_named(self):
        # Same rule as the ticker search: a 4-name list showing 3 rows must
        # say why, or it reads as data loss.
        body, _ = self.view.longterm_page({"list": ["daytrade"]})
        self.assertIn("no research page yet", body)
        self.assertIn("ZZZZ", body)

    def test_a_list_and_a_ticker_search_intersect(self):
        body, _ = self.view.longterm_page({"list": ["daytrade"],
                                           "q": ["NVDA, KO"]})
        # KO is not on the list, so it cannot survive the intersection.
        self.assertEqual(body.count('data-main="1"'), 1)
        self.assertIn(">NVDA<", body)

    def test_an_unknown_list_leaves_the_universe_alone(self):
        body, _ = self.view.longterm_page({"list": ["no-such-list"]})
        self.assertEqual(body.count('data-main="1"'), 4)

    def test_a_chosen_list_is_never_truncated(self):
        # Asking for "daytrade" and being shown the first few silently is
        # worse than a long page.
        body, _ = self.view.longterm_page({"list": ["daytrade"],
                                           "limit": ["1"]})
        self.assertEqual(body.count('data-main="1"'), 3)

    def test_the_list_survives_a_chip_or_preset_click(self):
        body, _ = self.view.longterm_page({"list": ["daytrade"]})
        self.assertIn("list=daytrade", body)

    def test_the_picker_offers_every_non_empty_list(self):
        body, _ = self.view.longterm_page({})
        for name in ("daytrade", "Longterm"):
            self.assertIn(f'<option value="{name}"', body)
        self.assertIn('<option value="">All tickers</option>', body)


class TestRowLimit(unittest.TestCase):
    def setUp(self):
        from stockanalysis.webapp import api, longterm_view
        self.view = longterm_view
        self.api = api
        self._real = api.longterm
        rows = [E.evaluate(_row(Ticker=f"T{i:03d}")) for i in range(120)]
        api.longterm = lambda override=None: {
            "rows": rows, "counts": {}, "regime": "FAVORABLE",
            "regime_note": "t", "risk_free_note": "t",
            "coverage": {"total": 120, "ma_slope": 120, "reversal": 120,
                         "statements": 120, "breakout": 120,
                         "needs_rescan": False}}

    def tearDown(self):
        self.api.longterm = self._real

    def test_the_default_limit_is_actually_the_default(self):
        """Clamping before defaulting made this ten for weeks.

        max(10, min(500, 0)) is 10, so `limit or DEFAULT_LIMIT` could never
        fire and the page showed ten rows while claiming a default of sixty.
        """
        body, _ = self.view.longterm_page({})
        self.assertEqual(body.count('data-main="1"'),
                         self.view.DEFAULT_LIMIT)

    def test_an_explicit_limit_is_honoured(self):
        body, _ = self.view.longterm_page({"limit": ["25"]})
        self.assertEqual(body.count('data-main="1"'), 25)

    def test_a_junk_limit_falls_back_rather_than_erroring(self):
        body, _ = self.view.longterm_page({"limit": ["banana"]})
        self.assertEqual(body.count('data-main="1"'),
                         self.view.DEFAULT_LIMIT)


class TestFCFMarginComesFromStatements(unittest.TestCase):
    """FCF margin must not inherit the broken .info["freeCashflow"].

    Alphabet reported a 5.1% FCF margin beside "compounding +7%/yr, positive
    in 4 of 4 years" — two lines that cannot both describe the same company.
    The margin was $22.7B/$445.9B from .info; the filed statements say
    $164.7B operating cash flow less $91.4B capex = $73.3B, a margin of 18%.
    """

    def setUp(self):
        from stockanalysis.core.longterm import fundamentals as F
        self.F = F

    def _frames(self, fcf, revenue):
        import pandas as pd
        cols = pd.to_datetime(["2025-12-31", "2024-12-31"])
        cash = pd.DataFrame([fcf], index=["Free Cash Flow"], columns=cols)
        inc = pd.DataFrame([revenue], index=["Total Revenue"], columns=cols)
        return cash, inc

    def test_margin_is_computed_from_the_statement_not_info(self):
        cash, inc = self._frames([73.3e9, 72.8e9], [402.5e9, 350.0e9])
        out = self.F.compute_fundamentals(cash, inc)
        self.assertAlmostEqual(out["FCF_Margin%"], 18.2, places=1)
        self.assertIs(out["FCF_Positive"], True)

    def test_both_sides_come_from_the_same_fiscal_year(self):
        # Pairing a statement numerator with a trailing-twelve-month
        # denominator quietly mixes periods.
        cash, inc = self._frames([100e9, 90e9], [500e9, 400e9])
        self.assertEqual(
            self.F.compute_fundamentals(cash, inc)["FCF_Margin%"], 20.0)

    def test_negative_free_cash_flow_reads_as_negative(self):
        cash, inc = self._frames([-5e9, 2e9], [100e9, 90e9])
        out = self.F.compute_fundamentals(cash, inc)
        self.assertIs(out["FCF_Positive"], False)
        self.assertLess(out["FCF_Margin%"], 0)
        self.assertEqual(out["FCF_Positive_Years"], 1)

    def test_no_statements_means_no_margin_rather_than_a_wrong_one(self):
        out = self.F.compute_fundamentals(None, None)
        self.assertIsNone(out["FCF_Margin%"])
        self.assertIsNone(out["FCF_Positive"])

    def test_metrics_no_longer_derives_the_margin_from_info(self):
        import inspect
        from stockanalysis.core import metrics
        src = inspect.getsource(metrics.get_metrics)
        # The only assignment left should be the None placeholder the
        # statements overwrite.
        self.assertNotIn('info.get("freeCashflow")', src)


class TestInvestmentTiersAndNamedWaits(unittest.TestCase):
    """Company tier is fundamentals-driven; the wait says what it waits for."""

    def test_valuation_is_a_tenth_of_the_company_question(self):
        # At 30% an expensive price pulled elite businesses out of the top
        # tier, which reads as "bad investment" when the finding is "bad
        # price". Waiting belongs to the entry side.
        self.assertEqual(E.INVESTMENT_WEIGHTS, (90, 10))

    def test_an_elite_business_survives_a_demanding_price(self):
        elite = _row(**{"EPS_Growth%": 60.0, "Revenue": 40.0,
                        "ReturnOnEquity%": 45.0, "OperatingMargin%": 45.0,
                        "GrossMargin%": 78.0, "FCF_Margin%": 35.0})
        priced = E.evaluate(elite)
        expensive = E.evaluate(dict(elite, FreeCashFlow=2.0e8,
                                    **{"FCF_CAGR%": 3.0, "Revenue_CAGR%": 3.0,
                                       "Revenue": 3.0}))
        self.assertEqual(priced["investment"]["status"], "CORE")
        self.assertIn(expensive["investment"]["status"], E.OWNABLE_TIERS)

    def test_the_four_tiers_are_ordered_and_reachable(self):
        floors = [f for f, _n in E.INVESTMENT_TIERS]
        self.assertEqual(floors, sorted(floors, reverse=True))
        for score, want in ((92, "CORE"), (80, "OWN"), (70, "WATCHLIST"),
                            (40, "REJECT")):
            self.assertEqual(E.investment_tier(score), want)

    def test_each_wait_names_what_it_is_waiting_for(self):
        core = {"status": "CORE"}
        self.assertEqual(E._wait_label(core, "price"), "OWN / WAIT FOR PRICE")
        self.assertEqual(E._wait_label(core, "trend"), "OWN / WAIT FOR TREND")
        self.assertEqual(E._wait_label(core, "entry"), "OWN / WAIT FOR ENTRY")

    def test_a_name_not_worth_owning_gets_no_own_label(self):
        weak = {"status": "REJECT"}
        for reason in ("price", "trend", "entry"):
            self.assertNotIn("OWN", E._wait_label(weak, reason))

    def test_every_action_has_a_colour_label_and_rank(self):
        from stockanalysis.webapp import longterm_view as V
        for action in E.ACTIONS:
            self.assertIn(action, V._ACTION_STYLE, action)
            self.assertIn(action, V._ACTION_SHORT, action)
            self.assertIn(action, V._ACTION_RANK, action)


class TestTrancheSizing(unittest.TestCase):
    """Size follows the entry score, and is stated as % of TARGET position."""

    def test_a_better_entry_earns_more_capital(self):
        sizes = [E.tranche_for(s) for s in (85, 75, 65, 55, 30)]
        self.assertEqual(sizes, [40, 28, 18, 8, 0])
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_a_weak_entry_gets_nothing(self):
        self.assertEqual(E.tranche_for(20), 0)

    def test_it_falls_back_to_the_zone_when_entry_is_unscored(self):
        self.assertEqual(E.tranche_for(None, "50MA"), E.ZONE_TRANCHE["50MA"])

    def test_the_ui_says_of_target_not_bare_tranche(self):
        # "28% tranche" is ambiguous between 28% of this holding and 28% of
        # the portfolio — a difference that matters enormously.
        from stockanalysis.webapp import longterm_view as V
        html = V._row(E.evaluate(_row()))
        self.assertNotIn("% tranche", html)
        if "of target" in html:
            self.assertIn("% of target", html)


class TestEarningsRisk(unittest.TestCase):
    def test_the_bands_run_from_clear_to_imminent(self):
        for days, want in ((45, "Clear"), (20, "Approaching"), (10, "Near"),
                           (3, "Imminent"), (0, "Imminent")):
            self.assertIn(want, E.earnings_risk(days)["label"])

    def test_a_passed_report_is_clear_not_imminent(self):
        self.assertIn("Clear", E.earnings_risk(-4)["label"])

    def test_unknown_stays_unknown(self):
        self.assertIn("Unknown", E.earnings_risk(None)["label"])

    def test_it_rides_along_with_every_verdict(self):
        self.assertIn("earnings_risk", E.evaluate(_row()))
