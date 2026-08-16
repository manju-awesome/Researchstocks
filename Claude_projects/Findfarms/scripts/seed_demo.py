"""
seed_demo.py — populate the database with worked examples.

These are INVENTED listings, not real properties. They exist so the dashboard
has something to show on first run and so the scoring behaviour is inspectable
without waiting to collect real data. Each one is written to exercise a
specific path through the engines — the PTCL hard stop, the river-proximity
trap, the deep-borewell penalty, a multi-source duplicate, and a price drop
across three sightings of one parcel.

Run:
    python scripts/seed_demo.py            # add to the live database
    python scripts/seed_demo.py --reset    # wipe and reseed
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from findfarms.core import pipeline           # noqa: E402
from findfarms.store import db                # noqa: E402

# (text, source, url) — the same parcel appearing more than once is the point.
LISTINGS = [
    # -- a strong candidate, seen on three channels with a price drop --------
    ("Agricultural land for sale at Bannur, T Narasipura taluk. 2 acre 20 gunta "
     "fertile red soil. Borewell 380 feet with 3 phase power and pump set, plus "
     "an open well. Water storage tank. 60 coconut trees and 40 mango trees, "
     "fully cultivated and yielding. 30 ft tar road frontage, 300 meters from "
     "main road, fully fenced. "
     "RTC and mutation available, survey no 142/3. Price 42 lakh per acre, "
     "slightly negotiable. Direct owner, no brokers. 22 km from Mysore. "
     "Contact 9845012345",
     "MagicBricks", "https://example-portal.test/listing/8821"),

    ("Farm land Bannur 2.5 acres with borewell 380 ft and open well, coconut and "
     "mango plantation, tar road, 300 mtr from main road, fencing done. "
     "Sy no 142/3. Rate 42L per acre. "
     "Owner direct 98450 12345",
     "Local broker site", "https://example-broker.test/p/441"),

    ("URGENT SALE — Bannur 2 acre 20 gunta coconut and mango farm, borewell 380 "
     "feet, open well, tar road frontage, fenced. Family settlement, price "
     "reduced to 35 lakh per acre. Sy no 142/3. Direct owner 9845012345",
     "Facebook group", "https://example-social.test/post/99231"),

    # -- canal water, larger, priced higher ---------------------------------
    ("3 acres agricultural land Kadakola near Mysore airport, Nanjangud road. "
     "Canal irrigation available plus open well. Sugarcane and paddy cultivation. "
     "Black soil, flat land. 40 ft tar road, 200 meters from highway. Electricity connection with 3 phase. "
     "45 lakh per acre. Broker 9880123456",
     "99acres", "https://example-portal.test/listing/7712"),

    # -- the river-proximity trap ------------------------------------------
    ("2 acres river facing land at T Narasipura, Kaveri river just 200 meters. "
     "River water available for irrigation. Sandy loam soil. Mud road access, 2 km from main road. "
     "Coconut trees planted. 38 lakh per acre negotiable. 9740098765",
     "OLX", "https://example-portal.test/listing/6650"),

    # -- deep borewell, weak water despite the claim ------------------------
    ("Farm land for sale Varuna, Mysore taluk. 1.5 acres. Borewell 850 feet "
     "good water. Red soil, ragi cultivation. Mud road, 1.5 km from tar road. "
     "32 lakh per acre. "
     "Urgent sale, owner shifting abroad. 9611223344",
     "Local broker site", "https://example-broker.test/p/512"),

    # -- the legal hard stop, cheapest on the page --------------------------
    ("Cheap agricultural land Bannur 2 acres only 24 lakh per acre. Grant land "
     "granted under PTCL. Borewell 300 ft, coconut trees. Urgent distress sale. "
     "9900112233",
     "Facebook group", "https://example-social.test/post/88110"),

    # -- no water at all -----------------------------------------------------
    ("Bilikere Hunsur road 4 acres dry land, rain fed. No borewell, borewell can "
     "be arranged. Barren land, no cultivation currently. Mud road access, interior village land. "
     "18 lakh per acre. 9845567890",
     "OLX", "https://example-portal.test/listing/5540"),

    # -- comparable filler so the price engine has enough ------------------
    ("Bannur 3 acres agricultural land, borewell 400 feet, coconut plantation, "
     "tar road facing, 400 m from main road, fenced. 40 lakh per acre. "
     "9812345670",
     "99acres", "https://example-portal.test/listing/7801"),

    ("Bannur 2 acres with borewell 350 ft and open well, mango and sapota trees, "
     "main road facing, red soil. 44 lakh per acre negotiable. 9812345671",
     "MagicBricks", "https://example-portal.test/listing/7802"),

    ("Agricultural land Bannur 1.5 acres borewell 320 feet, coconut trees, "
     "tar road, 800 meters from main road, fenced, red soil. 46 lakh per acre. "
     "9812345672",
     "Local broker site", "https://example-broker.test/p/601"),

    ("Kadakola 2 acres canal water, sugarcane, black soil, main road facing, "
     "3 phase power. 48 lakh per acre. 9812345673",
     "99acres", "https://example-portal.test/listing/7803"),

    ("Kadakola 4 acres farm land with canal and borewell 300 ft, paddy and "
     "sugarcane, flat land, 600 m from main road. 43 lakh per acre. 9812345674",
     "MagicBricks", "https://example-portal.test/listing/7804"),

    ("Srirangapatna 2 acres agricultural land, borewell 280 feet, coconut and "
     "banana, canal nearby, tar road, 250 meters from main road, fenced. 50 lakh per acre. 9812345675",
     "99acres", "https://example-portal.test/listing/7805"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true",
                    help="Wipe the database before seeding.")
    args = ap.parse_args()

    if args.reset:
        for p in (db.PROPERTIES_PATH, db.OBSERVATIONS_PATH,
                  db.PRICE_HISTORY_PATH, db.ALERTS_PATH):
            p.unlink(missing_ok=True)
        print("  database reset")

    print(f"\n  Seeding {len(LISTINGS)} listings "
          f"(invented examples, not real properties)...\n")
    for text, source, url in LISTINGS:
        r = pipeline.ingest(text, source=source, source_url=url)
        tag = "NEW  " if r["is_new"] else "MERGE"
        village = text.split(".")[0][:46]
        print(f"  {tag} {village:48s} -> {r['property_id'][:30]}")
        for ch in r["changes"]:
            if "no new information" not in ch:
                print(f"        · {ch}")

    n = pipeline.rescore_all()
    print(f"\n  Rescored {n} properties (comparables shift as the set grows).")

    alerts = pipeline.check_alerts()
    if alerts:
        print("\n  Alerts fired:")
        for a in alerts:
            print(f"    {a['summary']}")

    drops = pipeline.price_drops()
    if drops:
        print("\n  Price drops detected:")
        for d in drops:
            print(f"    {d['village']} {d['acres']} ac: −{d['drop_pct']:.0f}% "
                  f"across {d['steps']} observations")

    print(f"\n  Done. Run:  python src/findfarms/webapp/app.py\n")


if __name__ == "__main__":
    main()
