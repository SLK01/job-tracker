# Job Tracker

A small local tool for tracking open leadership/engineering roles. Tracks jobs through a status pipeline (new → interested → applied → interviewing → rejected/offer), with both a CLI and a local web UI backed by the same SQLite database.

Matching is faceted rather than a flat title list: a posting matches only if its title contains at least one tracked **domain** term (e.g. Engineering, Software) *and* at least one tracked **level** term (e.g. VP, Head, Senior Director) — so "Vice President, Engineering" matches but "Vice President, Marketing" doesn't.

Refreshing pulls candidate postings from Google (via [Serper.dev](https://serper.dev)) restricted to `job-boards.greenhouse.io` and `jobs.lever.co`, then verifies and enriches each one using Greenhouse's and Lever's official public job-board APIs — so closed/filled postings are automatically skipped rather than imported as dead links. Re-checking an already-tracked job updates its details in place (title, notes, workplace type, country) without resetting its status.

No external Python packages required — everything runs on the standard library.

## Setup

```bash
git clone <this-repo-url>
cd job-tracker
cp config.example.json config.json
cp criteria.example.json criteria.json
```

Edit `criteria.json` with your domain and level terms, and add a free [Serper.dev](https://serper.dev) API key (2,500 free searches, no credit card) to `config.json`.

## Usage

### Web UI

```bash
python3 server.py
```

Open `http://127.0.0.1:8787`. Add/remove domain and level terms, filter by Place (Remote/Hybrid/All) or Location (US only/All), click **Refresh listings** to pull fresh postings, change a job's status from the dropdown, click `×` to reject a job (it stays hidden and won't reappear on future refreshes), or click **Apply** to open the posting.

### CLI

```bash
python3 job_tracker.py list                          # list tracked jobs
python3 job_tracker.py list --status new              # filter by status
python3 job_tracker.py status <id> applied            # update a job's status
python3 job_tracker.py remove <id>                     # remove a job
python3 job_tracker.py domains add "Technology"        # track a new domain term
python3 job_tracker.py domains remove "..."
python3 job_tracker.py levels add "Director"           # track a new level term
python3 job_tracker.py levels remove "..."
python3 job_tracker.py add --title "..." --company "..." --url "..."  # add a job manually
```

## How refresh works

1. For each tracked **level** term, searches Google (via Serper) restricted to Greenhouse/Lever job boards, combined with an OR-group of all tracked **domain** terms.
2. For every candidate URL, calls the board's official public API directly (`boards-api.greenhouse.io` / `api.lever.co`) — a 404 means the posting is closed, so it's skipped.
3. The posting's actual title (from the API, not the search snippet) must contain both a domain term and a level term, or it's skipped as a mismatch.
4. Live, matching postings are upserted with structured notes: employment type, remote/hybrid/onsite, US/non-US, and salary if published.

## Data & privacy

`config.json` (your API key), `criteria.json` (your domain/level terms), and `jobs.db` (your tracked jobs) are all git-ignored — only the `.example` templates are committed.
