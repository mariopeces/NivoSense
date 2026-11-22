import sys, hashlib, json, urllib.request, concurrent.futures as cf
urls=[l.strip() for l in open(sys.argv[1])]
out=sys.argv[2]
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"}),timeout=20)
        b=r.read(); return u,{"md5":hashlib.md5(b).hexdigest(),"lm":r.headers.get("Last-Modified"),"date":r.headers.get("Date"),"n":len(b)}
    except Exception as e: return u,{"err":str(e)}
with cf.ThreadPoolExecutor(24) as ex: res=dict(ex.map(get,urls))
json.dump(res,open(out,"w"))
from collections import Counter
c=Counter(v.get("md5") for v in res.values()); print(len(res), c.most_common(5))
