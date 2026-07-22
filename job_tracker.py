#!/usr/bin/env python3
import argparse
import json
import sqlite3
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent
DB_PATH = ROOT / "jobs.db"
TITLES_PATH = ROOT / "titles.json"

STATUSES = ["new", "interested", "applied", "interviewing", "rejected", "offer"]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            url TEXT UNIQUE,
            source TEXT,
            date_found TEXT,
            status TEXT DEFAULT 'new',
            notes TEXT
        )
    """)
    return conn


def load_titles():
    if not TITLES_PATH.exists():
        return []
    return json.loads(TITLES_PATH.read_text())


def save_titles(titles):
    TITLES_PATH.write_text(json.dumps(titles, indent=2))


def cmd_titles_list(args):
    titles = load_titles()
    if not titles:
        print("No titles configured.")
        return
    for t in titles:
        print(f"- {t}")


def cmd_titles_add(args):
    titles = load_titles()
    if args.title in titles:
        print(f"Already tracking: {args.title}")
        return
    titles.append(args.title)
    save_titles(titles)
    print(f"Added: {args.title}")


def cmd_titles_remove(args):
    titles = load_titles()
    if args.title not in titles:
        print(f"Not found: {args.title}")
        return
    titles.remove(args.title)
    save_titles(titles)
    print(f"Removed: {args.title}")


def cmd_add(args):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO jobs (title, company, location, url, source, date_found, status, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, 'new', ?)",
            (args.title, args.company, args.location, args.url, args.source, date.today().isoformat(), args.notes),
        )
        conn.commit()
        print(f"Added job: {args.title} @ {args.company}")
    except sqlite3.IntegrityError:
        print(f"Already tracked (duplicate URL): {args.url}")
    finally:
        conn.close()


def cmd_import(args):
    data = json.loads(Path(args.file).read_text())
    conn = get_db()
    added, skipped = 0, 0
    for job in data:
        try:
            conn.execute(
                "INSERT INTO jobs (title, company, location, url, source, date_found, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'new')",
                (
                    job["title"],
                    job["company"],
                    job.get("location", ""),
                    job.get("url", ""),
                    job.get("source", ""),
                    date.today().isoformat(),
                ),
            )
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
    conn.commit()
    conn.close()
    print(f"Imported {added} job(s), skipped {skipped} duplicate(s).")


def cmd_list(args):
    conn = get_db()
    query = "SELECT id, title, company, location, status, date_found, url FROM jobs WHERE 1=1"
    params = []
    if args.status:
        query += " AND status = ?"
        params.append(args.status)
    if args.company:
        query += " AND company LIKE ?"
        params.append(f"%{args.company}%")
    query += " ORDER BY date_found DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    if not rows:
        print("No jobs found.")
        return
    for r in rows:
        job_id, title, company, location, status, date_found, url = r
        print(f"[{job_id}] {title} @ {company} ({location or 'n/a'}) — {status} — found {date_found}")
        if url:
            print(f"      {url}")


def cmd_remove(args):
    conn = get_db()
    cur = conn.execute("DELETE FROM jobs WHERE id = ?", (args.job_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        print(f"No job with id {args.job_id}")
    else:
        print(f"Removed job {args.job_id}")


def cmd_status(args):
    if args.status not in STATUSES:
        print(f"Invalid status. Choose from: {', '.join(STATUSES)}")
        return
    conn = get_db()
    cur = conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (args.status, args.job_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        print(f"No job with id {args.job_id}")
    else:
        print(f"Job {args.job_id} -> {args.status}")


def main():
    parser = argparse.ArgumentParser(description="Track open leadership eng jobs by title.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("titles", help="manage target job titles")
    tsub = t.add_subparsers(dest="tcmd", required=True)
    tsub.add_parser("list").set_defaults(func=cmd_titles_list)
    ta = tsub.add_parser("add")
    ta.add_argument("title")
    ta.set_defaults(func=cmd_titles_add)
    tr = tsub.add_parser("remove")
    tr.add_argument("title")
    tr.set_defaults(func=cmd_titles_remove)

    a = sub.add_parser("add", help="manually add a job")
    a.add_argument("--title", required=True)
    a.add_argument("--company", required=True)
    a.add_argument("--location", default="")
    a.add_argument("--url", default="")
    a.add_argument("--source", default="")
    a.add_argument("--notes", default="")
    a.set_defaults(func=cmd_add)

    i = sub.add_parser("import", help="bulk import jobs from a JSON file")
    i.add_argument("file")
    i.set_defaults(func=cmd_import)

    l = sub.add_parser("list", help="list tracked jobs")
    l.add_argument("--status", choices=STATUSES)
    l.add_argument("--company")
    l.set_defaults(func=cmd_list)

    rm = sub.add_parser("remove", help="remove a tracked job")
    rm.add_argument("job_id", type=int)
    rm.set_defaults(func=cmd_remove)

    s = sub.add_parser("status", help="update a job's status")
    s.add_argument("job_id", type=int)
    s.add_argument("status", choices=STATUSES)
    s.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
