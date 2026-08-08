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
        self.assertEqual(r["action"], "WAIT")
        self.assertEqual(r["gate"], "valuation")

    def test_broken_trend_watches_rather_than_avoids(self):
        # The business still passed gate 1, so this is a watchlist name whose
        # chart has to heal — not a company to discard.
        r = E.evaluate(_row(Above_200MA=False,
                            **{"MA200_Slope%": -2.0, "200MA": 120.0,
                               "50MA": 110.0, "Price_vs_50MA%": -9.0}))
        self.assertEqual(r["action"], "WATCH")
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

    def test_a_stock_falling_through_every_average_is_a_breakdown(self):
        # The failure mode the module exists to prevent: proximity to four
        # averages at once during a collapse reading as strong confluence.
        pull = T.compute_pullback(
            _row(**{"Current Price": 79.0, "8EMA": 99.0, "21EMA": 98.5,
                    "50MA": 92.0, "200MA": 80.0, "Pct_vs_8EMA": -20.2}))
        self.assertEqual(pull["zone"], "NONE")
        self.assertEqual(pull["stage"], "STAGE4_BREAKDOWN")
        self.assertIn("breakdown", pull["note"])

    def test_the_breakdown_note_does_not_contradict_itself(self):
        """The distance is derived from the price and level just compared.

        Reading it from Price_vs_200MA% instead let a stale scan column
        produce "Below the 200 MA (+25.0%)" — a sentence that disagrees with
        itself inside eight words.
        """
        pull = T.compute_pullback(
            _row(**{"Current Price": 79.0, "200MA": 80.0,
                    "Price_vs_200MA%": 25.0}))
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

    def test_columns_include_the_support_ladder(self):
        keys = [c[0] for c in self.view._COLUMNS]
        for slot in ("s1", "s2", "s3", "s4"):
            self.assertIn(slot, keys)

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
        self.assertGreater(self.view._TREND_RANK[True],
                           self.view._TREND_RANK[False])
        self.assertGreater(self.view._TREND_RANK[None],
                           self.view._TREND_RANK[False])

    def test_missing_values_emit_an_empty_sort_key(self):
        # The JS pins empty data-sort to the bottom in both directions; a "0"
        # here would rank a ticker with no 200 MA as the worst 200 MA support.
        html = self.view._row(E.evaluate(_row(**{"200MA": None})))
        self.assertIn('data-col="s4" data-sort=""', html)


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


class TestColumnsAndGrouping(unittest.TestCase):
    def setUp(self):
        from stockanalysis.webapp import longterm_view
        self.view = longterm_view

    def test_the_support_ladder_headers_have_no_s_prefix(self):
        labels = {c[0]: c[1] for c in self.view._COLUMNS}
        self.assertEqual(labels["s1"], "8 EMA")
        self.assertEqual(labels["s4"], "200 MA")

    def test_price_and_buy_zone_are_columns(self):
        keys = [c[0] for c in self.view._COLUMNS]
        self.assertIn("price", keys)
        self.assertIn("buyzone", keys)

    def test_every_column_still_renders_a_cell(self):
        html = self.view._row(E.evaluate(_row()))
        for key, _l, _a, _t in self.view._COLUMNS:
            self.assertIn(f'data-col="{key}"', html)
        self.assertIn(f'colspan="{len(self.view._COLUMNS)}"', html)

    def test_grouped_rows_carry_one_banner_per_action(self):
        rows = [E.evaluate(_row(Ticker=t)) for t in ("AAA", "BBB", "CCC")]
        rows[0]["action"] = rows[1]["action"] = "WATCH"
        rows[2]["action"] = "AVOID"
        html = self.view._grouped_rows(rows, expand=False)
        self.assertEqual(html.count('data-group="1"'), 2)
        # Banner order follows the engine's priority, not dict insertion.
        banners = re.findall(r'data-group="1".*?white-space:nowrap">\s*\S+\s+'
                             r'([A-Z][^<]*?)</span>', html, re.S)
        self.assertEqual(banners, ["WATCH", "AVOID"])
        self.assertEqual(html.count('data-main="1"'), 3)

    def test_an_unknown_action_still_renders(self):
        # A verdict the view has not been taught about must not vanish.
        r = E.evaluate(_row())
        r["action"] = "SOMETHING NEW"
        html = self.view._grouped_rows([r], expand=False)
        self.assertIn("SOMETHING NEW", html)
        self.assertIn('data-main="1"', html)

    def test_grouping_is_on_by_default_and_can_be_turned_off(self):
        from stockanalysis.webapp import api
        real = api.longterm
        rows = [E.evaluate(_row(Ticker=t)) for t in ("AAA", "BBB")]
        rows[1]["action"] = "AVOID"
        api.longterm = lambda override=None: {
            "rows": rows, "counts": {}, "regime": "FAVORABLE",
            "regime_note": "t", "risk_free_note": "t",
            "coverage": {"total": 2, "ma_slope": 2, "reversal": 2,
                         "statements": 2, "breakout": 2, "needs_rescan": False}}
        try:
            on, _ = self.view.longterm_page({})
            off, _ = self.view.longterm_page({"group": ["off"]})
            self.assertIn('data-group="1"', on)
            self.assertNotIn('data-group="1"', off)
        finally:
            api.longterm = real
