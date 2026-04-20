import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawl_to_m3u import MAX_MATCHES, START_URL, crawl


def parse_max_matches(query: dict[str, list[str]]) -> int:
    raw = query.get("max", [""])[0]
    if not raw:
        return MAX_MATCHES
    try:
        value = int(raw)
    except ValueError:
        return MAX_MATCHES
    return max(1, min(value, MAX_MATCHES))


def parse_source_url(query: dict[str, list[str]]) -> str:
    return (query.get("link") or query.get("url") or [START_URL])[0] or START_URL


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        output_format = query.get("format", ["json"])[0].lower()
        max_matches = parse_max_matches(query)
        source_url = parse_source_url(query)

        try:
            result = crawl(max_matches=max_matches, source_url=source_url)
        except ValueError as e:
            self.send_json(
                {
                    "ok": False,
                    "error": str(e),
                },
                status=400,
            )
            return
        except Exception as e:
            self.send_json(
                {
                    "ok": False,
                    "error": str(e),
                },
                status=500,
            )
            return

        if output_format == "m3u":
            self.send_text(result["m3u"], "audio/x-mpegurl; charset=utf-8")
            return

        if output_format == "stats":
            self.send_json(result["stats"])
            return

        self.send_json(result["json"])

    def send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_common_headers("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, content_type: str, status: int = 200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_common_headers(content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_common_headers(self, content_type: str):
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, s-maxage=30, stale-while-revalidate=120")
