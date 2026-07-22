import json
import re
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date

import job_tracker as jt

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"

SERPER_URL = "https://google.serper.dev/search"
GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"
LEVER_API = "https://api.lever.co/v0/postings/{company}/{job_id}?mode=json"

GREENHOUSE_RE = re.compile(r"https?://(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9\-_]+)/jobs/(\d+)")
LEVER_RE = re.compile(r"https?://jobs\.lever\.co/([a-zA-Z0-9\-_]+)/([0-9a-f\-]{36})")

MAX_CANDIDATES_PER_TITLE = 10

FILLER_WORDS = {"of", "the", "a", "an"}


def _normalize_title(title):
    title = title.lower()
    title = re.sub(r"\bsite reliability engineering\b", "sre", title)
    title = re.sub(r"[,&()\-–]", " ", title)
    return [w for w in title.split() if w and w not in FILLER_WORDS]


def _title_matches(fetched_title, target_titles):
    fetched_words = _normalize_title(fetched_title)
    return any(fetched_words == _normalize_title(t) for t in target_titles)


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


def _search_candidates(title, api_key):
    query = f'site:job-boards.greenhouse.io OR site:jobs.lever.co "{title}"'
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
    return candidates[:MAX_CANDIDATES_PER_TITLE]


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
    notes = f"{workplace.capitalize()} — " + (f"Salary published: {salary}" if salary else "No salary range published")
    return {
        "title": data.get("title", "").strip(),
        "company": data.get("company_name", company),
        "location": location_name,
        "url": data.get("absolute_url", f"https://job-boards.greenhouse.io/{company}/jobs/{job_id}"),
        "source": "greenhouse",
        "workplace_type": workplace,
        "notes": notes,
    }


def _fetch_lever(company, job_id):
    status, data = _http_get_json(LEVER_API.format(company=company, job_id=job_id))
    if status != 200 or not data:
        return None
    categories = data.get("categories", {})
    commitment = categories.get("commitment", "")
    workplace = data.get("workplaceType", "") or _detect_workplace_type(categories.get("location", ""))
    salary_range = data.get("salaryRange")
    notes = f"Salary published: {salary_range}" if salary_range else "No salary range published"
    parts = [p for p in [commitment, workplace] if p]
    if parts:
        notes = ", ".join(parts) + " — " + notes
    return {
        "title": data.get("text", "").strip(),
        "company": company,
        "location": categories.get("location", ""),
        "url": data.get("hostedUrl", f"https://jobs.lever.co/{company}/{job_id}"),
        "source": "lever",
        "workplace_type": workplace,
        "notes": notes,
    }


def run_refresh():
    config = load_config()
    api_key = config.get("serper_api_key", "")
    if not api_key or api_key == "PASTE_YOUR_SERPER_API_KEY_HERE":
        return {"error": "No Serper API key configured. Add one to config.json."}

    exclude_onsite = config.get("exclude_onsite", True)
    titles = jt.load_titles()
    checked = 0
    added = 0
    dead = 0
    title_mismatch = 0
    onsite_skipped = 0
    errors = []

    conn = jt.get_db()
    for title in titles:
        try:
            candidates = _search_candidates(title, api_key)
        except RuntimeError as e:
            errors.append(str(e))
            continue

        for source, company, job_id in candidates:
            checked += 1
            job = _fetch_greenhouse(company, job_id) if source == "greenhouse" else _fetch_lever(company, job_id)
            if job is None:
                dead += 1
                continue
            if not _title_matches(job["title"], titles):
                title_mismatch += 1
                continue
            if exclude_onsite and job["workplace_type"] == "onsite":
                onsite_skipped += 1
                continue
            try:
                conn.execute(
                    "INSERT INTO jobs (title, company, location, url, source, date_found, status, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'new', ?)",
                    (job["title"], job["company"], job["location"], job["url"], job["source"],
                     date.today().isoformat(), job["notes"]),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass  # duplicate URL, already tracked

    conn.commit()
    conn.close()

    return {
        "checked": checked,
        "added": added,
        "dead_skipped": dead,
        "title_mismatch_skipped": title_mismatch,
        "onsite_skipped": onsite_skipped,
        "errors": errors,
    }


if __name__ == "__main__":
    print(json.dumps(run_refresh(), indent=2))
