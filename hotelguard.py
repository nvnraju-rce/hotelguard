#!/usr/bin/env python3
"""HotelGuard prototype: compares what a public listing shows (phone, website, reviews)
against verified reference data, scores the risk, and drafts owner alerts for human review.

Usage:
  python hotelguard.py --offline --as-of 2026-10-29            # demo with bundled fixtures
  python hotelguard.py --data mydata --llm ollama:llama3.1:8b  # live checks + local LLM
"""
import argparse
import csv
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import checks
import llm
import store

LEVELS = [(60, "HIGH"), (30, "MEDIUM"), (0, "LOW")]


def read_csv(p: Path):
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def level_for(score):
    return next(name for floor, name in LEVELS if score >= floor)


def assess_all(data: Path, offline: bool, as_of: date, classifier=None, listings=None):
    refs = {r["hotel_id"]: r for r in read_csv(data / "reference.csv")}
    listings = listings if listings is not None else read_csv(data / "listings.csv")
    rev_path = data / "reviews.csv"
    reviews = defaultdict(list)
    if rev_path.exists():
        for r in read_csv(rev_path):
            reviews[r["hotel_id"]].append(r)
    fixtures = data / "fixtures"
    phone_counts = Counter(checks.norm_phone(l["listing_phone"]) for l in listings if l["listing_phone"])
    results = []
    for l in listings:
        ref = refs.get(l["hotel_id"])
        if not ref:
            continue
        findings, page = checks.check_website(ref, l, fixtures, offline, as_of)
        findings += checks.check_phone(ref, l, page, phone_counts)
        rev_findings, flagged = checks.check_reviews(reviews[l["hotel_id"]], as_of, classifier)
        findings += rev_findings
        score = min(100, sum(p for p, _, _ in findings))
        results.append({"ref": ref, "listing": l, "score": score, "level": level_for(score),
                        "findings": findings, "flagged_reviews": flagged})
    return sorted(results, key=lambda r: -r["score"])


def alert_text(r, as_of):
    ref, l = r["ref"], r["listing"]
    lines = [f"Subject: Please verify your online listing details - {ref['name']}, {ref['destination']}", "",
             f"Dear {ref['name']} team,", "",
             "During routine monitoring of public hotel listings we noticed possible mismatches between "
             "your verified contact details and what is currently shown online:", "",
             f"  Verified phone  : {ref['official_phone']}",
             f"  Listed phone    : {l['listing_phone'] or '-'}",
             f"  Verified website: {ref['official_domain']}",
             f"  Listed website  : {l['listing_website'] or '-'}", "", "What we observed:"]
    lines += [f"  - {m}" for _, _, m in r["findings"]]
    lines += ["", "Suggested next steps:",
              "  1. Sign in to your Google Business Profile and confirm the phone number and website.",
              "  2. If they are wrong, correct them and report the unauthorised edit through the Business Profile support flow.",
              "  3. Ask the domain registrar / hosting provider to review the lookalike website, if any.",
              "  4. Warn guests through your official channels; victims can report at cybercrime.gov.in or helpline 1930.",
              "", "This is an automated notice reviewed by a person. It indicates a possible mismatch, "
              "not a confirmed fraud. Please verify.", f"Checked on {as_of}."]
    return "\n".join(lines)


def write_outputs(results, out: Path, as_of: date, polisher=None):
    (out / "alerts").mkdir(parents=True, exist_ok=True)
    alerts = {}
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hotel_id", "name", "destination", "score", "level", "finding_codes"])
        for r in results:
            w.writerow([r["ref"]["hotel_id"], r["ref"]["name"], r["ref"]["destination"],
                        r["score"], r["level"], "|".join(c for _, c, _ in r["findings"])])
    md = [f"# HotelGuard report ({as_of})", "",
          "| Hotel | Destination | Score | Level | Signals |", "|---|---|---|---|---|"]
    for r in results:
        md.append(f"| {r['ref']['name']} | {r['ref']['destination']} | {r['score']} | {r['level']} | "
                  f"{', '.join(c for _, c, _ in r['findings']) or '-'} |")
    md.append("")
    for r in results:
        if r["level"] == "LOW":
            continue
        md += [f"## {r['ref']['name']} - {r['level']} ({r['score']})",
               f"Listed phone: `{r['listing']['listing_phone']}`; listed website: `{r['listing']['listing_website']}`", ""]
        md += [f"- (+{p}) {m}" for p, _, m in r["findings"]]
        for fr in r["flagged_reviews"][:2]:
            md.append(f"- Review {fr['date']} ({fr['rating']}*): {fr['text'][:140]}")
        md.append("")
        text = alert_text(r, as_of)
        if polisher:
            text = polisher(text) or text
        alerts[r["ref"]["hotel_id"]] = text
        (out / "alerts" / f"{r['ref']['hotel_id']}_{r['level']}.txt").write_text(text, encoding="utf-8")
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")
    return alerts


def evaluate(results):
    rows = [(r["level"] != "LOW", r["listing"].get("expected_label") == "fraud", r) for r in results
            if r["listing"].get("expected_label")]
    if not rows:
        return None
    tp = sum(1 for p, t, _ in rows if p and t)
    fp = sum(1 for p, t, _ in rows if p and not t)
    fn = sum(1 for p, t, _ in rows if not p and t)
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec,
            "false_positives": [r["ref"]["name"] for p, t, r in rows if p and not t],
            "missed": [r["ref"]["name"] for p, t, r in rows if not p and t]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="out")
    ap.add_argument("--offline", action="store_true", help="use bundled RDAP/page fixtures instead of the network")
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--llm", default="", help="e.g. ollama:llama3.1:8b (optional)")
    ap.add_argument("--db", default=os.environ.get("HOTELGUARD_DB", "hotelguard.db"), help="SQLite history file; pass an empty string to disable")
    ap.add_argument("--redact", action="store_true", help="store only hashes of listed phone/website (for data you may not retain)")
    a = ap.parse_args()
    as_of = datetime.strptime(a.as_of, "%Y-%m-%d").date()
    classifier = polisher = None
    if a.llm.startswith("ollama:"):
        model = a.llm.split(":", 1)[1]
        classifier = llm.make_review_classifier(model)
        polisher = lambda t: llm.polish_alert(model, t)
    results = assess_all(Path(a.data), a.offline, as_of, classifier)
    alerts = write_outputs(results, Path(a.out), as_of, polisher)
    if a.db:
        conn = store.connect(a.db)
        rid = store.save_run(conn, results, alerts, as_of, "offline" if a.offline else "live", redact=a.redact)
        print(f"Saved run #{rid} to {a.db}")
    print(f"{'Hotel':26}{'Dest':9}{'Score':>6}  Level   Signals")
    for r in results:
        print(f"{r['ref']['name'][:25]:26}{r['ref']['destination'][:8]:9}{r['score']:>6}  {r['level']:7} "
              f"{','.join(c for _, c, _ in r['findings'])}")
    ev = evaluate(results)
    if ev:
        print(f"\nValidation vs expected labels: precision={ev['precision']:.2f} recall={ev['recall']:.2f} "
              f"(TP={ev['tp']} FP={ev['fp']} FN={ev['fn']})")
        print("False positives:", ev["false_positives"] or "none", "| Missed:", ev["missed"] or "none")
    print(f"\nReport: {a.out}/report.md   Alerts: {a.out}/alerts/")


if __name__ == "__main__":
    main()
