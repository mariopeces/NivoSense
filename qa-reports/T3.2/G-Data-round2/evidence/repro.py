import sys, json, tempfile, shutil
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from backend import ingest_webcams as w
from backend.ingest_webcams import ImageResponse, LocalStillStore, build_catalog, parse_http_date
from email.utils import format_datetime
from datetime import datetime, timedelta, UTC
fx=Path(sys.argv[2])
# one in-domain DGT cam (dgt-312, A-395 PK 28.9, real position) on the shipped region config
FEED=f"""<?xml version="1.0"?><d2:payload xmlns:d2="urn:p" xmlns:device="urn:d" xmlns:loc="urn:l" xmlns:ext="urn:e">
<device:device id="312"><device:typeOfDevice>camera</device:typeOfDevice><device:pointLocation><loc:roadName>A-395</loc:roadName>
<loc:latitude>37.105434</loc:latitude><loc:longitude>-3.426944</loc:longitude></device:pointLocation>
<ext:deviceUrl>https://etraffic.dgt.es/camarasEtraffic/312.jpg</ext:deviceUrl></device:device></d2:payload>"""
cfg=json.loads((Path(sys.argv[1])/"backend/webcam_sources.json").read_text())
cfg["sources"]=[s for s in cfg["sources"] if s["id"]=="dgt"]
import os; os.chdir(sys.argv[1])
def run(store, body, lm, now):
    f=lambda url: ImageResponse(200,"image/jpeg",len(body),body,format_datetime(lm,usegmt=True),format_datetime(now,usegmt=True))
    cams,log=build_catalog(cfg,store,f,lambda u: FEED.encode(),now=now)
    r=[x for x in log if x.get("id")=="dgt-312"][0]
    return r["catalogue"], r["status"], r.get("problem"), r.get("captured_at")
t0=datetime(2026,11,22,8,0,tzinfo=UTC)
print("== A: solid-colour / corrupt frames, fresh LM, no history")
for n in ["164375.jpg","168074.jpg","1086.jpg"]:
    d=Path(tempfile.mkdtemp()); s=LocalStillStore(d,"data/webcam-stills/")
    print(n, run(s,(fx/n).read_bytes(), t0-timedelta(minutes=2), t0))
print("== B: 162889 frame (burned in 2026-10-02), DGT re-stamps it every 10 min")
d=Path(tempfile.mkdtemp()); s=LocalStillStore(d,"data/webcam-stills/")
body=(fx/"162889.jpg").read_bytes()
for k,(mins,state) in enumerate([(0,"none"),(60,"kept"),(90,"LOST (restore failed)"),(150,"kept"),(211,"kept")]):
    if state.startswith("LOST"): (d/"state.json").unlink()
    now=t0+timedelta(minutes=mins); lm=now-timedelta(minutes=3)
    print(f"run t0+{mins}min state={state}:", run(s,body,lm,now))
print("== C: corrupt state.json")
(d/"state.json").write_text("{broken")
now=t0+timedelta(minutes=300); print(run(s,body,now-timedelta(minutes=3),now))
