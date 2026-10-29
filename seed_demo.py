#!/usr/bin/env python3
"""Builds a demo history in hotelguard.db: three weekly runs showing listings getting hijacked over time,
plus a few reviewer decisions. Safe to re-run (it recreates the database)."""
import os
from datetime import datetime
from pathlib import Path

import hotelguard as hg
import store

DB = os.environ.get("HOTELGUARD_DB", "hotelguard.db")
DATA = Path("data")


def main():
    if os.path.exists(DB):
        os.remove(DB)
    conn = store.connect(DB)
    refs = {r["hotel_id"]: r for r in hg.read_csv(DATA / "reference.csv")}
    final = hg.read_csv(DATA / "listings.csv")
    clean = [dict(l, listing_phone=refs[l["hotel_id"]]["official_phone"],
                  listing_website=refs[l["hotel_id"]]["official_domain"]) for l in final]
    stage_b = [dict(c) for c in clean]
    for l in stage_b:
        if l["hotel_id"] in ("H02", "H07", "H08"):      # phones hijacked first
            l["listing_phone"] = next(f["listing_phone"] for f in final if f["hotel_id"] == l["hotel_id"])
    for stage, as_of in ((clean, "2026-10-01"), (stage_b, "2026-10-15"), (final, "2026-10-29")):
        d = datetime.strptime(as_of, "%Y-%m-%d").date()
        results = hg.assess_all(DATA, True, d, listings=stage)
        alerts = {r["ref"]["hotel_id"]: hg.alert_text(r, d) for r in results if r["level"] != "LOW"}
        rid = store.save_run(conn, results, alerts, d, "demo", run_at=f"{as_of}T09:00:00")
        print(f"run #{rid} as of {as_of}: " + ", ".join(f"{r['ref']['hotel_id']}={r['level']}" for r in results if r["level"] != "LOW"))
    store.set_case(conn, "H07", "false_positive", "Owner confirmed a new reception mobile number. Added to alt_phones.", "demo")
    store.set_case(conn, "H02", "investigating", "Called the official landline; owner unaware of the listed mobile number.", "demo")
    store.set_case(conn, "H03", "alert_sent", "Alert emailed to the verified owner address; registrar abuse report filed.", "demo")


if __name__ == "__main__":
    main()
