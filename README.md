# HotelGuard prototype

Detects possible hijacked or fake phone numbers and websites on hotel/resort listings and drafts notices to owners.
Runs on the Python standard library alone (3.9+). Every external service is open or free-to-self-host.

## Quick demo (no internet needed)
    python hotelguard.py --offline --as-of 2026-10-29
Reads `data/` (synthetic hotels, with injected fraud cases), writes `out/report.md`, `out/results.csv`
and `out/alerts/*.txt`, then prints precision and recall against `expected_label`.

## How it works
1. **reference.csv**: verified official phone and domain per hotel (from owners, registries, official sites).
2. **listings.csv**: what the public listing currently shows (phone, website).
3. **reviews.csv**: recent reviews.
4. For each hotel the agent runs checks, adds up a risk score, then writes a report and alert drafts:
   - Website: domain differs from official, lookalike name, suspicious extension, domain age (RDAP), UPI-ID and advance-payment wording on the page.
   - Phone: not among verified numbers, mobile instead of landline, same number on several unrelated hotels, phone on the fake site differs.
   - Reviews: recent reviews describing advance payment, no booking found, fake number or website (keywords, or a local LLM).
5. A person reviews every MEDIUM/HIGH case before any alert is sent.

Levels: HIGH >= 60, MEDIUM 30-59, LOW < 30. Weights are in `checks.py`; tune them on your own data.

## Dashboard and history (SQLite)
Every run is saved to `hotelguard.db` (SQLite, a single file), so you keep a history instead of one-off reports.

    pip install streamlit
    python seed_demo.py            # optional: 3 demo runs showing listings being hijacked over time
    streamlit run dashboard.py

Dashboard tabs:
- **Overview**: counts by risk level, filterable table (hotel, destination, listed vs verified values), CSV export.
- **Case review**: why a hotel was flagged, the reviews that triggered it, score trend, reviewer status
  (new, investigating, confirmed_fraud, false_positive, alert_sent, resolved), notes with an audit trail, and the draft owner alert.
- **Changes**: listed phone, website or risk-level changes since the previous run (formatting-only differences are ignored).
- **Run history**: all runs and flagged-hotels-per-run trend. The sidebar can also trigger a new run.

Tables in `hotelguard.db`: runs, assessments, findings, flagged_reviews, cases, case_log.
Use `--redact` to store only hashes of listed phone/website values (change detection still works) and no free text.
Do this for any data your licence does not let you retain (see Google data below).

## Docker
    docker compose up --build                                    # dashboard at http://localhost:8501 (demo data on first start)
    docker compose --profile monitor up --build                  # + re-checks every 24 h and saves each run
    docker compose --profile monitor --profile llm up --build    # + local Ollama LLM
    docker compose exec ollama ollama pull llama3.1:8b           # once, after the llm profile starts

Settings go in a `.env` file next to `docker-compose.yml`:

    HOTELGUARD_SEED_DEMO=0                 # 1 seeds demo history only when no database exists yet
    HOTELGUARD_MODE=live                   # offline = bundled fixtures, live = real RDAP and page fetches
    HOTELGUARD_INTERVAL_HOURS=24
    HOTELGUARD_LLM=ollama:llama3.1:8b      # optional; needs the llm profile

- `./data` (reference, listings, reviews) is mounted read-only, so edit it on your machine and the next run picks it up.
- The database and reports live in Docker volumes `hg_db` and `hg_out`, so they survive restarts.
  Back up the database: `docker compose cp dashboard:/app/db/hotelguard.db ./backup.db`
- Start fresh: `docker compose down -v` (deletes the volumes and all history).
- Security: the dashboard has no login and is bound to 127.0.0.1 only. To share it with colleagues, put it behind a reverse proxy
  with authentication (for example Caddy or nginx with basic auth, or your college SSO proxy) and use HTTPS. Don't publish port 8501 directly.

## GitHub Actions (CI/CD)
`.github/workflows/ci.yml` runs on every push to `main`, every pull request and every `v*` tag:

| Job | What it checks |
|---|---|
| test | Python 3.9 to 3.12: byte-compile, 14 unit/pipeline tests, offline demo must reach recall 1.00; uploads the sample report as an artifact |
| dashboard | Streamlit AppTest renders `dashboard.py` against seeded demo data and checks the KPI row |
| shell | shellcheck on `docker-entrypoint.sh` and `monitor.sh` |
| docker | Builds the image, starts it, waits for the health endpoint, checks demo seeding, non-root user and a one-shot run |
| publish | Only on `v*` tags, after all jobs pass: pushes the image to `ghcr.io/<owner>/<repo>` (tags `1.2.3`, `1.2`, `latest`) |

Setup: `git init && git add . && git commit -m "HotelGuard prototype"`, create a GitHub repository, push, then open the Actions tab.
To release: `git tag v0.1.0 && git push origin v0.1.0`. No secrets to configure; GHCR uses the built-in `GITHUB_TOKEN`.
Dependabot (`.github/dependabot.yml`) opens monthly update PRs for Actions, the Docker base image and pip.
Run the same tests locally with `python -m unittest discover -s tests -v`.

## Live mode
    python hotelguard.py --data data                      # real RDAP lookups and page fetches
    python hotelguard.py --data data --llm ollama:llama3.1:8b   # local LLM classifies reviews and polishes alerts
Install Ollama from ollama.com, then `ollama pull llama3.1:8b`.

## Real destinations
    python discover_osm.py "Goa"          # discovery from OpenStreetMap
Fill `discover/reference_template.csv` from verified sources, copy to `data/`, run the agent.

## Google data
The prototype avoids storing Google content. Google's Places API terms restrict caching beyond place IDs, so for
production either (a) fetch Google values live and compare with your own reference without storing them, or
(b) use owner-consented Business Profile API access. Check the current Google Maps Platform terms first.

## Limits of this prototype
- Synthetic data: the validation numbers show the logic works, not real-world accuracy.
- Legit changes (a new reception mobile number) trigger MEDIUM. See Blue Lagoon Stay in the demo. This is why a human reviews alerts.
- Reviews here are a CSV. Pulling Google reviews live needs the Places API (paid, with its terms) or owner access.
- Phone-type detection is a heuristic for India. Use `phonenumbers` for production.
