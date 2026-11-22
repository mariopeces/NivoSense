import sys, io, random
sys.path.insert(0, sys.argv[1])
from backend import ingest_webcams as w
from PIL import Image, ImageEnhance, ImageOps
from pathlib import Path
nv=Image.open(Path(sys.argv[2])/"168070.jpg").convert("RGB")
def chk(name, im, q=75):
    b=io.BytesIO(); im.save(b,"JPEG",quality=q); g=Image.open(io.BytesIO(b.getvalue())).convert("L")
    print(f"{name:45s}", w.picture_problem(g,"DGT"))
chk("NoVideo 1280x720 q50", nv.resize((1280,720)), 50)
chk("NoVideo 352x288 q20", nv.resize((352,288)), 20)
random.seed(1)
noisy=nv.copy(); px=noisy.load()
for x in range(noisy.width):
    for y in range(noisy.height):
        n=random.randint(-6,6); r,g,b=px[x,y]; px[x,y]=(max(0,r+n),max(0,g+n),max(0,b+n))
chk("NoVideo + sensor noise +-6", noisy)
chk("NoVideo brightness x6 (grey-ish)", ImageEnhance.Brightness(nv).enhance(6))
chk("NoVideo padded 4:3 into 16:9 grey bars", ImageOps.pad(nv,(853,480),color=(40,40,40)))
for f in ["dgt_night_1310.jpg","dgt_night_169624_0553.jpg"]:
    im=Image.open(Path(sys.argv[1])/"backend/tests/fixtures"/f).convert("RGB")
    for k in (1.0,0.8,0.6,0.4):
        chk(f"{f} brightness x{k}", ImageEnhance.Brightness(im).enhance(k))
