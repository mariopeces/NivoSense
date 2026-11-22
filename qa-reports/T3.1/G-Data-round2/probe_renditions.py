"""G-Data r2 probe: fetch feratel's dead-camera frame for cam 15110/2 in many
languages and hotspot sizes, and run the builder's image_problem on each, both with
the real headers and with Last-Modified moved 3 h back (so only MD5 + dHash decide)."""
import hashlib, sys, urllib.request, urllib.error, json
from email.utils import format_datetime, parsedate_to_datetime
from datetime import timedelta
sys.path.insert(0, sys.argv[1])
import ingest_webcams as iw
out = sys.argv[2]
langs = [None, "de", "es", "en", "fr", "it", "nl", "pt", "ca", "eu", "pl", "cs", "ru", "ja", "zh", "sv", "hu", "sl", "hr", "da"]
sizes = list(range(30, 46))
seen = {}
for size in sizes:
    for lang in langs:
        url = f"https://wtvhspt.feratel.com/hotspot/{size}/15110/2.jpeg?design=v5&dcsdesign=feratel4"
        headers = {"User-Agent": "Mozilla/5.0"}
        if lang: headers["Accept-Language"] = lang
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                body = r.read(); h = r.headers
                resp = iw.ImageResponse(r.status, h.get("Content-Type"), int(h["Content-Length"]) if h.get("Content-Length") else None, body, h.get("Last-Modified"), h.get("Date"))
        except urllib.error.HTTPError as e:
            print(size, lang, "HTTP", e.code); continue
        md5 = hashlib.md5(body).hexdigest()
        real = iw.image_problem(resp, "feratel")
        old = format_datetime(parsedate_to_datetime(resp.date) - timedelta(hours=3), usegmt=True) if resp.date else None
        shifted = iw.image_problem(resp._replace(last_modified=old), "feratel")
        try:
            from PIL import Image; import io
            dims = Image.open(io.BytesIO(body)).size
            d = min((iw.dhash(body) ^ k).bit_count() for k in iw.PLACEHOLDER_DHASH)
        except Exception as e:
            dims, d = None, None
        key = md5
        if key not in seen:
            seen[key] = (size, lang)
            open(f"{out}/ph_{size}_{lang}.jpg", "wb").write(body)
        print(size, lang, dims, md5[:8], "inMD5" if md5 in iw.PLACEHOLDER_MD5 else "unknownMD5", f"dH={d}", "LM", resp.last_modified, "Date", resp.date, "| real:", real, "| LM-3h:", shifted, flush=True)
print("distinct renditions:", len(seen))
