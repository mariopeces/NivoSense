import re, sys, hashlib, urllib.request, random, json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
d=Path(sys.argv[1]); out=Path(sys.argv[2]); out.mkdir(exist_ok=True)
urls=re.findall(r'<fse:deviceUrl>([^<]+)', (d/'feed.xml').read_text(encoding='utf-8'))
random.seed(7); sample=random.sample(urls,500)
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"qa-probe"}),timeout=20); b=r.read()
        return u,r.status,r.headers.get('Content-Type'),len(b),hashlib.md5(b).hexdigest(),r.headers.get('Last-Modified'),r.headers.get('Date'),b
    except Exception as e: return u,repr(e)[:60],None,0,None,None,None,b''
res=list(ThreadPoolExecutor(16).map(get,sample))
from collections import Counter
c=Counter(r[4] for r in res if r[4])
rows=[]
for r in res:
    rows.append(r[:7])
    if r[4] and (c[r[4]]>1 or r[3]<20000): (out/f"{r[4]}.jpg").write_bytes(r[7])
json.dump(rows,open(d/'national.json','w'))
print('ok',sum(1 for r in res if r[1]==200),'errors',Counter(str(r[1]) for r in res if r[1]!=200))
for m,n in c.most_common(10): 
    ex=next(r for r in res if r[4]==m); print(m,n,ex[3],ex[2],ex[5])
small=[r for r in res if r[4] and r[3]<20000 and c[r[4]]==1]; print('small unique',len(small)); 
for r in small[:20]: print(r[0],r[3],r[4],r[5])
