"""HotelGuard dashboard. Run:  streamlit run dashboard.py
Reads the SQLite history written by hotelguard.py. Reviewers triage cases here; alerts are
drafts only and are never sent automatically."""
import csv
import io
import os
import subprocess
import sys
from datetime import date

import streamlit as st

import store

ICON = {"HIGH": "🔴 HIGH", "MEDIUM": "🟠 MEDIUM", "LOW": "🟢 LOW"}

st.set_page_config(page_title="HotelGuard", page_icon="🛡️", layout="wide")
st.title("🛡️ HotelGuard: listing fraud monitor")
st.caption("Flags possible mismatches in hotel phone numbers and websites. A flag is a lead for a human "
           "reviewer, not a confirmed fraud. Alerts are drafts and are never sent automatically.")

# ------------------------------------------------------------------ sidebar
db_path = st.sidebar.text_input("Database file", os.environ.get("HOTELGUARD_DB", "hotelguard.db"))
reviewer = st.sidebar.text_input("Reviewer name", "")
conn = store.connect(db_path)
run_list = store.runs(conn)

with st.sidebar.expander("Run a new check"):
    offline = st.checkbox("Offline demo fixtures", value=True)
    as_of = st.date_input("As-of date", value=date.today())
    if st.button("Run now"):
        cmd = [sys.executable, "hotelguard.py", "--db", db_path, "--as-of", as_of.isoformat()]
        if offline:
            cmd.append("--offline")
        with st.spinner("Running checks..."):
            proc = subprocess.run(cmd, capture_output=True, text=True)
        (st.success if proc.returncode == 0 else st.error)("Run finished" if proc.returncode == 0 else proc.stderr[-500:])
        st.rerun()

if not run_list:
    st.info("No runs yet. Run `python seed_demo.py` for demo data, or `python hotelguard.py` for a real run.")
    st.stop()

label = {r["run_id"]: f"#{r['run_id']}  as of {r['as_of']}  ({r['mode']})" for r in run_list}
run_id = st.sidebar.selectbox("Run", list(label), format_func=lambda i: label[i])
rows = store.assessments(conn, run_id)
chg = store.changes(conn, run_id)

# ------------------------------------------------------------------ KPIs
k = st.columns(5)
k[0].metric("Hotels monitored", len(rows))
k[1].metric("🔴 High", sum(r["level"] == "HIGH" for r in rows))
k[2].metric("🟠 Medium", sum(r["level"] == "MEDIUM" for r in rows))
k[3].metric("🟢 Low", sum(r["level"] == "LOW" for r in rows))
k[4].metric("Changes since last run", len(chg))

tab_over, tab_case, tab_chg, tab_hist = st.tabs(["Overview", "Case review", "Changes", "Run history"])

# ------------------------------------------------------------------ overview
with tab_over:
    f1, f2 = st.columns(2)
    levels = f1.multiselect("Risk level", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM"])
    dests = sorted({r["destination"] for r in rows})
    sel_d = f2.multiselect("Destination", dests, default=dests)
    view = [r for r in rows if r["level"] in levels and r["destination"] in sel_d]
    st.dataframe([{
        "Hotel": r["name"], "Destination": r["destination"], "Risk": ICON[r["level"]], "Score": r["score"],
        "Listed phone": r["listed_phone"], "Verified phone": r["official_phone"],
        "Listed website": r["listed_website"], "Verified domain": r["official_domain"],
        "Case": r["case_status"] or "-"} for r in view],
        use_container_width=True, hide_index=True,
        column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["hotel_id", "name", "destination", "score", "level", "case_status"])
    for r in rows:
        w.writerow([r["hotel_id"], r["name"], r["destination"], r["score"], r["level"], r["case_status"]])
    st.download_button("Download results (CSV)", buf.getvalue(), file_name=f"hotelguard_run_{run_id}.csv")

# ------------------------------------------------------------------ case review
with tab_case:
    flagged = [r for r in rows if r["level"] != "LOW"]
    if not flagged:
        st.success("No flagged hotels in this run.")
    else:
        pick = st.selectbox("Flagged hotel", flagged, format_func=lambda r: f"{ICON[r['level']]}  {r['name']} ({r['destination']})")
        hid = pick["hotel_id"]
        left, right = st.columns([3, 2])
        with left:
            st.subheader(pick["name"])
            st.write(f"**Verified:** {pick['official_phone']}  |  {pick['official_domain']}")
            st.write(f"**Listed:** {pick['listed_phone'] or '-'}  |  {pick['listed_website'] or '-'}")
            st.markdown("**Why it was flagged**")
            for fnd in store.findings(conn, run_id, hid):
                st.write(f"- (+{fnd['points']}) {fnd['message']}")
            revs = store.flagged_reviews(conn, run_id, hid)
            if revs:
                st.markdown("**Reviews that triggered the scam-pattern signal**")
                for rv in revs:
                    st.write(f"- {rv['review_date']} ({rv['rating']}★): {rv['text']}")
            hist = store.history(conn, hid)
            if len(hist) > 1:
                st.markdown("**Risk score over time**")
                st.line_chart({"score": [h["score"] for h in hist]})
        with right:
            case = store.get_case(conn, hid)
            st.markdown("**Reviewer decision**")
            status = st.selectbox("Status", store.STATUSES, index=store.STATUSES.index(case["status"]) if case["status"] in store.STATUSES else 0, key=f"s_{hid}")
            note = st.text_area("Note (what you verified, who you contacted)", value=case["note"], key=f"n_{hid}")
            if st.button("Save decision", key=f"b_{hid}"):
                store.set_case(conn, hid, status, note, reviewer)
                st.success("Saved")
                st.rerun()
            log = store.case_log(conn, hid)
            if log:
                st.markdown("**Audit trail**")
                st.dataframe(log, hide_index=True, use_container_width=True)
        if pick["alert_text"]:
            with st.expander("Draft owner alert (review before sending)"):
                st.text_area("Draft", pick["alert_text"], height=380, key=f"a_{hid}")
                st.download_button("Download draft (.txt)", pick["alert_text"], file_name=f"alert_{hid}.txt", key=f"d_{hid}")
                st.caption("Send only to the owner's verified contact, from your own email, after confirming the facts.")

# ------------------------------------------------------------------ changes
with tab_chg:
    if not chg:
        st.info("No changes compared with the previous run (or this is the first run).")
    else:
        st.write("Changes in listed phone, website or risk level since the previous run. "
                 "Formatting-only differences (such as +91 vs 0) are ignored.")
        st.dataframe(chg, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ history
with tab_hist:
    st.dataframe(run_list, hide_index=True, use_container_width=True)
    trend = {"HIGH": [], "MEDIUM": []}
    for r in reversed(run_list):
        a = store.assessments(conn, r["run_id"])
        trend["HIGH"].append(sum(x["level"] == "HIGH" for x in a))
        trend["MEDIUM"].append(sum(x["level"] == "MEDIUM" for x in a))
    if len(run_list) > 1:
        st.markdown("**Flagged hotels per run**")
        st.line_chart(trend)
