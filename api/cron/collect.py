"""Vercel Cron target: GET /api/cron/collect

Runs once a day (see vercel.json "crons"). Fetches each topic from Bing News
RSS, classifies region, and upserts into the `articles` table — this is the
only place that writes to the database. The public-facing /api/news just
reads whatever is in the table.

Vercel automatically sends `Authorization: Bearer <CRON_SECRET>` when it
invokes a scheduled cron request, if a CRON_SECRET env var is set on the
project; we verify that header so random visitors can't trigger a collection
run (and burn through the daily Bing-request budget) by hitting this URL.
"""
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import news  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        secret = os.environ.get("CRON_SECRET")
        if secret:
            auth = self.headers.get("Authorization", "")
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            key = (qs.get("key") or [""])[0]
            if auth != f"Bearer {secret}" and key != secret:
                return self._send_json(401, {"ok": False, "error": "unauthorized"})

        try:
            conn = news.get_conn(url_env="POSTGRES_URL_NON_POOLING")
        except Exception as e:  # noqa: BLE001
            return self._send_json(500, {"ok": False, "error": f"db connect failed: {e}"})

        try:
            news.ensure_schema(conn)
            by_topic = news.fetch_all_topics(news.TOPIC_QUERIES, pages_per_query=2)
            summary = {}
            for topic, items in by_topic.items():
                items = news.dedupe(items)
                inserted = news.upsert_articles(conn, topic, items)
                summary[topic] = {"fetched": len(items), "inserted": inserted}
            news.prune_old(conn, days=16)
        except Exception as e:  # noqa: BLE001
            return self._send_json(500, {"ok": False, "error": str(e)})
        finally:
            conn.close()

        return self._send_json(200, {"ok": True, "summary": summary})
