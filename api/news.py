"""Vercel Python serverless function: GET /api/news?topic=plan

Pulls Bing News RSS search results (title, link, source, thumbnail) for a
fixed set of urban-planning / real-estate-policy topics, classifies each
item into one of 17 Korean regions by keyword matching on the title,
dedupes, and returns JSON.

No API key required: this is Bing's public news-search RSS feed, intended
for personal, non-commercial RSS-reader use per its own feed terms.
"""
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

TOPIC_QUERIES = {
    # Bing's news-search RSS doesn't honor boolean "OR" (it's treated as a
    # literal word), so topics that need multiple keywords list them
    # separately and the results are fetched per-keyword and merged.
    "plan": ["도시계획", "도시기본계획", "지구단위계획", "공간혁신구역"],
    "development": ["도시개발", "택지개발", "신도시", "도심복합개발", "물류단지", "데이터센터", "산업단지"],
    "redevelop": ["재개발", "재건축", "정비사업", "노후계획도시"],
    "realestate": ["부동산 정책", "주택공급", "분양가"],
    "national": ["국토교통부", "광역교통", "SOC"],
}

REGION_KEYWORDS = [
    ("seoul", ["서울", "강남구", "강북구", "강서구", "강동구", "송파구", "서초구", "마포구",
               "영등포", "용산구", "종로구", "중구", "성동구", "광진구", "동대문구", "중랑구",
               "성북구", "도봉구", "노원구", "은평구", "서대문구", "양천구", "구로구", "금천구",
               "동작구", "관악구"]),
    ("gyeonggi", ["경기도", "경기", "수원", "성남", "고양", "용인", "부천", "안산", "안양",
                  "남양주", "화성", "평택", "의정부", "시흥", "파주", "김포", "광명", "군포",
                  "이천", "양주", "오산", "구리", "안성", "포천", "의왕", "하남", "여주",
                  "양평", "동두천", "과천", "가평", "연천"]),
    ("incheon", ["인천", "연수구", "남동구", "부평", "계양", "미추홀", "강화", "옹진"]),
    ("gangwon", ["강원도", "강원", "춘천", "원주", "강릉", "동해", "태백", "속초", "삼척",
                 "홍천", "횡성", "영월", "평창", "정선", "철원", "화천", "양구", "인제",
                 "고성군", "양양"]),
    ("daejeon", ["대전", "유성구", "대덕구"]),
    ("sejong", ["세종"]),
    ("chungbuk", ["충북", "청주", "충주", "제천", "진천", "음성", "증평", "괴산", "보은",
                  "옥천", "영동", "단양"]),
    ("chungnam", ["충남", "천안", "아산", "서산", "논산", "공주", "보령", "당진", "계룡",
                  "금산", "부여", "청양", "홍성", "예산", "태안"]),
    ("gwangju", ["광주광역시", "광주시", "광주"]),
    ("jeonbuk", ["전북", "전주", "군산", "익산", "정읍", "남원", "김제", "완주", "고창",
                 "부안", "임실", "순창", "진안", "무주", "장수"]),
    ("jeonnam", ["전남", "목포", "여수", "순천", "나주", "광양", "담양", "곡성", "구례",
                 "고흥", "보성", "화순", "장흥", "강진", "해남", "영암", "무안", "함평",
                 "영광", "장성", "완도", "진도", "신안"]),
    ("daegu", ["대구", "수성구", "달서구", "달성군"]),
    ("gyeongbuk", ["경북", "포항", "경주", "김천", "안동", "구미", "영주", "영천", "상주",
                   "문경", "경산", "군위", "의성", "청송", "영양", "영덕", "청도", "고령",
                   "성주", "칠곡", "예천", "봉화", "울진", "울릉"]),
    ("busan", ["부산", "해운대", "수영구", "동래구"]),
    ("ulsan", ["울산"]),
    ("gyeongnam", ["경남", "창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산",
                   "의령", "함안", "창녕", "남해", "하동", "산청", "함양", "거창", "합천"]),
    ("jeju", ["제주", "서귀포"]),
]

REGION_LABELS = {
    "seoul": "서울", "gyeonggi": "경기", "incheon": "인천", "gangwon": "강원",
    "daejeon": "대전", "sejong": "세종", "chungbuk": "충북", "chungnam": "충남",
    "gwangju": "광주", "jeonbuk": "전북", "jeonnam": "전남", "daegu": "대구",
    "gyeongbuk": "경북", "busan": "부산", "ulsan": "울산", "gyeongnam": "경남",
    "jeju": "제주",
}


def classify_region(title):
    for code, keywords in REGION_KEYWORDS:
        for kw in keywords:
            if kw in title:
                return code
    return ""


def fetch_rss(query, first=1):
    url = (
        "https://www.bing.com/news/search?q=" + urllib.parse.quote(query)
        + "&format=rss&first=" + str(first)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return resp.read()


def fetch_many(queries, pages_per_query=3):
    return fetch_all_topics({"_": queries}, pages_per_query=pages_per_query)["_"]


def fetch_all_topics(topic_queries, pages_per_query=3):
    """Fetch every (topic, query, page) job across ALL topics in one shared
    thread pool, instead of one topic at a time — so wall-clock time is
    roughly one parallel batch, not num_topics batches in a row (this is
    what kept the daily cron job over Vercel's 60s function limit)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs = [
        (topic, query, 1 + i * 10)
        for topic, queries in topic_queries.items()
        for query in queries
        for i in range(pages_per_query)
    ]

    def _one(job):
        _, query, first = job
        try:
            raw = fetch_rss(query, first=first)
        except Exception:
            return []
        try:
            return parse_items(raw)
        except ET.ParseError:
            return []

    by_topic = {topic: [] for topic in topic_queries}
    with ThreadPoolExecutor(max_workers=min(24, len(jobs) or 1)) as pool:
        futs = {pool.submit(_one, job): job[0] for job in jobs}
        for fut in as_completed(futs):
            by_topic[futs[fut]].extend(fut.result())
    return by_topic


def _local(tag):
    """Strip a '{namespace}Name' Clark-notation tag down to 'Name'.

    Bing's RSS declares the News: namespace URI as the request URL itself
    (including the query string), so it differs per request and can't be
    matched with a fixed namespace dict — comparing local names instead.
    """
    return tag.rsplit("}", 1)[-1]


def parse_items(xml_bytes):
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source = ""
        image = ""
        for child in item:
            name = _local(child.tag)
            if name == "Source" and child.text:
                source = child.text.strip()
            elif name == "Image" and child.text:
                image = child.text.strip()

        try:
            dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
            published_at = dt.replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            published_at = pub_date

        out.append({
            "title": title,
            "link": link,
            "source": source,
            "image": image,
            "publishedAt": published_at,
            "region": classify_region(title),
        })
    return out


def dedupe(items):
    seen = set()
    result = []
    for it in items:
        key = re.sub(r"\s+", "", it["title"])[:40]
        if key in seen:
            continue
        seen.add(key)
        result.append(it)
    return result


# --- storage (Supabase/Neon Postgres, provisioned via Vercel Storage) ---
# The daily cron job (api/cron/collect.py) writes here; this module's own
# handler reads from it first and only falls back to a live Bing fetch if
# the table is empty or the database isn't reachable (first boot, outage).

def _dsn(url_env):
    return os.environ.get(url_env) or os.environ.get("POSTGRES_URL")


def get_conn(url_env="POSTGRES_URL"):
    import psycopg2
    dsn = _dsn(url_env)
    if not dsn:
        raise RuntimeError("no database configured (POSTGRES_URL missing)")
    return psycopg2.connect(dsn, connect_timeout=5)


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id BIGSERIAL PRIMARY KEY,
                dedupe_key TEXT UNIQUE NOT NULL,
                topic TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                source TEXT,
                image TEXT,
                region TEXT,
                published_at TIMESTAMPTZ,
                collected_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_topic_pub ON articles (topic, published_at DESC)"
        )
    conn.commit()


def upsert_articles(conn, topic, items):
    from psycopg2.extras import execute_values

    rows = []
    for it in items:
        if not it.get("title") or not it.get("link"):
            continue
        dedupe_key = topic + "|" + re.sub(r"\s+", "", it["title"])[:60]
        rows.append((
            dedupe_key, topic, it["title"], it["link"],
            it.get("source") or "", it.get("image") or "",
            it.get("region") or "", it.get("publishedAt"),
        ))
    if not rows:
        return 0

    with conn.cursor() as cur:
        result = execute_values(
            cur,
            """
            INSERT INTO articles (dedupe_key, topic, title, link, source, image, region, published_at)
            VALUES %s
            ON CONFLICT (dedupe_key) DO NOTHING
            RETURNING id
            """,
            rows,
            fetch=True,
        )
        inserted = len(result)
    conn.commit()
    return inserted


def prune_old(conn, days=16):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM articles WHERE published_at < now() - (%s || ' days')::interval",
            (days,),
        )
    conn.commit()


def query_articles(conn, topic, limit=200):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT title, link, source, image, region, published_at
            FROM articles WHERE topic = %s
            ORDER BY published_at DESC NULLS LAST
            LIMIT %s
            """,
            (topic, limit),
        )
        rows = cur.fetchall()
    out = []
    for title, link, source, image, region, published_at in rows:
        out.append({
            "title": title,
            "link": link,
            "source": source,
            "image": image,
            "region": region or "",
            "publishedAt": published_at.isoformat() if published_at else None,
        })
    return out


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "s-maxage=300, stale-while-revalidate=1800")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        topic = (qs.get("topic") or ["plan"])[0]
        queries = TOPIC_QUERIES.get(topic, TOPIC_QUERIES["plan"])

        # 1) try the database (fast, no Bing calls — filled by the daily cron job)
        try:
            conn = get_conn(url_env="POSTGRES_URL_NON_POOLING")
            try:
                items = query_articles(conn, topic)
            finally:
                conn.close()
            if items:
                return self._send_json(200, {
                    "ok": True,
                    "topic": topic,
                    "items": items,
                    "regionLabels": REGION_LABELS,
                    "source": "db",
                })
        except Exception:
            pass  # DB not configured / empty / unreachable — fall through

        # 2) fallback: fetch live from Bing (first boot before the cron has run,
        #    or a DB outage) so the site never just shows nothing
        try:
            items = fetch_many(queries)
            items = dedupe(items)
            items.sort(key=lambda x: x["publishedAt"], reverse=True)
            return self._send_json(200, {
                "ok": True,
                "topic": topic,
                "items": items[:80],
                "regionLabels": REGION_LABELS,
                "source": "live",
            })
        except Exception as e:  # noqa: BLE001
            return self._send_json(502, {"ok": False, "error": str(e)})
