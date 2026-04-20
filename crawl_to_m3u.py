import re
import sys
import json
import hashlib
import unicodedata
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from html import unescape
from ipaddress import ip_address
from urllib.parse import urljoin, urlparse, urlunparse

START_URL = "https://hoadaotv.info/"

OUT_M3U = ""
OUT_JSON = ""
GROUP_NAME = "BenjaminDoan"

TIMEOUT = 12
MAX_MATCHES = 80  # đủ dùng, mày tăng/giảm tùy
VN_TZ = timezone(timedelta(hours=7))
DEFAULT_MATCH_DURATION = timedelta(hours=2)
DEFAULT_IMAGE_URL = ""
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}

STATUS_META = {
    "live": {
        "text": "● Live",
        "group": "🔴 Live",
        "color": "#FF0000",
    },
    "upcoming": {
        "text": "Chưa diễn ra",
        "group": "⏳ Chưa diễn ra",
        "color": "#F59E0B",
    },
    "finished": {
        "text": "Đã kết thúc",
        "group": "⚪ Đã kết thúc",
        "color": "#6B7280",
    },
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Bắt m3u8 (absolute URL) trong HTML/inline JS
M3U8_RE = re.compile(r'https?://[^\s"\'<>]+?\.m3u8(?:\?[^\s"\'<>]+)?', re.IGNORECASE)

# Bắt giờ kiểu 09:30, 11:00
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")

# Link trận thường có dạng /team-a-vs-team-b-1234567
MATCH_PATH_RE = re.compile(r"^/[^/?#]+-vs-[^/?#]+-\d+/?$", re.IGNORECASE)

def pick_text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""

def stable_id(prefix: str, text: str, n: int = 10) -> str:
    h = hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:n]
    return f"{prefix}-{h}"

def normalize_source_url(source_url: str = START_URL) -> str:
    raw = (source_url or START_URL).strip()
    if not raw:
        raw = START_URL
    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Link chỉ hỗ trợ http hoặc https")
    if not parsed.netloc:
        raise ValueError("Link không hợp lệ")
    if parsed.username or parsed.password:
        raise ValueError("Link không được chứa username/password")

    host = (parsed.hostname or "").strip().lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        raise ValueError("Host không được phép crawl")

    try:
        ip = ip_address(host.strip("[]"))
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("IP nội bộ không được phép crawl")
    except ValueError as e:
        if "không được phép" in str(e):
            raise

    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", parsed.query, ""))

def extract_match_links(home_html: str, source_url: str = START_URL) -> list[str]:
    soup = BeautifulSoup(home_html, "html.parser")
    hrefs = [a.get("href", "") for a in soup.select("a[href]")]

    # Fallback nếu HTML đổi nhẹ hoặc parser bỏ sót attribute nào đó.
    hrefs.extend(re.findall(r'href=["\']([^"\']+-vs-[^"\']+-\d+/?)[^"\']*["\']', home_html, flags=re.I))

    seen = set()
    out = []
    for href in hrefs:
        if not href:
            continue
        u = urljoin(source_url, href)
        parsed = urlparse(u)
        if not MATCH_PATH_RE.match(parsed.path):
            continue

        try:
            clean_url = normalize_source_url(f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}")
        except ValueError:
            continue
        key = clean_url.lower()
        if key not in seen:
            seen.add(key)
            out.append(clean_url)
    return out

def extract_title_like(soup: BeautifulSoup) -> str:
    """
    Ưu tiên og:title -> title -> h1/h2/h3 đầu tiên
    """
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()

    t = soup.title.get_text(" ", strip=True) if soup.title else ""
    if t:
        return t.strip()

    for sel in ["h1", "h2", "h3"]:
        h = soup.select_one(sel)
        if h:
            tx = pick_text(h)
            if tx:
                return tx
    return ""

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

def content_attr(el) -> str:
    return clean_text(el.get("content", "")) if el else ""

def find_meta_content(soup: BeautifulSoup, selectors: list[dict]) -> str:
    for attrs in selectors:
        value = content_attr(soup.find("meta", attrs=attrs))
        if value:
            return value
    return ""

def absolute_url(value: str, source_url: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    return urljoin(source_url, value)

def slugify(value: str, fallback: str = "crawl", max_length: int = 70) -> str:
    text = clean_text(value)
    if not text:
        text = fallback
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        text = fallback
    return text[:max_length].strip("-") or fallback

def compact_site_name(value: str, source_url: str) -> str:
    text = clean_text(value)
    if not text:
        return urlparse(source_url).netloc or "crawl"

    # SEO titles often look like "Brand - long offer" or "Brand | long offer".
    text = re.split(r"\s+[|–—]\s+|\s+-\s+", text, maxsplit=1)[0].strip()
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    return clean_text(text) or urlparse(source_url).netloc or "crawl"

def looks_like_domain(value: str) -> bool:
    text = clean_text(value).lower()
    return bool(re.fullmatch(r"(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+", text))

def split_teams_from_title(title: str) -> tuple[str, str]:
    """
    Cố gắng tách team A / team B từ title kiểu:
    - "A vs B"
    - "A - B"
    - "A v B"
    - "A VS B"
    """
    if not title:
        return "", ""

    t = re.sub(r"\s+", " ", title).strip()

    # Loại bớt phần thừa hay gặp
    t = re.sub(r"\s*\|\s*.*$", "", t)   # cắt sau dấu |
    t = re.sub(r"^(?:Xem\s+)?Trực\s+Tiếp\s+", "", t, flags=re.I)
    t = re.sub(r"\s*-\s*(Trực tiếp|Live).*?$", "", t, flags=re.I)
    t = re.sub(r"\s*-\s*[^-]{2,30}$", "", t)  # bỏ tên BLV ở cuối title

    # Các dấu phân cách hay dùng
    seps = [r"\s+vs\s+", r"\s+v\s+", r"\s+-\s+", r"\s+–\s+"]
    for sep in seps:
        parts = re.split(sep, t, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            a = parts[0].strip(" -–|")
            b = parts[1].strip(" -–|")
            # chặn trường hợp tách bậy quá ngắn
            if len(a) >= 2 and len(b) >= 2:
                return a, b

    return "", ""

def parse_vietnam_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(VN_TZ)
    except (TypeError, ValueError):
        return None

def parse_vietnam_time_from_iso(value: str) -> str:
    dt = parse_vietnam_datetime(value)
    return dt.strftime("%H:%M") if dt else ""

def format_datetime(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""

def extract_image_url(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return (value.get("url") or value.get("contentUrl") or "").strip()
    if isinstance(value, list):
        for item in value:
            url = extract_image_url(item)
            if url:
                return url
    return ""

def status_from_times(start_at: datetime | None, end_at: datetime | None) -> str:
    if not start_at:
        return "live"

    now = datetime.now(VN_TZ)
    if now < start_at:
        return "upcoming"

    effective_end = end_at or (start_at + DEFAULT_MATCH_DURATION)
    if now > effective_end:
        return "finished"

    return "live"

def status_text(status: str) -> str:
    return STATUS_META.get(status, STATUS_META["live"])["text"]

def team_payload(name: str, image_url: str, side: str, default_image_url: str = DEFAULT_IMAGE_URL) -> dict:
    return {
        "side": side,
        "name": name,
        "image": {
            "url": image_url or default_image_url,
            "display": "cover",
            "shape": "square",
        }
    }

def image_payload(url: str, default_image_url: str = DEFAULT_IMAGE_URL) -> dict:
    return {
        "url": url or default_image_url,
        "height": 480,
        "width": 640,
        "display": "cover",
        "shape": "square",
    }

def description_from_info(info: dict) -> str:
    parts = [info.get("status_text", "")]
    when = " ".join(p for p in [info.get("date", ""), info.get("time", "")] if p)
    if when:
        parts.append(when)
    return " - ".join(p for p in parts if p)

def unique_stream_urls(html: str) -> list[str]:
    out = []
    seen = set()
    for url in M3U8_RE.findall(html):
        clean_url = unescape(url).replace("\\/", "/")
        if clean_url not in seen:
            seen.add(clean_url)
            out.append(clean_url)
    return out

def build_stream_links(stream_urls: list[str], channel_id: str, match_url: str) -> list[dict]:
    links = []
    for idx, url in enumerate(stream_urls, 1):
        links.append({
            "id": stable_id("lnk", f"{channel_id}|{url}", 10),
            "name": "HLS" if idx == 1 else f"HLS {idx}",
            "type": "hls",
            "default": idx == 1,
            "url": url,
            "request_headers": guess_request_headers(url, match_url)
        })
    return links

def build_channel(
    info: dict,
    match_url: str,
    stream_urls: list[str],
    group: str,
    source_name: str,
    default_image_url: str = DEFAULT_IMAGE_URL,
) -> dict:
    ch_id = stable_id("benjamin", match_url, 12)
    source_id = stable_id("src", ch_id, 10)
    content_id = stable_id("ct", ch_id, 10)
    stream_id = stable_id("st", ch_id, 10)
    display_name = build_channel_name(info)
    stream_links = build_stream_links(stream_urls, ch_id, match_url)

    return {
        "id": ch_id,
        "name": display_name,
        "labels": build_labels(info, group),
        "description": description_from_info(info),
        "image": image_payload(info.get("team_a_image") or info.get("team_b_image"), default_image_url),
        "type": "single",
        "display": "text-below",
        "status": info.get("status", ""),
        "status_text": info.get("status_text", ""),
        "match_url": match_url,
        "start_time": info.get("start_at", ""),
        "end_time": info.get("end_at", ""),
        "date": info.get("date", ""),
        "time": info.get("time", ""),
        "league": info.get("league", ""),
        "team_a": info.get("team_a", ""),
        "team_b": info.get("team_b", ""),
        "team_a_image": info.get("team_a_image", ""),
        "team_b_image": info.get("team_b_image", ""),
        "teams": [
            team_payload(info.get("team_a", ""), info.get("team_a_image", ""), "home", default_image_url),
            team_payload(info.get("team_b", ""), info.get("team_b_image", ""), "away", default_image_url),
        ],
        "sources": [
            {
                "id": source_id,
                "name": source_name,
                "contents": [
                    {
                        "id": content_id,
                        "name": display_name,
                        "streams": [
                            {
                                "id": stream_id,
                                "name": group,
                                "stream_links": stream_links
                            }
                        ]
                    }
                ]
            }
        ]
    }

def build_groups(group_channels: dict[str, list[dict]]) -> list[dict]:
    groups = []
    for status in ["live", "upcoming", "finished"]:
        channels = group_channels.get(status, [])
        if not channels:
            continue
        meta = STATUS_META[status]
        groups.append({
            "id": status,
            "name": meta["group"],
            "display": "horizontal",
            "grid_number": 2,
            "channels": channels
        })
    return groups or [
        {
            "id": "live",
            "name": STATUS_META["live"]["group"],
            "display": "horizontal",
            "grid_number": 2,
            "channels": []
        }
    ]

def iter_json_ld_objects(data):
    if isinstance(data, list):
        for item in data:
            yield from iter_json_ld_objects(item)
    elif isinstance(data, dict):
        yield data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from iter_json_ld_objects(item)

def extract_sports_event(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for obj in iter_json_ld_objects(data):
            event_type = obj.get("@type")
            if event_type == "SportsEvent" or (isinstance(event_type, list) and "SportsEvent" in event_type):
                return obj
    return {}

def extract_source_metadata(home_html: str, source_url: str) -> dict:
    soup = BeautifulSoup(home_html, "html.parser")
    parsed = urlparse(source_url)
    fallback_name = parsed.netloc or "crawl"

    title = find_meta_content(
        soup,
        [
            {"property": "og:title"},
            {"name": "twitter:title"},
        ],
    )
    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))
    if not title:
        title = fallback_name

    description = find_meta_content(
        soup,
        [
            {"name": "description"},
            {"property": "og:description"},
            {"name": "twitter:description"},
        ],
    )

    image_url = find_meta_content(
        soup,
        [
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "og:logo"},
        ],
    )

    site_name = find_meta_content(
        soup,
        [
            {"property": "og:site_name"},
            {"name": "application-name"},
        ],
    )

    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for obj in iter_json_ld_objects(data):
            obj_type = obj.get("@type")
            types = obj_type if isinstance(obj_type, list) else [obj_type]
            if "Organization" in types or "WebSite" in types:
                if not site_name:
                    site_name = clean_text(obj.get("name", ""))
                if not description:
                    description = clean_text(obj.get("description", ""))
                if not image_url:
                    image_url = extract_image_url(obj.get("logo")) or extract_image_url(obj.get("image"))

    if not image_url:
        for link in soup.find_all("link"):
            rel = link.get("rel", "")
            rel_text = " ".join(rel).lower() if isinstance(rel, list) else str(rel).lower()
            if "icon" in rel_text and link.get("href"):
                image_url = link.get("href", "")
                break

    if not image_url:
        image_url = "/favicon.ico"

    title_short_name = compact_site_name(title, source_url)
    site_display_name = compact_site_name(site_name, source_url) if site_name else ""
    short_name = title_short_name if looks_like_domain(site_display_name) else (site_display_name or title_short_name)
    display_name = short_name
    absolute_image_url = absolute_url(image_url, source_url)
    output_base = slugify(short_name, fallback=slugify(fallback_name, fallback="crawl"), max_length=40)

    return {
        "id": output_base,
        "title": title,
        "site_name": display_name,
        "short_name": short_name,
        "description": description,
        "image": absolute_image_url,
        "source_url": source_url,
        "output_base": output_base,
    }

def parse_match_info(match_html: str) -> dict:
    """
    Lấy giờ + team A/B từ title/og:title hoặc heading.
    """
    soup = BeautifulSoup(match_html, "html.parser")
    full_text = soup.get_text("\n", strip=True)
    event = extract_sports_event(soup)
    start_at_dt = parse_vietnam_datetime(event.get("startDate", ""))
    end_at_dt = parse_vietnam_datetime(event.get("endDate", ""))
    status = status_from_times(start_at_dt, end_at_dt)

    # giờ
    if start_at_dt:
        hhmm = start_at_dt.strftime("%H:%M")
        date_text = start_at_dt.strftime("%Y-%m-%d")
    else:
        time_m = TIME_RE.search(full_text)
        hhmm = time_m.group(1) if time_m else ""
        date_text = ""

    title_like = extract_title_like(soup)
    team_a, team_b = "", ""
    team_a_image, team_b_image = "", ""

    competitors = event.get("competitor", [])
    if isinstance(competitors, list) and len(competitors) >= 2:
        home = competitors[0] if isinstance(competitors[0], dict) else {}
        away = competitors[1] if isinstance(competitors[1], dict) else {}
        team_a = home.get("name", "")
        team_b = away.get("name", "")
        team_a_image = extract_image_url(home.get("image"))
        team_b_image = extract_image_url(away.get("image"))

    if not team_a or not team_b:
        team_a, team_b = split_teams_from_title(event.get("name", "") or title_like)

    # fallback: thử tìm trong các heading nếu title_like không tách được
    if not team_a and not team_b:
        headings = [pick_text(h) for h in soup.select("h1,h2,h3") if pick_text(h)]
        for h in headings[:5]:
            a, b = split_teams_from_title(h)
            if a and b:
                team_a, team_b = a, b
                break

    return {
        "time": hhmm.strip(),
        "date": date_text,
        "start_at": format_datetime(start_at_dt),
        "end_at": format_datetime(end_at_dt),
        "status": status,
        "status_text": status_text(status),
        "league": event.get("location", {}).get("name", "") if isinstance(event.get("location"), dict) else "",
        "team_a": team_a.strip(),
        "team_b": team_b.strip(),
        "team_a_image": team_a_image.strip(),
        "team_b_image": team_b_image.strip(),
        "title_like": title_like.strip()
    }

def build_channel_name(info: dict) -> str:
    # Mày muốn ngắn gọn để UI hiện đẹp
    if info["team_a"] and info["team_b"]:
        return f'{info["team_a"]} vs {info["team_b"]}'.strip()
    if info["title_like"]:
        return info["title_like"]
    return "Live"

def build_labels(info: dict, group: str) -> list[dict]:
    status = info.get("status", "live")
    meta = STATUS_META.get(status, STATUS_META["live"])
    labels = [
        {
            "position": "top-left",
            "text": meta["text"],
            "color": meta["color"],
            "text_color": "#FFFFFF"
        },
        {
            "position": "bottom-left",
            "text": group,
            "color": "#0066CC",
            "text_color": "#FFFFFF"
        }
    ]
    if info.get("time"):
        labels.append(
            {
                "position": "center",
                "text": info["time"],
                "color": "#4CAF50",
                "text_color": "#FFFFFF"
            }
        )
    return labels

def guess_request_headers(m3u8_url: str, match_url: str) -> list[dict]:
    """
    Một số CDN cần Referer. Nếu mày biết chắc referer nào thì set cứng ở đây.
    Default: dùng chính match_url làm Referer (an toàn hơn để chống 403).
    """
    return [{"key": "Referer", "value": match_url}]

def create_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "IPTV-Match-Crawler/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s

def build_m3u_text(m3u_items: list[dict]) -> str:
    m3u_lines = ["#EXTM3U"]
    for it in m3u_items:
        m3u_lines.append(f'#EXTINF:-1 group-title="{it["group"]}",{it["name"]}')
        m3u_lines.append(it["url"])
    return "\n".join(m3u_lines) + "\n"

def build_buncha_json(
    group_channels: dict[str, list[dict]],
    source_url: str = START_URL,
    source_metadata: dict | None = None,
) -> dict:
    source_metadata = source_metadata or {}
    name = source_metadata.get("short_name") or source_metadata.get("site_name") or source_metadata.get("title") or urlparse(source_url).netloc or "Crawl"
    description = source_metadata.get("description") or name
    image_url = source_metadata.get("image", "")
    return {
        "id": source_metadata.get("id") or slugify(name),
        "url": source_url,
        "name": name,
        "color": "#1cb57a",
        "description": description,
        "image": {
            "url": image_url
        },
        "groups": build_groups(group_channels),
        "option": {
            "save_history": False,
            "save_search_history": False,
            "save_wishlist": False
        }
    }

def crawl(max_matches: int = MAX_MATCHES, source_url: str = START_URL, logger=None) -> dict:
    source_url = normalize_source_url(source_url)
    s = create_session()
    home = s.get(source_url, timeout=TIMEOUT)
    home.raise_for_status()

    source_metadata = extract_source_metadata(home.text, source_url)
    source_name = source_metadata.get("site_name") or source_metadata.get("title") or urlparse(source_url).netloc
    source_image = source_metadata.get("image", "")
    match_links = extract_match_links(home.text, source_url)[:max_matches]
    if logger:
        logger(f"Nguồn: {source_metadata.get('title', source_url)}")
        logger(f"Logo/Image: {source_image}")
        logger(f"Tìm thấy số trang trận đấu: {len(match_links)}")

    m3u_items = []
    group_channels = {"live": [], "upcoming": [], "finished": []}
    seen_m3u8 = set()
    match_stats = []

    for idx, match_url in enumerate(match_links, 1):
        try:
            r = s.get(match_url, timeout=TIMEOUT)
            if r.status_code != 200:
                match_stats.append({
                    "url": match_url,
                    "status_code": r.status_code,
                    "error": "Non-200 response"
                })
                continue
            html = r.text
        except Exception as e:
            match_stats.append({
                "url": match_url,
                "error": str(e)
            })
            continue

        info = parse_match_info(html)
        base_name = build_channel_name(info)

        # lấy tất cả m3u8 duy nhất theo thứ tự
        m3u8s = unique_stream_urls(html)
        stream_urls = m3u8s if info["status"] == "live" else []
        status = info["status"] if info["status"] in group_channels else "upcoming"
        group_channels[status].append(
            build_channel(info, match_url, stream_urls, GROUP_NAME, source_name, source_image)
        )

        added_count = 0
        if info["status"] == "live":
            for link_idx, u in enumerate(stream_urls, 1):
                if u in seen_m3u8:
                    continue
                seen_m3u8.add(u)

                display_name = base_name if link_idx == 1 else f"{base_name} (Link {link_idx})"
                m3u_items.append({
                    "name": (f'[{info["time"]}] {display_name}'.strip() if info.get("time") else display_name),
                    "url": u,
                    "group": GROUP_NAME
                })
                added_count += 1

        match_stats.append({
            "url": match_url,
            "name": base_name,
            "status": info["status"],
            "status_text": info["status_text"],
            "time": info.get("time", ""),
            "m3u8_found": len(m3u8s),
            "m3u_added": added_count
        })

        if logger:
            logger(
                f"[{idx}/{len(match_links)}] {match_url} | {info['status_text']} | "
                f"Tìm thấy {len(m3u8s)} m3u8 | Đã thêm M3U {added_count} link"
            )

    counts = {status: len(channels) for status, channels in group_channels.items()}
    return {
        "json": build_buncha_json(group_channels, source_url, source_metadata),
        "m3u": build_m3u_text(m3u_items),
        "stats": {
            "source": source_url,
            "source_metadata": source_metadata,
            "matches_found": len(match_links),
            "channels": sum(counts.values()),
            "m3u_items": len(m3u_items),
            "groups": counts,
            "matches": match_stats,
        }
    }

def main():
    source_url = sys.argv[1] if len(sys.argv) > 1 else START_URL
    try:
        result = crawl(source_url=source_url, logger=print)
    except Exception as e:
        print(f"Lỗi khi crawl: {e}")
        return

    output_base = result["stats"]["source_metadata"].get("output_base", "crawl")
    out_m3u = OUT_M3U or f"{output_base}.txt"
    out_json = OUT_JSON or f"{output_base}.json"

    with open(out_m3u, "w", encoding="utf-8", newline="\n") as f:
        f.write(result["m3u"])

    with open(out_json, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result["json"], f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\nXONG -> {out_m3u} | Tổng số kênh M3U: {result['stats']['m3u_items']}")
    print(f"XONG -> {out_json} | Tổng số channels JSON: {result['stats']['channels']}")

if __name__ == "__main__":
    main()
