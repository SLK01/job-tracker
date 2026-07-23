import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date, datetime, timedelta

import job_tracker as jt

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"

SERPER_URL = "https://google.serper.dev/search"
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"
LEVER_API = "https://api.lever.co/v0/postings/{company}/{job_id}?mode=json"

GREENHOUSE_RE = re.compile(r"https?://(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9\-_]+)/jobs/(\d+)")
LEVER_RE = re.compile(r"https?://jobs\.lever\.co/([a-zA-Z0-9\-_]+)/([0-9a-f\-]{36})")

MAX_CANDIDATES_PER_LEVEL = 10

US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
}
US_STATE_ABBREVS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in",
    "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv",
    "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn",
    "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
}


def _contains_term(text, term):
    pattern = r"\b" + re.escape(term.lower()) + r"\b"
    return re.search(pattern, text.lower()) is not None


def _title_matches(fetched_title, domains, levels):
    has_domain = any(_contains_term(fetched_title, d) for d in domains)
    has_level = any(_contains_term(fetched_title, l) for l in levels)
    return has_domain and has_level


def _detect_country_from_location(location_name):
    text = location_name.lower()
    if "united states" in text or re.search(r"\busa?\b", text):
        return "US"
    words = re.split(r"[,\s]+", text)
    if any(w in US_STATE_ABBREVS for w in words) or any(s in text for s in US_STATE_NAMES):
        return "US"
    return None


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text())


def _http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "job-tracker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def _search_candidates(level, domains, api_key):
    domain_group = " OR ".join(f'"{d}"' for d in domains)
    query = f'site:job-boards.greenhouse.io OR site:jobs.lever.co "{level}" ({domain_group})'
    body = json.dumps({"q": query}).encode()
    req = urllib.request.Request(
        SERPER_URL,
        data=body,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Serper API error {e.code}: {e.read().decode(errors='ignore')}")
    except Exception as e:
        raise RuntimeError(f"Serper request failed: {e}")

    links = [r.get("link", "") for r in data.get("organic", [])]
    candidates = []
    seen = set()
    for link in links:
        m = GREENHOUSE_RE.search(link)
        if m:
            key = ("greenhouse", m.group(1), m.group(2))
            if key not in seen:
                seen.add(key)
                candidates.append(key)
            continue
        m = LEVER_RE.search(link)
        if m:
            key = ("lever", m.group(1), m.group(2))
            if key not in seen:
                seen.add(key)
                candidates.append(key)
    return candidates[:MAX_CANDIDATES_PER_LEVEL]


def _extract_salary_from_text(text):
    m = re.search(r"\$[\d,]{4,}\s*(?:-|to|–)\s*\$?[\d,]{4,}", text)
    return m.group(0) if m else None


def _detect_workplace_type(location_name):
    text = location_name.lower()
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text:
        return "remote"
    return "onsite"


def _fetch_greenhouse(company, job_id):
    status, data = _http_get_json(GREENHOUSE_API.format(company=company, job_id=job_id))
    if status != 200 or not data:
        return None
    content = re.sub(r"<[^>]+>", " ", data.get("content", ""))
    salary = _extract_salary_from_text(content)
    location_name = (data.get("location") or {}).get("name", "")
    workplace = _detect_workplace_type(location_name)
    country = _detect_country_from_location(location_name)
    notes = f"{workplace.capitalize()} — " + (f"Salary published: {salary}" if salary else "No salary range published")
    return {
        "title": data.get("title", "").strip(),
        "company": data.get("company_name", company),
        "location": location_name,
        "url": data.get("absolute_url", f"https://job-boards.greenhouse.io/{company}/jobs/{job_id}"),
        "source": "greenhouse",
        "workplace_type": workplace,
        "country": country,
        "notes": notes,
    }


def _fetch_lever(company, job_id):
    status, data = _http_get_json(LEVER_API.format(company=company, job_id=job_id))
    if status != 200 or not data:
        return None
    categories = data.get("categories", {})
    commitment = categories.get("commitment", "")
    location_name = categories.get("location", "")
    workplace = data.get("workplaceType", "") or _detect_workplace_type(location_name)
    lever_country = data.get("country", "")
    country = "US" if lever_country == "US" else _detect_country_from_location(location_name)
    salary_range = data.get("salaryRange")
    notes = f"Salary published: {salary_range}" if salary_range else "No salary range published"
    parts = [p for p in [commitment, workplace] if p]
    if parts:
        notes = ", ".join(parts) + " — " + notes
    return {
        "title": data.get("text", "").strip(),
        "company": company,
        "location": location_name,
        "url": data.get("hostedUrl", f"https://jobs.lever.co/{company}/{job_id}"),
        "source": "lever",
        "workplace_type": workplace,
        "country": country,
        "notes": notes,
    }


def run_refresh():
    config = load_config()
    api_key = config.get("serper_api_key", "")
    if not api_key or api_key == "PASTE_YOUR_SERPER_API_KEY_HERE":
        return {"error": "No Serper API key configured. Add one to config.json."}

    criteria = jt.load_criteria()
    domains = criteria.get("domains", [])
    levels = criteria.get("levels", [])
    if not domains or not levels:
        return {"error": "Configure at least one domain and one level term in criteria.json."}

    checked = 0
    added = 0
    updated = 0
    dead = 0
    title_mismatch = 0
    errors = []

    conn = jt.get_db()
    for level in levels:
        try:
            candidates = _search_candidates(level, domains, api_key)
        except RuntimeError as e:
            errors.append(str(e))
            continue

        for source, company, job_id in candidates:
            checked += 1
            job = _fetch_greenhouse(company, job_id) if source == "greenhouse" else _fetch_lever(company, job_id)
            if job is None:
                dead += 1
                continue
            if not _title_matches(job["title"], domains, levels):
                title_mismatch += 1
                continue

            exists = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (job["url"],)).fetchone()
            conn.execute(
                """
                INSERT INTO jobs (title, company, location, url, source, date_found, status, notes, workplace_type, country)
                VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    location = excluded.location,
                    notes = excluded.notes,
                    workplace_type = excluded.workplace_type,
                    country = excluded.country
                """,
                (job["title"], job["company"], job["location"], job["url"], job["source"],
                 date.today().isoformat(), job["notes"], job["workplace_type"], job["country"]),
            )
            if exists:
                updated += 1
            else:
                added += 1

    conn.commit()
    conn.close()

    jt.set_meta("last_refresh_at", datetime.utcnow().isoformat())

    return {
        "checked": checked,
        "added": added,
        "updated": updated,
        "dead_skipped": dead,
        "title_mismatch_skipped": title_mismatch,
        "errors": errors,
    }


def refresh_status():
    config = load_config()
    frequency_hours = config.get("refresh_frequency_hours", 24)
    last_refresh_at = jt.get_meta("last_refresh_at")
    due = True
    if last_refresh_at:
        elapsed = datetime.utcnow() - datetime.fromisoformat(last_refresh_at)
        due = elapsed >= timedelta(hours=frequency_hours)
    return {
        "last_refresh_at": last_refresh_at,
        "refresh_frequency_hours": frequency_hours,
        "due": due,
    }


def run_refresh_if_due():
    if refresh_status()["due"]:
        run_refresh()


if __name__ == "__main__":
    print(json.dumps(run_refresh(), indent=2))
