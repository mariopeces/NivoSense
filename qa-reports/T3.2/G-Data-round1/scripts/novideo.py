import sys,json,urllib.request,io
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageStat
rows=json.load(open(sys.argv[1]))
cand=[r[0] for r in rows if r[1]==200 and 0<r[3]<12000]
def chk(u):
    try:
        b=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"qa-probe"}),timeout=20).read()
        im=Image.open(io.BytesIO(b)).convert('L'); W,H=im.size
        body=im.crop((0,int(H*0.15),W,int(H*0.85)))
        s=ImageStat.Stat(body); return u,im.size,len(b),round(s.mean[0],1),round(s.stddev[0],1)
    except Exception as e: return u,repr(e)[:40]
for r in ThreadPoolExecutor(8).map(chk,cand): print(*r)
