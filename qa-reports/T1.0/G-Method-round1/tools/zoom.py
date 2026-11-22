import json, sys, numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, '.')
res = np.load('cache/chips_fixed.npy', allow_pickle=True).item()
key = json.load(open('chips/key.json'))
lines = open('mylabels.csv').read().strip().splitlines()[1:]
tent = sorted(set([l.split(',')[0] for l in lines if l.endswith('?')] + open('recheck.txt').read().split()))
def st(a): return (np.clip(np.nan_to_num(a, nan=0), 0, 1) ** 0.5 * 255).astype('uint8')
W = 24; c = 36; S = 10
font = ImageFont.load_default(size=20)
per = 8
for p0 in range(0, len(tent), per):
    chunk = tent[p0:p0+per]
    im = Image.new('RGB', (2 * (2 * W * S + 30) , 4 * (W * S + 30)), (30, 30, 30)); d = ImageDraw.Draw(im)
    for i, k in enumerate(chunk):
        a = res[key[k]]
        sl = slice(c - W // 2, c + W // 2)
        tc = np.dstack([st(a[(b, 'z')][sl, sl]) for b in ('red', 'green', 'blue')])
        sw = np.dstack([st(a[(b, 'z')][sl, sl]) for b in ('swir16', 'nir', 'red')])
        x0 = (i % 2) * (2 * W * S + 30); y0 = (i // 2) * (W * S + 30)
        for j, arr in enumerate((tc, sw)):
            big = Image.fromarray(arr).resize((W * S, W * S), Image.NEAREST)
            dd = ImageDraw.Draw(big)
            lo = (W // 2 - 1) * S; hi = (W // 2 + 1) * S
            dd.rectangle([lo - 1, lo - 1, hi, hi], outline=(255, 0, 0), width=2)
            im.paste(big, (x0 + j * (W * S + 6), y0 + 26))
        d.text((x0, y0 + 2), k, fill=(255, 255, 255), font=font)
    im.save(f'chips/zoom_{p0 // per:02d}.png')
print(len(tent))
