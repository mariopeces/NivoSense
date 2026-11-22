import sys,json,urllib.request,hashlib
from concurrent.futures import ThreadPoolExecutor
rows=json.load(open(sys.argv[1]))
live=[r for r in rows if r[1]==200 and r[3]>0 and r[4]!='c92fb6440dc51109074769bcad5c7de9']
def get(r):
    try:
        x=urllib.request.urlopen(urllib.request.Request(r[0],headers={"User-Agent":"qa-probe"}),timeout=20); b=x.read()
        return r,hashlib.md5(b).hexdigest(),x.headers.get('Last-Modified')
    except Exception as e: return r,None,None
res=list(ThreadPoolExecutor(16).map(get,live))
same_bytes_new_lm=[(r[0],r[5],lm) for r,m,lm in res if m==r[4] and lm!=r[5]]
changed=[1 for r,m,lm in res if m and m!=r[4]]
same_all=[1 for r,m,lm in res if m==r[4] and lm==r[5]]
print('live sampled',len(live),'bytes changed',len(changed),'unchanged+same LM',len(same_all),'SAME BYTES, NEW LM',len(same_bytes_new_lm))
for x in same_bytes_new_lm[:15]: print(*x)
