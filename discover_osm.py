#!/usr/bin/env python3
"""Discover hotels/resorts in a destination from OpenStreetMap (open data, ODbL) via Overpass.
Writes:
  discover/listings_osm.csv       observed phone/website per property (a proxy for a public listing)
  discover/reference_template.csv  blank sheet - fill official_domain/official_phone from VERIFIED sources
Usage: python discover_osm.py "Goa"        (needs internet; OSM data must be credited: (c) OpenStreetMap contributors)
Note: OSM coverage varies by area, so treat it as discovery. Verified reference data still comes from owners/registries."""
import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://overpass-api.de/api/interpreter"


def query(area: str) -> str:
    return f"""[out:json][timeout:90];
area["name"="{area}"]["boundary"="administrative"]->.a;
nwr["tourism"~"^(hotel|resort|guest_house)$"](area.a);
out center tags;"""


def main(area: str):
    data = urllib.parse.urlencode({"data": query(area)}).encode()
    req = urllib.request.Request(ENDPOINT, data=data, headers={"User-Agent": "HotelGuard-prototype"})
    with urllib.request.urlopen(req, timeout=120) as r:
        elements = json.load(r)["elements"]
    out = Path("discover")
    out.mkdir(exist_ok=True)
    rows = []
    for e in elements:
        t = e.get("tags", {})
        if not t.get("name"):
            continue
        rows.append({
            "hotel_id": f"osm_{e['type'][0]}{e['id']}",
            "listing_name": t["name"],
            "listing_phone": t.get("phone") or t.get("contact:phone", ""),
            "listing_website": t.get("website") or t.get("contact:website", ""),
            "expected_label": "",
        })
    with (out / "listings_osm.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["hotel_id"])
        w.writeheader()
        w.writerows(rows)
    with (out / "reference_template.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hotel_id", "name", "destination", "official_domain", "official_phone", "alt_phones", "phone_type"])
        for r in rows:
            w.writerow([r["hotel_id"], r["listing_name"], area, "", "", "", ""])
    print(f"{len(rows)} properties written to {out}/ - now fill reference_template.csv from verified sources.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
