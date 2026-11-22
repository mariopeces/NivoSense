import re, json, sys, hashlib, urllib.request, io, time
from pathlib import Path
d = Path(sys.argv[1])
xml = (d/'feed.xml').read_text(encoding='utf-8')
geo = json.loads((d/'domain.geojson').read_text(encoding='utf-8'))
rings=[]
def walk(c):
    if isinstance(c[0][0], (int,float)): rings.append(c)
    else:
        for x in c: walk(x)
for f in geo.get('features',[geo]):
    g=f.get('geometry',f); walk(g['coordinates'])
xs=[p[0] for r in rings for p in r]; ys=[p[1] for r in rings for p in r]
bounds=(min(xs),min(ys),max(xs),max(ys)); print('polygon bounds', [round(v,4) for v in bounds], 'rings', len(rings))
try:
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union
    poly=unary_union([shape(f['geometry']) for f in geo['features']])
    inpoly=lambda lon,lat: poly.contains(Point(lon,lat))
    dist=lambda lon,lat: poly.distance(Point(lon,lat))
except ImportError:
    poly=None; inpoly=lambda lon,lat: None; dist=lambda a,b: None
devs=re.findall(r'<ns2:device [^>]*id="([^"]+)".*?</ns2:device>', xml, re.S)
blocks=re.findall(r'(<ns2:device [^>]*id="[^"]+".*?</ns2:device>)', xml, re.S)
W,Sx,E,N=-3.6433,36.9129,-2.5885,37.2532
out=[]
for b in blocks:
    cid=re.search(r'id="([^"]+)"',b).group(1)
    lat=float(re.search(r'<loc:latitude>([^<]+)',b).group(1)); lon=float(re.search(r'<loc:longitude>([^<]+)',b).group(1))
    url=(re.search(r'<fse:deviceUrl>([^<]+)',b) or [None,None])[1] if re.search(r'<fse:deviceUrl>([^<]+)',b) else None
    road=(re.search(r'<loc:roadName>([^<]*)',b) or [None,''])[1] if re.search(r'<loc:roadName>',b) else ''
    pk=re.search(r'<lse:kilometerPoint>([^<]*)',b); prov=re.search(r'<lse:province>([^<]*)',b)
    margin=0.1
    if W-margin<=lon<=E+margin and Sx-margin<=lat<=N+margin:
        out.append(dict(id=cid,lat=lat,lon=lon,url=url,road=road,pk=pk and pk.group(1),prov=prov and prov.group(1),
            in_bbox=W<=lon<=E and Sx<=lat<=N, in_poly=inpoly(lon,lat), dist_deg=dist(lon,lat)))
print('devices',len(blocks),'near/in bbox',len(out),'in bbox',sum(c['in_bbox'] for c in out),'in polygon',sum(bool(c['in_poly']) for c in out))
H={"User-Agent":"qa-probe"}
for c in out:
    if not c['in_bbox'] and not (c['dist_deg'] is not None and c['dist_deg']<0.05): continue
    try:
        r=urllib.request.urlopen(urllib.request.Request(c['url'],headers=H),timeout=30)
        body=r.read(); c.update(http=r.status,ctype=r.headers.get('Content-Type'),lm=r.headers.get('Last-Modified'),date=r.headers.get('Date'),bytes=len(body),md5=hashlib.md5(body).hexdigest())
        (d/'img'/f"{c['id']}.jpg").write_bytes(body)
        try:
            from PIL import Image
            c['size']=Image.open(io.BytesIO(body)).size
        except Exception as e: c['size']=str(e)
    except Exception as e:
        c['err']=repr(e)
json.dump(out,open(d/'probe.json','w'),indent=1)
for c in sorted(out,key=lambda c:(not c['in_bbox'],c['id'])):
    print(c['id'],c['road'],c['pk'],c['prov'],c['lat'],c['lon'],'bbox' if c['in_bbox'] else '----','poly' if c['in_poly'] else 'out ', c.get('md5','')[:8],c.get('bytes'),c.get('size'),c.get('lm'),c.get('err',''))
