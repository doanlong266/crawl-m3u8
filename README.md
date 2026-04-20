# Crawl API

Python crawler packaged as a Vercel Function.

## Client

```powershell
python -m flask --app api.index run --host 127.0.0.1 --port 5000
```

Open:

```text
http://127.0.0.1:5000
```

Client source:

```text
index.html
assets/css/client.css
assets/js/client.js
assets/img/brand-mark.png
```

## Endpoints

```text
/api/crawl?link=https%3A%2F%2Fhoadaotv.info%2F
/api/crawl?format=m3u&link=https%3A%2F%2Fhoadaotv.info%2F
/api/crawl?format=stats&link=https%3A%2F%2Fhoadaotv.info%2F
```

Optional:

```text
max=10
```

## Local

```powershell
python3 crawl_to_m3u.py https://hoadaotv.info/
```
