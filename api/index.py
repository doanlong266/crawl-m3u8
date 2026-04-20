import json
import sys
from pathlib import Path

from flask import Flask, Response, request, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawl_to_m3u import MAX_MATCHES, START_URL, crawl


app = Flask(__name__)


def parse_max_matches() -> int:
    raw = request.args.get("max", "")
    if not raw:
        return MAX_MATCHES
    try:
        value = int(raw)
    except ValueError:
        return MAX_MATCHES
    return max(1, min(value, MAX_MATCHES))


def parse_source_url() -> str:
    return request.args.get("link") or request.args.get("url") or START_URL


def json_response(data, status: int = 200) -> Response:
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        status=status,
        content_type="application/json; charset=utf-8",
        headers=cors_headers(),
    )


def text_response(text: str, content_type: str, status: int = 200) -> Response:
    return Response(
        text,
        status=status,
        content_type=content_type,
        headers=cors_headers(),
    )


def cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, s-maxage=30, stale-while-revalidate=120",
    }


@app.route("/api", methods=["GET", "OPTIONS"])
@app.route("/api/crawl", methods=["GET", "OPTIONS"])
def crawl_route():
    if request.method == "OPTIONS":
        return Response(
            "",
            status=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    output_format = request.args.get("format", "json").lower()

    try:
        result = crawl(max_matches=parse_max_matches(), source_url=parse_source_url())
    except ValueError as e:
        return json_response({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return json_response({"ok": False, "error": str(e)}, status=500)

    if output_format == "m3u":
        return text_response(result["m3u"], "audio/x-mpegurl; charset=utf-8")

    if output_format == "stats":
        return json_response(result["stats"])

    return json_response(result["json"])


@app.route("/", methods=["GET"])
def client_route():
    return send_from_directory(str(ROOT), "index.html")


@app.route("/assets/<path:filename>", methods=["GET"])
def assets_route(filename: str):
    return send_from_directory(str(ROOT / "assets"), filename)
