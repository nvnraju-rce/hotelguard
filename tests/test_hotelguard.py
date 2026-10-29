"""Unit and pipeline tests (standard library only). Run: python -m unittest discover -s tests -v"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import checks  # noqa: E402
import hotelguard as hg  # noqa: E402
import store  # noqa: E402

DATA = ROOT / "data"
AS_OF = date(2026, 10, 29)


class TestHelpers(unittest.TestCase):
    def test_phone_normalisation(self):
        self.assertEqual(checks.norm_phone("0832 2275500"), "8322275500")
        self.assertEqual(checks.norm_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(checks.norm_phone("094400 55667"), "9440055667")
        self.assertEqual(checks.norm_phone("12345"), "")

    def test_registrable_domain(self):
        self.assertEqual(checks.registrable("www.snowvalleyinn.in"), "snowvalleyinn.in")
        self.assertEqual(checks.registrable("a.lakeviewheritage.co.in"), "lakeviewheritage.co.in")
        self.assertEqual(checks.core_label("palm-bay-resort.co.in"), "palmbayresort")

    def test_review_patterns(self):
        self.assertTrue(checks.keyword_scam_review("Paid advance, hotel says no booking was found"))
        self.assertFalse(checks.keyword_scam_review("Lovely stay, great pool"))

    def test_future_reviews_ignored(self):
        revs = [{"date": "2026-11-15", "rating": "1", "text": "Scam, paid advance"}]
        self.assertEqual(checks.check_reviews(revs, AS_OF)[0], [])


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = hg.assess_all(DATA, True, AS_OF)
        cls.by_id = {r["ref"]["hotel_id"]: r for r in cls.results}

    def test_all_injected_frauds_flagged_high(self):
        for hid in ("H02", "H03", "H04", "H08"):
            self.assertEqual(self.by_id[hid]["level"], "HIGH", hid)

    def test_clean_hotels_stay_low_despite_formatting_differences(self):
        for hid in ("H01", "H05", "H06"):
            self.assertEqual(self.by_id[hid]["level"], "LOW", hid)

    def test_validation_metrics(self):
        ev = hg.evaluate(self.results)
        self.assertEqual(ev["recall"], 1.0)
        self.assertGreaterEqual(ev["precision"], 0.8)
        self.assertEqual(ev["missed"], [])

    def test_reused_phone_detected(self):
        codes = {c for _, c, _ in self.by_id["H02"]["findings"]}
        self.assertIn("PHONE_REUSED", codes)

    def test_alert_is_neutral_and_has_next_steps(self):
        text = hg.alert_text(self.by_id["H03"], AS_OF)
        self.assertIn("possible mismatch", text.lower())
        self.assertIn("cybercrime.gov.in", text)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(os.path.join(self.tmp.name, "t.db"))
        self.results = hg.assess_all(DATA, True, AS_OF)
        self.alerts = {r["ref"]["hotel_id"]: hg.alert_text(r, AS_OF) for r in self.results if r["level"] != "LOW"}

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_save_and_read_back(self):
        rid = store.save_run(self.conn, self.results, self.alerts, AS_OF, "test")
        rows = store.assessments(self.conn, rid)
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]["level"], "HIGH")
        self.assertTrue(store.findings(self.conn, rid, rows[0]["hotel_id"]))

    def test_changes_ignore_formatting_but_catch_real_changes(self):
        refs = {r["hotel_id"]: r for r in hg.read_csv(DATA / "reference.csv")}
        final = hg.read_csv(DATA / "listings.csv")
        clean = [dict(l, listing_phone=refs[l["hotel_id"]]["official_phone"],
                      listing_website=refs[l["hotel_id"]]["official_domain"]) for l in final]
        r1 = hg.assess_all(DATA, True, AS_OF, listings=clean)
        store.save_run(self.conn, r1, {}, AS_OF, "t")
        rid2 = store.save_run(self.conn, self.results, self.alerts, AS_OF, "t")
        changed = {(c["hotel"], c["change"]) for c in store.changes(self.conn, rid2)}
        self.assertIn(("Snow Valley Inn", "listed website changed"), changed)
        self.assertIn(("Hillcrest Cottages", "listed phone changed"), changed)
        # Palm Bay only differs in formatting ("+91 832 ..." vs "0832 ...")
        self.assertNotIn(("Palm Bay Resort", "listed phone changed"), changed)

    def test_case_workflow_and_audit_log(self):
        store.save_run(self.conn, self.results, self.alerts, AS_OF, "t")
        store.set_case(self.conn, "H03", "investigating", "called owner", "tester")
        store.set_case(self.conn, "H03", "alert_sent", "emailed", "tester")
        self.assertEqual(store.get_case(self.conn, "H03")["status"], "alert_sent")
        self.assertEqual(len(store.case_log(self.conn, "H03")), 2)

    def test_redact_hides_listed_values_and_text(self):
        rid = store.save_run(self.conn, self.results, self.alerts, AS_OF, "t", redact=True)
        a = {r["hotel_id"]: r for r in store.assessments(self.conn, rid)}["H03"]
        self.assertTrue(a["listed_website"].startswith("#"))
        self.assertEqual(a["alert_text"], "")
        self.assertNotIn("xyz", str(store.findings(self.conn, rid, "H03")))
        self.assertEqual(store.flagged_reviews(self.conn, rid, "H03"), [])


if __name__ == "__main__":
    unittest.main()
