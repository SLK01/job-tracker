#!/usr/bin/env python3
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

import job_tracker as jt
import refresh as rf

ROOT = Path(__file__).parent
INDEX_HTML = ROOT / "index.html"
PORT = 8787

JOB_STATUS_RE = re.compile(r"^/api/jobs/(\d+)/status$")
JOB_ID_RE = re.compile(r"^/api/jobs/(\d+)$")
CRITERIA_KIND_RE = re.compile(r"^/api/criteria/(domains|levels)$")
CRITERIA_TERM_RE = re.compile(r"^/api/criteria/(domains|levels)/(.+)$")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/jobs":
            qs = parse_qs(parsed.query)
            conn = jt.get_db()
            query = ("SELECT id, title, company, location, url, source, status, date_found, notes, workplace_type, country "
                     "FROM jobs WHERE 1=1")
            params = []
            if "status" in qs:
                query += " AND status = ?"
                params.append(qs["status"][0])
            else:
                query += " AND status != 'rejected'"
            place = qs.get("place", ["all"])[0]
            if place in ("remote", "hybrid", "onsite"):
                query += " AND workplace_type = ?"
                params.append(place)
            if qs.get("country", ["all"])[0] == "us":
                query += " AND country = 'US'"
            query += " ORDER BY date_found DESC, id DESC"
            rows = conn.execute(query, params).fetchall()
            conn.close()
            cols = ["id", "title", "company", "location", "url", "source", "status", "date_found", "notes",
                    "workplace_type", "country"]
            jobs = [dict(zip(cols, r)) for r in rows]
            self._send_json(jobs)
            return

        if parsed.path == "/api/criteria":
            self._send_json(jt.load_criteria())
            return

        if parsed.path == "/api/statuses":
            self._send_json(jt.STATUSES)
            return

        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlsplit(self.path)

        m = JOB_STATUS_RE.match(parsed.path)
        if m:
            job_id = int(m.group(1))
            data = self._read_json()
            status = data.get("status")
            if status not in jt.STATUSES:
                self._send_json({"error": "invalid status"}, 400)
                return
            conn = jt.get_db()
            cur = conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
            conn.commit()
            conn.close()
            if cur.rowcount == 0:
                self._send_json({"error": "job not found"}, 404)
                return
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/refresh":
            result = rf.run_refresh()
            self._send_json(result)
            return

        m = CRITERIA_KIND_RE.match(parsed.path)
        if m:
            kind = m.group(1)
            data = self._read_json()
            term = (data.get("term") or "").strip()
            if not term:
                self._send_json({"error": "term required"}, 400)
                return
            criteria = jt.load_criteria()
            terms = criteria.setdefault(kind, [])
            if term not in terms:
                terms.append(term)
                jt.save_criteria(criteria)
            self._send_json({"ok": True, "criteria": criteria})
            return

        self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urlsplit(self.path)

        m = JOB_ID_RE.match(parsed.path)
        if m:
            job_id = int(m.group(1))
            conn = jt.get_db()
            cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            conn.close()
            self._send_json({"ok": cur.rowcount > 0})
            return

        m = CRITERIA_TERM_RE.match(parsed.path)
        if m:
            kind, term = m.group(1), unquote(m.group(2))
            criteria = jt.load_criteria()
            terms = criteria.setdefault(kind, [])
            if term in terms:
                terms.remove(term)
                jt.save_criteria(criteria)
            self._send_json({"ok": True, "criteria": criteria})
            return
        self._send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    jt.get_db().close()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Job tracker running at http://127.0.0.1:{PORT}")
    server.serve_forever()
