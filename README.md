# Crawl API

Python crawler packaged as a Vercel Function.

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
