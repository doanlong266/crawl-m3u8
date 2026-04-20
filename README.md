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

## Supabase upload

The client can upload the generated JSON/TXT file to Supabase Storage through the backend route:

```text
/api/supabase/upload
```

Set these values in local env and Vercel env:

```powershell
$env:SUPABASE_URL="https://your-project.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY="..."
$env:SUPABASE_STORAGE_BUCKET="link"
```

Optional upload folder:

```powershell
$env:SUPABASE_UPLOAD_DIR="exports"
```

If the bucket is public, the API returns a public URL. If the bucket is private, set:

```powershell
$env:SUPABASE_PUBLIC_BUCKET="false"
$env:SUPABASE_SIGNED_URL_EXPIRES="3600"
```

Recommended bucket setup:

```text
Bucket: link
Public: true
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
