"""Deterministic checks for HotelGuard: website, phone and review signals.
Standard library only, so the prototype runs anywhere. Every check returns a list of
findings: (points, code, human-readable message)."""
import difflib
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

SECOND_LEVEL = {"co.in", "org.in", "net.in", "gov.in", "ac.in", "nic.in", "res.in",
                "co.uk", "com.au", "co.nz", "co.za"}
SUSPICIOUS_TLDS = {"xyz", "top", "online", "site", "click", "shop", "icu", "buzz",
                   "live", "club", "vip", "work", "fun", "cfd", "sbs"}
BOOKING_WORDS = ("booking", "book", "reserve", "reservation", "deal", "offer", "stay", "official")
UPI_RE = re.compile(r"\b[\w.\-]{2,}@(ybl|ibl|axl|okaxis|oksbi|okhdfcbank|okicici|paytm|upi|apl)\b", re.I)
PAYMENT_PHRASES = ("advance payment", "pay advance", "token amount", "pay now to confirm",
                   "whatsapp only", "limited offer", "only today", "booking amount",
                   "scan qr", "pay 30%", "pay 50%")
SCAM_REVIEW_PATTERNS = [
    r"\badvance\b", r"\btoken amount\b", r"\bscam", r"\bfraud", r"\bcheat", r"\bfake\b",
    r"no booking (was )?(found|made|record)", r"not the official", r"\bwhatsapp\b.*\b(pay|payment)\b",
    r"called the number", r"never refund", r"money (was )?(taken|deducted)",
    r"hotel (said|told).*(not|never).*(our|their) (number|website)",
]

# ---------------------------------------------------------------- helpers
def host_of(url: str) -> str:
    if not url:
        return ""
    u = url if "://" in url else "https://" + url
    return (urllib.parse.urlparse(u).hostname or "").lower()


def registrable(host: str) -> str:
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def core_label(domain: str) -> str:
    """'palm-bay-resort.co.in' -> 'palmbayresort'"""
    parts = domain.split(".")
    n = 3 if len(parts) >= 3 and ".".join(parts[-2:]) in SECOND_LEVEL else 2
    return re.sub(r"[^a-z0-9]", "", ".".join(parts[:-(n - 1)]) if len(parts) >= n else parts[0])


def tld_of(domain: str) -> str:
    return domain.rsplit(".", 1)[-1]


def norm_phone(raw: str) -> str:
    """Return the 10-digit Indian national number, or '' if it can't be parsed."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("0091"):
        d = d[4:]
    elif d.startswith("91") and len(d) > 10:
        d = d[2:]
    elif d.startswith("0") and len(d) == 11:
        d = d[1:]
    return d if len(d) == 10 else ""


def looks_mobile(raw: str) -> bool:
    n = norm_phone(raw)
    d = re.sub(r"\D", "", raw or "")
    return bool(n) and n[0] in "6789" and not d.startswith("0") and "(" not in (raw or "")


# ---------------------------------------------------------------- network (with offline fixtures)
def rdap_creation_date(domain: str, fixtures: Path, offline: bool):
    fx = fixtures / "rdap.json"
    if offline:
        data = json.loads(fx.read_text()) if fx.exists() else {}
        v = data.get(domain)
        return datetime.strptime(v, "%Y-%m-%d").date() if v else None
    try:
        req = urllib.request.Request(f"https://rdap.org/domain/{domain}",
                                     headers={"User-Agent": "HotelGuard-prototype"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        for ev in data.get("events", []):
            if ev.get("eventAction") == "registration":
                return datetime.strptime(ev["eventDate"][:10], "%Y-%m-%d").date()
    except Exception:
        return None
    return None


def fetch_text(url: str, fixtures: Path, offline: bool) -> str:
    if not url:
        return ""
    if offline:
        p = fixtures / "pages" / f"{registrable(host_of(url))}.txt"
        return p.read_text() if p.exists() else ""
    try:
        u = url if "://" in url else "https://" + url
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 HotelGuard-prototype"})
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read(300_000).decode("utf-8", "ignore")
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    except Exception:
        return ""


# ---------------------------------------------------------------- checks
def check_website(ref: dict, listing: dict, fixtures: Path, offline: bool, as_of: date):
    f = []
    url = (listing.get("listing_website") or "").strip()
    if not url:
        return f, ""
    listed = registrable(host_of(url))
    official = registrable(host_of(ref["official_domain"]))
    page = ""
    if listed != official:
        f.append((40, "WEB_DOMAIN_MISMATCH",
                  f"Listed website domain '{listed}' differs from the verified domain '{official}'."))
        a, b = core_label(listed), core_label(official)
        if a and b and (b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75):
            f.append((25, "WEB_LOOKALIKE", f"'{listed}' closely resembles the official name '{official}'."))
        if tld_of(listed) in SUSPICIOUS_TLDS:
            f.append((10, "WEB_SUSPICIOUS_TLD", f"Domain uses the '.{tld_of(listed)}' extension, common in scam sites."))
        if any(w in a for w in BOOKING_WORDS):
            f.append((5, "WEB_BOOKING_WORDS", "Domain name contains booking/offer words typical of fake booking sites."))
        created = rdap_creation_date(listed, fixtures, offline)
        if created:
            age = max((as_of - created).days, 0)
            if age < 180:
                f.append((25, "WEB_NEW_DOMAIN", f"Domain registered only {age} days ago ({created})."))
        page = fetch_text(url, fixtures, offline)
        if page:
            low = page.lower()
            if UPI_RE.search(page):
                f.append((20, "WEB_UPI_ID", "Page asks for payment to a personal-style UPI ID."))
            hits = [p for p in PAYMENT_PHRASES if p in low]
            if hits:
                f.append((15, "WEB_PAYMENT_PRESSURE", "Page uses pressure/advance-payment wording: " + ", ".join(hits[:3]) + "."))
    return f, page


def check_phone(ref: dict, listing: dict, page: str, phone_counts: dict):
    f = []
    raw = (listing.get("listing_phone") or "").strip()
    n = norm_phone(raw)
    ref_numbers = {norm_phone(ref.get("official_phone", ""))}
    ref_numbers |= {norm_phone(x) for x in (ref.get("alt_phones") or "").split("|") if x.strip()}
    ref_numbers.discard("")
    if raw and n not in ref_numbers:
        f.append((35, "PHONE_MISMATCH", f"Listed phone {raw} is not among the verified numbers for this property."))
        if ref.get("phone_type") == "landline" and looks_mobile(raw):
            f.append((10, "PHONE_MOBILE_FOR_LANDLINE", "Property uses a landline officially, but the listing shows a mobile number."))
    if n and phone_counts.get(n, 0) >= 2:
        f.append((30, "PHONE_REUSED", f"The same number appears on {phone_counts[n]} unrelated listings."))
    if page:
        found = {norm_phone(m) for m in re.findall(r"\+?\d[\d\s\-()]{8,}\d", page)} - {""}
        if found and not (found & ref_numbers):
            f.append((15, "PAGE_PHONE_MISMATCH", "Phone numbers shown on the listed website don't match the verified numbers."))
    return f


def keyword_scam_review(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in SCAM_REVIEW_PATTERNS)


def check_reviews(reviews: list, as_of: date, classify=None):
    """reviews: list of dicts with date,rating,text. classify: optional callable(text)->bool|None."""
    flagged = []
    for r in reviews:
        try:
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
            if (as_of - d).days > 365 or d > as_of:
                continue
        except Exception:
            pass
        verdict = classify(r["text"]) if classify else None
        if verdict is None:
            verdict = keyword_scam_review(r["text"])
        if verdict:
            flagged.append(r)
    if not flagged:
        return [], flagged
    pts = min(30, 10 * len(flagged))
    return [(pts, "REVIEWS_SCAM_PATTERN", f"{len(flagged)} recent review(s) describe booking/payment problems.")], flagged
