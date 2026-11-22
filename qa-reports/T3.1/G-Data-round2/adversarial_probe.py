"""G-Data r2 adversarial probe on PR #8 @ 2f28bf1. Feeds real fetched bytes through
the builder's probe_camera_image / build_catalog with crafted headers.
usage: python -I adversarial_probe.py <backend dir> <stills dir from a live run> <placeholder dir>"""
import sys, glob, json, copy, hashlib
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
sys.path.insert(0, sys.argv[1])
import ingest_webcams as iw
stills, ph = sys.argv[2], sys.argv[3]
now = datetime.now(timezone.utc).replace(microsecond=0)
H = lambda dt: format_datetime(dt, usegmt=True)
real_t = open(glob.glob(f"{stills}/cetursa-15111-0/*thumbnail*")[0], "rb").read()
real_l = open(glob.glob(f"{stills}/cetursa-15111-0/*large*")[0], "rb").read()
cam = {"id": "x", "provider": "feratel", "thumbnail_url": "t", "large_url": "l"}

def run(label, t_body, l_body, t_lm, l_lm, date=now):
    resp = {"t": iw.ImageResponse(200, "image/jpeg", len(t_body), t_body, t_lm and H(t_lm), H(date)),
            "l": iw.ImageResponse(200, "image/jpeg", len(l_body), l_body, l_lm and H(l_lm), H(date))}
    rec, bodies = iw.probe_camera_image(dict(cam), lambda u: resp[u])
    print(f"{label}: status={rec['status']} captured_at={rec['captured_at']} problem={rec['problem']}")

# Every distinct placeholder rendition fetched (sizes 35-45, 20 Accept-Language values)
phs = sorted(glob.glob(f"{ph}/ph_*.jpg"))
bad = []
for f in phs:
    b = open(f, "rb").read()
    for lm in (now, now - timedelta(hours=3)):
        resp = iw.ImageResponse(200, "image/jpeg", len(b), b, H(lm), H(now))
        if iw.image_problem(resp, "feratel") is None: bad.append((f, lm))
print(f"A. {len(phs)} distinct placeholder renditions x (LM=Date, LM=Date-3h): passed as frame = {len(bad)}")
run("B. frozen camera: real 18:08 frame re-served with fresh Last-Modified (now-5min)", real_t, real_l, now - timedelta(minutes=5), now - timedelta(minutes=5))
run("C. stale camera: real frame, true Last-Modified 21 Nov 17:08, served 3 days later", real_t, real_l, datetime(2026,11,21,17,8,5,tzinfo=timezone.utc), datetime(2026,11,21,17,8,5,tzinfo=timezone.utc), date=now + timedelta(days=3))
run("D. clock skew: real frame with Last-Modified 50 min in the future", real_t, real_l, now + timedelta(minutes=50), now + timedelta(minutes=50))
run("E. real frame, no Last-Modified header", real_t, real_l, None, None)
run("F. thumbnail real, large is a placeholder 38 rendition with old LM", real_t, open(phs[0],'rb').read(), now - timedelta(hours=1), now - timedelta(hours=1))
run("G. thumbnail and large with different Last-Modified", real_t, real_l, now - timedelta(hours=1), now - timedelta(hours=2))

# H. shared-bytes guard alone, on live providers: disable MD5, dHash and the LM==Date guard
iw.PLACEHOLDER_MD5 = frozenset({"c92fb6440dc51109074769bcad5c7de9"})  # keep DGT
iw.PLACEHOLDER_DHASH_MAX_BITS = -1
iw.GENERATED_ON_REQUEST_SECONDS = -1
class Mem:
    def put(self, key, body, ct): return "data/webcam-stills/" + key
cams, log = iw.build_catalog(iw.load_config(iw.DEFAULT_CONFIG), Mem())
print("H. live run with only the shared-bytes guard:")
for r in log:
    if r["id"].startswith("cetursa"): print("  ", r["id"], r["status"], r["problem"])
