# Job Tracker

A small local tool for tracking open leadership/engineering roles by job title. Tracks jobs through a status pipeline (new → interested → applied → interviewing → rejected/offer), with both a CLI and a local web UI backed by the same SQLite database.

Refreshing pulls candidate postings from Google (via [Serper.dev](https://serper.dev)) restricted to `job-boards.greenhouse.io` and `jobs.lever.co`, then verifies and enriches each one using Greenhouse's and Lever's official public job-board APIs — so closed/filled postings are automatically skipped rather than imported as dead links.

No external Python packages required — everything runs on the standard library.

## Setup

```bash
git clone <this-repo-url>
cd job-tracker
cp config.example.json config.json
cp titles.example.json titles.json
```

Edit `titles.json` with the job titles you want to track, and add a free [Serper.dev](https://serper.dev) API key (2,500 free searches, no credit card) to `config.json`.

## Usage

### Web UI

```bash
python3 server.py
```

Open `http://127.0.0.1:8787`. Add/remove target titles, click **Refresh listings** to pull fresh postings, change a job's status from the dropdown, or click **Apply** to open the posting.

### CLI

```bash
python3 job_tracker.py list                       # list tracked jobs
python3 job_tracker.py list --status new           # filter by status
python3 job_tracker.py status <id> applied         # update a job's status
python3 job_tracker.py remove <id>                 # remove a job
python3 job_tracker.py titles add "SVP Engineering" # track a new title
python3 job_tracker.py titles remove "..."
python3 job_tracker.py add --title "..." --company "..." --url "..."  # add a job manually
```

## How refresh works

1. Searches Google (via Serper) for each tracked title, restricted to Greenhouse/Lever job boards.
2. For every candidate URL, calls the board's official public API directly (`boards-api.greenhouse.io` / `api.lever.co`) — a 404 means the posting is closed, so it's skipped.
3. Live postings are inserted with structured notes: employment type, remote/onsite, and salary if published.

## Data & privacy

`config.json` (your API key), `titles.json` (your tracked titles), and `jobs.db` (your tracked jobs) are all git-ignored — only the `.example` templates are committed.
