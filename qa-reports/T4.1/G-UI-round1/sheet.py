"""Side-by-side sheets: PR build | T4.0 mockup | references."""
from PIL import Image, ImageDraw
def sheet(paths, labels, out, w):
    ims = [Image.open(p).convert('RGB') for p in paths]
    ims = [im.resize((w, int(im.height * w / im.width))) for im in ims]
    H = max(i.height for i in ims) + 28
    S = Image.new('RGB', (w * len(ims) + 10 * (len(ims) - 1), H), 'white'); d = ImageDraw.Draw(S)
    for k, (im, lab) in enumerate(zip(ims, labels)):
        x = k * (w + 10); S.paste(im, (x, 28)); d.text((x + 4, 8), lab, fill='black')
    S.save(out, quality=82)
for s in ['nieve', 'cuenca', 'webcams', 'colapsado']:
    sheet([f'shots/app-{s}-1440.png', f'shots/mock-{s}-1440.png'], [f'PR #25 build: {s}', f'T4.0 mockup: {s}'], f'side-{s}-1440.webp', 720)
sheet(['shots/app-nieve-1440.png', 'shots/ref-openpas-viewer-1440.png', 'C:/Users/mario/AppData/Local/Temp/claude/ab72e24bb756155a/3e50bce6-67d4-49bb-b6c2-ef26dfd9322c/scratchpad/design/docs/design/screenshots/reference/cedar-vista-1440.webp'],
      ['PR #25 build (this run)', 'openpas-habitat viewer, guest (this run)', 'cedar-vista viewer (T4.0 reference; local build shows only the sign-in landing)'], 'side-refs-1440.webp', 720)
sheet(['shots/x-fresh-375-run1-12s.png', 'shots/mock-nieve-375.png', 'shots/app-cuenca-375.png', 'shots/mock-cuenca-375.png', 'shots/ref-openpas-viewer-375.png'],
      ['PR fresh load', 'mockup nieve', 'PR cuenca', 'mockup cuenca', 'openpas guest'], 'side-375.webp', 300)
print('ok')
