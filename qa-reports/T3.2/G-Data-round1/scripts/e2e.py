import sys, json, shutil
from pathlib import Path
be=Path(sys.argv[1]); dl=Path(sys.argv[2]); out=Path(sys.argv[3])
sys.path.insert(0,str(be))
import ingest_webcams as iw, validate_webcam_artifact as va
cfg=iw.load_config(be/'webcam_sources.json')
cfg['sources']=[s for s in cfg['sources'] if s['id']=='dgt']
ph=(dl/'img'/'312.jpg').read_bytes(); nv=(dl/'nat'/'c69be961d85234d6ee32eb9295f33498.jpg').read_bytes(); real=(dl/'img'/'169624.jpg').read_bytes()
def fetch(u):
    b = nv if '168445' in u else real if '169624' in u else ph
    return iw.ImageResponse(200,'image/jpeg',len(b),b,"Sun, 22 Nov 2026 05:53:13 GMT","Sun, 22 Nov 2026 05:59:04 GMT")
if out.exists(): shutil.rmtree(out)
store=iw.LocalStillStore(out/'data'/'webcam-stills','data/webcam-stills/')
cams,log=iw.build_catalog(cfg,store,fetch=fetch,fetch_xml=lambda u:(dl/'feed.xml').read_bytes())
for c in cams: print('KEPT',c['id'],c['name'],c['status'],c['thumbnail_url'])
print('dropped',sum(r.get('catalogue')=='dropped' for r in log))
(out/'data').mkdir(parents=True,exist_ok=True); json.dump(cams,open(out/'data'/'webcams.json','w'))
print('validator errors:',va.validate(out,iw.load_config(be/'webcam_sources.json')))
