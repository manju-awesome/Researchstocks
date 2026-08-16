"""
Unit tests. No network, no writes to the live database — every test that
touches the store redirects db's paths into a temp directory first.

The tests worth having here are the ones that pin down behaviour which is
easy to regress and expensive to get wrong: unit conversion, negation in
extraction, the evidence caps, the legal hard stop, and dedup. Several of
these encode bugs that were actually hit while building — the storage-tank
false positive, the price timeline not seeding on first sighting, the
double-discounted confidence weights — so they are regression tests, not
decoration.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from findfarms.core import (agriculture, dedup, deal, extract, geo, legal,
                            motivation, price, retirement, units, water)
from findfarms.core.claims import (Claim, ClaimSet, SELLER_CLAIM, SITE_VISIT,
                                   VERIFIED, seller, verified)


class TestUnits(unittest.TestCase):
    def test_compound_acre_gunta(self):
        acres, how = units.parse_area("2 acre 20 gunta")
        self.assertAlmostEqual(acres, 2.5)
        self.assertIn("gunta", how)

    def test_bare_forms(self):
        self.assertAlmostEqual(units.parse_area("3.5 acres")[0], 3.5)
        self.assertAlmostEqual(units.parse_area("30 guntha")[0], 0.75)
        self.assertAlmostEqual(units.parse_area("43560 sq ft")[0], 1.0)

    def test_unreadable_area_is_none_not_a_guess(self):
        self.assertEqual(units.parse_area("a nice big plot")[0], None)
        self.assertEqual(units.parse_area("")[0], None)

    def test_price_scale_words(self):
        self.assertEqual(units.parse_price("45 lakh"), 4_500_000)
        self.assertEqual(units.parse_price("1.8 Cr"), 18_000_000)
        self.assertEqual(units.parse_price("Rs 45,00,000"), 4_500_000)
        # Crore must not be read as lakh — a 100x error.
        self.assertEqual(units.parse_price("2 crore"), 20_000_000)

    def test_price_sanity_catches_missing_scale_word(self):
        # ₹45 total on 2 acres — a dropped "lakh".
        self.assertIsNotNone(units.price_sanity(45, 2))
        # A plausible figure passes.
        self.assertIsNone(units.price_sanity(8_400_000, 2))

    def test_format_area_uses_guntas_below_an_acre(self):
        self.assertIn("gunta", units.format_area(0.75))
        self.assertIn("ac", units.format_area(2.5))


class TestGeo(unittest.TestCase):
    def test_transliteration_variants_fold_together(self):
        for name in ("Mysore", "Mysuru", "mysore city"):
            self.assertEqual(geo.normalise_place(name), "mysuru")
        for name in ("T. Narasipura", "TN Pura", "Tirumakudalu Narasipura"):
            self.assertEqual(geo.normalise_place(name), "t narasipura")

    def test_known_villages_resolve(self):
        r = geo.resolve_location(village="Bannur")
        self.assertIsNotNone(r["lat"])
        self.assertEqual(r["taluk"], "T Narasipura")

    def test_unknown_village_does_not_guess(self):
        r = geo.resolve_location(village="Nowhereville")
        self.assertIsNone(r["lat"])

    def test_distance_bands(self):
        # Hunsur town is genuinely outside the 30 km target; the system must
        # say so rather than flattering the search area.
        r = geo.resolve_location(village="Hunsur")
        d = geo.distances_from_mysuru(r["lat"], r["lon"], r["corridor"])
        self.assertGreater(d["driving_km"], 30)
        self.assertTrue(geo.radius_status(d["driving_km"])[0].startswith("OUTSIDE"))

        r = geo.resolve_location(village="Bannur")
        d = geo.distances_from_mysuru(r["lat"], r["lon"], r["corridor"])
        self.assertEqual(geo.radius_status(d["driving_km"])[0], "PREFERRED")

    def test_swapped_or_wild_coordinates_rejected(self):
        r = geo.resolve_location(village="Bannur", lat=76.86, lon=12.33)
        self.assertNotEqual(r["method"], "listing_coordinates")


class TestMainRoadConnectivity(unittest.TestCase):
    """Distance to a main tarred road — a different question from road
    frontage, and the one that decides monsoon and emergency access."""

    def _m(self, text):
        return extract.extract_listing(f"Bannur 2 acres borewell 300 ft. {text} "
                                       f"40 lakh per acre", "T")

    def test_reads_metres_and_kilometres(self):
        self.assertEqual(self._m("500 meters from main road.").value(
            "main_road_distance_m"), 500)
        self.assertEqual(self._m("1.5 km from highway.").value(
            "main_road_distance_m"), 1500)
        self.assertEqual(self._m("200 mtr from NH 275.").value(
            "main_road_distance_m"), 200)

    def test_frontage_on_a_main_road_is_zero(self):
        cs = self._m("Main road facing, tar road.")
        self.assertEqual(cs.value("main_road_distance_m"), 0)
        self.assertEqual(geo.main_road_band(0)[0], "ON_MAIN_ROAD")

    def test_silence_is_unknown_not_zero(self):
        # Sellers state this when it is good and omit it when it is not, so
        # an absent value must never be read as "on the road".
        cs = self._m("Fenced, red soil.")
        self.assertFalse(cs.get("main_road_distance_m").known)
        self.assertEqual(geo.main_road_band(None)[0], "UNKNOWN")

    def test_route_distance_is_not_an_approach_distance(self):
        # "45 km from Mysore main road" describes the drive to the city, not
        # the parcel's approach.
        cs = self._m("45 km from Mysore main road.")
        self.assertFalse(cs.get("main_road_distance_m").known)

    def test_vague_phrases_read_conservatively(self):
        # The generous reading of a vague phrase is the seller's reading.
        self.assertGreaterEqual(
            self._m("Just off the main road.").value("main_road_distance_m"), 500)
        self.assertGreaterEqual(
            self._m("Interior village land.").value("main_road_distance_m"), 1000)

    def test_unpaved_approach_costs_a_band(self):
        paved, _ = geo.main_road_band(800, "tarred")
        mud, why = geo.main_road_band(800, "unpaved")
        order = [b[1] for b in geo.MAIN_ROAD_BANDS]
        self.assertGreater(order.index(mud), order.index(paved))
        self.assertIn("monsoon", why)

    def test_frontage_does_not_substitute_for_main_road_access(self):
        # A parcel with frontage on a mud lane 2 km from tar must score below
        # one 300 m from a main road — frontage alone is not access.
        from findfarms.core import pipeline
        lane = pipeline.analyse_property(extract.extract_listing(
            "Bannur 2 acres borewell 350 ft coconut, road frontage, mud road, "
            "2 km from main road. 40 lakh per acre", "T"), {})
        near = pipeline.analyse_property(extract.extract_listing(
            "Bannur 2 acres borewell 350 ft coconut, road frontage, tar road, "
            "300 meters from main road. 40 lakh per acre", "T"), {})
        self.assertGreater(near["retirement"]["score"],
                           lane["retirement"]["score"])


class TestAmenities(unittest.TestCase):
    def test_gazetteer_carries_the_new_amenity_kinds(self):
        g = geo.load_gazetteer()
        for kind in ("yoga", "wellness", "school"):
            self.assertTrue(
                any(kind in (p.get("amenities") or []) for p in g["places"]),
                f"no place tagged {kind}")

    def test_nearest_amenities_returns_every_kind(self):
        r = geo.resolve_location(village="Bannur")
        a = geo.nearest_amenities(r["lat"], r["lon"])
        for kind in geo.AMENITY_KINDS:
            self.assertIn(kind, a)
            self.assertIn(f"{kind}_name", a)

    def test_yoga_clusters_in_the_city_not_the_district(self):
        # Gokulam is where Mysuru's shalas actually are, so a city-fringe
        # parcel must read much closer to yoga than a far-taluk one.
        near = geo.resolve_location(village="Bogadi")
        far = geo.resolve_location(village="T Narasipura")
        self.assertLess(geo.nearest_amenities(near["lat"], near["lon"])["yoga"],
                        geo.nearest_amenities(far["lat"], far["lon"])["yoga"])

    def test_yoga_and_schools_cannot_outweigh_water(self):
        # The two lifestyle factors are tie-breakers by design. A parcel with
        # perfect amenity access and no water must never outrank a watered
        # one — if it can, the weights are wrong.
        from findfarms.core import pipeline
        dry_but_central = pipeline.analyse_property(extract.extract_listing(
            "Bogadi 2 acres dry land rain fed, no borewell, tar road, "
            "main road facing. 40 lakh per acre", "T"), {})
        watered_far = pipeline.analyse_property(extract.extract_listing(
            "Bannur 2 acres canal water and open well and borewell 350 ft with "
            "3 phase and pump, coconut, tar road, 300 m from main road. "
            "40 lakh per acre", "T"), {})
        self.assertGreater(watered_far["deal"]["score"],
                           dry_but_central["deal"]["score"])

    def test_retirement_ceiling_is_exactly_100(self):
        # Guards the weight table: if a factor is added without taking points
        # from another, this drifts past 100 and every score silently
        # compresses at the top.
        cs = ClaimSet()
        for k, v in (("road_surface", "tarred"), ("road_frontage", True),
                     ("road_width_ft", 30), ("main_road_distance_m", 0),
                     ("neighbouring_houses", "12 houses"), ("caretaker", True),
                     ("village", "Bogadi"), ("electricity", True),
                     ("mobile_signal", "strong"), ("farmhouse", True)):
            cs.set(k, Claim(value=v, source="site visit", confidence=VERIFIED))
        r = geo.resolve_location(village="Bogadi")
        self.assertEqual(
            retirement.score_retirement(cs, r, 15.0, 100)["score"], 100)


class TestExtraction(unittest.TestCase):
    def test_reads_a_normal_listing(self):
        cs = extract.extract_listing(
            "Bannur 2 acre 20 gunta red soil, 400 feet borewell, 3 phase power, "
            "coconut and mango, 30 ft tar road frontage, 42 lakh per acre, "
            "direct owner 9876543210", source="T")
        self.assertAlmostEqual(cs.value("acres"), 2.5)
        self.assertEqual(cs.value("borewell_depth_ft"), 400)
        self.assertEqual(cs.value("road_width_ft"), 30)
        self.assertEqual(cs.value("village"), "Bannur")
        self.assertTrue(cs.get("owner_direct").truthy())
        self.assertEqual(cs.value("price_per_acre"), 4_200_000)

    def test_negation_inverts_claims(self):
        cs = extract.extract_listing(
            "No borewell, water can be arranged. Barren land, no road frontage.",
            source="T")
        self.assertFalse(cs.get("water_borewell").truthy())
        self.assertTrue(cs.get("water_borewell_absent").truthy())
        self.assertFalse(cs.get("road_frontage").truthy())
        self.assertFalse(cs.get("under_cultivation").truthy())

    def test_crop_names_need_word_boundaries(self):
        # "tur" (a pulse) must not match inside "agricultural".
        cs = extract.extract_listing(
            "Agricultural land for sale 2 acres 30 lakh per acre in Bannur", "T")
        self.assertIsNone(cs.value("crops"))

    def test_storage_tank_is_not_a_water_body(self):
        # Regression: bare "tank" matched "water storage tank" and invented a
        # village irrigation tank, which then scored as a water source.
        cs = extract.extract_listing(
            "2 acres Bannur with borewell 300 ft and water storage tank, "
            "30 lakh per acre", "T")
        self.assertFalse(cs.get("water_lake_tank").truthy())
        self.assertTrue(cs.get("water_storage").truthy())

    def test_everything_extracted_is_a_seller_claim(self):
        cs = extract.extract_listing(
            "Bannur 2 acres clear title no dispute borewell good water "
            "35 lakh per acre", "T")
        for key in ("water_borewell", "acres", "mentions_clear_title"):
            c = cs.get(key)
            if c.known:
                self.assertEqual(c.confidence, SELLER_CLAIM,
                                 f"{key} must not be more than a seller claim")

    def test_village_name_containing_a_keyword_is_not_a_water_source(self):
        # Regression: "kere" (village tank) matched inside "Bilikere", so a
        # dry-land parcel scored points for a water body that was only ever
        # the village's own name.
        cs = extract.extract_listing(
            "Bilikere Hunsur road 4 acres dry land rain fed, no borewell. "
            "18 lakh per acre", "T")
        self.assertFalse(cs.get("water_lake_tank").truthy())
        self.assertEqual(water.score_water(cs)["score"], 0)

    def test_no_dispute_is_not_a_dispute(self):
        # Regression: "no dispute" / "litigation free" are the most common
        # reassurances in these adverts, and each registered AS a risk.
        cs = extract.extract_listing(
            "Bannur 2 acres clear title, no dispute, litigation free, "
            "35 lakh per acre", "T")
        self.assertFalse(cs.get("risk_dispute").truthy())
        self.assertTrue(cs.get("risk_dispute_denied").truthy())

    def test_missing_documents_recorded_as_a_finding(self):
        cs = extract.extract_listing("Bannur 2 acres 35 lakh per acre", "T")
        self.assertTrue(cs.get("no_documents_mentioned").truthy())


class TestClaims(unittest.TestCase):
    def test_unknown_is_not_a_no(self):
        c = Claim.unknown()
        self.assertFalse(c.known)
        self.assertEqual(c.weight, 0.0)

    def test_empty_value_forced_to_unknown(self):
        c = Claim(value="", source="x", confidence=VERIFIED)
        self.assertEqual(c.confidence, "UNKNOWN")

    def test_better_evidence_wins_on_merge(self):
        cs = ClaimSet()
        cs.add("water_sources", seller("borewell", "listing"))
        cs.add("water_sources", verified("canal", "irrigation dept record"))
        self.assertEqual(cs.value("water_sources"), "canal")

    def test_weaker_evidence_does_not_overwrite(self):
        cs = ClaimSet()
        cs.add("water_sources", verified("canal", "irrigation dept record"))
        cs.add("water_sources", seller("borewell", "listing"))
        self.assertEqual(cs.value("water_sources"), "canal")

    def test_equal_evidence_on_stable_field_records_a_conflict(self):
        cs = ClaimSet()
        cs.add("soil", seller("red soil", "portal A"))
        cs.add("soil", seller("black soil", "portal B"))
        self.assertEqual(cs.value("soil"), "red soil")
        self.assertTrue(cs.conflicts())

    def test_volatile_field_takes_the_newer_value(self):
        # Regression: a relisted (lower) price was recorded as a conflict and
        # the stale price stayed on the dashboard while the price-history
        # timeline correctly showed the drop.
        cs = ClaimSet()
        cs.add("price_per_acre", seller(4_200_000, "portal A"))
        cs.add("price_per_acre", seller(3_500_000, "portal B"))
        self.assertEqual(cs.value("price_per_acre"), 3_500_000)


class TestWater(unittest.TestCase):
    def _cs(self, text):
        return extract.extract_listing(text, "T")

    def test_unverified_claims_are_capped(self):
        cs = self._cs("Bannur 2 acres with canal water, open well, borewell 300 "
                      "feet, 3 phase power, pump set, water storage tank, "
                      "drip irrigation. 40 lakh per acre")
        r = water.score_water(cs)
        self.assertTrue(r["capped_by_evidence"])
        self.assertLessEqual(r["score"], water.UNVERIFIED_CAP)

    def test_verification_lifts_the_cap(self):
        cs = self._cs("Bannur 2 acres canal water and open well and borewell "
                      "300 feet with 3 phase power and pump. 40 lakh per acre")
        before = water.score_water(cs)["score"]
        cs.set("water_borewell", Claim(value=True, source="Site visit, pump run",
                                       confidence=SITE_VISIT))
        after = water.score_water(cs)
        self.assertGreater(after["score"], before)
        self.assertFalse(after["capped_by_evidence"])

    def test_river_proximity_is_not_irrigation(self):
        cs = self._cs("2 acres river facing land T Narasipura, Kaveri river 200 "
                      "meters. 38 lakh per acre")
        r = water.score_water(cs)
        self.assertLess(r["score"], 40)
        self.assertTrue(any("NOT an irrigation right" in w for w in r["warnings"]))

    def test_very_deep_borewell_is_a_negative_signal(self):
        shallow = water.score_water(self._cs(
            "Bannur 2 acres borewell 300 feet. 35 lakh per acre"))
        deep = water.score_water(self._cs(
            "Bannur 2 acres borewell 850 feet good water. 35 lakh per acre"))
        self.assertLess(deep["score"], shallow["score"])

    def test_no_water_scores_zero_and_warns(self):
        r = water.score_water(self._cs(
            "Bilikere 4 acres dry land rain fed, no borewell. 18 lakh per acre"))
        self.assertEqual(r["score"], 0)
        self.assertTrue(r["warnings"])

    def test_always_produces_questions_to_ask(self):
        r = water.score_water(self._cs("Bannur 2 acres borewell. 35 lakh per acre"))
        self.assertTrue(any("April" in q for q in r["questions"]))


class TestWatershed(unittest.TestCase):
    """Rivers, rainfall, undulation and harvesting potential."""

    def _ws(self, text):
        from findfarms.core import watershed, geo
        cs = extract.extract_listing(text, "T")
        r = geo.resolve_location(village=cs.value("village"),
                                 taluk=cs.value("taluk"))
        return watershed.score_watershed(cs, r), cs

    def test_river_courses_place_known_towns_correctly(self):
        from findfarms.core import watershed, geo
        # Srirangapatna is an island in the Kaveri; Nanjangud sits on the
        # Kabini; T. Narasipura is the confluence of both. If the polylines
        # are wrong, these three break first.
        srp = geo.resolve_location(village="Srirangapatna")
        njd = geo.resolve_location(village="Nanjangud")
        tnp = geo.resolve_location(village="T Narasipura")
        self.assertLess(watershed.river_distances(srp["lat"], srp["lon"])["kaveri_km"], 2)
        self.assertLess(watershed.river_distances(njd["lat"], njd["lon"])["kabini_km"], 2)
        t = watershed.river_distances(tnp["lat"], tnp["lon"])
        self.assertLess(t["kaveri_km"], 3)
        self.assertLess(t["kabini_km"], 3)

    def test_inland_village_is_far_from_both_rivers(self):
        from findfarms.core import watershed, geo
        r = geo.resolve_location(village="Bilikere")
        d = watershed.river_distances(r["lat"], r["lon"])
        self.assertGreater(d["nearest_km"], 10)

    def test_river_proximity_never_counts_as_irrigation(self):
        # The core rule from water.py must survive this module existing.
        ws, cs = self._ws("T Narasipura 2 acres river facing Kaveri just 200 "
                          "meters, sandy loam. 38 lakh per acre")
        self.assertTrue(any("NOT an irrigation right" in w for w in ws["warnings"]))

    def test_very_close_river_reports_resolution_limit_not_false_precision(self):
        from findfarms.core import watershed
        pts, drivers, warnings, _ = watershed.river_assessment(
            {"nearest_km": 0.0, "nearest": "Kaveri"})
        self.assertTrue(any("below what this data can resolve" in w
                            for w in warnings))
        self.assertFalse(any("0.0 km" in d for d in drivers))

    def test_very_close_river_warns_about_buffer_and_flood(self):
        from findfarms.core import watershed
        _, _, warnings, _ = watershed.river_assessment(
            {"nearest_km": 0.5, "nearest": "Kabini"})
        joined = " ".join(warnings).lower()
        self.assertIn("buffer", joined)
        self.assertIn("flood", joined)

    def test_rainfall_gradient_across_the_district_is_real(self):
        from findfarms.core import watershed
        wet, _, _ = watershed.rainfall_for("H D Kote")
        dry, _, _ = watershed.rainfall_for("T Narasipura")
        self.assertGreater(wet, dry)
        # Unknown taluk falls back to the district default and says so.
        mm, src, note = watershed.rainfall_for("Nowhere")
        self.assertEqual(src, "district default")
        self.assertTrue(note)

    def test_gentle_slope_beats_flat_for_harvesting(self):
        # The counter-intuitive one, and the reason undulation is scored
        # separately from the agriculture terrain reading.
        gentle, _ = self._ws("Bannur 2 acres gentle slope red soil borewell "
                             "350 ft. 40 lakh per acre")
        flat, _ = self._ws("Bannur 2 acres flat land red soil borewell 350 ft. "
                           "40 lakh per acre")
        self.assertGreater(gentle["score"], flat["score"])

    def test_agriculture_and_watershed_disagree_about_undulation(self):
        # Not an inconsistency: undulating land is harder to plough and
        # better at catching water. Both scores must be free to say so.
        from findfarms.core import agriculture, watershed, geo
        undul = extract.extract_listing(
            "Bannur 2 acres undulating red soil borewell 350 ft coconut. "
            "40 lakh per acre", "T")
        flat = extract.extract_listing(
            "Bannur 2 acres flat land red soil borewell 350 ft coconut. "
            "40 lakh per acre", "T")
        r = geo.resolve_location(village="Bannur")
        self.assertGreater(watershed.score_watershed(undul, r)["score"],
                           watershed.score_watershed(flat, r)["score"])
        self.assertGreater(agriculture.score_agriculture(flat, 50)["score"],
                           agriculture.score_agriculture(undul, 50)["score"])

    def test_harvest_volume_arithmetic(self):
        from findfarms.core import watershed
        # 1 acre at 1000 mm = 4046.86 m³ gross, before any runoff coefficient.
        v = watershed.harvest_volumes(1.0, 1000, 0.30)
        self.assertAlmostEqual(v["gross_m3"], 4047, delta=2)
        self.assertAlmostEqual(v["runoff_m3"], 1214, delta=3)
        self.assertAlmostEqual(v["harvestable_m3"], 728, delta=3)
        # Harvestable must always be well under gross — quoting gross is how
        # harvesting potential gets oversold by about four times.
        self.assertLess(v["harvestable_m3"], v["gross_m3"] * 0.5)

    def test_no_acreage_means_no_volume_guess(self):
        from findfarms.core import watershed
        self.assertIsNone(watershed.harvest_volumes(None, 900, 0.3)["gross_m3"])

    def test_harvesting_potential_cannot_fake_present_water(self):
        # A dry parcel with ideal harvesting conditions must still score
        # badly on water — the bonus is capped and applied before the
        # evidence cap for exactly this reason.
        from findfarms.core import pipeline
        dry = pipeline.analyse_property(extract.extract_listing(
            "Bilikere Hunsur road 3 acres undulating red soil, rain fed, "
            "no borewell. 20 lakh per acre", "T"), {})
        self.assertGreater(dry["watershed"]["score"], 45)
        self.assertLess(dry["water"]["score"], 25)

    def test_existing_harvesting_structures_are_extracted(self):
        cs = extract.extract_listing(
            "Jayapura 3 acres with farm pond and contour bunds, recharge pit, "
            "borewell 400 ft. 35 lakh per acre", "T")
        self.assertTrue(cs.get("farm_pond").truthy())
        self.assertTrue(cs.get("contour_bunds").truthy())
        self.assertTrue(cs.get("recharge_pit").truthy())

    def test_recommendations_are_parcel_specific(self):
        ws, _ = self._ws("Bannur 2 acres flat land red soil borewell 350 ft. "
                         "40 lakh per acre")
        joined = " ".join(ws["recommendations"]).lower()
        self.assertIn("pump", joined)          # flat land needs pumping back
        self.assertIn("recharge pit", joined)  # has a borewell, no recharge

    def test_sellers_river_claim_is_kept_separate_from_the_computed_one(self):
        _, cs = self._ws("T Narasipura 2 acres, Kaveri river just 200 meters "
                         "away, borewell. 38 lakh per acre")
        self.assertTrue(cs.get("seller_stated_river_distance").known)
        self.assertEqual(cs.get("seller_stated_river_distance").confidence,
                         SELLER_CLAIM)


class TestLegal(unittest.TestCase):
    def test_ptcl_grant_land_is_a_hard_stop(self):
        cs = extract.extract_listing(
            "Cheap land Bannur 2 acres grant land granted under PTCL, borewell, "
            "only 24 lakh per acre urgent", "T")
        r = legal.screen_legal(cs)
        self.assertEqual(r["level"], legal.HIGH)
        self.assertTrue(r["hard_stop"])

    def test_no_information_means_unknown_not_low(self):
        cs = extract.extract_listing("Bannur 2 acres 35 lakh per acre", "T")
        self.assertEqual(legal.screen_legal(cs)["level"], legal.UNKNOWN)

    def test_advertised_clear_title_does_not_lower_risk(self):
        cs = extract.extract_listing(
            "Bannur 2 acres clear title, no dispute, litigation free, "
            "35 lakh per acre", "T")
        self.assertEqual(legal.screen_legal(cs)["level"], legal.UNKNOWN)

    def test_low_requires_verified_documents(self):
        cs = extract.extract_listing("Bannur 2 acres 35 lakh per acre", "T")
        for f in ("mentions_rtc", "mentions_ec", "mentions_mutation",
                  "mentions_sale_deed"):
            cs.set(f, Claim(value=True, source="read by lawyer",
                            confidence=VERIFIED))
        self.assertEqual(legal.screen_legal(cs)["level"], legal.LOW)

    def test_always_states_what_it_did_not_check(self):
        r = legal.screen_legal(extract.extract_listing("Bannur 2 acres 35L", "T"))
        self.assertTrue(r["not_checked"])
        self.assertIn("NOT LEGAL ADVICE", r["disclaimer"])


class TestDealGates(unittest.TestCase):
    def _analyse(self, text):
        from findfarms.core import pipeline
        return pipeline.analyse_property(extract.extract_listing(text, "T"), {})

    def test_legal_hard_stop_overrides_everything_good(self):
        a = self._analyse(
            "Bannur 2 acres grant land under PTCL. Canal water, open well, "
            "borewell 300 ft, coconut and mango, tar road frontage, fenced, "
            "3 phase power. Only 20 lakh per acre, urgent sale.")
        self.assertEqual(a["deal"]["status"], deal.DO_NOT_PROCEED)
        self.assertEqual(a["deal"]["category"], "E")
        self.assertEqual(a["alert"]["level"], deal.REJECT)

    def test_unknown_legal_caps_the_score(self):
        a = self._analyse(
            "Bannur 2 acres canal water, open well, borewell 300 ft with 3 phase "
            "and pump, coconut and mango fully cultivated, 30 ft tar road "
            "frontage, fenced, farm house. 35 lakh per acre.")
        self.assertEqual(a["legal"]["level"], legal.UNKNOWN)
        self.assertLessEqual(a["deal"]["score"], deal.UNKNOWN_LEGAL_CAP)

    def test_weak_water_caps_the_deal(self):
        a = self._analyse(
            "Bilikere 3 acres dry land rain fed no borewell, tar road frontage, "
            "fenced, flat land, red soil. 15 lakh per acre.")
        self.assertLessEqual(a["deal"]["score"], deal.WATER_FLOOR_CAP)

    def test_size_outside_range_is_flagged_not_silently_dropped(self):
        a = self._analyse("Bannur 40 acres borewell 300 ft. 20 lakh per acre.")
        self.assertTrue(any("outside the 0.5" in g for g in a["deal"]["gates"]))


class TestPrice(unittest.TestCase):
    def test_refuses_a_verdict_below_three_comparables(self):
        subject = extract.extract_listing("Bannur 2 acres 40 lakh per acre", "T")
        r = price.analyse_price(subject, {})
        self.assertEqual(r["position"], "UNKNOWN")
        self.assertIn("not a market", r["rationale"])

    def test_gives_a_verdict_with_enough_comparables(self):
        props = {}
        for i, ppa in enumerate((40, 42, 44, 46)):
            cs = extract.extract_listing(
                f"Bannur 2 acres borewell 300 ft. {ppa} lakh per acre. "
                f"98000111{i}{i}", "T")
            props[f"p{i}"] = {"claims": cs.to_dict()}
        cheap = extract.extract_listing("Bannur 2 acres borewell 300 ft. "
                                        "30 lakh per acre. 9800099999", "T")
        r = price.analyse_price(cheap, props)
        self.assertEqual(r["position"], "CHEAP")
        self.assertGreaterEqual(len(r["comparables"]), 3)

    def test_cheap_carries_a_warning_rather_than_praise(self):
        props = {}
        for i, ppa in enumerate((40, 42, 44, 46)):
            cs = extract.extract_listing(
                f"Bannur 2 acres borewell 300 ft. {ppa} lakh per acre. "
                f"98000111{i}{i}", "T")
            props[f"p{i}"] = {"claims": cs.to_dict()}
        r = price.analyse_price(extract.extract_listing(
            "Bannur 2 acres borewell 300 ft. 28 lakh per acre. 9800099999", "T"),
            props)
        self.assertTrue(any("title, water or access" in w for w in r["warnings"]))


class TestDedup(unittest.TestCase):
    def test_same_parcel_across_portals_matches(self):
        a = extract.extract_listing(
            "Bannur 2.5 acres borewell 400 ft coconut trees 42 lakh per acre "
            "owner 9876543210", "MagicBricks")
        b = extract.extract_listing(
            "Farm land Bannur 2 acre 20 gunta with borewell 400 feet and "
            "coconut. Rate 42L per acre. Call 98765 43210", "Broker")
        score, reasons = dedup.match_score(a, b)
        self.assertGreaterEqual(score, dedup.MERGE_THRESHOLD)
        self.assertTrue(reasons)

    def test_same_broker_different_parcels_do_not_merge(self):
        a = extract.extract_listing(
            "Bannur 2.5 acres borewell 42 lakh per acre 9876543210", "MB")
        b = extract.extract_listing(
            "Nanjangud 8 acres canal water sugarcane 30 lakh per acre 9876543210",
            "MB")
        score, _ = dedup.match_score(a, b)
        self.assertLess(score, dedup.MERGE_THRESHOLD)

    def test_price_change_does_not_change_the_canonical_id(self):
        a = extract.extract_listing(
            "Bannur 2.5 acres borewell 400 ft 42 lakh per acre 9876543210", "T")
        b = extract.extract_listing(
            "Bannur 2.5 acres borewell 400 ft 35 lakh per acre 9876543210", "T")
        self.assertEqual(dedup.canonical_id(a), dedup.canonical_id(b))

    def test_far_apart_coordinates_disqualify(self):
        a = ClaimSet(); a.add("latitude", seller(12.33)); a.add("longitude", seller(76.86))
        b = ClaimSet(); b.add("latitude", seller(12.10)); b.add("longitude", seller(76.35))
        score, _ = dedup.match_score(a, b)
        self.assertEqual(score, 0.0)


class TestStore(unittest.TestCase):
    """Store tests redirect every path into a temp dir — nothing here ever
    touches the real data/ directory."""

    def setUp(self):
        from findfarms.store import db
        self.db = db
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._saved = (db.PROPERTIES_PATH, db.OBSERVATIONS_PATH,
                       db.PRICE_HISTORY_PATH, db.ALERTS_PATH)
        db.PROPERTIES_PATH = d / "properties.json"
        db.OBSERVATIONS_PATH = d / "observations.json"
        db.PRICE_HISTORY_PATH = d / "price_history.json"
        db.ALERTS_PATH = d / "alerts.json"

    def tearDown(self):
        (self.db.PROPERTIES_PATH, self.db.OBSERVATIONS_PATH,
         self.db.PRICE_HISTORY_PATH, self.db.ALERTS_PATH) = self._saved
        self.tmp.cleanup()

    def test_rediscovery_updates_rather_than_inserting(self):
        from findfarms.core import pipeline
        pipeline.ingest("Bannur 2.5 acres borewell 400 ft coconut 42 lakh per "
                        "acre owner 9876543210", "MagicBricks", "http://a/1")
        pipeline.ingest("Bannur 2 acre 20 gunta borewell 400 feet coconut 42L "
                        "per acre 98765 43210", "Broker", "http://b/2")
        self.assertEqual(len(self.db.load_properties()), 1)

    def test_price_drop_recorded_on_the_second_sighting(self):
        # Regression: the timeline was only seeded on a merge, so the opening
        # price was lost and a two-sighting drop recorded nothing.
        from findfarms.core import pipeline
        pipeline.ingest("Jayapura 2 acres borewell 420 ft coconut 36 lakh per "
                        "acre owner 9845099887", "A", "http://a/1")
        pipeline.ingest("Jayapura 2 acre borewell 420 feet coconut reduced "
                        "30 lakh per acre 98450 99887", "B", "http://b/2")
        drops = pipeline.price_drops()
        self.assertEqual(len(drops), 1)
        self.assertAlmostEqual(drops[0]["drop_pct"], 16.7, places=0)

    def test_verification_moves_the_scores(self):
        from findfarms.core import pipeline
        r = pipeline.ingest(
            "Bannur 2.5 acres borewell 400 ft with 3 phase and pump, coconut "
            "and mango, tar road frontage, fenced. 42 lakh per acre. "
            "Owner 9876543210", "T", "http://a/1")
        pid = r["property_id"]
        before = self.db.load_properties()[pid]["scores"]["deal"]
        for f, v, s in (("mentions_rtc", True, "RTC 30yr read"),
                        ("mentions_ec", True, "EC 30yr nil"),
                        ("mentions_mutation", True, "MR extracts"),
                        ("mentions_sale_deed", True, "Deed + parent deed")):
            self.db.record_verification(pid, f, v, s, "VERIFIED")
        self.db.record_verification(pid, "summer_yield", "2 inch through May",
                                    "Site visit pump run", "SITE_VISIT")
        pipeline.rescore_property(pid)
        after = self.db.load_properties()[pid]["scores"]
        self.assertGreater(after["deal"], before)
        self.assertEqual(after["legal_risk"], legal.LOW)

    def test_alerts_do_not_repeat_at_the_same_level(self):
        from findfarms.core import pipeline
        pipeline.ingest("Bannur 2.5 acres borewell 400 ft coconut tar road "
                        "42 lakh per acre 9876543210", "T", "http://a/1")
        first = pipeline.check_alerts()
        second = pipeline.check_alerts()
        self.assertTrue(len(second) < len(first) or not first)


class TestDiscoveryCompliance(unittest.TestCase):
    def test_manual_only_sources_are_refused_before_any_network_call(self):
        from findfarms.discovery import ingest as ing
        r = ing.ingest_url("https://www.magicbricks.com/property/123")
        self.assertFalse(r["ok"])
        self.assertTrue(r["refused"])
        self.assertIn("manual-only", r["error"])

    def test_robots_gate_fails_closed_on_an_unreachable_host(self):
        from findfarms.discovery import robots
        ok, why = robots.may_fetch("https://nonexistent-host-xyz-987.invalid/x")
        self.assertFalse(ok)
        self.assertIn("fails closed", why)

    def test_non_http_urls_refused(self):
        from findfarms.discovery import robots
        self.assertFalse(robots.may_fetch("file:///etc/passwd")[0])
        self.assertFalse(robots.may_fetch("")[0])

    def test_access_walls_are_detected_not_parsed(self):
        from findfarms.discovery import robots
        self.assertIsNotNone(
            robots.looks_like_access_wall("<html>Please sign in to continue</html>"))
        self.assertIsNone(
            robots.looks_like_access_wall("<html>2 acres in Bannur</html>"))

    def test_crawl_delay_never_below_the_floor(self):
        from findfarms.discovery import robots
        self.assertGreaterEqual(robots.crawl_delay("https://example.test/x"),
                                robots.MIN_CRAWL_DELAY)


class TestChecklists(unittest.TestCase):
    def test_every_property_gets_actionable_output(self):
        from findfarms.core import pipeline
        a = pipeline.analyse_property(
            extract.extract_listing("Bannur 2 acres 35 lakh per acre", "T"), {})
        self.assertTrue(a["missing_information"])
        self.assertTrue(a["site_visit_checklist"])
        self.assertTrue(a["document_checklist"])
        self.assertTrue(a["why_interesting"])
        self.assertTrue(a["major_risks"])

    def test_survey_number_is_a_critical_gap(self):
        from findfarms.core import pipeline
        a = pipeline.analyse_property(
            extract.extract_listing("Bannur 2 acres 35 lakh per acre", "T"), {})
        critical = [m["item"] for m in a["missing_information"]
                    if m["priority"] == "CRITICAL"]
        self.assertTrue(any("Survey number" in c for c in critical))


if __name__ == "__main__":
    unittest.main(verbosity=2)
