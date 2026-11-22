import sys, os, json, io
sys.path.insert(0, sys.argv[1])
from backend import ingest_webcams as w
from PIL import Image, ImageStat
from collections import Counter
d=sys.argv[2]; out=[]
for n in sorted(os.listdir(d)):
    b=open(os.path.join(d,n),"rb").read()
    resp=w.ImageResponse(200,"image/jpeg",b,None,None,len(b)) if False else None
    try:
        with Image.open(io.BytesIO(b)) as im: g=im.convert("L"); size=im.size
    except Exception as e:
        out.append((n,"undecodable",None,None,None)); continue
    p=w.picture_problem(g,"DGT")
    W,H=g.size; band=round(H*w.OVERLAY_BAND)
    st=ImageStat.Stat(g.crop((0,band,W,H-band)))
    small=w.thumbnail(g)
    dist={k:sum(abs(a-c) for a,c in zip(small,r))/len(small) for k,r in w.reference_thumbnails().items()}
    out.append((n,p,round(st.mean[0],1),round(st.stddev[0],1),{k:round(v,1) for k,v in dist.items()},size,len(b)))
json.dump(out,open(sys.argv[3],"w"))
print(Counter((o[1] or "PASS").split(" (")[0] for o in out))
