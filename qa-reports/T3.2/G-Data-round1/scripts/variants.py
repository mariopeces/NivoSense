import sys, io, glob, hashlib
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import ingest_webcams as iw
from PIL import Image, ImageEnhance
dl=Path(sys.argv[2])
def resp(body, lm="Sun, 22 Nov 2026 05:53:13 GMT", date="Sun, 22 Nov 2026 05:59:04 GMT"):
    return iw.ImageResponse(200,"image/jpeg",len(body),body,lm,date)
def jpg(img,q=85):
    b=io.BytesIO(); img.convert('RGB').save(b,'JPEG',quality=q); return b.getvalue()
def dist(body):
    h=iw.dhash(body); return min((h^k).bit_count() for k in iw.PLACEHOLDER_DHASH)
cases={}
ph=(dl/'img'/'312.jpg').read_bytes(); P=Image.open(io.BytesIO(ph))
cases['DGT placeholder original']=ph
cases['DGT placeholder 9422B re-encode (cam 1687, live)']=(dl/'nat'/'7292eb9b25718e8a1ca0d1eae101168a.jpg').read_bytes()
cases['placeholder re-encoded q50']=jpg(P,50)
cases['placeholder re-encoded q95']=jpg(P,95)
cases['placeholder resized 853x480']=jpg(P.resize((853,480)))
cases['placeholder resized 320x180']=jpg(P.resize((320,180)))
cases['placeholder resized 1280x720']=jpg(P.resize((1280,720)))
cases['placeholder cropped 10px']=jpg(P.crop((10,10,629,349)))
cases['placeholder brightness 0.8']=jpg(ImageEnhance.Brightness(P).enhance(0.8))
cases['placeholder brightness 1.15']=jpg(ImageEnhance.Brightness(P).enhance(1.15))
cases['placeholder letterboxed 4:3']=jpg((lambda c:(c.paste(P,(0,60)),c)[1])(Image.new('RGB',(639,479),'black')))
for f in ['c69be961d85234d6ee32eb9295f33498','67c456bbc730c610bd317adeb3b1a36a','b56802cbf58a2d1ee6a2faaf76dd429f','677f3bf343289b1be19c9cfa98ca6d1d']:
    p=dl/'nat'/f'{f}.jpg'
    if p.exists(): cases[f'DGT "No video" frame {f[:8]} (live)']=p.read_bytes()
cases['real frame dgt-169624 (live)']=(dl/'img'/'169624.jpg').read_bytes()
for n in ['169623','169625']:
    cases[f'real frame dgt-{n} (live)']=(dl/'img'/f'{n}.jpg').read_bytes()
for name,b in cases.items():
    print(f"{name:55s} problem={iw.image_problem(resp(b),'DGT')!r:70s} dhash_dist={dist(b)}")
# frozen frame: real bytes, Last-Modified 6 days old
cam={'id':'dgt-x','provider':'DGT','thumbnail_url':'u','large_url':'u'}
rec,_=iw.probe_camera_image(dict(cam), lambda u: resp(cases['real frame dgt-169624 (live)'],"Mon, 16 Nov 2026 10:34:54 GMT"))
print('frozen frame (old LM):',rec['status'],rec['captured_at'],rec['problem'])
