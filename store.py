"""SQLite persistence for HotelGuard: run history, findings, alert drafts, reviewer cases.
Standard library only. The dashboard reads everything through these functions."""
import hashlib
import sqlite3
from datetime import datetime

import checks

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT, as_of TEXT, mode TEXT, n_hotels INTEGER);
CREATE TABLE IF NOT EXISTS assessments(
  run_id INTEGER, hotel_id TEXT, name TEXT, destination TEXT, score INTEGER, level TEXT,
  listed_phone TEXT, listed_website TEXT, official_phone TEXT, official_domain TEXT, alert_text TEXT,
  PRIMARY KEY(run_id, hotel_id));
CREATE TABLE IF NOT EXISTS findings(
  run_id INTEGER, hotel_id TEXT, code TEXT, points INTEGER, message TEXT);
CREATE TABLE IF NOT EXISTS flagged_reviews(
  run_id INTEGER, hotel_id TEXT, review_date TEXT, rating TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS cases(
  hotel_id TEXT PRIMARY KEY, status TEXT, note TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS case_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, hotel_id TEXT, status TEXT, note TEXT, reviewer TEXT, at TEXT);
CREATE INDEX IF NOT EXISTS ix_assess_hotel ON assessments(hotel_id, run_id);
CREATE INDEX IF NOT EXISTS ix_find ON findings(run_id, hotel_id);
"""
STATUSES = ["new", "investigating", "confirmed_fraud", "false_positive", "alert_sent", "resolved"]


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _mask(v: str) -> str:
    return "#" + hashlib.sha256((v or "").encode()).hexdigest()[:10] if v else ""


def _phone_key(v: str) -> str:
    return v if v.startswith("#") else (checks.norm_phone(v) or v)


def _site_key(v: str) -> str:
    return v if v.startswith("#") else (checks.registrable(checks.host_of(v)) or v)


def save_run(conn, results, alerts: dict, as_of, mode: str, redact=False, run_at=None) -> int:
    """results: output of hotelguard.assess_all. redact=True stores only hashes of the listed values
    (still lets you detect changes) and no free-text messages, for data you must not retain."""
    run_at = run_at or datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("INSERT INTO runs(run_at, as_of, mode, n_hotels) VALUES(?,?,?,?)",
                       (run_at, str(as_of), mode, len(results)))
    run_id = cur.lastrowid
    for r in results:
        ref, l, hid = r["ref"], r["listing"], r["ref"]["hotel_id"]
        phone, site = l.get("listing_phone", ""), l.get("listing_website", "")
        conn.execute("INSERT INTO assessments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (run_id, hid, ref["name"], ref["destination"], r["score"], r["level"],
                      _mask(phone) if redact else phone, _mask(site) if redact else site,
                      ref["official_phone"], ref["official_domain"],
                      "" if redact else alerts.get(hid, "")))
        for pts, code, msg in r["findings"]:
            conn.execute("INSERT INTO findings VALUES(?,?,?,?,?)",
                         (run_id, hid, code, pts, code if redact else msg))
        if not redact:
            for fr in r["flagged_reviews"]:
                conn.execute("INSERT INTO flagged_reviews VALUES(?,?,?,?,?)",
                             (run_id, hid, fr.get("date"), fr.get("rating"), fr.get("text")))
        if not conn.execute("SELECT 1 FROM cases WHERE hotel_id=?", (hid,)).fetchone() and r["level"] != "LOW":
            conn.execute("INSERT INTO cases VALUES(?,?,?,?)", (hid, "new", "", run_at))
    conn.commit()
    return run_id


def runs(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY run_id DESC")]


def assessments(conn, run_id):
    q = """SELECT a.*, COALESCE(c.status,'') AS case_status FROM assessments a
           LEFT JOIN cases c ON c.hotel_id=a.hotel_id WHERE a.run_id=? ORDER BY a.score DESC"""
    return [dict(r) for r in conn.execute(q, (run_id,))]


def findings(conn, run_id, hotel_id):
    return [dict(r) for r in conn.execute(
        "SELECT code, points, message FROM findings WHERE run_id=? AND hotel_id=? ORDER BY points DESC",
        (run_id, hotel_id))]


def flagged_reviews(conn, run_id, hotel_id):
    return [dict(r) for r in conn.execute(
        "SELECT review_date, rating, text FROM flagged_reviews WHERE run_id=? AND hotel_id=?", (run_id, hotel_id))]


def history(conn, hotel_id):
    return [dict(r) for r in conn.execute(
        """SELECT r.run_id, r.as_of, a.score, a.level FROM assessments a JOIN runs r USING(run_id)
           WHERE a.hotel_id=? ORDER BY r.run_id""", (hotel_id,))]


def changes(conn, run_id):
    """What changed between this run and the run before it, per hotel."""
    prev = conn.execute("SELECT MAX(run_id) FROM runs WHERE run_id<?", (run_id,)).fetchone()[0]
    if prev is None:
        return []
    now = {r["hotel_id"]: r for r in assessments(conn, run_id)}
    old = {r["hotel_id"]: r for r in assessments(conn, prev)}
    out = []
    for hid, n in now.items():
        o = old.get(hid)
        if not o:
            out.append({"hotel": n["name"], "change": "new in monitoring", "from": "", "to": n["level"]})
            continue
        if _phone_key(n["listed_phone"]) != _phone_key(o["listed_phone"]):
            out.append({"hotel": n["name"], "change": "listed phone changed", "from": o["listed_phone"], "to": n["listed_phone"]})
        if _site_key(n["listed_website"]) != _site_key(o["listed_website"]):
            out.append({"hotel": n["name"], "change": "listed website changed", "from": o["listed_website"], "to": n["listed_website"]})
        if n["level"] != o["level"]:
            out.append({"hotel": n["name"], "change": "risk level changed", "from": f"{o['level']} ({o['score']})", "to": f"{n['level']} ({n['score']})"})
    return out


def set_case(conn, hotel_id, status, note, reviewer="") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("INSERT INTO cases VALUES(?,?,?,?) ON CONFLICT(hotel_id) DO UPDATE SET status=excluded.status, "
                 "note=excluded.note, updated_at=excluded.updated_at", (hotel_id, status, note, now))
    conn.execute("INSERT INTO case_log(hotel_id,status,note,reviewer,at) VALUES(?,?,?,?,?)",
                 (hotel_id, status, note, reviewer, now))
    conn.commit()


def get_case(conn, hotel_id):
    r = conn.execute("SELECT * FROM cases WHERE hotel_id=?", (hotel_id,)).fetchone()
    return dict(r) if r else {"hotel_id": hotel_id, "status": "new", "note": "", "updated_at": ""}


def case_log(conn, hotel_id):
    return [dict(r) for r in conn.execute(
        "SELECT at, status, note, reviewer FROM case_log WHERE hotel_id=? ORDER BY id DESC", (hotel_id,))]
