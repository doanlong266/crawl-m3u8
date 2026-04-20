import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from flask import Flask, Response, request, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawl_to_m3u import MAX_MATCHES, START_URL, crawl


app = Flask(__name__)

MAX_STORAGE_UPLOAD_BYTES = 8 * 1024 * 1024
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def load_local_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()


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


def json_response(data, status: int = 200, cache: bool = True) -> Response:
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        status=status,
        content_type="application/json; charset=utf-8",
        headers=cors_headers(cache=cache),
    )


def text_response(text: str, content_type: str, status: int = 200, cache: bool = True) -> Response:
    return Response(
        text,
        status=status,
        content_type=content_type,
        headers=cors_headers(cache=cache),
    )


def cors_headers(cache: bool = True) -> dict:
    headers = {
        "Access-Control-Allow-Origin": "*",
    }
    headers["Cache-Control"] = "public, s-maxage=30, stale-while-revalidate=120" if cache else "no-store"
    return headers


def options_response() -> Response:
    return Response(
        "",
        status=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


def supabase_url() -> str:
    raw = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if not raw:
        raise RuntimeError("Thieu SUPABASE_URL.")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("SUPABASE_URL khong hop le.")
    return raw


def supabase_key() -> str:
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or ""
    ).strip()
    if not key:
        raise RuntimeError("Thieu SUPABASE_SERVICE_ROLE_KEY hoac SUPABASE_ANON_KEY.")
    return key


def supabase_bucket() -> str:
    bucket = (os.getenv("SUPABASE_STORAGE_BUCKET") or os.getenv("SUPABASE_BUCKET") or "crawl-m3u8").strip().strip("/")
    if not bucket:
        raise RuntimeError("SUPABASE_STORAGE_BUCKET khong hop le.")
    return bucket


def supabase_upload_dir() -> str:
    return (os.getenv("SUPABASE_UPLOAD_DIR") or "").strip().strip("/")


def supabase_public_bucket() -> bool:
    return (os.getenv("SUPABASE_PUBLIC_BUCKET") or "true").strip().lower() not in {"0", "false", "no"}


def supabase_signed_url_expires() -> int:
    raw = (os.getenv("SUPABASE_SIGNED_URL_EXPIRES") or "3600").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 3600


def safe_storage_filename(value: str) -> str:
    name = (value or "").replace("\\", "/").split("/")[-1].strip()
    name = SAFE_FILENAME_RE.sub("-", name).strip(" .-")
    if not name:
        name = "crawl-output.txt"
    return name[:120].strip(" .-") or "crawl-output.txt"


def storage_object_path(filename: str) -> str:
    folder = supabase_upload_dir()
    safe_name = safe_storage_filename(filename)
    return f"{folder}/{safe_name}" if folder else safe_name


def storage_content_type(filename: str) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".json"):
        return "application/json; charset=utf-8"
    if lower_name.endswith(".txt") or lower_name.endswith(".m3u") or lower_name.endswith(".m3u8"):
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def supabase_error(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text or response.reason
    return data.get("message") or data.get("error") or json.dumps(data, ensure_ascii=False)


def supabase_headers(key: str, content_type: str = "application/json") -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type,
    }


def public_storage_url(base_url: str, bucket: str, object_path: str) -> str:
    return f"{base_url}/storage/v1/object/public/{quote(bucket)}/{quote(object_path, safe='/')}"


def signed_storage_url(base_url: str, key: str, bucket: str, object_path: str) -> str:
    response = requests.post(
        f"{base_url}/storage/v1/object/sign/{quote(bucket)}/{quote(object_path, safe='/')}",
        headers=supabase_headers(key),
        data=json.dumps({"expiresIn": supabase_signed_url_expires()}),
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Khong tao duoc Supabase signed URL: {supabase_error(response)}")

    signed_path = response.json().get("signedURL", "")
    if not signed_path:
        raise RuntimeError("Supabase khong tra signedURL.")
    return f"{base_url}/storage/v1{signed_path}" if signed_path.startswith("/") else signed_path


def upload_to_supabase(filename: str, content: str) -> dict:
    body = content.encode("utf-8")
    if not body:
        raise ValueError("File rong, khong co noi dung de upload.")
    if len(body) > MAX_STORAGE_UPLOAD_BYTES:
        raise ValueError("File qua lon de upload qua endpoint nay.")

    base_url = supabase_url()
    key = supabase_key()
    bucket = supabase_bucket()
    object_path = storage_object_path(filename)
    response = requests.post(
        f"{base_url}/storage/v1/object/{quote(bucket)}/{quote(object_path, safe='/')}",
        headers={
            **supabase_headers(key, storage_content_type(filename)),
            "x-upsert": "true",
        },
        data=body,
        timeout=30,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(f"Khong upload duoc Supabase file: {supabase_error(response)}")

    metadata = response.json()
    shared_url = public_storage_url(base_url, bucket, object_path)
    direct_url = shared_url if supabase_public_bucket() else signed_storage_url(base_url, key, bucket, object_path)
    return {
        "bucket": bucket,
        "path": object_path,
        "name": safe_storage_filename(filename),
        "size": len(body),
        "shared_url": shared_url,
        "direct_url": direct_url,
        "storage_key": metadata.get("Key") or metadata.get("key") or f"{bucket}/{object_path}",
    }


@app.route("/api", methods=["GET", "OPTIONS"])
@app.route("/api/crawl", methods=["GET", "OPTIONS"])
def crawl_route():
    if request.method == "OPTIONS":
        return options_response()

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


@app.route("/api/supabase/upload", methods=["POST", "OPTIONS"])
def supabase_upload_route():
    if request.method == "OPTIONS":
        return options_response()

    payload = request.get_json(silent=True) or {}
    filename = payload.get("filename", "")
    content = payload.get("content", "")

    try:
        if not isinstance(content, str):
            raise ValueError("Noi dung upload khong hop le.")
        result = upload_to_supabase(filename, content)
    except ValueError as e:
        return json_response({"ok": False, "error": str(e)}, status=400, cache=False)
    except Exception as e:
        return json_response({"ok": False, "error": str(e)}, status=500, cache=False)

    return json_response({"ok": True, **result}, cache=False)


@app.route("/", methods=["GET"])
def client_route():
    return send_from_directory(str(ROOT), "index.html")


@app.route("/assets/<path:filename>", methods=["GET"])
def assets_route(filename: str):
    return send_from_directory(str(ROOT / "assets"), filename)
